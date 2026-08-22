"""Prevent editorial review cycles from silently shrinking resume strategy."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .atomic import atomic_write_json
from .compilation import sha256_file
from .layout import contained_path
from .synthesis import SynthesisPlan


def _digest(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _strings(value: object) -> list[str]:
    return (
        sorted({item for item in value if isinstance(item, str)}) if isinstance(value, list) else []
    )


def build_selection(
    plan: SynthesisPlan,
    synthesis: dict[str, Any],
    *,
    target: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Return the non-prose strategy selected for one compiled resume."""
    used_ids = set(_strings(synthesis.get("used_story_ids")))
    evidence_by_story = {
        str(item.get("story_id")): _strings(item.get("used_fact_ids"))
        for item in synthesis.get("story_evidence", [])
        if isinstance(item, dict) and isinstance(item.get("story_id"), str)
    }
    required_ids = {story_id for arc in plan.role_arcs for story_id in arc.required_story_ids}
    stories = []
    for story in sorted(plan.stories, key=lambda item: item.story_id):
        if story.story_id not in used_ids:
            continue
        stories.append(
            {
                "id": story.story_id,
                "section": story.section,
                "role_ids": sorted(story.role_ids),
                "importance": story.importance,
                "required": story.story_id in required_ids,
                "used_fact_ids": evidence_by_story.get(story.story_id, []),
            }
        )
    role_arcs = [
        {
            "role_ids": sorted(arc.role_ids),
            "required_dimensions": sorted(arc.required_dimensions),
            "required_story_ids": sorted(arc.required_story_ids),
            **(
                {"role_anchor_story_ids": sorted(arc.role_anchor_story_ids)}
                if plan.version >= 8
                else {}
            ),
            **(
                {"role_selling_story_ids": sorted(arc.role_selling_story_ids)}
                if plan.version >= 9
                else {}
            ),
            **(
                {
                    "core_job": {
                        "selected_id": arc.selected_core_job_id,
                        "decision": arc.core_job_decision,
                        "candidates": sorted(
                            [
                                {
                                    "id": candidate.candidate_id,
                                    "description": candidate.description,
                                    "confidence": candidate.confidence,
                                }
                                for candidate in arc.core_job_candidates
                            ],
                            key=lambda item: str(item["id"]),
                        ),
                    }
                }
                if plan.version >= 10
                else {}
            ),
        }
        for arc in plan.role_arcs
    ]
    role_arcs.sort(key=lambda item: tuple(item["role_ids"]))
    selection = {
        "version": 1,
        "direction": plan.direction.relative_to(plan.source.parents[2]).as_posix(),
        "target": target,
        "target_mode": plan.target_mode,
        "progression_role_ids": sorted(plan.progression),
        "stories": stories,
        "summary_fact_ids": sorted(plan.summary_fact_ids),
        "role_arcs": role_arcs,
    }
    return selection


def selection_digest(selection: dict[str, Any]) -> str:
    """Hash only the stable strategy payload, never timestamps or review prose."""
    return _digest(selection)


def _story_map(selection: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(item["id"]): item
        for item in selection.get("stories", [])
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }


def _arc_map(selection: dict[str, Any]) -> dict[tuple[str, ...], dict[str, Any]]:
    return {
        tuple(_strings(item.get("role_ids"))): item
        for item in selection.get("role_arcs", [])
        if isinstance(item, dict)
    }


