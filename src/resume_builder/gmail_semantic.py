"""Compatibility facade for semantic application-email classification."""

from .application_tracking.email_classification import (
    ACTIONABLE_EVENT_TYPES,
    MAX_SEMANTIC_BODY_CHARS,
    SemanticEmailClassifier,
    SemanticEventType,
    SemanticLifecycleDecision,
    SemanticLifecycleOutcome,
    minimize_message,
)

__all__ = [
    "ACTIONABLE_EVENT_TYPES",
    "MAX_SEMANTIC_BODY_CHARS",
    "SemanticEmailClassifier",
    "SemanticEventType",
    "SemanticLifecycleDecision",
    "SemanticLifecycleOutcome",
    "minimize_message",
]
