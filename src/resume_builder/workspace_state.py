"""Compatibility facade for private workspace inspection."""

from .workspace_management.state import (
    DEFAULT_VAULT_REPOSITORY_NAME,
    DEFAULT_WORKSPACE,
    GITHUB_OWNER,
    GITHUB_REMOTES,
    GITHUB_REPOSITORY,
    WORKSPACE_CONFIG,
    WORKSPACE_VERSION,
    CommandResult,
    Runner,
    WorkspaceError,
    WorkspaceInitResult,
    default_github_repository,
    discover_workspace,
    github_repository_from_remote,
    run_command,
    workspace_status,
)

__all__ = [
    "DEFAULT_VAULT_REPOSITORY_NAME",
    "DEFAULT_WORKSPACE",
    "GITHUB_OWNER",
    "GITHUB_REMOTES",
    "GITHUB_REPOSITORY",
    "WORKSPACE_CONFIG",
    "WORKSPACE_VERSION",
    "CommandResult",
    "Runner",
    "WorkspaceError",
    "WorkspaceInitResult",
    "default_github_repository",
    "discover_workspace",
    "github_repository_from_remote",
    "run_command",
    "workspace_status",
]
