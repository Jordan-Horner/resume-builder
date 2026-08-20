"""Pure terminology and style diagnostics for direction profiles."""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

from .direction_schema import (
    COPIED_LABEL_MIN_COVERAGE,
    STYLE_MIN_CLAIM_BLOCKS,
    STYLE_MIN_TERM_OCCURRENCES,
    STYLE_MIN_WORD_SHARE,
    STYLE_TOKEN_EXCLUSIONS,
    nonempty_string,
    string_list,
)
from .rendering import object_value


def normalize_phrase(value: str) -> str:
    """Normalize prose for deterministic multi-word terminology matching."""
    tokens = (token.strip(".") for token in re.findall(r"[a-z0-9+#.]+", value.casefold()))
    return " ".join(token for token in tokens if token)


def phrase_present(term: str, normalized_text: str) -> bool:
    """Match a normalized term on token boundaries rather than substrings."""
    normalized_term = normalize_phrase(term)
    return bool(normalized_term) and f" {normalized_term} " in f" {normalized_text} "


def direction_style_diagnostics(
    profile: dict[str, Any], blocks: list[tuple[str, str, list[str], str | None]]
) -> dict[str, Any]:
    """Report role-profile echo as editorial advice without rejecting the resume."""
    block_tokens = {owner: normalize_phrase(claim).split() for owner, claim, _, _ in blocks}
    all_tokens = [token for tokens in block_tokens.values() for token in tokens]
    token_counts = Counter(all_tokens)
    configured_tokens: set[str] = set()
    concepts = profile["priority_concepts"]
    assert isinstance(concepts, list)
    for raw_concept in concepts:
        concept = object_value(raw_concept, "priority concept")
        for term in string_list(concept["terms"], "terms"):
            configured_tokens.update(normalize_phrase(term).split())

    concentrated: list[dict[str, Any]] = []
    token_total = len(all_tokens)
    for token in sorted(configured_tokens):
        if len(token) < 5 or token in STYLE_TOKEN_EXCLUSIONS:
            continue
        count = token_counts[token]
        owners = sorted(owner for owner, tokens in block_tokens.items() if token in tokens)
        share = count / token_total if token_total else 0.0
        if (
            count >= STYLE_MIN_TERM_OCCURRENCES
            and len(owners) >= STYLE_MIN_CLAIM_BLOCKS
            and share >= STYLE_MIN_WORD_SHARE
        ):
            concentrated.append(
                {
                    "term": token,
                    "occurrences": count,
                    "claim_blocks": len(owners),
                    "word_share": round(share, 3),
                }
            )

    competency_blocks = [
        (owner, claim) for owner, claim, _, _ in blocks if owner.startswith("competencies[")
    ]
    copied_labels: list[dict[str, str]] = []
    for raw_concept in concepts:
        concept = object_value(raw_concept, "priority concept")
        label = nonempty_string(concept["label"], "concept label")
        label_tokens = {
            token for token in normalize_phrase(label).split() if token not in {"and", "or", "the"}
        }
        if not label_tokens:
            continue
        for owner, claim in competency_blocks:
            claim_tokens = {
                token
                for token in normalize_phrase(claim).split()
                if token not in {"and", "or", "the"}
            }
            overlap = len(label_tokens & claim_tokens) / len(label_tokens)
            if overlap >= COPIED_LABEL_MIN_COVERAGE:
                copied_labels.append(
                    {
                        "concept_id": str(concept["id"]),
                        "concept_label": label,
                        "owner": owner,
                    }
                )

    return {
        "advisory_only": True,
        "target_term_concentration": concentrated,
        "copied_concept_labels": copied_labels,
    }
