"""Report current Resume Builder readiness across vault, resumes, and outputs."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from . import __version__
from .directions import parse_direction
from .evaluations import load_case
from .feedback_memory import manifest_guidance_freshness, validate_feedback_memory
from .job_matching import validate_target
from .layout import contained_path
from .review_records import load_review_record, review_freshness
from .synthesis import load_synthesis_plan
from .validation import validate_vault
from .verification import workflow_state


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _relative(path: Path, project_root: Path) -> str:
    return path.resolve().relative_to(project_root).as_posix()


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _record_freshness(
    value: object,
    project_root: Path,
    owner: str,
    *,
    base: Path | None = None,
) -> str | None:
    if not isinstance(value, dict):
        return f"{owner} record is missing"
    path_value = value.get("path")
    digest = value.get("sha256")
    if not isinstance(path_value, str) or not isinstance(digest, str):
        return f"{owner} record is invalid"
    try:
        path = contained_path(base or project_root, path_value, f"{owner} path")
    except ValueError:
        return f"{owner} path is unsafe"
    if not path.is_file():
        return f"{owner} file is missing"
    if _sha256(path) != digest:
        return f"{owner} file changed"
    return None


def _build_status(resume: Path, project_root: Path, vault_root: Path) -> dict[str, Any]:
    manifest_path = project_root / "build" / f"{resume.stem}.manifest.json"
    if not manifest_path.is_file():
        return {"status": "missing", "path": _relative(manifest_path, project_root), "reasons": []}
    try:
        manifest = _load_json(manifest_path)
    except ValueError as exc:
        return {
            "status": "invalid",
            "path": _relative(manifest_path, project_root),
            "reasons": [str(exc)],
        }

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
    return {
        "status": "stale" if reasons else "current",
        "path": _relative(manifest_path, project_root),
        "reasons": reasons,
        "warnings": manifest.get("warnings", []),
    }


def _review_status(
    resume: Path,
    project_root: Path,
    plan: Path,
    direction: Path | None,
) -> dict[str, Any]:
    review_path = project_root / "build" / "reviews" / f"{resume.stem}.json"
    if not review_path.is_file():
        return {"status": "missing", "path": _relative(review_path, project_root), "reasons": []}
    try:
        record = load_review_record(review_path, project_root)
        reasons = review_freshness(record)
    except ValueError as exc:
        return {
            "status": "invalid",
            "path": _relative(review_path, project_root),
            "reasons": [str(exc)],
        }
    if record.resume.path != resume.resolve():
        reasons.append("review record names a different resume")
    if record.plan.path != plan.resolve():
        reasons.append("review record names a different synthesis plan")
    if direction is not None and record.direction.path != direction.resolve():
        reasons.append("review record names a different direction")
    return {
        "status": "stale" if reasons else "current",
        "path": _relative(review_path, project_root),
        "reasons": reasons,
        "verdict": record.verdict,
        "hiring_read": record.hiring_read,
        "findings": record.findings,
        "reviewed_at": record.reviewed_at,
        "target": _relative(record.target.path, project_root) if record.target else None,
        "next_action": {"route": record.next_route, "summary": record.next_summary},
        "evidence_status": record.evidence_status or "legacy-not-separated",
        "language_status": record.editorial_status,
        "language_blocks": {
            "reviewed": len(record.editorial_blocks),
            "revise": sum(block.decision == "revise" for block in record.editorial_blocks),
        },
        "feedback_status": record.feedback_status,
        "feedback_rules": {
            "reviewed": len(record.feedback_rules),
            "revise": sum(rule.decision == "revise" for rule in record.feedback_rules),
        },
    }


def _mint_status(resume: Path, project_root: Path) -> dict[str, Any]:
    mint_path = project_root / "build" / f"{resume.stem}.mint.json"
    if not mint_path.is_file():
        return {"status": "missing", "path": _relative(mint_path, project_root), "reasons": []}
    try:
        manifest = _load_json(mint_path)
    except ValueError as exc:
        return {
            "status": "invalid",
            "path": _relative(mint_path, project_root),
            "reasons": [str(exc)],
        }
    reasons: list[str] = []
    if (
        manifest.get("version") not in {1, 2}
        or manifest.get("phase") != "mint"
        or not manifest.get("valid")
    ):
        reasons.append("mint manifest does not describe a successful supported mint")
    compiler = manifest.get("compiler")
    if not isinstance(compiler, dict) or compiler.get("version") != __version__:
        reasons.append("mint uses a different compiler version")
    if manifest.get("source") != _relative(resume, project_root):
        reasons.append("mint names a different resume source")
    review_key = "review_record" if manifest.get("version") == 2 else "editorial_review"
    for key in ("build_manifest", "preview_manifest", review_key, "output"):
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
    return {
        "status": "stale" if reasons else "current",
        "path": _relative(mint_path, project_root),
        "reasons": reasons,
        "pages": pages,
    }


def _preview_status(resume: Path, project_root: Path) -> dict[str, Any]:
    """Report whether the career-professional-reviewed web preview is current."""
    preview_path = project_root / "build" / f"{resume.stem}.preview.json"
    if not preview_path.is_file():
        return {"status": "missing", "path": _relative(preview_path, project_root), "reasons": []}
    try:
        manifest = _load_json(preview_path)
    except ValueError as exc:
        return {
            "status": "invalid",
            "path": _relative(preview_path, project_root),
            "reasons": [str(exc)],
        }
    reasons: list[str] = []
    if (
        manifest.get("version") not in {1, 2}
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
    review_key = "review_record" if manifest.get("version") == 2 else "editorial_review"
    for key in ("build_manifest", review_key, "output"):
        reason = _record_freshness(manifest.get(key), project_root, f"preview {key}")
        if reason:
            reasons.append(reason)
    statuses = manifest.get("review_statuses")
    if not isinstance(statuses, dict):
        reasons.append("preview has no separated review statuses")
        statuses = {}
    elif statuses.get("user_review") != "pending":
        reasons.append("preview user-review status is not pending")
    return {
        "status": "stale" if reasons else "current",
        "path": _relative(preview_path, project_root),
        "reasons": reasons,
        "final_review_status": manifest.get("final_review_status"),
        "review_statuses": statuses,
    }


def _match_status(target: Path, resume: Path, project_root: Path) -> dict[str, Any]:
    report_path = project_root / "build" / "matches" / f"{target.stem}--{resume.stem}.json"
    if not report_path.is_file():
        return {"status": "missing", "path": _relative(report_path, project_root), "reasons": []}
    try:
        report = _load_json(report_path)
    except ValueError as exc:
        return {
            "status": "invalid",
            "path": _relative(report_path, project_root),
            "reasons": [str(exc)],
        }
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
    return {
        "status": "stale" if reasons else "current",
        "path": _relative(report_path, project_root),
        "reasons": reasons,
    }


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


def _next_action(
    vault: dict[str, Any],
    directions: list[dict[str, Any]],
    resumes: list[dict[str, Any]],
    targets: list[dict[str, Any]],
    evaluations: dict[str, Any],
    errors: list[str],
) -> dict[str, str]:
    registered_sources = int(vault.get("registered_sources", 0))
    facts = int(vault.get("facts", 0))
    if not registered_sources and not facts:
        return {
            "route": "needs-sources",
            "message": "Add a resume, LinkedIn export, career note, or other source material.",
        }
    if registered_sources and not facts:
        return {
            "route": "needs-hydration",
            "message": "Source registration is complete; finish reviewed career-fact hydration.",
        }
    if not vault.get("valid"):
        return {"route": "fix-vault", "message": "Resolve the vault validation errors."}
    readiness = _initial_draft_readiness(vault)
    if not readiness["ready"]:
        return {
            "route": "needs-hydration",
            "message": "Hydrate enough role and experience evidence for a safe first draft.",
        }
    if errors:
        return {"route": "fix-project", "message": "Resolve invalid project records."}
    if not directions:
        return {
            "route": "needs-direction",
            "message": "Choose the target career direction before building the first draft.",
        }
    baselines = [record for record in resumes if record["kind"] == "baseline"]
    if not baselines:
        return {"route": "build-baseline", "message": "Build the first directional baseline."}
    for record in baselines:
        if record["plan"]["status"] != "valid":
            return {"route": "plan", "message": f"Create or repair the plan for {record['path']}."}
        if record["build"]["status"] != "current":
            return {
                "route": "compile",
                "message": f"Recompile {record['path']} from current inputs.",
            }
        critique = record["critique"]
        if critique["status"] != "current":
            return {
                "route": "critique",
                "message": f"Run the narrative-block critique for {record['path']}.",
            }
        if critique.get("evidence_status") == "changes-required":
            return {
                "route": "rebuild",
                "message": f"Repair evidence integrity for {record['path']}.",
            }
        if critique.get("language_status") == "changes-required":
            critique_action = critique["next_action"]
            return {
                "route": critique_action["route"],
                "message": critique_action["summary"],
            }
        if critique.get("feedback_status") == "changes-required":
            return {
                "route": "rebuild",
                "message": f"Repair accepted-feedback compliance for {record['path']}.",
            }
    for target in targets:
        if target["tailored_resume"] is None:
            return {
                "route": "tailor",
                "message": f"Build a tailored resume for {target['company']} — {target['role']}.",
            }
        tailored = next(record for record in resumes if record["path"] == target["tailored_resume"])
        if tailored["build"]["status"] != "current":
            return {
                "route": "compile",
                "message": f"Compile {tailored['path']} from current inputs.",
            }
        if target["match"]["status"] != "current":
            return {"route": "match", "message": f"Run the job match for {tailored['path']}."}
        critique = tailored["critique"]
        if critique["status"] != "current":
            return {"route": "critique", "message": f"Critique {tailored['path']} before minting."}
        if critique.get("target") != target["path"]:
            return {
                "route": "critique",
                "message": f"Critique {tailored['path']} against its current target before minting.",
            }
        if critique.get("evidence_status") == "changes-required":
            return {
                "route": "rebuild",
                "message": f"Repair evidence integrity for {tailored['path']}.",
            }
        if critique.get("language_status") == "changes-required":
            critique_action = critique["next_action"]
            return {
                "route": critique_action["route"],
                "message": critique_action["summary"],
            }
        if critique.get("feedback_status") == "changes-required":
            return {
                "route": "rebuild",
                "message": f"Repair accepted-feedback compliance for {tailored['path']}.",
            }
        if critique.get("verdict") == "needs-revision":
            critique_action = critique["next_action"]
            return {
                "route": critique_action["route"],
                "message": critique_action["summary"],
            }
        if tailored["preview"]["status"] != "current":
            return {
                "route": "preview",
                "message": f"Publish {tailored['path']} for final user review.",
            }
        if tailored["mint"]["status"] != "current":
            return {
                "route": "mint",
                "message": f"Mint {tailored['path']} after explicit final approval.",
            }
    if evaluations["unsealed"]:
        return {
            "route": "seal-evaluations",
            "message": "Finish editorial comparison and seal the remaining regression cases.",
        }
    if evaluations["uncovered_baselines"]:
        return {
            "route": "assess-regression-coverage",
            "message": "Add a regression case only if an uncovered baseline has a suitable earlier resume in the same lane.",
        }
    return {
        "route": "maintain",
        "message": "The current workflow is ready for the next target or vault update.",
    }


def _initial_draft_readiness(vault: dict[str, Any]) -> dict[str, object]:
    """Require role chronology and usable experience evidence when typed counts exist."""
    facts = int(vault.get("facts", 0))
    raw_types = vault.get("types")
    if not isinstance(raw_types, dict):
        return {"ready": facts > 0, "reasons": [] if facts else ["no canonical facts"]}
    roles = int(raw_types.get("role", 0))
    evidence = sum(
        int(raw_types.get(kind, 0))
        for kind in ("accomplishment", "incident", "leadership", "project", "responsibility")
    )
    reasons = []
    if roles == 0:
        reasons.append("no supported role chronology")
    if evidence == 0:
        reasons.append("no usable experience evidence")
    return {"ready": not reasons, "reasons": reasons}


def _onboarding_status(
    next_action: dict[str, str],
    vault: dict[str, Any],
) -> dict[str, object]:
    """Describe the progressive first-run stage without storing duplicate state."""
    route = next_action["route"]
    messages = {
        "needs-sources": (
            "I don't have any resume material yet. Attach one or more resume files, give me "
            "the exact folder path where they are stored, paste resume text, provide a "
            "LinkedIn export, or start from career notes."
        ),
        "needs-hydration": (
            "I registered your source material, but career-fact extraction is not finished. "
            "I will review the imported evidence before asking you for anything else."
        ),
        "needs-direction": (
            "I imported your resume and found enough information to build from it. Some "
            "experience may be undersold, particularly around outcomes, scale, and leadership. "
            "Choose a target direction first; after I build the initial draft, I'll ask only "
            "the questions most likely to strengthen it."
        ),
        "build-baseline": "Your evidence and direction are ready for the first resume draft.",
    }
    return {
        "stage": route,
        "active": route in messages,
        "message": messages.get(route, next_action["message"]),
        "initial_draft_readiness": _initial_draft_readiness(vault),
    }


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
        for state in ("draft", "awaiting-review", "reviewed", "published")
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
            f"{workflow_counts['awaiting-review']} awaiting review, "
            f"{workflow_counts['reviewed']} reviewed, "
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
