"""Record conversational feedback sessions and revisions."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .atomic import atomic_write_json
from .feedback_resolution import (
    KINDS,
    PROMOTIONS,
    RULE_ID,
    SCOPE_LEVELS,
    SESSION_ID,
    STRENGTHS,
    SUBJECT_KEY,
    _effective_digest,
    _exact_fields,
    _identity_digest,
    _nonempty,
    _object,
    _project_file,
    _read_json,
    _string_list,
    _text_digest,
    _validate_session,
)
from .layout import contained_path


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _block_inventory(resume: Path) -> dict[str, dict[str, object]]:
    from .resume_parser import compile_markdown

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
