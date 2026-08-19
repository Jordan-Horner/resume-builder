#!/usr/bin/env python3
"""Validate a Resume Builder schema v2 vault and its provenance."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from .layout import LayoutError, VaultLayout

SOURCE_ID = re.compile(r"^SRC-[0-9a-f]{12}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
FACT_ID = re.compile(r"^[A-Z][A-Z0-9]{1,9}-\d{3}$")
ALLOWED_FORMATS = {"md", "txt", "html", "htm", "tex", "pdf", "docx"}
ALLOWED_TYPES = {
    "role",
    "responsibility",
    "accomplishment",
    "project",
    "incident",
    "leadership",
    "feedback",
    "story",
}
ALLOWED_STATUSES = {"confirmed", "approximate", "needs-review"}
ALLOWED_CATEGORIES = {
    "profile",
    "skills",
    "education",
    "certifications",
    "projects",
    "employment",
}
LIST_FIELDS = {"sources", "themes", "fact_ids", "role_ids"}


def sha256_bytes(data: bytes) -> str:
    """Return a lowercase SHA-256 digest."""
    return hashlib.sha256(data).hexdigest()


def scalar(value: str) -> object:
    """Parse the deliberately small frontmatter scalar subset used by the vault."""
    value = value.strip()
    if value.isdigit():
        return int(value)
    if value.startswith('"'):
        return json.loads(value)
    return value


def parse_frontmatter(path: Path) -> tuple[dict[str, object], str]:
    """Parse schema frontmatter and return metadata plus the Markdown body."""
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise ValueError("missing frontmatter")
    end = text.find("\n---\n", 4)
    if end < 0:
        raise ValueError("unterminated frontmatter")
    data: dict[str, object] = {}
    current_list: str | None = None
    for line in text[4:end].splitlines():
        if line.startswith("  - "):
            if not current_list or not isinstance(data.get(current_list), list):
                raise ValueError(f"list item without field: {line}")
            values = data[current_list]
            assert isinstance(values, list)
            values.append(scalar(line[4:]))
            continue
        match = re.fullmatch(r"([a-z_]+):\s*(.*)", line)
        if not match:
            raise ValueError(f"invalid frontmatter line: {line}")
        key, raw = match.groups()
        if key in data:
            raise ValueError(f"duplicate frontmatter field: {key}")
        if key in LIST_FIELDS:
            if raw:
                raise ValueError(f"{key} must use list syntax")
            data[key] = []
            current_list = key
        else:
            data[key] = scalar(raw)
            current_list = None
    return data, text[end + 5 :].strip()


def read_json(path: Path, errors: list[str]) -> object | None:
    """Read JSON while converting all data errors into validator findings."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        errors.append(f"invalid JSON {path}: {exc}")
        return None


def string_list(
    value: object,
    field: str,
    owner: str,
    errors: list[str],
) -> list[str]:
    """Validate a list of non-empty strings without raising on malformed data."""
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        errors.append(f"{owner}: {field} must be a list of non-empty strings")
        return []
    return value


def empty_result(errors: list[str]) -> dict[str, object]:
    """Return a stable result shape when layout loading fails early."""
    return {
        "valid": False,
        "schema_version": None,
        "registered_sources": 0,
        "empty_sources": 0,
        "employment_files": 0,
        "facts": 0,
        "statuses": {status: 0 for status in sorted(ALLOWED_STATUSES)},
        "types": {fact_type: 0 for fact_type in sorted(ALLOWED_TYPES)},
        "categories": {category: 0 for category in sorted(ALLOWED_CATEGORIES)},
        "warnings": [],
        "errors": errors,
    }


