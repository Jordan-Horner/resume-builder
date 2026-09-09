"""Compatibility facade for portal update checks."""

from .portal.updates import API_URL, RELEASE_URL, REPOSITORY, UpdateChecker

__all__ = ["API_URL", "RELEASE_URL", "REPOSITORY", "UpdateChecker"]
