"""Finalize reviewer decisions into hash-pinned review records."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .atomic import atomic_write_json
from .layout import contained_path
from .review_approval import review_freshness
from .review_schema import (
    EDITORIAL_SCOPE,
    FEEDBACK_DECISIONS,
    FEEDBACK_STATUSES,
    _exact_fields,
    _object,
    _source_input,
    load_review_record,
    sha256_file,
)
from .selection_guard import (
    guard_selection,
    matching_repair_handoff,
    selection_digest,
    write_selection_seal,
)
from .selection_review import (
    require_approved_selection_review,
)


def finalize_review_record(
    decisions: Path,
    project_root: Path,
    *,
    output: Path | None = None,
) -> dict[str, Any]:
    """Build and validate a version 4 review record from reviewer decisions."""
    resolved_root = project_root.expanduser().resolve()
    decisions_path = decisions.expanduser()
    decisions_path = (
        decisions_path.resolve()
        if decisions_path.is_absolute()
        else contained_path(resolved_root, decisions_path.as_posix(), "review decisions")
    )
    reviews_root = (resolved_root / "build" / "reviews").resolve()
    if decisions_path.parent != reviews_root or not decisions_path.name.endswith(".decisions.json"):
        raise ValueError("review decisions must be a *.decisions.json file under build/reviews/")
    try:
        raw = json.loads(decisions_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid review decisions {decisions_path}: {exc}") from exc
    data = _object(raw, "review decisions")
    decisions_version = data.get("version")
    if decisions_version not in {1, 2, 3}:
        raise ValueError("review decisions must declare version 1, 2, or 3")
    decision_fields = {
        "version",
        "generated_at",
        "review_inputs",
        "reviewer",
        "verdict",
        "hiring_read",
        "findings",
        "next_action",
        "language_review",
    }
    if decisions_version >= 3:
        decision_fields.add("feedback_review")
    _exact_fields(data, decision_fields, "review decisions")
    review_inputs = _object(data["review_inputs"], "review decisions.review_inputs")
    _exact_fields(
        review_inputs,
        {"cold_read", "review_package"},
        "review decisions.review_inputs",
    )
    cold_read = _source_input(
        review_inputs["cold_read"], "review decisions cold_read", resolved_root, "build/reviews"
    )
    review_package = _source_input(
        review_inputs["review_package"],
        "review decisions review_package",
        resolved_root,
        "build/reviews",
    )
    for item, owner in (
        (cold_read, "cold-read package"),
        (review_package, "review package"),
    ):
        if sha256_file(item.path) != item.sha256:
            raise ValueError(f"{owner} changed after reviewer decisions were prepared")
    try:
        package = json.loads(review_package.path.read_text(encoding="utf-8"))
        cold = json.loads(cold_read.path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid pinned review input: {exc}") from exc
    package_data = _object(package, "review package")
    cold_data = _object(cold, "cold-read package")
    if package_data.get("version") != 1 or cold_data.get("version") != 1:
        raise ValueError("review inputs must declare version 1")
    if package_data.get("cold_read") != review_inputs["cold_read"]:
        raise ValueError("review package does not pin the selected cold-read package")

    selection_appendix = _object(
        package_data.get("selection_appendix"), "review package selection_appendix"
    )
    memory = _object(
        selection_appendix.get("feedback_memory"),
        "review package feedback_memory",
    )
    package_feedback_rules = memory.get("rules")
    if not isinstance(package_feedback_rules, list):
        raise ValueError("review package feedback_memory.rules must be a list")
    if package_feedback_rules and decisions_version < 3:
        raise ValueError("applicable feedback rules require review decisions version 3")

    language_review = _object(data["language_review"], "review decisions.language_review")
    _exact_fields(language_review, {"status", "blocks"}, "review decisions.language_review")
    package_blocks = cold_data.get("blocks")
    if not isinstance(package_blocks, list) or not package_blocks:
        raise ValueError("cold-read package has no narrative blocks")
    decision_blocks = language_review.get("blocks")
    if not isinstance(decision_blocks, list) or not decision_blocks:
        raise ValueError("review decisions have no narrative blocks")
    normalized_decision_blocks: list[dict[str, object]] = []
    for index, value in enumerate(decision_blocks):
        owner = f"review decisions.language_review.blocks[{index}]"
        block = _object(value, owner)
        expected_fields = {"id", "sha256", "decision", "note"}
        if decisions_version >= 2:
            expected_fields.add("repair")
        _exact_fields(block, expected_fields, owner)
        repair = block.get("repair")
        if repair is not None:
            repair_data = _object(repair, f"{owner}.repair")
            _exact_fields(repair_data, {"kind", "replacement"}, f"{owner}.repair")
            if repair_data.get("kind") != "wording-only":
                raise ValueError(f"{owner}.repair.kind must be 'wording-only'")
            replacement = repair_data.get("replacement")
            if not isinstance(replacement, str) or not replacement.strip():
                raise ValueError(f"{owner}.repair.replacement must be non-empty prose")
            if block.get("decision") != "revise":
                raise ValueError(f"{owner}.repair requires a revise decision")
        normalized_decision_blocks.append(
            {
                "id": block.get("id"),
                "sha256": block.get("sha256"),
                "decision": block.get("decision"),
                "note": block.get("note"),
            }
        )

    normalized_feedback_rules: list[dict[str, object]] = []
    feedback_status = "not-applicable"
    if decisions_version >= 3:
        feedback_review = _object(data["feedback_review"], "review decisions.feedback_review")
        _exact_fields(feedback_review, {"status", "rules"}, "review decisions.feedback_review")
        raw_feedback_status = feedback_review.get("status")
        if not isinstance(
            raw_feedback_status, str
        ) or raw_feedback_status not in FEEDBACK_STATUSES - {"not-applicable"}:
            raise ValueError("feedback review.status must be approved or changes-required")
        feedback_status = raw_feedback_status
        decision_rules = feedback_review.get("rules")
        if not isinstance(decision_rules, list) or not decision_rules:
            raise ValueError("feedback review.rules must be a non-empty list")
        package_rule_pins: dict[tuple[str, int], dict[str, Any]] = {}
        for index, raw_rule in enumerate(package_feedback_rules):
            owner = f"review package feedback rule[{index}]"
            rule = _object(raw_rule, owner)
            rule_id = rule.get("id")
            revision = rule.get("revision")
            if not isinstance(rule_id, str) or not isinstance(revision, int):
                raise ValueError(f"{owner} has invalid rule identity")
            package_rule_pins[(rule_id, revision)] = rule
        decision_rule_pins: set[tuple[str, int]] = set()
        for index, raw_rule in enumerate(decision_rules):
            owner = f"review decisions.feedback_review.rules[{index}]"
            rule = _object(raw_rule, owner)
            _exact_fields(rule, {"id", "revision", "sha256", "decision", "note"}, owner)
            rule_id = rule.get("id")
            revision = rule.get("revision")
            digest = rule.get("sha256")
            decision = rule.get("decision")
            note = rule.get("note")
            key = (str(rule_id), revision if isinstance(revision, int) else -1)
            package_rule = package_rule_pins.get(key)
            if package_rule is None or package_rule.get("sha256") != digest:
                raise ValueError(f"{owner} does not match an applicable feedback rule")
            if decision not in FEEDBACK_DECISIONS:
                raise ValueError(f"{owner}.decision must be complies or revise")
            if not isinstance(note, str):
                raise ValueError(f"{owner}.note must be a string")
            if decision == "revise" and not note.strip():
                raise ValueError(f"{owner}.note must explain a revise decision")
            decision_rule_pins.add(key)
            normalized_feedback_rules.append(
                {
                    "id": rule_id,
                    "revision": revision,
                    "path": package_rule.get("path"),
                    "sha256": digest,
                    "decision": decision,
                    "note": note.strip(),
                }
            )
        if decision_rule_pins != set(package_rule_pins):
            raise ValueError("feedback review does not cover the exact applicable rules")
        has_feedback_revisions = any(
            rule["decision"] == "revise" for rule in normalized_feedback_rules
        )
        if feedback_status == "approved" and has_feedback_revisions:
            raise ValueError("approved feedback review cannot contain revise decisions")
        if feedback_status == "changes-required" and not has_feedback_revisions:
            raise ValueError("changes-required feedback review requires a revise decision")
        if feedback_status == "changes-required" and data["verdict"] != "needs-revision":
            raise ValueError("feedback changes-required requires a needs-revision verdict")
        if data["verdict"] != "needs-revision" and feedback_status != "approved":
            raise ValueError("a ready verdict requires approved feedback compliance")
    package_pins = {
        str(_object(block, "cold-read block").get("id")): str(
            _object(block, "cold-read block").get("sha256")
        )
        for block in package_blocks
    }
    decision_pins = {
        str(_object(block, "review decision block").get("id")): str(
            _object(block, "review decision block").get("sha256")
        )
        for block in decision_blocks
    }
    if package_pins != decision_pins:
        raise ValueError("review decisions do not cover the exact cold-read narrative blocks")
    language_pin = package_data.get("language_review")
    if language_pin is not None:
        if not isinstance(language_pin, dict):
            raise ValueError("review package language_review pin is invalid")
        standalone_language = _source_input(
            language_pin,
            "review package language_review",
            resolved_root,
            "build/reviews",
        )
        if sha256_file(standalone_language.path) != standalone_language.sha256:
            raise ValueError("standalone language review changed after packaging")
        try:
            language_data = json.loads(standalone_language.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid standalone language review: {exc}") from exc
        standalone_review = _object(
            language_data.get("language_review"), "standalone language review"
        )
        if standalone_review.get("status") != "approved":
            raise ValueError("packaged standalone language review must be approved")
        standalone_blocks = standalone_review.get("blocks")
        if not isinstance(standalone_blocks, list):
            raise ValueError("standalone language review blocks are invalid")
        standalone_by_id = {
            str(_object(block, "standalone language block").get("id")): _object(
                block, "standalone language block"
            )
            for block in standalone_blocks
        }
        for block_id, approved in standalone_by_id.items():
            current = next(
                (
                    block
                    for block in decision_blocks
                    if isinstance(block, dict) and block.get("id") == block_id
                ),
                None,
            )
            if (
                current is None
                or current.get("sha256") != approved.get("sha256")
                or current.get("decision") != "approved"
                or current.get("note") != approved.get("note")
            ):
                raise ValueError(
                    f"career review cannot reopen standalone approved language block: {block_id}"
                )
    package_resume = _object(package_data.get("resume"), "review package resume")
    package_selection = _object(selection_appendix.get("selection"), "review package selection")
    package_resume_path = contained_path(
        resolved_root, package_resume.get("path"), "review package resume path"
    )
    require_approved_selection_review(resolved_root, package_resume_path)
    handoff = matching_repair_handoff(
        resolved_root,
        package_resume_path,
        str(package_resume.get("sha256")),
        selection_digest(package_selection),
    )
    if handoff is not None:
        decisions_by_id = {
            str(_object(block, "review decision block").get("id")): _object(
                block, "review decision block"
            )
            for block in decision_blocks
        }
        for prior_value in handoff["carried_blocks"]:
            prior = _object(prior_value, "repair handoff carried block")
            block_id = prior.get("id")
            current = decisions_by_id.get(str(block_id))
            if (
                current is None
                or current.get("sha256") != prior.get("sha256")
                or current.get("decision") != "approved"
                or current.get("note") != prior.get("note")
            ):
                raise ValueError(
                    f"repair review cannot reopen unchanged approved block: {block_id}"
                )

    build_manifest_record = _object(
        package_data.get("build_manifest"), "review package build_manifest"
    )
    build_manifest = _source_input(
        build_manifest_record, "review package build_manifest", resolved_root, "build"
    )
    if sha256_file(build_manifest.path) != build_manifest.sha256:
        raise ValueError("compiled build changed after the review package was created")
    try:
        build_data = json.loads(build_manifest.path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid compiled build manifest: {exc}") from exc
    evidence = _object(build_data.get("evidence"), "compiled evidence audit")
    structured_claims = evidence.get("structured_claims_checked")
    if not isinstance(structured_claims, int) or isinstance(structured_claims, bool):
        raise ValueError("compiled evidence audit has no structured-claim count")

    reviewer = _object(data["reviewer"], "review decisions.reviewer")
    findings = _object(data["findings"], "review decisions.findings")
    next_action = _object(data["next_action"], "review decisions.next_action")
    record = {
        "version": 5 if decisions_version >= 3 else 4,
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
        "reviewer": reviewer,
        "resume": package_data.get("resume"),
        "plan": package_data.get("plan"),
        "direction": package_data.get("direction"),
        "target": package_data.get("target"),
        "build_manifest": build_manifest_record,
        "cold_read": review_inputs["cold_read"],
        "review_package": review_inputs["review_package"],
        "evidence_integrity": {
            "status": "claim-checked",
            "method": "deterministic-structured-claims",
            "structured_claims": structured_claims,
        },
        "verdict": data["verdict"],
        "hiring_read": data["hiring_read"],
        "findings": findings,
        "next_action": next_action,
        "language_review": {
            "scope": EDITORIAL_SCOPE,
            "status": language_review.get("status"),
            "blocks": normalized_decision_blocks,
        },
    }
    if decisions_version >= 3:
        record["feedback_review"] = {
            "status": feedback_status,
            "rules": normalized_feedback_rules,
        }
    destination = (
        output or reviews_root / f"{decisions_path.name.removesuffix('.decisions.json')}.json"
    )
    destination = (
        destination.resolve()
        if destination.is_absolute()
        else contained_path(resolved_root, destination.as_posix(), "review record output")
    )
    if destination.parent != reviews_root or destination.suffix != ".json":
        raise ValueError("review record output must be a JSON file directly under build/reviews/")
    candidate = reviews_root / f".{destination.stem}.candidate.json"
    atomic_write_json(candidate, record)
    try:
        validated = load_review_record(candidate, resolved_root)
        reasons = review_freshness(validated)
        if reasons:
            raise ValueError(f"review decisions are stale or incomplete: {reasons}")
    finally:
        candidate.unlink(missing_ok=True)
    atomic_write_json(destination, record)
    result = {
        "valid": True,
        "record": destination.relative_to(resolved_root).as_posix(),
        "version": record["version"],
        "language_status": validated.editorial_status,
        "verdict": validated.verdict,
        "hiring_read": validated.hiring_read,
        "blocks": len(validated.editorial_blocks),
        "feedback_status": validated.feedback_status,
        "feedback_rules": len(validated.feedback_rules),
    }
    if (
        validated.editorial_status == "approved"
        and validated.verdict in {"ready-to-mint", "ready-with-optional-improvements"}
        and validated.feedback_status in {"approved", "not-applicable"}
    ):
        selection = _object(selection_appendix.get("selection"), "review package selection")
        resume_input = _source_input(
            package_data.get("resume"), "review package resume", resolved_root, "resumes"
        )
        guard_selection(resolved_root, resume_input.path, selection)
        seal = write_selection_seal(
            resolved_root,
            resume_input.path,
            selection,
            destination,
        )
        result["selection_seal"] = seal.relative_to(resolved_root).as_posix()
    return result
