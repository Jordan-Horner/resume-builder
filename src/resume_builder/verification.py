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
from .atomic import atomic_write_json
from .compilation import build_resume, relative_output, sha256_file
from .directions import audit_direction, parse_direction
from .feedback_memory import manifest_guidance_freshness
from .job_matching import match_job, project_target_path
from .rendering import contained_project_path
from .review_records import (
    build_review_package,
    load_review_record,
    narrative_block_inventory,
    review_freshness,
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


def build_manifest_freshness(manifest_path: Path, project_root: Path) -> list[str]:
    """Return deterministic reasons a compiled build can no longer be reused."""
    if not manifest_path.is_file():
        return ["compiled build manifest is missing"]
    try:
        manifest = _load_json(manifest_path, "compiled build manifest")
    except ValueError as exc:
        return [str(exc)]
    reasons: list[str] = []
    if manifest.get("version") != 1 or manifest.get("phase") != "build":
        reasons.append("compiled build manifest has an unsupported schema")
    compiler = manifest.get("compiler")
    if not isinstance(compiler, dict) or compiler.get("version") != __version__:
        reasons.append("compiled build uses a different builder version")
    for owner in ("source", "template", "synthesis"):
        reasons.extend(_record_freshness(manifest.get(owner), project_root, f"build {owner}"))
    outputs = manifest.get("outputs")
    if not isinstance(outputs, list) or not outputs:
        reasons.append("compiled build output inventory is missing")
    else:
        for index, output in enumerate(outputs):
            reasons.extend(_record_freshness(output, project_root, f"build output[{index}]"))
    evidence = manifest.get("evidence")
    facts = evidence.get("facts") if isinstance(evidence, dict) else None
    if not isinstance(facts, list):
        reasons.append("compiled build fact inventory is missing")
    else:
        vault_root = project_root / "vault"
        for index, fact in enumerate(facts):
            if not isinstance(fact, dict):
                reasons.append(f"build fact[{index}] record is invalid")
                continue
            path_value = fact.get("path")
            digest = fact.get("sha256")
            if not isinstance(path_value, str) or not isinstance(digest, str):
                reasons.append(f"build fact[{index}] record is invalid")
                continue
            path = (vault_root / path_value).resolve()
            if not path.is_relative_to(vault_root.resolve()) or not path.is_file():
                reasons.append(f"build fact[{index}] file is missing")
            elif sha256_file(path) != digest:
                reasons.append(f"{path.name} changed after compilation")
    reasons.extend(manifest_guidance_freshness(manifest, project_root, project_root / "vault"))
    return reasons


def _preview_freshness(resume: Path, project_root: Path) -> list[str]:
    path = project_root / "build" / f"{resume.stem}.preview.json"
    if not path.is_file():
        return ["published preview is missing"]
    try:
        preview = _load_json(path, "preview manifest")
    except ValueError as exc:
        return [str(exc)]
    reasons: list[str] = []
    if preview.get("phase") != "preview" or preview.get("valid") is not True:
        reasons.append("preview manifest is not a successful preview")
    for owner in ("build_manifest", "review_record", "output"):
        reasons.extend(_record_freshness(preview.get(owner), project_root, f"preview {owner}"))
    return reasons


def workflow_state(resume: Path, project_root: Path) -> dict[str, Any]:
    """Return the current Draft → Review → Published lifecycle state."""
    manifest = project_root / "build" / f"{resume.stem}.manifest.json"
    build_reasons = build_manifest_freshness(manifest, project_root)
    if build_reasons:
        return {"state": "draft", "reasons": build_reasons}
    selection_record = selection_review_paths(project_root, resume)["record"]
    selection_reasons = selection_review_freshness(selection_record, project_root)
    if selection_reasons:
        return {"state": "awaiting-selection-review", "reasons": selection_reasons}
    review_path = project_root / "build" / "reviews" / f"{resume.stem}.json"
    if not review_path.is_file():
        return {"state": "awaiting-review", "reasons": []}
    try:
        review = load_review_record(review_path, project_root)
        review_reasons = review_freshness(review)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {"state": "awaiting-review", "reasons": [str(exc)]}
    if review_reasons:
        return {"state": "awaiting-review", "reasons": review_reasons}
    if review.editorial_status != "approved":
        return {
            "state": "draft",
            "reasons": ["career-professional review requires narrative changes"],
        }
    preview_reasons = _preview_freshness(resume, project_root)
    if preview_reasons:
        return {"state": "reviewed", "reasons": preview_reasons}
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
    manifest_path = project_root / "build" / f"{resume.stem}.manifest.json"
    if build_manifest_freshness(manifest_path, project_root):
        return None
    selection_reasons = selection_review_freshness(
        selection_review_paths(project_root, resume)["record"], project_root
    )
    review_inputs = receipt.get("review_inputs")
    if not isinstance(review_inputs, dict):
        return None
    if "selection_case" in review_inputs and not selection_reasons:
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
    template: Path = Path("templates/resume-template.html"),
    synthesis_plan: Path | None = None,
    refresh: bool = False,
    skip_vault_validation: bool = False,
) -> dict[str, Any]:
    """Run the fast content gates once and prepare a frozen review package."""
    resolved_vault = vault_root.expanduser().resolve()
    project_root = resolved_vault.parent
    resume_path = contained_project_path(resume, project_root, "resumes", "resume")
    template_path = contained_project_path(template, project_root, "templates", "template")
    plan_argument = synthesis_plan or Path("resumes/plans") / f"{resume_path.stem}.yaml"
    plan = load_synthesis_plan(plan_argument, project_root, resolved_vault)
    if plan.resume != resume_path:
        raise ValueError("synthesis plan targets a different resume")
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
        "target": _optional_path_record(target_path, project_root),
        "baseline": _optional_path_record(baseline_path, project_root),
        "vault_validation": "skipped" if skip_vault_validation else "strict",
    }
    receipt_path = project_root / "build" / f"{resume_path.stem}.verify.json"
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
            "state": workflow_state(resume_path, project_root),
            "receipt": relative_output(receipt_path, project_root),
            "checks": cached["checks"],
            "review_inputs": cached["review_inputs"],
        }

    vault_result: dict[str, object] | None = None
    if not skip_vault_validation:
        vault_result = validate_vault(resolved_vault, strict=True)
        if vault_result.get("valid") is not True:
            raise ValueError(f"strict vault validation failed: {vault_result.get('errors', [])}")

    build_result = build_resume(
        resume_path,
        vault_root=resolved_vault,
        template=template_path,
        synthesis_plan=plan.source,
    )
    manifest_path = project_root / "build" / f"{resume_path.stem}.manifest.json"
    payload_path = project_root / "build" / f"{resume_path.stem}.json"
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
    selection = build_selection(
        plan,
        synthesis,
        target=_optional_path_record(target_path, project_root),
    )
    selection_guard = guard_selection(project_root, resume_path, selection)
    selection_package = build_selection_review_package(
        project_root,
        resume_path,
        plan,
        selection,
        manifest=manifest_path,
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
    if selection_reasons:
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
        "state": workflow_state(resume_path, project_root),
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
    parser.add_argument("--template", type=Path, default=Path("templates/resume-template.html"))
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
