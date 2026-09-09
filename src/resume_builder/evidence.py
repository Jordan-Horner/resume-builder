"""Compatibility facade for canonical-fact evidence audits."""

from .vault.evidence import (
    ASSERTION_VERBS,
    LEADING_WORD,
    LOW_INFORMATION_LEADS,
    NUMBER,
    STOP_WORDS,
    WORD,
    FactEvidence,
    audit_claims,
    claim_blocks,
    load_fact_evidence,
    meaningful_words,
    normalized_numbers,
    unsupported_assertion_verbs,
)

__all__ = [
    "ASSERTION_VERBS",
    "LEADING_WORD",
    "LOW_INFORMATION_LEADS",
    "NUMBER",
    "STOP_WORDS",
    "WORD",
    "FactEvidence",
    "audit_claims",
    "claim_blocks",
    "load_fact_evidence",
    "meaningful_words",
    "normalized_numbers",
    "unsupported_assertion_verbs",
]
