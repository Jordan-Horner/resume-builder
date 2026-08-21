#!/usr/bin/env python3
"""Compile and publish the current resume as an editable web preview."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import __version__
from .artifact_paths import default_resume_output_base
from .artifact_status import build_manifest_freshness
from .atomic import atomic_write_json, atomic_write_text
from .compilation import build_resume, relative_output, sha256_file
from .language_review import current_language_review
from .rendering import contained_project_path, known_fact_ids, load_payload, render_payload
from .review_approval import review_freshness
from .review_policy import hybrid_review_route
from .review_schema import load_review_record
from .selection_review import require_approved_selection_review
from .synthesis import load_synthesis_plan

APPROVED_NOTICE = "Language reviewed · Edit or mint when ready"
ATTENTION_NOTICE = "Language reviewed · Wording needs attention before minting"
PREVIEW_MODE = {
    "kind": "continuous-web",
    "pagination": "PDF page count is calculated only during minting",
}
PRESENTATION_POLICY = {
    "mode": "exclusive-current-stage",
    "supersedes_prior_handoffs": True,
    "append_to_rendered_markdown": False,
}


def _handoff_presentation(
    *,
    tailored: bool,
    language_status: str,
    language_issues: int,
    career_verdict: str = "not-reviewed",
    career_note: str | None = None,
) -> dict[str, Any]:
    """Return the user-facing structure for the preview/edit loop."""
    resume_label = "tailored resume" if tailored else "resume"
    if language_status == "approved":
        if career_verdict == "needs-revision" and career_note:
            summary = (
                f"Your {resume_label} passed its independent language review. The career "
                f"review still flags one positioning tradeoff: {career_note}"
            )
            guidance = "Confirm that the content feels accurate and that you accept this tradeoff."
            response_prompt = (
                'Tell me what to change, or reply "Mint" if you accept the tradeoff and want '
                "the PDF."
            )
        else:
            summary = (
                f"Your {resume_label} passed its independent language review. Review it and tell "
                'me what to change. When it looks right, reply "Mint" to create the PDF.'
            )
            guidance = "Confirm that the content feels accurate and sounds like you."
            response_prompt = 'Reply "Mint" to create the PDF, or tell me what to change.'
    else:
        noun = "item" if language_issues == 1 else "items"
        summary = (
            f"Your {resume_label} preview is ready, but the independent language review found "
            f"{language_issues} {noun} that still need attention."
        )
        guidance = "Review the flagged wording before creating the final PDF."
        response_prompt = "Tell me how you want to revise the flagged wording."
    return {
        "title": "Resume Preview",
        "summary": summary,
        "review_heading": "Review your resume",
        "guidance_heading": "What to check",
        "guidance": guidance,
        "response_prompt": response_prompt,
    }


def _current_career_review(
    resume: Path,
    project_root: Path,
    language: dict[str, Any],
) -> tuple[str, str, dict[str, str] | None]:
    """Return only a current review that satisfies the hybrid deep-review contract."""
    path = project_root / "build" / "reviews" / f"{resume.stem}.json"
    if not path.is_file():
        return "not-reviewed", "not-reviewed", None
    try:
        record = load_review_record(path, project_root)
    except ValueError:
        return "not-reviewed", "not-reviewed", None
    if (
        record.resume.path != resume.resolve()
        or record.version not in {4, 5}
        or record.reviewer_method != "independent-cold-review"
        or record.evidence_status != "claim-checked"
        or record.editorial_status != "approved"
        or record.build_manifest is None
        or record.cold_read is None
        or record.review_package is None
        or (record.version >= 5 and record.feedback_status != "approved")
        or review_freshness(record)
    ):
        return "not-reviewed", "not-reviewed", None
    if record.version == 4:
        try:
            build = json.loads(record.build_manifest.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return "not-reviewed", "not-reviewed", None
        memory = build.get("feedback_memory") if isinstance(build, dict) else None
        rules = memory.get("rules") if isinstance(memory, dict) else None
        if isinstance(rules, list) and rules:
            return "not-reviewed", "not-reviewed", None
    try:
        package = json.loads(record.review_package.path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "not-reviewed", "not-reviewed", None
    expected_language = {
        "path": relative_output(language["path"], project_root),
        "sha256": language["sha256"],
    }
    if not isinstance(package, dict) or package.get("language_review") != expected_language:
        return "not-reviewed", "not-reviewed", None
    try:
        require_approved_selection_review(project_root, resume)
    except ValueError:
        return "not-reviewed", "not-reviewed", None
    return (
        record.hiring_read,
        record.verdict,
        {
            "path": relative_output(path, project_root),
            "sha256": sha256_file(path),
            "verdict": record.verdict,
            "hiring_read": record.hiring_read,
            "next_action": record.next_summary,
        },
    )


def _render_handoff_markdown(presentation: dict[str, Any], artifact_markdown: str) -> str:
    """Render the structured preview handoff for direct presentation."""
    return "\n\n".join(
        [
            f"## {presentation['title']}",
            presentation["summary"],
            f"### {presentation['review_heading']}",
            artifact_markdown,
            f"### {presentation['guidance_heading']}",
            presentation["guidance"],
            presentation["response_prompt"],
        ]
    )


def _current_build(
    resume: Path,
    project_root: Path,
    vault_root: Path,
    resolved_base: Path,
) -> tuple[Path, Path, dict[str, Any]]:
    """Return the current compiled artifacts and verify their pinned inputs."""
    json_path = resolved_base.with_suffix(".json")
    manifest_path = resolved_base.with_suffix(".manifest.json")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("preview requires a current compiled build") from exc
    if not isinstance(manifest, dict) or manifest.get("phase") != "build":
        raise ValueError("preview requires a valid build manifest")
    freshness = build_manifest_freshness(manifest_path, project_root)
    if freshness:
        raise ValueError("preview compiled build is stale: " + "; ".join(freshness))
    source = manifest.get("source")
    if (
        not isinstance(source, dict)
        or source.get("path") != relative_output(resume, project_root)
        or source.get("sha256") != sha256_file(resume)
    ):
        raise ValueError("preview build is stale for the current resume")
    synthesis = manifest.get("synthesis")
    template = manifest.get("template")
    for owner, value, allowed_directory in (
        ("synthesis", synthesis, "resumes/plans"),
        ("template", template, "templates"),
    ):
        if not isinstance(value, dict):
            raise ValueError(f"preview build {owner} record is missing")
        path_value = value.get("path")
        digest = value.get("sha256")
        if not isinstance(path_value, str) or not isinstance(digest, str):
            raise ValueError(f"preview build {owner} record is invalid")
        path = contained_project_path(
            Path(path_value), project_root, allowed_directory, f"build {owner}"
        )
        if not path.is_file() or sha256_file(path) != digest:
            raise ValueError(f"preview build {owner} changed after compilation")
    evidence = manifest.get("evidence")
    facts = evidence.get("facts") if isinstance(evidence, dict) else None
    if not isinstance(facts, list):
        raise ValueError("preview build evidence inventory is missing")
    for fact in facts:
        if not isinstance(fact, dict):
            raise ValueError("preview build evidence record is invalid")
        path_value = fact.get("path")
        digest = fact.get("sha256")
        if not isinstance(path_value, str) or not isinstance(digest, str):
            raise ValueError("preview build evidence record is invalid")
        fact_path = (vault_root.resolve() / path_value).resolve()
        if not fact_path.is_relative_to(vault_root.resolve()):
            raise ValueError("preview build evidence path is unsafe")
        if not fact_path.is_file() or sha256_file(fact_path) != digest:
            raise ValueError(f"preview build evidence changed: {fact_path.name}")
    if not json_path.is_file():
        raise ValueError("preview compiled payload is missing")
    outputs = manifest.get("outputs")
    if not isinstance(outputs, list):
        raise ValueError("preview build output inventory is missing")
    expected_json_path = relative_output(json_path, project_root)
    json_record = next(
        (
            value
            for value in outputs
            if isinstance(value, dict) and value.get("path") == expected_json_path
        ),
        None,
    )
    if not isinstance(json_record, dict) or json_record.get("sha256") != sha256_file(json_path):
        raise ValueError("preview compiled payload changed after compilation")
    return json_path, manifest_path, manifest


def preview_resume(
    resume: Path,
    *,
    output_base: Path | None = None,
    vault_root: Path = Path("vault"),
    template: Path = Path("templates/resume-template.html"),
    synthesis_plan: Path | None = None,
    accept_review_risk: bool = False,
    review_risk_note: str | None = None,
) -> dict[str, Any]:
    """Compile and publish the current draft for the user's preview/edit loop."""
    project_root = vault_root.expanduser().resolve().parent
    resume_path = contained_project_path(resume, project_root, "resumes", "resume")
    template_path = contained_project_path(template, project_root, "templates", "template")
    base_argument = output_base or default_resume_output_base(resume_path)
    resolved_base = contained_project_path(base_argument, project_root, "build", "output base")
    if resolved_base.suffix:
        raise ValueError("output base must not have a file extension")

    requested_plan_argument = synthesis_plan or Path("resumes/plans") / f"{resume_path.stem}.yaml"
    requested_plan = contained_project_path(
        requested_plan_argument,
        project_root,
        "resumes/plans",
        "synthesis plan",
    )
    needs_build = False
    try:
        json_path, build_manifest_path, build_manifest = _current_build(
            resume_path, project_root, vault_root, resolved_base
        )
    except ValueError:
        needs_build = True
    else:
        build_template = build_manifest.get("template")
        build_synthesis = build_manifest.get("synthesis")
        needs_build = (
            not isinstance(build_template, dict)
            or build_template.get("path") != relative_output(template_path, project_root)
            or not isinstance(build_synthesis, dict)
            or build_synthesis.get("path") != relative_output(requested_plan, project_root)
        )
    if needs_build:
        build_resume(
            resume_path,
            output_base=resolved_base,
            vault_root=vault_root,
            template=template_path,
            synthesis_plan=synthesis_plan,
        )
        json_path, build_manifest_path, build_manifest = _current_build(
            resume_path, project_root, vault_root, resolved_base
        )
    build_template = build_manifest.get("template")
    if not isinstance(build_template, dict) or build_template.get("path") != relative_output(
        template_path, project_root
    ):
        raise ValueError("preview build uses a different rendering template")
    synthesis = build_manifest.get("synthesis")
    if not isinstance(synthesis, dict) or synthesis.get("path") != relative_output(
        requested_plan, project_root
    ):
        raise ValueError("preview build uses a different synthesis plan")
    language = current_language_review(resume_path, project_root)
    synthesis_record = build_manifest.get("synthesis")
    if not isinstance(synthesis_record, dict) or not isinstance(synthesis_record.get("path"), str):
        raise ValueError("preview build synthesis record is missing")
    plan = load_synthesis_plan(Path(synthesis_record["path"]), project_root, project_root / "vault")
    route = hybrid_review_route(plan)
    role_fit, career_verdict, career_record = _current_career_review(
        resume_path, project_root, language
    )
    career_required = bool(route["career_review"]["run"])
    if career_required and career_record is None:
        raise ValueError(
            "the hybrid fit check requires the career-strategist and hiring-manager review "
            "before preview because this resume is competitive but still improvable"
        )
    if career_record is None:
        role_fit = str(route["fit"]["band"])
        career_verdict = (
            "gap-documented" if route["fit"]["band"] == "weak-or-exploratory" else "not-required"
        )
    html_path = resolved_base.with_suffix(".html")
    preview_manifest_path = resolved_base.with_suffix(".preview.json")
    payload = load_payload(json_path)
    experience_bullets = sum(
        len(item.get("bullets", []))
        for item in payload.get("experience", [])
        if isinstance(item, dict)
    )
    template_text = template_path.read_text(encoding="utf-8")
    rendered = render_payload(
        payload,
        template_text,
        known_fact_ids(vault_root.resolve()),
        preview_notice=(APPROVED_NOTICE if language["status"] == "approved" else ATTENTION_NOTICE),
        review_issues={str(issue["id"]): str(issue["note"]) for issue in language["issues"]},
    )
    atomic_write_text(html_path, rendered)

    relative_html_path = relative_output(html_path, project_root)
    evidence = build_manifest.get("evidence")
    evidence_status = (
        "claim-checked"
        if isinstance(evidence, dict) and isinstance(evidence.get("structured_claims_checked"), int)
        else "legacy-not-separated"
    )
    presentation = _handoff_presentation(
        tailored=resume_path.parent.name == "tailored",
        language_status=str(language["status"]),
        language_issues=len(language["issues"]),
        career_verdict=career_verdict,
        career_note=career_record.get("next_action") if career_record else None,
    )
    user_handoff: dict[str, Any] = {
        "required": True,
        "action": "present-preview",
        "presentation_policy": PRESENTATION_POLICY,
        "artifact": {
            "path": relative_html_path,
            "media_type": "text/html",
            "label": "Open the current resume preview",
        },
        "approval": {
            "required": True,
            "status": "pending",
            "next_action_on_approval": (
                "mint" if language["status"] == "approved" else "revise-language"
            ),
        },
        "presentation": presentation,
    }

    manifest = {
        "version": 4,
        "phase": "preview",
        "valid": True,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "compiler": {"name": "resume-builder", "version": __version__},
        "source": relative_output(resume_path, project_root),
        "review_statuses": {
            "evidence_integrity": evidence_status,
            "language_review": language["status"],
            "role_fit": role_fit,
            "career_verdict": career_verdict,
            "user_review": "pending",
        },
        "language_review": {
            "path": relative_output(language["path"], project_root),
            "sha256": language["sha256"],
            "issues": language["issues"],
        },
        "career_review": career_record,
        "hybrid_review": route,
        "preview_mode": {
            **PREVIEW_MODE,
            "experience_bullets": experience_bullets,
        },
        "build_manifest": {
            "path": relative_output(build_manifest_path, project_root),
            "sha256": sha256_file(build_manifest_path),
        },
        "final_review_status": "awaiting-user-approval",
        "output": {
            "path": relative_html_path,
            "sha256": sha256_file(html_path),
        },
        "user_handoff": user_handoff,
        "warnings": list(build_manifest.get("warnings", [])),
        "errors": [],
    }
    atomic_write_json(preview_manifest_path, manifest)
    absolute_html_path = str(html_path.resolve())
    artifact_markdown = f"[Open the full resume preview](<{absolute_html_path}>)"
    return {
        "valid": True,
        "source": relative_output(resume_path, project_root),
        "outputs": [
            relative_output(html_path, project_root),
            relative_output(preview_manifest_path, project_root),
        ],
        "review_statuses": manifest["review_statuses"],
        "final_review_status": "awaiting-user-approval",
        "preview_mode": manifest["preview_mode"],
        "user_handoff": {
            **user_handoff,
            "artifact": {
                **user_handoff["artifact"],
                "absolute_path": absolute_html_path,
                "markdown": artifact_markdown,
            },
            "rendered_markdown": _render_handoff_markdown(presentation, artifact_markdown),
        },
        "warnings": list(build_manifest.get("warnings", [])),
    }


def main(argv: Sequence[str] | None = None) -> int:
    """Compile and publish one resume as editable HTML under build/."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("resume", type=Path)
    parser.add_argument("--output-base", type=Path)
    parser.add_argument("--vault-root", type=Path, default=Path("vault"))
    parser.add_argument("--template", type=Path, default=Path("templates/resume-template.html"))
    parser.add_argument("--synthesis-plan", type=Path)
    parser.add_argument("--accept-review-risk", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--review-risk-note", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        result = preview_resume(
            args.resume,
            output_base=args.output_base,
            vault_root=args.vault_root,
            template=args.template,
            synthesis_plan=args.synthesis_plan,
            accept_review_risk=args.accept_review_risk,
            review_risk_note=args.review_risk_note,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": str(exc)}, indent=2), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
