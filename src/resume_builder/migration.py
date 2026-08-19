#!/usr/bin/env python3
"""Safely migrate aggregate Resume Builder vault files to the current schema."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

from .atomic import atomic_write_json, atomic_write_text
from .layout import DEFAULT_CONFIG
from .validation import (
    ALLOWED_STATUSES,
    ALLOWED_TYPES,
    FACT_ID,
    SOURCE_ID,
    validate_vault,
)

FACT_HEADING = re.compile(
    r"^###\s+([A-Z][A-Z0-9]{1,9}-\d{3})\s+—\s+(.+)$",
    re.MULTILINE,
)
FIELD = re.compile(
    r"^\*\*(Type|Status|Sources|Themes):\*\*\s*(.*?)\s*$",
    re.MULTILINE,
)
SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
CATEGORY_FILES = {
    "profile.md": "profile",
    "skills.md": "skills",
    "education.md": "education",
    "certifications.md": "certifications",
    "projects.md": "projects",
}


def quote(value: str) -> str:
    """Render one JSON-compatible quoted frontmatter scalar."""
    return json.dumps(value, ensure_ascii=False)


def sha256_file(path: Path) -> str:
    """Hash a legacy file for the recovery manifest."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def split_frontmatter(text: str) -> tuple[dict[str, object], str]:
    """Parse legacy frontmatter and return it with the remaining content."""
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---\n", 4)
    if end < 0:
        raise ValueError("unterminated frontmatter")
    metadata: dict[str, object] = {}
    current_list: str | None = None
    for line in text[4:end].splitlines():
        if line.startswith("  - ") and current_list:
            values = metadata.get(current_list)
            if not isinstance(values, list):
                raise ValueError(f"invalid list field: {current_list}")
            values.append(line[4:].strip())
            continue
        match = re.fullmatch(r"([a-z_]+):\s*(.*)", line)
        if not match:
            raise ValueError(f"invalid frontmatter line: {line}")
        key, raw = match.groups()
        if raw:
            metadata[key] = raw.strip().strip('"')
            current_list = None
        else:
            metadata[key] = []
            current_list = key
    return metadata, text[end + 5 :]


def meaningful_unparsed(content: str) -> str:
    """Return unmatched prose while ignoring headings and structural whitespace."""
    meaningful = []
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped == "---":
            continue
        meaningful.append(line)
    return "\n".join(meaningful).strip()


def parse_facts_with_unmatched(path: Path) -> tuple[list[dict[str, object]], str]:
    """Parse legacy facts and report any substantive prefix the parser skipped."""
    text = path.read_text(encoding="utf-8")
    _, content = split_frontmatter(text)
    matches = list(FACT_HEADING.finditer(content))
    unmatched = meaningful_unparsed(content[: matches[0].start()] if matches else content)
    facts: list[dict[str, object]] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(content)
        block = content[match.end() : end].strip()
        fields = {key.lower(): value for key, value in FIELD.findall(block)}
        missing = {"type", "status", "sources", "themes"} - fields.keys()
        if missing:
            raise ValueError(f"{path}: {match.group(1)} missing {sorted(missing)}")
        body = FIELD.sub("", block)
        body = re.sub(r"\n{3,}", "\n\n", body).strip()
        facts.append(
            {
                "id": match.group(1),
                "title": match.group(2).strip(),
                "type": fields["type"],
                "status": fields["status"],
                "sources": [item.strip() for item in fields["sources"].split(",") if item.strip()],
                "themes": [item.strip() for item in fields["themes"].split(",") if item.strip()],
                "body": body,
            }
        )
    return facts, unmatched


def parse_facts(path: Path) -> list[dict[str, object]]:
    """Compatibility API returning facts while rejecting unmatched legacy prose."""
    facts, unmatched = parse_facts_with_unmatched(path)
    if unmatched:
        raise ValueError(f"{path}: unmatched legacy content: {unmatched[:120]!r}")
    return facts


def render_fact(
    fact: dict[str, object],
    category: str,
    organization: str | None,
) -> str:
    """Render one current-schema atomic fact."""
    lines = [
        "---",
        "schema_version: 2",
        f"id: {fact['id']}",
        f"title: {quote(str(fact['title']))}",
        f"type: {fact['type']}",
        f"status: {fact['status']}",
        f"category: {category}",
    ]
    if organization:
        lines.append(f"organization: {organization}")
        if fact.get("type") != "role":
            lines.append("scope: organization")
    lines.append("sources:")
    lines.extend(f"  - {source}" for source in cast(list[str], fact["sources"]))
    lines.append("themes:")
    lines.extend(f"  - {theme}" for theme in cast(list[str], fact["themes"]))
    lines.extend(["---", "", f"# {fact['title']}", "", str(fact["body"]).strip(), ""])
    return "\n".join(lines)


