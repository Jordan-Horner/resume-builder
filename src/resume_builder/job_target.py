"""Parse and validate source-preserving job-posting targets."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml

from .directions import (
    SLUG,
    iso_date,
    nonempty_string,
    normalize_phrase,
    parse_direction,
    string_list,
)
from .rendering import contained_project_path, object_value

TARGET_FIELDS = {
    "schema_version",
    "slug",
    "company",
    "role",
    "captured_at",
    "source",
    "direction",
    "criteria",
    "search_groups",
}
SOURCE_FIELDS = {"kind", "reference", "url", "published_at", "body_sha256"}
CRITERION_FIELDS = {
    "id",
    "importance",
    "label",
    "description",
    "resume_evaluable",
    "source_section",
}
SEARCH_FIELDS = {"id", "criterion_id", "any_of"}
SOURCE_KINDS = {"url", "pasted", "file"}
IMPORTANCE = {"required", "preferred"}


def body_sha256(body: str) -> str:
    """Hash the normalized posting snapshot independently from its metadata."""
    return hashlib.sha256(body.strip().encode("utf-8")).hexdigest()


def parse_target(path: Path) -> tuple[dict[str, Any], str]:
    """Load and validate a versioned, source-preserving target posting."""
    try:
        markdown = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"cannot read target posting: {exc}") from exc
    if not markdown.startswith("---\n"):
        raise ValueError("target posting must begin with YAML frontmatter")
    try:
        raw, body = markdown[4:].split("\n---\n", 1)
    except ValueError as exc:
        raise ValueError("target posting frontmatter is not closed with ---") from exc
    try:
        metadata = object_value(yaml.safe_load(raw), "target frontmatter")
    except yaml.YAMLError as exc:
        raise ValueError(f"invalid target frontmatter: {exc}") from exc
    if unexpected := sorted(set(metadata) - TARGET_FIELDS):
        raise ValueError(f"target posting contains unsupported fields: {unexpected}")
    if metadata.get("schema_version") != 1:
        raise ValueError("target posting must declare schema_version 1")
    slug = nonempty_string(metadata.get("slug"), "slug")
    if not SLUG.fullmatch(slug):
        raise ValueError("slug must use lowercase kebab-case")
    if path.stem != slug:
        raise ValueError(f"target filename must match slug: expected {slug}.md")
    nonempty_string(metadata.get("company"), "company")
    nonempty_string(metadata.get("role"), "role")
    iso_date(metadata.get("captured_at"), "captured_at")
    direction = nonempty_string(metadata.get("direction"), "direction")
    if not direction.startswith("directions/") or not direction.endswith(".md"):
        raise ValueError("direction must reference a Markdown file under directions/")
    source = object_value(metadata.get("source"), "source")
    if unexpected_source := sorted(set(source) - SOURCE_FIELDS):
        raise ValueError(f"source contains unsupported fields: {unexpected_source}")
    source_kind = nonempty_string(source.get("kind"), "source.kind")
    if source_kind not in SOURCE_KINDS:
        raise ValueError(f"source.kind must be one of {sorted(SOURCE_KINDS)}")
    nonempty_string(source.get("reference"), "source.reference")
    if "published_at" in source:
        iso_date(source.get("published_at"), "source.published_at")
    if source_kind == "url":
        url = nonempty_string(source.get("url"), "source.url")
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("source.url must be an http or https URL")
    elif "url" in source:
        raise ValueError("source.url is allowed only when source.kind is url")
    if not body.strip().startswith("# Job Posting Snapshot"):
        raise ValueError("target body must begin with '# Job Posting Snapshot'")
    expected_digest = nonempty_string(source.get("body_sha256"), "source.body_sha256")
    if not re.fullmatch(r"[a-f0-9]{64}", expected_digest):
        raise ValueError("source.body_sha256 must be a lowercase SHA-256 digest")
    if expected_digest != body_sha256(body):
        raise ValueError("target posting body does not match source.body_sha256")
    raw_criteria = metadata.get("criteria")
    if not isinstance(raw_criteria, list) or not raw_criteria:
        raise ValueError("criteria must be a non-empty list")
    if len(raw_criteria) > 12:
        raise ValueError("criteria must contain no more than 12 focused criteria")
    criteria: dict[str, dict[str, Any]] = {}
    for index, raw_criterion in enumerate(raw_criteria):
        criterion = object_value(raw_criterion, f"criteria[{index}]")
        if unexpected := sorted(set(criterion) - CRITERION_FIELDS):
            raise ValueError(f"criteria[{index}] contains unsupported fields: {unexpected}")
        criterion_id = nonempty_string(criterion.get("id"), f"criteria[{index}].id")
        if not SLUG.fullmatch(criterion_id):
            raise ValueError(f"criteria[{index}].id must use lowercase kebab-case")
        if criterion_id in criteria:
            raise ValueError(f"duplicate criterion ID: {criterion_id}")
        importance = nonempty_string(criterion.get("importance"), f"criteria[{index}].importance")
        if importance not in IMPORTANCE:
            raise ValueError(f"criteria[{index}].importance must be one of {sorted(IMPORTANCE)}")
        nonempty_string(criterion.get("label"), f"criteria[{index}].label")
        nonempty_string(criterion.get("description"), f"criteria[{index}].description")
        nonempty_string(criterion.get("source_section"), f"criteria[{index}].source_section")
        if not isinstance(criterion.get("resume_evaluable"), bool):
            raise ValueError(f"criteria[{index}].resume_evaluable must be a boolean")
        criteria[criterion_id] = criterion
    if not any(item["importance"] == "required" for item in criteria.values()):
        raise ValueError("criteria must identify at least one required criterion")
    raw_groups = metadata.get("search_groups")
    if not isinstance(raw_groups, list) or not raw_groups:
        raise ValueError("search_groups must be a non-empty list")
    group_ids: set[str] = set()
    searchable_criteria: set[str] = set()
    for index, raw_group in enumerate(raw_groups):
        group = object_value(raw_group, f"search_groups[{index}]")
        if unexpected := sorted(set(group) - SEARCH_FIELDS):
            raise ValueError(f"search_groups[{index}] contains unsupported fields: {unexpected}")
        group_id = nonempty_string(group.get("id"), f"search_groups[{index}].id")
        if not SLUG.fullmatch(group_id):
            raise ValueError(f"search_groups[{index}].id must use lowercase kebab-case")
        if group_id in group_ids:
            raise ValueError(f"duplicate search group ID: {group_id}")
        group_ids.add(group_id)
        criterion_id = nonempty_string(
            group.get("criterion_id"), f"search_groups[{index}].criterion_id"
        )
        if criterion_id not in criteria:
            raise ValueError(f"search_groups[{index}] cites unknown criterion: {criterion_id}")
        if not criteria[criterion_id]["resume_evaluable"]:
            raise ValueError(
                f"search_groups[{index}] cites a criterion that is not resume-evaluable"
            )
        terms = string_list(group.get("any_of"), f"search_groups[{index}].any_of")
        normalized = [normalize_phrase(term) for term in terms]
        if any(not term for term in normalized):
            raise ValueError(f"search_groups[{index}].any_of contains an empty search phrase")
        if len(set(normalized)) != len(normalized):
            raise ValueError(
                f"search_groups[{index}].any_of contains phrases that normalize to duplicates"
            )
        searchable_criteria.add(criterion_id)
    missing = sorted(
        criterion_id
        for criterion_id, criterion in criteria.items()
        if criterion["resume_evaluable"] and criterion_id not in searchable_criteria
    )
    if missing:
        raise ValueError(f"resume-evaluable criteria require search groups: {missing}")
    return metadata, body.strip()


def project_target_path(path: Path, project_root: Path) -> Path:
    """Require a canonical target record under targets/."""
    resolved = contained_project_path(path, project_root, "targets", "target posting")
    if resolved.name == "README.md" or resolved.name.endswith(".template.md"):
        raise ValueError("target posting must not be README.md or a template")
    if resolved.suffix != ".md":
        raise ValueError("target posting must use a .md extension")
    return resolved


def target_paths(project_root: Path, requested: list[Path]) -> list[Path]:
    """Resolve requested target records or discover every canonical posting."""
    if requested:
        return [project_target_path(path, project_root) for path in requested]
    directory = (project_root / "targets").resolve()
    return [
        path
        for path in sorted(directory.glob("*.md"))
        if path.name != "README.md" and not path.name.endswith(".template.md")
    ]


def validate_target(path: Path, project_root: Path) -> tuple[dict[str, Any], Path]:
    """Validate one target and its referenced reusable direction."""
    target_path = project_target_path(path, project_root)
    target_data, _ = parse_target(target_path)
    direction_path = contained_project_path(
        Path(str(target_data["direction"])), project_root, "directions", "direction"
    )
    parse_direction(direction_path)
    return target_data, direction_path
