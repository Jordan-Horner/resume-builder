"""Compatibility facade for project-wide readiness reporting."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .project_status import report as _report

_build_status = _report._build_status
_initial_draft_readiness = _report._initial_draft_readiness
_match_status = _report._match_status
_mint_status = _report._mint_status
_next_action = _report._next_action
_onboarding_status = _report._onboarding_status
_preview_status = _report._preview_status
_resume_records = _report._resume_records
_review_status = _report._review_status
_slugify = _report._slugify
_status = _report._status
_target_records = _report._target_records
format_summary = _report.format_summary
main = _report.main
validate_vault = _report.validate_vault


def project_report(vault_root: Path, *, strict: bool = False) -> dict[str, Any]:
    """Build the report while preserving legacy dependency monkeypatching."""
    _report.validate_vault = validate_vault
    return _report.project_report(vault_root, strict=strict)


__all__ = [
    "_build_status",
    "_initial_draft_readiness",
    "_match_status",
    "_mint_status",
    "_next_action",
    "_onboarding_status",
    "_preview_status",
    "_resume_records",
    "_review_status",
    "_slugify",
    "_status",
    "_target_records",
    "format_summary",
    "main",
    "project_report",
    "validate_vault",
]
