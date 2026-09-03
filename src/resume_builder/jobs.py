"""Orchestrate local job inventory collection and deterministic review metadata."""

from __future__ import annotations

import argparse
import csv
import fcntl
import hashlib
import io
import json
import re
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from job_puller.cli import main as puller_main
from job_puller.config import load_config, resolve_database_path
from job_puller.database import InventoryDatabase
from job_puller.liveness import verify_job_liveness

from .applications import DEFAULT_ROOT as DEFAULT_APPLICATIONS_ROOT
from .applications import application_job_dispositions
from .atomic import atomic_write_json, atomic_write_text
from .job_screening import ScreeningPacket, build_screening_packet, profile_from_preferences

DEFAULT_CONFIG = Path("job-search/config/search.yml")
DEFAULT_PREFERENCES = Path("job-search/preferences.yml")
DEFAULT_OUTPUT = Path("job-search/shortlist.json")
DEFAULT_REVIEW_OUTPUT = Path("job-search/jobs-review.csv")
DEFAULT_NEW_OUTPUT = Path("job-search/new-jobs.json")
DEFAULT_NEW_REVIEW_OUTPUT = Path("job-search/new-jobs-review.csv")
DEFAULT_LATEST_REFRESH = Path("job-search/latest-refresh.json")
PRESCREEN_VERSION = 6
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
    new = commands.add_parser(
        "new", help="Refresh providers and shortlist only jobs new to the canonical database"
    )
    new.add_argument("--provider", action="append")
    new.add_argument(
        "--retry-failed",
        action="store_true",
        help="Retry only provider types whose latest refresh marked them retryable",
    )
    new.add_argument("--limit", type=int, default=50)
    commands.add_parser("status", help="Show inventory and shortlist status")
    shortlist = commands.add_parser("shortlist", help="Prepare active jobs for review")
    shortlist.add_argument("--limit", type=int, default=50)
    screen = commands.add_parser("screen", help="Show one job and its prescreen evidence")
    screen.add_argument("job_id")
    verify = commands.add_parser("verify", help="Check whether one direct ATS posting is live")
    verify.add_argument("job_id")
    reposts = commands.add_parser("reposts", help="Report conservative possible repost signals")
    reposts.add_argument("--window-days", type=int, default=90)
    reposts.add_argument("--min-span-days", type=int, default=1)
    reposts.add_argument("--aggregator", action="append", default=[])
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
        "job_dispositions",
        "accepted_location_terms",
        "excluded_location_terms",
        "include_unknown_locations",
        "minimum_salary",
        "resume_globs",
        "screening_profile",
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
    dispositions = payload.get("job_dispositions", {})
    if not isinstance(dispositions, dict) or any(
        not isinstance(job_id, str)
        or not isinstance(status, str)
        or status not in {"applied", "not_interested"}
        for job_id, status in dispositions.items()
    ):
        raise ValueError("job_dispositions must map job IDs to applied or not_interested")
    screening_profile = payload.get("screening_profile", {})
    if not isinstance(screening_profile, dict):
        raise ValueError("screening_profile must be a mapping")
    profile_from_preferences(payload)
    return payload


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _prescreen_job_hash(job: dict[str, Any]) -> str:
    """Hash every inventory field that can change a prescreen decision or output."""
    fields = (
        "title",
        "company",
        "location",
        "work_modes",
        "description_hash",
        "description_quality",
        "salary_min",
        "salary_max",
        "salary_currency",
        "salary_interval",
    )
    return _hash_text(json.dumps({field: job.get(field) for field in fields}, sort_keys=True))


def _resume_paths(preferences: dict[str, Any]) -> list[Path]:
    globs = preferences.get("resume_globs") or ["resumes/baselines/*.md", "resumes/tailored/*.md"]
    return sorted(
        {path for pattern in globs for path in Path.cwd().glob(pattern) if path.is_file()}
    )


