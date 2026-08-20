"""Parse canonical resume Markdown into the renderer payload.

This module is dependency-neutral with respect to compilation workflows so
feedback recording and editorial review can inspect narrative blocks without
creating orchestration import cycles.
"""

from __future__ import annotations

import re
from typing import Any

import yaml

from .rendering import object_value

EVIDENCE = re.compile(r"<!--\s*evidence:\s*([^<>]+?)\s*-->", re.IGNORECASE)
STORY = re.compile(r"<!--\s*story:\s*([a-z0-9]+(?:-[a-z0-9]+)*)\s*-->", re.IGNORECASE)
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
