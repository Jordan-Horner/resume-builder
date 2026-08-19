"""Private workspace discovery and first-run initialization."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path

from .atomic import atomic_write_json, atomic_write_text
from .layout import VaultLayout

WORKSPACE_CONFIG = ".resume-builder.json"
WORKSPACE_VERSION = 1
DEFAULT_WORKSPACE = Path("workspace")
GITHUB_REPOSITORY = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")


class WorkspaceError(RuntimeError):
    """Raised when a private workspace cannot be discovered or initialized safely."""


@dataclass(frozen=True)
class CommandResult:
    """Small command result used to make Git and GitHub operations testable."""

    returncode: int
    stdout: str = ""
    stderr: str = ""


Runner = Callable[[Sequence[str], Path], CommandResult]


@dataclass(frozen=True)
class WorkspaceInitResult:
    """Outcome of a workspace initialization attempt."""

    root: Path
    created: bool
    committed: bool
    backup: str
    github_repository: str | None = None


def run_command(arguments: Sequence[str], cwd: Path) -> CommandResult:
    """Run one argument-safe child process without invoking a shell."""
    completed = subprocess.run(
        list(arguments),
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
    )
    return CommandResult(completed.returncode, completed.stdout, completed.stderr)


def _require_success(result: CommandResult, action: str) -> None:
    if result.returncode == 0:
        return
    detail = result.stderr.strip() or result.stdout.strip() or "unknown error"
    raise WorkspaceError(f"{action} failed: {detail}")


def _is_git_repository(path: Path, runner: Runner) -> bool:
    result = runner(("git", "rev-parse", "--is-inside-work-tree"), path)
    return result.returncode == 0 and result.stdout.strip() == "true"


def _require_parent_ignore(target: Path, runner: Runner) -> None:
    """Refuse to place private data inside a parent Git repo unless it is ignored."""
    parent = target.parent.resolve()
    probe = runner(("git", "rev-parse", "--show-toplevel"), parent)
    if probe.returncode != 0:
        return
    repository = Path(probe.stdout.strip()).resolve()
    try:
        relative = target.resolve().relative_to(repository)
    except ValueError:
        return
    ignore_probe = relative / ".resume-builder-private-probe"
    ignored = runner(
        ("git", "check-ignore", "--quiet", "--no-index", ignore_probe.as_posix()),
        repository,
    )
    if ignored.returncode != 0:
        raise WorkspaceError(
            f"refusing to create private workspace inside Git repository {repository}: "
            f"{relative.as_posix()} is not ignored"
        )


def _workspace_configuration(backup: str, github_repository: str | None) -> dict[str, object]:
    git_config: dict[str, object] = {"backup": backup, "auto_checkpoint": False}
    if github_repository is not None:
        git_config["github_repository"] = github_repository
    return {
        "workspace_version": WORKSPACE_VERSION,
        "vault": {"path": "vault"},
        "paths": {
            "resumes": "resumes",
            "directions": "directions",
            "targets": "targets",
            "editorial": "editorial",
            "build": "build",
        },
        "git": git_config,
    }


def _write_workspace_files(
    root: Path,
    *,
    backup: str,
    github_repository: str | None,
) -> None:
    atomic_write_json(
        root / WORKSPACE_CONFIG,
        _workspace_configuration(backup, github_repository),
    )
    atomic_write_text(
        root / ".gitignore",
        "/build/\n*.db\n*.docx\n*.pdf\n*.sqlite\n*.sqlite3\n.DS_Store\n",
    )
    atomic_write_text(
        root / "README.md",
        "# Private Resume Builder Workspace\n\n"
        "This repository contains private career information. Keep every remote private.\n"
        "Local Git history is not an off-device backup.\n",
    )
    VaultLayout.load(root / "vault", allow_missing=True).initialize()
    workspace_resources = files("resume_builder.resources").joinpath("workspace")
    for directory in ("vault", "resumes", "directions", "targets", "editorial"):
        readme = workspace_resources.joinpath(directory).joinpath("README.md")
        atomic_write_text(root / directory / "README.md", readme.read_text(encoding="utf-8"))
    for directory in (
        "resumes/baselines",
        "resumes/plans",
        "resumes/tailored",
        "editorial/rules",
    ):
        atomic_write_text(root / directory / ".gitkeep", "")
    template = (
        files("resume_builder.resources").joinpath("templates").joinpath("resume-template.html")
    )
    atomic_write_text(
        root / "templates" / "resume-template.html",
        template.read_text(encoding="utf-8"),
    )


def _create_initial_commit(root: Path, runner: Runner) -> bool:
    name = runner(("git", "config", "user.name"), root)
    email = runner(("git", "config", "user.email"), root)
    if (
        name.returncode != 0
        or not name.stdout.strip()
        or email.returncode != 0
        or not email.stdout.strip()
    ):
        return False
    _require_success(runner(("git", "add", "."), root), "staging the initial workspace")
    _require_success(
        runner(("git", "commit", "-m", "Initialize private career workspace"), root),
        "creating the initial workspace checkpoint",
    )
    return True


def _connect_private_github(
    root: Path,
    repository: str,
    *,
    runner: Runner,
    committed: bool,
) -> None:
    if GITHUB_REPOSITORY.fullmatch(repository) is None:
        raise WorkspaceError("GitHub repository must use the OWNER/NAME format")
    if not committed:
        raise WorkspaceError(
            "a Git user.name and user.email are required before creating the private GitHub backup"
        )
    _require_success(runner(("gh", "auth", "status"), root), "checking GitHub authentication")
    _require_success(
        runner(
            (
                "gh",
                "repo",
                "create",
                repository,
                "--private",
                "--source",
                ".",
                "--remote",
                "origin",
            ),
            root,
        ),
        "creating the private GitHub repository",
    )
    visibility = runner(
        ("gh", "repo", "view", repository, "--json", "visibility", "--jq", ".visibility"),
        root,
    )
    _require_success(visibility, "verifying GitHub repository visibility")
    if visibility.stdout.strip().upper() != "PRIVATE":
        raise WorkspaceError(
            "GitHub did not report PRIVATE visibility; no workspace data was pushed"
        )
    _require_success(
        runner(("git", "push", "--set-upstream", "origin", "main"), root),
        "pushing the initial private workspace checkpoint",
    )


def initialize_workspace(
    target: Path,
    *,
    backup: str = "local",
    github_repository: str | None = None,
    git_name: str | None = None,
    git_email: str | None = None,
    runner: Runner = run_command,
) -> WorkspaceInitResult:
    """Create an independent private Git workspace atomically."""
    if backup not in {"local", "github"}:
        raise WorkspaceError(f"unsupported backup mode: {backup}")
    if backup == "github" and not github_repository:
        raise WorkspaceError("--github-repo OWNER/NAME is required for GitHub backup")
    if bool(git_name) != bool(git_email):
        raise WorkspaceError("Git name and email must be provided together")

    resolved = target.expanduser().resolve()
    config_path = resolved / WORKSPACE_CONFIG
    if config_path.is_file() and _is_git_repository(resolved, runner):
        data = json.loads(config_path.read_text(encoding="utf-8"))
        configured_backup = str(data.get("git", {}).get("backup", "local"))
        committed = runner(("git", "rev-parse", "--verify", "HEAD"), resolved).returncode == 0
        return WorkspaceInitResult(resolved, False, committed, configured_backup)
    if resolved.exists() and any(resolved.iterdir()):
        raise WorkspaceError(f"workspace directory is not empty: {resolved}")

    resolved.parent.mkdir(parents=True, exist_ok=True)
    _require_parent_ignore(resolved, runner)
    temporary = Path(
        tempfile.mkdtemp(prefix=f".{resolved.name}.resume-builder-init-", dir=resolved.parent)
    )
    try:
        _write_workspace_files(
            temporary,
            backup=backup,
            github_repository=github_repository,
        )
        _require_success(runner(("git", "init", "-b", "main"), temporary), "initializing local Git")
        if git_name is not None and git_email is not None:
            _require_success(
                runner(("git", "config", "user.name", git_name), temporary),
                "configuring the workspace Git author name",
            )
            _require_success(
                runner(("git", "config", "user.email", git_email), temporary),
                "configuring the workspace Git author email",
            )
        committed = _create_initial_commit(temporary, runner)
        if resolved.exists():
            resolved.rmdir()
        os.replace(temporary, resolved)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise

    if backup == "github":
        assert github_repository is not None
        try:
            _connect_private_github(
                resolved,
                github_repository,
                runner=runner,
                committed=committed,
            )
        except BaseException:
            atomic_write_json(resolved / WORKSPACE_CONFIG, _workspace_configuration("local", None))
            raise
    return WorkspaceInitResult(
        resolved,
        True,
        committed,
        backup,
        github_repository if backup == "github" else None,
    )


def connect_existing_workspace(
    target: Path,
    *,
    runner: Runner = run_command,
) -> WorkspaceInitResult:
    """Connect an existing private Git workspace without rewriting its data."""
    resolved = target.expanduser().resolve()
    if not resolved.is_dir():
        raise WorkspaceError(f"existing workspace directory does not exist: {resolved}")
    _require_parent_ignore(resolved, runner)
    if not _is_git_repository(resolved, runner):
        raise WorkspaceError(
            "existing workspace must be an independent Git repository before it can be connected"
        )
    if not (resolved / "vault" / "vault.json").is_file():
        raise WorkspaceError(f"existing workspace does not contain vault/vault.json: {resolved}")

    config_path = resolved / WORKSPACE_CONFIG
    if config_path.is_file():
        data = json.loads(config_path.read_text(encoding="utf-8"))
        configured_backup = str(data.get("git", {}).get("backup", "local"))
    else:
        configured_backup = "local"
        atomic_write_json(
            config_path,
            _workspace_configuration(configured_backup, None),
        )
    committed = runner(("git", "rev-parse", "--verify", "HEAD"), resolved).returncode == 0
    return WorkspaceInitResult(resolved, False, committed, configured_backup)


def discover_workspace(start: Path | None = None) -> Path | None:
    """Find a configured workspace or a compatible legacy workspace."""
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


def _interactive_identity() -> tuple[str | None, str | None]:
    name = run_command(("git", "config", "--global", "user.name"), Path.cwd())
    email = run_command(("git", "config", "--global", "user.email"), Path.cwd())
    if (
        name.returncode == 0
        and name.stdout.strip()
        and email.returncode == 0
        and email.stdout.strip()
    ):
        return None, None
    print("\nGit needs an author identity for local vault checkpoints.")
    entered_name = input("Git author name: ").strip()
    entered_email = input("Git author email: ").strip()
    if not entered_name or not entered_email:
        raise WorkspaceError("Git author name and email are required for the initial checkpoint")
    return entered_name, entered_email


def _interactive_options(
    default_target: Path,
) -> tuple[Path, str, str | None, str | None, str | None]:
    print("Welcome to Resume Builder.")
    print("Your career information stays in a separate private Git repository.")
    entered = input(f"Private workspace location [{default_target}]: ").strip()
    target = Path(entered) if entered else default_target
    print("\nChoose private-workspace setup:")
    print("  1. Local Git plus a private GitHub backup (recommended)")
    print("  2. Local Git only (no protection from device loss)")
    print("  3. Connect an existing private Git workspace")
    choice = input("Choice [1]: ").strip() or "1"
    if choice == "2":
        git_name, git_email = _interactive_identity()
        return target, "local", None, git_name, git_email
    if choice == "3":
        return target, "existing", None, None, None
    if choice != "1":
        raise WorkspaceError("choice must be 1, 2, or 3")
    repository = input("Private GitHub repository (OWNER/NAME): ").strip()
    if not repository or "/" not in repository:
        raise WorkspaceError("enter a GitHub repository as OWNER/NAME")
    confirmation = input(
        f"Create {repository} as PRIVATE, verify it, then push the initial vault? [y/N]: "
    )
    if confirmation.strip().lower() not in {"y", "yes"}:
        raise WorkspaceError("GitHub backup was not confirmed")
    git_name, git_email = _interactive_identity()
    return target, "github", repository, git_name, git_email


def main(argv: Sequence[str] | None = None) -> int:
    """Initialize a private workspace with local Git and optional private backup."""
    parser = argparse.ArgumentParser(prog="resume-builder init")
    parser.add_argument("--workspace", type=Path, default=DEFAULT_WORKSPACE)
    parser.add_argument("--storage", choices=("local", "github"))
    parser.add_argument("--github-repo", metavar="OWNER/NAME")
    parser.add_argument("--git-name")
    parser.add_argument("--git-email")
    parser.add_argument(
        "--existing",
        action="store_true",
        help="connect an existing private Git workspace without rewriting its data",
    )
    args = parser.parse_args(argv)

    if args.existing and (args.storage is not None or args.github_repo is not None):
        parser.error("--existing cannot be combined with --storage or --github-repo")

    interactive = args.storage is None and sys.stdin.isatty() and sys.stdout.isatty()
    if interactive:
        target, backup, repository, git_name, git_email = _interactive_options(args.workspace)
    else:
        target = args.workspace
        backup = "existing" if args.existing else args.storage or "local"
        repository = args.github_repo
        git_name = args.git_name
        git_email = args.git_email
    try:
        if backup == "existing":
            result = connect_existing_workspace(target)
        else:
            result = initialize_workspace(
                target,
                backup=backup,
                github_repository=repository,
                git_name=git_name,
                git_email=git_email,
            )
    except (OSError, ValueError, WorkspaceError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    verb = "Created" if result.created else "Connected"
    print(f"{verb} private workspace: {result.root}")
    if result.committed:
        print("Local Git checkpoint: ready")
    else:
        print("Local Git initialized, but no checkpoint was created.")
        print("Configure Git user.name and user.email, then create a checkpoint.")
    if result.backup == "github":
        print(f"Private GitHub backup verified: {result.github_repository}")
    else:
        print("Backup: local only. A private remote is recommended to prevent data loss.")
    return 0
