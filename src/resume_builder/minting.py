#!/usr/bin/env python3
"""Mint a validated resume draft as a final, audited PDF artifact."""

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
from .compilation import relative_output, sha256_file
from .pdf_rendering import render_pdf
from .rendering import contained_project_path
from .review_records import require_editorial_approval
from .review_records import sha256_file as review_sha256_file


def mint_resume(
    resume: Path,
    *,
    output_base: Path | None = None,
    browser: Path | None = None,
    max_pages: int | None = None,
    vault_root: Path = Path("vault"),
    template: Path = Path("templates/resume-template.html"),
    synthesis_plan: Path | None = None,
    accept_review_risk: bool = False,
) -> dict[str, Any]:
    """Render the exact user-reviewed HTML as a PDF and audit the final artifact."""
    if max_pages is not None and max_pages < 1:
        raise ValueError("--max-pages must be a positive integer")
    project_root = vault_root.expanduser().resolve().parent
    resume_path = contained_project_path(resume, project_root, "resumes", "resume")
    base_argument = output_base or Path("build") / resume_path.stem
    resolved_base = contained_project_path(base_argument, project_root, "build", "output base")
    if resolved_base.suffix:
        raise ValueError("output base must not have a file extension")

    review = require_editorial_approval(
        resume_path,
        project_root,
        accept_review_risk=accept_review_risk,
    )

    json_path = resolved_base.with_suffix(".json")
    html_path = resolved_base.with_suffix(".html")
    pdf_path = resolved_base.with_suffix(".pdf")
    build_manifest_path = resolved_base.with_suffix(".manifest.json")
    preview_manifest_path = resolved_base.with_suffix(".preview.json")
    mint_manifest_path = resolved_base.with_suffix(".mint.json")
    try:
        build_manifest = json.loads(build_manifest_path.read_text(encoding="utf-8"))
        preview_manifest = json.loads(preview_manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("mint requires the current user-review web preview") from exc
    if not isinstance(build_manifest, dict) or not isinstance(preview_manifest, dict):
        raise ValueError("mint requires valid build and preview manifests")
    preview_build = preview_manifest.get("build_manifest")
    preview_output = preview_manifest.get("output")
    preview_review = preview_manifest.get("review_record")
    if (
        preview_manifest.get("version") != 2
        or preview_manifest.get("phase") != "preview"
        or preview_manifest.get("valid") is not True
        or not isinstance(preview_build, dict)
        or preview_build.get("path") != relative_output(build_manifest_path, project_root)
        or preview_build.get("sha256") != sha256_file(build_manifest_path)
        or not isinstance(preview_output, dict)
        or preview_output.get("path") != relative_output(html_path, project_root)
        or preview_output.get("sha256") != sha256_file(html_path)
        or not isinstance(preview_review, dict)
        or preview_review.get("path") != relative_output(review.source, project_root)
        or preview_review.get("sha256") != review_sha256_file(review.source)
    ):
        raise ValueError("mint preview is stale; publish and approve the current build")
    if preview_manifest.get("source") != relative_output(resume_path, project_root):
        raise ValueError("mint preview names a different resume")
    if preview_manifest.get("final_review_status") != "awaiting-user-approval":
        raise ValueError("mint preview is not awaiting explicit user approval")
    template_path = contained_project_path(template, project_root, "templates", "template")
    build_template = build_manifest.get("template")
    if not isinstance(build_template, dict) or build_template.get("path") != relative_output(
        template_path, project_root
    ):
        raise ValueError("mint build uses a different rendering template")
    build_outputs = build_manifest.get("outputs")
    expected_json_path = relative_output(json_path, project_root)
    json_record = (
        next(
            (
                value
                for value in build_outputs
                if isinstance(value, dict) and value.get("path") == expected_json_path
            ),
            None,
        )
        if isinstance(build_outputs, list)
        else None
    )
    if not isinstance(json_record, dict) or json_record.get("sha256") != sha256_file(json_path):
        raise ValueError("mint compiled payload changed after compilation")
    if synthesis_plan is not None:
        requested_plan = contained_project_path(
            synthesis_plan, project_root, "resumes/plans", "synthesis plan"
        )
        build_synthesis = build_manifest.get("synthesis")
        if not isinstance(build_synthesis, dict) or build_synthesis.get("path") != relative_output(
            requested_plan, project_root
        ):
            raise ValueError("mint build uses a different synthesis plan")
    if review.verdict == "needs-revision":
        risk_acceptance = preview_manifest.get("risk_acceptance")
        if (
            not accept_review_risk
            or not isinstance(risk_acceptance, dict)
            or risk_acceptance.get("accepted") is not True
            or not isinstance(risk_acceptance.get("note"), str)
            or not str(risk_acceptance["note"]).strip()
        ):
            raise ValueError("mint requires the recorded review-risk acceptance from preview")
    synthesis = build_manifest.get("synthesis")
    planned_budget = None
    if isinstance(synthesis, dict):
        page_budget = synthesis.get("page_budget")
        if isinstance(page_budget, dict) and isinstance(page_budget.get("max_pages"), int):
            planned_budget = int(page_budget["max_pages"])
    resolved_max_pages = max_pages if max_pages is not None else planned_budget or 2
    if planned_budget is not None and max_pages is not None and max_pages != planned_budget:
        raise ValueError(
            "--max-pages disagrees with the resolved synthesis page budget; update the plan first"
        )
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    pdf_audit = render_pdf(html_path, pdf_path, payload, browser)
    pages = pdf_audit["extraction"]["pages"]
    page_error = None
    if pages > resolved_max_pages:
        page_error = (
            f"PDF has {pages} pages; configured maximum is {resolved_max_pages}; "
            "draft PDF was retained for inspection"
        )
    manifest = {
        "version": 2,
        "phase": "mint",
        "valid": page_error is None,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "compiler": {"name": "resume-builder", "version": __version__},
        "source": relative_output(resume_path, project_root),
        "review_record": {
            "path": relative_output(review.source, project_root),
            "sha256": review_sha256_file(review.source),
            "verdict": review.verdict,
            "hiring_read": review.hiring_read,
        },
        "build_manifest": {
            "path": relative_output(build_manifest_path, project_root),
            "sha256": sha256_file(build_manifest_path),
        },
        "preview_manifest": {
            "path": relative_output(preview_manifest_path, project_root),
            "sha256": sha256_file(preview_manifest_path),
        },
        "user_approval": {
            "status": "approved-for-mint",
            "preview_sha256": sha256_file(html_path),
            "recorded_by": "explicit-mint-invocation",
        },
        "max_pages": resolved_max_pages,
        "pdf_audit": pdf_audit,
        "output": {
            "path": relative_output(pdf_path, project_root),
            "sha256": sha256_file(pdf_path),
        },
        "warnings": [page_error] if page_error else [],
        "errors": [page_error] if page_error else [],
    }
    atomic_write_json(mint_manifest_path, manifest)
    if page_error:
        raise ValueError(page_error)
    return {
        "valid": True,
        "source": relative_output(resume_path, project_root),
        "outputs": [
            relative_output(pdf_path, project_root),
            relative_output(mint_manifest_path, project_root),
        ],
        "pages": pages,
        "warnings": list(build_manifest.get("warnings", [])),
    }


def main(argv: Sequence[str] | None = None) -> int:
    """Mint one canonical Markdown resume under resumes/."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("resume", type=Path)
    parser.add_argument("--output-base", type=Path)
    parser.add_argument("--browser", type=Path)
    parser.add_argument("--max-pages", type=int)
    parser.add_argument("--vault-root", type=Path, default=Path("vault"))
    parser.add_argument("--template", type=Path, default=Path("templates/resume-template.html"))
    parser.add_argument("--synthesis-plan", type=Path)
    parser.add_argument("--accept-review-risk", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = mint_resume(
            args.resume,
            output_base=args.output_base,
            browser=args.browser,
            max_pages=args.max_pages,
            vault_root=args.vault_root,
            template=args.template,
            synthesis_plan=args.synthesis_plan,
            accept_review_risk=args.accept_review_risk,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": str(exc)}, indent=2), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
