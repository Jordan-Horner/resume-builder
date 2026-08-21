"""Report current Resume Builder readiness across vault, resumes, and outputs."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from . import __version__
from .artifact_paths import resume_output_base
from .artifact_status import (
    ArtifactStatus,
)
from .artifact_status import (
    load_json_object as _load_json,
)
from .artifact_status import (
    record_freshness as _record_freshness,
)
from .artifact_status import (
    relative_path as _relative,
)
from .artifact_status import (
    sha256 as _sha256,
)
from .directions import parse_direction
from .evaluations import load_case
from .feedback_memory import manifest_guidance_freshness, validate_feedback_memory
from .job_matching import validate_target
from .layout import contained_path
from .report_policy import _initial_draft_readiness, _next_action, _onboarding_status
from .review_records import load_review_record, review_freshness
from .synthesis import load_synthesis_plan
from .validation import validate_vault
from .verification import workflow_state

__all__ = [
    "_initial_draft_readiness",
    "_next_action",
    "_onboarding_status",
    "format_summary",
    "main",
    "project_report",
]


def _status(
    status: str,
    path: Path,
    project_root: Path,
    reasons: Sequence[str] = (),
    **details: Any,
) -> dict[str, Any]:
    return ArtifactStatus(
        status=status,
        path=_relative(path, project_root),
        reasons=tuple(reasons),
        details=details,
    ).as_dict()


def _build_status(resume: Path, project_root: Path, vault_root: Path) -> dict[str, Any]:
    manifest_path = resume_output_base(project_root, resume).with_suffix(".manifest.json")
    if not manifest_path.is_file():
        return _status("missing", manifest_path, project_root)
    try:
        manifest = _load_json(manifest_path)
    except ValueError as exc:
        return _status("invalid", manifest_path, project_root, [str(exc)])

    reasons: list[str] = []
    if (
        manifest.get("version") != 1
        or manifest.get("phase") != "build"
        or not manifest.get("valid")
    ):
        reasons.append("build manifest does not describe a valid version 1 build")
    compiler = manifest.get("compiler")
    if not isinstance(compiler, dict) or compiler.get("version") != __version__:
        reasons.append("build uses a different compiler version")
    for key in ("source", "template", "synthesis"):
        reason = _record_freshness(manifest.get(key), project_root, f"build {key}")
        if reason:
            reasons.append(reason)
    source = manifest.get("source")
    if isinstance(source, dict) and isinstance(source.get("path"), str):
        if source["path"] != _relative(resume, project_root):
            reasons.append("build names a different resume source")
    evidence = manifest.get("evidence")
    facts = evidence.get("facts") if isinstance(evidence, dict) else None
    if not isinstance(facts, list):
        reasons.append("build evidence records are missing")
    else:
        for index, fact in enumerate(facts):
            reason = _record_freshness(
                fact,
                project_root,
                f"build fact[{index}]",
                base=vault_root,
            )
            if reason:
                reasons.append(reason)
    reasons.extend(manifest_guidance_freshness(manifest, project_root, vault_root))
    outputs = manifest.get("outputs")
    if not isinstance(outputs, list) or not outputs:
        reasons.append("build output records are missing")
    else:
        for index, output in enumerate(outputs):
            reason = _record_freshness(output, project_root, f"build output[{index}]")
            if reason:
                reasons.append(reason)
    return _status(
        "stale" if reasons else "current",
        manifest_path,
        project_root,
        reasons,
        warnings=manifest.get("warnings", []),
    )


def _review_status(
    resume: Path,
    project_root: Path,
    plan: Path,
    direction: Path | None,
) -> dict[str, Any]:
    review_path = project_root / "build" / "reviews" / f"{resume.stem}.json"
    if not review_path.is_file():
        return _status("missing", review_path, project_root)
    try:
        record = load_review_record(review_path, project_root)
        reasons = review_freshness(record)
    except ValueError as exc:
        return _status("invalid", review_path, project_root, [str(exc)])
    if record.resume.path != resume.resolve():
        reasons.append("review record names a different resume")
    if record.plan.path != plan.resolve():
        reasons.append("review record names a different synthesis plan")
    if direction is not None and record.direction.path != direction.resolve():
        reasons.append("review record names a different direction")
    return _status(
        "stale" if reasons else "current",
        review_path,
        project_root,
        reasons,
        verdict=record.verdict,
        hiring_read=record.hiring_read,
        findings=record.findings,
        reviewed_at=record.reviewed_at,
        target=_relative(record.target.path, project_root) if record.target else None,
        next_action={"route": record.next_route, "summary": record.next_summary},
        evidence_status=record.evidence_status or "legacy-not-separated",
        language_status=record.editorial_status,
        language_blocks={
            "reviewed": len(record.editorial_blocks),
            "revise": sum(block.decision == "revise" for block in record.editorial_blocks),
        },
        feedback_status=record.feedback_status,
        feedback_rules={
            "reviewed": len(record.feedback_rules),
            "revise": sum(rule.decision == "revise" for rule in record.feedback_rules),
        },
    )


def _mint_status(resume: Path, project_root: Path) -> dict[str, Any]:
    mint_path = resume_output_base(project_root, resume).with_suffix(".mint.json")
    if not mint_path.is_file():
        return _status("missing", mint_path, project_root)
    try:
        manifest = _load_json(mint_path)
    except ValueError as exc:
        return _status("invalid", mint_path, project_root, [str(exc)])
    reasons: list[str] = []
    if (
        manifest.get("version") not in {1, 2, 3, 4}
        or manifest.get("phase") != "mint"
        or not manifest.get("valid")
    ):
        reasons.append("mint manifest does not describe a successful supported mint")
    compiler = manifest.get("compiler")
    if not isinstance(compiler, dict) or compiler.get("version") != __version__:
        reasons.append("mint uses a different compiler version")
    if manifest.get("source") != _relative(resume, project_root):
        reasons.append("mint names a different resume source")
    pinned_keys = ["build_manifest", "preview_manifest", "output"]
    if manifest.get("submission_output") is not None:
        pinned_keys.append("submission_output")
    if manifest.get("version") in {1, 2}:
        pinned_keys.append("review_record" if manifest.get("version") == 2 else "editorial_review")
    if manifest.get("version") == 4:
        pinned_keys.append("language_review")
    for key in pinned_keys:
        reason = _record_freshness(manifest.get(key), project_root, f"mint {key}")
        if reason:
            reasons.append(reason)
    preview_record = manifest.get("preview_manifest")
    preview_manifest: dict[str, Any] | None = None
    if isinstance(preview_record, dict) and isinstance(preview_record.get("path"), str):
        try:
            preview_path = contained_path(
                project_root, preview_record["path"], "mint preview_manifest path"
            )
            preview_manifest = _load_json(preview_path)
        except ValueError as exc:
            reasons.append(str(exc))
    if preview_manifest is not None:
        reason = _record_freshness(
            preview_manifest.get("output"), project_root, "mint approved preview output"
        )
        if reason:
            reasons.append(reason)
    user_approval = manifest.get("user_approval")
    if (
        not isinstance(user_approval, dict)
        or user_approval.get("status") != "approved-for-mint"
        or user_approval.get("recorded_by") != "explicit-mint-invocation"
    ):
        reasons.append("mint has no explicit user-approval record")
    elif preview_manifest is not None:
        preview_output = preview_manifest.get("output")
        preview_digest = preview_output.get("sha256") if isinstance(preview_output, dict) else None
        if user_approval.get("preview_sha256") != preview_digest:
            reasons.append("mint user approval does not pin the approved preview")
    pdf_audit = manifest.get("pdf_audit")
    extraction = pdf_audit.get("extraction") if isinstance(pdf_audit, dict) else None
    pages = extraction.get("pages") if isinstance(extraction, dict) else None
    return _status(
        "stale" if reasons else "current",
        mint_path,
        project_root,
        reasons,
        pages=pages,
    )


def _preview_status(resume: Path, project_root: Path) -> dict[str, Any]:
    """Report whether the career-professional-reviewed web preview is current."""
    preview_path = resume_output_base(project_root, resume).with_suffix(".preview.json")
    if not preview_path.is_file():
        return _status("missing", preview_path, project_root)
    try:
        manifest = _load_json(preview_path)
    except ValueError as exc:
        return _status("invalid", preview_path, project_root, [str(exc)])
    reasons: list[str] = []
    if (
        manifest.get("version") not in {1, 2, 3, 4}
        or manifest.get("phase") != "preview"
        or not manifest.get("valid")
    ):
        reasons.append("preview manifest does not describe a successful supported preview")
    compiler = manifest.get("compiler")
    if not isinstance(compiler, dict) or compiler.get("version") != __version__:
        reasons.append("preview uses a different compiler version")
    if manifest.get("source") != _relative(resume, project_root):
        reasons.append("preview names a different resume source")
    if manifest.get("final_review_status") != "awaiting-user-approval":
        reasons.append("preview does not await final user approval")
    pinned_keys = ["build_manifest", "output"]
    if manifest.get("version") in {1, 2}:
        pinned_keys.append("review_record" if manifest.get("version") == 2 else "editorial_review")
    if manifest.get("version") == 4:
        pinned_keys.append("language_review")
    for key in pinned_keys:
        reason = _record_freshness(manifest.get(key), project_root, f"preview {key}")
        if reason:
            reasons.append(reason)
    statuses = manifest.get("review_statuses")
    if not isinstance(statuses, dict):
        reasons.append("preview has no separated review statuses")
        statuses = {}
    elif statuses.get("user_review") != "pending":
        reasons.append("preview user-review status is not pending")
    return _status(
        "stale" if reasons else "current",
        preview_path,
        project_root,
        reasons,
        final_review_status=manifest.get("final_review_status"),
        review_statuses=statuses,
    )


def _match_status(target: Path, resume: Path, project_root: Path) -> dict[str, Any]:
    report_path = project_root / "build" / "matches" / f"{target.stem}--{resume.stem}.json"
    if not report_path.is_file():
        return _status("missing", report_path, project_root)
    try:
        report = _load_json(report_path)
    except ValueError as exc:
        return _status("invalid", report_path, project_root, [str(exc)])
    reasons: list[str] = []
    for key, expected in (("target", target), ("resume", resume)):
        value = report.get(key)
        if not isinstance(value, dict):
            reasons.append(f"match {key} record is missing")
            continue
        if value.get("path") != _relative(expected, project_root):
            reasons.append(f"match {key} names a different file")
        if value.get("sha256") != _sha256(expected):
            reasons.append(f"match {key} changed")
    target_record = report.get("target")
    if isinstance(target_record, dict):
        direction = {
            "path": target_record.get("direction"),
            "sha256": target_record.get("direction_sha256"),
        }
        reason = _record_freshness(direction, project_root, "match direction")
        if reason:
            reasons.append(reason)
    comparison = report.get("comparison")
    if isinstance(comparison, dict):
        reason = _record_freshness(comparison.get("baseline"), project_root, "match baseline")
        if reason:
            reasons.append(reason)
    return _status("stale" if reasons else "current", report_path, project_root, reasons)


def _resume_records(
    project_root: Path,
    vault_root: Path,
    errors: list[str],
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for kind in ("baselines", "tailored"):
        for resume in sorted((project_root / "resumes" / kind).glob("*.md")):
            plan_path = project_root / "resumes" / "plans" / f"{resume.stem}.yaml"
            plan_status = "missing"
            direction: str | None = None
            target_mode: str | None = None
            gaps: list[str] = []
            direction_path: Path | None = None
            if plan_path.is_file():
                try:
                    plan = load_synthesis_plan(plan_path, project_root, vault_root)
                    plan_status = "valid"
                    direction_path = plan.direction
                    direction = _relative(plan.direction, project_root)
                    target_mode = plan.target_mode
                    gaps = list(plan.gaps)
                except ValueError as exc:
                    plan_status = "invalid"
                    errors.append(f"{_relative(plan_path, project_root)}: {exc}")
            records.append(
                {
                    "path": _relative(resume, project_root),
                    "kind": "baseline" if kind == "baselines" else "tailored",
                    "plan": {
                        "path": _relative(plan_path, project_root),
                        "status": plan_status,
                        "target_mode": target_mode,
                        "gaps": gaps,
                    },
                    "direction": direction,
                    "workflow": workflow_state(resume, project_root),
                    "build": _build_status(resume, project_root, vault_root),
                    "critique": _review_status(
                        resume,
                        project_root,
                        plan_path,
                        direction_path,
                    ),
                    "preview": _preview_status(resume, project_root),
                    "mint": _mint_status(resume, project_root),
                }
            )
    return records


def _slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def _target_records(
    project_root: Path,
    resume_by_path: dict[str, dict[str, Any]],
    errors: list[str],
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in sorted((project_root / "targets").glob("*.md")):
        if path.name == "README.md":
            continue
        try:
            target, _ = validate_target(path, project_root)
        except ValueError as exc:
            errors.append(f"{_relative(path, project_root)}: {exc}")
            continue
        tailored_path = (
            project_root
            / "resumes"
            / "tailored"
            / (f"{_slugify(target['company'] + '-' + target['role'])}.md")
        )
        relative_tailored = _relative(tailored_path, project_root)
        resume_record = resume_by_path.get(relative_tailored)
        records.append(
            {
                "path": _relative(path, project_root),
                "company": target["company"],
                "role": target["role"],
                "tailored_resume": relative_tailored if resume_record else None,
                "match": _match_status(path, tailored_path, project_root)
                if resume_record
                else {"status": "not-applicable", "path": None, "reasons": []},
            }
        )
    return records


def project_report(vault_root: Path, *, strict: bool = False) -> dict[str, Any]:
    """Collect a read-only project state report with deterministic next action."""
    resolved_vault = vault_root.expanduser().resolve()
    project_root = resolved_vault.parent
    vault = validate_vault(resolved_vault, strict=strict)
    errors: list[str] = []
    directions: list[dict[str, Any]] = []
    for path in sorted((project_root / "directions").glob("*.md")):
        if path.name == "README.md":
            continue
        try:
            profile, _ = parse_direction(path)
            directions.append(
                {
                    "path": _relative(path, project_root),
                    "slug": profile["slug"],
                    "status": profile["status"],
                    "maturity": profile["maturity"],
                }
            )
        except ValueError as exc:
            errors.append(f"{_relative(path, project_root)}: {exc}")

    resumes = _resume_records(project_root, resolved_vault, errors)
    resume_by_path = {record["path"]: record for record in resumes}
    targets = _target_records(project_root, resume_by_path, errors)
    cases: list[dict[str, Any]] = []
    for path in sorted((project_root / "evals" / "cases").glob("*.yaml")):
        try:
            case = load_case(path, project_root)
            cases.append({"id": case["id"], "resume": case["resume"], "sealed": case["sealed"]})
        except ValueError as exc:
            errors.append(f"{_relative(path, project_root)}: {exc}")
    baseline_paths = {record["path"] for record in resumes if record["kind"] == "baseline"}
    covered = {case["resume"] for case in cases}
    evaluations = {
        "cases": len(cases),
        "sealed": sum(1 for case in cases if case["sealed"]),
        "unsealed": sum(1 for case in cases if not case["sealed"]),
        "uncovered_baselines": sorted(baseline_paths - covered),
    }
    feedback = validate_feedback_memory(project_root)
    feedback_errors = feedback.get("errors")
    if isinstance(feedback_errors, list):
        errors.extend(str(error) for error in feedback_errors)
    result: dict[str, Any] = {
        "valid": bool(vault.get("valid")) and not errors,
        "vault": vault,
        "directions": directions,
        "resumes": resumes,
        "targets": targets,
        "evaluations": evaluations,
        "feedback": feedback,
        "errors": errors,
    }
    result["next_action"] = _next_action(
        vault,
        directions,
        resumes,
        targets,
        evaluations,
        errors,
    )
    result["onboarding"] = _onboarding_status(result["next_action"], vault)
    result["status"] = (
        "getting-started"
        if result["onboarding"]["active"]
        else "valid"
        if result["valid"]
        else "invalid"
    )
    return result


def format_summary(result: dict[str, Any]) -> str:
    """Render the project report for a quick human status check."""
    vault = result["vault"]
    resumes = result["resumes"]
    baselines = [item for item in resumes if item["kind"] == "baseline"]
    tailored = [item for item in resumes if item["kind"] == "tailored"]

    def current(key: str) -> int:
        return sum(1 for item in resumes if item[key]["status"] == "current")

    workflow_counts = {
        state: sum(1 for item in resumes if item["workflow"]["state"] == state)
        for state in (
            "draft",
            "preview-ready",
            "published",
        )
    }

    lines = [
        f"Project: {str(result.get('status', 'valid' if result['valid'] else 'invalid')).upper()}",
        (
            f"Vault: {vault.get('facts', 0)} facts, "
            f"{vault.get('registered_sources', 0)} sources, "
            f"{len(vault.get('warnings', []))} warnings"
        ),
        f"Directions: {len(result['directions'])}",
        (
            "Feedback memory: "
            f"{result['feedback']['active_rules']} active rules, "
            f"{result['feedback']['open_sessions']} open revisions"
        ),
        f"Resumes: {len(baselines)} baselines, {len(tailored)} tailored",
        (
            "Workflow: "
            f"{workflow_counts['draft']} draft, "
            f"{workflow_counts['preview-ready']} ready for preview, "
            f"{workflow_counts['published']} published"
        ),
        f"Fresh artifacts: {current('build')} builds, {current('critique')} critiques, {current('mint')} mints",
        f"Targets: {len(result['targets'])}",
        (
            f"Regression cases: {result['evaluations']['cases']} "
            f"({result['evaluations']['sealed']} sealed, "
            f"{result['evaluations']['unsealed']} unsealed)"
        ),
        f"Onboarding: {result['onboarding']['stage']}",
        f"Next: {result['next_action']['message']}",
    ]
    lines.extend(f"  error: {error}" for error in result["errors"])
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    """Print project-wide readiness as JSON or a concise summary."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vault-root", type=Path, default=Path("vault"))
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = project_report(args.vault_root, strict=args.strict)
    except (OSError, ValueError) as exc:
        print(json.dumps({"error": str(exc)}, indent=2), file=sys.stderr)
        return 2
    print(format_summary(result) if args.summary else json.dumps(result, indent=2))
    return 0 if result["valid"] or result["onboarding"]["active"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
