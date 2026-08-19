#!/usr/bin/env python3
"""Publish a career-professional-reviewed resume as a web preview."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import __version__
from .atomic import atomic_write_json, atomic_write_text
from .compilation import relative_output, sha256_file
from .rendering import contained_project_path, known_fact_ids, load_payload, render_payload
from .review_records import require_editorial_approval
from .review_records import sha256_file as review_sha256_file

READY_NOTICE = "Evidence checked · Language reviewed · Awaiting your final approval"
RISK_NOTICE = "Evidence checked · Language reviewed · Career-fit risk remains"
PREVIEW_MODE = {
    "kind": "continuous-web",
    "pagination": "PDF page count is calculated only during minting",
}


def _current_build(
    resume: Path,
    project_root: Path,
    vault_root: Path,
    resolved_base: Path,
) -> tuple[Path, Path, dict[str, Any]]:
    """Return current compiled artifacts without rebuilding reviewed content."""
    json_path = resolved_base.with_suffix(".json")
    manifest_path = resolved_base.with_suffix(".manifest.json")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("preview requires a current compiled build") from exc
    if not isinstance(manifest, dict) or manifest.get("phase") != "build":
        raise ValueError("preview requires a valid build manifest")
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
    """Publish the exact compiled build after a fresh career-professional review."""
    project_root = vault_root.expanduser().resolve().parent
    resume_path = contained_project_path(resume, project_root, "resumes", "resume")
    template_path = contained_project_path(template, project_root, "templates", "template")
    base_argument = output_base or Path("build") / resume_path.stem
    resolved_base = contained_project_path(base_argument, project_root, "build", "output base")
    if resolved_base.suffix:
        raise ValueError("output base must not have a file extension")

    json_path, build_manifest_path, build_manifest = _current_build(
        resume_path, project_root, vault_root, resolved_base
    )
    build_template = build_manifest.get("template")
    if not isinstance(build_template, dict) or build_template.get("path") != relative_output(
        template_path, project_root
    ):
        raise ValueError("preview build uses a different rendering template")
    review = require_editorial_approval(
        resume_path,
        project_root,
        accept_review_risk=accept_review_risk,
    )
    if synthesis_plan is not None:
        requested_plan = contained_project_path(
            synthesis_plan, project_root, "resumes/plans", "synthesis plan"
        )
        synthesis = build_manifest.get("synthesis")
        if not isinstance(synthesis, dict) or synthesis.get("path") != relative_output(
            requested_plan, project_root
        ):
            raise ValueError("preview build uses a different synthesis plan")
    if review.verdict == "needs-revision" and accept_review_risk:
        if not isinstance(review_risk_note, str) or not review_risk_note.strip():
            raise ValueError("accepted review risk requires --review-risk-note")
        risk_acceptance: dict[str, object] | None = {
            "accepted": True,
            "note": review_risk_note.strip(),
        }
        preview_notice = RISK_NOTICE
    else:
        risk_acceptance = None
        preview_notice = READY_NOTICE

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
        preview_notice=preview_notice,
    )
    atomic_write_text(html_path, rendered)

    manifest = {
        "version": 2,
        "phase": "preview",
        "valid": True,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "compiler": {"name": "resume-builder", "version": __version__},
        "source": relative_output(resume_path, project_root),
        "review_record": {
            "path": relative_output(review.source, project_root),
            "sha256": review_sha256_file(review.source),
            "verdict": review.verdict,
            "hiring_read": review.hiring_read,
            "status": review.editorial_status,
        },
        "review_statuses": {
            "evidence_integrity": review.evidence_status or "legacy-not-separated",
            "language_review": review.editorial_status,
            "role_fit": review.hiring_read,
            "career_verdict": review.verdict,
            "user_review": "pending",
        },
        "risk_acceptance": risk_acceptance,
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
            "path": relative_output(html_path, project_root),
            "sha256": sha256_file(html_path),
        },
        "warnings": list(build_manifest.get("warnings", [])),
        "errors": [],
    }
    atomic_write_json(preview_manifest_path, manifest)
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
        "warnings": list(build_manifest.get("warnings", [])),
    }


def main(argv: Sequence[str] | None = None) -> int:
    """Publish one reviewed resume as HTML under build/."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("resume", type=Path)
    parser.add_argument("--output-base", type=Path)
    parser.add_argument("--vault-root", type=Path, default=Path("vault"))
    parser.add_argument("--template", type=Path, default=Path("templates/resume-template.html"))
    parser.add_argument("--synthesis-plan", type=Path)
    parser.add_argument("--accept-review-risk", action="store_true")
    parser.add_argument("--review-risk-note")
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
