"""Capture conversational resume feedback and promote accepted guidance."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .atomic import atomic_write_bytes, atomic_write_json
from .layout import contained_path
from .synthesis import SynthesisPlan, load_synthesis_plan

SESSION_ID = re.compile(r"^FB-[0-9a-f]{12}$")
RULE_ID = re.compile(r"^ER-[0-9a-f]{12}$")
SUBJECT_KEY = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
KINDS = {
    "claim-boundary",
    "terminology",
    "authority",
    "relationship",
    "presentation",
    "style",
}
STRENGTHS = {"hard", "preference"}
PROMOTIONS = {"durable", "local", "none", "hydrate"}
SCOPE_LEVELS = {"facts", "story", "resume", "direction", "global"}
SESSION_STATUSES = {"open", "accepted", "closed", "needs-hydration"}
RULE_STATUSES = {"active", "retired"}


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


def _string_list(value: object, owner: str) -> list[str]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise ValueError(f"{owner} must be a list of non-empty strings")
    result = [item.strip() for item in value]
    if len(result) != len(set(result)):
        raise ValueError(f"{owner} must not contain duplicates")
    return result


def _read_json(path: Path, owner: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid {owner} {path}: {exc}") from exc
    return _object(value, owner)


def _project_file(
    project_root: Path,
    value: object,
    owner: str,
    directory: str,
    *,
    required: bool = True,
) -> Path:
    path = contained_path(project_root, value, owner)
    allowed = (project_root / directory).resolve()
    if not path.is_relative_to(allowed):
        raise ValueError(f"{owner} must be under {directory}/")
    if required and not path.is_file():
        raise ValueError(f"{owner} does not exist: {path}")
    return path


def _text_digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _identity_digest(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:12]


def _effective_payload(
    identity: dict[str, Any],
    strength: object,
    revision: dict[str, Any],
) -> dict[str, object]:
    """Return the storage-independent guidance that can affect resume prose."""
    return {
        "identity": identity,
        "strength": strength,
        "instruction": revision["instruction"],
        "must_preserve": revision["must_preserve"],
        "must_avoid": revision["must_avoid"],
        "preferred_examples": revision["preferred_examples"],
    }


def _effective_digest(
    identity: dict[str, Any],
    strength: object,
    revision: dict[str, Any],
) -> str:
    payload = _effective_payload(identity, strength, revision)
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _block_inventory(resume: Path) -> dict[str, dict[str, object]]:
    from .compilation import compile_markdown

    payload = compile_markdown(resume.read_text(encoding="utf-8"))
    blocks: dict[str, dict[str, object]] = {}
    candidate = _object(payload.get("candidate"), "candidate")
    headline = candidate.get("headline")
    if isinstance(headline, str) and headline.strip():
        evidence = candidate.get("evidence")
        blocks["candidate.headline"] = {
            "text": headline.strip(),
            "evidence": evidence if isinstance(evidence, list) else [],
            "story": None,
            "section": "header",
        }
    blocks["summary"] = {
        "text": str(payload["summary"]),
        "evidence": list(payload["summary_evidence"]),
        "story": None,
        "section": "summary",
    }
    for index, competency in enumerate(payload["competencies"]):
        blocks[f"competencies[{index}]"] = {
            "text": str(competency["text"]),
            "evidence": list(competency["evidence"]),
            "story": None,
            "section": "competencies",
        }
    for experience_index, experience in enumerate(payload["experience"]):
        for bullet_index, bullet in enumerate(experience["bullets"]):
            blocks[f"experience[{experience_index}].bullets[{bullet_index}]"] = {
                "text": str(bullet["text"]),
                "evidence": list(bullet["evidence"]),
                "story": bullet.get("story"),
                "section": "experience",
            }
    for index, project in enumerate(payload["projects"]):
        for suffix, field in (("name", "name"), ("description", "description")):
            blocks[f"projects[{index}].{suffix}"] = {
                "text": str(project[field]),
                "evidence": list(project["evidence"]),
                "story": project.get("story"),
                "section": "projects",
            }
        if project.get("tech"):
            blocks[f"projects[{index}].tech"] = {
                "text": str(project["tech"]),
                "evidence": list(project["evidence"]),
                "story": project.get("story"),
                "section": "projects",
            }
    for index, education in enumerate(payload["education"]):
        if education.get("description"):
            blocks[f"education[{index}].description"] = {
                "text": str(education["description"]),
                "evidence": list(education["evidence"]),
                "story": None,
                "section": "education",
            }
    return blocks


def _scope(
    value: object, project_root: Path, resume: Path, block: dict[str, object]
) -> dict[str, object]:
    data = _object(value, "feedback.scope")
    _exact_fields(
        data,
        {"level", "fact_ids", "resume", "story_id", "direction", "section"},
        "feedback.scope",
    )
    level = data.get("level")
    if level not in SCOPE_LEVELS:
        raise ValueError(f"feedback.scope.level must be one of {sorted(SCOPE_LEVELS)}")
    fact_ids = _string_list(data.get("fact_ids"), "feedback.scope.fact_ids")
    resume_value = data.get("resume")
    story_id = data.get("story_id")
    direction_value = data.get("direction")
    section = data.get("section")
    for optional, owner in (
        (resume_value, "feedback.scope.resume"),
        (story_id, "feedback.scope.story_id"),
        (direction_value, "feedback.scope.direction"),
        (section, "feedback.scope.section"),
    ):
        if optional is not None and (not isinstance(optional, str) or not optional.strip()):
            raise ValueError(f"{owner} must be null or a non-empty string")
    normalized_resume = None
    if resume_value is not None:
        scoped_resume = _project_file(
            project_root, resume_value, "feedback.scope.resume", "resumes"
        )
        if scoped_resume != resume:
            raise ValueError("feedback.scope.resume must match the feedback source resume")
        normalized_resume = scoped_resume.relative_to(project_root).as_posix()
    normalized_direction = None
    if direction_value is not None:
        direction = _project_file(
            project_root,
            direction_value,
            "feedback.scope.direction",
            "directions",
        )
        normalized_direction = direction.relative_to(project_root).as_posix()
    normalized_story = story_id.strip() if isinstance(story_id, str) else None
    normalized_section = section.strip() if isinstance(section, str) else None
    raw_block_evidence = block.get("evidence")
    block_evidence = (
        {str(item) for item in raw_block_evidence}
        if isinstance(raw_block_evidence, list)
        else set()
    )
    if level == "facts":
        if not fact_ids or set(fact_ids) - block_evidence:
            raise ValueError("fact-scoped feedback must cite facts used by the selected block")
    elif fact_ids:
        raise ValueError("feedback.scope.fact_ids is only allowed for facts scope")
    if level == "story":
        if normalized_resume is None or normalized_story != block.get("story"):
            raise ValueError("story-scoped feedback must match the selected block story and resume")
    elif normalized_story is not None:
        raise ValueError("feedback.scope.story_id is only allowed for story scope")
    if level == "resume" and normalized_resume is None:
        raise ValueError("resume-scoped feedback requires feedback.scope.resume")
    if level == "direction" and normalized_direction is None:
        raise ValueError("direction-scoped feedback requires feedback.scope.direction")
    if level == "global" and any(
        item is not None for item in (normalized_resume, normalized_story, normalized_direction)
    ):
        raise ValueError("global feedback cannot name a resume, story, or direction")
    if normalized_section is not None and normalized_section != block.get("section"):
        raise ValueError("feedback.scope.section must match the selected block section")
    return {
        "level": level,
        "fact_ids": fact_ids,
        "resume": normalized_resume,
        "story_id": normalized_story,
        "direction": normalized_direction,
        "section": normalized_section,
    }


def _validate_feedback(
    value: object,
    project_root: Path,
    resume: Path,
    block: dict[str, object],
) -> dict[str, object]:
    data = _object(value, "feedback")
    _exact_fields(
        data,
        {
            "subject_key",
            "kind",
            "strength",
            "promotion",
            "scope",
            "summary",
            "instruction",
            "must_preserve",
            "must_avoid",
            "preferred_examples",
            "supersedes",
        },
        "feedback",
    )
    subject_key = _nonempty(data.get("subject_key"), "feedback.subject_key")
    if not SUBJECT_KEY.fullmatch(subject_key):
        raise ValueError("feedback.subject_key must be lowercase and hyphenated")
    kind = data.get("kind")
    strength = data.get("strength")
    promotion = data.get("promotion")
    if kind not in KINDS:
        raise ValueError(f"feedback.kind must be one of {sorted(KINDS)}")
    if strength not in STRENGTHS:
        raise ValueError(f"feedback.strength must be one of {sorted(STRENGTHS)}")
    if promotion not in PROMOTIONS:
        raise ValueError(f"feedback.promotion must be one of {sorted(PROMOTIONS)}")
    scope = _scope(data.get("scope"), project_root, resume, block)
    if promotion == "local" and scope["level"] not in {"story", "resume", "direction"}:
        raise ValueError("local feedback must use story, resume, or direction scope")
    if promotion == "durable" and scope["level"] not in {"facts", "direction", "global"}:
        raise ValueError("durable feedback must use facts, direction, or global scope")
    if strength == "hard" and kind in {"presentation", "style"}:
        raise ValueError("presentation and style feedback must be a preference")
    supersedes = _string_list(data.get("supersedes"), "feedback.supersedes")
    if any(not RULE_ID.fullmatch(rule_id) for rule_id in supersedes):
        raise ValueError("feedback.supersedes contains an invalid rule ID")
    return {
        "subject_key": subject_key,
        "kind": kind,
        "strength": strength,
        "promotion": promotion,
        "scope": scope,
        "summary": _nonempty(data.get("summary"), "feedback.summary"),
        "instruction": _nonempty(data.get("instruction"), "feedback.instruction"),
        "must_preserve": _string_list(data.get("must_preserve"), "feedback.must_preserve"),
        "must_avoid": _string_list(data.get("must_avoid"), "feedback.must_avoid"),
        "preferred_examples": _string_list(
            data.get("preferred_examples"), "feedback.preferred_examples"
        ),
        "supersedes": supersedes,
    }


def _validate_persisted_scope(value: object, owner: str, project_root: Path) -> dict[str, Any]:
    scope = _object(value, owner)
    _exact_fields(
        scope,
        {"level", "fact_ids", "resume", "story_id", "direction", "section"},
        owner,
    )
    level = scope.get("level")
    if level not in SCOPE_LEVELS:
        raise ValueError(f"{owner}.level must be one of {sorted(SCOPE_LEVELS)}")
    fact_ids = _string_list(scope.get("fact_ids"), f"{owner}.fact_ids")
    if level == "facts" and not fact_ids:
        raise ValueError(f"{owner}.fact_ids must be non-empty for facts scope")
    if level != "facts" and fact_ids:
        raise ValueError(f"{owner}.fact_ids is only allowed for facts scope")
    for field in ("resume", "story_id", "direction", "section"):
        item = scope.get(field)
        if item is not None and (not isinstance(item, str) or not item.strip()):
            raise ValueError(f"{owner}.{field} must be null or a non-empty string")
    if scope.get("resume") is not None:
        _project_file(
            project_root,
            scope["resume"],
            f"{owner}.resume",
            "resumes",
            required=False,
        )
    if scope.get("direction") is not None:
        _project_file(
            project_root,
            scope["direction"],
            f"{owner}.direction",
            "directions",
            required=False,
        )
    if level == "story" and (scope.get("resume") is None or scope.get("story_id") is None):
        raise ValueError(f"{owner} story scope requires resume and story_id")
    if level == "resume" and scope.get("resume") is None:
        raise ValueError(f"{owner} resume scope requires resume")
    if level == "direction" and scope.get("direction") is None:
        raise ValueError(f"{owner} direction scope requires direction")
    return scope


def record_feedback(
    plan: Path,
    project_root: Path,
    *,
    session_id: str | None = None,
) -> dict[str, object]:
    """Record the newest interpretation of one user correction in a temporary session."""
    root = project_root.expanduser().resolve()
    plan_path = plan.expanduser()
    plan_path = (
        plan_path.resolve()
        if plan_path.is_absolute()
        else contained_path(root, plan_path.as_posix(), "feedback plan")
    )
    if not plan_path.is_relative_to((root / "build").resolve()) or not plan_path.is_file():
        raise ValueError("feedback plan must be an existing JSON file under build/")
    data = _read_json(plan_path, "feedback plan")
    version = data.get("version")
    expected_fields = {"version", "resume", "block", "feedback"}
    if version == 2:
        expected_fields.add("session_id")
    _exact_fields(data, expected_fields, "feedback plan")
    if version not in {1, 2}:
        raise ValueError("feedback plan must declare version 1 or 2")
    planned_session_id = data.get("session_id") if version == 2 else None
    if session_id is not None and planned_session_id not in {None, session_id}:
        raise ValueError("--session disagrees with feedback plan session_id")
    selected_session_id = session_id or planned_session_id
    if selected_session_id is not None and not SESSION_ID.fullmatch(str(selected_session_id)):
        raise ValueError("feedback session ID must look like FB-<12 lowercase hex characters>")
    resume = _project_file(root, data.get("resume"), "feedback plan resume", "resumes")
    blocks = _block_inventory(resume)
    block_data = _object(data.get("block"), "feedback plan block")
    _exact_fields(block_data, {"id", "sha256"}, "feedback plan block")
    block_id = _nonempty(block_data.get("id"), "feedback plan block.id")
    if block_id not in blocks:
        raise ValueError(f"feedback plan block does not exist in the current resume: {block_id}")
    block = blocks[block_id]
    expected_digest = _text_digest(str(block["text"]))
    if block_data.get("sha256") != expected_digest:
        raise ValueError("feedback plan block hash does not match the current resume")
    feedback = _validate_feedback(data.get("feedback"), root, resume, block)
    identity = {
        "subject_key": feedback["subject_key"],
        "kind": feedback["kind"],
        "scope": feedback["scope"],
    }
    digest = _identity_digest(identity)
    session_id = str(selected_session_id or f"FB-{digest}")
    rule_id = f"ER-{digest}"
    session_path = root / "build" / "feedback" / f"{session_id}.json"
    existing: dict[str, Any] | None = None
    if session_path.is_file():
        existing = _read_json(session_path, "feedback session")
        _validate_session(existing, session_path, root)
        if selected_session_id is None and (
            existing.get("identity") != identity or existing.get("rule_id") != rule_id
        ):
            raise ValueError("feedback session identity does not match its deterministic ID")
    revisions = list(existing.get("revisions", [])) if existing is not None else []
    revision_number = len(revisions) + 1
    revision = {
        "revision": revision_number,
        "recorded_at": _now(),
        "source": {
            "resume": resume.relative_to(root).as_posix(),
            "block_id": block_id,
            "block_sha256": expected_digest,
        },
        "summary": feedback["summary"],
        "instruction": feedback["instruction"],
        "must_preserve": feedback["must_preserve"],
        "must_avoid": feedback["must_avoid"],
        "preferred_examples": feedback["preferred_examples"],
        "supersedes": feedback["supersedes"],
    }
    revisions.append(revision)
    session = {
        "version": 1,
        "id": session_id,
        "rule_id": rule_id,
        "status": "open",
        "identity": identity,
        "strength": feedback["strength"],
        "promotion": feedback["promotion"],
        "current_revision": revision_number,
        "revisions": revisions,
        "accepted_at": None,
        "promoted_rule": existing.get("promoted_rule") if existing is not None else None,
        "accepted_result": None,
    }
    atomic_write_json(session_path, session)
    return {
        "valid": True,
        "session": session_path.relative_to(root).as_posix(),
        "session_id": session_id,
        "rule_id": rule_id,
        "current_revision": revision_number,
        "effective_digest": _effective_digest(identity, feedback["strength"], revision),
        "receipt": f"Remembering for this revision: {feedback['instruction']}",
        "next_action": "Revise the resume, verify it, and request user review.",
    }


def _validate_session(data: dict[str, Any], path: Path, project_root: Path) -> None:
    _exact_fields(
        data,
        {
            "version",
            "id",
            "rule_id",
            "status",
            "identity",
            "strength",
            "promotion",
            "current_revision",
            "revisions",
            "accepted_at",
            "promoted_rule",
            "accepted_result",
        },
        "feedback session",
    )
    if data.get("version") != 1:
        raise ValueError(f"{path}: feedback session must declare version 1")
    if data.get("id") != path.stem or not SESSION_ID.fullmatch(str(data.get("id"))):
        raise ValueError(f"{path}: feedback session ID does not match its filename")
    if not RULE_ID.fullmatch(str(data.get("rule_id"))):
        raise ValueError(f"{path}: feedback session has an invalid rule ID")
    if data.get("status") not in SESSION_STATUSES:
        raise ValueError(f"{path}: feedback session has an invalid status")
    if data.get("strength") not in STRENGTHS or data.get("promotion") not in PROMOTIONS:
        raise ValueError(f"{path}: feedback session has invalid strength or promotion")
    identity = _object(data.get("identity"), f"{path} identity")
    _exact_fields(identity, {"subject_key", "kind", "scope"}, f"{path} identity")
    if not SUBJECT_KEY.fullmatch(str(identity.get("subject_key"))):
        raise ValueError(f"{path}: invalid subject key")
    if identity.get("kind") not in KINDS:
        raise ValueError(f"{path}: invalid feedback kind")
    _validate_persisted_scope(identity.get("scope"), f"{path} scope", project_root)
    revisions = data.get("revisions")
    if not isinstance(revisions, list) or not revisions:
        raise ValueError(f"{path}: feedback session revisions must be non-empty")
    current = data.get("current_revision")
    if current != len(revisions):
        raise ValueError(f"{path}: current revision must identify the latest revision")
    for index, value in enumerate(revisions, start=1):
        revision = _object(value, f"{path} revision[{index}]")
        _exact_fields(
            revision,
            {
                "revision",
                "recorded_at",
                "source",
                "summary",
                "instruction",
                "must_preserve",
                "must_avoid",
                "preferred_examples",
                "supersedes",
            },
            f"{path} revision[{index}]",
        )
        if revision.get("revision") != index:
            raise ValueError(f"{path}: feedback revisions must be sequential")
        source = _object(revision.get("source"), f"{path} revision[{index}].source")
        _exact_fields(source, {"resume", "block_id", "block_sha256"}, "feedback source")
        _project_file(project_root, source.get("resume"), "feedback source resume", "resumes")
        _nonempty(source.get("block_id"), "feedback source block_id")
        if not isinstance(source.get("block_sha256"), str) or not re.fullmatch(
            r"[0-9a-f]{64}", str(source.get("block_sha256"))
        ):
            raise ValueError(f"{path}: feedback source block_sha256 is invalid")
        for field in ("summary", "instruction"):
            _nonempty(revision.get(field), f"{path} revision[{index}].{field}")
        for field in ("must_preserve", "must_avoid", "preferred_examples", "supersedes"):
            _string_list(revision.get(field), f"{path} revision[{index}].{field}")
    accepted_result = data.get("accepted_result")
    if accepted_result is not None:
        result = _object(accepted_result, f"{path} accepted_result")
        expected = {
            "resume_sha256",
            "build_manifest",
            "build_sha256",
            "review_record",
            "review_sha256",
            "preview_manifest",
            "preview_sha256",
            "output",
            "output_sha256",
            "effective_digest",
        }
        _exact_fields(result, expected, f"{path} accepted_result")
        for field in expected:
            _nonempty(result.get(field), f"{path} accepted_result.{field}")


def _validate_rule(data: dict[str, Any], path: Path, project_root: Path) -> None:
    _exact_fields(
        data,
        {
            "version",
            "id",
            "status",
            "identity",
            "strength",
            "current_revision",
            "revisions",
            "retired_at",
            "retirement_reason",
        },
        "feedback rule",
    )
    if data.get("version") != 1:
        raise ValueError(f"{path}: feedback rule must declare version 1")
    if data.get("id") != path.stem or not RULE_ID.fullmatch(str(data.get("id"))):
        raise ValueError(f"{path}: feedback rule ID does not match its filename")
    if data.get("status") not in RULE_STATUSES:
        raise ValueError(f"{path}: feedback rule has an invalid status")
    identity = _object(data.get("identity"), f"{path} identity")
    _exact_fields(identity, {"subject_key", "kind", "scope"}, f"{path} identity")
    if not SUBJECT_KEY.fullmatch(str(identity.get("subject_key"))):
        raise ValueError(f"{path}: invalid feedback-rule subject key")
    if identity.get("kind") not in KINDS:
        raise ValueError(f"{path}: invalid feedback-rule kind")
    _validate_persisted_scope(identity.get("scope"), f"{path} scope", project_root)
    revisions = data.get("revisions")
    if not isinstance(revisions, list) or not revisions:
        raise ValueError(f"{path}: feedback rule revisions must be non-empty")
    if data.get("current_revision") != len(revisions):
        raise ValueError(f"{path}: current revision must identify the latest accepted revision")
    for index, value in enumerate(revisions, start=1):
        revision = _object(value, f"{path} revision[{index}]")
        _exact_fields(
            revision,
            {
                "revision",
                "accepted_at",
                "source_session",
                "source_session_revision",
                "summary",
                "instruction",
                "must_preserve",
                "must_avoid",
                "preferred_examples",
            },
            f"{path} revision[{index}]",
        )
        if revision.get("revision") != index:
            raise ValueError(f"{path}: feedback rule revisions must be sequential")
        for field in ("summary", "instruction", "source_session"):
            _nonempty(revision.get(field), f"{path} revision[{index}].{field}")
        if not SESSION_ID.fullmatch(str(revision.get("source_session"))):
            raise ValueError(f"{path}: feedback rule source_session is invalid")
        source_revision = revision.get("source_session_revision")
        if (
            not isinstance(source_revision, int)
            or isinstance(source_revision, bool)
            or source_revision < 1
        ):
            raise ValueError(f"{path}: feedback rule source_session_revision is invalid")
        for field in ("must_preserve", "must_avoid", "preferred_examples"):
            _string_list(revision.get(field), f"{path} revision[{index}].{field}")
    if data.get("strength") not in STRENGTHS:
        raise ValueError(f"{path}: feedback rule has an invalid strength")


def _rule_record(path: Path, data: dict[str, Any], project_root: Path) -> dict[str, object]:
    current = data["revisions"][int(data["current_revision"]) - 1]
    return {
        "id": data["id"],
        "revision": data["current_revision"],
        "kind": data["identity"]["kind"],
        "strength": data["strength"],
        "scope": data["identity"]["scope"],
        "instruction": current["instruction"],
        "must_preserve": current["must_preserve"],
        "must_avoid": current["must_avoid"],
        "preferred_examples": current["preferred_examples"],
        "effective_digest": _effective_digest(data["identity"], data["strength"], current),
        "path": path.relative_to(project_root).as_posix(),
        "sha256": _file_digest(path),
    }


def _retire_rule(path: Path, data: dict[str, Any], reason: str) -> None:
    data["status"] = "retired"
    data["retired_at"] = _now()
    data["retirement_reason"] = reason
    atomic_write_json(path, data)


def _acceptance_result(
    root: Path,
    session: dict[str, Any],
    preview: Path,
) -> dict[str, str]:
    """Validate that one reviewed preview contains the exact open revision."""
    from .review_records import load_review_record, review_freshness, sha256_file

    preview_path = _project_file(root, preview.as_posix(), "accepted feedback preview", "build")
    if not preview_path.name.endswith(".preview.json"):
        raise ValueError("accepted feedback preview must be a *.preview.json file")
    preview_data = _read_json(preview_path, "accepted feedback preview")
    if (
        preview_data.get("version") != 2
        or preview_data.get("phase") != "preview"
        or preview_data.get("valid") is not True
        or preview_data.get("final_review_status") != "awaiting-user-approval"
    ):
        raise ValueError("feedback acceptance requires a successful current preview")
    build_record = _object(preview_data.get("build_manifest"), "preview build manifest")
    review_record = _object(preview_data.get("review_record"), "preview review record")
    output_record = _object(preview_data.get("output"), "preview output")
    build_path = _project_file(root, build_record.get("path"), "preview build", "build")
    review_path = _project_file(root, review_record.get("path"), "preview review", "build/reviews")
    output_path = _project_file(root, output_record.get("path"), "preview output", "build")
    for path, record, owner in (
        (build_path, build_record, "preview build"),
        (review_path, review_record, "preview review"),
        (output_path, output_record, "preview output"),
    ):
        if record.get("sha256") != sha256_file(path):
            raise ValueError(f"{owner} changed after preview publication")
    build = _read_json(build_path, "accepted feedback build")
    memory = _object(build.get("feedback_memory"), "accepted feedback build memory")
    guidance = memory.get("rules")
    if not isinstance(guidance, list):
        raise ValueError("accepted feedback build has no effective guidance")
    current_revision = int(session["current_revision"])
    current = session["revisions"][current_revision - 1]
    digest = _effective_digest(session["identity"], session["strength"], current)
    matching_guidance = [
        item
        for item in guidance
        if isinstance(item, dict)
        and item.get("source") == "open-session"
        and item.get("id") == session["id"]
        and item.get("revision") == current_revision
        and item.get("effective_digest") == digest
    ]
    if len(matching_guidance) != 1:
        raise ValueError("preview does not contain the exact current feedback revision")
    review = load_review_record(review_path, root)
    reasons = review_freshness(review)
    if reasons:
        raise ValueError(f"feedback acceptance review is stale or incomplete: {reasons}")
    matching_decisions = [
        decision
        for decision in review.feedback_rules
        if decision.id == session["id"] and decision.revision == current_revision
    ]
    if (
        review.feedback_status != "approved"
        or len(matching_decisions) != 1
        or matching_decisions[0].decision != "complies"
    ):
        raise ValueError("preview lacks approved compliance for the current feedback revision")
    return {
        "resume_sha256": str(_object(build.get("source"), "build source").get("sha256")),
        "build_manifest": build_path.relative_to(root).as_posix(),
        "build_sha256": sha256_file(build_path),
        "review_record": review_path.relative_to(root).as_posix(),
        "review_sha256": sha256_file(review_path),
        "preview_manifest": preview_path.relative_to(root).as_posix(),
        "preview_sha256": sha256_file(preview_path),
        "output": output_path.relative_to(root).as_posix(),
        "output_sha256": sha256_file(output_path),
        "effective_digest": digest,
    }


def accept_feedback(
    project_root: Path,
    *,
    session_id: str | None = None,
    resume: Path | None = None,
    preview: Path | None = None,
) -> dict[str, object]:
    """Accept current feedback sessions and promote only their latest revisions."""
    root = project_root.expanduser().resolve()
    sessions_root = root / "build" / "feedback"
    paths: list[Path]
    if session_id is not None:
        if not SESSION_ID.fullmatch(session_id):
            raise ValueError("feedback session ID must look like FB-<12 lowercase hex characters>")
        paths = [sessions_root / f"{session_id}.json"]
    else:
        if resume is None:
            raise ValueError("accept requires a session ID or --resume")
        resume_path = _project_file(root, resume.as_posix(), "accepted feedback resume", "resumes")
        relative_resume = resume_path.relative_to(root).as_posix()
        paths = []
        for candidate in sorted(sessions_root.glob("FB-*.json")):
            value = _read_json(candidate, "feedback session")
            _validate_session(value, candidate, root)
            revisions = value.get("revisions")
            current_source = (
                _object(revisions[-1], "feedback revision").get("source")
                if isinstance(revisions, list) and revisions
                else None
            )
            if (
                value.get("status") == "open"
                and isinstance(revisions, list)
                and revisions
                and _object(current_source, "feedback source").get("resume") == relative_resume
            ):
                paths.append(candidate)
    if not paths:
        raise ValueError("no open feedback sessions matched the acceptance request")
    if len(paths) != 1:
        raise ValueError(
            "feedback acceptance must name one exact session; accept additional sessions separately"
        )
    if preview is None:
        raise ValueError("feedback acceptance requires --preview for the reviewed result")
    accepted: list[dict[str, object]] = []
    for path in paths:
        if not path.is_file():
            raise ValueError(f"feedback session does not exist: {path.stem}")
        session = _read_json(path, "feedback session")
        _validate_session(session, path, root)
        if session["status"] != "open":
            raise ValueError(f"feedback session is not open: {path.stem}")
        accepted_result = _acceptance_result(root, session, preview)
        promotion = session["promotion"]
        current = session["revisions"][session["current_revision"] - 1]
        if promotion == "hydrate":
            session["status"] = "needs-hydration"
            session["accepted_at"] = _now()
            session["accepted_result"] = accepted_result
            atomic_write_json(path, session)
            accepted.append({"session_id": session["id"], "route": "hydrate", "rule": None})
            continue
        if promotion == "none":
            session["status"] = "closed"
            session["accepted_at"] = _now()
            session["accepted_result"] = accepted_result
            atomic_write_json(path, session)
            accepted.append({"session_id": session["id"], "route": "closed", "rule": None})
            continue
        rules_root = root / "editorial" / "rules"
        rule_path = rules_root / f"{session['rule_id']}.json"
        if rule_path.is_file():
            rule = _read_json(rule_path, "feedback rule")
            _validate_rule(rule, rule_path, root)
            if rule["identity"] != session["identity"]:
                raise ValueError("existing feedback rule has a different semantic identity")
            revisions = list(rule["revisions"])
        else:
            revisions = []
            rule = {
                "version": 1,
                "id": session["rule_id"],
                "status": "active",
                "identity": session["identity"],
                "strength": session["strength"],
                "current_revision": 0,
                "revisions": [],
                "retired_at": None,
                "retirement_reason": None,
            }
        accepted_at = _now()
        revisions.append(
            {
                "revision": len(revisions) + 1,
                "accepted_at": accepted_at,
                "source_session": session["id"],
                "source_session_revision": session["current_revision"],
                "summary": current["summary"],
                "instruction": current["instruction"],
                "must_preserve": current["must_preserve"],
                "must_avoid": current["must_avoid"],
                "preferred_examples": current["preferred_examples"],
            }
        )
        rule.update(
            {
                "status": "active",
                "strength": session["strength"],
                "current_revision": len(revisions),
                "revisions": revisions,
                "retired_at": None,
                "retirement_reason": None,
            }
        )
        superseded_ids = list(current["supersedes"])
        previous_rule = session.get("promoted_rule")
        if (
            isinstance(previous_rule, dict)
            and isinstance(previous_rule.get("id"), str)
            and previous_rule["id"] != session["rule_id"]
            and previous_rule["id"] not in superseded_ids
        ):
            superseded_ids.append(previous_rule["id"])
        superseded_records: list[tuple[Path, dict[str, Any]]] = []
        for superseded_id in superseded_ids:
            superseded_path = rules_root / f"{superseded_id}.json"
            if not superseded_path.is_file():
                raise ValueError(f"superseded feedback rule does not exist: {superseded_id}")
            superseded = _read_json(superseded_path, "superseded feedback rule")
            _validate_rule(superseded, superseded_path, root)
            superseded_records.append((superseded_path, superseded))
        retired_updates: list[tuple[Path, dict[str, Any]]] = []
        for superseded_path, superseded in superseded_records:
            retired = dict(superseded)
            retired["status"] = "retired"
            retired["retired_at"] = _now()
            retired["retirement_reason"] = (
                f"Superseded by {session['rule_id']} revision {len(revisions)}."
            )
            retired_updates.append((superseded_path, retired))
        session["status"] = "accepted"
        session["accepted_at"] = accepted_at
        session["accepted_result"] = accepted_result
        session["promoted_rule"] = {
            "id": rule["id"],
            "revision": rule["current_revision"],
            "path": rule_path.relative_to(root).as_posix(),
        }
        updates = [*retired_updates, (rule_path, rule), (path, session)]
        originals = {
            update_path: update_path.read_bytes() if update_path.is_file() else None
            for update_path, _ in updates
        }
        try:
            for update_path, value in updates:
                atomic_write_json(update_path, value)
        except BaseException:
            for update_path, original in originals.items():
                if original is None:
                    update_path.unlink(missing_ok=True)
                else:
                    atomic_write_bytes(update_path, original)
            raise
        accepted.append(
            {
                "session_id": session["id"],
                "route": "memory",
                "rule": rule["id"],
                "revision": rule["current_revision"],
                "receipt": f"Saved for future resumes: {current['instruction']}",
            }
        )
    return {"valid": True, "accepted": accepted}


def retire_feedback_rule(rule_id: str, reason: str, project_root: Path) -> dict[str, object]:
    root = project_root.expanduser().resolve()
    if not RULE_ID.fullmatch(rule_id):
        raise ValueError("feedback rule ID must look like ER-<12 lowercase hex characters>")
    path = root / "editorial" / "rules" / f"{rule_id}.json"
    if not path.is_file():
        raise ValueError(f"feedback rule does not exist: {rule_id}")
    rule = _read_json(path, "feedback rule")
    _validate_rule(rule, path, root)
    _retire_rule(path, rule, _nonempty(reason, "retirement reason"))
    return {"valid": True, "rule": rule_id, "status": "retired"}


def _context(plan: SynthesisPlan, project_root: Path) -> dict[str, object]:
    fact_ids = set(plan.summary_fact_ids)
    story_ids: set[str] = set()
    fact_sections: dict[str, set[str]] = {}
    story_sections: dict[str, str] = {}
    for fact_id in plan.summary_fact_ids:
        fact_sections.setdefault(fact_id, set()).add("summary")
    for story in plan.stories:
        fact_ids.update(story.fact_ids)
        fact_ids.update(story.role_ids)
        story_ids.add(story.story_id)
        story_sections[story.story_id] = story.section
        for fact_id in (*story.fact_ids, *story.role_ids):
            fact_sections.setdefault(fact_id, set()).add(story.section)
    return {
        "facts": fact_ids,
        "stories": story_ids,
        "fact_sections": fact_sections,
        "story_sections": story_sections,
        "sections": set(story_sections.values())
        | ({"summary"} if plan.summary_fact_ids else set()),
        "resume": plan.resume.relative_to(project_root).as_posix(),
        "direction": plan.direction.relative_to(project_root).as_posix(),
    }


def _applies(scope: dict[str, object], context: dict[str, object]) -> bool:
    level = scope["level"]
    section = scope.get("section")
    section_applies = True
    if isinstance(section, str):
        if level == "facts":
            fact_sections = context.get("fact_sections")
            scope_facts = scope.get("fact_ids")
            section_applies = (
                isinstance(fact_sections, dict)
                and isinstance(scope_facts, list)
                and all(section in fact_sections.get(fact_id, set()) for fact_id in scope_facts)
            )
        elif level == "story":
            story_sections = context.get("story_sections")
            section_applies = (
                isinstance(story_sections, dict)
                and story_sections.get(scope.get("story_id")) == section
            )
        else:
            sections = context.get("sections")
            section_applies = isinstance(sections, set) and section in sections
    if not section_applies:
        return False
    if level == "global":
        return True
    if level == "facts":
        scope_facts = scope.get("fact_ids")
        context_facts = context.get("facts")
        return (
            isinstance(scope_facts, list)
            and isinstance(context_facts, set)
            and set(scope_facts).issubset(context_facts)
        )
    if level == "story":
        stories = context.get("stories")
        return (
            scope["resume"] == context["resume"]
            and isinstance(stories, set)
            and scope["story_id"] in stories
        )
    if level == "resume":
        return scope["resume"] == context["resume"]
    return scope["direction"] == context["direction"]


def resolve_for_plan(
    plan: SynthesisPlan,
    project_root: Path,
    *,
    include_open: bool = False,
) -> list[dict[str, object]]:
    """Resolve current accepted rules and optionally unfinished session guidance."""
    root = project_root.expanduser().resolve()
    context = _context(plan, root)
    resolved: list[dict[str, object]] = []
    open_records: list[dict[str, object]] = []
    suppressed_rule_ids: set[str] = set()
    if include_open:
        for path in sorted((root / "build" / "feedback").glob("FB-*.json")):
            session = _read_json(path, "feedback session")
            _validate_session(session, path, root)
            if session["status"] != "open" or not _applies(session["identity"]["scope"], context):
                continue
            current = session["revisions"][session["current_revision"] - 1]
            suppressed_rule_ids.add(str(session["rule_id"]))
            promoted_rule = session.get("promoted_rule")
            if isinstance(promoted_rule, dict) and isinstance(promoted_rule.get("id"), str):
                suppressed_rule_ids.add(str(promoted_rule["id"]))
            open_records.append(
                {
                    "source": "open-session",
                    "id": session["id"],
                    "rule_id": session["rule_id"],
                    "revision": session["current_revision"],
                    "kind": session["identity"]["kind"],
                    "strength": session["strength"],
                    "scope": session["identity"]["scope"],
                    "instruction": current["instruction"],
                    "must_preserve": current["must_preserve"],
                    "must_avoid": current["must_avoid"],
                    "preferred_examples": current["preferred_examples"],
                    "effective_digest": _effective_digest(
                        session["identity"], session["strength"], current
                    ),
                    "path": path.relative_to(root).as_posix(),
                    "sha256": _file_digest(path),
                }
            )
    for path in sorted((root / "editorial" / "rules").glob("ER-*.json")):
        rule = _read_json(path, "feedback rule")
        _validate_rule(rule, path, root)
        if (
            rule["status"] == "active"
            and rule["id"] not in suppressed_rule_ids
            and _applies(rule["identity"]["scope"], context)
        ):
            resolved.append({"source": "accepted-rule", **_rule_record(path, rule, root)})
    resolved.extend(open_records)
    return sorted(resolved, key=lambda item: (str(item["effective_digest"]), str(item["id"])))


def guidance_snapshot(
    plan: SynthesisPlan,
    project_root: Path,
) -> dict[str, object]:
    """Return applicable guidance with a storage-state-independent fingerprint."""
    guidance = resolve_for_plan(plan, project_root, include_open=True)
    digests = sorted(str(item["effective_digest"]) for item in guidance)
    return {
        "guidance": guidance,
        "fingerprint": _text_digest(json.dumps(digests, separators=(",", ":"))),
    }


def manifest_guidance_freshness(
    manifest: dict[str, Any],
    project_root: Path,
    vault_root: Path,
) -> list[str]:
    """Compare a build's effective guidance with the currently applicable set."""
    memory = manifest.get("feedback_memory")
    synthesis = manifest.get("synthesis")
    if not isinstance(memory, dict) or not isinstance(memory.get("fingerprint"), str):
        return ["compiled build feedback-memory fingerprint is missing"]
    if not isinstance(synthesis, dict) or not isinstance(synthesis.get("path"), str):
        return ["compiled build synthesis record is missing"]
    try:
        plan = load_synthesis_plan(
            Path(str(synthesis["path"])),
            project_root,
            vault_root,
        )
        current = guidance_snapshot(plan, project_root)
    except (OSError, ValueError) as exc:
        return [f"current feedback guidance is invalid: {exc}"]
    if current["fingerprint"] != memory["fingerprint"]:
        return ["applicable feedback guidance changed after compilation"]
    return []


