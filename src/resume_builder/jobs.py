"""Orchestrate local job inventory collection and inexpensive prescreening."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import yaml

from job_puller.cli import main as puller_main
from job_puller.config import load_config, resolve_database_path
from job_puller.database import InventoryDatabase

from .atomic import atomic_write_json, atomic_write_text

DEFAULT_CONFIG = Path("job-search/config/search.yml")
DEFAULT_PREFERENCES = Path("job-search/preferences.yml")
DEFAULT_OUTPUT = Path("job-search/shortlist.json")
PRESCREEN_VERSION = 2
TOKEN = re.compile(r"[a-z][a-z0-9+#.]{2,}")
STOPWORDS = {
    "and",
    "are",
    "for",
    "from",
    "have",
    "into",
    "our",
    "that",
    "the",
    "their",
    "this",
    "with",
    "will",
    "you",
    "your",
    "years",
    "work",
    "role",
    "team",
    "using",
    "job",
    "who",
}


def parser() -> argparse.ArgumentParser:
    command_parser = argparse.ArgumentParser(prog="resume-builder jobs")
    command_parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    command_parser.add_argument("--preferences", type=Path, default=DEFAULT_PREFERENCES)
    commands = command_parser.add_subparsers(dest="command", required=True)
    update = commands.add_parser("update", help="Run enabled inventory providers")
    update.add_argument("--provider", action="append")
    commands.add_parser("status", help="Show inventory and shortlist status")
    shortlist = commands.add_parser("shortlist", help="Prescreen new or changed active jobs")
    shortlist.add_argument("--limit", type=int, default=50)
    screen = commands.add_parser("screen", help="Show one job and its prescreen evidence")
    screen.add_argument("job_id")
    return command_parser


def _database(config_path: Path) -> InventoryDatabase:
    config = load_config(config_path)
    database = InventoryDatabase(
        resolve_database_path(config_path, config.database_path), config.raw_payload_retention_days
    )
    database.migrate()
    return database


def _load_preferences(path: Path) -> dict[str, Any]:
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"preferences file not found: {path}") from exc
    except yaml.YAMLError as exc:
        raise ValueError(f"invalid preferences YAML: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("preferences root must be a mapping")
    allowed = {
        "schema_version",
        "accepted_work_modes",
        "desired_title_terms",
        "interest_terms",
        "unwanted_title_terms",
        "excluded_companies",
        "minimum_salary",
        "resume_globs",
    }
    unknown = set(payload) - allowed
    if unknown:
        raise ValueError(f"unknown preference fields: {', '.join(sorted(unknown))}")
    if payload.get("schema_version") != 1:
        raise ValueError("preferences schema_version must be 1")
    list_fields = (
        "accepted_work_modes",
        "desired_title_terms",
        "interest_terms",
        "unwanted_title_terms",
        "excluded_companies",
        "resume_globs",
    )
    for field in list_fields:
        values = payload.get(field, [])
        if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
            raise ValueError(f"{field} must be a list of strings")
    minimum_salary = payload.get("minimum_salary")
    if minimum_salary is not None and not isinstance(minimum_salary, (int, float)):
        raise ValueError("minimum_salary must be a number or null")
    return payload


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _resume_corpus(preferences: dict[str, Any]) -> tuple[str, str]:
    globs = preferences.get("resume_globs") or ["resumes/baselines/*.md", "resumes/tailored/*.md"]
    paths = sorted(
        {path for pattern in globs for path in Path.cwd().glob(pattern) if path.is_file()}
    )
    text = "\n".join(path.read_text(encoding="utf-8") for path in paths)
    return text, _hash_text(text)


def _terms(value: str) -> set[str]:
    return {token for token in TOKEN.findall(value.casefold()) if token not in STOPWORDS}


def _contains_any(value: str, terms: list[str]) -> list[str]:
    normalized = value.casefold()
    return [term for term in terms if term.casefold() in normalized]


def _prescreen(
    job: dict[str, object], preferences: dict[str, Any], resume_terms: set[str]
) -> dict[str, object]:
    title = str(job["title"])
    company = str(job["company"])
    description = str(job["description_text"])
    desired = _contains_any(title, preferences.get("desired_title_terms", []))
    interesting = _contains_any(f"{title}\n{description}", preferences.get("interest_terms", []))
    unwanted = _contains_any(title, preferences.get("unwanted_title_terms", []))
    excluded_company = _contains_any(company, preferences.get("excluded_companies", []))
    accepted_modes = set(preferences.get("accepted_work_modes") or [])
    modes = set(job["work_modes"] if isinstance(job["work_modes"], list) else [])
    mode_match = not accepted_modes or bool(accepted_modes & modes)
    job_terms = _terms(f"{title}\n{description}")
    matched_terms = sorted(job_terms & resume_terms)
    readiness = round(100 * len(matched_terms) / max(1, len(job_terms)))
    salary_min = job.get("salary_min")
    minimum_salary = preferences.get("minimum_salary")
    salary_below = bool(
        minimum_salary is not None
        and isinstance(salary_min, (int, float))
        and salary_min < minimum_salary
    )

    if excluded_company or not mode_match or salary_below:
        category = "SKIP"
    elif unwanted:
        category = "EASY BUT UNWANTED"
    elif not title.strip() or not company.strip() or job.get("description_quality") != "complete":
        category = "NEEDS REVIEW"
    elif desired and readiness >= 35:
        category = "SCREEN NEXT"
    elif desired:
        category = "POSSIBLE FIT"
    elif interesting:
        category = "INTERESTING STRETCH"
    else:
        category = "SKIP"
    return {
        "category": category,
        "interest": {"desired_title_terms": desired, "interest_terms": interesting},
        "constraints": {
            "work_mode_match": mode_match,
            "excluded_company": bool(excluded_company),
            "salary_below_minimum": salary_below,
            "unwanted_title_terms": unwanted,
        },
        "keyword_readiness": {
            "percent": readiness,
            "matched_terms": matched_terms[:30],
            "method": "deterministic posting-to-resume token overlap; not an ATS score or fit decision",
        },
    }


def _shortlist(config_path: Path, preferences_path: Path, limit: int) -> int:
    preferences = _load_preferences(preferences_path)
    resume_text, resume_hash = _resume_corpus(preferences)
    preference_hash = _hash_text(json.dumps(preferences, sort_keys=True))
    output_path = DEFAULT_OUTPUT
    prior: dict[str, dict[str, Any]] = {}
    if output_path.exists():
        payload = json.loads(output_path.read_text(encoding="utf-8"))
        prior = {str(item["id"]): item for item in payload.get("jobs", [])}
    results: list[dict[str, Any]] = []
    reused = 0
    resume_terms = _terms(resume_text)
    for inventory_job in _database(config_path).active_inventory():
        job: dict[str, Any] = inventory_job
        key = _hash_text(
            "|".join(
                (
                    str(PRESCREEN_VERSION),
                    str(job["id"]),
                    str(job["description_hash"]),
                    resume_hash,
                    preference_hash,
                )
            )
        )
        existing = prior.get(str(job["id"]))
        if existing and existing.get("analysis_key") == key:
            results.append(existing)
            reused += 1
            continue
        results.append(
            {**job, "analysis_key": key, "prescreen": _prescreen(job, preferences, resume_terms)}
        )
    priority = {
        "SCREEN NEXT": 0,
        "POSSIBLE FIT": 1,
        "INTERESTING STRETCH": 2,
        "NEEDS REVIEW": 3,
        "EASY BUT UNWANTED": 4,
        "SKIP": 5,
    }
    results.sort(
        key=lambda item: (
            priority[str(item["prescreen"]["category"])],
            -int(item["prescreen"]["keyword_readiness"]["percent"]),
            str(item["title"]),
        )
    )
    payload = {
        "schema_version": 1,
        "prescreen_version": PRESCREEN_VERSION,
        "resume_hash": resume_hash,
        "preference_hash": preference_hash,
        "jobs": results,
    }
    atomic_write_json(output_path, payload)
    lines = ["# Job Shortlist", "", f"Active jobs: {len(results)}; reused: {reused}", ""]
    for item in results[: max(1, limit)]:
        screen = item["prescreen"]
        lines.append(
            f"- **{screen['category']}** — {item['title']} at {item['company']} "
            f"(keyword readiness {screen['keyword_readiness']['percent']}%) — {item['id']}"
        )
    atomic_write_text(output_path.with_suffix(".md"), "\n".join(lines) + "\n")
    print(f"Prescreened {len(results)} active jobs; reused {reused} unchanged analyses.")
    print(f"Shortlist: {output_path.with_suffix('.md')}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    config_path = args.config.expanduser()
    try:
        if args.command == "update":
            forwarded = ["--config", str(config_path), "scrape"]
            for provider in args.provider or []:
                forwarded.extend(("--provider", provider))
            return puller_main(forwarded)
        if args.command == "status":
            stats = _database(config_path).stats()
            for key, value in stats.items():
                print(f"{key.replace('_', ' ').title()}: {value}")
            if DEFAULT_OUTPUT.exists():
                payload = json.loads(DEFAULT_OUTPUT.read_text(encoding="utf-8"))
                print(f"Prescreened Jobs: {len(payload.get('jobs', []))}")
            return 0
        if args.command == "shortlist":
            return _shortlist(config_path, args.preferences.expanduser(), args.limit)
        inventory = {str(job["id"]): job for job in _database(config_path).active_inventory()}
        job = inventory.get(args.job_id)
        if job is None:
            print(f"Active job not found: {args.job_id}", file=sys.stderr)
            return 2
        shortlist = (
            json.loads(DEFAULT_OUTPUT.read_text(encoding="utf-8"))
            if DEFAULT_OUTPUT.exists()
            else {}
        )
        screen = next(
            (item for item in shortlist.get("jobs", []) if item["id"] == args.job_id), None
        )
        print(json.dumps(screen or job, indent=2, sort_keys=True))
        return 0
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"Job inventory error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
