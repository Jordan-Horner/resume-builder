"""Explainable, non-hiding shadow personalization for job screening queues."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any

TOKEN = re.compile(r"[a-z][a-z0-9+#.]{2,}")
STOPWORDS = {
    "and",
    "engineer",
    "for",
    "job",
    "remote",
    "role",
    "senior",
    "the",
    "with",
}


@dataclass(frozen=True)
class ShadowRankingSettings:
    enabled: bool = True
    exploration_fraction: float = 0.15


def load_shadow_settings(preferences: dict[str, Any]) -> ShadowRankingSettings:
    raw = preferences.get("personalization") or {}
    if not isinstance(raw, dict):
        raise ValueError("personalization must be a mapping")
    unknown = set(raw) - {"enabled", "mode", "exploration_fraction"}
    if unknown:
        raise ValueError(f"unknown personalization fields: {', '.join(sorted(unknown))}")
    if raw.get("mode", "shadow") != "shadow":
        raise ValueError("personalization mode must be shadow")
    enabled = raw.get("enabled", True)
    fraction = raw.get("exploration_fraction", 0.15)
    if not isinstance(enabled, bool):
        raise ValueError("personalization.enabled must be true or false")
    if not isinstance(fraction, (int, float)) or isinstance(fraction, bool):
        raise ValueError("personalization.exploration_fraction must be a number")
    if not 0 <= float(fraction) <= 0.5:
        raise ValueError("personalization.exploration_fraction must be from 0 to 0.5")
    return ShadowRankingSettings(enabled=enabled, exploration_fraction=float(fraction))


def _tokens(value: str) -> set[str]:
    return {token for token in TOKEN.findall(value.casefold()) if token not in STOPWORDS}


def _positive_similarity(title: str, positive_titles: list[str]) -> float:
    title_terms = _tokens(title)
    if not title_terms:
        return 0.0
    best = 0.0
    for positive in positive_titles:
        terms = _tokens(positive)
        if not terms:
            continue
        best = max(best, len(title_terms & terms) / len(title_terms | terms))
    return best


def _semantic_score(item: dict[str, Any]) -> tuple[float, list[str]]:
    screen = item.get("screening")
    if not isinstance(screen, dict) or screen.get("status") != "complete":
        return 0.25, ["Semantic fit has not been evaluated."]
    result = screen.get("result")
    if not isinstance(result, dict):
        return 0.25, ["Semantic fit result is unavailable."]
    recommendation = str(result.get("recommendation"))
    fit = str(result.get("fit"))
    bases = {
        "strong_match": 0.78,
        "good_match": 0.68,
        "worthwhile_stretch": 0.60,
        "insufficient_information": 0.35,
        "weak_fit": 0.22,
    }
    score = bases.get(fit, 0.30)
    reasons = [f"Semantic fit is {fit.replace('_', ' ')}."]
    if recommendation == "verify_eligibility":
        score = min(score, 0.42)
        reasons.append("Eligibility still needs verification.")
    elif recommendation == "do_not_apply":
        score = 0.0
        reasons.append("Explicit evidence indicates a required eligibility conflict.")
    return score, reasons


def score_shadow_job(item: dict[str, Any], *, positive_titles: list[str]) -> dict[str, Any]:
    """Score one visible job without changing eligibility or queue membership."""
    score, reasons = _semantic_score(item)
    deterministic = item.get("deterministic")
    if isinstance(deterministic, dict):
        interest = deterministic.get("interest")
        if isinstance(interest, dict):
            desired = interest.get("desired_title_terms") or []
            interesting = interest.get("interest_terms") or []
            if desired:
                score += 0.08
                reasons.append("The title matches an explicit desired-title term.")
            if interesting:
                score += 0.05
                reasons.append("The posting matches an explicit interest term.")
        conflicts = deterministic.get("hard_conflicts") or []
        if conflicts:
            score = max(0.0, score - 0.35)
            reasons.append("Deterministic preferences contain a required conflict warning.")
    similarity = _positive_similarity(str(item.get("title") or ""), positive_titles)
    if similarity:
        score += 0.12 * similarity
        reasons.append("The title resembles a previously applied-to role.")
    return {
        "score": round(min(1.0, max(0.0, score)), 3),
        "confidence": (
            str(item.get("screening", {}).get("result", {}).get("confidence") or "unknown")
        ),
        "reasons": reasons[:4],
        "learning_sources": {
            "explicit_preferences": True,
            "positive_applications": bool(positive_titles),
            "ignored_jobs_used_as_negative": False,
            "not_interested_without_reason_used_as_rule": False,
        },
    }


def _exploration_order(
    ranked: list[dict[str, Any]], fraction: float
) -> tuple[list[dict[str, Any]], set[str]]:
    if fraction <= 0 or len(ranked) < 3:
        return ranked, set()
    candidates = []
    for item in ranked[1:]:
        result = item.get("screening", {}).get("result", {})
        conflicts = item.get("deterministic", {}).get("hard_conflicts", [])
        if result.get("recommendation") != "do_not_apply" and not conflicts:
            candidates.append(item)
    if not candidates:
        return ranked, set()
    count = min(len(candidates), max(1, math.floor(len(ranked) * fraction)))
    exploratory = candidates[-count:]
    exploratory_ids = {str(item.get("id") or "") for item in exploratory}
    primary = [item for item in ranked if str(item.get("id") or "") not in exploratory_ids]
    interval = max(2, round(1 / fraction))
    output = list(primary)
    for offset, item in enumerate(exploratory):
        position = min(len(output), interval * (offset + 1) - 1)
        output.insert(position, item)
    return output, exploratory_ids


def build_shadow_order(
    items: list[dict[str, Any]],
    *,
    preferences: dict[str, Any],
    positive_titles: list[str],
) -> tuple[list[str], dict[str, dict[str, Any]]]:
    """Return an advisory order containing every active job exactly once."""
    settings = load_shadow_settings(preferences)
    active = [item for item in items if item.get("active") is True]
    scores = {
        str(item.get("id") or ""): score_shadow_job(item, positive_titles=positive_titles)
        for item in active
    }
    if not settings.enabled:
        return [str(item.get("id") or "") for item in active], scores
    ranked = sorted(
        active,
        key=lambda item: (
            -float(scores[str(item.get("id") or "")]["score"]),
            int(item.get("source_order") or 0),
        ),
    )
    ordered, exploratory_ids = _exploration_order(ranked, settings.exploration_fraction)
    for job_id in exploratory_ids:
        scores[job_id]["exploration_slot"] = True
        scores[job_id]["reasons"].append(
            "Included as an exploration result to limit preference-filter narrowing."
        )
    return [str(item.get("id") or "") for item in ordered], scores
