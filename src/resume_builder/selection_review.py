"""Build and validate an independent pre-language resume selection review."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .atomic import atomic_write_json
from .compilation import sha256_file
from .layout import contained_path
from .selection_guard import selection_digest
from .synthesis import SynthesisPlan
from .validation import parse_frontmatter

SELECTION_DECISIONS = {"approved", "strategy-revise", "needs-user-decision"}


def _path_record(path: Path, project_root: Path) -> dict[str, str]:
    return {
        "path": path.relative_to(project_root).as_posix(),
        "sha256": sha256_file(path),
    }


def _fact_record(fact_id: str, vault_root: Path) -> dict[str, Any]:
    matches = list(vault_root.joinpath("facts").rglob(f"{fact_id}.md"))
    if len(matches) != 1:
        raise ValueError(f"selection review fact {fact_id} must resolve to exactly one vault file")
    path = matches[0]
    metadata, body = parse_frontmatter(path)
    return {
        "id": fact_id,
        "kind": metadata.get("kind"),
        "status": metadata.get("status"),
        "content": body.strip(),
        "source": path.relative_to(vault_root).as_posix(),
        "sha256": sha256_file(path),
    }


def selection_review_paths(project_root: Path, resume: Path) -> dict[str, Path]:
    base = project_root / "build" / "reviews" / resume.stem
    return {
        "package": base.with_name(f"{base.name}.selection.package.json"),
        "decisions": base.with_name(f"{base.name}.selection.decisions.json"),
        "record": base.with_name(f"{base.name}.selection-review.json"),
    }


def _claim_record(story: object) -> dict[str, Any] | None:
    claim = getattr(story, "claim", None)
    if claim is None:
        return None
    return {
        "subject": claim.subject,
        "action": claim.action,
        "object": claim.object,
        "scope": claim.scope,
        "outcome": claim.outcome,
        "relationship": claim.relationship,
        "evidence": {
            "action": list(claim.evidence.action),
            "object": list(claim.evidence.object),
            "scope": list(claim.evidence.scope),
            "outcome": list(claim.evidence.outcome),
        },
    }


def build_selection_review_package(
    project_root: Path,
    resume: Path,
    plan: SynthesisPlan,
    selection: dict[str, Any],
    *,
    manifest: Path,
) -> Path:
    """Freeze the complete evidence-selection argument before prose review."""
    paths = selection_review_paths(project_root, resume)
    paths["package"].parent.mkdir(parents=True, exist_ok=True)
    selected_ids = {
        item["id"]
        for item in selection.get("stories", [])
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    story_records: list[dict[str, Any]] = []
    all_fact_ids = set(plan.summary_fact_ids)
    all_fact_ids.update(fact_id for fact_id, _reason in plan.exclusions)
    for story in plan.stories:
        all_fact_ids.update(story.fact_ids)
        story_records.append(
            {
                "id": story.story_id,
                "selected": story.story_id in selected_ids,
                "section": story.section,
                "role_ids": list(story.role_ids),
                "importance": story.importance,
                "primary_job": story.primary_job,
                "rationale": story.rationale,
                "claim_focus": story.claim_focus,
                "fact_ids": list(story.fact_ids),
                "core_fact_ids": list(story.core_fact_ids),
                "claim": _claim_record(story),
            }
        )
    facts = [_fact_record(fact_id, project_root / "vault") for fact_id in sorted(all_fact_ids)]
    role_arc_records: list[dict[str, Any]] = [
        {
            "role_ids": list(arc.role_ids),
            "emphasis": arc.emphasis,
            "arc_focus": arc.arc_focus,
            "selected_story_ids": [
                story_id for story_id in arc.story_ids if story_id in selected_ids
            ],
            "candidate_story_ids": list(arc.story_ids),
            "required_dimensions": list(arc.required_dimensions),
            "required_story_ids": list(arc.required_story_ids),
            "optional_story_ids": list(arc.optional_story_ids),
            "selection_rationale": arc.selection_rationale,
            "omitted_signals": [
                {
                    "signal": signal.signal,
                    "fact_ids": list(signal.fact_ids),
                    "reason": signal.reason,
                }
                for signal in arc.omitted_signals
            ],
        }
        for arc in plan.role_arcs
    ]
    package: dict[str, Any] = {
        "version": 1,
        "phase": "selection-review",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "inputs": {
            # Selection is a non-prose decision. Pin the resume identity, not its
            # wording hash, so a bounded language repair does not reopen strategy.
            "resume": {"path": resume.relative_to(project_root).as_posix()},
            "plan": _path_record(plan.source, project_root),
            "direction": _path_record(plan.direction, project_root),
            "selection_sha256": selection_digest(selection),
        },
        "review_context": {
            "target_argument": plan.target_argument,
            "target_mode": plan.target_mode,
            "summary_job": plan.summary_job,
            "summary_fact_ids": list(plan.summary_fact_ids),
            "progression_role_ids": list(plan.progression),
            "concept_fit": [
                {
                    "concept_id": item.concept_id,
                    "status": item.status,
                    "fact_ids": list(item.fact_ids),
                    "rationale": item.rationale,
                }
                for item in plan.concept_fit
            ],
            "reviewer_risks": [
                {
                    "id": item.risk_id,
                    "concern": item.concern,
                    "status": item.status,
                    "fact_ids": list(item.fact_ids),
                    "planning_action": item.planning_action,
                }
                for item in plan.reviewer_risks
            ],
            "exclusions": [
                {"fact_id": fact_id, "reason": reason} for fact_id, reason in plan.exclusions
            ],
        },
        "selection": selection,
        "stories": story_records,
        "role_arcs": role_arc_records,
        "facts": facts,
        "review_standard": {
            "purpose": (
                "Decide whether the complete selection makes the strongest honest hiring "
                "argument for the target before any language is reviewed."
            ),
            "selected_content_must": [
                "advance target qualification, accomplishment, progression, credential, or necessary context",
                "be supported by canonical evidence",
                "earn its space against the available alternatives",
            ],
            "adverse_or_sensitive_context_may_be_selected_only_when": [
                "the target requires the disclosure",
                "omitting it would make a visible claim misleading",
                "the response itself demonstrates target-relevant capability or outcome",
                "the user explicitly chose the disclosure after seeing the tradeoff",
            ],
            "anti_gaming": [
                "Review selected stories and omitted candidates; fewer selected stories do not improve the verdict.",
                "A reviewer risk is not itself a reason to place adverse history on the resume.",
                "Do not edit prose or invent facts; route strategy changes back to the builder.",
            ],
        },
    }
    # The compiled manifest is required to exist, but its timestamp must not make an
    # otherwise identical strategy review stale on every verification run.
    if not manifest.is_file():
        raise ValueError("selection review requires a compiled build manifest")
    if paths["package"].is_file() and paths["decisions"].is_file():
        existing = _load_json(paths["package"], "selection package")
        comparable_existing = {
            key: value for key, value in existing.items() if key != "generated_at"
        }
        comparable_new = {key: value for key, value in package.items() if key != "generated_at"}
        if comparable_existing == comparable_new:
            return paths["package"]
    atomic_write_json(paths["package"], package)
    decisions = {
        "version": 1,
        "selection_package": _path_record(paths["package"], project_root),
        "reviewer": {"method": "independent-selection-review", "context": ""},
        "argument": {"decision": None, "note": ""},
        "stories": [
            {"id": story["id"], "selected": story["selected"], "decision": None, "note": ""}
            for story in story_records
        ],
        "exclusions": [
            {"fact_id": fact_id, "decision": None, "note": ""}
            for fact_id, _reason in plan.exclusions
        ],
        "role_arcs": [
            {
                "role_ids": arc["role_ids"],
                "decision": None,
                "note": "",
            }
            for arc in role_arc_records
        ],
        "verdict": None,
    }
    atomic_write_json(paths["decisions"], decisions)
    return paths["package"]


def _load_json(path: Path, owner: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid {owner}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{owner} must be a JSON object")
    return value


def _validate_decision(value: object, owner: str) -> str:
    if value not in SELECTION_DECISIONS:
        raise ValueError(f"{owner} must be one of {sorted(SELECTION_DECISIONS)}")
    return str(value)


def finalize_selection_review(decisions: Path, project_root: Path) -> dict[str, Any]:
    """Validate reviewer-owned decisions and create a hash-pinned selection record."""
    decisions_source = decisions.expanduser()
    source = (
        decisions_source.resolve()
        if decisions_source.is_absolute()
        else contained_path(project_root, decisions_source.as_posix(), "selection decisions")
    )
    reviews_root = (project_root / "build" / "reviews").resolve()
    if source.parent != reviews_root or not source.name.endswith(".selection.decisions.json"):
        raise ValueError(
            "selection decisions must be a *.selection.decisions.json file under build/reviews/"
        )
    raw = _load_json(source, "selection decisions")
    if raw.get("version") != 1:
        raise ValueError("selection decisions must declare version 1")
    package_ref = raw.get("selection_package")
    if not isinstance(package_ref, dict):
        raise ValueError("selection decisions are missing the package reference")
    package_value = package_ref.get("path")
    if not isinstance(package_value, str):
        raise ValueError("selection package path is invalid")
    package_path = contained_path(project_root, package_value, "selection package")
    if package_ref.get("sha256") != sha256_file(package_path):
        raise ValueError("selection package changed after reviewer decisions were created")
    package = _load_json(package_path, "selection package")
    if package.get("version") != 1 or package.get("phase") != "selection-review":
        raise ValueError("selection package has an unsupported schema")
    reviewer = raw.get("reviewer")
    if not isinstance(reviewer, dict) or reviewer.get("method") != "independent-selection-review":
        raise ValueError("selection review must use the independent-selection-review method")
    if not isinstance(reviewer.get("context"), str) or not reviewer["context"].strip():
        raise ValueError("selection reviewer must describe its isolated context")

    decisions_seen: list[str] = []
    argument = raw.get("argument")
    if not isinstance(argument, dict):
        raise ValueError("selection decisions are missing the whole-resume argument")
    decisions_seen.append(_validate_decision(argument.get("decision"), "argument decision"))
    if argument["decision"] != "approved" and not str(argument.get("note", "")).strip():
        raise ValueError("a non-approved argument decision requires a note")

    package_stories = package.get("stories")
    raw_stories = raw.get("stories")
    if not isinstance(package_stories, list) or not isinstance(raw_stories, list):
        raise ValueError("selection story inventory is invalid")
    expected = [(item.get("id"), item.get("selected")) for item in package_stories]
    actual = [
        (item.get("id"), item.get("selected")) for item in raw_stories if isinstance(item, dict)
    ]
    if actual != expected or len(actual) != len(raw_stories):
        raise ValueError(
            "selection decisions must cover every selected and omitted candidate unchanged"
        )
    for index, item in enumerate(raw_stories):
        decision = _validate_decision(item.get("decision"), f"story decision[{index}]")
        decisions_seen.append(decision)
        if decision != "approved" and not str(item.get("note", "")).strip():
            raise ValueError(f"story decision[{index}] requires a note")

    package_exclusions = package.get("review_context", {}).get("exclusions")
    raw_exclusions = raw.get("exclusions")
    if not isinstance(package_exclusions, list) or not isinstance(raw_exclusions, list):
        raise ValueError("selection exclusion inventory is invalid")
    expected_exclusions = [item.get("fact_id") for item in package_exclusions]
    actual_exclusions = [item.get("fact_id") for item in raw_exclusions if isinstance(item, dict)]
    if actual_exclusions != expected_exclusions or len(actual_exclusions) != len(raw_exclusions):
        raise ValueError("selection decisions must cover every intentional exclusion unchanged")
    for index, item in enumerate(raw_exclusions):
        decision = _validate_decision(item.get("decision"), f"exclusion decision[{index}]")
        decisions_seen.append(decision)
        if decision != "approved" and not str(item.get("note", "")).strip():
            raise ValueError(f"exclusion decision[{index}] requires a note")

    package_arcs = package.get("role_arcs")
    raw_arcs = raw.get("role_arcs")
    if not isinstance(package_arcs, list) or not isinstance(raw_arcs, list):
        raise ValueError("selection role-arc inventory is invalid")
    expected_arcs = [item.get("role_ids") for item in package_arcs]
    actual_arcs = [item.get("role_ids") for item in raw_arcs if isinstance(item, dict)]
    if actual_arcs != expected_arcs or len(actual_arcs) != len(raw_arcs):
        raise ValueError("selection decisions must cover every role arc unchanged")
    for index, item in enumerate(raw_arcs):
        decision = _validate_decision(item.get("decision"), f"role-arc decision[{index}]")
        decisions_seen.append(decision)
        if decision != "approved" and not str(item.get("note", "")).strip():
            raise ValueError(f"role-arc decision[{index}] requires a note")

    derived = (
        "needs-user-decision"
        if "needs-user-decision" in decisions_seen
        else "changes-required"
        if "strategy-revise" in decisions_seen
        else "approved"
    )
    if raw.get("verdict") != derived:
        raise ValueError(f"selection verdict must be {derived!r} for the recorded decisions")
    package_inputs = package.get("inputs")
    if not isinstance(package_inputs, dict):
        raise ValueError("selection package inputs are invalid")
    output = selection_review_paths(project_root, Path(str(package_inputs["resume"]["path"])))[
        "record"
    ]
    record = {
        "version": 1,
        "phase": "selection-review-record",
        "finalized_at": datetime.now(timezone.utc).isoformat(),
        "status": derived,
        "selection_package": _path_record(package_path, project_root),
        "inputs": package_inputs,
        "reviewer": reviewer,
        "argument": argument,
        "stories": raw_stories,
        "exclusions": raw_exclusions,
        "role_arcs": raw_arcs,
    }
    atomic_write_json(output, record)
    return {"valid": True, "status": derived, "record": output.relative_to(project_root).as_posix()}


def selection_review_freshness(record: Path, project_root: Path) -> list[str]:
    """Return reasons a selection review is stale, incomplete, or unapproved."""
    if not record.is_file():
        return ["selection review is missing"]
    try:
        raw = _load_json(record, "selection review")
    except ValueError as exc:
        return [str(exc)]
    reasons: list[str] = []
    if raw.get("version") != 1 or raw.get("phase") != "selection-review-record":
        reasons.append("selection review has an unsupported schema")
    if raw.get("status") != "approved":
        reasons.append(f"selection review status is {raw.get('status', 'invalid')}")
    package_ref = raw.get("selection_package")
    if not isinstance(package_ref, dict) or not isinstance(package_ref.get("path"), str):
        reasons.append("selection review package reference is invalid")
        return reasons
    try:
        package = contained_path(project_root, package_ref["path"], "selection package")
    except ValueError as exc:
        reasons.append(str(exc))
        return reasons
    package_data: dict[str, Any] | None = None
    if not package.is_file() or package_ref.get("sha256") != sha256_file(package):
        reasons.append("selection review package changed or is missing")
    else:
        try:
            package_data = _load_json(package, "selection package")
        except ValueError as exc:
            reasons.append(str(exc))
    inputs = raw.get("inputs")
    if not isinstance(inputs, dict):
        reasons.append("selection review inputs are invalid")
        return reasons
    for owner in ("resume", "plan", "direction"):
        ref = inputs.get(owner)
        if not isinstance(ref, dict) or not isinstance(ref.get("path"), str):
            reasons.append(f"selection review {owner} reference is invalid")
            continue
        try:
            path = contained_path(project_root, ref["path"], f"selection review {owner}")
        except ValueError as exc:
            reasons.append(str(exc))
            continue
        if not path.is_file():
            reasons.append(f"selection review {owner} changed or is missing")
        elif owner != "resume" and ref.get("sha256") != sha256_file(path):
            reasons.append(f"selection review {owner} changed or is missing")
    if package_data is None:
        return reasons
    selection = package_data.get("selection")
    target = selection.get("target") if isinstance(selection, dict) else None
    if target is not None:
        if not isinstance(target, dict) or not isinstance(target.get("path"), str):
            reasons.append("selection review target reference is invalid")
        else:
            try:
                target_path = contained_path(
                    project_root, target["path"], "selection review target"
                )
            except ValueError as exc:
                reasons.append(str(exc))
            else:
                if not target_path.is_file() or target.get("sha256") != sha256_file(target_path):
                    reasons.append("selection review target changed or is missing")
    facts = package_data.get("facts")
    if not isinstance(facts, list):
        reasons.append("selection review fact references are invalid")
        return reasons
    vault_root = project_root / "vault"
    for index, fact in enumerate(facts):
        if not isinstance(fact, dict) or not isinstance(fact.get("source"), str):
            reasons.append(f"selection review fact reference[{index}] is invalid")
            continue
        try:
            fact_path = contained_path(
                vault_root, fact["source"], f"selection review fact[{index}]"
            )
        except ValueError as exc:
            reasons.append(str(exc))
            continue
        if not fact_path.is_file() or fact.get("sha256") != sha256_file(fact_path):
            fact_id = fact.get("id", index)
            reasons.append(f"selection review fact {fact_id} changed or is missing")
    return reasons


def require_approved_selection_review(project_root: Path, resume: Path) -> Path:
    """Return the current selection record or fail closed."""
    record = selection_review_paths(project_root, resume)["record"]
    reasons = selection_review_freshness(record, project_root)
    if reasons:
        raise ValueError(f"resume selection review is stale or incomplete: {reasons}")
    return record
