"""Compatibility facade for packaged private-workspace resources."""

from .workspace_management.templates import (
    sync_templates,
    template_resources,
    write_workspace_files,
)

__all__ = ["sync_templates", "template_resources", "write_workspace_files"]
