"""Compatibility facade for resume regression evaluations."""

from .quality_assurance.regression import (
    DIMENSIONS,
    _compiled_selection,
    _fact_sources,
    _generated_output,
    _review,
    _source_entry,
    _strings,
    grade_case,
    load_case,
    main,
)

__all__ = [
    "DIMENSIONS",
    "_compiled_selection",
    "_fact_sources",
    "_generated_output",
    "_review",
    "_source_entry",
    "_strings",
    "grade_case",
    "load_case",
    "main",
]
