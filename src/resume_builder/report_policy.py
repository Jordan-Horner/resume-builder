"""Compatibility facade for project-readiness routing policy."""

from .project_status.policy import (
    _initial_draft_readiness,
    _next_action,
    _onboarding_status,
)

__all__ = ["_initial_draft_readiness", "_next_action", "_onboarding_status"]
