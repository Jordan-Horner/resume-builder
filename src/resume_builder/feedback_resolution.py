"""Resolve and validate feedback guidance without importing review workflows."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

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
    """Return semantic compliance guidance independent of drafting examples."""
    return {
        "identity": identity,
        "strength": strength,
        "instruction": revision["instruction"],
        "must_preserve": revision["must_preserve"],
        "must_avoid": revision["must_avoid"],
    }


def _effective_digest(
    identity: dict[str, Any],
    strength: object,
    revision: dict[str, Any],
) -> str:
    payload = _effective_payload(identity, strength, revision)
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


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
        common = {
            "resume_sha256",
            "build_manifest",
            "build_sha256",
            "preview_manifest",
            "preview_sha256",
            "output",
            "output_sha256",
            "effective_digest",
        }
        reviewed = common | {"review_record", "review_sha256"}
        user_approved = common | {"approval"}
        actual = set(result)
        if actual == reviewed:
            expected = reviewed
        elif actual == user_approved and result.get("approval") == "user-approved-preview":
            expected = user_approved
        else:
            raise ValueError(
                f"{path} accepted_result must pin either a reviewed preview or a "
                "user-approved preview"
            )
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


def _rule_record(
    path: Path,
    data: dict[str, Any],
    project_root: Path,
    *,
    semantic_only: bool = False,
) -> dict[str, object]:
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
        "preferred_examples": [] if semantic_only else current["preferred_examples"],
        "effective_digest": _effective_digest(data["identity"], data["strength"], current),
        "path": path.relative_to(project_root).as_posix(),
        "sha256": _file_digest(path),
    }


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
    semantic_only: bool = False,
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
                    "preferred_examples": [] if semantic_only else current["preferred_examples"],
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
            resolved.append(
                {
                    "source": "accepted-rule",
                    **_rule_record(path, rule, root, semantic_only=semantic_only),
                }
            )
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
