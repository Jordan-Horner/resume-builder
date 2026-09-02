"""Record private application history, outcomes, and submitted answers."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from collections.abc import Sequence
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import yaml

from job_puller.config import load_config, resolve_database_path
from job_puller.database import InventoryDatabase

from .atomic import atomic_write_json
from .evidence import load_fact_evidence

SCHEMA_VERSION = 1
DEFAULT_ROOT = Path("applications")
RATE_SAMPLE_FLOOR = 10
STATUSES = {
    "applied",
    "recruiter_contact",
    "screen_scheduled",
    "interview",
    "assessment",
    "final_interview",
    "offer",
    "hired",
    "rejected",
    "withdrawn",
    "no_response",
}
TERMINAL_STATUSES = {"hired", "rejected", "withdrawn", "no_response"}
INTERVIEW_STATUSES = {"interview", "assessment", "final_interview", "offer", "hired"}
OFFER_STATUSES = {"offer", "hired"}
ANSWER_STATES = {"draft", "submitted"}
TOKEN = re.compile(r"[a-z0-9+#.]+")


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _date(value: str | None) -> str:
    candidate = value or date.today().isoformat()
    try:
        return date.fromisoformat(candidate).isoformat()
    except ValueError as exc:
        raise ValueError(f"invalid date: {candidate}") from exc


def _digest(*values: str, length: int = 16) -> str:
    payload = "\x1f".join(values).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:length]


def _application_id(company: str, role: str, applied_on: str, job_id: str | None) -> str:
    return f"APP-{applied_on.replace('-', '')}-{_digest(company.casefold(), role.casefold(), job_id or '')[:10]}"


def _artifact(path: Path | None, workspace: Path) -> dict[str, str] | None:
    if path is None:
        return None
    resolved = path.expanduser().resolve()
    try:
        relative = resolved.relative_to(workspace.resolve())
    except ValueError as exc:
        raise ValueError(
            f"application artifact must be inside the private workspace: {resolved}"
        ) from exc
    if not resolved.is_file():
        raise ValueError(f"application artifact does not exist: {resolved}")
    return {
        "path": relative.as_posix(),
        "sha256": hashlib.sha256(resolved.read_bytes()).hexdigest(),
    }


def _optional(value: str | None) -> str | None:
    cleaned = value.strip() if isinstance(value, str) else ""
    return cleaned or None


def _screen_snapshot(workspace: Path, job_id: str | None) -> dict[str, Any] | None:
    if not job_id:
        return None
    candidates: list[tuple[datetime, dict[str, Any]]] = []
    for relative in (Path("job-search/new-jobs.json"), Path("job-search/shortlist.json")):
        path = workspace / relative
        if not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid prescreen snapshot: {path}: {exc}") from exc
        if not isinstance(payload, dict):
            continue
        for item in payload.get("jobs", []):
            if not isinstance(item, dict) or str(item.get("id")) != job_id:
                continue
            prescreen = item.get("prescreen")
            if not isinstance(prescreen, dict):
                continue
            generated_at = payload.get("generated_at")
            try:
                freshness = (
                    datetime.fromisoformat(generated_at)
                    if isinstance(generated_at, str)
                    else datetime.fromtimestamp(path.stat().st_mtime, UTC)
                )
            except (OSError, ValueError):
                freshness = datetime.min.replace(tzinfo=UTC)
            if freshness.tzinfo is None:
                freshness = freshness.replace(tzinfo=UTC)
            candidates.append(
                (
                    freshness,
                    {
                        "path": relative.as_posix(),
                        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                        "prescreen_version": payload.get("prescreen_version"),
                        "analysis_key": item.get("analysis_key"),
                        "category": prescreen.get("category"),
                    },
                )
            )
    return max(candidates, key=lambda candidate: candidate[0])[1] if candidates else None


def _event(
    application_id: str,
    status: str,
    effective_on: str,
    *,
    stage: str | None = None,
    feedback: str | None = None,
    note: str | None = None,
    supersedes: str | None = None,
    event_type: str | None = None,
    occurred_at: str | None = None,
    source_type: str | None = None,
    source_reference: str | None = None,
    confidence: float | None = None,
    match_confidence: float | None = None,
    classifier_version: str | None = None,
    automation_policy: str | None = None,
) -> dict[str, Any]:
    if status not in STATUSES:
        raise ValueError(f"invalid application status: {status}")
    parts = (
        application_id,
        status,
        effective_on,
        stage or "",
        feedback or "",
        note or "",
        supersedes or "",
        event_type or "",
        occurred_at or "",
        source_type or "",
        source_reference or "",
        str(confidence) if confidence is not None else "",
        str(match_confidence) if match_confidence is not None else "",
        classifier_version or "",
        automation_policy or "",
    )
    event: dict[str, Any] = {
        "id": f"EVT-{_digest(*parts)}",
        "status": status,
        "effective_on": effective_on,
        "recorded_at": _now(),
        "stage": _optional(stage),
        "feedback_verbatim": _optional(feedback),
        "note": _optional(note),
        "supersedes": _optional(supersedes),
    }
    if event_type:
        event["event_type"] = event_type.strip()
    if occurred_at:
        parsed = datetime.fromisoformat(occurred_at)
        if parsed.tzinfo is None:
            raise ValueError("application event occurred_at must include a timezone")
        event["occurred_at"] = parsed.isoformat()
    if source_type:
        event["source"] = {
            "type": source_type.strip(),
            "reference": _optional(source_reference),
        }
    if confidence is not None or classifier_version or automation_policy:
        if confidence is None or not 0 <= confidence <= 1:
            raise ValueError("automated application event confidence must be between 0 and 1")
        if match_confidence is not None and not 0 <= match_confidence <= 1:
            raise ValueError("application match confidence must be between 0 and 1")
        event["automation"] = {
            "confidence": confidence,
            "match_confidence": match_confidence,
            "classifier_version": _optional(classifier_version),
            "policy": _optional(automation_policy),
        }
    return event


def validate_record(record: dict[str, Any]) -> None:
    if set(record) != {"schema_version", "application", "events", "answers"}:
        raise ValueError("application record has invalid top-level fields")
    if record.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"application schema_version must be {SCHEMA_VERSION}")
    application = record.get("application")
    if not isinstance(application, dict):
        raise ValueError("application must be an object")
    required = {"id", "company", "role", "applied_on", "created_at"}
    if any(
        not isinstance(application.get(field), str) or not application[field].strip()
        for field in required
    ):
        raise ValueError("application identity fields must be non-empty strings")
    _date(application["applied_on"])
    events = record.get("events")
    answers = record.get("answers")
    if not isinstance(events, list) or not events:
        raise ValueError("application events must be a non-empty list")
    if not isinstance(answers, list):
        raise ValueError("application answers must be a list")
    event_ids: set[str] = set()
    for event in events:
        if not isinstance(event, dict) or event.get("status") not in STATUSES:
            raise ValueError("application event is invalid")
        if not isinstance(event.get("id"), str) or event["id"] in event_ids:
            raise ValueError("application event IDs must be unique strings")
        event_ids.add(event["id"])
        _date(event.get("effective_on"))
        supersedes = event.get("supersedes")
        if supersedes is not None and supersedes not in event_ids:
            raise ValueError("an event may supersede only an earlier event")
        occurred_at = event.get("occurred_at")
        if occurred_at is not None:
            if not isinstance(occurred_at, str):
                raise ValueError("application event occurred_at must be a string")
            parsed = datetime.fromisoformat(occurred_at)
            if parsed.tzinfo is None:
                raise ValueError("application event occurred_at must include a timezone")
        source = event.get("source")
        if source is not None and (
            not isinstance(source, dict)
            or not isinstance(source.get("type"), str)
            or not source["type"].strip()
        ):
            raise ValueError("application event source is invalid")
        automation = event.get("automation")
        if automation is not None and (
            not isinstance(automation, dict)
            or not isinstance(automation.get("confidence"), int | float)
            or not 0 <= automation["confidence"] <= 1
        ):
            raise ValueError("application event automation metadata is invalid")
        if automation is not None and automation.get("match_confidence") is not None and (
            not isinstance(automation["match_confidence"], int | float)
            or not 0 <= automation["match_confidence"] <= 1
        ):
            raise ValueError("application event match confidence is invalid")
    answer_ids: set[str] = set()
    for answer in answers:
        if not isinstance(answer, dict) or answer.get("state") not in ANSWER_STATES:
            raise ValueError("application answer is invalid")
        if not isinstance(answer.get("id"), str) or answer["id"] in answer_ids:
            raise ValueError("application answer IDs must be unique strings")
        if not isinstance(answer.get("question"), str) or not answer["question"].strip():
            raise ValueError("application answer question must be present")
        if not isinstance(answer.get("answer"), str) or not answer["answer"].strip():
            raise ValueError("application answer text must be present")
        evidence = answer.get("evidence")
        if not isinstance(evidence, list) or any(not isinstance(item, str) for item in evidence):
            raise ValueError("application answer evidence must be a list of fact IDs")
        answer_ids.add(answer["id"])


def load_record(path: Path) -> dict[str, Any]:
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"application not found: {path.stem}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid application JSON at {path}: {exc}") from exc
    if not isinstance(record, dict):
        raise ValueError(f"application record must be an object: {path}")
    validate_record(record)
    if path.stem != record["application"]["id"]:
        raise ValueError("application filename must match its stable ID")
    return record


def iter_records(root: Path = DEFAULT_ROOT) -> list[tuple[Path, dict[str, Any]]]:
    if not root.exists():
        return []
    records = [(path, load_record(path)) for path in sorted(root.glob("APP-*.json"))]
    return records


def applied_job_ids(root: Path = DEFAULT_ROOT) -> set[str]:
    values: set[str] = set()
    for _, record in iter_records(root):
        job_id = record["application"].get("job_id")
        if isinstance(job_id, str) and job_id.strip():
            values.add(job_id)
    return values


def application_job_dispositions(root: Path = DEFAULT_ROOT) -> dict[str, str]:
    """Return each linked inventory job's current application status."""
    dispositions: dict[str, str] = {}
    for _, record in iter_records(root):
        job_id = record["application"].get("job_id")
        if isinstance(job_id, str) and job_id.strip():
            dispositions[job_id] = str(_outcome(record)["current_status"])
    return dispositions


