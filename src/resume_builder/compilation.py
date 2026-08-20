#!/usr/bin/env python3
"""Compile canonical resume Markdown into validated review artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import __version__
from .atomic import atomic_write_json, atomic_write_text
from .ats import normalize_payload
from .evidence import audit_claims
from .feedback_resolution import guidance_snapshot
from .rendering import contained_project_path, known_fact_ids, render_payload
from .resume_parser import (
    EVIDENCE,
    HEADING,
    SECTION_ALIASES,
    SKILL_LINE,
    STORY,
    compile_markdown,
    delimited,
    evidence_text,
    frontmatter,
    heading_blocks,
    list_blocks,
    sections,
    story_id,
)
from .synthesis import audit_synthesis, load_synthesis_plan

__all__ = [
    "EVIDENCE",
    "HEADING",
    "PREVIEW_NOTICE",
    "SECTION_ALIASES",
    "SKILL_LINE",
    "STALE_PREVIEW_NOTICE",
    "STORY",
    "build_resume",
    "compile_markdown",
    "delimited",
    "evidence_text",
    "frontmatter",
    "heading_blocks",
    "list_blocks",
    "main",
    "mark_published_preview_stale",
    "relative_output",
    "sections",
    "sha256_file",
    "story_id",
]

PREVIEW_NOTICE = re.compile(
    r'(<aside class="draft-notice" role="status">\s*)(.*?)(\s*</aside>)',
    re.DOTALL,
)
STALE_PREVIEW_NOTICE = "Previous preview · Current build changed · Review required"


def sha256_file(path: Path) -> str:
    """Return the content digest used by the reproducibility manifest."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def relative_output(path: Path, project_root: Path) -> str:
    """Return a stable project-relative output path."""
    return path.relative_to(project_root).as_posix()


def mark_published_preview_stale(path: Path) -> None:
    """Keep the stable preview URL while making its stale status visible."""
    if not path.is_file():
        return
    existing = path.read_text(encoding="utf-8")
    updated, replacements = PREVIEW_NOTICE.subn(
        rf"\1{STALE_PREVIEW_NOTICE}\3",
        existing,
        count=1,
    )
    if replacements and updated != existing:
        atomic_write_text(path, updated)


def build_resume(
    resume: Path,
    *,
    output_base: Path | None = None,
    vault_root: Path = Path("vault"),
    template: Path = Path("templates/resume-template.html"),
    synthesis_plan: Path | None = None,
) -> dict[str, Any]:
    """Build validated draft artifacts without creating a release PDF."""
    project_root = vault_root.expanduser().resolve().parent
    resume_path = contained_project_path(resume, project_root, "resumes", "resume")
    template_path = contained_project_path(template, project_root, "templates", "template")
    base_argument = output_base or Path("build") / resume_path.stem
    resolved_base = contained_project_path(base_argument, project_root, "build", "output base")
    if resolved_base.suffix:
        raise ValueError("output base must not have a file extension")

    source_markdown = resume_path.read_text(encoding="utf-8")
    raw_payload = compile_markdown(source_markdown)
    payload, ats_replacements = normalize_payload(raw_payload)
    plan_argument = synthesis_plan or Path("resumes/plans") / f"{resume_path.stem}.yaml"
    plan = load_synthesis_plan(plan_argument, project_root, vault_root.resolve())
    if plan.resume != resume_path:
        raise ValueError("synthesis plan targets a different resume")
    feedback_snapshot = guidance_snapshot(plan, project_root)
    feedback_rules = feedback_snapshot["guidance"]
    synthesis_audit = audit_synthesis(payload, plan)
    claim_specs = {story.story_id: story.claim for story in plan.stories if story.claim is not None}
    grounding_audit = audit_claims(
        payload,
        vault_root.resolve(),
        claim_specs=claim_specs or None,
    )
    facts = known_fact_ids(vault_root.resolve())
    template_text = template_path.read_text(encoding="utf-8")
    # Validate the template and rendered payload without publishing a web preview.
    # A readable HTML artifact is created only by the review-gated preview stage.
    render_payload(payload, template_text, facts)
    json_path = resolved_base.with_suffix(".json")
    manifest_path = resolved_base.with_suffix(".manifest.json")
    atomic_write_json(json_path, payload)
    outputs = [json_path]

    # Published previews and mints are retained. Their manifests pin this build
    # manifest, so rebuilding makes them explicitly stale without breaking the
    # stable user-facing URL or destroying the last inspected artifact.
    review_statuses = {
        "evidence_integrity": ("claim-checked" if plan.version >= 6 else "legacy-not-separated"),
        "language_review": "unreviewed",
        "role_fit": "not-reviewed",
        "career_verdict": "not-reviewed",
        "user_review": "not-published",
    }
    manifest = {
        "version": 1,
        "phase": "build",
        "valid": True,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "compiler": {"name": "resume-builder", "version": __version__},
        "source": {
            "path": relative_output(resume_path, project_root),
            "sha256": hashlib.sha256(source_markdown.encode("utf-8")).hexdigest(),
        },
        "template": {
            "path": relative_output(template_path, project_root),
            "sha256": hashlib.sha256(template_text.encode("utf-8")).hexdigest(),
        },
        "page_format": payload.get("page_format"),
        "synthesis": {
            "path": relative_output(plan.source, project_root),
            "sha256": sha256_file(plan.source),
            **synthesis_audit,
        },
        "evidence": grounding_audit,
        "feedback_memory": {
            "status": "applied" if feedback_rules else "not-applicable",
            "rules": feedback_rules,
            "fingerprint": feedback_snapshot["fingerprint"],
        },
        "ats_replacements": ats_replacements,
        "outputs": [
            {"path": relative_output(path, project_root), "sha256": sha256_file(path)}
            for path in outputs
        ],
        "warnings": list(grounding_audit["warnings"]),
        "errors": [],
        "review_statuses": review_statuses,
        "editorial_status": "unreviewed",
    }
    atomic_write_json(manifest_path, manifest)
    mark_published_preview_stale(resolved_base.with_suffix(".html"))
    outputs.append(manifest_path)
    return {
        "valid": True,
        "source": relative_output(resume_path, project_root),
        "outputs": [relative_output(path, project_root) for path in outputs],
        "evidence_ids": len(
            {item for match in EVIDENCE.findall(source_markdown) for item in match.split()}
        ),
        "warnings": manifest["warnings"],
        "review_statuses": review_statuses,
    }


def main(argv: Sequence[str] | None = None) -> int:
    """Compile one canonical Markdown resume into review-input artifacts."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("resume", type=Path)
    parser.add_argument("--output-base", type=Path)
    parser.add_argument("--vault-root", type=Path, default=Path("vault"))
    parser.add_argument("--template", type=Path, default=Path("templates/resume-template.html"))
    parser.add_argument("--synthesis-plan", type=Path)
    args = parser.parse_args(argv)
    try:
        result = build_resume(
            args.resume,
            output_base=args.output_base,
            vault_root=args.vault_root,
            template=args.template,
            synthesis_plan=args.synthesis_plan,
        )
    except (OSError, ValueError) as exc:
        print(json.dumps({"error": str(exc)}, indent=2), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