def render_employment(metadata: dict[str, object], fact_ids: list[str]) -> str:
    """Render one current-schema employment index."""
    organization = str(metadata["organization"])
    lines = [
        "---",
        "schema_version: 2",
        f"organization: {quote(organization)}",
        f"slug: {metadata['slug']}",
        f"status: {metadata['status']}",
        "sources:",
    ]
    lines.extend(f"  - {source}" for source in cast(list[str], metadata.get("sources", [])))
    lines.append("fact_ids:")
    lines.extend(f"  - {fact_id}" for fact_id in fact_ids)
    lines.extend(["---", "", f"# {organization}", ""])
    return "\n".join(lines)


@dataclass
class MigrationPlan:
    """A loss-audited aggregate-to-atomic migration proposal."""

    root: Path
    facts: dict[str, tuple[dict[str, object], str, str | None]] = field(default_factory=dict)
    employment: list[tuple[dict[str, object], list[str]]] = field(default_factory=list)
    inputs: list[Path] = field(default_factory=list)
    unmatched: dict[str, str] = field(default_factory=dict)

    def summary(self, *, applied: bool) -> dict[str, object]:
        """Return a reviewable migration summary."""
        return {
            "applied": applied,
            "schema_from": 0,
            "schema_to": 2,
            "facts": len(self.facts),
            "employment_records": len(self.employment),
            "fact_ids": sorted(self.facts),
            "inputs": [path.relative_to(self.root).as_posix() for path in self.inputs],
            "unmatched_content": self.unmatched,
            "backup": "migrations/v0-original",
        }


def validate_legacy_fact(fact: dict[str, object], path: Path) -> None:
    """Reject legacy values that cannot produce a valid current-schema fact."""
    fact_id = fact.get("id")
    if not isinstance(fact_id, str) or not FACT_ID.fullmatch(fact_id):
        raise ValueError(f"{path}: invalid fact ID {fact_id!r}")
    if fact.get("type") not in ALLOWED_TYPES:
        raise ValueError(f"{path}: {fact_id} has invalid type {fact.get('type')!r}")
    if fact.get("status") not in ALLOWED_STATUSES:
        raise ValueError(f"{path}: {fact_id} has invalid status {fact.get('status')!r}")
    sources = fact.get("sources")
    if not isinstance(sources, list) or not sources:
        raise ValueError(f"{path}: {fact_id} has no sources")
    if not all(isinstance(source, str) and SOURCE_ID.fullmatch(source) for source in sources):
        raise ValueError(f"{path}: {fact_id} has invalid source IDs")
    if not fact.get("themes") or not fact.get("body"):
        raise ValueError(f"{path}: {fact_id} has empty themes or body")


def build_migration_plan(root: Path) -> MigrationPlan:
    """Parse every legacy file and prove that no substantive text is skipped."""
    resolved = root.expanduser().resolve()
    if (resolved / "vault.json").exists():
        raise ValueError("vault.json already exists; refusing to migrate initialized schema")
    if (resolved / "facts").exists() or (resolved / "employment").exists():
        raise ValueError("canonical output directories already exist; refusing partial migration")

    plan = MigrationPlan(root=resolved)
    inputs: list[tuple[Path, str, str | None, dict[str, object] | None]] = []
    for filename, category in CATEGORY_FILES.items():
        path = resolved / filename
        if not path.is_file():
            raise ValueError(f"missing legacy file: {path}")
        inputs.append((path, category, None, None))

    role_root = resolved / "roles"
    role_files = sorted(role_root.glob("*.md"))
    if not role_files:
        raise ValueError("no legacy role files found")
    for path in role_files:
        role_metadata, _ = split_frontmatter(path.read_text(encoding="utf-8"))
        required = {"organization", "slug", "status", "sources"}
        if not required.issubset(role_metadata):
            raise ValueError(f"invalid role frontmatter: {path}")
        slug = role_metadata.get("slug")
        if not isinstance(slug, str) or not SLUG.fullmatch(slug):
            raise ValueError(f"invalid employment slug in {path}: {slug!r}")
        if role_metadata.get("status") not in ALLOWED_STATUSES:
            raise ValueError(f"invalid employment status in {path}")
        sources = role_metadata.get("sources")
        if not isinstance(sources, list) or not all(
            isinstance(source, str) and SOURCE_ID.fullmatch(source) for source in sources
        ):
            raise ValueError(f"invalid employment sources in {path}")
        inputs.append((path, "employment", slug, role_metadata))

    for path, category, organization, input_metadata in inputs:
        plan.inputs.append(path)
        facts, unmatched = parse_facts_with_unmatched(path)
        if unmatched:
            plan.unmatched[path.relative_to(resolved).as_posix()] = unmatched[:500]
        ids: list[str] = []
        for fact in facts:
            validate_legacy_fact(fact, path)
            fact_id = str(fact["id"])
            if fact_id in plan.facts:
                raise ValueError(f"duplicate fact ID: {fact_id}")
            plan.facts[fact_id] = (fact, category, organization)
            ids.append(fact_id)
        if input_metadata is not None:
            plan.employment.append((input_metadata, ids))
    return plan


