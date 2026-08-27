"""Orchestrate local job inventory collection and inexpensive prescreening."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
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
DEFAULT_REVIEW_OUTPUT = Path("job-search/jobs-review.csv")
PRESCREEN_VERSION = 3
TOKEN = re.compile(r"[a-z][a-z0-9+#.]{2,}")
PHRASE_TOKEN = re.compile(r"[a-z0-9]+")
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
        "excluded_title_terms",
        "senior_title_terms",
        "accepted_senior_role_terms",
        "unwanted_title_terms",
        "excluded_companies",
        "accepted_location_terms",
        "excluded_location_terms",
        "include_unknown_locations",
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
        "excluded_title_terms",
        "senior_title_terms",
        "accepted_senior_role_terms",
        "unwanted_title_terms",
        "excluded_companies",
        "accepted_location_terms",
        "excluded_location_terms",
        "resume_globs",
    )
    for field in list_fields:
        values = payload.get(field, [])
        if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
            raise ValueError(f"{field} must be a list of strings")
    minimum_salary = payload.get("minimum_salary")
    if minimum_salary is not None and not isinstance(minimum_salary, (int, float)):
        raise ValueError("minimum_salary must be a number or null")
    include_unknown = payload.get("include_unknown_locations", True)
    if not isinstance(include_unknown, bool):
        raise ValueError("include_unknown_locations must be true or false")
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


def _contains_phrases(value: str, terms: list[str]) -> list[str]:
    """Match configurable phrases without substring collisions such as US/Australia."""
    normalized = f" {' '.join(PHRASE_TOKEN.findall(value.casefold()))} "
    return [
        term
        for term in terms
        if f" {' '.join(PHRASE_TOKEN.findall(term.casefold()))} " in normalized
    ]


def _format_salary(job: dict[str, object]) -> str:
    salary_min = job.get("salary_min")
    salary_max = job.get("salary_max")
    if not isinstance(salary_min, (int, float)) and not isinstance(salary_max, (int, float)):
        return "Not listed"
    currency = str(job.get("salary_currency") or "")
    prefix = "$" if currency == "USD" else f"{currency} " if currency else ""
    interval = str(job.get("salary_interval") or "").strip()
    suffix = f" {interval}" if interval else ""
    if isinstance(salary_min, (int, float)) and isinstance(salary_max, (int, float)):
        return f"{prefix}{salary_min:.0f}-{prefix}{salary_max:.0f}{suffix}"
    if isinstance(salary_min, (int, float)):
        return f"From {prefix}{salary_min:.0f}{suffix}"
    return f"Up to {prefix}{salary_max:.0f}{suffix}"


def _write_review_csv(results: list[dict[str, Any]], output_path: Path) -> int:
    eligible = [item for item in results if item["prescreen"]["review_eligible"]]
    eligible.sort(
        key=lambda item: (
            str(item["title"]).casefold(),
            -float(item.get("salary_max") or item.get("salary_min") or -1),
            str(item["company"]).casefold(),
        )
    )
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=("title", "company", "salary"))
    writer.writeheader()
    for item in eligible:
        writer.writerow(
            {
                "title": item["title"],
                "company": item["company"] or "Unknown company",
                "salary": _format_salary(item),
            }
        )
    atomic_write_text(output_path, stream.getvalue())
    return len(eligible)


def _prescreen(
    job: dict[str, object], preferences: dict[str, Any], resume_terms: set[str]
) -> dict[str, object]:
    title = str(job["title"])
    company = str(job["company"])
    description = str(job["description_text"])
    desired = _contains_any(title, preferences.get("desired_title_terms", []))
    interesting = _contains_any(f"{title}\n{description}", preferences.get("interest_terms", []))
    excluded_title = _contains_any(title, preferences.get("excluded_title_terms", []))
    seniority = _contains_phrases(title, preferences.get("senior_title_terms", []))
    accepted_senior_role = _contains_phrases(
        title, preferences.get("accepted_senior_role_terms", [])
    )
    seniority_match = not seniority or bool(accepted_senior_role)
    unwanted = _contains_any(title, preferences.get("unwanted_title_terms", []))
    excluded_company = _contains_any(company, preferences.get("excluded_companies", []))
    location = str(job.get("location") or "")
    accepted_location = _contains_phrases(location, preferences.get("accepted_location_terms", []))
    excluded_location = _contains_phrases(location, preferences.get("excluded_location_terms", []))
    location_match = bool(accepted_location) or (
        not excluded_location and preferences.get("include_unknown_locations", True)
    )
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
    complete = bool(
        title.strip() and company.strip() and job.get("description_quality") == "complete"
    )
    review_eligible = bool(
        complete
        and not excluded_title
        and seniority_match
        and not excluded_company
        and mode_match
        and location_match
        and not salary_below
    )

    if (
        excluded_title
        or not seniority_match
        or excluded_company
        or not mode_match
        or not location_match
        or salary_below
    ):
        category = "SKIP"
    elif unwanted:
        category = "EASY BUT UNWANTED"
    elif not complete:
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
        "review_eligible": review_eligible,
        "interest": {"desired_title_terms": desired, "interest_terms": interesting},
        "constraints": {
            "work_mode_match": mode_match,
            "location_match": location_match,
            "accepted_location_terms": accepted_location,
            "excluded_location_terms": excluded_location,
            "excluded_title_terms": excluded_title,
            "seniority_terms": seniority,
            "accepted_senior_role_terms": accepted_senior_role,
            "seniority_match": seniority_match,
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
    review_count = _write_review_csv(results, DEFAULT_REVIEW_OUTPUT)
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
    print(f"Review queue: {DEFAULT_REVIEW_OUTPUT} ({review_count} jobs)")
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
