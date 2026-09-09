"""Compatibility facade for portal inventory filters."""

from .portal.filters import FilterTerm, ViewFilters, matches_view

__all__ = ["FilterTerm", "ViewFilters", "matches_view"]