def validate_history(root: Path = DEFAULT_ROOT) -> dict[str, Any]:
    """Validate every application file and its current career-fact citations."""
    errors: list[str] = []
    records: list[dict[str, Any]] = []
    if root.exists():
        for path in sorted(root.glob("APP-*.json")):
            try:
                records.append(load_record(path))
            except (OSError, ValueError) as exc:
                errors.append(f"{path.name}: {exc}")
    cited = {
        fact_id
        for record in records
        for answer in record["answers"]
        for fact_id in answer["evidence"]
    }
    if cited:
        try:
            facts = load_fact_evidence(root.parent / "vault")
        except (OSError, ValueError) as exc:
            errors.append(f"career-fact validation failed: {exc}")
        else:
            for fact_id in sorted(cited - set(facts)):
                errors.append(f"unknown cited career fact: {fact_id}")
            for fact_id in sorted(cited & set(facts)):
                if facts[fact_id].status == "needs-review":
                    errors.append(f"cited career fact now needs review: {fact_id}")
    return {
        "valid": not errors,
        "schema_version": SCHEMA_VERSION,
        "applications": len(records),
        "events": sum(len(record["events"]) for record in records),
        "answers": sum(len(record["answers"]) for record in records),
        "errors": errors,
    }


def build_record(args: argparse.Namespace, workspace: Path) -> dict[str, Any]:
    company = args.company.strip()
    role = args.role.strip()
    if not company or not role:
        raise ValueError("company and role must be non-empty")
    applied_on = _date(args.on)
    application_id = _application_id(company, role, applied_on, args.job_id)
    screen_snapshot = _screen_snapshot(workspace, args.job_id)
    application = {
        "id": application_id,
        "company": company,
        "role": role,
        "applied_on": applied_on,
        "job_id": _optional(args.job_id),
        "application_url": _optional(args.url),
        "role_family": _optional(args.role_family),
        "screen_category": _optional(args.screen_category)
        or (screen_snapshot.get("category") if screen_snapshot else None),
        "screen_snapshot": screen_snapshot,
        "match_classification": _optional(args.match_classification),
        "match_report": _artifact(getattr(args, "match_report", None), workspace),
        "target": _artifact(args.target, workspace),
        "resume": _artifact(args.resume, workspace),
        "created_at": _now(),
    }
    record = {
        "schema_version": SCHEMA_VERSION,
        "application": application,
        "events": [_event(application_id, "applied", applied_on, note=args.note)],
        "answers": [],
    }
    validate_record(record)
    return record


