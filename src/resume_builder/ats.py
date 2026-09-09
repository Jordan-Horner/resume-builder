"""Compatibility facade for ATS-safe resume text normalization."""

from .document_export.normalization import REPLACEMENTS, normalize_payload, normalize_text

__all__ = ["REPLACEMENTS", "normalize_payload", "normalize_text"]
