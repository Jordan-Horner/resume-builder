"""Compatibility facade for resume workflow verification."""

from .publishing.verification import (
    _cached_receipt,
    _load_json,
    _optional_path_record,
    _path_record,
    _preview_freshness,
    _record_freshness,
    build_manifest_freshness,
    main,
    verify_resume,
    workflow_state,
)

__all__ = [
    "_cached_receipt",
    "_load_json",
    "_optional_path_record",
    "_path_record",
    "_preview_freshness",
    "_record_freshness",
    "build_manifest_freshness",
    "main",
    "verify_resume",
    "workflow_state",
]