def build_automated_record(
    *,
    company: str,
    role: str,
    applied_on: str,
    occurred_at: str,
    source_reference: str,
    confidence: float,
    classifier_version: str,
    automation_policy: str,
    workspace: Path,
    job_id: str | None = None,
    application_url: str | None = None,
    requisition_id: str | None = None,
) -> dict[str, Any]:
    """Build an email-confirmed application without retaining message content."""
    args = argparse.Namespace(
        company=company,
        role=role,
        on=applied_on,
        job_id=job_id,
        url=application_url,
        role_family=None,
        screen_category=None,
        match_classification=None,
        target=None,
        resume=None,
        note=None,
    )
    record = build_record(args, workspace)
    record["application"]["requisition_id"] = _optional(requisition_id)
    application_id = record["application"]["id"]
    record["events"] = [
        _event(
            application_id,
            "applied",
            applied_on,
            event_type="application_confirmed",
            occurred_at=occurred_at,
            source_type="gmail-automation",
            source_reference=source_reference,
            confidence=confidence,
            classifier_version=classifier_version,
            automation_policy=automation_policy,
        )
    ]
    validate_record(record)
    return record


def _write_or_preview(root: Path, record: dict[str, Any], *, apply: bool) -> dict[str, Any]:
    path = root / f"{record['application']['id']}.json"
    if apply:
        if path.exists():
            existing = load_record(path)
            comparable_existing = json.loads(json.dumps(existing))
            comparable_new = json.loads(json.dumps(record))
            comparable_existing["application"]["created_at"] = ""
            comparable_new["application"]["created_at"] = ""
            comparable_existing["events"][0]["recorded_at"] = ""
            comparable_new["events"][0]["recorded_at"] = ""
            if comparable_existing != comparable_new:
                raise ValueError(f"application already exists with different content: {path.stem}")
        else:
            atomic_write_json(path, record)
    return {"valid": True, "applied": apply, "path": str(path), "record": record}


