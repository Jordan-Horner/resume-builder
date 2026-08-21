"""Typed status records and freshness helpers for generated artifacts."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import __version__
from .feedback_resolution import manifest_guidance_freshness
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


def build_manifest_freshness(manifest_path: Path, project_root: Path) -> list[str]:
    """Return every reason a compiled build can no longer be reused."""
    if not manifest_path.is_file():
        return ["compiled build manifest is missing"]
    try:
        manifest = load_json_object(manifest_path)
    except ValueError as exc:
        return [str(exc)]

    reasons: list[str] = []
    if (
        manifest.get("version") != 1
        or manifest.get("phase") != "build"
        or manifest.get("valid") is not True
    ):
        reasons.append("compiled build manifest has an unsupported schema")
    compiler = manifest.get("compiler")
    if not isinstance(compiler, dict) or compiler.get("version") != __version__:
        reasons.append("compiled build uses a different builder version")

    for owner in ("source", "template", "synthesis"):
        reason = record_freshness(manifest.get(owner), project_root, f"build {owner}")
        if reason:
            reasons.append(reason)

    outputs = manifest.get("outputs")
    if not isinstance(outputs, list) or not outputs:
        reasons.append("compiled build output inventory is missing")
    else:
        for index, output in enumerate(outputs):
            reason = record_freshness(output, project_root, f"build output[{index}]")
            if reason:
                reasons.append(reason)

    evidence = manifest.get("evidence")
    facts = evidence.get("facts") if isinstance(evidence, dict) else None
    vault_root = project_root / "vault"
    if not isinstance(facts, list):
        reasons.append("compiled build fact inventory is missing")
    else:
        for index, fact in enumerate(facts):
            reason = record_freshness(
                fact,
                project_root,
                f"build fact[{index}]",
                base=vault_root,
            )
            if reason:
                reasons.append(reason)

    reasons.extend(manifest_guidance_freshness(manifest, project_root, vault_root))
    return list(dict.fromkeys(reasons))
