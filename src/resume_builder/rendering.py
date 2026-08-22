#!/usr/bin/env python3
"""Render a validated, evidence-grounded resume payload into ATS-safe HTML."""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .atomic import atomic_write_text
from .layout import VaultLayout

PLACEHOLDER = re.compile(r"\{\{[A-Z_]+\}\}")
PAGE_FORMATS = {
    "letter": {"size": "Letter", "width": "8.5in", "height": "11in"},
    "a4": {"size": "A4", "width": "210mm", "height": "297mm"},
}
SECTION_TITLES = {
    "summary": "Professional Summary",
    "competencies": "Core Competencies",
    "experience": "Work Experience",
    "projects": "Selected Projects",
    "education": "Education",
    "certifications": "Certifications",
    "skills": "Technical Skills",
}


def text(value: object, owner: str, *, required: bool = True) -> str:
    """Return a validated string field."""
    if value is None and not required:
        return ""
    if not isinstance(value, str) or (required and not value.strip()):
        raise ValueError(f"{owner} must be a{' non-empty' if required else ''} string")
    return value.strip()


def object_value(value: object, owner: str) -> dict[str, Any]:
    """Return a validated JSON object."""
    if not isinstance(value, dict):
        raise ValueError(f"{owner} must be an object")
    return value


def object_list(value: object, owner: str) -> list[dict[str, Any]]:
    """Return a list containing only JSON objects."""
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ValueError(f"{owner} must be a list of objects")
    return value


def known_fact_ids(vault_root: Path) -> set[str]:
    """Collect canonical fact IDs from the configured facts directory."""
    layout = VaultLayout.load(vault_root)
    return {path.stem for path in layout.facts.rglob("*.md")}


def evidence(value: object, owner: str, fact_ids: set[str]) -> list[str]:
    """Validate a non-empty evidence list against canonical fact IDs."""
    if not isinstance(value, list) or not value:
        raise ValueError(f"{owner} evidence must be a non-empty list")
    if not all(isinstance(item, str) and item for item in value):
        raise ValueError(f"{owner} evidence must contain non-empty fact IDs")
    unknown = sorted(set(value) - fact_ids)
    if unknown:
        raise ValueError(f"{owner} references unknown fact IDs: {unknown}")
    return list(dict.fromkeys(value))


def escaped(value: object, owner: str, *, required: bool = True) -> str:
    """Validate and HTML-escape one text field."""
    return html.escape(text(value, owner, required=required), quote=True)


def evidence_attribute(ids: list[str]) -> str:
    """Render hidden evidence metadata for audits and regression tooling."""
    return f'data-evidence="{html.escape(" ".join(ids), quote=True)}"'


def safe_link(url: object, owner: str) -> str:
    """Allow only HTTP(S) contact links."""
    value = text(url, owner)
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"{owner} must use an http or https URL")
    return html.escape(value, quote=True)


def contact_html(candidate: dict[str, Any]) -> str:
    """Render non-empty contact fields without dangling separators."""
    items: list[str] = []
    phone = text(candidate.get("phone"), "candidate.phone", required=False)
    email = text(candidate.get("email"), "candidate.email", required=False)
    location = text(candidate.get("location"), "candidate.location", required=False)
    if phone:
        phone_href = html.escape(phone.replace(" ", ""), quote=True)
        items.append(f'<a class="contact-item" href="tel:{phone_href}">{html.escape(phone)}</a>')
    if email:
        items.append(
            f'<a class="contact-item" href="mailto:{html.escape(email, quote=True)}">'
            f"{html.escape(email)}</a>"
        )
    for key in ("linkedin", "github", "portfolio"):
        raw = candidate.get(key)
        if raw is None:
            continue
        link = object_value(raw, f"candidate.{key}")
        url = safe_link(link.get("url"), f"candidate.{key}.url")
        display = escaped(link.get("display"), f"candidate.{key}.display")
        items.append(f'<a class="contact-item" href="{url}">{display}</a>')
    if location:
        items.append(f'<span class="contact-item">{html.escape(location)}</span>')
    if not items:
        raise ValueError("candidate requires at least one contact field")
    return "".join(items)


