"""Inventory and advise on visible resume narrative blocks."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .resume_parser import compile_markdown

BLOCK_ID = re.compile(
    r"^(?:candidate\.headline|summary|competencies\[\d+\]|"
    r"experience\[\d+\]\.bullets\[\d+\]|projects\[\d+\]\.(?:name|description|tech)|"
    r"education\[\d+\]\.description)$"
)


@dataclass(frozen=True)
class NarrativeReviewBlock:
    """One narrative block with the visible context needed for editorial judgment."""

    id: str
    text: str
    context: dict[str, str | None]
    advisories: tuple[str, ...] = ()


def _object(value: object, owner: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{owner} must be an object")
    return value


def _neighbor_context(items: list[str], index: int) -> dict[str, str | None]:
    """Return the adjacent visible prose surrounding one ordered block."""
    return {
        "previous_block": items[index - 1] if index > 0 else None,
        "next_block": items[index + 1] if index + 1 < len(items) else None,
    }


def _opening_advisories(text: str, role: str | None) -> tuple[str, ...]:
    """Flag high-confidence role-title repetition without deciding editorial quality."""
    if not role:
        return ()
    opening = re.match(
        r"^(?:as|in\s+(?:my|the)\s+role\s+as)\s+(?:an?\s+)?([^,;:]+)[,;:]",
        text,
        re.IGNORECASE,
    )
    if opening is None:
        return ()
    words = re.compile(r"[a-z0-9]+")
    opening_tokens = set(words.findall(opening.group(1).casefold()))
    role_tokens = set(words.findall(role.casefold()))
    if opening_tokens and opening_tokens <= role_tokens:
        return (
            "opening may repeat the visible role heading; verify that it adds scope, "
            "authority, chronology, contrast, or necessary qualification",
        )
    return ()


def _has_long_parallel_list(text: str) -> bool:
    """Return whether a clause likely contains four or more parallel items."""
    for clause in re.split(r"[;.!?]", text):
        for conjunction in re.finditer(r",\s*(?:and|or)\b", clause, re.IGNORECASE):
            if clause[: conjunction.start()].count(",") >= 3:
                return True
    return False


def _density_advisories(text: str) -> tuple[str, ...]:
    """Flag likely long or nested enumerations without imposing a length limit."""
    comma_count = text.count(",")
    conjunction_count = len(re.findall(r"\b(?:and|or)\b", text, re.IGNORECASE))
    has_clause_pivot = re.search(r"\b(?:while|then)\b", text, re.IGNORECASE) is not None
    if (
        _has_long_parallel_list(text)
        or (comma_count >= 6 and conjunction_count >= 2)
        or (comma_count >= 5 and has_clause_pivot)
    ):
        return (
            "block may contain nested lists competing with its main claim; verify that each "
            "enumerated detail materially improves proof, scope, outcome, or differentiation",
        )
    return ()


def _contribution_advisories(text: str) -> tuple[str, ...]:
    """Flag openings that describe tool contact or leave authority unresolved."""
    advisories: list[str] = []
    if re.match(r"^(?:used|utilized|leveraged)\b", text, re.IGNORECASE):
        advisories.append(
            "opening describes tool use rather than the candidate's contribution; verify that "
            "the supported diagnosis, resolution, change, or result leads the sentence"
        )
    if re.match(r"^participated in or led\b", text, re.IGNORECASE):
        advisories.append(
            "opening leaves the candidate's authority unresolved; preserve uncertainty but "
            "state the supported contribution directly"
        )
    return tuple(advisories)


def _candidate_voice_advisories(text: str) -> tuple[str, ...]:
    """Flag pronouns that may turn an implied-first-person bullet into biography."""
    possible_candidate_reference = re.search(
        r"^(?:he|she)\b"
        r"|^(?:in|during|after|before|throughout)\s+(?:his|her)\b"
        r"|\b(?:himself|herself)\b",
        text,
        re.IGNORECASE,
    )
    if possible_candidate_reference:
        return (
            "block contains a third-person pronoun; identify its referent and revise when it "
            "describes the candidate instead of another person",
        )
    return ()


def _prose_advisories(text: str, role: str | None = None) -> tuple[str, ...]:
    """Return high-confidence prompts for contextual editorial review."""
    return (
        *_opening_advisories(text, role),
        *_density_advisories(text),
        *_contribution_advisories(text),
        *_candidate_voice_advisories(text),
    )


def narrative_block_inventory(path: Path) -> tuple[NarrativeReviewBlock, ...]:
    """Return narrative prose with its visible resume context in reading order."""
    return narrative_block_inventory_from_markdown(path.read_text(encoding="utf-8"))


def narrative_block_inventory_from_markdown(
    markdown: str,
) -> tuple[NarrativeReviewBlock, ...]:
    """Return narrative prose from an in-memory canonical resume."""
    payload = compile_markdown(markdown)
    blocks: list[NarrativeReviewBlock] = []
    candidate = _object(payload.get("candidate"), "candidate")
    candidate_name = str(candidate.get("name", "")) or None
    headline = candidate.get("headline")
    if isinstance(headline, str) and headline.strip():
        headline = headline.strip()
        blocks.append(
            NarrativeReviewBlock(
                id="candidate.headline",
                text=headline,
                context={"section": "Header", "candidate_name": candidate_name},
                advisories=_prose_advisories(headline),
            )
        )
    summary = str(payload["summary"])
    blocks.append(
        NarrativeReviewBlock(
            id="summary",
            text=summary,
            context={"section": "Professional Summary", "headline": str(headline or "") or None},
            advisories=_prose_advisories(summary),
        )
    )
    competency_texts = [str(item["text"]) for item in payload["competencies"]]
    for index, text in enumerate(competency_texts):
        blocks.append(
            NarrativeReviewBlock(
                id=f"competencies[{index}]",
                text=text,
                context={
                    "section": "Core Competencies",
                    **_neighbor_context(competency_texts, index),
                },
                advisories=_prose_advisories(text),
            )
        )
    for experience_index, experience in enumerate(payload["experience"]):
        bullet_texts = [str(bullet["text"]) for bullet in experience["bullets"]]
        company = str(experience.get("company", "")) or None
        role = str(experience.get("role", "")) or None
        dates = str(experience.get("dates", "")) or None
        location = str(experience.get("location", "")) or None
        for bullet_index, bullet in enumerate(experience["bullets"]):
            text = str(bullet["text"])
            blocks.append(
                NarrativeReviewBlock(
                    id=f"experience[{experience_index}].bullets[{bullet_index}]",
                    text=text,
                    context={
                        "section": "Work Experience",
                        "company": company,
                        "role": role,
                        "dates": dates,
                        "location": location,
                        **_neighbor_context(bullet_texts, bullet_index),
                    },
                    advisories=_prose_advisories(text, role),
                )
            )
    for index, project in enumerate(payload["projects"]):
        name = str(project["name"])
        description = str(project["description"])
        blocks.append(
            NarrativeReviewBlock(
                id=f"projects[{index}].name",
                text=name,
                context={"section": "Selected Projects"},
                advisories=_prose_advisories(name),
            )
        )
        blocks.append(
            NarrativeReviewBlock(
                id=f"projects[{index}].description",
                text=description,
                context={"section": "Selected Projects", "project": name},
                advisories=_prose_advisories(description),
            )
        )
        if project.get("tech"):
            blocks.append(
                NarrativeReviewBlock(
                    id=f"projects[{index}].tech",
                    text=str(project["tech"]),
                    context={
                        "section": "Selected Projects",
                        "project": name,
                        "previous_block": description,
                    },
                    advisories=_prose_advisories(str(project["tech"])),
                )
            )
    for index, education in enumerate(payload["education"]):
        if education.get("description"):
            blocks.append(
                NarrativeReviewBlock(
                    id=f"education[{index}].description",
                    text=str(education["description"]),
                    context={
                        "section": "Education",
                        "degree": str(education.get("degree", "")) or None,
                        "institution": str(education.get("org", "")) or None,
                    },
                    advisories=_prose_advisories(str(education["description"])),
                )
            )
    return tuple(blocks)


def narrative_blocks(path: Path) -> dict[str, str]:
    """Return the stable text-only block map used by versioned review records."""
    return {block.id: block.text for block in narrative_block_inventory(path)}
