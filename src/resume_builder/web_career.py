"""Compatibility facade for portal résumé-library operations."""

from .portal.career import (
    _all_evidence_ids,
    _direction_label,
    _display_name,
    _headline_parts,
    _preview_url,
    _render_portal_preview,
    _without_workflow_notice,
    archive_directional_resume,
    directional_resume_removal_impact,
    list_resumes,
    resolve_application_resume_preview,
    resolve_directional_resume_reference,
    resolve_resume_preview,
    resolve_retired_resume_reference,
    restore_directional_resume,
)

__all__ = [
    "_all_evidence_ids",
    "_direction_label",
    "_display_name",
    "_headline_parts",
    "_preview_url",
    "_render_portal_preview",
    "_without_workflow_notice",
    "archive_directional_resume",
    "directional_resume_removal_impact",
    "list_resumes",
    "resolve_application_resume_preview",
    "resolve_directional_resume_reference",
    "resolve_resume_preview",
    "resolve_retired_resume_reference",
    "restore_directional_resume",
]