def compare_selections(previous: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    """Classify structural losses separately from harmless or additive changes."""
    old_stories = _story_map(previous)
    new_stories = _story_map(current)
    removed_story_ids = sorted(old_stories.keys() - new_stories.keys())
    added_story_ids = sorted(new_stories.keys() - old_stories.keys())
    moved_stories: list[dict[str, object]] = []
    evidence_losses: list[dict[str, object]] = []
    demoted_stories: list[dict[str, object]] = []
    for story_id in sorted(old_stories.keys() & new_stories.keys()):
        old = old_stories[story_id]
        new = new_stories[story_id]
        old_story_roles = _strings(old.get("role_ids"))
        new_story_roles = _strings(new.get("role_ids"))
        if old_story_roles != new_story_roles:
            moved_stories.append({"id": story_id, "from": old_story_roles, "to": new_story_roles})
        lost_facts = sorted(
            set(_strings(old.get("used_fact_ids"))) - set(_strings(new.get("used_fact_ids")))
        )
        if lost_facts:
            evidence_losses.append({"id": story_id, "removed_fact_ids": lost_facts})
        if (old.get("importance") == "core" and new.get("importance") != "core") or (
            old.get("required") is True and new.get("required") is not True
        ):
            demoted_stories.append(
                {
                    "id": story_id,
                    "from": {"importance": old.get("importance"), "required": old.get("required")},
                    "to": {"importance": new.get("importance"), "required": new.get("required")},
                }
            )
    old_roles = set(_strings(previous.get("progression_role_ids")))
    new_roles = set(_strings(current.get("progression_role_ids")))
    old_arcs = _arc_map(previous)
    new_arcs = _arc_map(current)
    removed_dimensions: list[dict[str, object]] = []
    removed_role_anchors: list[dict[str, object]] = []
    removed_role_sellers: list[dict[str, object]] = []
    for role_key, old_arc in sorted(old_arcs.items()):
        new_arc = new_arcs.get(role_key, {})
        lost = sorted(
            set(_strings(old_arc.get("required_dimensions")))
            - set(_strings(new_arc.get("required_dimensions")))
        )
        if lost:
            removed_dimensions.append({"role_ids": list(role_key), "dimensions": lost})
        lost_anchors = sorted(
            set(_strings(old_arc.get("role_anchor_story_ids")))
            - set(_strings(new_arc.get("role_anchor_story_ids")))
        )
        if lost_anchors:
            removed_role_anchors.append({"role_ids": list(role_key), "story_ids": lost_anchors})
        lost_sellers = sorted(
            set(_strings(old_arc.get("role_selling_story_ids")))
            - set(_strings(new_arc.get("role_selling_story_ids")))
        )
        if lost_sellers:
            removed_role_sellers.append({"role_ids": list(role_key), "story_ids": lost_sellers})
    target_changed = None
    if previous.get("target") != current.get("target") or previous.get("direction") != current.get(
        "direction"
    ):
        target_changed = {
            "from": {"direction": previous.get("direction"), "target": previous.get("target")},
            "to": {"direction": current.get("direction"), "target": current.get("target")},
        }
    blocking = {
        "removed_role_ids": sorted(old_roles - new_roles),
        "removed_story_ids": removed_story_ids,
        "moved_stories": moved_stories,
        "evidence_losses": evidence_losses,
        "demoted_stories": demoted_stories,
        "removed_summary_fact_ids": sorted(
            set(_strings(previous.get("summary_fact_ids")))
            - set(_strings(current.get("summary_fact_ids")))
        ),
        "removed_required_dimensions": removed_dimensions,
        "removed_role_anchor_story_ids": removed_role_anchors,
        "removed_role_selling_story_ids": removed_role_sellers,
        "target_or_direction_changed": target_changed,
    }
    blocking = {key: value for key, value in blocking.items() if value not in ([], None)}
    return {
        "blocking": blocking,
        "additions": {
            "role_ids": sorted(new_roles - old_roles),
            "story_ids": added_story_ids,
        },
        "requires_approval": bool(blocking),
    }


def seal_path(project_root: Path, resume: Path) -> Path:
    return project_root / "resumes" / "selections" / f"{resume.stem}.json"


def load_seal(project_root: Path, resume: Path) -> dict[str, Any] | None:
    path = seal_path(project_root, resume)
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid reviewed selection seal: {exc}") from exc
    if not isinstance(value, dict) or value.get("version") != 1:
        raise ValueError("reviewed selection seal must declare version 1")
    if value.get("resume") != resume.relative_to(project_root).as_posix():
        raise ValueError(
            "reviewed selection seal belongs to another resume; resume filenames must be "
            "unique across baselines and tailored resumes"
        )
    selection = value.get("selection")
    if not isinstance(selection, dict) or value.get("selection_sha256") != selection_digest(
        selection
    ):
        raise ValueError("reviewed selection seal has an invalid selection digest")
    return value


def proposal_path(project_root: Path, resume: Path) -> Path:
    return project_root / "build" / "revisions" / f"{resume.stem}.strategy.json"


def approval_path(project_root: Path, resume: Path, proposal_id: str) -> Path:
    return project_root / "resumes" / "strategy-decisions" / resume.stem / f"{proposal_id}.json"


def guard_selection(
    project_root: Path,
    resume: Path,
    current: dict[str, Any],
) -> dict[str, Any]:
    """Require explicit approval before a reviewed selection loses substance."""
    seal = load_seal(project_root, resume)
    current_digest = selection_digest(current)
    if seal is None:
        return {"status": "first-reviewed-selection", "selection_sha256": current_digest}
    previous = seal["selection"]
    previous_digest = str(seal["selection_sha256"])
    delta = compare_selections(previous, current)
    if not delta["requires_approval"]:
        return {
            "status": "selection-preserved",
            "selection_sha256": current_digest,
            "previous_selection_sha256": previous_digest,
            "additions": delta["additions"],
        }
    proposal_core = {
        "resume": resume.relative_to(project_root).as_posix(),
        "previous_selection_sha256": previous_digest,
        "proposed_selection_sha256": current_digest,
        "blocking_changes": delta["blocking"],
        "additions": delta["additions"],
    }
    proposal_digest = _digest(proposal_core)
    proposal_id = proposal_digest[:12]
    approval = approval_path(project_root, resume, proposal_id)
    if approval.is_file():
        try:
            approved = json.loads(approval.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid strategy approval: {exc}") from exc
        if (
            not isinstance(approved, dict)
            or approved.get("status") != "approved"
            or approved.get("proposal_sha256") != proposal_digest
            or approved.get("previous_selection_sha256") != previous_digest
            or approved.get("proposed_selection_sha256") != current_digest
        ):
            raise ValueError("strategy approval does not match the current structural change")
        return {
            "status": "strategy-change-approved",
            "selection_sha256": current_digest,
            "previous_selection_sha256": previous_digest,
            "approval": approval.relative_to(project_root).as_posix(),
            "blocking_changes": delta["blocking"],
        }
    proposal = {
        "version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "proposal_id": proposal_id,
        "proposal_sha256": proposal_digest,
        **proposal_core,
        "instruction": (
            "Review these changes as one strategy decision. Approving reviewer wording does "
            "not approve removal of career content."
        ),
    }
    output = proposal_path(project_root, resume)
    atomic_write_json(output, proposal)
    raise ValueError(
        "reviewed resume selection would lose or weaken content; strategy approval required: "
        f"{output.relative_to(project_root).as_posix()} (run: resume-builder review "
        f'strategy-approve {output.relative_to(project_root).as_posix()} --reason "...")'
    )


def approve_proposal(proposal: Path, project_root: Path, reason: str) -> dict[str, Any]:
    """Record an explicit, exact approval for one grouped structural change."""
    if not reason.strip():
        raise ValueError("strategy approval requires a non-empty --reason")
    source = contained_path(project_root, proposal.as_posix(), "strategy proposal")
    revisions = (project_root / "build" / "revisions").resolve()
    if source.parent != revisions or not source.name.endswith(".strategy.json"):
        raise ValueError("strategy proposal must be a *.strategy.json file under build/revisions/")
    try:
        raw = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid strategy proposal: {exc}") from exc
    if not isinstance(raw, dict) or raw.get("version") != 1:
        raise ValueError("strategy proposal must declare version 1")
    resume_value = raw.get("resume")
    if not isinstance(resume_value, str):
        raise ValueError("strategy proposal has no resume path")
    resume = contained_path(project_root, resume_value, "strategy proposal resume")
    proposal_id = raw.get("proposal_id")
    proposal_digest = raw.get("proposal_sha256")
    core = {
        "resume": resume_value,
        "previous_selection_sha256": raw.get("previous_selection_sha256"),
        "proposed_selection_sha256": raw.get("proposed_selection_sha256"),
        "blocking_changes": raw.get("blocking_changes"),
        "additions": raw.get("additions"),
    }
    if not isinstance(proposal_id, str) or proposal_id != _digest(core)[:12]:
        raise ValueError("strategy proposal ID does not match its changes")
    if proposal_digest != _digest(core):
        raise ValueError("strategy proposal digest does not match its changes")
    seal = load_seal(project_root, resume)
    if seal is None or seal.get("selection_sha256") != raw.get("previous_selection_sha256"):
        raise ValueError("strategy proposal is stale because the reviewed selection changed")
    output = approval_path(project_root, resume, proposal_id)
    record = {
        "version": 1,
        "status": "approved",
        "approved_at": datetime.now(timezone.utc).isoformat(),
        "reason": reason.strip(),
        "proposal": source.relative_to(project_root).as_posix(),
        "proposal_sha256": proposal_digest,
        "previous_selection_sha256": raw.get("previous_selection_sha256"),
        "proposed_selection_sha256": raw.get("proposed_selection_sha256"),
        "blocking_changes": raw.get("blocking_changes"),
    }
    atomic_write_json(output, record)
    return {"valid": True, "approval": output.relative_to(project_root).as_posix(), **record}


def write_selection_seal(
    project_root: Path,
    resume: Path,
    selection: dict[str, Any],
    review_record: Path,
) -> Path:
    """Persist the last independently reviewed ready selection outside disposable build output."""
    output = seal_path(project_root, resume)
    record = {
        "version": 1,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "resume": resume.relative_to(project_root).as_posix(),
        "selection_sha256": selection_digest(selection),
        "selection": selection,
        "review": {
            "path": review_record.relative_to(project_root).as_posix(),
            "sha256": sha256_file(review_record),
        },
    }
    atomic_write_json(output, record)
    return output


def repair_cycle_key(project_root: Path, resume: Path, selection_sha256: str) -> str:
    seal = load_seal(project_root, resume)
    anchor = seal.get("review", {}).get("sha256") if seal is not None else "unsealed"
    return _digest({"selection_sha256": selection_sha256, "review_anchor": anchor})


def record_repair_attempts(
    project_root: Path,
    resume: Path,
    selection_sha256: str,
    block_ids: list[str],
) -> None:
    """Allow one automatic wording repair per block in a reviewed selection cycle."""
    path = project_root / "resumes" / "selections" / f"{resume.stem}.repair-attempts.json"
    if path.is_file():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid repair-attempt record: {exc}") from exc
    else:
        raw = {"version": 1, "cycles": {}}
    if (
        not isinstance(raw, dict)
        or raw.get("version") != 1
        or not isinstance(raw.get("cycles"), dict)
    ):
        raise ValueError("repair-attempt record must declare version 1 with cycles")
    key = repair_cycle_key(project_root, resume, selection_sha256)
    cycles = raw["cycles"]
    prior = cycles.get(key, [])
    if not isinstance(prior, list) or any(not isinstance(item, str) for item in prior):
        raise ValueError("repair-attempt cycle has an invalid block list")
    repeated = sorted(set(prior) & set(block_ids))
    if repeated:
        raise ValueError(
            "automatic wording repair already attempted for these blocks in the current "
            f"selection cycle: {repeated}; require a user wording decision or a new strategy"
        )
    cycles[key] = sorted(set(prior) | set(block_ids))
    raw["updated_at"] = datetime.now(timezone.utc).isoformat()
    atomic_write_json(path, raw)


def write_repair_handoff(
    project_root: Path,
    resume: Path,
    resume_sha256: str,
    selection_sha256: str,
    changed_block_ids: list[str],
    carried_blocks: Sequence[dict[str, object]],
) -> Path:
    """Pin unchanged approvals so the repair review cannot reopen unrelated prose."""
    output = project_root / "resumes" / "selections" / f"{resume.stem}.repair-handoff.json"
    atomic_write_json(
        output,
        {
            "version": 1,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "resume": resume.relative_to(project_root).as_posix(),
            "resume_sha256": resume_sha256,
            "selection_sha256": selection_sha256,
            "changed_block_ids": sorted(changed_block_ids),
            "carried_blocks": list(carried_blocks),
        },
    )
    return output


def matching_repair_handoff(
    project_root: Path,
    resume: Path,
    resume_sha256: str,
    selection_sha256: str,
) -> dict[str, Any] | None:
    path = project_root / "resumes" / "selections" / f"{resume.stem}.repair-handoff.json"
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid repair handoff: {exc}") from exc
    if not isinstance(raw, dict) or raw.get("version") != 1:
        raise ValueError("repair handoff must declare version 1")
    if raw.get("resume") != resume.relative_to(project_root).as_posix():
        return None
    if raw.get("resume_sha256") != resume_sha256 or raw.get("selection_sha256") != selection_sha256:
        return None
    changed = raw.get("changed_block_ids")
    carried = raw.get("carried_blocks")
    if (
        not isinstance(changed, list)
        or any(not isinstance(item, str) for item in changed)
        or not isinstance(carried, list)
        or any(not isinstance(item, dict) for item in carried)
    ):
        raise ValueError("repair handoff has invalid block records")
    return raw