def copy_recovery_backup(plan: MigrationPlan, backup_root: Path) -> None:
    """Copy every legacy input and record checksums before canonical writes."""
    if backup_root.exists():
        raise ValueError(f"migration backup already exists: {backup_root}")
    backup_root.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="v0-backup-", dir=backup_root.parent) as raw:
        staged_backup = Path(raw) / backup_root.name
        records: list[dict[str, str]] = []
        for source in plan.inputs:
            relative = source.relative_to(plan.root)
            destination = staged_backup / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            records.append({"path": relative.as_posix(), "sha256": sha256_file(source)})
        atomic_write_json(staged_backup / "manifest.json", {"version": 1, "files": records})
        os.replace(staged_backup, backup_root)


def render_staged_vault(plan: MigrationPlan, staged: Path) -> tuple[Path, Path]:
    """Render the complete target vault and prove it passes strict validation."""
    sources = plan.root / "sources"
    hydration_report = plan.root / "hydration-report.md"
    if sources.is_dir():
        shutil.copytree(sources, staged / "sources")
    if hydration_report.is_file():
        shutil.copy2(hydration_report, staged / hydration_report.name)

    facts_root = staged / "facts"
    employment_root = staged / "employment"
    for fact_id, (fact, category, organization) in plan.facts.items():
        category_path = facts_root / category
        if organization:
            category_path /= organization
        category_path.mkdir(parents=True, exist_ok=True)
        atomic_write_text(
            category_path / f"{fact_id}.md",
            render_fact(fact, category, organization),
        )
    employment_root.mkdir(parents=True, exist_ok=True)
    for metadata, fact_ids in plan.employment:
        slug = str(metadata["slug"])
        atomic_write_text(
            employment_root / f"{slug}.md",
            render_employment(metadata, fact_ids),
        )
    atomic_write_json(staged / "vault.json", DEFAULT_CONFIG)
    validation = validate_vault(staged, strict=True)
    if not validation["valid"]:
        raise ValueError(f"staged migration is invalid: {validation['errors']}")
    return facts_root, employment_root


def apply_migration_plan(plan: MigrationPlan) -> None:
    """Apply a complete plan only after a recovery copy and staged rendering."""
    if plan.unmatched:
        raise ValueError("unmatched legacy content must be resolved before --apply")
    with tempfile.TemporaryDirectory(prefix="vault-v1-", dir=plan.root.parent) as raw:
        staged = Path(raw)
        facts_root, employment_root = render_staged_vault(plan, staged)
        backup_root = plan.root / "migrations" / "v0-original"
        copy_recovery_backup(plan, backup_root)
        os.replace(facts_root, plan.root / "facts")
        os.replace(employment_root, plan.root / "employment")

    atomic_write_json(plan.root / "vault.json", DEFAULT_CONFIG)
    validation = validate_vault(plan.root)
    if not validation["valid"]:
        raise RuntimeError(f"installed migration is invalid: {validation['errors']}")
    for path in plan.inputs:
        path.unlink()
    (plan.root / "roles").rmdir()
    final_validation = validate_vault(plan.root, strict=True)
    if not final_validation["valid"]:
        raise RuntimeError(f"final migration is invalid: {final_validation['errors']}")


def main(argv: Sequence[str] | None = None) -> int:
    """Preview migration by default and require ``--apply`` for mutation."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vault-root", type=Path, default=Path("vault"))
    parser.add_argument("--apply", action="store_true", help="Apply the migration")
    args = parser.parse_args(argv)
    try:
        plan = build_migration_plan(args.vault_root)
        if args.apply:
            apply_migration_plan(plan)
    except (OSError, RuntimeError, ValueError) as exc:
        print(json.dumps({"error": str(exc)}, indent=2), file=sys.stderr)
        return 2
    print(json.dumps(plan.summary(applied=args.apply), indent=2))
    return 0 if not plan.unmatched else 1


if __name__ == "__main__":
    raise SystemExit(main())
