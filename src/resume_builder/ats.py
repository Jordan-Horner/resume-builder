"""Normalize resume text away from characters that commonly confuse ATS parsers."""

from __future__ import annotations

from collections import Counter
from typing import Any

REPLACEMENTS = {
    "\u2010": "-",
    "\u2011": "-",
    "\u2012": "-",
    "\u2013": "-",
    "\u2014": "-",
    "\u2018": "'",
    "\u2019": "'",
    "\u201c": '"',
    "\u201d": '"',
    "\u2026": "...",
    "\u00a0": " ",
    "\u200b": "",
    "\u200c": "",
    "\u200d": "",
    "\ufeff": "",
    "\u2192": "->",
    "\u2022": "-",
    "\u00b7": "-",
    "\u20ac": "EUR ",
    "\u00a3": "GBP ",
}


def normalize_text(value: str, counts: Counter[str] | None = None) -> str:
    """Return ATS-safe text and optionally count each replaced character."""
    normalized = value
    for source, replacement in REPLACEMENTS.items():
        occurrences = normalized.count(source)
        if occurrences:
            if counts is not None:
                counts[f"U+{ord(source):04X}"] += occurrences
            normalized = normalized.replace(source, replacement)
    return normalized


def normalize_payload(payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, int]]:
    """Recursively normalize human-facing strings while preserving URLs and email addresses."""
    counts: Counter[str] = Counter()

    def visit(value: Any, key: str = "") -> Any:
        if isinstance(value, dict):
            return {item_key: visit(item, item_key) for item_key, item in value.items()}
        if isinstance(value, list):
            return [visit(item, key) for item in value]
        if isinstance(value, str) and key not in {"url", "email"}:
            return normalize_text(value, counts)
        return value

    normalized = visit(payload)
    assert isinstance(normalized, dict)
    return normalized, dict(sorted(counts.items()))