def append_event(
    root: Path,
    application_id: str,
    status: str,
    effective_on: str,
    *,
    stage: str | None,
    feedback: str | None,
    note: str | None,
    supersedes: str | None,
    apply: bool,
    event_type: str | None = None,
    occurred_at: str | None = None,
    source_type: str | None = None,
    source_reference: str | None = None,
    confidence: float | None = None,
    match_confidence: float | None = None,
    classifier_version: str | None = None,
    automation_policy: str | None = None,
) -> dict[str, Any]:
    path = root / f"{application_id}.json"
    record = load_record(path)
    event = _event(
        application_id,
        status,
        _date(effective_on),
        stage=stage,
        feedback=feedback,
        note=note,
        supersedes=supersedes,
        event_type=event_type,
        occurred_at=occurred_at,
        source_type=source_type,
        source_reference=source_reference,
        confidence=confidence,
        match_confidence=match_confidence,
        classifier_version=classifier_version,
        automation_policy=automation_policy,
    )
    if supersedes and supersedes not in {item["id"] for item in record["events"]}:
        raise ValueError(f"superseded event not found: {supersedes}")
    if event["id"] not in {item["id"] for item in record["events"]}:
        record["events"].append(event)
    validate_record(record)
    if apply:
        atomic_write_json(path, record)
    return {"valid": True, "applied": apply, "path": str(path), "event": event}


