"""Verify a resume draft once and prepare hash-pinned review inputs."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import __version__
from .artifact_paths import resume_output_base
from .artifact_status import build_manifest_freshness
from .atomic import atomic_write_json
from .compilation import build_resume, relative_output, sha256_file
from .directions import audit_direction, parse_direction
from .job_matching import match_job, project_target_path
from .rendering import contained_project_path
from .review_records import (
    build_review_package,
    narrative_block_inventory,
)
from .selection_guard import build_selection, guard_selection
from .selection_review import (
    build_selection_review_package,
    selection_review_freshness,
    selection_review_paths,
)
from .synthesis import load_synthesis_plan
from .validation import validate_vault


def _path_record(path: Path, project_root: Path) -> dict[str, str]:
    """Return one project-relative immutable file reference."""
    return {
        "path": relative_output(path, project_root),
        "sha256": sha256_file(path),
    }


def _optional_path_record(path: Path | None, project_root: Path) -> dict[str, str] | None:
    return None if path is None else _path_record(path, project_root)


def _load_json(path: Path, owner: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid {owner}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{owner} must be a JSON object")
    return value


def _record_freshness(
    value: object,
    project_root: Path,
    owner: str,
) -> list[str]:
    if not isinstance(value, dict):
        return [f"{owner} record is missing"]
    path_value = value.get("path")
    digest = value.get("sha256")
    if not isinstance(path_value, str) or not isinstance(digest, str):
        return [f"{owner} record is invalid"]
    try:
        path = contained_project_path(
            Path(path_value), project_root, path_value.split("/", 1)[0], owner
        )
    except ValueError:
        path = (project_root / path_value).resolve()
        if not path.is_relative_to(project_root):
            return [f"{owner} path leaves the project"]
    if not path.is_file():
        return [f"{owner} file is missing"]
    if sha256_file(path) != digest:
        return [f"{owner} changed"]
    return []


def _preview_freshness(resume: Path, project_root: Path) -> list[str]:
    path = resume_output_base(project_root, resume).with_suffix(".preview.json")
    if not path.is_file():
        return ["published preview is missing"]
    try:
        preview = _load_json(path, "preview manifest")
    except ValueError as exc:
        return [str(exc)]
    reasons: list[str] = []
    if (
        preview.get("version") != 4
        or preview.get("phase") != "preview"
        or preview.get("valid") is not True
    ):
        reasons.append("preview manifest is not a successful preview")
    owners = ["build_manifest", "output"]
    if preview.get("version") in {1, 2}:
        owners.append("review_record" if preview.get("version") == 2 else "editorial_review")
    if preview.get("version") == 4:
        owners.append("language_review")
    for owner in owners:
        reasons.extend(_record_freshness(preview.get(owner), project_root, f"preview {owner}"))
    return reasons


def workflow_state(resume: Path, project_root: Path) -> dict[str, Any]:
    """Return the current draft, review, preview, or published lifecycle state."""
    manifest = resume_output_base(project_root, resume).with_suffix(".manifest.json")
    build_reasons = build_manifest_freshness(manifest, project_root)
    if build_reasons:
        return {"state": "draft", "reasons": build_reasons}
    preview_reasons = _preview_freshness(resume, project_root)
    if preview_reasons:
        return {"state": "preview-ready", "reasons": preview_reasons}
    preview_path = resume_output_base(project_root, resume).with_suffix(".preview.json")
    preview = _load_json(preview_path, "preview manifest")
    statuses = preview.get("review_statuses")
    language_status = statuses.get("language_review") if isinstance(statuses, dict) else None
    if language_status != "approved":
        return {
            "state": "revision-required",
            "reasons": ["independent language review requires changes"],
        }
    return {"state": "published", "reasons": []}


def _cached_receipt(
    receipt_path: Path,
    project_root: Path,
    resume: Path,
    inputs: dict[str, object],
) -> dict[str, Any] | None:
    if not receipt_path.is_file():
        return None
    try:
        receipt = _load_json(receipt_path, "verification receipt")
    except ValueError:
        return None
    if (
        receipt.get("version") != 3
        or receipt.get("phase") != "verification"
        or receipt.get("inputs") != inputs
    ):
        return None
    compiler = receipt.get("compiler")
    if not isinstance(compiler, dict) or compiler.get("version") != __version__:
        return None
    artifacts = receipt.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        return None
    if any(_record_freshness(item, project_root, "verification artifact") for item in artifacts):
        return None
    manifest_path = resume_output_base(project_root, resume).with_suffix(".manifest.json")
    if build_manifest_freshness(manifest_path, project_root):
        return None
    selection_reasons = selection_review_freshness(
        selection_review_paths(project_root, resume)["record"], project_root
    )
    review_inputs = receipt.get("review_inputs")
    if not isinstance(review_inputs, dict):
        return None
    selection_record = selection_review_paths(project_root, resume)["record"]
    if "selection_case" in review_inputs and selection_record.is_file():
        return None
    if "selection_review" in review_inputs and selection_reasons:
        return None
    return receipt


def verify_resume(
    resume: Path,
    *,
    target: Path | None = None,
    baseline: Path | None = None,
    vault_root: Path = Path("vault"),
    template: Path | None = None,
    synthesis_plan: Path | None = None,
    refresh: bool = False,
    skip_vault_validation: bool = False,
) -> dict[str, Any]:
    """Run the fast content gates once and prepare a frozen review package."""
    resolved_vault = vault_root.expanduser().resolve()
    project_root = resolved_vault.parent
    resume_path = contained_project_path(resume, project_root, "resumes", "resume")
    plan_argument = synthesis_plan or Path("resumes/plans") / f"{resume_path.stem}.yaml"
    plan = load_synthesis_plan(plan_argument, project_root, resolved_vault)
    if plan.resume != resume_path:
        raise ValueError("synthesis plan targets a different resume")
    template_argument = template or (
        plan.resume_template.theme.renderer
        if plan.resume_template is not None
        else Path("templates/resume-template.html")
    )
    template_path = contained_project_path(template_argument, project_root, "templates", "template")
    target_path = project_target_path(target, project_root) if target is not None else None
    baseline_path = (
        contained_project_path(baseline, project_root, "resumes", "baseline")
        if baseline is not None
        else None
    )
    if baseline_path is not None and target_path is None:
        raise ValueError("baseline comparison requires --target")
    inputs: dict[str, object] = {
        "resume": _path_record(resume_path, project_root),
        "plan": _path_record(plan.source, project_root),
        "direction": _path_record(plan.direction, project_root),
        "template": _path_record(template_path, project_root),
        "resume_template": (
            {
                "content": _path_record(plan.resume_template.content.source, project_root),
                "theme": _path_record(plan.resume_template.theme.source, project_root),
                "renderer": _path_record(plan.resume_template.theme.renderer, project_root),
            }
            if plan.resume_template is not None
            else None
        ),
        "target": _optional_path_record(target_path, project_root),
        "baseline": _optional_path_record(baseline_path, project_root),
        "vault_validation": "skipped" if skip_vault_validation else "strict",
    }
    output_base = resume_output_base(project_root, resume_path)
    receipt_path = output_base.with_suffix(".verify.json")
    cached = (
        None
        if refresh
        else _cached_receipt(
            receipt_path,
            project_root,
            resume_path,
            inputs,
        )
    )
    if cached is not None:
        return {
            "valid": True,
            "cached": True,
            "source": relative_output(resume_path, project_root),
            "state": cached["workflow"],
            "receipt": relative_output(receipt_path, project_root),
            "checks": cached["checks"],
            "review_inputs": cached["review_inputs"],
        }

    vault_result: dict[str, object] | None = None
    if not skip_vault_validation:
        vault_result = validate_vault(resolved_vault, strict=True)
        if vault_result.get("valid") is not True:
            raise ValueError(f"strict vault validation failed: {vault_result.get('errors', [])}")

    manifest_path = output_base.with_suffix(".manifest.json")
    payload_path = output_base.with_suffix(".json")
    build_reasons = build_manifest_freshness(manifest_path, project_root)
    if not build_reasons:
        current_manifest = _load_json(manifest_path, "compiled build manifest")
        current_template = current_manifest.get("template")
        current_synthesis = current_manifest.get("synthesis")
        if (
            not isinstance(current_template, dict)
            or current_template.get("path") != relative_output(template_path, project_root)
            or not isinstance(current_synthesis, dict)
            or current_synthesis.get("path") != relative_output(plan.source, project_root)
        ):
            build_reasons.append("compiled build uses different requested inputs")
    if build_reasons:
        build_result = build_resume(
            resume_path,
            vault_root=resolved_vault,
            template=template_path,
            synthesis_plan=plan.source,
        )
    else:
        build_result = {"warnings": current_manifest.get("warnings", [])}
    manifest = _load_json(manifest_path, "compiled build manifest")
    payload = _load_json(payload_path, "compiled resume payload")
    profile, _ = parse_direction(plan.direction)
    direction_result = audit_direction(profile, payload, resolved_vault, plan=plan)
    if direction_result.get("passes") is not True:
        raise ValueError("direction evidence audit failed")

    match_result: dict[str, Any] | None = None
    if target_path is not None:
        match_result = match_job(
            target_path,
            resume_path,
            baseline=baseline_path,
            vault_root=resolved_vault,
        )

    inventory = narrative_block_inventory(resume_path)
    advisories = [
        {"id": block.id, "advisories": list(block.advisories)}
        for block in inventory
        if block.advisories
    ]
    evidence_value = manifest.get("evidence")
    evidence: dict[str, Any] = evidence_value if isinstance(evidence_value, dict) else {}
    synthesis_value = manifest.get("synthesis")
    synthesis: dict[str, Any] = synthesis_value if isinstance(synthesis_value, dict) else {}
    role_balance_value = synthesis.get("role_balance")
    role_balance: dict[str, Any] = (
        role_balance_value if isinstance(role_balance_value, dict) else {}
    )
    selection = build_selection(
        plan,
        synthesis,
        target=_optional_path_record(target_path, project_root),
    )
    selection_guard = guard_selection(project_root, resume_path, selection)
    if (
        role_balance.get("status") == "reviewer-decision"
        and selection_guard.get("status") == "selection-preserved"
    ):
        role_balance = {
            **role_balance,
            "status": "user-decision",
            "protected_by_reviewed_selection": True,
            "inversions": [
                {**item, "resolution": "user-decision"}
                if isinstance(item, dict)
                else item
                for item in role_balance.get("inversions", [])
            ],
        }
    selection_package = build_selection_review_package(
        project_root,
        resume_path,
        plan,
        selection,
        manifest=manifest_path,
        role_balance=role_balance,
    )
    selection_paths = selection_review_paths(project_root, resume_path)
    selection_reasons = selection_review_freshness(selection_paths["record"], project_root)
    feedback_value = manifest.get("feedback_memory")
    feedback: dict[str, Any] = feedback_value if isinstance(feedback_value, dict) else {}
    role_arcs_value = synthesis.get("role_arcs")
    role_arcs: list[Any] = role_arcs_value if isinstance(role_arcs_value, list) else []
    planned_story_ids = synthesis.get("planned_story_ids")
    used_story_ids = synthesis.get("used_story_ids")
    vault_warnings_value = vault_result.get("warnings", []) if vault_result is not None else []
    vault_warnings = list(vault_warnings_value) if isinstance(vault_warnings_value, list) else []
    exact_retrieval: dict[str, Any] | None = None
    if match_result is not None:
        exact_retrieval_value = match_result["resume"]["audit"]["exact_retrieval"]
        if not isinstance(exact_retrieval_value, dict):
            raise ValueError("job match exact-retrieval result is invalid")
        exact_retrieval = exact_retrieval_value
    checks: dict[str, Any] = {
        "vault": (
            {"valid": True, "warnings": vault_warnings}
            if vault_result is not None
            else {"valid": None, "skipped": True, "warnings": []}
        ),
        "build": {
            "valid": True,
            "warnings": list(build_result.get("warnings", [])),
            "structured_claims": evidence.get("structured_claims_checked"),
            "claim_relationships_checked": evidence.get("claim_relationships_checked"),
            "planned_stories": len(planned_story_ids) if isinstance(planned_story_ids, list) else 0,
            "used_stories": len(used_story_ids) if isinstance(used_story_ids, list) else 0,
            "role_arcs": [
                {
                    "role_ids": arc.get("role_ids"),
                    "planned": arc.get("planned_story_count"),
                    "used": arc.get("used_story_count"),
                    "omitted": arc.get("omitted_story_ids"),
                }
                for arc in role_arcs
                if isinstance(arc, dict)
            ],
            "role_balance": role_balance,
            "selection_guard": selection_guard,
        },
        "direction": {
            "valid": True,
            "evidence_score": direction_result.get("evidence_score"),
            "experience_evidence_score": direction_result.get("experience_evidence_score"),
            "vocabulary_score": direction_result.get("vocabulary_score"),
            "warnings": list(direction_result.get("warnings", [])),
        },
        "match": (
            {
                "valid": True,
                "target": match_result["target"]["path"],
                "required_missing_group_ids": exact_retrieval["required_missing_group_ids"],
                "listed_without_demonstration_group_ids": exact_retrieval[
                    "listed_without_demonstration_group_ids"
                ],
            }
            if match_result is not None and exact_retrieval is not None
            else None
        ),
        "prose_preflight": {
            "blocks": len(inventory),
            "advisories": advisories,
        },
        "feedback_memory": {
            "status": feedback.get("status", "not-applicable"),
            "rules": len(feedback.get("rules", []))
            if isinstance(feedback.get("rules"), list)
            else 0,
        },
        "selection_review": {
            "status": "approved" if not selection_reasons else "required",
            "reasons": selection_reasons,
            "package": relative_output(selection_package, project_root),
        },
    }
    artifact_paths = [manifest_path, payload_path, selection_package]
    if match_result is not None:
        artifact_paths.extend(project_root / path for path in match_result["outputs"])
    review_inputs: dict[str, Any]
    workflow: dict[str, Any]
    selection_record: dict[str, Any] | None = None
    if selection_paths["record"].is_file():
        selection_record = _load_json(selection_paths["record"], "selection review")
    if selection_reasons and selection_record is not None and selection_record.get("status") == "needs-user-decision":
        artifact_paths.append(selection_paths["record"])
        review_inputs = {
            "user_decision": {
                "role_balance": role_balance,
                "selection_review": _path_record(selection_paths["record"], project_root),
                "role_arc_decisions": [
                    item
                    for item in selection_record.get("role_arcs", [])
                    if isinstance(item, dict) and item.get("decision") == "needs-user-decision"
                ],
            }
        }
        workflow = {
            "state": "awaiting-user-decision",
            "next_action": (
                "Show the exact protected-content tradeoff and wait for the user's decision; "
                "do not publish or revise the resume automatically."
            ),
        }
    elif selection_reasons:
        review_inputs = {
            "selection_case": _path_record(selection_package, project_root),
            "selection_decisions": relative_output(selection_paths["decisions"], project_root),
        }
        workflow = {
            "state": "awaiting-selection-review",
            "next_action": (
                "Complete the independent selection decisions and run review "
                "selection-finalize before language review."
            ),
        }
    else:
        package_path = build_review_package(resume_path, project_root, target=target_path)
        cold_path = package_path.with_name(
            f"{package_path.name.removesuffix('.package.json')}.cold.json"
        )
        decisions_path = package_path.with_name(
            f"{package_path.name.removesuffix('.package.json')}.decisions.json"
        )
        artifact_paths.extend([selection_paths["record"], cold_path, package_path])
        review_inputs = {
            "selection_review": _path_record(selection_paths["record"], project_root),
            "cold_read": _path_record(cold_path, project_root),
            "package": _path_record(package_path, project_root),
            "decisions": relative_output(decisions_path, project_root),
        }
        workflow = {
            "state": "awaiting-review",
            "next_action": "Complete the generated language decisions and run review finalize.",
        }
    receipt = {
        "version": 3,
        "phase": "verification",
        "valid": True,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "compiler": {"name": "resume-builder", "version": __version__},
        "inputs": inputs,
        "artifacts": [_path_record(path, project_root) for path in artifact_paths],
        "checks": checks,
        "review_inputs": review_inputs,
        "workflow": workflow,
    }
    atomic_write_json(receipt_path, receipt)
    return {
        "valid": True,
        "cached": False,
        "source": relative_output(resume_path, project_root),
        "state": workflow,
        "receipt": relative_output(receipt_path, project_root),
        "checks": checks,
        "review_inputs": review_inputs,
    }


def main(argv: Sequence[str] | None = None) -> int:
    """Verify one resume draft and prepare its frozen review package."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("resume", type=Path)
    parser.add_argument("--target", type=Path)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--vault-root", type=Path, default=Path("vault"))
    parser.add_argument("--template", type=Path)
    parser.add_argument("--synthesis-plan", type=Path)
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--skip-vault-validation", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = verify_resume(
            args.resume,
            target=args.target,
            baseline=args.baseline,
            vault_root=args.vault_root,
            template=args.template,
            synthesis_plan=args.synthesis_plan,
            refresh=args.refresh,
            skip_vault_validation=args.skip_vault_validation,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": str(exc)}, indent=2), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