def validate_sources(
    layout: VaultLayout,
    errors: list[str],
    warnings: list[str],
) -> tuple[set[str], int]:
    """Validate the source manifest, snapshots, hashes, and path containment."""
    manifest = read_json(layout.manifest, errors)
    if not isinstance(manifest, dict):
        if manifest is not None:
            errors.append("source manifest must contain a JSON object")
        return set(), 0
    if manifest.get("version") != 1:
        errors.append("source manifest must declare version 1")
    entries = manifest.get("sources")
    if not isinstance(entries, list):
        errors.append("source manifest sources must be a list")
        return set(), 0

    registered: set[str] = set()
    referenced_snapshots: set[Path] = set()
    empty_sources = 0
    for index, entry in enumerate(entries):
        owner = f"manifest source {index}"
        if not isinstance(entry, dict):
            errors.append(f"{owner} must be an object")
            continue
        source_id = entry.get("id")
        if not isinstance(source_id, str) or not SOURCE_ID.fullmatch(source_id):
            errors.append(f"{owner}: invalid source ID {source_id!r}")
            continue
        if source_id in registered:
            errors.append(f"duplicate source ID: {source_id}")
            continue
        registered.add(source_id)

        digest = entry.get("sha256")
        if not isinstance(digest, str) or not SHA256.fullmatch(digest):
            errors.append(f"{source_id}: sha256 must contain 64 lowercase hex characters")
        elif source_id != f"SRC-{digest[:12]}":
            errors.append(f"source ID does not match SHA-256: {source_id}")
        source_format = entry.get("format")
        if source_format not in ALLOWED_FORMATS:
            errors.append(f"{source_id}: invalid source format {source_format!r}")
        string_list(entry.get("filenames"), "filenames", source_id, errors)

        extracted = entry.get("extracted_characters")
        if not isinstance(extracted, int) or isinstance(extracted, bool) or extracted < 0:
            errors.append(f"{source_id}: extracted_characters must be a non-negative integer")
        extraction_status = entry.get("extraction_status")
        if extraction_status not in {"ok", "empty"}:
            errors.append(f"{source_id}: invalid extraction_status {extraction_status!r}")
        elif extraction_status == "empty":
            empty_sources += 1
            warnings.append(f"source has no extractable text: {source_id}")
            if extracted != 0:
                errors.append(f"{source_id}: empty extraction must have zero characters")
        elif extracted == 0:
            errors.append(f"{source_id}: ok extraction must contain text")

        imported_at = entry.get("imported_at")
        if not isinstance(imported_at, str):
            errors.append(f"{source_id}: imported_at must be an ISO-8601 string")
        else:
            try:
                datetime.fromisoformat(imported_at)
            except ValueError:
                errors.append(f"{source_id}: invalid imported_at {imported_at!r}")

        try:
            snapshot = layout.snapshot_path(entry.get("snapshot"))
        except LayoutError as exc:
            errors.append(f"{source_id}: {exc}")
            continue
        if snapshot in referenced_snapshots:
            errors.append(f"snapshot referenced more than once: {layout.relative(snapshot)}")
        referenced_snapshots.add(snapshot)
        if not snapshot.is_file():
            errors.append(f"missing snapshot for {source_id}")
            continue
        snapshot_hash = entry.get("snapshot_sha256")
        if not isinstance(snapshot_hash, str) or not SHA256.fullmatch(snapshot_hash):
            errors.append(f"{source_id}: invalid snapshot_sha256")
            continue
        try:
            actual_hash = sha256_bytes(snapshot.read_bytes())
        except OSError as exc:
            errors.append(f"cannot read snapshot for {source_id}: {exc}")
        else:
            if actual_hash != snapshot_hash:
                errors.append(f"snapshot hash mismatch: {source_id}")

    if layout.normalized_sources.exists():
        for snapshot in layout.normalized_sources.glob("*.md"):
            if snapshot.resolve() not in referenced_snapshots:
                warnings.append(f"orphan normalized snapshot: {layout.relative(snapshot)}")
    return registered, empty_sources


