"""Validated, containment-safe paths for a Resume Builder vault."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from .atomic import atomic_write_json

SCHEMA_VERSION = 2
DEFAULT_CONFIG: dict[str, object] = {
    "schema_version": SCHEMA_VERSION,
    "facts_path": "facts",
    "employment_path": "employment",
    "sources_manifest": "sources/manifest.json",
}


class LayoutError(ValueError):
    """Raised when vault configuration or a vault-relative path is unsafe."""


def relative_path(value: object, field: str) -> Path:
    """Validate and convert a portable vault-relative path."""
    if not isinstance(value, str) or not value.strip():
        raise LayoutError(f"{field} must be a non-empty relative path")
    portable = PurePosixPath(value)
    if portable.is_absolute() or ".." in portable.parts or "." in portable.parts:
        raise LayoutError(f"{field} must not be absolute or contain traversal: {value!r}")
    return Path(*portable.parts)


def contained_path(base: Path, value: object, field: str) -> Path:
    """Resolve a relative path and require it to remain beneath *base*."""
    relative = relative_path(value, field)
    resolved_base = base.resolve()
    resolved = (resolved_base / relative).resolve()
    if not resolved.is_relative_to(resolved_base):
        raise LayoutError(f"{field} escapes its allowed directory: {value!r}")
    return resolved


def load_json_object(path: Path) -> dict[str, Any]:
    """Load a JSON object with a useful configuration error."""
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise LayoutError(f"invalid JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise LayoutError(f"{path} must contain a JSON object")
    return value


@dataclass(frozen=True)
class VaultLayout:
    """Canonical paths selected by a validated ``vault.json`` declaration."""

    root: Path
    config_path: Path
    facts: Path
    employment: Path
    manifest: Path
    sources: Path
    normalized_sources: Path
    hydration_report: Path
    migrations: Path
    config: dict[str, object]

    @classmethod
    def load(cls, root: Path, *, allow_missing: bool = False) -> VaultLayout:
        """Load an existing layout or construct the default layout in memory."""
        resolved_root = root.expanduser().resolve()
        config_path = resolved_root / "vault.json"
        if config_path.exists():
            config: dict[str, object] = load_json_object(config_path)
        elif allow_missing:
            config = dict(DEFAULT_CONFIG)
        else:
            raise LayoutError(f"missing vault configuration: {config_path}")

        if config.get("schema_version") != SCHEMA_VERSION:
            raise LayoutError(f"unsupported vault schema: {config.get('schema_version')!r}")
        facts = contained_path(resolved_root, config.get("facts_path"), "facts_path")
        employment = contained_path(
            resolved_root,
            config.get("employment_path"),
            "employment_path",
        )
        manifest = contained_path(
            resolved_root,
            config.get("sources_manifest"),
            "sources_manifest",
        )
        sources = manifest.parent
        normalized_sources = contained_path(sources, "normalized", "normalized sources")
        paths = {facts, employment, manifest, normalized_sources}
        if len(paths) != 4:
            raise LayoutError("vault paths must be distinct")
        roots = (facts, employment, sources)
        if any(
            left.is_relative_to(right) or right.is_relative_to(left)
            for index, left in enumerate(roots)
            for right in roots[index + 1 :]
        ):
            raise LayoutError("facts, employment, and sources paths must not overlap")

        return cls(
            root=resolved_root,
            config_path=config_path,
            facts=facts,
            employment=employment,
            manifest=manifest,
            sources=sources,
            normalized_sources=normalized_sources,
            hydration_report=resolved_root / "hydration-report.md",
            migrations=resolved_root / "migrations",
            config=config,
        )

    def initialize(self) -> None:
        """Create missing canonical directories and the schema declaration."""
        self.root.mkdir(parents=True, exist_ok=True)
        if not self.config_path.exists():
            atomic_write_json(self.config_path, self.config)
        self.facts.mkdir(parents=True, exist_ok=True)
        self.employment.mkdir(parents=True, exist_ok=True)
        self.normalized_sources.mkdir(parents=True, exist_ok=True)

    def relative(self, path: Path) -> str:
        """Return a portable vault-relative path after containment validation."""
        resolved = path.resolve()
        if not resolved.is_relative_to(self.root):
            raise LayoutError(f"path is outside vault: {path}")
        return resolved.relative_to(self.root).as_posix()

    def snapshot_path(self, value: object) -> Path:
        """Resolve a manifest snapshot path inside the normalized source folder."""
        snapshot = contained_path(self.root, value, "snapshot")
        if not snapshot.is_relative_to(self.normalized_sources):
            raise LayoutError(f"snapshot must be under normalized sources: {value!r}")
        return snapshot
