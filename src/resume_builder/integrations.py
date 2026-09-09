"""Compatibility facade for optional workspace integration guidance."""

from .workspace_management.integrations import (
    INTEGRATION_CHOICES,
    integration_setup_guide,
    interactive_integration_setup,
    parse_integration_choices,
)

__all__ = [
    "INTEGRATION_CHOICES",
    "integration_setup_guide",
    "interactive_integration_setup",
    "parse_integration_choices",
]
