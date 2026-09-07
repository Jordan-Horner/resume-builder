"""Explainable, non-hiding shadow personalization for job screening queues."""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
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
TRAIT_PATTERNS = {
    "customer_facing": re.compile(
        r"\b(?:customer-facing|client-facing|work with customers)\b", re.I
    ),
    "on_call": re.compile(r"\b(?:on[ -]?call|24/7 rotation)\b", re.I),
    "phone_support": re.compile(
        r"\b(?:phone support|phone calls?|call center|inbound calls?|call volume)\b", re.I
    ),
    "travel": re.compile(r"\b(?:travel required|travel up to|% travel)\b", re.I),
}
LEARNABLE_TRAITS = frozenset(TRAIT_PATTERNS)
SENIORITY_PATTERNS = (
    ("management", re.compile(r"\b(?:manager|director|vice president|vp)\b", re.I)),
    ("principal", re.compile(r"\bprincipal\b", re.I)),
    ("staff", re.compile(r"\bstaff\b", re.I)),
    ("senior", re.compile(r"\b(?:senior|sr\.?)\b", re.I)),
    ("intern", re.compile(r"\bintern(?:ship)?\b", re.I)),
    ("new_grad", re.compile(r"\b(?:new grad(?:uate)?|campus hire|graduate)\b", re.I)),
    ("entry", re.compile(r"\b(?:entry[ -]level|junior|jr\.?)\b", re.I)),
)
DESCRIPTION_SENIORITY_PATTERNS = (
    ("new_grad", re.compile(r"\b(?:recent graduate|new graduate|campus hire)\b", re.I)),
    ("entry", re.compile(r"\bentry[ -]level (?:position|role|opportunity)\b", re.I)),
)
LEARNABLE_SENIORITIES = frozenset({"intern", "new_grad", "entry", "senior", "staff", "principal"})
ROLE_STOPWORDS = STOPWORDS | {
    "entry",
    "grad",
    "graduate",
    "intern",
    "internship",
    "junior",
    "level",
    "new",
    "principal",
    "staff",
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


def extract_preference_traits(job: dict[str, Any]) -> list[str]:
    """Extract only preference traits that can be recognized without another model call."""
    text = "\n".join(
        str(job.get(key) or "") for key in ("title", "description", "description_text")
    )
    return sorted(name for name, pattern in TRAIT_PATTERNS.items() if pattern.search(text))


def extract_seniority(job: dict[str, Any]) -> str:
    """Classify only explicit seniority language without a model call."""
    title = str(job.get("title") or "")
    for level, pattern in SENIORITY_PATTERNS:
        if pattern.search(title):
            return level
    description = "\n".join(str(job.get(key) or "") for key in ("description", "description_text"))
    for level, pattern in DESCRIPTION_SENIORITY_PATTERNS:
        if pattern.search(description):
            return level
    return "unknown"


def load_feedback_events(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"invalid job feedback: {path}") from exc
    events = payload.get("events") if isinstance(payload, dict) else None
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != 1
        or not isinstance(events, list)
    ):
        raise ValueError(f"invalid job feedback: {path}")
    if any(not isinstance(event, dict) for event in events):
        raise ValueError(f"invalid job feedback: {path}")
    return events


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


def _terms_similarity(left: str, right: str) -> float:
    left_terms = _tokens(left)
    right_terms = _tokens(right)
    return (
        len(left_terms & right_terms) / len(left_terms | right_terms)
        if left_terms and right_terms
        else 0.0
    )


def _role_similarity(left: str, right: str) -> float:
    left_terms = {token for token in _tokens(left) if token not in ROLE_STOPWORDS}
    right_terms = {token for token in _tokens(right) if token not in ROLE_STOPWORDS}
    return (
        len(left_terms & right_terms) / len(left_terms | right_terms)
        if left_terms and right_terms
        else 0.0
    )