def append_answer(
    root: Path,
    application_id: str,
    question: str,
    answer_text: str,
    *,
    state: str,
    evidence: list[str],
    apply: bool,
) -> dict[str, Any]:
    if state not in ANSWER_STATES:
        raise ValueError(f"answer state must be one of: {', '.join(sorted(ANSWER_STATES))}")
    question = question.strip()
    answer_text = answer_text.strip()
    if not question or not answer_text:
        raise ValueError("question and answer must be non-empty")
    unique_evidence = sorted(set(evidence))
    if unique_evidence:
        facts = load_fact_evidence(root.parent / "vault")
        unknown = sorted(set(unique_evidence) - set(facts))
        if unknown:
            raise ValueError(f"application answer cites unknown career facts: {', '.join(unknown)}")
        unresolved = sorted(
            fact_id for fact_id in unique_evidence if facts[fact_id].status == "needs-review"
        )
        if unresolved:
            raise ValueError(
                "application answer cites needs-review career facts: " + ", ".join(unresolved)
            )
    path = root / f"{application_id}.json"
    record = load_record(path)
    answer_id = f"ANS-{_digest(application_id, question.casefold(), answer_text, state)}"
    answer = {
        "id": answer_id,
        "question": question,
        "answer": answer_text,
        "state": state,
        "evidence": unique_evidence,
        "recorded_at": _now(),
    }
    if answer_id not in {item["id"] for item in record["answers"]}:
        record["answers"].append(answer)
    validate_record(record)
    if apply:
        atomic_write_json(path, record)
    return {"valid": True, "applied": apply, "path": str(path), "answer": answer}


def _outcome(record: dict[str, Any]) -> dict[str, Any]:
    superseded = {
        event["supersedes"]
        for event in record["events"]
        if isinstance(event.get("supersedes"), str)
    }
    active_events = [event for event in record["events"] if event["id"] not in superseded]
    statuses = [event["status"] for event in active_events]
    current_event = max(
        enumerate(active_events),
        key=lambda item: (
            item[1]["effective_on"],
            item[1].get("recorded_at") or "",
            item[0],
        ),
    )[1]
    current = current_event["status"]
    return {
        "interview": bool(set(statuses) & INTERVIEW_STATUSES),
        "offer": bool(set(statuses) & OFFER_STATUSES),
        "pending": current not in TERMINAL_STATUSES,
        "current_status": current,
    }


def current_application_status(record: dict[str, Any]) -> str:
    """Return the effective current status from append-only application history."""
    return str(_outcome(record)["current_status"])


def _group_summary(records: list[dict[str, Any]], field: str) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        label = record["application"].get(field)
        if field == "resume" and isinstance(label, dict):
            label = label.get("path")
        groups[str(label or "Unspecified")].append(record)
    rows: list[dict[str, Any]] = []
    for label, group in sorted(groups.items()):
        outcomes = [_outcome(record) for record in group]
        applications = len(group)
        interviews = sum(item["interview"] for item in outcomes)
        offers = sum(item["offer"] for item in outcomes)
        pending = sum(item["pending"] for item in outcomes)
        concluded = applications - pending
        concluded_outcomes = [item for item in outcomes if not item["pending"]]
        concluded_interviews = sum(item["interview"] for item in concluded_outcomes)
        concluded_offers = sum(item["offer"] for item in concluded_outcomes)
        rows.append(
            {
                "group": label,
                "applications": applications,
                "interviews": interviews,
                "offers": offers,
                "pending": pending,
                "concluded": concluded,
                "interview_rate": round(concluded_interviews / concluded, 3)
                if concluded >= RATE_SAMPLE_FLOOR
                else None,
                "offer_rate": round(concluded_offers / concluded, 3)
                if concluded >= RATE_SAMPLE_FLOOR
                else None,
            }
        )
    return rows