def validate_vault(root: Path, strict: bool = False) -> dict[str, object]:
    """Return a complete validation result without throwing on malformed vault data."""
    errors: list[str] = []
    warnings: list[str] = []
    try:
        layout = VaultLayout.load(root)
    except LayoutError as exc:
        errors.append(str(exc))
        return empty_result(errors)

    registered, empty_sources = validate_sources(layout, errors, warnings)
    fact_files = sorted(layout.facts.rglob("*.md")) if layout.facts.exists() else []
    facts: dict[str, dict[str, object]] = {}
    statuses = {status: 0 for status in sorted(ALLOWED_STATUSES)}
    types = {fact_type: 0 for fact_type in sorted(ALLOWED_TYPES)}
    categories = {category: 0 for category in sorted(ALLOWED_CATEGORIES)}

    for path in fact_files:
        owner = layout.relative(path)
        try:
            data, body = parse_frontmatter(path)
        except (OSError, ValueError) as exc:
            errors.append(f"{owner}: {exc}")
            continue
        required = {
            "schema_version",
            "id",
            "title",
            "type",
            "status",
            "category",
            "sources",
            "themes",
        }
        missing = required - data.keys()
        if missing:
            errors.append(f"{owner} missing fields: {sorted(missing)}")
            continue
        fact_id = data.get("id")
        if not isinstance(fact_id, str) or not FACT_ID.fullmatch(fact_id):
            errors.append(f"{owner}: invalid fact ID {fact_id!r}")
            continue
        if path.stem != fact_id:
            errors.append(f"filename does not match fact ID: {owner}")
        if fact_id in facts:
            errors.append(f"duplicate fact ID: {fact_id}")
        facts[fact_id] = data
        if data.get("schema_version") != 2:
            errors.append(f"{fact_id}: schema_version must be 2")
        title = data.get("title")
        if not isinstance(title, str) or not title:
            errors.append(f"{fact_id}: title must be a non-empty string")
            title = ""
        fact_type = data.get("type")
        status = data.get("status")
        category = data.get("category")
        if fact_type not in ALLOWED_TYPES:
            errors.append(f"{fact_id}: invalid type {fact_type!r}")
        else:
            types[str(fact_type)] += 1
        if status not in ALLOWED_STATUSES:
            errors.append(f"{fact_id}: invalid status {status!r}")
        else:
            statuses[str(status)] += 1
        if category not in ALLOWED_CATEGORIES:
            errors.append(f"{fact_id}: invalid category {category!r}")
            category = ""
        else:
            categories[str(category)] += 1

        relative_parts = path.relative_to(layout.facts).parts
        expected_depth = 3 if category == "employment" else 2
        if (
            not relative_parts
            or relative_parts[0] != category
            or len(relative_parts) != expected_depth
        ):
            errors.append(f"{fact_id}: category does not match canonical directory")
        if not body:
            errors.append(f"{fact_id}: empty fact body")
        elif title and not body.startswith(f"# {title}\n"):
            errors.append(f"{fact_id}: body heading does not match title")
        sources = string_list(data.get("sources"), "sources", fact_id, errors)
        themes = string_list(data.get("themes"), "themes", fact_id, errors)
        if not sources:
            errors.append(f"{fact_id}: no source references")
        if not themes:
            errors.append(f"{fact_id}: no themes")
        for source_id in sources:
            if source_id not in registered:
                errors.append(f"{fact_id}: unknown source {source_id}")
        organization = data.get("organization")
        if category == "employment":
            if not isinstance(organization, str) or not organization:
                errors.append(f"{fact_id}: employment fact missing organization")
            elif len(relative_parts) != 3 or relative_parts[1] != organization:
                errors.append(f"{fact_id}: organization does not match directory")
            scope = data.get("scope")
            role_ids = data.get("role_ids")
            if fact_type == "role":
                if scope is not None or role_ids is not None:
                    errors.append(f"{fact_id}: role facts must not declare scope or role_ids")
            elif scope not in {"role", "organization"}:
                errors.append(f"{fact_id}: employment fact requires role or organization scope")
            elif scope == "role":
                scoped_roles = string_list(role_ids, "role_ids", fact_id, errors)
                if not scoped_roles:
                    errors.append(f"{fact_id}: role-scoped fact requires role_ids")
            elif role_ids is not None:
                errors.append(f"{fact_id}: organization-scoped fact must not declare role_ids")
        elif organization is not None:
            errors.append(f"{fact_id}: non-employment fact must not have organization")
        elif data.get("scope") is not None or data.get("role_ids") is not None:
            errors.append(f"{fact_id}: non-employment fact must not declare role scope")

    for fact_id, data in facts.items():
        if data.get("category") != "employment" or data.get("scope") != "role":
            continue
        role_ids = data.get("role_ids")
        if not isinstance(role_ids, list):
            continue
        for role_id in role_ids:
            role = facts.get(str(role_id))
            if role is None:
                errors.append(f"{fact_id}: unknown role ID {role_id}")
            elif role.get("type") != "role":
                errors.append(f"{fact_id}: scoped ID is not a role fact: {role_id}")
            elif role.get("organization") != data.get("organization"):
                errors.append(f"{fact_id}: role {role_id} belongs to another organization")

    employment_files = sorted(layout.employment.glob("*.md")) if layout.employment.exists() else []
    organizations: set[str] = set()
    indexed_facts: dict[str, str] = {}
    for path in employment_files:
        owner = layout.relative(path)
        try:
            data, body = parse_frontmatter(path)
        except (OSError, ValueError) as exc:
            errors.append(f"{owner}: {exc}")
            continue
        required = {
            "schema_version",
            "organization",
            "slug",
            "status",
            "sources",
            "fact_ids",
        }
        missing = required - data.keys()
        if missing:
            errors.append(f"{owner} missing fields: {sorted(missing)}")
            continue
        slug = data.get("slug")
        if not isinstance(slug, str) or not slug:
            errors.append(f"{owner}: slug must be a non-empty string")
            continue
        if path.stem != slug:
            errors.append(f"employment filename does not match slug: {path.name}")
        if slug in organizations:
            errors.append(f"duplicate employment slug: {slug}")
        organizations.add(slug)
        if data.get("schema_version") != 2:
            errors.append(f"{slug}: schema_version must be 2")
        organization = data.get("organization")
        if not isinstance(organization, str) or not organization:
            errors.append(f"{slug}: organization must be a non-empty string")
        status = data.get("status")
        if status not in ALLOWED_STATUSES:
            errors.append(f"{slug}: invalid status {status!r}")
        sources = string_list(data.get("sources"), "sources", slug, errors)
        fact_ids = string_list(data.get("fact_ids"), "fact_ids", slug, errors)
        if not sources:
            errors.append(f"{slug}: no source references")
        if not fact_ids:
            errors.append(f"{slug}: no indexed facts")
        for source_id in sources:
            if source_id not in registered:
                errors.append(f"{slug}: unknown source {source_id}")
        for fact_id in fact_ids:
            if fact_id not in facts:
                errors.append(f"{slug}: unknown fact {fact_id}")
                continue
            if fact_id in indexed_facts:
                errors.append(f"fact {fact_id} indexed by both {indexed_facts[fact_id]} and {slug}")
            indexed_facts[fact_id] = slug
            if facts[fact_id].get("organization") != slug:
                errors.append(f"{slug}: fact {fact_id} organization mismatch")
        if body and body != f"# {organization}":
            errors.append(f"{slug}: employment body must contain only its heading")

    for fact_id, data in facts.items():
        if data.get("category") == "employment" and fact_id not in indexed_facts:
            errors.append(f"employment fact not indexed: {fact_id}")

    legacy_names = [
        "profile.md",
        "skills.md",
        "education.md",
        "certifications.md",
        "projects.md",
        "roles",
    ]
    legacy = [layout.root / name for name in legacy_names if (layout.root / name).exists()]
    if strict:
        if not registered:
            errors.append("no registered sources")
        if not fact_files:
            errors.append("no atomic fact files found")
        if not employment_files:
            errors.append("no employment files found")
        if not layout.hydration_report.is_file():
            errors.append("missing hydration-report.md")
        if legacy:
            errors.append(f"legacy aggregate paths remain: {[path.name for path in legacy]}")

    return {
        "valid": not errors,
        "schema_version": layout.config.get("schema_version"),
        "registered_sources": len(registered),
        "empty_sources": empty_sources,
        "employment_files": len(employment_files),
        "facts": len(facts),
        "statuses": statuses,
        "types": types,
        "categories": categories,
        "warnings": warnings,
        "errors": errors,
    }


def format_summary(result: dict[str, object]) -> str:
    """Render a short report suitable for humans and CI logs."""
    warnings = result.get("warnings")
    errors = result.get("errors")
    warning_items = warnings if isinstance(warnings, list) else []
    error_items = errors if isinstance(errors, list) else []
    state = "VALID" if result.get("valid") else "INVALID"
    lines = [
        f"Vault: {state} (schema v{result.get('schema_version')})",
        f"Facts: {result.get('facts', 0)}",
        f"Employment records: {result.get('employment_files', 0)}",
        f"Registered sources: {result.get('registered_sources', 0)}",
        f"Warnings: {len(warning_items)}",
        f"Errors: {len(error_items)}",
    ]
    lines.extend(f"  warning: {warning}" for warning in warning_items)
    lines.extend(f"  error: {error}" for error in error_items)
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    """Run vault validation and print JSON or a concise summary."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vault-root", type=Path, default=Path("vault"))
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--summary", action="store_true", help="Print a concise report")
    args = parser.parse_args(argv)

    result = validate_vault(args.vault_root, strict=args.strict)
    print(format_summary(result) if args.summary else json.dumps(result, indent=2))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
