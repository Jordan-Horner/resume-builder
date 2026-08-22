"""Dependency-neutral primitives for parsing versioned synthesis plans."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .layout import VaultLayout
from .synthesis_models import STORY_ID, CoreJobCandidate
from .validation import parse_frontmatter


def object_value(value: object, owner: str) -> dict[str, Any]:
    """Return a dictionary or raise a useful plan error."""
    if not isinstance(value, dict):
        raise ValueError(f"{owner} must be an object")
    return value


def exact_fields(value: dict[str, Any], allowed: set[str], owner: str) -> None:
    """Reject omitted and unexpected fields in a versioned synthesis object."""
    missing = sorted(allowed - value.keys())
    unexpected = sorted(value.keys() - allowed)
    if missing:
        raise ValueError(f"{owner} missing fields: {missing}")
    if unexpected:
        raise ValueError(f"{owner} contains unsupported fields: {unexpected}")


def nonempty_string(value: object, owner: str) -> str:
    """Return a stripped non-empty string."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{owner} must be a non-empty string")
    return value.strip()


def optional_string(value: object, owner: str) -> str | None:
    """Return a stripped optional string."""
    if value is None:
        return None
    return nonempty_string(value, owner)


def string_list(value: object, owner: str, *, required: bool = True) -> list[str]:
    """Return a unique list of non-empty strings."""
    if not isinstance(value, list):
        raise ValueError(f"{owner} must be a list of non-empty strings")
    if required and not value:
        raise ValueError(f"{owner} must not be empty")
    if not all(isinstance(item, str) for item in value):
        raise ValueError(f"{owner} must be a list of non-empty strings")
    normalized = [item.strip() for item in value]
    if any(not item for item in normalized):
        raise ValueError(f"{owner} must be a list of non-empty strings")
    if len(set(normalized)) != len(normalized):
        raise ValueError(f"{owner} must not contain duplicates")
    return normalized


def string_subset(value: object, owner: str, candidates: list[str]) -> list[str]:
    """Return a required string list whose values all belong to candidates."""
    items = string_list(value, owner)
    unknown = sorted(set(items) - set(candidates))
    if unknown:
        raise ValueError(f"{owner} must reference required stories: {unknown}")
    return items


def role_story_classes(
    arc: dict[str, object], owner: str, required: list[str], version: int
) -> tuple[list[str], list[str]]:
    """Return required role-anchor and distinct selling-story assignments."""
    anchors = (
        string_subset(arc["role_anchor_story_ids"], f"{owner}.role_anchor_story_ids", required)
        if version >= 8
        else []
    )
    sellers = (
        string_subset(arc["role_selling_story_ids"], f"{owner}.role_selling_story_ids", required)
        if version >= 9
        else []
    )
    overlap = sorted(set(anchors) & set(sellers))
    if overlap:
        raise ValueError(
            f"{owner} assigns stories as both role anchors and selling stories: {overlap}"
        )
    return anchors, sellers


def role_arc_fields(version: int) -> set[str]:
    """Return the exact role-arc fields for one synthesis schema version."""
    fields = {"role_ids", "emphasis", "arc_focus", "selection_rationale", "omitted_signals"}
    if version >= 6:
        fields.update({"required_dimensions", "required_story_ids", "optional_story_ids"})
    else:
        fields.add("story_ids")
    if version >= 8:
        fields.add("role_anchor_story_ids")
    if version >= 9:
        fields.add("role_selling_story_ids")
    if version >= 10:
        fields.update({"core_job_candidates", "selected_core_job_id", "core_job_decision"})
    return fields


def confidence_score(value: object, owner: str) -> int:
    """Return an integer confidence estimate from zero through one hundred."""
    if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 100:
        raise ValueError(f"{owner} must be an integer from 0 through 100")
    return value


