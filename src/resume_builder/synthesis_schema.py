"""Dependency-neutral primitives for parsing versioned synthesis plans."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .layout import VaultLayout
from .synthesis_models import STORY_ID
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
