"""Compatibility facade for reviewed resume preview publication."""

from .publishing.preview import (
    APPROVED_NOTICE,
    ATTENTION_NOTICE,
    PRESENTATION_POLICY,
    PREVIEW_MODE,
    _current_build,
    _current_career_review,
    _handoff_presentation,
    _job_context,
    _match_feedback,
    _render_handoff_markdown,
    _require_resolved_role_balance,
    main,
    preview_resume,
)

__all__ = [
    "APPROVED_NOTICE",
    "ATTENTION_NOTICE",
    "PRESENTATION_POLICY",
    "PREVIEW_MODE",
    "_current_build",
    "_current_career_review",
    "_handoff_presentation",
    "_job_context",
    "_match_feedback",
    "_render_handoff_markdown",
    "_require_resolved_role_balance",
    "main",
    "preview_resume",
]
