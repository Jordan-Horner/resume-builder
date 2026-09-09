"""Compatibility facade for role-profile terminology diagnostics."""

from .role_profiles.diagnostics import (
    direction_style_diagnostics,
    normalize_phrase,
    phrase_present,
)

__all__ = ["direction_style_diagnostics", "normalize_phrase", "phrase_present"]