def section(title: str, body: str, class_name: str = "") -> str:
    """Wrap a non-empty section using standard ATS-visible headings."""
    if not body:
        return ""
    extra = f" {class_name}" if class_name else ""
    return (
        f'<section class="section{extra}">'
        f'<h2 class="section-title">{html.escape(title)}</h2>{body}</section>'
    )


def review_block_id(block_id: str) -> str:
    """Return a stable, HTML-safe anchor for one narrative review block."""
    return "review-block-" + re.sub(r"[^a-z0-9]+", "-", block_id.casefold()).strip("-")


def review_label(block_id: str) -> str:
    """Return a concise reader-facing label for one narrative block ID."""
    if block_id == "candidate.headline":
        return "Headline"
    if block_id == "summary":
        return "Professional summary"
    match = re.fullmatch(r"competencies\[(\d+)\]", block_id)
    if match:
        return f"Core competency {int(match.group(1)) + 1}"
    match = re.fullmatch(r"experience\[(\d+)\]\.bullets\[(\d+)\]", block_id)
    if match:
        return f"Experience {int(match.group(1)) + 1}, bullet {int(match.group(2)) + 1}"
    match = re.fullmatch(r"projects\[(\d+)\]\.(name|description|tech)", block_id)
    if match:
        field = {"name": "name", "description": "description", "tech": "technology"}[match.group(2)]
        return f"Project {int(match.group(1)) + 1} {field}"
    match = re.fullmatch(r"education\[(\d+)\]\.description", block_id)
    if match:
        return f"Education {int(match.group(1)) + 1} description"
    return block_id


def review_text(block_id: str, content: str, review_issues: Mapping[str, str]) -> str:
    """Wrap visible prose with a stable review target and optional screen-only flag."""
    issue = review_issues.get(block_id)
    anchor = review_block_id(block_id)
    block_attribute = html.escape(block_id, quote=True)
    if issue is None:
        return (
            f'<span id="{anchor}" class="review-text" '
            f'data-review-block="{block_attribute}">{content}</span>'
        )
    note_id = f"{anchor}-note"
    escaped_note = html.escape(issue, quote=True)
    return (
        f'<span id="{anchor}" class="review-text review-issue" '
        f'data-review-block="{block_attribute}" data-review-status="changes-required" '
        f'aria-describedby="{note_id}">{content}'
        '<span class="review-issue-badge" aria-hidden="true">Needs review</span>'
        f'<span id="{note_id}" class="screen-reader-only">Needs review: {escaped_note}</span>'
        "</span>"
    )


def review_panel(review_issues: Mapping[str, str]) -> str:
    """Render a concise screen-only index of language issues."""
    if not review_issues:
        return ""
    noun = "item" if len(review_issues) == 1 else "items"
    items = []
    for block_id, note in review_issues.items():
        anchor = review_block_id(block_id)
        items.append(
            f'<li><a href="#{anchor}"><span class="review-panel-label">'
            f"{html.escape(review_label(block_id))}</span>"
            f'<span class="review-panel-note">{html.escape(note)}</span></a></li>'
        )
    return (
        '<aside class="review-panel" aria-labelledby="review-panel-title">'
        '<div class="review-panel-kicker">Independent language review</div>'
        f'<h2 id="review-panel-title">{len(review_issues)} {noun} needs revision</h2>'
        "<p>Highlighted wording should be revised before minting.</p>"
        f"<ol>{''.join(items)}</ol></aside>"
    )


