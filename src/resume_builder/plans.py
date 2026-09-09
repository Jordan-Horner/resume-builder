"""Compatibility facade for approved career-vault change plans."""

from .vault.change_plans import (
    LayoutError,
    PlannedWrite,
    VaultChangePlan,
    VaultLayout,
    affected_references,
    apply_plan,
    file_sha256,
    load_plan,
    main,
    plan_summary,
    validate_staged_plan,
)

__all__ = [
    "LayoutError",
    "PlannedWrite",
    "VaultChangePlan",
    "VaultLayout",
    "affected_references",
    "apply_plan",
    "file_sha256",
    "load_plan",
    "main",
    "plan_summary",
    "validate_staged_plan",
]
