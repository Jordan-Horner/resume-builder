"""Compatibility facade for resume template and theme selection."""

from .construction.templates import (
    LEGACY_SECTION_PLACEHOLDERS,
    THEME_CSS_PLACEHOLDER,
    THEME_KINDS,
    THEME_REQUIRED_PLACEHOLDERS,
    THEME_STYLE_PLACEHOLDERS,
    load_content_template,
    load_rendering_theme,
    rendering_theme_text,
    scaffold_template,
    select_catalog_item,
    template_catalog,
)

__all__ = [
    "LEGACY_SECTION_PLACEHOLDERS",
    "THEME_CSS_PLACEHOLDER",
    "THEME_KINDS",
    "THEME_REQUIRED_PLACEHOLDERS",
    "THEME_STYLE_PLACEHOLDERS",
    "load_content_template",
    "load_rendering_theme",
    "rendering_theme_text",
    "scaffold_template",
    "select_catalog_item",
    "template_catalog",
]
