"""Deterministic grounding checks between visible resume claims and cited vault facts."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .layout import VaultLayout
from .validation import parse_frontmatter

NUMBER = re.compile(
    r"(?<![\w])(?:[$€£])?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?:%|x)?(?![\w])",
    re.IGNORECASE,
)
WORD = re.compile(r"[a-z0-9+#.]{3,}", re.IGNORECASE)
STOP_WORDS = {
    "and",
    "for",
    "from",
    "into",
    "the",
    "through",
    "using",
    "with",
    "who",
}

LEADING_WORD = re.compile(r"^\s*([a-z][a-z-]*)", re.IGNORECASE)
LOW_INFORMATION_LEADS = {"used", "utilized", "leveraged"}

# These verbs assert authorship or authority, not merely participation. Keep the
# families intentionally narrow: a fact that says "used" must not support
# "built," and "coordinated" must not silently become "directed."
ASSERTION_VERBS: dict[str, re.Pattern[str]] = {
    "authored": re.compile(r"\b(?:author|authors|authored|authoring)\b", re.IGNORECASE),
    "architected": re.compile(
        r"\b(?:architect|architects|architected|architecting)\b", re.IGNORECASE
    ),
    "built": re.compile(r"\b(?:build|builds|built|building)\b", re.IGNORECASE),
    "commanded": re.compile(r"\b(?:command|commands|commanded|commanding)\b", re.IGNORECASE),
    "created": re.compile(r"\b(?:create|creates|created|creating)\b", re.IGNORECASE),
    "designed": re.compile(r"\b(?:design|designs|designed|designing)\b", re.IGNORECASE),
    "developed": re.compile(r"\b(?:develop|develops|developed|developing)\b", re.IGNORECASE),
    "directed": re.compile(r"\b(?:direct|directs|directed|directing)\b", re.IGNORECASE),
    "established": re.compile(
        r"\b(?:establish|establishes|established|establishing)\b", re.IGNORECASE
    ),
    "founded": re.compile(r"\b(?:found|founds|founded|founding)\b", re.IGNORECASE),
    "implemented": re.compile(
        r"\b(?:implement|implements|implemented|implementing)\b", re.IGNORECASE
    ),
    "invented": re.compile(r"\b(?:invent|invents|invented|inventing)\b", re.IGNORECASE),
    "launched": re.compile(r"\b(?:launch|launches|launched|launching)\b", re.IGNORECASE),
    "led": re.compile(r"\b(?:lead|leads|led|leading)\b", re.IGNORECASE),
    "managed": re.compile(r"\b(?:manage|manages|managed|managing)\b", re.IGNORECASE),
    "orchestrated": re.compile(
        r"\b(?:orchestrate|orchestrates|orchestrated|orchestrating)\b", re.IGNORECASE
    ),
    "oversaw": re.compile(r"\b(?:oversee|oversees|oversaw|overseeing)\b", re.IGNORECASE),
    "owned": re.compile(r"\b(?:own|owns|owned|owning)\b", re.IGNORECASE),
    "spearheaded": re.compile(
        r"\b(?:spearhead|spearheads|spearheaded|spearheading)\b", re.IGNORECASE
    ),
    "supervised": re.compile(r"\b(?:supervise|supervises|supervised|supervising)\b", re.IGNORECASE),
}


@dataclass(frozen=True)
class FactEvidence:
    """Searchable content and review status for one canonical fact."""

    fact_id: str
    content: str
    status: str
    path: str
    sha256: str


def load_fact_evidence(vault_root: Path) -> dict[str, FactEvidence]:
    """Load canonical fact text through the validated vault layout."""
    layout = VaultLayout.load(vault_root)
    facts: dict[str, FactEvidence] = {}
    for path in sorted(layout.facts.rglob("*.md")):
        metadata, body = parse_frontmatter(path)
        fact_id = metadata.get("id")
        if not isinstance(fact_id, str):
            raise ValueError(f"fact has no valid id: {path}")
        searchable = " ".join(
            str(value)
            for value in (metadata.get("title"), metadata.get("organization"), body)
            if value
        )
        facts[fact_id] = FactEvidence(
            fact_id=fact_id,
            content=searchable,
            status=str(metadata.get("status", "")),
            path=layout.relative(path),
            sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        )
    return facts


def claim_blocks(payload: dict[str, Any]) -> list[tuple[str, str, list[str], str | None]]:
    """Return visible factual blocks and the evidence assigned to each block."""
    blocks: list[tuple[str, str, list[str], str | None]] = []

    def add(owner: str, values: list[Any], evidence: Any, story: str | None = None) -> None:
        ids = (
            [item for item in evidence if isinstance(item, str)]
            if isinstance(evidence, list)
            else []
        )
        visible = " ".join(
            str(item).strip() for item in values if isinstance(item, str) and item.strip()
        )
        if visible:
            blocks.append((owner, visible, ids, story))

    candidate = payload.get("candidate")
    if isinstance(candidate, dict):
        add(
            "candidate",
            [candidate.get("name"), candidate.get("headline"), candidate.get("location")],
            candidate.get("evidence"),
        )
    add("summary", [payload.get("summary")], payload.get("summary_evidence"))
    for section in (
        "competencies",
        "experience",
        "projects",
        "education",
        "certifications",
        "skills",
    ):
        items = payload.get(section)
        if not isinstance(items, list):
            continue
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            owner = f"{section}[{index}]"
            if section == "experience":
                add(
                    owner,
                    [item.get(key) for key in ("company", "role", "dates", "location")],
                    item.get("evidence"),
                )
                for bullet_index, bullet in enumerate(item.get("bullets", [])):
                    if isinstance(bullet, dict):
                        add(
                            f"{owner}.bullets[{bullet_index}]",
                            [bullet.get("text")],
                            bullet.get("evidence"),
                            bullet.get("story") if isinstance(bullet.get("story"), str) else None,
                        )
            elif section == "skills":
                add(owner, [item.get("category"), *item.get("items", [])], item.get("evidence"))
            else:
                add(
                    owner,
                    [
                        item.get(key)
                        for key in ("text", "name", "description", "tech", "title", "org", "year")
                    ],
                    item.get("evidence"),
                    item.get("story")
                    if section == "projects" and isinstance(item.get("story"), str)
                    else None,
                )
    return blocks


def normalized_numbers(value: str) -> set[str]:
    """Extract comparable metric and date tokens."""
    return {token.casefold().replace(",", "").lstrip("$€£") for token in NUMBER.findall(value)}


def meaningful_words(value: str) -> set[str]:
    """Extract words useful for a conservative lexical support signal."""
    words = {word.casefold().strip(".") for word in WORD.findall(value)}
    return {word for word in words if word and word not in STOP_WORDS}


def unsupported_assertion_verbs(claim: str, support: str) -> list[str]:
    """Return authorship or authority verbs absent from the cited evidence."""
    return [
        label
        for label, pattern in ASSERTION_VERBS.items()
        if re.search(
            rf"(?:^|[.!?]\s+|;\s+|,\s*then\s+|\band\s+|\bthen\s+){pattern.pattern}",
            claim,
            re.IGNORECASE,
        )
        and not pattern.search(support)
    ]


def audit_claims(
    payload: dict[str, Any],
    vault_root: Path,
    *,
    claim_specs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Reject unsupported numbers and report weak lexical or provisional evidence.

    This gate verifies traceability and exact numeric support. Lexical overlap is
    only a review signal; semantic entailment belongs to the editorial evaluator.
    """
    facts = load_fact_evidence(vault_root)
    warnings: list[str] = []
    reviewed_ids: set[str] = set()
    structured_claims_checked = 0
    for owner, claim, ids, story_id in claim_blocks(payload):
        missing = sorted(set(ids) - facts.keys())
        if missing:
            raise ValueError(f"{owner} cites unknown fact IDs: {missing}")
        cited = [facts[fact_id] for fact_id in ids]
        reviewed_ids.update(ids)
        support = " ".join(fact.content for fact in cited)
        unresolved = sorted(fact.fact_id for fact in cited if fact.status == "needs-review")
        if unresolved:
            raise ValueError(f"{owner} relies on unresolved facts: {unresolved}")
        unsupported = sorted(normalized_numbers(claim) - normalized_numbers(support))
        if unsupported:
            raise ValueError(
                f"{owner} contains numeric claims absent from its cited facts: {unsupported}"
            )
        claim_spec = claim_specs.get(story_id) if claim_specs and story_id else None
        action_support = support
        if claim_spec is not None:
            expected_ids = set(claim_spec.evidence.fact_ids)
            if set(ids) != expected_ids:
                raise ValueError(
                    f"{owner} evidence disagrees with structured claim {story_id}: "
                    f"missing={sorted(expected_ids - set(ids))}, "
                    f"unexpected={sorted(set(ids) - expected_ids)}"
                )
            action_support = " ".join(
                facts[fact_id].content for fact_id in claim_spec.evidence.action
            )
            visible_words = meaningful_words(claim)
            for claim_part, value in (
                ("action", claim_spec.action),
                ("object", claim_spec.object),
                ("scope", claim_spec.scope),
                ("outcome", claim_spec.outcome),
            ):
                if value is None:
                    continue
                planned_words = meaningful_words(value)
                if planned_words and not planned_words & visible_words:
                    raise ValueError(
                        f"{owner} does not express the structured claim {claim_part} "
                        f"for {story_id}: {value!r}"
                    )
            object_tokens = re.findall(r"[a-z0-9]+", claim_spec.object.casefold())
            if {"one", "single"} & set(object_tokens):
                object_nouns = [
                    token
                    for token in object_tokens
                    if token not in {"one", "single", "production", "support", "technical"}
                ]
                pluralized = [
                    noun
                    for noun in object_nouns
                    if re.search(rf"\b{re.escape(noun)}s\b", claim, re.IGNORECASE)
                ]
                if pluralized:
                    raise ValueError(
                        f"{owner} pluralizes a singular structured claim object: {pluralized}"
                    )
            structured_claims_checked += 1
        unsupported_verbs = unsupported_assertion_verbs(claim, action_support)
        if unsupported_verbs:
            raise ValueError(
                f"{owner} claims authorship or authority absent from its cited facts: "
                f"{unsupported_verbs}"
            )
        leading = LEADING_WORD.match(claim)
        if (
            ".bullets[" in owner
            and leading
            and leading.group(1).casefold() in LOW_INFORMATION_LEADS
        ):
            warnings.append(
                f"{owner} starts with low-information verb '{leading.group(1)}'; "
                "lead with the supported contribution or omit the story"
            )
        claim_words = meaningful_words(claim)
        support_words = meaningful_words(support)
        overlap = len(claim_words & support_words) / len(claim_words) if claim_words else 1.0
        if owner != "candidate" and overlap < 0.2:
            warnings.append(
                f"{owner} has low lexical support from its cited facts "
                f"({overlap:.0%}); review wording"
            )
        approximate = sorted(fact.fact_id for fact in cited if fact.status == "approximate")
        if approximate:
            warnings.append(f"{owner} relies on qualified approximate facts: {approximate}")
    return {
        "claims_checked": len(claim_blocks(payload)),
        "fact_ids_checked": len(reviewed_ids),
        "facts": [
            {"id": fact_id, "path": facts[fact_id].path, "sha256": facts[fact_id].sha256}
            for fact_id in sorted(reviewed_ids)
        ],
        "warnings": warnings,
        "method": (
            "deterministic traceability, unresolved-fact exclusion, numeric support, "
            "authorship and authority integrity, and lexical review signals"
        ),
        "semantic_entailment_checked": False,
        "structured_claims_checked": structured_claims_checked,
        "claim_relationships_checked": claim_specs is not None,
    }