def outcome_report(root: Path = DEFAULT_ROOT) -> dict[str, Any]:
    records = [record for _, record in iter_records(root)]
    outcomes = [_outcome(record) for record in records]
    status_counts = Counter(item["current_status"] for item in outcomes)
    return {
        "schema_version": 1,
        "method": (
            "Deterministic counts from recorded application events; rates are withheld until "
            f"at least {RATE_SAMPLE_FLOOR} applications in a group have concluded."
        ),
        "applications": len(records),
        "pending": sum(item["pending"] for item in outcomes),
        "interviews": sum(item["interview"] for item in outcomes),
        "offers": sum(item["offer"] for item in outcomes),
        "current_statuses": dict(sorted(status_counts.items())),
        "by_screen_category": _group_summary(records, "screen_category"),
        "by_match_classification": _group_summary(records, "match_classification"),
        "by_role_family": _group_summary(records, "role_family"),
        "by_resume": _group_summary(records, "resume"),
    }


def find_answers(root: Path, query: str) -> list[dict[str, Any]]:
    query_terms = set(TOKEN.findall(query.casefold()))
    matches: list[tuple[int, dict[str, Any]]] = []
    for _, record in iter_records(root):
        application = record["application"]
        for answer in record["answers"]:
            question_terms = set(TOKEN.findall(answer["question"].casefold()))
            score = len(query_terms & question_terms)
            if query_terms and score == 0:
                continue
            matches.append(
                (
                    score,
                    {
                        **answer,
                        "application_id": application["id"],
                        "company": application["company"],
                        "role": application["role"],
                    },
                )
            )
    return [
        item for _, item in sorted(matches, key=lambda pair: (-pair[0], pair[1]["recorded_at"]))
    ]