def _resume_corpus(preferences: dict[str, Any]) -> tuple[str, str]:
    paths = _resume_paths(preferences)
    text = "\n".join(path.read_text(encoding="utf-8") for path in paths)
    return text, _hash_text(text)


def _terms(value: str) -> set[str]:
    return {token for token in TOKEN.findall(value.casefold()) if token not in STOPWORDS}


def _contains_any(value: str, terms: list[str]) -> list[str]:
    normalized = value.casefold()
    return [term for term in terms if term.casefold() in normalized]


def _contains_bounded(value: str, terms: list[str]) -> list[str]:
    """Match terms without collisions such as PPLIED/Applied or US/Australia."""
    return [
        term
        for term in terms
        if term.strip()
        and re.search(
            rf"(?<![a-z0-9]){re.escape(term.strip().casefold())}(?![a-z0-9])",
            value.casefold(),
        )
    ]


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


def _with_application_dispositions(
    preferences: dict[str, Any], applications_root: Path = DEFAULT_APPLICATIONS_ROOT
) -> dict[str, Any]:
    """Overlay durable application records without removing legacy preferences."""
    dispositions = dict(preferences.get("job_dispositions", {}))
    dispositions.update(application_job_dispositions(applications_root))
    return {**preferences, "job_dispositions": dispositions}


def _write_review_csv(results: list[dict[str, Any]], output_path: Path) -> int:
    eligible = [item for item in results if item["prescreen"]["review_eligible"]]
    eligible.sort(key=_newest_first_key)
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


def _recency_timestamp(job: dict[str, Any]) -> float:
    for field in ("posted_at", "first_seen_at", "last_seen_at"):
        value = job.get(field)
        if not isinstance(value, str) or not value:
            continue
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.timestamp()
    return 0.0


def _newest_first_key(job: dict[str, Any]) -> tuple[float, str, str, str]:
    return (
        -_recency_timestamp(job),
        str(job.get("title") or "").casefold(),
        str(job.get("company") or "").casefold(),
        str(job.get("id") or ""),
    )


def _prescreen(
    job: dict[str, object], preferences: dict[str, Any], resume_terms: set[str]
) -> dict[str, object]:
    title = str(job["title"])
    company = str(job["company"])
    description = str(job["description_text"])
    desired = _contains_any(title, preferences.get("desired_title_terms", []))
    interesting = _contains_any(f"{title}\n{description}", preferences.get("interest_terms", []))
    excluded_title = _contains_bounded(title, preferences.get("excluded_title_terms", []))
    seniority = _contains_phrases(title, preferences.get("senior_title_terms", []))
    accepted_senior_role = _contains_phrases(
        title, preferences.get("accepted_senior_role_terms", [])
    )
    seniority_match = not seniority or bool(accepted_senior_role)
    unwanted = _contains_bounded(title, preferences.get("unwanted_title_terms", []))
    excluded_company = _contains_bounded(company, preferences.get("excluded_companies", []))
    dispositions = preferences.get("job_dispositions", {})
    disposition = (
        dispositions.get(str(job.get("id") or "")) if isinstance(dispositions, dict) else None
    )
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
    screening_profile = preferences.get("screening_profile") or {}
    mode_required = screening_profile.get("work_mode_strength", "required") == "required"
    location_required = screening_profile.get("location_strength", "required") == "required"
    salary_required = screening_profile.get("minimum_salary_strength", "required") == "required"
    remote_only = "remote" in modes and not {"hybrid", "onsite"} & modes
    if remote_only and "remote_location_terms" in screening_profile:
        # Inventory location often names an office rather than a remote-work
        # residency restriction. Preserve it for semantic review, but do not
        # turn a non-match into a deterministic rejection.
        hard_location_match = True
    else:
        hard_location_match = location_match or not location_required
    hard_mode_match = mode_match or not mode_required
    hard_salary_below = salary_below and salary_required
    complete = bool(
        title.strip() and company.strip() and job.get("description_quality") == "complete"
    )
    hard_conflicts = []
    if excluded_title:
        hard_conflicts.append("excluded_title")
    if not seniority_match:
        hard_conflicts.append("seniority")
    if excluded_company:
        hard_conflicts.append("excluded_company")
    if not hard_mode_match:
        hard_conflicts.append("work_mode")
    if not hard_location_match:
        hard_conflicts.append("location")
    if hard_salary_below:
        hard_conflicts.append("salary")

    if disposition:
        queue_state = str(disposition)
    elif not complete:
        queue_state = "needs_description"
    elif hard_conflicts:
        queue_state = "hard_conflict"
    else:
        queue_state = "ready"
    return {
        "queue_state": queue_state,
        # Kept for artifact compatibility. Relevance and hard-warning rules no
        # longer suppress jobs; only a durable disposition removes one.
        "review_eligible": not bool(disposition),
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
            "disposition": disposition,
            "salary_below_minimum": salary_below,
            "unwanted_title_terms": unwanted,
            "hard_conflicts": hard_conflicts,
        },
        "keyword_readiness": {
            "percent": readiness,
            "matched_terms": matched_terms[:30],
            "method": "deterministic posting-to-resume token overlap; not an ATS score or fit decision",
        },
    }


