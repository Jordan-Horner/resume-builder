"""Validate and remember targeted resume evidence questions."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from .atomic import atomic_write_json
from .layout import contained_path

GAP_KEY = re.compile(r"^[a-z0-9]+(?:[.-][a-z0-9]+)*$")
SOURCE_ID = re.compile(r"^SRC-[0-9a-f]{12}$")
GAP_TYPES = {
    "outcome",
    "scale",
    "ownership",
    "chronology",
    "stakes",
    "collaboration",
    "technical-depth",
}
RESOLUTIONS = {"answered", "unknown", "declined", "accept-gap"}
GENERIC_PROMPTS = (
    "tell me more",
    "describe your experience",
    "anything else",
    "what else",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _object(value: object, owner: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{owner} must be an object")
    return value


def _exact_fields(value: dict[str, Any], expected: set[str], owner: str) -> None:
    missing = sorted(expected - value.keys())
    unexpected = sorted(value.keys() - expected)
    if missing or unexpected:
        raise ValueError(f"{owner} fields mismatch; missing={missing}, unexpected={unexpected}")


def _nonempty(value: object, owner: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{owner} must be a non-empty string")
    return value.strip()


def _read_json(path: Path, owner: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid {owner} {path}: {exc}") from exc
    return _object(value, owner)


def _history_path(project_root: Path) -> Path:
    return project_root / "editorial" / "evidence-questions.json"


def _load_history(project_root: Path) -> dict[str, Any]:
    path = _history_path(project_root)
    if not path.is_file():
        return {"version": 1, "entries": []}
    history = _read_json(path, "evidence-question history")
    _exact_fields(history, {"version", "entries"}, "evidence-question history")
    if history.get("version") != 1 or not isinstance(history.get("entries"), list):
        raise ValueError("evidence-question history must declare version 1 and an entries list")
    return history


def _registered_source_ids(project_root: Path) -> set[str]:
    manifest = project_root / "vault" / "sources" / "manifest.json"
    if not manifest.is_file():
        return set()
    data = _read_json(manifest, "source manifest")
    sources = data.get("sources")
    if not isinstance(sources, list):
        raise ValueError("source manifest sources must be a list")
    return {
        str(source.get("id"))
        for source in sources
        if isinstance(source, dict) and isinstance(source.get("id"), str)
    }


def _source_is_canonical(project_root: Path, source_id: str) -> bool:
    facts_root = project_root / "vault" / "facts"
    for path in facts_root.rglob("*.md") if facts_root.is_dir() else ():
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        if not text.startswith("---\n"):
            continue
        _, frontmatter, _ = text.split("---", 2)
        try:
            data = yaml.safe_load(frontmatter)
        except yaml.YAMLError:
            continue
        if isinstance(data, dict) and source_id in data.get("sources", []):
            return True
    return False


def question_plan(plan: Path, project_root: Path, *, apply: bool = False) -> dict[str, Any]:
    """Validate, deduplicate, and optionally remember one prioritized question set."""
    root = project_root.expanduser().resolve()
    plan_path = plan.expanduser()
    plan_path = (
        plan_path.resolve()
        if plan_path.is_absolute()
        else contained_path(root, plan_path.as_posix(), "evidence-question plan")
    )
    reviews_root = (root / "build" / "reviews").resolve()
    if not plan_path.is_relative_to(reviews_root) or not plan_path.is_file():
        raise ValueError(
            "evidence-question plan must be an existing JSON file under build/reviews/"
        )
    data = _read_json(plan_path, "evidence-question plan")
    _exact_fields(data, {"version", "resume", "questions"}, "evidence-question plan")
    if data.get("version") != 1:
        raise ValueError("evidence-question plan must declare version 1")
    resume = contained_path(root, data.get("resume"), "evidence-question plan resume")
    resumes_root = (root / "resumes").resolve()
    if not resume.is_relative_to(resumes_root) or not resume.is_file():
        raise ValueError("evidence-question plan resume must name an existing file under resumes/")
    questions = data.get("questions")
    if not isinstance(questions, list):
        raise ValueError("evidence-question plan questions must be a list")
    if len(questions) > 5:
        raise ValueError("one evidence-question round may contain no more than five questions")

    normalized: list[dict[str, object]] = []
    keys: set[str] = set()
    for index, raw in enumerate(questions):
        owner = f"evidence-question plan questions[{index}]"
        question = _object(raw, owner)
        _exact_fields(
            question,
            {
                "gap_key",
                "gap",
                "subject",
                "priority",
                "question",
                "expected_value",
                "evidence_searched",
            },
            owner,
        )
        gap_key = _nonempty(question.get("gap_key"), f"{owner}.gap_key")
        if not GAP_KEY.fullmatch(gap_key):
            raise ValueError(f"{owner}.gap_key must be a stable lowercase dot-or-dash key")
        if gap_key in keys:
            raise ValueError(f"duplicate gap_key in evidence-question plan: {gap_key}")
        keys.add(gap_key)
        gap = question.get("gap")
        if gap not in GAP_TYPES:
            raise ValueError(f"{owner}.gap must be one of {sorted(GAP_TYPES)}")
        priority = question.get("priority")
        if not isinstance(priority, int) or isinstance(priority, bool) or priority != index + 1:
            raise ValueError(f"{owner}.priority must match its 1-based expected-value order")
        wording = _nonempty(question.get("question"), f"{owner}.question")
        if not wording.endswith("?"):
            raise ValueError(f"{owner}.question must be a focused question")
        if any(prompt in wording.casefold() for prompt in GENERIC_PROMPTS):
            raise ValueError(f"{owner}.question is too generic")
        searched = _object(question.get("evidence_searched"), f"{owner}.evidence_searched")
        _exact_fields(
            searched,
            {"canonical_facts", "registered_sources", "notes"},
            f"{owner}.evidence_searched",
        )
        if (
            searched.get("canonical_facts") is not True
            or searched.get("registered_sources") is not True
        ):
            raise ValueError(f"{owner} must confirm facts and registered sources were searched")
        normalized.append(
            {
                "gap_key": gap_key,
                "gap": gap,
                "subject": _nonempty(question.get("subject"), f"{owner}.subject"),
                "priority": priority,
                "question": wording,
                "expected_value": _nonempty(
                    question.get("expected_value"), f"{owner}.expected_value"
                ),
                "evidence_searched": {
                    "canonical_facts": True,
                    "registered_sources": True,
                    "notes": _nonempty(searched.get("notes"), f"{owner}.evidence_searched.notes"),
                },
            }
        )

    history = _load_history(root)
    entries = history["entries"]
    assert isinstance(entries, list)
    existing = {entry.get("gap_key"): entry for entry in entries if isinstance(entry, dict)}
    resume_path = resume.relative_to(root).as_posix()
    askable = [item for item in normalized if item["gap_key"] not in existing]
    skipped = [existing[item["gap_key"]] for item in normalized if item["gap_key"] in existing]
    if apply and askable:
        asked_at = _now()
        for item in askable:
            entries.append(
                {
                    **item,
                    "resume": resume_path,
                    "status": "asked",
                    "asked_at": asked_at,
                    "resolved_at": None,
                    "source_id": None,
                }
            )
        _history_path(root).parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(_history_path(root), history)
    return {
        "valid": True,
        "applied": apply,
        "resume": resume_path,
        "askable": askable,
        "already_recorded": skipped,
        "history": _history_path(root).relative_to(root).as_posix(),
    }


def resolve_question(
    project_root: Path,
    *,
    resume: Path,
    gap_key: str,
    status: str,
    source_id: str | None = None,
) -> dict[str, Any]:
    """Resolve an asked gap without storing the user's conversational answer."""
    root = project_root.expanduser().resolve()
    resume_path = (
        resume.expanduser().resolve()
        if resume.is_absolute()
        else contained_path(root, resume.as_posix(), "evidence-question resume")
    )
    if not resume_path.is_relative_to((root / "resumes").resolve()):
        raise ValueError("evidence-question resume must be under resumes/")
    if not resume_path.is_file():
        raise ValueError("evidence-question resume must exist")
    relative_resume = resume_path.relative_to(root).as_posix()
    if not GAP_KEY.fullmatch(gap_key):
        raise ValueError("gap_key must be a stable lowercase dot-or-dash key")
    if status not in RESOLUTIONS:
        raise ValueError(f"question status must be one of {sorted(RESOLUTIONS)}")
    if status == "answered":
        if source_id is None or not SOURCE_ID.fullmatch(source_id):
            raise ValueError("answered questions require a registered SRC-<12 lowercase hex> ID")
        if source_id not in _registered_source_ids(root):
            raise ValueError("answered question source_id is not registered in the vault")
        if not _source_is_canonical(root, source_id):
            raise ValueError("answered question source_id is not cited by a canonical fact")
    elif source_id is not None:
        raise ValueError("source_id is allowed only for an answered question")

    history = _load_history(root)
    entries = history["entries"]
    assert isinstance(entries, list)
    matches = [
        entry for entry in entries if isinstance(entry, dict) and entry.get("gap_key") == gap_key
    ]
    if len(matches) != 1:
        raise ValueError("question resolution must match exactly one recorded resume gap")
    entry = matches[0]
    if entry.get("status") != "asked":
        raise ValueError(f"question is already resolved as {entry.get('status')}")
    entry["status"] = status
    entry["resolved_at"] = _now()
    entry["source_id"] = source_id
    atomic_write_json(_history_path(root), history)
    return {
        "valid": True,
        "resume": relative_resume,
        "gap_key": gap_key,
        "status": status,
        "source_id": source_id,
    }
