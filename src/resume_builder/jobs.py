"""Compatibility facade for the opportunity inventory command."""

from .opportunities.cli import (
    DEFAULT_CONFIG,
    DEFAULT_LATEST_REFRESH,
    DEFAULT_NEW_OUTPUT,
    DEFAULT_NEW_REVIEW_OUTPUT,
    DEFAULT_OUTPUT,
    DEFAULT_PREFERENCES,
    DEFAULT_PROVIDER_COMPARISON,
    DEFAULT_REVIEW_OUTPUT,
    get_job_screening_packet,
    main,
    parser,
)

__all__ = [
    "DEFAULT_CONFIG",
    "DEFAULT_LATEST_REFRESH",
    "DEFAULT_NEW_OUTPUT",
    "DEFAULT_NEW_REVIEW_OUTPUT",
    "DEFAULT_OUTPUT",
    "DEFAULT_PREFERENCES",
    "DEFAULT_PROVIDER_COMPARISON",
    "DEFAULT_REVIEW_OUTPUT",
    "get_job_screening_packet",
    "main",
    "parser",
]
