"""Packaged resume-template installation for private workspaces."""

from __future__ import annotations

from importlib.resources import files
from pathlib import Path
from typing import Any

from .atomic import atomic_write_json, atomic_write_text
from .layout import VaultLayout


def _walk_resources(node: Any, prefix: Path = Path()) -> list[tuple[Path, str]]:
    entries: list[tuple[Path, str]] = []
    for child in sorted(node.iterdir(), key=lambda item: item.name):
        relative = prefix / child.name
        if child.is_dir():
            entries.extend(_walk_resources(child, relative))
        elif child.is_file():
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError(f"unsafe packaged template resource: {relative}")
            entries.append((relative, child.read_text(encoding="utf-8")))
    return entries


def template_resources() -> list[tuple[Path, str]]:
    """Return every immutable built-in template resource and its workspace path."""
    root = files("resume_builder.resources") / "templates"
    return _walk_resources(root)


def sync_templates(root: Path) -> dict[str, object]:
    """Install missing built-ins without overwriting workspace-owned templates."""
    installed: list[str] = []
    present: list[str] = []
    conflicts: list[str] = []
    for relative, content in template_resources():
        destination = root / "templates" / relative
        label = (Path("templates") / relative).as_posix()
        if not destination.exists():
            atomic_write_text(destination, content)
            installed.append(label)
        elif destination.is_file() and destination.read_text(encoding="utf-8") == content:
            present.append(label)
        else:
            conflicts.append(label)
    return {
        "valid": True,
        "workspace": str(root),
        "installed": installed,
        "already_present": present,
        "conflicts": conflicts,
    }


def write_workspace_files(root: Path, configuration: dict[str, object]) -> None:
    """Write the packaged skeleton for one new private workspace."""
    atomic_write_json(root / ".resume-builder.json", configuration)
    atomic_write_text(
        root / ".gitignore",
        "/build/\n*.db\n*.docx\n*.pdf\n*.sqlite\n*.sqlite3\n.DS_Store\n",
    )
    atomic_write_text(
        root / "README.md",
        "# Private Resume Builder Workspace\n\n"
        "This repository contains private career information. Keep every remote private.\n"
        "Local Git history is not an off-device backup.\n\n"
        "## Where to find finished resumes\n\n"
        "Use `exports/resumes/` for PDFs that are ready to upload with job applications.\n"
        "Targeting context stays in the folder name, while the PDF itself uses a neutral\n"
        "filename such as `<candidate-name>-Resume.pdf`.\n\n"
        "The ignored `build/` directory contains internal previews, manifests, reviews,\n"
        "diagnostics, and audited working files. You normally do not need to open it.\n\n"
        "Canonical career facts and editable resume sources remain under `vault/` and\n"
        "`resumes/`. Files under `exports/` and `build/` can be regenerated from those\n"
        "sources.\n",
    )
    VaultLayout.load(root / "vault", allow_missing=True).initialize()
    workspace_resources = files("resume_builder.resources") / "workspace"
    for directory in ("vault", "resumes", "directions", "targets", "editorial", "exports"):
        readme = workspace_resources / directory / "README.md"
        atomic_write_text(root / directory / "README.md", readme.read_text(encoding="utf-8"))
    for directory in (
        "resumes/baselines",
        "resumes/plans",
        "resumes/tailored",
        "editorial/rules",
    ):
        atomic_write_text(root / directory / ".gitkeep", "")
    for relative, content in template_resources():
        atomic_write_text(root / "templates" / relative, content)