def migrate_dispositions(
    root: Path,
    preferences_path: Path,
    config_path: Path,
    dates: dict[str, str],
    *,
    apply: bool,
) -> dict[str, Any]:
    """Preview or migrate legacy applied dispositions without inventing dates."""
    try:
        preferences = yaml.safe_load(preferences_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(f"cannot read legacy preferences: {exc}") from exc
    if not isinstance(preferences, dict):
        raise ValueError("legacy preferences must contain a mapping")
    dispositions = preferences.get("job_dispositions", {})
    if not isinstance(dispositions, dict):
        raise ValueError("legacy job_dispositions must contain a mapping")
    job_ids = {
        str(job_id)
        for job_id, status in dispositions.items()
        if status == "applied" and str(job_id) not in applied_job_ids(root)
    }
    config = load_config(config_path)
    database_path = resolve_database_path(config_path, config.database_path)
    if not database_path.is_file():
        raise ValueError(f"job inventory database not found: {database_path}")
    database = InventoryDatabase(database_path)
    candidates: dict[str, dict[str, object]] = {
        str(item["id"]): item for item in database.application_candidates(job_ids)
    }
    missing_inventory = sorted(job_ids - set(candidates))
    missing_dates = sorted(job_id for job_id in candidates if job_id not in dates)
    valid = not missing_inventory and not missing_dates
    planned: list[dict[str, Any]] = []
    for job_id, item in sorted(candidates.items()):
        if job_id not in dates:
            continue
        namespace = argparse.Namespace(
            company=item["company"],
            role=item["role"],
            on=_date(dates[job_id]),
            job_id=job_id,
            url=item.get("url"),
            role_family=None,
            screen_category=None,
            match_classification=None,
            target=None,
            resume=None,
            note="Migrated from legacy job_dispositions.",
        )
        record = build_record(namespace, root.parent)
        result = _write_or_preview(root, record, apply=apply and valid)
        planned.append({"job_id": job_id, "path": result["path"]})
    return {
        "valid": valid,
        "applied": apply and valid,
        "planned": planned,
        "missing_application_dates": missing_dates,
        "missing_inventory_jobs": missing_inventory,
        "instruction": (
            "Supply --on JOB_ID=YYYY-MM-DD for every legacy applied job; inventory dates are "
            "not treated as application dates."
        ),
    }


def parser() -> argparse.ArgumentParser:
    command_parser = argparse.ArgumentParser(prog="resume-builder application")
    commands = command_parser.add_subparsers(dest="command", required=True)

    record = commands.add_parser("record", help="Preview or record one submitted application")
    record.add_argument("--company", required=True)
    record.add_argument("--role", required=True)
    record.add_argument("--on")
    record.add_argument("--job-id")
    record.add_argument("--url")
    record.add_argument("--role-family")
    record.add_argument("--screen-category")
    record.add_argument("--match-classification")
    record.add_argument("--match-report", type=Path)
    record.add_argument("--target", type=Path)
    record.add_argument("--resume", type=Path)
    record.add_argument("--note")
    record.add_argument("--apply", action="store_true")

    outcome = commands.add_parser("outcome", help="Preview or append an application event")
    outcome.add_argument("application_id")
    outcome.add_argument("status", choices=sorted(STATUSES - {"applied"}))
    outcome.add_argument("--on")
    outcome.add_argument("--stage")
    outcome.add_argument("--feedback")
    outcome.add_argument("--note")
    outcome.add_argument("--supersedes")
    outcome.add_argument("--apply", action="store_true")

    answer = commands.add_parser("answer", help="Preview or preserve one application answer")
    answer.add_argument("application_id")
    answer.add_argument("--question", required=True)
    answer.add_argument("--answer", required=True)
    answer.add_argument("--state", choices=sorted(ANSWER_STATES), default="draft")
    answer.add_argument("--evidence", action="append", default=[])
    answer.add_argument("--apply", action="store_true")

    answers = commands.add_parser("answers", help="Find earlier application answers")
    answers.add_argument("--query", default="")
    commands.add_parser("list", help="List recorded applications")
    show = commands.add_parser("show", help="Show one application record")
    show.add_argument("application_id")
    commands.add_parser("report", help="Report outcomes without changing match rules")
    commands.add_parser("validate", help="Validate application records and fact citations")

    migrate = commands.add_parser(
        "migrate-dispositions", help="Preview legacy applied-disposition migration"
    )
    migrate.add_argument("--preferences", type=Path, default=Path("job-search/preferences.yml"))
    migrate.add_argument("--config", type=Path, default=Path("job-search/config/search.yml"))
    migrate.add_argument("--on", action="append", default=[], metavar="JOB_ID=YYYY-MM-DD")
    migrate.add_argument("--apply", action="store_true")
    return command_parser


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    workspace = Path.cwd().resolve()
    if not (workspace / ".resume-builder.json").is_file():
        print("application commands require an active private workspace", file=sys.stderr)
        return 2
    root = workspace / DEFAULT_ROOT
    try:
        if args.command == "record":
            result = _write_or_preview(root, build_record(args, Path.cwd()), apply=args.apply)
        elif args.command == "outcome":
            result = append_event(
                root,
                args.application_id,
                args.status,
                args.on,
                stage=args.stage,
                feedback=args.feedback,
                note=args.note,
                supersedes=args.supersedes,
                apply=args.apply,
            )
        elif args.command == "answer":
            result = append_answer(
                root,
                args.application_id,
                args.question,
                args.answer,
                state=args.state,
                evidence=args.evidence,
                apply=args.apply,
            )
        elif args.command == "answers":
            result = {"answers": find_answers(root, args.query)}
        elif args.command == "list":
            result = {
                "applications": [
                    {**record["application"], **_outcome(record)}
                    for _, record in iter_records(root)
                ]
            }
        elif args.command == "show":
            result = load_record(root / f"{args.application_id}.json")
        elif args.command == "report":
            result = outcome_report(root)
        elif args.command == "validate":
            result = validate_history(root)
        else:
            dates: dict[str, str] = {}
            for assignment in args.on:
                job_id, separator, value = assignment.partition("=")
                if not separator or not job_id or not value:
                    raise ValueError("--on must use JOB_ID=YYYY-MM-DD")
                dates[job_id] = _date(value)
            result = migrate_dispositions(
                root,
                args.preferences.expanduser(),
                args.config.expanduser(),
                dates,
                apply=args.apply,
            )
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result.get("valid", True) else 1
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"Application history error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
