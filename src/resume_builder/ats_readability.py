"""Compatibility facade for deterministic ATS readability checks."""

from .document_export.readability import (
    MAX_RECOMMENDED_BYTES,
    REPORT_VERSION,
    SECTION_TITLES,
    ReadabilityCheck,
    build_ats_readability_report,
)

__all__ = [
    "MAX_RECOMMENDED_BYTES",
    "REPORT_VERSION",
    "SECTION_TITLES",
    "ReadabilityCheck",
    "build_ats_readability_report",
]
