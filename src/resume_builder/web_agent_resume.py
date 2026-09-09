"""Compatibility facade for portal résumé editing."""

from .portal.resume_editing import (
    LanguageBlock,
    LanguageDecisions,
    WordingCheck,
    apply_wording,
    digest,
    read_resume,
    replacement_source,
    resume_path,
)

__all__ = [
    "LanguageBlock",
    "LanguageDecisions",
    "WordingCheck",
    "apply_wording",
    "digest",
    "read_resume",
    "replacement_source",
    "resume_path",
]
