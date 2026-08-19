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

import yaml

from . import __version__
from .atomic import atomic_write_json, atomic_write_text
from .ats import normalize_payload
from .evidence import audit_claims
from .feedback_memory import guidance_snapshot
from .rendering import contained_project_path, known_fact_ids, object_value, render_payload
from .synthesis import audit_synthesis, load_synthesis_plan

EVIDENCE = re.compile(r"<!--\s*evidence:\s*([^<>]+?)\s*-->", re.IGNORECASE)
STORY = re.compile(r"<!--\s*story:\s*([a-z0-9]+(?:-[a-z0-9]+)*)\s*-->", re.IGNORECASE)
PREVIEW_NOTICE = re.compile(
    r'(<aside class="draft-notice" role="status">\s*)(.*?)(\s*</aside>)',
    re.DOTALL,
)
STALE_PREVIEW_NOTICE = "Previous preview · Current build changed · Review required"
HEADING = re.compile(r"^(#{1,2})\s+(.+?)\s*$")
SKILL_LINE = re.compile(r"^\*\*(.+?):\*\*\s*(.+)$")
SECTION_ALIASES = {
    "professional summary": "summary",
    "summary": "summary",
    "core competencies": "competencies",
    "work experience": "experience",
    "professional experience": "experience",
    "selected projects": "projects",
    "projects": "projects",
    "education": "education",
    "certifications": "certifications",
    "technical skills": "skills",
    "skills": "skills",
}


def frontmatter(markdown: str) -> tuple[dict[str, Any], str]:
    """Load required YAML frontmatter and return the remaining Markdown body."""
    if not markdown.startswith("---\n"):
        raise ValueError("resume Markdown must begin with YAML frontmatter")
    try:
        raw, body = markdown[4:].split("\n---\n", 1)
    except ValueError as exc:
        raise ValueError("resume Markdown frontmatter is not closed with ---") from exc
    try:
        value = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise ValueError(f"invalid resume frontmatter: {exc}") from exc
    metadata = object_value(value, "resume frontmatter")
    allowed = {"version", "lang", "page_format", "candidate"}
    unexpected = sorted(set(metadata) - allowed)
    if unexpected:
        raise ValueError(f"resume frontmatter contains unsupported fields: {unexpected}")
    if metadata.get("version") != 1:
        raise ValueError("resume frontmatter must declare version 1")
    return metadata, body


def evidence_text(block: str, owner: str) -> tuple[str, list[str]]:
    """Return visible text and stable evidence IDs from one factual block."""
    matches = EVIDENCE.findall(block)
    if not matches:
        raise ValueError(f"{owner} requires an evidence comment")
    ids = [item for match in matches for item in match.split()]
    if not ids or any(not re.fullmatch(r"[A-Za-z0-9]+(?:-[A-Za-z0-9]+)+", item) for item in ids):
        raise ValueError(f"{owner} contains an invalid evidence ID")
    visible = STORY.sub("", EVIDENCE.sub("", block))
    if "<!--" in visible or "-->" in visible:
        raise ValueError(f"{owner} contains an unsupported HTML comment")
    visible = " ".join(line.strip() for line in visible.splitlines() if line.strip())
    if not visible:
        raise ValueError(f"{owner} must contain visible text")
    return visible, list(dict.fromkeys(ids))


def story_id(block: str, owner: str) -> str | None:
    """Return one optional synthesis story annotation from a factual block."""
    matches = STORY.findall(block)
    if len(matches) > 1:
        raise ValueError(f"{owner} contains more than one story annotation")
    return matches[0].casefold() if matches else None


def sections(body: str) -> dict[str, list[str]]:
    """Split the resume body into known level-one sections without losing text."""
    result: dict[str, list[str]] = {}
    current: str | None = None
    for line_number, line in enumerate(body.splitlines(), start=1):
        match = HEADING.match(line)
        if match and match.group(1) == "#":
            title = EVIDENCE.sub("", match.group(2)).strip().casefold()
            canonical = SECTION_ALIASES.get(title)
            if canonical is None:
                raise ValueError(
                    f"unsupported level-one section at body line {line_number}: {title}"
                )
            if canonical in result:
                raise ValueError(f"duplicate resume section: {title}")
            result[canonical] = []
            current = canonical
            continue
        if current is None:
            if line.strip():
                raise ValueError(
                    f"content appears before the first resume section at body line {line_number}"
                )
            continue
        result[current].append(line)
    if "summary" not in result:
        raise ValueError("resume requires a Professional Summary section")
    return result


def list_blocks(lines: list[str], owner: str) -> list[str]:
    """Collect Markdown list items with their indented evidence continuations."""
    blocks: list[str] = []
    current: list[str] = []
    for line in lines:
        if line.startswith("- "):
            if current:
                blocks.append("\n".join(current))
            current = [line[2:]]
        elif not line.strip():
            continue
        elif current and (line.startswith("  ") or EVIDENCE.fullmatch(line.strip())):
            current.append(line.strip())
        else:
            raise ValueError(f"{owner} must contain only Markdown list items")
    if current:
        blocks.append("\n".join(current))
    return blocks


