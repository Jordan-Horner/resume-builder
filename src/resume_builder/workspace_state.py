"""Inspect workspace configuration, Git state, and remote privacy without mutation."""

from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

WORKSPACE_CONFIG = ".resume-builder.json"
WORKSPACE_VERSION = 1
DEFAULT_WORKSPACE = Path("workspace")
DEFAULT_VAULT_REPOSITORY_NAME = "resume-vault"
GITHUB_REPOSITORY = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
GITHUB_OWNER = re.compile(r"[A-Za-z0-9-]+")
GITHUB_REMOTES = (
    re.compile(
        r"https?://github\.com/(?P<repository>[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+?)(?:\.git)?/?$"
    ),
    re.compile(r"git@github\.com:(?P<repository>[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+?)(?:\.git)?$"),
    re.compile(
        r"ssh://git@github\.com/(?P<repository>[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+?)(?:\.git)?/?$"
    ),
)


class WorkspaceError(RuntimeError):
    """Raised when a private workspace cannot be discovered or initialized safely."""


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""


Runner = Callable[[Sequence[str], Path], CommandResult]


@dataclass(frozen=True)
class WorkspaceInitResult:
    root: Path
    created: bool
    committed: bool
    backup: str
    github_repository: str | None = None


def run_command(arguments: Sequence[str], cwd: Path) -> CommandResult:
    completed = subprocess.run(
        list(arguments), cwd=cwd, check=False, capture_output=True, text=True
    )
    return CommandResult(completed.returncode, completed.stdout, completed.stderr)


def default_github_repository(
    *, runner: Runner = run_command, cwd: Path | None = None
) -> str | None:
    result = runner(("gh", "api", "user", "--jq", ".login"), (cwd or Path.cwd()).resolve())
    owner = result.stdout.strip()
    if result.returncode != 0 or GITHUB_OWNER.fullmatch(owner) is None:
        return None
    return f"{owner}/{DEFAULT_VAULT_REPOSITORY_NAME}"


def github_repository_from_remote(remote: str) -> str | None:
    for pattern in GITHUB_REMOTES:
        if match := pattern.fullmatch(remote.strip()):
            return match.group("repository")
    return None


def _remote_privacy(root: Path, *, runner: Runner) -> tuple[str, str | None, str | None]:
    result = runner(("git", "remote", "get-url", "origin"), root)
    remote = result.stdout.strip() if result.returncode == 0 and result.stdout.strip() else None
    if remote is None:
        return "local", None, None
    repository = github_repository_from_remote(remote)
    if repository is None:
        return "unverified", remote, None
    visibility = runner(
        ("gh", "repo", "view", repository, "--json", "visibility", "--jq", ".visibility"), root
    )
    if visibility.returncode != 0:
        return "unverified", remote, repository
    normalized = visibility.stdout.strip().upper()
    if normalized == "PRIVATE":
        return "github", remote, repository
    if normalized == "PUBLIC":
        return "public", remote, repository
    return "unverified", remote, repository


def _is_git_repository(path: Path, runner: Runner) -> bool:
    result = runner(("git", "rev-parse", "--is-inside-work-tree"), path)
    return result.returncode == 0 and result.stdout.strip() == "true"


def discover_workspace(start: Path | None = None) -> Path | None:
    environment = os.environ.get("RESUME_BUILDER_WORKSPACE")
    if environment:
        candidate = Path(environment).expanduser().resolve()
        if (candidate / WORKSPACE_CONFIG).is_file() or (
            candidate / "vault" / "vault.json"
        ).is_file():
            return candidate
        raise WorkspaceError(f"configured workspace does not exist: {candidate}")
    origin = (start or Path.cwd()).expanduser().resolve()
    for directory in (origin, *origin.parents):
        if (directory / WORKSPACE_CONFIG).is_file():
            return directory
        nested = directory / DEFAULT_WORKSPACE
        if (nested / WORKSPACE_CONFIG).is_file():
            return nested
        if (directory / "vault" / "vault.json").is_file():
            return directory
    return None


def workspace_status(
    root: Path | None = None, *, runner: Runner = run_command
) -> dict[str, object]:
    resolved = root.expanduser().resolve() if root is not None else discover_workspace()
    if resolved is None:
        raise WorkspaceError("no Resume Builder workspace could be discovered")
    if (
        not (resolved / WORKSPACE_CONFIG).is_file()
        and not (resolved / "vault" / "vault.json").is_file()
    ):
        raise WorkspaceError(f"configured workspace does not exist: {resolved}")
    if not _is_git_repository(resolved, runner):
        raise WorkspaceError(f"workspace is not an independent Git repository: {resolved}")
    backup, remote, repository = _remote_privacy(resolved, runner=runner)
    return {
        "workspace": str(resolved),
        "independent_git": True,
        "backup": backup,
        "origin": remote,
        "github_repository": repository,
        "privacy_verified": backup in {"local", "github"},
    }