def _screening_criteria(item: dict[str, Any]) -> str:
    screen = item.get("screening")
    result = screen.get("result") if isinstance(screen, dict) else None
    criteria = result.get("criterion_evidence") if isinstance(result, dict) else None
    if not isinstance(criteria, list):
        return ""
    return " ".join(
        str(criterion.get("label") or "") for criterion in criteria if isinstance(criterion, dict)
    )


def _positive_event_affinity(item: dict[str, Any], event: dict[str, Any]) -> float:
    weights = {"opened_posting": 0.04, "interested": 0.09, "applied": 0.14}
    weight = weights.get(str(event.get("action")))
    snapshot = event.get("job")
    if weight is None or not isinstance(snapshot, dict):
        return 0.0
    title_similarity = _terms_similarity(
        str(item.get("title") or ""), str(snapshot.get("title") or "")
    )
    current_criteria = _screening_criteria(item)
    prior_screen = snapshot.get("screening")
    prior_criteria = prior_screen.get("criteria") if isinstance(prior_screen, dict) else None
    prior_labels = (
        " ".join(
            str(criterion.get("label") or "")
            for criterion in prior_criteria
            if isinstance(criterion, dict)
        )
        if isinstance(prior_criteria, list)
        else ""
    )
    if current_criteria and prior_labels:
        similarity = 0.3 * title_similarity + 0.7 * _terms_similarity(
            current_criteria, prior_labels
        )
    else:
        similarity = title_similarity
    return weight * similarity


def _positive_pattern_matches(item: dict[str, Any], events: list[dict[str, Any]]) -> int:
    """Count distinct positive jobs that match role, level, and available duties."""
    title = str(item.get("title") or "")
    seniority = extract_seniority(item)
    criteria = _screening_criteria(item)
    matches = 0
    for event in events:
        if event.get("action") not in {"interested", "applied"}:
            continue
        snapshot = event.get("job")
        if not isinstance(snapshot, dict) or snapshot.get("id") == item.get("id"):
            continue
        role_similarity = _role_similarity(title, str(snapshot.get("title") or ""))
        if role_similarity < 0.5:
            continue
        saved_seniority = str(snapshot.get("seniority") or "unknown")
        if seniority != "unknown" and saved_seniority != "unknown" and seniority != saved_seniority:
            continue
        prior_screen = snapshot.get("screening")
        prior_criteria = prior_screen.get("criteria") if isinstance(prior_screen, dict) else None
        prior_labels = (
            " ".join(
                str(criterion.get("label") or "")
                for criterion in prior_criteria
                if isinstance(criterion, dict)
            )
            if isinstance(prior_criteria, list)
            else ""
        )
        if criteria or prior_labels:
            if not criteria or not prior_labels:
                continue
            if _terms_similarity(criteria, prior_labels) < 0.25:
                continue
        elif role_similarity < 0.67:
            continue
        matches += 1
    return matches


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


def _level(score: float, *, positive: str = "High") -> str:
    if score >= 0.7:
        return positive
    if score < 0.4:
        return "Low"
    return "Neutral"