def heading_blocks(lines: list[str], owner: str) -> list[tuple[str, list[str]]]:
    """Collect level-two entries and all lines belonging to each entry."""
    result: list[tuple[str, list[str]]] = []
    heading: str | None = None
    content: list[str] = []
    for line in lines:
        match = HEADING.match(line)
        if match and match.group(1) == "##":
            if heading is not None:
                result.append((heading, content))
            heading, content = match.group(2), []
        elif heading is None:
            if line.strip():
                raise ValueError(f"{owner} content must follow a level-two heading")
        else:
            content.append(line)
    if heading is not None:
        result.append((heading, content))
    return result


def delimited(value: str, owner: str, minimum: int, maximum: int) -> list[str]:
    """Split a compact pipe-delimited resume record."""
    parts = [part.strip() for part in value.split("|")]
    if not minimum <= len(parts) <= maximum or any(not part for part in parts[:minimum]):
        raise ValueError(f"{owner} requires {minimum} to {maximum} pipe-delimited fields")
    return parts


def compile_markdown(markdown: str) -> dict[str, Any]:
    """Compile strict canonical Markdown into the renderer's versioned payload."""
    metadata, body = frontmatter(markdown)
    candidate = object_value(metadata.get("candidate"), "candidate")
    section_map = sections(body)

    summary, summary_evidence = evidence_text("\n".join(section_map["summary"]), "summary")
    competencies = []
    for index, block in enumerate(list_blocks(section_map.get("competencies", []), "competencies")):
        value, ids = evidence_text(block, f"competencies[{index}]")
        competencies.append({"text": value, "evidence": ids})

    experience = []
    for index, (heading, lines) in enumerate(
        heading_blocks(section_map.get("experience", []), "experience")
    ):
        heading_value, heading_evidence = evidence_text(heading, f"experience[{index}]")
        parts = delimited(heading_value, f"experience[{index}]", 3, 4)
        bullets = []
        for bullet_index, block in enumerate(list_blocks(lines, f"experience[{index}].bullets")):
            value, ids = evidence_text(block, f"experience[{index}].bullets[{bullet_index}]")
            bullet = {"text": value, "evidence": ids}
            planned_story = story_id(block, f"experience[{index}].bullets[{bullet_index}]")
            if planned_story:
                bullet["story"] = planned_story
            bullets.append(bullet)
        if not bullets:
            raise ValueError(f"experience[{index}] requires at least one bullet")
        item: dict[str, Any] = {
            "company": parts[0],
            "role": parts[1],
            "dates": parts[2],
            "evidence": heading_evidence,
            "bullets": bullets,
        }
        if len(parts) == 4:
            item["location"] = parts[3]
        experience.append(item)

    projects = []
    for index, (heading, lines) in enumerate(
        heading_blocks(section_map.get("projects", []), "projects")
    ):
        name, ids = evidence_text(heading, f"projects[{index}].name")
        description_lines: list[str] = []
        tech = ""
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            match = SKILL_LINE.match(stripped)
            if match and match.group(1).casefold() in {"technology", "technologies", "tech"}:
                if tech:
                    raise ValueError(f"projects[{index}] has more than one technology line")
                tech, tech_ids = evidence_text(match.group(2), f"projects[{index}].tech")
                ids.extend(tech_ids)
            else:
                description_lines.append(stripped)
        description, description_ids = evidence_text(
            "\n".join(description_lines), f"projects[{index}].description"
        )
        item = {
            "name": name,
            "description": description,
            "evidence": list(dict.fromkeys([*ids, *description_ids])),
        }
        planned_story = story_id(heading, f"projects[{index}].name")
        if planned_story:
            item["story"] = planned_story
        if tech:
            item["tech"] = tech
        projects.append(item)

    education = []
    for index, block in enumerate(list_blocks(section_map.get("education", []), "education")):
        value, ids = evidence_text(block, f"education[{index}]")
        parts = delimited(value, f"education[{index}]", 2, 4)
        item = {"title": parts[0], "org": parts[1], "evidence": ids}
        if len(parts) >= 3:
            item["year"] = parts[2]
        if len(parts) == 4:
            item["description"] = parts[3]
        education.append(item)

    certifications = []
    for index, block in enumerate(
        list_blocks(section_map.get("certifications", []), "certifications")
    ):
        value, ids = evidence_text(block, f"certifications[{index}]")
        parts = delimited(value, f"certifications[{index}]", 1, 3)
        item = {"title": parts[0], "evidence": ids}
        if len(parts) >= 2:
            item["org"] = parts[1]
        if len(parts) == 3:
            item["year"] = parts[2]
        certifications.append(item)

    skills = []
    for index, block in enumerate(list_blocks(section_map.get("skills", []), "skills")):
        value, ids = evidence_text(block, f"skills[{index}]")
        match = SKILL_LINE.match(value)
        if not match:
            raise ValueError(f"skills[{index}] must use **Category:** item, item")
        items = [item.strip() for item in match.group(2).split(",") if item.strip()]
        if not items:
            raise ValueError(f"skills[{index}] requires at least one item")
        skills.append({"category": match.group(1), "items": items, "evidence": ids})

    return {
        "version": 1,
        "lang": metadata.get("lang", "en"),
        "page_format": metadata.get("page_format", "letter"),
        "candidate": candidate,
        "summary": summary,
        "summary_evidence": summary_evidence,
        "competencies": competencies,
        "experience": experience,
        "projects": projects,
        "education": education,
        "certifications": certifications,
        "skills": skills,
    }


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
