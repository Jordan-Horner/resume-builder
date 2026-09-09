"""Compatibility facade for private workspace setup and discovery."""

from .workspace_management.setup import (
    CommandResult,
    WorkspaceError,
    WorkspaceInitResult,
    connect_existing_workspace,
    default_github_repository,
    discover_workspace,
    github_repository_from_remote,
    initialize_workspace,
    main,
    run_command,
    status_main,
    sync_workspace_templates,
    workspace_status,
)

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
