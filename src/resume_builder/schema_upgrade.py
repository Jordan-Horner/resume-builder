"""Preview and apply a lossless schema-v1 to schema-v2 vault upgrade."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import tempfile
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from .atomic import atomic_write_bytes, atomic_write_json, atomic_write_text
from .layout import DEFAULT_CONFIG, contained_path
from .validation import parse_frontmatter, validate_vault


@dataclass(frozen=True)
class SchemaUpgradePlan:
    """Complete set of schema-v2 replacements for one schema-v1 vault."""

    root: Path
    writes: tuple[tuple[Path, str], ...]
    role_scoped: tuple[str, ...]
    organization_scoped: tuple[str, ...]
    override_path: Path | None

    def summary(self, *, applied: bool) -> dict[str, object]:
        """Return a stable preview of the upgrade."""
        return {
            "valid": True,
            "applied": applied,
            "schema_from": 1,
            "schema_to": 2,
            "writes": len(self.writes) + 1,
            "role_scoped": list(self.role_scoped),
            "organization_scoped": list(self.organization_scoped),
            "role_map": str(self.override_path) if self.override_path else None,
            "backup": "migrations/v1-original",
        }


def read_v1_config(root: Path) -> dict[str, object]:
    """Load a schema-v1 declaration without using the current-schema layout."""
    path = root / "vault.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise ValueError(f"invalid vault configuration: {exc}") from exc
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise ValueError("schema upgrade requires a schema-v1 vault")
    return value


def load_role_map(path: Path | None) -> dict[str, list[str]]:
    """Load optional reviewed role assignments for multi-role employers."""
    if path is None:
        return {}
    resolved = path.expanduser().resolve()
    try:
        value = json.loads(resolved.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise ValueError(f"invalid role map {resolved}: {exc}") from exc
    if not isinstance(value, dict) or value.get("version") != 1:
        raise ValueError("role map must be a version 1 object")
    assignments = value.get("assignments")
    if not isinstance(assignments, dict):
        raise ValueError("role map assignments must be an object")
    result: dict[str, list[str]] = {}
    for fact_id, role_ids in assignments.items():
        if not isinstance(fact_id, str) or not isinstance(role_ids, list) or not role_ids:
            raise ValueError("role map assignments require fact IDs and non-empty role lists")
        if not all(isinstance(role_id, str) and role_id for role_id in role_ids):
            raise ValueError(f"invalid role IDs for {fact_id}")
        if len(set(role_ids)) != len(role_ids):
            raise ValueError(f"duplicate role IDs for {fact_id}")
        result[fact_id] = role_ids
    return result


def insert_scope(text: str, scope: str, role_ids: list[str]) -> str:
    """Upgrade fact frontmatter while preserving its factual body."""
    upgraded = text.replace("schema_version: 1", "schema_version: 2", 1)
    lines = upgraded.splitlines()
    for index, line in enumerate(lines):
        if line.startswith("organization: "):
            additions = [f"scope: {scope}"]
            if scope == "role":
                additions.append("role_ids:")
                additions.extend(f"  - {role_id}" for role_id in role_ids)
            lines[index + 1 : index + 1] = additions
            return "\n".join(lines) + ("\n" if text.endswith("\n") else "")
    raise ValueError("employment fact is missing organization frontmatter")


def build_upgrade_plan(root: Path, role_map_path: Path | None = None) -> SchemaUpgradePlan:
    """Build and stage-validate a complete v1-to-v2 upgrade."""
    resolved = root.expanduser().resolve()
    config = read_v1_config(resolved)
    facts_root = contained_path(resolved, config.get("facts_path"), "facts_path")
    employment_root = contained_path(resolved, config.get("employment_path"), "employment_path")
    assignments = load_role_map(role_map_path)

    metadata: dict[str, dict[str, object]] = {}
    paths: dict[str, Path] = {}
    roles_by_org: dict[str, list[str]] = defaultdict(list)
    for path in sorted(facts_root.rglob("*.md")):
        fact, _ = parse_frontmatter(path)
        fact_id = fact.get("id")
        if not isinstance(fact_id, str):
            raise ValueError(f"fact has no ID: {path}")
        if fact.get("schema_version") != 1:
            raise ValueError(f"schema-v1 upgrade found non-v1 fact: {fact_id}")
        metadata[fact_id] = fact
        paths[fact_id] = path
        if fact.get("type") == "role" and isinstance(fact.get("organization"), str):
            roles_by_org[str(fact["organization"])].append(fact_id)

    unknown_assignments = sorted(set(assignments) - metadata.keys())
    if unknown_assignments:
        raise ValueError(f"role map cites unknown facts: {unknown_assignments}")
    writes: list[tuple[Path, str]] = []
    role_scoped: list[str] = []
    organization_scoped: list[str] = []
    for fact_id, fact in metadata.items():
        text = paths[fact_id].read_text(encoding="utf-8")
        if fact.get("category") != "employment" or fact.get("type") == "role":
            upgraded = text.replace("schema_version: 1", "schema_version: 2", 1)
        else:
            organization = fact.get("organization")
            known_roles = roles_by_org.get(str(organization), [])
            selected_roles = assignments.get(fact_id)
            if selected_roles is None and len(known_roles) == 1:
                selected_roles = known_roles
            if selected_roles:
                invalid = sorted(set(selected_roles) - set(known_roles))
                if invalid:
                    raise ValueError(f"{fact_id} role map has incompatible roles: {invalid}")
                upgraded = insert_scope(text, "role", selected_roles)
                role_scoped.append(fact_id)
            else:
                upgraded = insert_scope(text, "organization", [])
                organization_scoped.append(fact_id)
        writes.append((paths[fact_id], upgraded))

    for path in sorted(employment_root.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        if "schema_version: 1" not in text:
            raise ValueError(f"schema-v1 upgrade found non-v1 employment index: {path}")
        writes.append((path, text.replace("schema_version: 1", "schema_version: 2", 1)))

    plan = SchemaUpgradePlan(
        root=resolved,
        writes=tuple(writes),
        role_scoped=tuple(sorted(role_scoped)),
        organization_scoped=tuple(sorted(organization_scoped)),
        override_path=role_map_path.expanduser().resolve() if role_map_path else None,
    )
    validate_staged_upgrade(plan)
    return plan


def validate_staged_upgrade(plan: SchemaUpgradePlan) -> None:
    """Prove the upgraded vault passes strict current-schema validation."""
    with tempfile.TemporaryDirectory(prefix="vault-v2-stage-", dir=plan.root.parent) as raw:
        staged = Path(raw) / "vault"
        shutil.copytree(plan.root, staged)
        for path, content in plan.writes:
            target = staged / path.relative_to(plan.root)
            atomic_write_text(target, content)
        atomic_write_json(staged / "vault.json", DEFAULT_CONFIG)
        result = validate_vault(staged, strict=True)
        if not result.get("valid"):
            raise ValueError(f"staged schema upgrade is invalid: {result.get('errors')}")


def create_backup(plan: SchemaUpgradePlan) -> Path:
    """Create an immutable recovery copy of all schema-v1 canonical inputs."""
    backup = plan.root / "migrations" / "v1-original"
    if backup.exists():
        raise ValueError(f"schema-v1 backup already exists: {backup}")
    backup.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="v1-backup-", dir=backup.parent) as raw:
        staged = Path(raw) / "v1-original"
        records: list[dict[str, str]] = []
        source_paths = [plan.root / "vault.json", *(path for path, _ in plan.writes)]
        for source in source_paths:
            relative = source.relative_to(plan.root)
            destination = staged / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            records.append(
                {
                    "path": relative.as_posix(),
                    "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                }
            )
        atomic_write_json(staged / "manifest.json", {"version": 1, "files": records})
        staged.rename(backup)
    return backup


def apply_upgrade_plan(plan: SchemaUpgradePlan) -> None:
    """Apply v2 files atomically per path and restore v1 on failure."""
    validate_staged_upgrade(plan)
    create_backup(plan)
    originals = {path: path.read_bytes() for path, _ in plan.writes}
    config_path = plan.root / "vault.json"
    original_config = config_path.read_bytes()
    try:
        for path, content in plan.writes:
            atomic_write_text(path, content)
        atomic_write_json(config_path, DEFAULT_CONFIG)
        result = validate_vault(plan.root, strict=True)
        if not result.get("valid"):
            raise ValueError(f"applied schema upgrade is invalid: {result.get('errors')}")
    except BaseException:
        for path, original_bytes in originals.items():
            atomic_write_bytes(path, original_bytes)
        atomic_write_bytes(config_path, original_config)
        raise


def main(argv: Sequence[str] | None = None) -> int:
    """Preview a schema-v1 upgrade unless --apply is supplied."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vault-root", type=Path, default=Path("vault"))
    parser.add_argument("--role-map", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    try:
        plan = build_upgrade_plan(args.vault_root, args.role_map)
        if args.apply:
            apply_upgrade_plan(plan)
        result = plan.summary(applied=args.apply)
    except (OSError, RuntimeError, ValueError) as exc:
        print(json.dumps({"error": str(exc)}, indent=2), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