def _shortlist(
    config_path: Path,
    preferences_path: Path,
    limit: int,
    *,
    included_job_ids: set[str] | None = None,
    output_path: Path = DEFAULT_OUTPUT,
    review_output_path: Path = DEFAULT_REVIEW_OUTPUT,
    heading: str = "Job Shortlist",
) -> int:
    preferences = _load_preferences(preferences_path)
    preferences = _with_application_dispositions(preferences)
    resume_text, resume_hash = _resume_corpus(preferences)
    preference_hash = _hash_text(json.dumps(preferences, sort_keys=True))
    prior: dict[str, dict[str, Any]] = {}
    if output_path.exists():
        payload = json.loads(output_path.read_text(encoding="utf-8"))
        prior = {str(item["id"]): item for item in payload.get("jobs", [])}
    results: list[dict[str, Any]] = []
    reused = 0
    resume_terms = _terms(resume_text)
    for inventory_job in _database(config_path).active_inventory():
        job: dict[str, Any] = inventory_job
        if included_job_ids is not None and str(job["id"]) not in included_job_ids:
            continue
        key = _hash_text(
            "|".join(
                (
                    str(PRESCREEN_VERSION),
                    str(job["id"]),
                    _prescreen_job_hash(job),
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
    results.sort(key=_newest_first_key)
    payload = {
        "schema_version": 1,
        "prescreen_version": PRESCREEN_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "resume_hash": resume_hash,
        "preference_hash": preference_hash,
        "jobs": results,
    }
    atomic_write_json(output_path, payload)
    review_count = _write_review_csv(results, review_output_path)
    visible_results = [
        item for item in results if not item["prescreen"]["constraints"].get("disposition")
    ]
    count_label = "Active jobs" if included_job_ids is None else "Jobs in this refresh"
    lines = [f"# {heading}", "", f"{count_label}: {len(results)}; reused: {reused}", ""]
    for item in visible_results[: max(1, limit)]:
        screen = item["prescreen"]
        state = str(screen["queue_state"]).replace("_", " ").upper()
        lines.append(f"- **{state}** — {item['title']} at {item['company']} — {item['id']}")
    atomic_write_text(output_path.with_suffix(".md"), "\n".join(lines) + "\n")
    print(f"Prepared {len(results)} jobs; reused {reused} unchanged analyses.")
    print(f"Newest jobs: {output_path.with_suffix('.md')}")
    print(f"Review queue: {review_output_path} ({review_count} jobs)")
    return 0


def get_job_screening_packet(
    job_id: str,
    *,
    config_path: Path = DEFAULT_CONFIG,
    preferences_path: Path = DEFAULT_PREFERENCES,
) -> ScreeningPacket:
    """Build one bounded, read-only packet from authoritative local inputs."""
    preferences = _with_application_dispositions(_load_preferences(preferences_path))
    inventory = {str(item["id"]): item for item in _database(config_path).active_inventory()}
    job = inventory.get(job_id)
    if job is None:
        raise ValueError(f"active job not found: {job_id}")
    resume_text, _ = _resume_corpus(preferences)
    prescreen = _prescreen(job, preferences, _terms(resume_text))
    return build_screening_packet(job, preferences, prescreen)


def _provider_args(config_path: Path, providers: list[str] | None) -> list[str]:
    forwarded = ["--config", str(config_path), "scrape"]
    for provider in providers or []:
        forwarded.extend(("--provider", provider))
    return forwarded


def _recover_pending_new_job_ids(database: InventoryDatabase) -> set[str]:
    if not DEFAULT_LATEST_REFRESH.exists():
        return set()
    prior = json.loads(DEFAULT_LATEST_REFRESH.read_text(encoding="utf-8"))
    if prior.get("status") == "processing":
        values = prior.get("new_to_database_job_ids", [])
        return {str(value) for value in values if isinstance(value, str)}
    if prior.get("status") != "in_progress":
        return set()
    started_at = prior.get("started_at")
    if not isinstance(started_at, str):
        return set()
    return database.active_job_ids_first_seen_since(datetime.fromisoformat(started_at))


def _new_jobs(
    config_path: Path,
    preferences_path: Path,
    limit: int,
    providers: list[str] | None,
    *,
    retry_failed: bool = False,
) -> int:
    lock_path = DEFAULT_LATEST_REFRESH.with_suffix(".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as stream:
        try:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError("another job discovery scan is already running") from exc
        try:
            return _new_jobs_unlocked(
                config_path,
                preferences_path,
                limit,
                providers,
                retry_failed=retry_failed,
            )
        finally:
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def _new_jobs_unlocked(
    config_path: Path,
    preferences_path: Path,
    limit: int,
    providers: list[str] | None,
    *,
    retry_failed: bool = False,
) -> int:
    database = _database(config_path)
    if retry_failed:
        if providers:
            raise ValueError("--retry-failed cannot be combined with --provider")
        if not DEFAULT_LATEST_REFRESH.exists():
            raise ValueError("no prior refresh exists to retry")
        prior = json.loads(DEFAULT_LATEST_REFRESH.read_text(encoding="utf-8"))
        providers = sorted(
            {
                str(run["provider"])
                for run in prior.get("provider_runs", [])
                if isinstance(run, dict)
                and run.get("retryable") is True
                and isinstance(run.get("provider"), str)
            }
        )
        if not providers:
            raise ValueError("the latest refresh has no retryable provider failures")
    recovered_job_ids = _recover_pending_new_job_ids(database)
    before_ids = database.job_ids()
    started_at = datetime.now(UTC)
    selected_providers = sorted(set(providers or []))
    manifest: dict[str, object] = {
        "schema_version": 1,
        "status": "in_progress",
        "started_at": started_at.isoformat(),
        "completed_at": None,
        "provider_selection": selected_providers or ["all_enabled"],
        "new_to_database_job_ids": [],
    }
    atomic_write_json(DEFAULT_LATEST_REFRESH, manifest)

    refresh_status = puller_main(_provider_args(config_path, providers))
    after_ids = database.job_ids()
    active_ids = {str(job["id"]) for job in database.active_inventory()}
    provider_runs = database.scrape_runs_since(started_at)
    new_job_ids = sorted((((after_ids - before_ids) & active_ids) | recovered_job_ids) & active_ids)
    has_successful_provider = any(
        run.get("outcome") in {"healthy", "healthy-empty", "capped"}
        or (run.get("success") and not run.get("suspicious_empty"))
        for run in provider_runs
    )
    outcome = (
        "complete"
        if refresh_status == 0
        else "partial"
        if has_successful_provider or new_job_ids
        else "failed"
    )
    manifest.update(
        {
            "status": "processing",
            "completed_at": datetime.now(UTC).isoformat(),
            "refresh_exit_code": refresh_status,
            "provider_runs": provider_runs,
            "recovered_job_ids": sorted(recovered_job_ids),
            "new_to_database_job_ids": new_job_ids,
        }
    )
    atomic_write_json(DEFAULT_LATEST_REFRESH, manifest)

    heading = {
        "complete": "New Jobs",
        "partial": "New Jobs — Partial Refresh",
        "failed": "New Jobs — Refresh Failed",
    }[outcome]
    _shortlist(
        config_path,
        preferences_path,
        limit,
        included_job_ids=set(new_job_ids),
        output_path=DEFAULT_NEW_OUTPUT,
        review_output_path=DEFAULT_NEW_REVIEW_OUTPUT,
        heading=heading,
    )
    manifest["status"] = outcome
    atomic_write_json(DEFAULT_LATEST_REFRESH, manifest)
    if outcome == "complete":
        print(f"New to database: {len(new_job_ids)} job(s).")
    elif outcome == "partial":
        print(
            f"Partial refresh: {len(new_job_ids)} new job(s) were found, but provider coverage "
            "was incomplete.",
            file=sys.stderr,
        )
    else:
        print("Refresh failed; no complete new-job result is available.", file=sys.stderr)
    return refresh_status


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    config_path = args.config.expanduser()
    try:
        if args.command == "update":
            return puller_main(_provider_args(config_path, args.provider))
        if args.command == "new":
            return _new_jobs(
                config_path,
                args.preferences.expanduser(),
                args.limit,
                args.provider,
                retry_failed=args.retry_failed,
            )
        if args.command == "status":
            database = _database(config_path)
            stats = database.stats()
            for key, value in stats.items():
                print(f"{key.replace('_', ' ').title()}: {value}")
            health = database.source_health()
            if health:
                print("Source Health:")
                for source in health:
                    detail = f"; {source['error_category']}" if source["error_category"] else ""
                    print(
                        f"  {source['source_key']}: {source['outcome']} "
                        f"(problem streak {source['problem_streak']}{detail})"
                    )
            if DEFAULT_OUTPUT.exists():
                payload = json.loads(DEFAULT_OUTPUT.read_text(encoding="utf-8"))
                print(f"Prepared Jobs: {len(payload.get('jobs', []))}")
            return 0
        if args.command == "shortlist":
            return _shortlist(config_path, args.preferences.expanduser(), args.limit)
        if args.command == "reposts":
            candidates = _database(config_path).possible_reposts(
                window_days=args.window_days,
                min_span_days=args.min_span_days,
                aggregator_companies=set(args.aggregator),
            )
            print(
                json.dumps(
                    {
                        "possible_reposts": candidates,
                        "detector": {
                            "window_days": args.window_days,
                            "min_span_days": args.min_span_days,
                            "aggregator_companies": sorted(set(args.aggregator)),
                        },
                        "method": (
                            "Advisory same-employer and exact title-token identity; concurrent "
                            "postings and shared provider identities are excluded."
                        ),
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
            return 0
        config = load_config(config_path)
        inventory = {str(job["id"]): job for job in _database(config_path).active_inventory()}
        job = inventory.get(args.job_id)
        if job is None:
            print(f"Active job not found: {args.job_id}", file=sys.stderr)
            return 2
        liveness = verify_job_liveness(job, config.request_timeout_seconds)
        if args.command == "verify":
            print(json.dumps(liveness, indent=2, sort_keys=True))
            return 3 if liveness["status"] == "closed" else 0
        shortlist = (
            json.loads(DEFAULT_OUTPUT.read_text(encoding="utf-8"))
            if DEFAULT_OUTPUT.exists()
            else {}
        )
        screen = next(
            (item for item in shortlist.get("jobs", []) if item["id"] == args.job_id), None
        )
        output = dict(screen or job)
        output["liveness"] = liveness
        print(json.dumps(output, indent=2, sort_keys=True))
        return 0
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"Job inventory error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