def render_payload(
    payload: dict[str, Any],
    template: str,
    fact_ids: set[str],
    *,
    preview_notice: str = "Unreviewed diagnostic render — not approved for final review",
    review_issues: Mapping[str, str] | None = None,
) -> str:
    """Render one validated payload into the supplied template."""
    if payload.get("version") != 1:
        raise ValueError("resume payload must declare version 1")
    page_format = payload.get("page_format", "letter")
    if page_format not in PAGE_FORMATS:
        raise ValueError("page_format must be letter or a4")
    page = PAGE_FORMATS[page_format]
    candidate = object_value(payload.get("candidate"), "candidate")
    header_evidence = evidence(candidate.get("evidence"), "candidate", fact_ids)
    issues = dict(review_issues or {})
    if not all(
        isinstance(key, str) and isinstance(value, str) and value.strip()
        for key, value in issues.items()
    ):
        raise ValueError("review issues must map block IDs to non-empty notes")
    if issues and "{{REVIEW_ISSUES}}" not in template:
        raise ValueError(
            "rendering template cannot display language review issues; update it to include "
            "the {{REVIEW_ISSUES}} placeholder"
        )
    rendered_review_blocks: set[str] = {"candidate.headline", "summary"}

    summary_value = escaped(payload.get("summary"), "summary")
    summary_evidence = evidence(payload.get("summary_evidence"), "summary", fact_ids)
    summary_body = (
        f'<p class="summary" {evidence_attribute(summary_evidence)}>'
        f"{review_text('summary', summary_value, issues)}</p>"
    )

    competency_parts: list[str] = []
    for index, item in enumerate(object_list(payload.get("competencies"), "competencies")):
        owner = f"competencies[{index}]"
        rendered_review_blocks.add(owner)
        item_evidence = evidence(item.get("evidence"), owner, fact_ids)
        competency_parts.append(
            f'<span class="competency" {evidence_attribute(item_evidence)}>'
            f"{review_text(owner, escaped(item.get('text'), f'{owner}.text'), issues)}</span>"
        )

    experience_parts: list[str] = []
    for index, item in enumerate(object_list(payload.get("experience"), "experience")):
        owner = f"experience[{index}]"
        item_evidence = evidence(item.get("evidence"), owner, fact_ids)
        bullets = object_list(item.get("bullets"), f"{owner}.bullets")
        if not bullets:
            raise ValueError(f"{owner}.bullets must not be empty")
        bullet_parts: list[str] = []
        for bullet_index, bullet in enumerate(bullets):
            bullet_owner = f"{owner}.bullets[{bullet_index}]"
            rendered_review_blocks.add(bullet_owner)
            bullet_evidence = evidence(bullet.get("evidence"), bullet_owner, fact_ids)
            bullet_parts.append(
                f"<li {evidence_attribute(bullet_evidence)}>"
                f"{review_text(bullet_owner, escaped(bullet.get('text'), f'{bullet_owner}.text'), issues)}</li>"
            )
        location = escaped(item.get("location"), f"{owner}.location", required=False)
        location_html = f'<div class="location">{location}</div>' if location else ""
        experience_parts.append(
            f'<article class="job" {evidence_attribute(item_evidence)}>'
            '<div class="job-header">'
            f'<span class="company">{escaped(item.get("company"), f"{owner}.company")}</span>'
            f'<span class="dates">{escaped(item.get("dates"), f"{owner}.dates")}</span>'
            "</div>"
            f'<div class="role">{escaped(item.get("role"), f"{owner}.role")}</div>'
            f"{location_html}<ul>{''.join(bullet_parts)}</ul></article>"
        )

    project_parts: list[str] = []
    for index, item in enumerate(object_list(payload.get("projects"), "projects")):
        owner = f"projects[{index}]"
        rendered_review_blocks.update({f"{owner}.name", f"{owner}.description"})
        item_evidence = evidence(item.get("evidence"), owner, fact_ids)
        tech = escaped(item.get("tech"), f"{owner}.tech", required=False)
        if tech:
            rendered_review_blocks.add(f"{owner}.tech")
        meta = (
            f'<div class="project-meta">{review_text(f"{owner}.tech", tech, issues)}</div>'
            if tech
            else ""
        )
        project_parts.append(
            f'<article class="project" {evidence_attribute(item_evidence)}>'
            f'<div class="project-name">'
            f"{review_text(f'{owner}.name', escaped(item.get('name'), f'{owner}.name'), issues)}</div>"
            f'<div class="project-description">'
            f"{review_text(f'{owner}.description', escaped(item.get('description'), f'{owner}.description'), issues)}"
            f"</div>{meta}</article>"
        )

    education_parts: list[str] = []
    for index, item in enumerate(object_list(payload.get("education"), "education")):
        owner = f"education[{index}]"
        item_evidence = evidence(item.get("evidence"), owner, fact_ids)
        year = escaped(item.get("year"), f"{owner}.year", required=False)
        description = escaped(item.get("description"), f"{owner}.description", required=False)
        if description:
            rendered_review_blocks.add(f"{owner}.description")
        description_html = (
            f'<div class="education-description">'
            f"{review_text(f'{owner}.description', description, issues)}</div>"
            if description
            else ""
        )
        education_parts.append(
            f'<article class="education" {evidence_attribute(item_evidence)}>'
            '<div class="education-header">'
            f'<span><span class="education-title">'
            f"{escaped(item.get('title'), f'{owner}.title')}</span> - "
            f'<span class="education-org">{escaped(item.get("org"), f"{owner}.org")}</span></span>'
            f'<span class="year">{year}</span></div>{description_html}</article>'
        )

    certification_parts: list[str] = []
    for index, item in enumerate(object_list(payload.get("certifications"), "certifications")):
        owner = f"certifications[{index}]"
        item_evidence = evidence(item.get("evidence"), owner, fact_ids)
        org = escaped(item.get("org"), f"{owner}.org", required=False)
        year = escaped(item.get("year"), f"{owner}.year", required=False)
        org_html = f' - <span class="certification-org">{org}</span>' if org else ""
        certification_parts.append(
            f'<div class="certification" {evidence_attribute(item_evidence)}>'
            f'<span><span class="certification-title">'
            f"{escaped(item.get('title'), f'{owner}.title')}</span>{org_html}</span>"
            f'<span class="year">{year}</span></div>'
        )

    skill_parts: list[str] = []
    for index, item in enumerate(object_list(payload.get("skills"), "skills")):
        owner = f"skills[{index}]"
        item_evidence = evidence(item.get("evidence"), owner, fact_ids)
        items = item.get("items")
        if (
            not isinstance(items, list)
            or not items
            or not all(isinstance(skill, str) and skill.strip() for skill in items)
        ):
            raise ValueError(f"{owner}.items must be a non-empty list of strings")
        rendered_items = ", ".join(html.escape(skill.strip()) for skill in items)
        skill_parts.append(
            f'<div class="skill-group" {evidence_attribute(item_evidence)}>'
            f'<span class="skill-label">{escaped(item.get("category"), f"{owner}.category")}: '
            f"</span>{rendered_items}</div>"
        )

    lang = text(payload.get("lang", "en"), "lang")
    unknown_issues = sorted(set(issues) - rendered_review_blocks)
    if unknown_issues:
        raise ValueError(f"review issues reference unknown narrative blocks: {unknown_issues}")
    replacements = {
        "{{LANG}}": html.escape(lang, quote=True),
        "{{PAGE_SIZE}}": page["size"],
        "{{PAGE_WIDTH}}": page["width"],
        "{{PAGE_MIN_HEIGHT}}": page["height"],
        "{{TITLE}}": f"{escaped(candidate.get('name'), 'candidate.name')} - Resume",
        "{{HEADER_EVIDENCE}}": evidence_attribute(header_evidence),
        "{{NAME}}": escaped(candidate.get("name"), "candidate.name"),
        "{{HEADLINE}}": review_text(
            "candidate.headline",
            escaped(candidate.get("headline"), "candidate.headline"),
            issues,
        ),
        "{{CONTACT}}": contact_html(candidate),
        "{{SUMMARY_SECTION}}": section(SECTION_TITLES["summary"], summary_body, "summary-section"),
        "{{COMPETENCIES_SECTION}}": section(
            SECTION_TITLES["competencies"],
            f'<div class="competencies">{"".join(competency_parts)}</div>'
            if competency_parts
            else "",
        ),
        "{{EXPERIENCE_SECTION}}": section(SECTION_TITLES["experience"], "".join(experience_parts)),
        "{{PROJECTS_SECTION}}": section(SECTION_TITLES["projects"], "".join(project_parts)),
        "{{EDUCATION_SECTION}}": section(SECTION_TITLES["education"], "".join(education_parts)),
        "{{CERTIFICATIONS_SECTION}}": section(
            SECTION_TITLES["certifications"], "".join(certification_parts)
        ),
        "{{SKILLS_SECTION}}": section(
            SECTION_TITLES["skills"],
            f'<div class="skills">{"".join(skill_parts)}</div>' if skill_parts else "",
        ),
        "{{PREVIEW_NOTICE}}": html.escape(preview_notice),
        "{{REVIEW_ISSUES}}": review_panel(issues),
    }
    section_html = {
        "summary": replacements["{{SUMMARY_SECTION}}"],
        "competencies": replacements["{{COMPETENCIES_SECTION}}"],
        "experience": replacements["{{EXPERIENCE_SECTION}}"],
        "projects": replacements["{{PROJECTS_SECTION}}"],
        "education": replacements["{{EDUCATION_SECTION}}"],
        "certifications": replacements["{{CERTIFICATIONS_SECTION}}"],
        "skills": replacements["{{SKILLS_SECTION}}"],
    }
    raw_section_order = payload.get("section_order")
    if raw_section_order is None:
        ordered_section_ids = list(section_html)
    elif not isinstance(raw_section_order, list) or not all(
        isinstance(item, str) and item in section_html for item in raw_section_order
    ):
        raise ValueError("section_order must contain canonical resume section IDs")
    else:
        ordered_section_ids = list(raw_section_order)
        if len(set(ordered_section_ids)) != len(ordered_section_ids):
            raise ValueError("section_order must not contain duplicates")
    replacements["{{RESUME_SECTIONS}}"] = "".join(
        section_html[section_id] for section_id in ordered_section_ids
    )
    rendered = template
    for placeholder, replacement in replacements.items():
        rendered = rendered.replace(placeholder, replacement)
    unresolved = sorted(set(PLACEHOLDER.findall(rendered)))
    if unresolved:
        raise ValueError(f"template contains unresolved placeholders: {unresolved}")
    return rendered


