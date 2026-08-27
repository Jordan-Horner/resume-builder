#!/usr/bin/env python3
"""Fail when built distributions cross the engine/private-workspace boundary."""

from __future__ import annotations

import argparse
import tarfile
import zipfile
from collections.abc import Iterable
from pathlib import Path, PurePosixPath

TEXT_SUFFIXES = {
    ".cfg",
    ".html",
    ".ini",
    ".json",
    ".md",
    ".py",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}
PRIVATE_ROOTS = {
    ".git",
    "build",
    "career",
    "editorial",
    "resumes",
    "targets",
    "vault",
    "workspace",
}
PUBLIC_WHEEL_PACKAGES = {"job_puller", "resume_builder"}


def _safe_parts(name: str) -> tuple[str, ...]:
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"unsafe archive member: {name}")
    return tuple(part for part in path.parts if part not in {"", "."})


def _payload_has_denylist(name: str, payload: bytes, denylist: tuple[bytes, ...]) -> bool:
    return PurePosixPath(name).suffix.casefold() in TEXT_SUFFIXES and any(
        value in payload.lower() for value in denylist
    )


def _denylist(path: Path | None) -> tuple[bytes, ...]:
    if path is None:
        return ()
    values = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        value = raw.strip()
        if value and not value.startswith("#"):
            if len(value) < 4:
                raise ValueError("denylist entries must contain at least four characters")
            values.append(value.casefold().encode("utf-8"))
    return tuple(values)


def _check_private_roots(names: Iterable[str], *, strip_first: bool) -> None:
    for name in names:
        parts = _safe_parts(name)
        scoped = parts[1:] if strip_first and parts else parts
        if scoped and scoped[0] in PRIVATE_ROOTS:
            raise ValueError(f"private runtime path leaked into distribution: {name}")


def audit_wheel(path: Path, denylist: tuple[bytes, ...]) -> None:
    """Require the wheel to contain only the CLI package and its metadata."""
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        _check_private_roots(names, strip_first=False)
        for name in names:
            parts = _safe_parts(name)
            if not parts:
                continue
            if parts[0] not in PUBLIC_WHEEL_PACKAGES and not parts[0].endswith(".dist-info"):
                raise ValueError(f"unexpected wheel path: {name}")
            if (
                parts[0] == "resume_builder"
                and len(parts) > 1
                and parts[1]
                in {
                    ".agents",
                    "examples",
                }
            ):
                raise ValueError(f"agent or fixture content leaked into wheel: {name}")
            if _payload_has_denylist(name, archive.read(name), denylist):
                raise ValueError(f"private denylist match in wheel member: {name}")
        required = {
            "job_puller/cli.py",
            "resume_builder/cli.py",
            "resume_builder/evidence_questions.py",
            "resume_builder/resources/workspace/vault/README.md",
        }
        missing = sorted(required - set(names))
        if missing:
            raise ValueError(f"wheel is missing required CLI content: {missing}")


def audit_sdist(path: Path, denylist: tuple[bytes, ...]) -> None:
    """Require the source archive to omit runtime data and retain the public demo."""
    with tarfile.open(path, "r:gz") as archive:
        files = [member for member in archive.getmembers() if member.isfile()]
        names = [member.name for member in files]
        roots = {_safe_parts(name)[0] for name in names if _safe_parts(name)}
        if len(roots) != 1 or not next(iter(roots)).startswith("resume_builder-"):
            raise ValueError("source archive must have one versioned resume_builder root")
        root = next(iter(roots))
        scoped_names = {PurePosixPath(*_safe_parts(name)[1:]).as_posix() for name in names}
        _check_private_roots(names, strip_first=True)
        if not {"AGENTS.md", "CLAUDE.md"} <= scoped_names:
            raise ValueError("source archive is missing cross-agent instruction entry points")
        canonical_skills = {
            parts[3]
            for name in names
            if (parts := _safe_parts(name))[0] == root
            and len(parts) == 5
            and parts[1:3] == (".agents", "skills")
            and parts[4] == "SKILL.md"
        }
        claude_skills = {
            parts[3]
            for name in names
            if (parts := _safe_parts(name))[0] == root
            and len(parts) == 5
            and parts[1:3] == (".claude", "skills")
            and parts[4] == "SKILL.md"
        }
        if not canonical_skills or claude_skills != canonical_skills:
            raise ValueError("source archive has incomplete Claude skill adapters")
        if not any("/examples/phoenix-wright/workspace/" in name for name in names):
            raise ValueError("source archive is missing the approved fictional demonstration")
        for member in files:
            stream = archive.extractfile(member)
            if stream is None:
                continue
            if _payload_has_denylist(member.name, stream.read(), denylist):
                raise ValueError(f"private denylist match in source member: {member.name}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", type=Path, default=Path("dist"))
    parser.add_argument(
        "--denylist-file",
        type=Path,
        help="Optional untracked newline-separated private strings to reject",
    )
    args = parser.parse_args()
    wheels = sorted(args.dist.glob("*.whl"))
    sdists = sorted(args.dist.glob("*.tar.gz"))
    if len(wheels) != 1 or len(sdists) != 1:
        raise ValueError("distribution directory must contain exactly one wheel and one sdist")
    denylist = _denylist(args.denylist_file)
    audit_wheel(wheels[0], denylist)
    audit_sdist(sdists[0], denylist)
    print(f"Distribution boundary valid: {wheels[0].name}, {sdists[0].name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
