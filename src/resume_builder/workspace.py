"""Private workspace discovery and first-run initialization."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

from .atomic import atomic_write_json
from .resume_templates import scaffold_template, select_catalog_item, template_catalog
from .workspace_state import (
    DEFAULT_VAULT_REPOSITORY_NAME,
    DEFAULT_WORKSPACE,
    GITHUB_REPOSITORY,
    WORKSPACE_CONFIG,
    WORKSPACE_VERSION,
    CommandResult,
    Runner,
    WorkspaceError,
    WorkspaceInitResult,
    _is_git_repository,
    _remote_privacy,
    default_github_repository,
    discover_workspace,
    github_repository_from_remote,
    run_command,
    workspace_status,
)
from .workspace_templates import sync_templates, write_workspace_files

__all__ = [
    "CommandResult",
    "WorkspaceError",
    "WorkspaceInitResult",
    "connect_existing_workspace",
    "default_github_repository",
    "discover_workspace",
    "github_repository_from_remote",
    "initialize_workspace",
    "main",
    "run_command",
    "status_main",
    "sync_workspace_templates",
    "workspace_status",
]


def sync_workspace_templates(root: Path) -> dict[str, object]:
    """Install missing built-ins without overwriting workspace-owned templates."""
    resolved = root.expanduser().resolve()
    if not (resolved / WORKSPACE_CONFIG).is_file():
        raise WorkspaceError(f"workspace configuration is missing: {resolved}")
    _load_workspace_configuration(resolved / WORKSPACE_CONFIG)
    return sync_templates(resolved)


def _require_success(result: CommandResult, action: str) -> None:
    if result.returncode == 0:
        return
    detail = result.stderr.strip() or result.stdout.strip() or "unknown error"
    raise WorkspaceError(f"{action} failed: {detail}")


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
            "exports": "exports",
        },
        "git": git_config,
    }


def _load_workspace_configuration(path: Path) -> dict[str, object]:
    """Load the configuration fields needed to trust an existing workspace."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise WorkspaceError(f"invalid workspace configuration: {exc}") from exc
    if not isinstance(raw, dict):
        raise WorkspaceError("workspace configuration must be a JSON object")
    if raw.get("workspace_version") != WORKSPACE_VERSION:
        raise WorkspaceError(
            f"workspace configuration must declare workspace_version {WORKSPACE_VERSION}"
        )
    git = raw.get("git")
    if not isinstance(git, dict):
        raise WorkspaceError("workspace configuration git must be an object")
    backup = git.get("backup")
    if backup not in {"local", "github", "unverified"}:
        raise WorkspaceError(
            "workspace configuration git.backup must be local, github, or unverified"
        )
    repository = git.get("github_repository")
    if repository is not None and (
        not isinstance(repository, str) or GITHUB_REPOSITORY.fullmatch(repository) is None
    ):
        raise WorkspaceError("workspace configuration git.github_repository must be OWNER/NAME")
    if backup == "github" and repository is None:
        raise WorkspaceError(
            "workspace configuration with GitHub backup requires git.github_repository"
        )
    return raw


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
        raise WorkspaceError("GitHub backup requires authentication or --github-repo OWNER/NAME")
    if bool(git_name) != bool(git_email):
        raise WorkspaceError("Git name and email must be provided together")

    resolved = target.expanduser().resolve()
    config_path = resolved / WORKSPACE_CONFIG
    if config_path.is_file() and _is_git_repository(resolved, runner):
        _load_workspace_configuration(config_path)
        sync_workspace_templates(resolved)
        actual_backup, remote, actual_repository = _remote_privacy(resolved, runner=runner)
        if actual_backup == "public":
            raise WorkspaceError(
                f"existing workspace origin is PUBLIC ({remote}); disconnect it or make it "
                "private before continuing"
            )
        committed = runner(("git", "rev-parse", "--verify", "HEAD"), resolved).returncode == 0
        return WorkspaceInitResult(
            resolved,
            False,
            committed,
            actual_backup,
            actual_repository,
        )
    if resolved.exists() and any(resolved.iterdir()):
        raise WorkspaceError(f"workspace directory is not empty: {resolved}")

    resolved.parent.mkdir(parents=True, exist_ok=True)
    _require_parent_ignore(resolved, runner)
    temporary = Path(
        tempfile.mkdtemp(prefix=f".{resolved.name}.resume-builder-init-", dir=resolved.parent)
    )
    try:
        write_workspace_files(
            temporary,
            _workspace_configuration(backup, github_repository),
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
    result_repository = github_repository if backup == "github" else None
    return WorkspaceInitResult(resolved, True, committed, backup, result_repository)


def connect_existing_workspace(
    target: Path,
    *,
    allow_unverified_remote: bool = False,
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

    backup, remote, github_repository = _remote_privacy(resolved, runner=runner)
    if backup == "public":
        raise WorkspaceError(
            f"existing workspace origin is PUBLIC ({remote}); disconnect it or make it private "
            "before connecting"
        )
    if backup == "unverified" and not allow_unverified_remote:
        raise WorkspaceError(
            f"existing workspace origin privacy could not be verified ({remote}); "
            "verify it is private or rerun with --allow-unverified-remote"
        )

    config_path = resolved / WORKSPACE_CONFIG
    if config_path.is_file():
        _load_workspace_configuration(config_path)
    else:
        atomic_write_json(
            config_path,
            _workspace_configuration(backup, github_repository),
        )
    sync_workspace_templates(resolved)
    committed = runner(("git", "rev-parse", "--verify", "HEAD"), resolved).returncode == 0
    return WorkspaceInitResult(resolved, False, committed, backup, github_repository)


def status_main(argv: Sequence[str] | None = None) -> int:
    """Print the resolved private workspace and remote privacy state."""
    parser = argparse.ArgumentParser(prog="resume-builder workspace")
    subparsers = parser.add_subparsers(dest="action", required=True)
    show = subparsers.add_parser("show", help="Show the active private workspace")
    show.add_argument("--workspace", type=Path)
    sync = subparsers.add_parser("templates", help="Manage built-in resume templates")
    sync_subparsers = sync.add_subparsers(dest="template_action", required=True)
    sync_templates = sync_subparsers.add_parser(
        "sync", help="Install missing built-ins without overwriting custom files"
    )
    sync_templates.add_argument("--workspace", type=Path)
    list_templates = sync_subparsers.add_parser(
        "list", help="List content templates and visual themes"
    )
    list_templates.add_argument("--workspace", type=Path)
    validate_templates = sync_subparsers.add_parser(
        "validate", help="Validate all templates or one template ID"
    )
    validate_templates.add_argument("template_id", nargs="?")
    validate_templates.add_argument("--workspace", type=Path)
    scaffold = sync_subparsers.add_parser(
        "scaffold", help="Create a workspace-owned version-2 template"
    )
    scaffold.add_argument("kind", choices=("content", "theme"))
    scaffold.add_argument("template_id")
    scaffold.add_argument("--workspace", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.action == "show":
            result = workspace_status(args.workspace)
        else:
            target = args.workspace or discover_workspace()
            if target is None:
                raise WorkspaceError("no Resume Builder workspace is configured")
            if args.template_action == "sync":
                result = sync_workspace_templates(target)
            elif args.template_action in {"list", "validate"}:
                result = select_catalog_item(
                    template_catalog(target), getattr(args, "template_id", None)
                )
                if args.template_action == "validate" and result["valid"] is not True:
                    raise ValueError(f"template validation failed: {result['errors']}")
            else:
                result = scaffold_template(target, args.kind, args.template_id)
    except (OSError, ValueError, WorkspaceError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": str(exc)}, indent=2), file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


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
    default_repository = default_github_repository()
    suggestion = default_repository or f"OWNER/{DEFAULT_VAULT_REPOSITORY_NAME}"
    entered_repository = input(f"Private GitHub repository [{suggestion}]: ").strip()
    repository = entered_repository or default_repository
    if repository is None or "/" not in repository:
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
    parser.add_argument(
        "--allow-unverified-remote",
        action="store_true",
        help="connect an existing non-GitHub or unverifiable origin after checking it manually",
    )
    args = parser.parse_args(argv)

    if args.existing and (args.storage is not None or args.github_repo is not None):
        parser.error("--existing cannot be combined with --storage or --github-repo")
    if args.allow_unverified_remote and not args.existing:
        parser.error("--allow-unverified-remote requires --existing")

    interactive = args.storage is None and sys.stdin.isatty() and sys.stdout.isatty()
    if interactive:
        target, backup, repository, git_name, git_email = _interactive_options(args.workspace)
    else:
        target = args.workspace
        backup = "existing" if args.existing else args.storage or "local"
        repository = args.github_repo
        if backup == "github" and repository is None:
            repository = default_github_repository()
        git_name = args.git_name
        git_email = args.git_email
    try:
        if backup == "existing":
            result = connect_existing_workspace(
                target,
                allow_unverified_remote=args.allow_unverified_remote,
            )
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
    elif result.backup == "unverified":
        print("Backup: remote privacy unverified. Resume Builder will not push automatically.")
    else:
        print("Backup: local only. A private remote is recommended to prevent data loss.")
    return 0