def load_payload(path: Path) -> dict[str, Any]:
    """Load a structured resume payload."""
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise ValueError(f"cannot read resume payload: {exc}") from exc
    return object_value(value, "resume payload")


def contained_project_path(path: Path, root: Path, directory: str, owner: str) -> Path:
    """Require generated and template paths to remain in their project areas."""
    expanded = path.expanduser()
    resolved = expanded.resolve() if expanded.is_absolute() else (root / expanded).resolve()
    allowed = (root / directory).resolve()
    if not resolved.is_relative_to(allowed):
        raise ValueError(f"{owner} must be under {allowed}")
    return resolved


def main(argv: Sequence[str] | None = None) -> int:
    """Render one structured payload to an HTML file under build/."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("payload", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--vault-root", type=Path, default=Path("vault"))
    parser.add_argument("--template", type=Path, default=Path("templates/resume-template.html"))
    args = parser.parse_args(argv)
    try:
        project_root = args.vault_root.expanduser().resolve().parent
        output = contained_project_path(args.output, project_root, "build", "output")
        template_path = contained_project_path(args.template, project_root, "templates", "template")
        payload = load_payload(args.payload)
        template = template_path.read_text(encoding="utf-8")
        rendered = render_payload(payload, template, known_fact_ids(args.vault_root.resolve()))
        atomic_write_text(output, rendered)
        rendered_evidence = {
            fact_id
            for attribute in re.findall(r'data-evidence="([^"]+)"', rendered)
            for fact_id in attribute.split()
        }
        result = {
            "valid": True,
            "output": output.relative_to(project_root).as_posix(),
            "template": template_path.relative_to(project_root).as_posix(),
            "evidence_ids": len(rendered_evidence),
        }
    except (OSError, ValueError) as exc:
        print(json.dumps({"error": str(exc)}, indent=2), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
