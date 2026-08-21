"""Typed status records and freshness helpers for generated artifacts."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .layout import contained_path


@dataclass(frozen=True)
class ArtifactStatus:
    """Serializable readiness state for one generated artifact."""

    status: str
    path: str
    reasons: tuple[str, ...] = ()
    details: Mapping[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        """Return the stable JSON-facing report shape."""
        result: dict[str, Any] = {
            "status": self.status,
            "path": self.path,
            "reasons": list(self.reasons),
        }
        result.update({key: value for key, value in self.details.items() if key not in result})
        return result


def sha256(path: Path) -> str:
    """Hash an artifact exactly as report manifests do."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def relative_path(path: Path, project_root: Path) -> str:
    """Return a project-relative POSIX path for report output."""
    return path.resolve().relative_to(project_root).as_posix()


def load_json_object(path: Path) -> dict[str, Any]:
    """Load a JSON object with a report-friendly validation error."""
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def record_freshness(
    value: object,
    project_root: Path,
    owner: str,
    *,
    base: Path | None = None,
) -> str | None:
    """Return the first integrity problem for a path-and-digest record."""
    if not isinstance(value, dict):
        return f"{owner} record is missing"
    path_value = value.get("path")
    digest = value.get("sha256")
    if not isinstance(path_value, str) or not isinstance(digest, str):
        return f"{owner} record is invalid"
    try:
        path = contained_path(base or project_root, path_value, f"{owner} path")
    except ValueError:
        return f"{owner} path is unsafe"
    if not path.is_file():
        return f"{owner} file is missing"
    if sha256(path) != digest:
        return f"{owner} file changed"
    return None