def score_shadow_job(
    item: dict[str, Any],
    *,
    positive_titles: list[str],
    clearance_preference: str = "neutral",
    feedback_events: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Score one visible job without changing eligibility or queue membership."""
    fit_score, reasons = _semantic_score(item)
    interest_score = 0.5
    company_score = 0.5
    deterministic = item.get("deterministic")
    if isinstance(deterministic, dict):
        interest = deterministic.get("interest")
        if isinstance(interest, dict):
            desired = interest.get("desired_title_terms") or []
            interesting = interest.get("interest_terms") or []
            if desired:
                interest_score += 0.15
                reasons.append("The title matches an explicit desired-title term.")
            if interesting:
                interest_score += 0.10
                reasons.append("The posting matches an explicit interest term.")
            preferred_attributes = interest.get("preferred_job_attributes") or []
            avoided_attributes = interest.get("avoided_job_attributes") or []
            if preferred_attributes:
                interest_score += min(0.12, 0.04 * len(preferred_attributes))
                reasons.append("The posting explicitly matches work you prefer.")
            if avoided_attributes:
                interest_score -= min(0.18, 0.06 * len(avoided_attributes))
                reasons.append("The posting explicitly matches work you prefer to avoid.")
        conflicts = deterministic.get("hard_conflicts") or []
        if conflicts:
            fit_score = max(0.0, fit_score - 0.35)
            reasons.append("Deterministic preferences contain a required conflict warning.")
        if clearance_preference == "prefer" and deterministic.get("clearance_requirement"):
            interest_score += 0.05
            reasons.append("The role matches the explicit preference for clearance work.")
    similarity = _positive_similarity(str(item.get("title") or ""), positive_titles)
    if similarity:
        interest_score += 0.15 * similarity
        reasons.append("The title resembles a previously applied-to role.")
    events_by_job: dict[str, dict[str, Any]] = {}
    for event in feedback_events or []:
        snapshot = event.get("job")
        if isinstance(snapshot, dict) and snapshot.get("id"):
            events_by_job[str(snapshot["id"])] = event
    current_id = str(item.get("id") or "")
    current_company = str(item.get("company") or "").strip().casefold()
    current_traits = set(item.get("preference_traits") or [])
    current_seniority = extract_seniority(item)
    negative_same_level = 0
    positive_same_level = 0
    positive_other_level = 0
    seniority_rule_applied = False
    if current_seniority in LEARNABLE_SENIORITIES:
        for event in events_by_job.values():
            snapshot = event.get("job")
            if (
                not isinstance(snapshot, dict)
                or _role_similarity(str(item.get("title") or ""), str(snapshot.get("title") or ""))
                < 0.5
            ):
                continue
            saved_seniority = snapshot.get("seniority")
            event_seniority = (
                saved_seniority
                if isinstance(saved_seniority, str) and saved_seniority in LEARNABLE_SENIORITIES
                else extract_seniority(snapshot)
            )
            if event_seniority not in LEARNABLE_SENIORITIES:
                continue
            action = event.get("action")
            if action == "not_interested" and event_seniority == current_seniority:
                negative_same_level += 1
            elif action in {"interested", "applied"}:
                if event_seniority == current_seniority:
                    positive_same_level += 1
                else:
                    positive_other_level += 1
        if (
            negative_same_level >= 3
            and negative_same_level >= positive_same_level + 2
            and positive_other_level >= 1
        ):
            interest_score -= 0.12
            seniority_rule_applied = True
            reasons.insert(0, "You tend to pursue other levels of similar roles.")
    seniority_pattern = {
        "level": current_seniority,
        "negative_same_level": negative_same_level,
        "positive_same_level": positive_same_level,
        "positive_other_level": positive_other_level,
        "applied": seniority_rule_applied,
    }
    latest = events_by_job.get(current_id)
    if latest:
        if latest.get("action") in {"interested", "applied"}:
            interest_score = max(interest_score, 0.85)
            reasons.append("You marked this job positively.")
        elif latest.get("action") == "not_interested":
            interest_score = min(interest_score, 0.15)
            reasons.append("You marked this job not interested.")
    positive_affinity = sum(
        sorted(
            (_positive_event_affinity(item, event) for event in events_by_job.values()),
            reverse=True,
        )[:3]
    )
    if positive_affinity:
        interest_score += min(0.2, positive_affinity)
        reasons.append("Similar to jobs you opened or pursued.")
    positive_pattern_matches = _positive_pattern_matches(item, list(events_by_job.values()))
    same_company = [
        event
        for event in events_by_job.values()
        if isinstance(event.get("job"), dict)
        and str(event["job"].get("company") or "").strip().casefold() == current_company
    ]
    company_positive = sum(
        event.get("action") in {"interested", "applied"}
        and "company" in (event.get("reasons") or [])
        for event in same_company
    )
    company_negative = sum(
        event.get("action") == "not_interested" and "company" in (event.get("reasons") or [])
        for event in same_company
    )
    company_score += min(0.3, company_positive * 0.12)
    company_score -= min(0.3, company_negative * 0.15)
    for trait in sorted(current_traits & LEARNABLE_TRAITS):
        matching = [
            event
            for event in events_by_job.values()
            if trait in (event.get("reasons") or [])
            and isinstance(event.get("job"), dict)
            and trait in (event["job"].get("traits") or [])
        ]
        positive = sum(event.get("action") in {"interested", "applied"} for event in matching)
        negative = sum(event.get("action") == "not_interested" for event in matching)
        if positive >= 3:
            interest_score += 0.12
            reasons.append(f"You repeatedly liked jobs with {trait.replace('_', ' ')}.")
        if negative >= 3:
            interest_score -= 0.18
            reasons.append(f"You repeatedly passed on jobs with {trait.replace('_', ' ')}.")
    fit_score = min(1.0, max(0.0, fit_score))
    interest_score = min(1.0, max(0.0, interest_score))
    company_score = min(1.0, max(0.0, company_score))
    hot_score = min(1.0, max(0.0, fit_score * (0.5 + interest_score) + (company_score - 0.5) * 0.1))
    screen = item.get("screening")
    result = screen.get("result") if isinstance(screen, dict) else None
    interest = deterministic.get("interest") if isinstance(deterministic, dict) else None
    explicit_target_match = bool(isinstance(interest, dict) and interest.get("desired_title_terms"))
    explicit_interest_match = bool(isinstance(interest, dict) and interest.get("interest_terms"))
    deterministic_match = explicit_target_match or explicit_interest_match
    hard_conflict = bool(isinstance(deterministic, dict) and deterministic.get("hard_conflicts"))
    exact_positive = bool(latest and latest.get("action") in {"interested", "applied"})
    fit_is_strong = bool(
        isinstance(screen, dict)
        and screen.get("status") == "complete"
        and isinstance(result, dict)
        and result.get("fit") == "strong_match"
        and result.get("recommendation") != "do_not_apply"
    )
    learned_match = positive_pattern_matches >= 2
    hot = bool(not hard_conflict and deterministic_match and fit_is_strong)
    hot_reasons: list[str] = []
    if hot:
        hot_reasons.append("career_fit")
        if explicit_target_match:
            hot_reasons.append("saved_target")
        elif explicit_interest_match:
            hot_reasons.append("saved_interest")
        if exact_positive:
            hot_reasons.append("exact_interest")
        if learned_match:
            hot_reasons.append("positive_pattern")
    return {
        "score": round(hot_score, 3),
        "hot_score": round(hot_score, 3),
        "fit_score": round(fit_score, 3),
        "interest_score": round(interest_score, 3),
        "company_score": round(company_score, 3),
        "fit_label": _level(fit_score, positive="Strong"),
        "interest_label": _level(interest_score),
        "company_label": _level(company_score, positive="Positive"),
        "hot_label": (
            "Hot job"
            if hot
            else "Recommended"
            if deterministic_match and not hard_conflict
            else "Promising"
            if fit_score >= 0.55 and interest_score >= 0.5
            else "Learning your preferences"
            if interest_score == 0.5
            else "Low priority"
        ),
        "hot": hot,
        "hot_reasons": hot_reasons,
        "confidence": str(result.get("confidence") or "unknown")
        if isinstance(result, dict)
        else "unknown",
        "reasons": reasons[:4],
        "learning_sources": {
            "explicit_preferences": True,
            "positive_applications": bool(positive_titles),
            "ignored_jobs_used_as_negative": False,
            "not_interested_without_reason_used_as_rule": bool(seniority_pattern["applied"]),
            "seniority_pattern": seniority_pattern,
            "positive_pattern_matches": positive_pattern_matches,
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
    feedback_events: list[dict[str, Any]] | None = None,
) -> tuple[list[str], dict[str, dict[str, Any]]]:
    """Return an advisory order containing every active job exactly once."""
    settings = load_shadow_settings(preferences)
    active = [item for item in items if item.get("active") is True]
    scores = {
        str(item.get("id") or ""): score_shadow_job(
            item,
            positive_titles=positive_titles,
            clearance_preference=str(preferences.get("clearance_preference", "neutral")),
            feedback_events=feedback_events,
        )
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
