"""Compatibility facade for prioritized career-evidence questions."""

from .vault.questions import (
    GAP_KEY,
    GAP_TYPES,
    GENERIC_PROMPTS,
    RESOLUTIONS,
    SOURCE_ID,
    open_questions,
    question_plan,
    resolve_question,
)

__all__ = [
    "GAP_KEY",
    "GAP_TYPES",
    "GENERIC_PROMPTS",
    "RESOLUTIONS",
    "SOURCE_ID",
    "open_questions",
    "question_plan",
    "resolve_question",
]
