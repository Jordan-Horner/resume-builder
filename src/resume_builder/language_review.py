"""Prepare and validate the always-on independent resume language review."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .artifact_paths import resume_output_base
from .artifact_status import build_manifest_freshness
from .atomic import atomic_write_json
from .compilation import relative_output, sha256_file
from .layout import contained_path
from .review_blocks import NarrativeReviewBlock, narrative_block_inventory
from .review_schema import sha256_text

LANGUAGE_REVIEW_METHOD = "independent-cold-review"
LANGUAGE_REVIEW_STATUSES = {"approved", "changes-required"}
LANGUAGE_BLOCK_DECISIONS = {"approved", "revise"}
LANGUAGE_REVIEW_STANDARD = {
    "version": 5,
    "context_test": (
        "Can a reviewer identify the actor, action, object, and why the claim matters "
        "using only the visible block and its supplied context?"
    ),
    "unstated_premise_rule": (
        "Reject prose when its central meaning depends on an unstated premise, omitted "
        "mechanism, unexplained internal name, or relationship the reader must invent."
    ),
    "concrete_object_rule": (
        "Judge whether the action's object identifies a decision-relevant system, "
        "deliverable, operation, or change. Reject a grammatically complete but "
        "semantically generic object when the reader still cannot tell what work occurred. "
        "A clearly named position, formal assignment, or trusted role may itself be the "
        "decision-relevant value when its relationship and scope are explicit; do not require "
        "an invented task, deliverable, or outcome to make that position valid."
    ),
    "summary_inventory_rule": (
        "Reject a summary sentence whose main function is to inventory technologies, "
        "capabilities, responsibilities, or matched requirements. A summary must establish "
        "a clear hiring position and use only the limited detail needed to support it; move "
        "secondary retrieval terms to experience or technical skills."
    ),
    "summary_positioning_rule": (
        "Judge the summary opening against the intended target and supplied evidence. Reject "
        "a broad prior-role, legacy-function, or generic umbrella identity when sufficient "
        "direct evidence supports the intended role family and the opening would cause a "
        "recruiter to misclassify the candidate. For adjacent or exploratory evidence, "
        "require an honest bridge or proof-led opening rather than an unsupported target title."
    ),
    "summary_completeness_rule": (
        "Judge summary readability and completeness from the supplied visible context without "
        "prescribing new evidence or a sentence count. Flag a supported result or differentiator "
        "when it is already visible but buried inside a dense sentence, and reject filler added "
        "only to reach a preferred length. Do not reject a clear two-sentence summary merely "
        "because a third sentence could exist."
    ),
    "boundary": (
        "Apply these rules through contextual meaning, not exact-word matching, a "
        "banned-term list, or a requirement to explain every implementation detail."
    ),
}


def language_review_paths(project_root: Path, resume: Path) -> dict[str, Path]:
    """Return the stable standalone language-review artifact paths."""
    base = project_root / "build" / "reviews" / resume.stem
    return {
        "cold": base.with_name(f"{base.name}.language.cold.json"),
        "decisions": base.with_name(f"{base.name}.language.decisions.json"),
        "record": base.with_name(f"{base.name}.language.json"),
    }


def _path_record(path: Path, project_root: Path) -> dict[str, str]:
    return {
        "path": relative_output(path, project_root),
        "sha256": sha256_file(path),
    }


def _load_json(path: Path, owner: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid {owner}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{owner} must be a JSON object")
    return value


def _exact_fields(value: dict[str, Any], expected: set[str], owner: str) -> None:
    missing = sorted(expected - value.keys())
    unexpected = sorted(value.keys() - expected)
    if missing or unexpected:
        raise ValueError(f"{owner} fields mismatch; missing={missing}, unexpected={unexpected}")


def _resolve_resume(resume: Path, project_root: Path) -> Path:
    source = resume.expanduser()
    path = (
        source.resolve()
        if source.is_absolute()
        else contained_path(project_root, source.as_posix(), "resume")
    )
    resumes_root = (project_root / "resumes").resolve()
    if not path.is_relative_to(resumes_root) or not path.is_file():
        raise ValueError("resume must name an existing file under resumes/")
    return path


def _resolve_target(target: Path | None, project_root: Path) -> Path | None:
    if target is None:
        return None
    source = target.expanduser()
    path = (
        source.resolve()
        if source.is_absolute()
        else contained_path(project_root, source.as_posix(), "language review target")
    )
    targets_root = (project_root / "targets").resolve()
    if not path.is_relative_to(targets_root) or not path.is_file():
        raise ValueError("language review target must name an existing file under targets/")
    return path


def _record_blocks(record: dict[str, Any]) -> dict[str, dict[str, Any]]:
    review = record.get("language_review")
    values = review.get("blocks") if isinstance(review, dict) else None
    if not isinstance(values, list):
        return {}
    return {
        str(block.get("id")): block
        for block in values
        if isinstance(block, dict)
        and isinstance(block.get("id"), str)
        and block.get("decision") == "approved"
    }


def _visible_items(
    payload: dict[str, Any], owner: str, fields: tuple[str, ...]
) -> list[dict[str, Any]]:
    """Return visible, non-evidence fields from one compiled resume collection."""
    values = payload.get(owner, [])
    if not isinstance(values, list):
        raise ValueError(f"compiled resume {owner} must be a list")
    visible: list[dict[str, Any]] = []
    for index, value in enumerate(values):
        if not isinstance(value, dict):
            raise ValueError(f"compiled resume {owner}[{index}] must be an object")
        visible.append({field: value[field] for field in fields if field in value})
    return visible


def _visible_resume_context(
    payload: dict[str, Any], inventory: tuple[NarrativeReviewBlock, ...]
) -> dict[str, Any]:
    """Return reader-visible context without contact data, evidence, or builder rationale."""
    candidate = payload.get("candidate")
    if not isinstance(candidate, dict):
        raise ValueError("compiled resume candidate must be an object")
    headline = candidate.get("headline")
    return {
        "headline": headline.strip() if isinstance(headline, str) else None,
        "narrative_blocks": [
            {
                "id": block.id,
                "text": block.text,
                "context": {
                    key: value for key, value in block.context.items() if key != "candidate_name"
                },
            }
            for block in inventory
        ],
        "education": _visible_items(payload, "education", ("title", "org", "year", "description")),
        "certifications": _visible_items(payload, "certifications", ("title", "org", "year")),
        "technical_skills": _visible_items(payload, "skills", ("category", "items")),
    }


def prepare_language_review(
    resume: Path,
    project_root: Path,
    *,
    target: Path | None = None,
) -> dict[str, Any]:
    """Freeze only new or changed narrative blocks for an independent cold read."""
    resolved_root = project_root.expanduser().resolve()
    resume_path = _resolve_resume(resume, resolved_root)
    target_path = _resolve_target(target, resolved_root)
    paths = language_review_paths(resolved_root, resume_path)
    manifest_path = resume_output_base(resolved_root, resume_path).with_suffix(".manifest.json")
    build_reasons = build_manifest_freshness(manifest_path, resolved_root)
    if build_reasons:
        raise ValueError(
            "language review requires a current compiled build: " + "; ".join(build_reasons)
        )

    current_reasons = language_review_freshness(paths["record"], resolved_root, resume_path)
    if not current_reasons:
        current = _load_json(paths["record"], "language review record")
        return {
            "valid": True,
            "cached": True,
            "record": relative_output(paths["record"], resolved_root),
            "status": current["language_review"]["status"],
            "pending_blocks": 0,
            "review_inputs": None,
        }

    prior_record: dict[str, str] | None = None
    prior_approved: dict[str, dict[str, Any]] = {}
    if paths["record"].is_file():
        try:
            prior = _load_json(paths["record"], "prior language review record")
            _validate_language_record_shape(prior, resolved_root)
        except ValueError:
            prior = None
        if prior is not None:
            prior_record = _path_record(paths["record"], resolved_root)
            prior_approved = _record_blocks(prior)

    inventory = narrative_block_inventory(resume_path)
    payload_path = resume_output_base(resolved_root, resume_path).with_suffix(".json")
    payload = _load_json(payload_path, "compiled resume")
    pending = [
        block
        for block in inventory
        if not (
            block.id in prior_approved
            and prior_approved[block.id].get("sha256") == sha256_text(block.text)
        )
    ]
    generated_at = datetime.now(timezone.utc).isoformat()
    target_record = _path_record(target_path, resolved_root) if target_path is not None else None
    cold = {
        "version": 2,
        "phase": "language-cold-read",
        "generated_at": generated_at,
        "resume": _path_record(resume_path, resolved_root),
        "target": target_record,
        "target_text": target_path.read_text(encoding="utf-8") if target_path is not None else None,
        "scope": "changed-narrative-prose" if prior_record is not None else "all-narrative-prose",
        "review_standard": LANGUAGE_REVIEW_STANDARD,
        "resume_context": _visible_resume_context(payload, inventory),
        "blocks": [
            {
                "id": block.id,
                "sha256": sha256_text(block.text),
                "text": block.text,
                "context": block.context,
                "advisories": list(block.advisories),
            }
            for block in pending
        ],
    }
    paths["cold"].parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(paths["cold"], cold)
    decisions = {
        "version": 1,
        "generated_at": generated_at,
        "review_inputs": {
            "resume": _path_record(resume_path, resolved_root),
            "build_manifest": _path_record(manifest_path, resolved_root),
            "target": target_record,
            "cold_read": _path_record(paths["cold"], resolved_root),
            "prior_review": prior_record,
        },
        "reviewer": {"method": LANGUAGE_REVIEW_METHOD, "context": ""},
        "language_review": {
            "status": None,
            "blocks": [
                {
                    "id": block.id,
                    "sha256": sha256_text(block.text),
                    "decision": None,
                    "note": "",
                }
                for block in pending
            ],
        },
    }
    atomic_write_json(paths["decisions"], decisions)
    return {
        "valid": True,
        "cached": False,
        "source": relative_output(resume_path, resolved_root),
        "pending_blocks": len(pending),
        "review_inputs": {
            "cold_read": _path_record(paths["cold"], resolved_root),
            "decisions": relative_output(paths["decisions"], resolved_root),
            "prior_approved_blocks": len(inventory) - len(pending),
        },
        "next_action": "Send only the cold-read file to an independent language reviewer, complete the decisions, and run review language-finalize.",
    }


def _validate_language_record_shape(record: dict[str, Any], project_root: Path) -> None:
    _exact_fields(
        record,
        {
            "version",
            "reviewed_at",
            "reviewer",
            "resume",
            "build_manifest",
            "target",
            "cold_read",
            "language_review",
        },
        "language review record",
    )
    if record.get("version") != 1:
        raise ValueError("language review record must declare version 1")
    reviewer = record.get("reviewer")
    if not isinstance(reviewer, dict) or set(reviewer) != {"method", "context"}:
        raise ValueError("language review reviewer is invalid")
    if reviewer.get("method") != LANGUAGE_REVIEW_METHOD:
        raise ValueError("approved language review requires an independent cold reviewer")
    context = reviewer.get("context")
    if not isinstance(context, str) or not context.strip():
        raise ValueError("language review reviewer context must be non-empty")
    for owner in ("resume", "build_manifest", "cold_read"):
        value = record.get(owner)
        if not isinstance(value, dict) or set(value) != {"path", "sha256"}:
            raise ValueError(f"language review {owner} pin is invalid")
        path_value = value.get("path")
        digest = value.get("sha256")
        if not isinstance(path_value, str) or not isinstance(digest, str):
            raise ValueError(f"language review {owner} pin is invalid")
        path = contained_path(project_root, path_value, f"language review {owner}")
        if not path.is_file():
            raise ValueError(f"language review {owner} file is missing")
    target = record.get("target")
    if target is not None and (
        not isinstance(target, dict)
        or set(target) != {"path", "sha256"}
        or not isinstance(target.get("path"), str)
        or not isinstance(target.get("sha256"), str)
    ):
        raise ValueError("language review target pin is invalid")
    review = record.get("language_review")
    if not isinstance(review, dict) or set(review) != {"status", "blocks"}:
        raise ValueError("language review decision set is invalid")
    if review.get("status") not in LANGUAGE_REVIEW_STATUSES:
        raise ValueError("language review status is invalid")
    blocks = review.get("blocks")
    if not isinstance(blocks, list) or not blocks:
        raise ValueError("language review must cover at least one narrative block")
    for index, block in enumerate(blocks):
        if not isinstance(block, dict) or set(block) != {"id", "sha256", "decision", "note"}:
            raise ValueError(f"language review block[{index}] is invalid")
        if block.get("decision") not in LANGUAGE_BLOCK_DECISIONS:
            raise ValueError(f"language review block[{index}] decision is invalid")
        note = block.get("note")
        if not isinstance(note, str) or (block.get("decision") == "revise" and not note.strip()):
            raise ValueError(f"language review block[{index}] note is invalid")


def finalize_language_review(
    decisions: Path,
    project_root: Path,
    *,
    output: Path | None = None,
) -> dict[str, Any]:
    """Finalize independent decisions while carrying exact unchanged approvals forward."""
    resolved_root = project_root.expanduser().resolve()
    decisions_path = decisions.expanduser()
    decisions_path = (
        decisions_path.resolve()
        if decisions_path.is_absolute()
        else contained_path(resolved_root, decisions_path.as_posix(), "language decisions")
    )
    reviews_root = (resolved_root / "build" / "reviews").resolve()
    if decisions_path.parent != reviews_root or not decisions_path.name.endswith(
        ".language.decisions.json"
    ):
        raise ValueError(
            "language decisions must be a *.language.decisions.json file under build/reviews/"
        )
    data = _load_json(decisions_path, "language review decisions")
    _exact_fields(
        data,
        {"version", "generated_at", "review_inputs", "reviewer", "language_review"},
        "language review decisions",
    )
    if data.get("version") != 1:
        raise ValueError("language review decisions must declare version 1")
    inputs = data.get("review_inputs")
    if not isinstance(inputs, dict):
        raise ValueError("language review inputs must be an object")
    _exact_fields(
        inputs,
        {"resume", "build_manifest", "target", "cold_read", "prior_review"},
        "language review inputs",
    )
    for owner in ("resume", "build_manifest", "cold_read"):
        pin = inputs.get(owner)
        if not isinstance(pin, dict) or set(pin) != {"path", "sha256"}:
            raise ValueError(f"language review input {owner} is invalid")
        path = contained_path(resolved_root, pin.get("path"), f"language review {owner}")
        if not path.is_file() or sha256_file(path) != pin.get("sha256"):
            raise ValueError(f"language review input {owner} changed")
    resume_pin = inputs["resume"]
    resume_path = contained_path(resolved_root, resume_pin["path"], "language review resume")
    cold_path = contained_path(resolved_root, inputs["cold_read"]["path"], "language cold read")
    cold = _load_json(cold_path, "language cold read")
    cold_blocks = cold.get("blocks")
    if not isinstance(cold_blocks, list):
        raise ValueError("language cold read blocks must be a list")
    cold_pins = {
        str(block.get("id")): str(block.get("sha256"))
        for block in cold_blocks
        if isinstance(block, dict)
    }

    reviewer = data.get("reviewer")
    if not isinstance(reviewer, dict) or set(reviewer) != {"method", "context"}:
        raise ValueError("language review reviewer is invalid")
    if reviewer.get("method") != LANGUAGE_REVIEW_METHOD:
        raise ValueError("language review must use an independent cold reviewer")
    context = reviewer.get("context")
    if not isinstance(context, str) or not context.strip():
        raise ValueError("language review reviewer context must be non-empty")

    review = data.get("language_review")
    if not isinstance(review, dict) or set(review) != {"status", "blocks"}:
        raise ValueError("language review decisions are invalid")
    status = review.get("status")
    if status not in LANGUAGE_REVIEW_STATUSES:
        raise ValueError("language review status must be approved or changes-required")
    decision_values = review.get("blocks")
    if not isinstance(decision_values, list):
        raise ValueError("language review decisions blocks must be a list")
    decisions_by_id: dict[str, dict[str, Any]] = {}
    for index, block in enumerate(decision_values):
        owner = f"language review decision block[{index}]"
        if not isinstance(block, dict):
            raise ValueError(f"{owner} must be an object")
        _exact_fields(block, {"id", "sha256", "decision", "note"}, owner)
        block_id = block.get("id")
        if not isinstance(block_id, str) or block_id in decisions_by_id:
            raise ValueError(f"{owner} has an invalid or duplicate id")
        if block.get("decision") not in LANGUAGE_BLOCK_DECISIONS:
            raise ValueError(f"{owner} decision must be approved or revise")
        note = block.get("note")
        if not isinstance(note, str) or (block.get("decision") == "revise" and not note.strip()):
            raise ValueError(f"{owner} note must explain a revise decision")
        decisions_by_id[block_id] = block
    decision_pins = {key: str(value.get("sha256")) for key, value in decisions_by_id.items()}
    if decision_pins != cold_pins:
        raise ValueError("language decisions do not cover the exact cold-read blocks")
    advisories = {
        str(block.get("id")): block.get("advisories")
        for block in cold_blocks
        if isinstance(block, dict)
    }
    missing_advisory_notes = sorted(
        block_id
        for block_id, block in decisions_by_id.items()
        if block.get("decision") == "approved"
        and advisories.get(block_id)
        and not str(block.get("note", "")).strip()
    )
    if missing_advisory_notes:
        raise ValueError(
            "approved language blocks with advisories require a reviewer note: "
            f"{missing_advisory_notes}"
        )

    prior_approved: dict[str, dict[str, Any]] = {}
    prior_pin = inputs.get("prior_review")
    if prior_pin is not None:
        if not isinstance(prior_pin, dict) or set(prior_pin) != {"path", "sha256"}:
            raise ValueError("prior language review pin is invalid")
        prior_path = contained_path(
            resolved_root, prior_pin.get("path"), "prior language review record"
        )
        if not prior_path.is_file() or sha256_file(prior_path) != prior_pin.get("sha256"):
            raise ValueError("prior language review changed after preparation")
        prior = _load_json(prior_path, "prior language review record")
        _validate_language_record_shape(prior, resolved_root)
        prior_approved = _record_blocks(prior)

    final_blocks: list[dict[str, Any]] = []
    for block in narrative_block_inventory(resume_path):
        digest = sha256_text(block.text)
        decision = decisions_by_id.get(block.id)
        if decision is None:
            prior_block = prior_approved.get(block.id)
            if prior_block is None or prior_block.get("sha256") != digest:
                raise ValueError(f"language review is missing current block: {block.id}")
            decision = prior_block
        final_blocks.append(
            {
                "id": block.id,
                "sha256": digest,
                "decision": decision.get("decision"),
                "note": str(decision.get("note", "")).strip(),
            }
        )
    has_revisions = any(block["decision"] == "revise" for block in final_blocks)
    if status == "approved" and has_revisions:
        raise ValueError("approved language review cannot contain revise decisions")
    if status == "changes-required" and not has_revisions:
        raise ValueError("changes-required language review requires a revise decision")

    record = {
        "version": 1,
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
        "reviewer": {"method": LANGUAGE_REVIEW_METHOD, "context": context.strip()},
        "resume": inputs["resume"],
        "build_manifest": inputs["build_manifest"],
        "target": inputs["target"],
        "cold_read": inputs["cold_read"],
        "language_review": {"status": status, "blocks": final_blocks},
    }
    destination = output or language_review_paths(resolved_root, resume_path)["record"]
    destination = (
        destination.resolve()
        if destination.is_absolute()
        else contained_path(resolved_root, destination.as_posix(), "language review output")
    )
    if destination.parent != reviews_root or not destination.name.endswith(".language.json"):
        raise ValueError(
            "language review output must be a *.language.json file under build/reviews/"
        )
    atomic_write_json(destination, record)
    reasons = language_review_freshness(destination, resolved_root, resume_path)
    if reasons:
        raise ValueError("language review is stale or incomplete: " + "; ".join(reasons))
    return {
        "valid": True,
        "record": relative_output(destination, resolved_root),
        "status": status,
        "blocks": len(final_blocks),
        "reviewed_blocks": len(decisions_by_id),
        "carried_blocks": len(final_blocks) - len(decisions_by_id),
    }


def language_review_freshness(
    record_path: Path,
    project_root: Path,
    resume: Path | None = None,
) -> list[str]:
    """Return deterministic reasons a standalone language review is not current."""
    resolved_root = project_root.expanduser().resolve()
    source = record_path.expanduser()
    source = (
        source.resolve()
        if source.is_absolute()
        else contained_path(resolved_root, source.as_posix(), "language review record")
    )
    if not source.is_file():
        return ["language review record is missing"]
    try:
        record = _load_json(source, "language review record")
        _validate_language_record_shape(record, resolved_root)
    except ValueError as exc:
        return [str(exc)]
    reasons: list[str] = []
    for owner in ("resume", "build_manifest", "cold_read"):
        pin = record[owner]
        path = contained_path(resolved_root, pin["path"], f"language review {owner}")
        if sha256_file(path) != pin["sha256"]:
            reasons.append(f"language review {owner} changed")
    target = record.get("target")
    if isinstance(target, dict):
        path = contained_path(resolved_root, target["path"], "language review target")
        if not path.is_file() or sha256_file(path) != target["sha256"]:
            reasons.append("language review target changed")
    resume_path = contained_path(resolved_root, record["resume"]["path"], "language resume")
    if resume is not None and resume_path != resume.resolve():
        reasons.append("language review names a different resume")
    manifest_path = contained_path(
        resolved_root, record["build_manifest"]["path"], "language build manifest"
    )
    reasons.extend(build_manifest_freshness(manifest_path, resolved_root))
    expected = {
        block.id: sha256_text(block.text) for block in narrative_block_inventory(resume_path)
    }
    reviewed = {
        str(block.get("id")): str(block.get("sha256"))
        for block in record["language_review"]["blocks"]
        if isinstance(block, dict)
    }
    if expected != reviewed:
        reasons.append("language review does not cover the exact current narrative blocks")
    return list(dict.fromkeys(reasons))


def current_language_review(resume: Path, project_root: Path) -> dict[str, Any]:
    """Return the current standalone review status or raise with actionable reasons."""
    resolved_root = project_root.expanduser().resolve()
    resume_path = _resolve_resume(resume, resolved_root)
    record_path = language_review_paths(resolved_root, resume_path)["record"]
    reasons = language_review_freshness(record_path, resolved_root, resume_path)
    if reasons:
        raise ValueError(
            "current independent natural-language review is required: " + "; ".join(reasons)
        )
    record = _load_json(record_path, "language review record")
    review = record["language_review"]
    issues = [
        {"id": block["id"], "note": block["note"]}
        for block in review["blocks"]
        if block["decision"] == "revise"
    ]
    return {
        "path": record_path,
        "sha256": sha256_file(record_path),
        "status": review["status"],
        "issues": issues,
        "blocks": len(review["blocks"]),
    }
