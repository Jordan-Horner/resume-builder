"""Parse and validate versioned direction profiles."""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml

from .rendering import object_value

SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
SOURCE_ID = re.compile(r"^DIRSRC-\d{3}$")
STATUSES = {"draft", "approved"}
MATURITIES = {"provisional", "researched", "outcome-validated"}
BASES = {"user-confirmed", "research-supported", "outcome-supported", "needs-review"}
SOURCE_KINDS = {"user", "research", "outcome"}
PAGE_FORMATS = {"letter", "a4"}
STYLE_TOKEN_EXCLUSIONS = {
    "across",
    "engineering",
    "management",
    "operations",
    "support",
    "technical",
    "through",
}
STYLE_MIN_TERM_OCCURRENCES = 12
STYLE_MIN_CLAIM_BLOCKS = 6
STYLE_MIN_WORD_SHARE = 0.025
COPIED_LABEL_MIN_COVERAGE = 0.8
ALLOWED_FIELDS = {
    "schema_version",
    "slug",
    "status",
    "maturity",
    "target_titles",
    "audiences",
    "positioning",
    "essential_terms",
    "priority_concepts",
    "de_emphasize",
    "avoid_terms",
    "defaults",
    "success_criteria",
    "sources",
}


def nonempty_string(value: object, owner: str) -> str:
    """Require one non-empty string."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{owner} must be a non-empty string")
    return value.strip()


def string_list(value: object, owner: str, *, required: bool = True) -> list[str]:
    """Require a list of unique non-empty strings."""
    if not isinstance(value, list) or (required and not value):
        raise ValueError(f"{owner} must be a{' non-empty' if required else ''} list of strings")
    if not all(isinstance(item, str) and item.strip() for item in value):
        raise ValueError(f"{owner} must contain only non-empty strings")
    normalized = [item.strip() for item in value]
    if len(set(normalized)) != len(normalized):
        raise ValueError(f"{owner} must not contain duplicates")
    return normalized


def iso_date(value: object, owner: str) -> str:
    """Accept YAML dates or strict ISO date strings."""
    if isinstance(value, date):
        return value.isoformat()
    text = nonempty_string(value, owner)
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError as exc:
        raise ValueError(f"{owner} must use YYYY-MM-DD") from exc


def parse_direction(path: Path) -> tuple[dict[str, Any], str]:
    """Load and validate a direction profile's versioned frontmatter."""
    try:
        markdown = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"cannot read direction profile: {exc}") from exc
    if not markdown.startswith("---\n"):
        raise ValueError("direction profile must begin with YAML frontmatter")
    try:
        raw, body = markdown[4:].split("\n---\n", 1)
    except ValueError as exc:
        raise ValueError("direction profile frontmatter is not closed with ---") from exc
    try:
        metadata = object_value(yaml.safe_load(raw), "direction frontmatter")
    except yaml.YAMLError as exc:
        raise ValueError(f"invalid direction frontmatter: {exc}") from exc
    unexpected = sorted(set(metadata) - ALLOWED_FIELDS)
    if unexpected:
        raise ValueError(f"direction profile contains unsupported fields: {unexpected}")
    if metadata.get("schema_version") != 1:
        raise ValueError("direction profile must declare schema_version 1")
    slug = nonempty_string(metadata.get("slug"), "slug")
    if not SLUG.fullmatch(slug):
        raise ValueError("slug must use lowercase kebab-case")
    if path.stem != slug:
        raise ValueError(f"direction filename must match slug: expected {slug}.md")
    status = nonempty_string(metadata.get("status"), "status")
    if status not in STATUSES:
        raise ValueError(f"status must be one of {sorted(STATUSES)}")
    maturity = nonempty_string(metadata.get("maturity"), "maturity")
    if maturity not in MATURITIES:
        raise ValueError(f"maturity must be one of {sorted(MATURITIES)}")
    string_list(metadata.get("target_titles"), "target_titles")
    string_list(metadata.get("audiences"), "audiences")
    nonempty_string(metadata.get("positioning"), "positioning")
    essential_terms = string_list(
        metadata.get("essential_terms", []), "essential_terms", required=False
    )
    if len(essential_terms) > 5:
        raise ValueError("essential_terms must contain no more than 5 terms")
    string_list(metadata.get("de_emphasize", []), "de_emphasize", required=False)
    string_list(metadata.get("avoid_terms", []), "avoid_terms", required=False)
    string_list(metadata.get("success_criteria"), "success_criteria")

    sources = metadata.get("sources")
    if not isinstance(sources, list) or not sources:
        raise ValueError("sources must be a non-empty list")
    source_ids: set[str] = set()
    source_kind_by_id: dict[str, str] = {}
    source_kinds: set[str] = set()
    for index, raw_source in enumerate(sources):
        source = object_value(raw_source, f"sources[{index}]")
        allowed = {"id", "kind", "reference", "as_of", "url"}
        if unexpected_source := sorted(set(source) - allowed):
            raise ValueError(f"sources[{index}] contains unsupported fields: {unexpected_source}")
        source_id = nonempty_string(source.get("id"), f"sources[{index}].id")
        if not SOURCE_ID.fullmatch(source_id):
            raise ValueError(f"sources[{index}].id must use DIRSRC-NNN")
        if source_id in source_ids:
            raise ValueError(f"duplicate direction source ID: {source_id}")
        source_ids.add(source_id)
        kind = nonempty_string(source.get("kind"), f"sources[{index}].kind")
        if kind not in SOURCE_KINDS:
            raise ValueError(f"sources[{index}].kind must be one of {sorted(SOURCE_KINDS)}")
        source_kinds.add(kind)
        source_kind_by_id[source_id] = kind
        nonempty_string(source.get("reference"), f"sources[{index}].reference")
        iso_date(source.get("as_of"), f"sources[{index}].as_of")
        if "url" in source:
            url = nonempty_string(source.get("url"), f"sources[{index}].url")
            parsed = urlparse(url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ValueError(f"sources[{index}].url must be an http or https URL")

    if maturity == "researched" and "research" not in source_kinds:
        raise ValueError("researched directions require at least one research source")
    if maturity == "outcome-validated" and "outcome" not in source_kinds:
        raise ValueError("outcome-validated directions require at least one outcome source")

    concepts = metadata.get("priority_concepts")
    if not isinstance(concepts, list) or not concepts:
        raise ValueError("priority_concepts must be a non-empty list")
    concept_ids: set[str] = set()
    concept_bases: set[str] = set()
    for index, raw_concept in enumerate(concepts):
        concept = object_value(raw_concept, f"priority_concepts[{index}]")
        allowed = {"id", "label", "weight", "terms", "evidence_themes", "basis", "source_ids"}
        if unexpected_concept := sorted(set(concept) - allowed):
            raise ValueError(
                f"priority_concepts[{index}] contains unsupported fields: {unexpected_concept}"
            )
        concept_id = nonempty_string(concept.get("id"), f"priority_concepts[{index}].id")
        if not SLUG.fullmatch(concept_id):
            raise ValueError(f"priority_concepts[{index}].id must use lowercase kebab-case")
        if concept_id in concept_ids:
            raise ValueError(f"duplicate priority concept ID: {concept_id}")
        concept_ids.add(concept_id)
        nonempty_string(concept.get("label"), f"priority_concepts[{index}].label")
        weight = concept.get("weight")
        if not isinstance(weight, int) or isinstance(weight, bool) or not 1 <= weight <= 5:
            raise ValueError(f"priority_concepts[{index}].weight must be an integer from 1 to 5")
        string_list(concept.get("terms"), f"priority_concepts[{index}].terms")
        string_list(concept.get("evidence_themes"), f"priority_concepts[{index}].evidence_themes")
        basis = nonempty_string(concept.get("basis"), f"priority_concepts[{index}].basis")
        if basis not in BASES:
            raise ValueError(f"priority_concepts[{index}].basis must be one of {sorted(BASES)}")
        concept_bases.add(basis)
        linked_sources = string_list(
            concept.get("source_ids", []),
            f"priority_concepts[{index}].source_ids",
            required=basis != "needs-review",
        )
        unknown_sources = sorted(set(linked_sources) - source_ids)
        if unknown_sources:
            raise ValueError(
                f"priority_concepts[{index}] cites unknown direction sources: {unknown_sources}"
            )
        expected_kind = {
            "user-confirmed": "user",
            "research-supported": "research",
            "outcome-supported": "outcome",
        }.get(basis)
        if expected_kind and not any(
            source_kind_by_id[source_id] == expected_kind for source_id in linked_sources
        ):
            raise ValueError(
                f"priority_concepts[{index}] basis {basis} requires a {expected_kind} source"
            )
        if status == "approved" and basis == "needs-review":
            raise ValueError("approved directions cannot contain needs-review concepts")
    if maturity == "researched" and "research-supported" not in concept_bases:
        raise ValueError("researched directions require at least one research-supported concept")
    if maturity == "outcome-validated" and "outcome-supported" not in concept_bases:
        raise ValueError(
            "outcome-validated directions require at least one outcome-supported concept"
        )

    defaults = object_value(metadata.get("defaults"), "defaults")
    if unexpected_defaults := sorted(
        set(defaults) - {"max_pages", "page_format", "minimum_coverage"}
    ):
        raise ValueError(f"defaults contains unsupported fields: {unexpected_defaults}")
    max_pages = defaults.get("max_pages")
    if not isinstance(max_pages, int) or isinstance(max_pages, bool) or max_pages < 1:
        raise ValueError("defaults.max_pages must be a positive integer")
    if defaults.get("page_format") not in PAGE_FORMATS:
        raise ValueError(f"defaults.page_format must be one of {sorted(PAGE_FORMATS)}")
    minimum = defaults.get("minimum_coverage")
    if not isinstance(minimum, int) or isinstance(minimum, bool) or not 0 <= minimum <= 100:
        raise ValueError("defaults.minimum_coverage must be an integer from 0 to 100")
    if not body.strip().startswith("# "):
        raise ValueError("direction profile body must begin with a level-one heading")
    return metadata, body.strip()
