"""Compatibility facade for semantic match grading."""

from .matching.grading import (
    CASE_FIELDS,
    IMPORTANCE,
    JUDGMENT_FIELDS,
    MATCH_LABELS,
    REQUIREMENT_TYPES,
    STATUSES,
    SUFFICIENCY,
    classify_match,
    load_classification_case,
    validate_against_match,
    validate_classification_case,
)

__all__ = [
    "CASE_FIELDS",
    "IMPORTANCE",
    "JUDGMENT_FIELDS",
    "MATCH_LABELS",
    "REQUIREMENT_TYPES",
    "STATUSES",
    "SUFFICIENCY",
    "classify_match",
    "load_classification_case",
    "validate_against_match",
    "validate_classification_case",
]
