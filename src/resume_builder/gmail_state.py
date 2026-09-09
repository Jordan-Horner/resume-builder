"""Compatibility facade for content-free Gmail runtime state."""

from .gmail_integration.state import (
    CLASSIFIER_VERSION,
    GmailMessage,
    GmailRuntimeState,
    sender_domain_hash,
)

__all__ = [
    "CLASSIFIER_VERSION",
    "GmailMessage",
    "GmailRuntimeState",
    "sender_domain_hash",
]