def resolve_feedback(
    plan_path: Path,
    project_root: Path,
    vault_root: Path,
    *,
    include_open: bool = False,
) -> dict[str, object]:
    root = project_root.expanduser().resolve()
    plan = load_synthesis_plan(plan_path, root, vault_root.expanduser().resolve())
    rules = resolve_for_plan(plan, root, include_open=include_open)
    return {
        "valid": True,
        "plan": plan.source.relative_to(root).as_posix(),
        "resume": plan.resume.relative_to(root).as_posix(),
        "rules": rules,
        "count": len(rules),
    }


def validate_feedback_memory(project_root: Path) -> dict[str, object]:
    """Validate existing memory while treating missing directories as an empty install."""
    root = project_root.expanduser().resolve()
    errors: list[str] = []
    sessions = 0
    open_sessions = 0
    rules = 0
    active_rules = 0
    for path in sorted((root / "build" / "feedback").glob("*.json")):
        try:
            value = _read_json(path, "feedback session")
            _validate_session(value, path, root)
            sessions += 1
            open_sessions += value["status"] == "open"
        except ValueError as exc:
            errors.append(str(exc))
    for path in sorted((root / "editorial" / "rules").glob("*.json")):
        try:
            value = _read_json(path, "feedback rule")
            _validate_rule(value, path, root)
            rules += 1
            active_rules += value["status"] == "active"
        except ValueError as exc:
            errors.append(str(exc))
    return {
        "valid": not errors,
        "sessions": sessions,
        "open_sessions": open_sessions,
        "rules": rules,
        "active_rules": active_rules,
        "errors": errors,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="action", required=True)
    record_parser = subparsers.add_parser("record", help="Record or revise one feedback session")
    record_parser.add_argument("plan", type=Path)
    record_parser.add_argument("--session")
    accept_parser = subparsers.add_parser("accept", help="Promote accepted feedback")
    accept_parser.add_argument("session_id", nargs="?")
    accept_parser.add_argument("--resume", type=Path)
    accept_parser.add_argument("--preview", type=Path)
    resolve_parser = subparsers.add_parser("resolve", help="Resolve guidance for one plan")
    resolve_parser.add_argument("plan", type=Path)
    resolve_parser.add_argument("--vault-root", type=Path, default=Path("vault"))
    resolve_parser.add_argument("--include-open", action="store_true")
    retire_parser = subparsers.add_parser("retire", help="Retire one accepted feedback rule")
    retire_parser.add_argument("rule_id")
    retire_parser.add_argument("--reason", required=True)
    validate_parser = subparsers.add_parser(
        "validate", help="Validate sessions and accepted memory"
    )
    status_parser = subparsers.add_parser("status", help="Summarize sessions and accepted memory")
    for subparser in (
        record_parser,
        accept_parser,
        resolve_parser,
        retire_parser,
        validate_parser,
        status_parser,
    ):
        subparser.add_argument("--project-root", type=Path, default=Path("."))
    args = parser.parse_args(argv)
    root = args.project_root.expanduser().resolve()
    try:
        if args.action == "record":
            result = record_feedback(args.plan, root, session_id=args.session)
        elif args.action == "accept":
            result = accept_feedback(
                root,
                session_id=args.session_id,
                resume=args.resume,
                preview=args.preview,
            )
        elif args.action == "resolve":
            vault_root = args.vault_root
            if not vault_root.is_absolute():
                vault_root = root / vault_root
            result = resolve_feedback(
                args.plan,
                root,
                vault_root,
                include_open=args.include_open,
            )
        elif args.action == "retire":
            result = retire_feedback_rule(args.rule_id, args.reason, root)
        else:
            result = validate_feedback_memory(root)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": str(exc)}, indent=2), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    return 0 if result.get("valid") is True else 2


if __name__ == "__main__":
    raise SystemExit(main())
