"""Compatibility facade for hardened PDF rendering and verification."""

from .document_export.pdf import (
    BAD_GLYPHS,
    audit_pdf,
    extraction_blocks,
    normalized_tokens,
    render_pdf,
    tokens_recovered,
)

__all__ = [
    "BAD_GLYPHS",
    "audit_pdf",
    "extraction_blocks",
    "normalized_tokens",
    "render_pdf",
    "tokens_recovered",
]