def core_job_assessment(
    arc: dict[str, object], owner: str, version: int
) -> tuple[list[CoreJobCandidate], str | None, str | None]:
    """Parse scored core-job candidates and enforce the close-score user gate."""
    if version < 10:
        return [], None, None
    raw_candidates = arc["core_job_candidates"]
    if not isinstance(raw_candidates, list) or not 2 <= len(raw_candidates) <= 3:
        raise ValueError(f"{owner}.core_job_candidates must contain two or three items")
    candidates: list[CoreJobCandidate] = []
    seen_ids: set[str] = set()
    seen_descriptions: set[str] = set()
    for index, raw_candidate in enumerate(raw_candidates):
        candidate_owner = f"{owner}.core_job_candidates[{index}]"
        candidate = object_value(raw_candidate, candidate_owner)
        exact_fields(candidate, {"id", "description", "confidence"}, candidate_owner)
        candidate_id = nonempty_string(candidate["id"], f"{candidate_owner}.id")
        if not STORY_ID.fullmatch(candidate_id):
            raise ValueError(f"{candidate_owner}.id must use a lowercase hyphenated identifier")
        if candidate_id in seen_ids:
            raise ValueError(f"duplicate core job candidate id in {owner}: {candidate_id}")
        description = nonempty_string(candidate["description"], f"{candidate_owner}.description")
        if description in seen_descriptions:
            raise ValueError(f"duplicate core job candidate description in {owner}: {description}")
        seen_ids.add(candidate_id)
        seen_descriptions.add(description)
        candidates.append(
            CoreJobCandidate(
                candidate_id=candidate_id,
                description=description,
                confidence=confidence_score(
                    candidate["confidence"], f"{candidate_owner}.confidence"
                ),
            )
        )
    selected_id = nonempty_string(arc["selected_core_job_id"], f"{owner}.selected_core_job_id")
    if selected_id not in seen_ids:
        raise ValueError(f"{owner}.selected_core_job_id must reference a core job candidate")
    decision = nonempty_string(arc["core_job_decision"], f"{owner}.core_job_decision")
    if decision not in {"model-selected", "user-confirmed"}:
        raise ValueError(f"{owner}.core_job_decision must be model-selected or user-confirmed")
    selected = next(item for item in candidates if item.candidate_id == selected_id)
    competitor = max(item.confidence for item in candidates if item.candidate_id != selected_id)
    margin = selected.confidence - competitor
    if decision == "model-selected" and margin <= 10:
        raise ValueError(
            f"{owner} core job candidates are close ({margin} point margin); "
            "ask the user and record core_job_decision as user-confirmed"
        )
    return candidates, selected_id, decision


def fact_metadata(vault_root: Path) -> dict[str, dict[str, object]]:
    """Load canonical fact metadata for synthesis validation."""
    layout = VaultLayout.load(vault_root)
    result: dict[str, dict[str, object]] = {}
    for path in sorted(layout.facts.rglob("*.md")):
        metadata, _ = parse_frontmatter(path)
        fact_id = metadata.get("id")
        if isinstance(fact_id, str):
            result[fact_id] = metadata
    return result


def direction_concept_ids(path: Path) -> set[str]:
    """Return stable concept IDs declared by a direction profile."""
    try:
        markdown = path.read_text(encoding="utf-8")
        if not markdown.startswith("---\n"):
            raise ValueError("direction must begin with YAML frontmatter")
        raw_frontmatter, _ = markdown[4:].split("\n---\n", 1)
        metadata = object_value(yaml.safe_load(raw_frontmatter), "synthesis direction")
    except (OSError, ValueError, yaml.YAMLError) as exc:
        raise ValueError(f"invalid synthesis direction {path}: {exc}") from exc
    raw_concepts = metadata.get("priority_concepts")
    if not isinstance(raw_concepts, list) or not raw_concepts:
        raise ValueError("synthesis direction must declare priority_concepts")
    concept_ids: set[str] = set()
    for index, raw_concept in enumerate(raw_concepts):
        owner = f"synthesis direction priority_concepts[{index}]"
        concept = object_value(raw_concept, owner)
        concept_id = nonempty_string(concept.get("id"), f"{owner}.id")
        if not STORY_ID.fullmatch(concept_id):
            raise ValueError(f"{owner}.id must be a lowercase hyphenated identifier")
        if concept_id in concept_ids:
            raise ValueError(f"duplicate synthesis direction concept ID: {concept_id}")
        concept_ids.add(concept_id)
    return concept_ids


def direction_page_budget(path: Path) -> int:
    """Return the validated default page budget declared by a direction."""
    try:
        markdown = path.read_text(encoding="utf-8")
        raw_frontmatter, _ = markdown[4:].split("\n---\n", 1)
        metadata = object_value(yaml.safe_load(raw_frontmatter), "synthesis direction")
        defaults = object_value(metadata.get("defaults"), "synthesis direction defaults")
        max_pages = defaults.get("max_pages")
    except (OSError, ValueError, yaml.YAMLError) as exc:
        raise ValueError(f"invalid synthesis direction page budget {path}: {exc}") from exc
    if not isinstance(max_pages, int) or isinstance(max_pages, bool) or max_pages < 1:
        raise ValueError("synthesis direction defaults.max_pages must be a positive integer")
    return max_pages
