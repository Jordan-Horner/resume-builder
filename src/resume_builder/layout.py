"""Compatibility facade for containment-safe career-vault paths."""

from .vault.layout import (
    DEFAULT_CONFIG,
    SCHEMA_VERSION,
    LayoutError,
    VaultLayout,
    contained_path,
    load_json_object,
    relative_path,
)

__all__ = [
    "DEFAULT_CONFIG",
    "SCHEMA_VERSION",
    "LayoutError",
    "VaultLayout",
    "contained_path",
    "load_json_object",
    "relative_path",
]
