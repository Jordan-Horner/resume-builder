"""Build a complete, non-hiding semantic screening view of newly discovered jobs."""

from __future__ import annotations

import json
import logging
import time
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from job_puller.normalize import normalized_key

from ..agent_contracts import ModelAdapter, ModelProviderError
from ..application_tracking.records import DEFAULT_ROOT as DEFAULT_APPLICATIONS_ROOT
from ..application_tracking.records import applied_job_ids
from ..atomic import atomic_write_json, atomic_write_text
from .cli import (
    DEFAULT_CONFIG,
    DEFAULT_NEW_OUTPUT,
    DEFAULT_PREFERENCES,
    _database,
    _load_preferences,
    _with_application_dispositions,
    get_job_screening_packet,
)
from .personalization import (
    build_shadow_order,
    extract_preference_traits,
    extract_seniority,
    load_feedback_events,
    score_shadow_job,
)
from .posting import PostingInterpretationCache
from .resume_recommendations import load_directional_resume_candidates
from .screening import (
    Confidence,
    FitOutcome,
    Recommendation,
    ScreeningCache,
    ScreeningResult,
)
from .screening_evidence import adjacent_evidence_signal
from .screening_service import ScreeningService, enrich_packet_from_cached_interpretation

LOGGER = logging.getLogger(__name__)

DEFAULT_SCREENING_OUTPUT = Path("job-search/new-job-screens.json")
SCREENING_QUEUE_SCHEMA_VERSION = 1
LEARNED_ADJACENT_SCHEMA_VERSION = 1
RECOMMENDED = {Recommendation.PURSUE, Recommendation.PURSUE_AS_STRETCH}
QUEUE_JOB_FIELDS = (
    "id",
    "title",
    "company",
    "url",
    "posted_at",
    "first_seen_at",
    "salary_min",
    "salary_max",
    "salary_currency",
    "work_modes",
)


@dataclass(frozen=True)
class ScreeningQueueSummary:
    total: int
    active: int
    completed: int
    cached: int
    attempted: int
    succeeded: int
    provider_calls: int
    recommended: int
    needs_review: int
    pending: int
    additional: int
    failed: int
    failure_categories: dict[str, int]
    input_tokens: int
    output_tokens: int
    cost_usd: Decimal
    duration_seconds: float


def _result_payload(result: ScreeningResult, *, cached: bool) -> dict[str, Any]:
    return {
        "status": "complete",
        "cached": cached,
        "result": result.model_dump(mode="json"),
    }


def _job_view(job: dict[str, Any], *, source_order: int, active: bool) -> dict[str, Any]:
    """Keep the queue useful without duplicating full posting or resume-derived text."""
    view = {field: job.get(field) for field in QUEUE_JOB_FIELDS}
    prescreen = job.get("prescreen")
    if isinstance(prescreen, dict):
        constraints = prescreen.get("constraints")
        view["deterministic"] = {
            "queue_state": prescreen.get("queue_state"),
            "interest": prescreen.get("interest", {}),
            "clearance_requirement": (
                constraints.get("clearance_requirement", False)
                if isinstance(constraints, dict)
                else False
            ),
            "hard_conflicts": (
                constraints.get("hard_conflicts", []) if isinstance(constraints, dict) else []
            ),
        }
    view["preference_traits"] = extract_preference_traits(job)
    return {**view, "source_order": source_order, "active": active}


def _automatic_skip_reason(job: dict[str, Any]) -> str | None:
    """Use only local prescreen evidence to avoid spending on obvious misses."""
    prescreen = job.get("prescreen")
    if not isinstance(prescreen, dict):
        return None
    queue_state = prescreen.get("queue_state")
    if queue_state == "hard_conflict":
        return "hard_constraint_conflict"
    if queue_state == "needs_description":
        return "incomplete_listing"
    if isinstance(prescreen.get("interest"), dict) and not _has_saved_search_signal(job):
        return "no_saved_search_signal"
    return None


def _has_saved_search_signal(job: dict[str, Any]) -> bool:
    prescreen = job.get("prescreen")
    interest = prescreen.get("interest") if isinstance(prescreen, dict) else None
    return bool(
        isinstance(interest, dict)
        and any(bool(interest.get(key)) for key in ("desired_title_terms", "interest_terms"))
    )


def _load_learned_adjacent(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"invalid learned adjacent roles: {path}") from exc
    patterns = payload.get("patterns") if isinstance(payload, dict) else None
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != LEARNED_ADJACENT_SCHEMA_VERSION
        or not isinstance(patterns, list)
    ):
        raise ValueError(f"invalid learned adjacent roles: {path}")
    if any(
        not isinstance(item, dict)
        or not isinstance(item.get("title"), str)
        or not isinstance(item.get("seniority"), str)
        for item in patterns
    ):
        raise ValueError(f"invalid learned adjacent roles: {path}")
    return patterns


def _learned_adjacent_match(job: dict[str, Any], patterns: list[dict[str, str]]) -> bool:
    title = normalized_key(str(job.get("title") or ""))
    seniority = extract_seniority(job)
    return any(
        item.get("title") == title
        and (
            seniority == "unknown"
            or item.get("seniority") == "unknown"
            or item.get("seniority") == seniority
        )
        for item in patterns
    )


def _screen_confirms_adjacent(screening: dict[str, Any]) -> bool:
    result = screening.get("result") if screening.get("status") == "complete" else None
    return bool(
        isinstance(result, dict)
        and result.get("fit") in {"strong_match", "good_match"}
        and result.get("recommendation") == "pursue"
        and result.get("confidence") in {"medium", "high"}
    )


def _remember_adjacent(job: dict[str, Any], patterns: list[dict[str, str]]) -> bool:
    pattern = {
        "title": normalized_key(str(job.get("title") or "")),
        "seniority": extract_seniority(job),
    }
    if pattern["title"] and pattern not in patterns:
        patterns.append(pattern)
        return True
    return False


def _priority(item: dict[str, Any]) -> tuple[int, int, int]:
    screen = item.get("screening")
    if not isinstance(screen, dict) or screen.get("status") != "complete":
        status_rank = {"unscreened": 3, "failed": 4}.get(
            str(screen.get("status")) if isinstance(screen, dict) else "", 3
        )
        return status_rank, 3, int(item["source_order"])
    result = screen.get("result")
    if not isinstance(result, dict):
        return 4, 3, int(item["source_order"])
    recommendation = str(result.get("recommendation"))
    fit = str(result.get("fit"))
    if recommendation == Recommendation.PURSUE.value:
        fit_rank = {
            FitOutcome.STRONG_MATCH.value: 0,
            FitOutcome.GOOD_MATCH.value: 1,
        }.get(fit, 2)
    else:
        fit_rank = {
            Recommendation.PURSUE_AS_STRETCH.value: 2,
            Recommendation.VERIFY_ELIGIBILITY.value: 3,
            Recommendation.NEEDS_MORE_EVIDENCE.value: 4,
            Recommendation.DEPRIORITIZE.value: 6,
            Recommendation.DO_NOT_APPLY.value: 7,
        }.get(recommendation, 5)
    confidence_rank = {
        Confidence.HIGH.value: 0,
        Confidence.MEDIUM.value: 1,
        Confidence.LOW.value: 2,
    }.get(str(result.get("confidence")), 3)
    return fit_rank, confidence_rank, int(item["source_order"])


def _previous_failures(path: Path) -> dict[str, dict[str, Any]]:
    """Retain failed-job cooldown state while later candidates use the next batch."""
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    jobs = payload.get("jobs") if isinstance(payload, dict) else None
    if not isinstance(jobs, list):
        return {}
    return {
        str(item["id"]): dict(screen)
        for item in jobs
        if isinstance(item, dict)
        and item.get("id")
        and isinstance((screen := item.get("screening")), dict)
        and screen.get("status") == "failed"
    }


def _summary(
    items: list[dict[str, Any]],
    attempted: int,
    duration_seconds: float,
    failure_categories: Counter[str],
    provider_calls: int,
    input_tokens: int,
    output_tokens: int,
    cost: Decimal,
) -> ScreeningQueueSummary:
    active_items = [item for item in items if item.get("active") is True]
    statuses = Counter(str(item.get("screening", {}).get("status")) for item in active_items)
    complete = [
        item
        for item in active_items
        if isinstance(item.get("screening"), dict) and item["screening"].get("status") == "complete"
    ]
    recommendations = Counter(
        str(item["screening"].get("result", {}).get("recommendation")) for item in complete
    )
    recommended = sum(recommendations[value.value] for value in RECOMMENDED)
    needs_review = (
        statuses["unscreened"]
        + statuses["failed"]
        + recommendations[Recommendation.VERIFY_ELIGIBILITY.value]
        + recommendations[Recommendation.NEEDS_MORE_EVIDENCE.value]
    )
    pending = statuses["unscreened"] + statuses["failed"]
    return ScreeningQueueSummary(
        total=len(items),
        active=len(active_items),
        completed=len(complete),
        cached=sum(bool(item["screening"].get("cached")) for item in complete),
        attempted=attempted,
        succeeded=max(0, attempted - sum(failure_categories.values())),
        provider_calls=provider_calls,
        recommended=recommended,
        needs_review=needs_review,
        pending=pending,
        additional=max(0, len(active_items) - recommended - needs_review),
        failed=statuses["failed"],
        failure_categories=dict(sorted(failure_categories.items())),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=cost,
        duration_seconds=duration_seconds,
    )


def build_screening_queue(
    *,
    adapter: ModelAdapter,
    model: str,
    interpretation_model: str | None = None,
    cache_path: Path,
    input_path: Path = DEFAULT_NEW_OUTPUT,
    output_path: Path = DEFAULT_SCREENING_OUTPUT,
    config_path: Path = DEFAULT_CONFIG,
    preferences_path: Path = DEFAULT_PREFERENCES,
    max_provider_jobs: int = 6,
    allow_provider: bool = False,
    workspace: Path = Path("."),
) -> ScreeningQueueSummary:
    """Screen a complete new-job set without allowing any result to hide a job."""
    batch_started = time.monotonic()
    if not 1 <= max_provider_jobs <= 25:
        raise ValueError("max_provider_jobs must be from 1 to 25")
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    raw_jobs = payload.get("jobs")
    if not isinstance(raw_jobs, list):
        raise ValueError("new-job artifact must contain a jobs list")

    cache = ScreeningCache(cache_path)
    service = ScreeningService(
        adapter,
        cache,
    )
    preferences = (
        _with_application_dispositions(
            _load_preferences(preferences_path), workspace / DEFAULT_APPLICATIONS_ROOT
        )
        if preferences_path.exists()
        else {}
    )
    directional_resumes = load_directional_resume_candidates(workspace)
    dispositions = preferences.get("job_dispositions") or {}
    positive_ids = applied_job_ids() | {
        str(job_id) for job_id, status in dispositions.items() if status == "applied"
    }
    positive_titles = (
        [
            str(job.get("title") or "")
            for job in _database(config_path).active_inventory()
            if str(job.get("id") or "") in positive_ids
        ]
        if positive_ids
        else []
    )
    feedback_events = load_feedback_events(workspace / "job-search/job-feedback.json")
    learned_path = output_path.with_name("learned-adjacent-roles.json")
    learned_adjacent = _load_learned_adjacent(learned_path)
    previous_failures = _previous_failures(output_path)
    latest_actions = {
        str(snapshot["id"]): str(event.get("action"))
        for event in feedback_events
        if event.get("action") in {"interested", "not_interested", "applied"}
        and isinstance((snapshot := event.get("job")), dict)
        and snapshot.get("id")
    }
    prepared: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for source_order, raw in enumerate(raw_jobs):
        if not isinstance(raw, dict):
            raise ValueError("new-job artifact contains a non-object job")
        job = dict(raw)
        prescreen = job.get("prescreen")
        constraints = prescreen.get("constraints") if isinstance(prescreen, dict) else None
        disposition = constraints.get("disposition") if isinstance(constraints, dict) else None
        active = not bool(disposition)
        prepared.append((job, _job_view(job, source_order=source_order, active=active)))
    prepared.sort(
        key=lambda pair: (
            0 if _has_saved_search_signal(pair[0]) else 1,
            1 if str(pair[0].get("id") or "") in previous_failures else 0,
            -float(
                score_shadow_job(
                    {**pair[1], "screening": {"status": "unscreened"}},
                    positive_titles=positive_titles,
                    clearance_preference=str(preferences.get("clearance_preference", "neutral")),
                    feedback_events=feedback_events,
                )["score"]
            ),
            int(pair[1]["source_order"]),
        )
    )
    LOGGER.info(
        "screening_batch_started model=%s total_jobs=%d active_jobs=%d max_provider_jobs=%d",
        model,
        len(prepared),
        sum(bool(item[1]["active"]) for item in prepared),
        max_provider_jobs,
    )

    items: list[dict[str, Any]] = []
    provider_jobs = 0
    provider_calls = 0
    input_tokens = 0
    output_tokens = 0
    total_cost = Decimal("0")
    failure_categories: Counter[str] = Counter()
    adjacent_candidates = 0
    learned_title_candidates = 0
    confirmed_adjacent = 0
    suppressed_patterns = 0
    for job, item in prepared:
        active = bool(item["active"])
        if not active:
            item["screening"] = {"status": "not_active", "reason": "durable_disposition"}
            items.append(item)
            continue
        packet = None
        adjacent: dict[str, object] | None = None
        skip_reason = _automatic_skip_reason(job)
        if skip_reason == "no_saved_search_signal":
            packet = get_job_screening_packet(
                str(job.get("id") or ""),
                config_path=config_path,
                preferences_path=preferences_path,
                workspace=workspace,
                prepared_job=job,
                prepared_preferences=preferences,
                prepared_prescreen=(
                    prescreen if isinstance((prescreen := job.get("prescreen")), dict) else None
                ),
                prepared_directional_resumes=directional_resumes,
            )
            learned = _learned_adjacent_match(job, learned_adjacent)
            adjacent = (
                {"eligible": True, "learned_title": True}
                if learned
                else adjacent_evidence_signal(
                    packet.job.model_dump(mode="python"), packet.candidate_evidence
                )
            )
            item.setdefault("deterministic", {})["adjacent_candidate"] = adjacent
            if not adjacent["eligible"]:
                item["screening"] = {"status": "skipped", "reason": skip_reason}
                items.append(item)
                continue
            adjacent_candidates += 1
            learned_title_candidates += learned
        elif skip_reason:
            item["screening"] = {"status": "skipped", "reason": skip_reason}
            items.append(item)
            continue
        if latest_actions.get(str(job.get("id") or "")) in {
            "interested",
            "not_interested",
            "applied",
        }:
            item["screening"] = {"status": "skipped", "reason": "feedback_disposition"}
            items.append(item)
            continue
        pattern_score = score_shadow_job(
            {**item, "screening": {"status": "unscreened"}},
            positive_titles=positive_titles,
            clearance_preference=str(preferences.get("clearance_preference", "neutral")),
            feedback_events=feedback_events,
        )
        role_pattern = pattern_score.get("learning_sources", {}).get("role_pattern", {})
        if isinstance(role_pattern, dict) and role_pattern.get("suppressed") is True:
            suppressed_patterns += 1
            item["screening"] = {"status": "skipped", "reason": "role_pattern_suppressed"}
            items.append(item)
            continue

        if packet is None:
            packet = get_job_screening_packet(
                str(job.get("id") or ""),
                config_path=config_path,
                preferences_path=preferences_path,
                workspace=workspace,
                prepared_job=job,
                prepared_preferences=preferences,
                prepared_prescreen=(
                    prescreen if isinstance((prescreen := job.get("prescreen")), dict) else None
                ),
                prepared_directional_resumes=directional_resumes,
            )
        packet = enrich_packet_from_cached_interpretation(
            packet,
            model=interpretation_model or model,
            interpretation_cache=PostingInterpretationCache(cache_path),
            vault_root=workspace / "vault",
            directional_resumes=directional_resumes,
        )
        cached = cache.get(packet, model)
        if cached is not None:
            item["screening"] = _result_payload(cached, cached=True)
            if adjacent and _screen_confirms_adjacent(item["screening"]):
                confirmed_adjacent += _remember_adjacent(job, learned_adjacent)
            items.append(item)
            continue
        if packet.eligibility.value == "ineligible":
            item["screening"] = {
                "status": "skipped",
                "reason": "hard_constraint_conflict",
            }
            items.append(item)
            continue
        if not allow_provider:
            item["screening"] = {
                "status": "unscreened",
                "reason": "provider_authorization_required",
            }
            items.append(item)
            continue
        if provider_jobs >= max_provider_jobs:
            item["screening"] = previous_failures.get(
                str(job.get("id") or ""),
                {"status": "unscreened", "reason": "run_budget_exhausted"},
            )
            items.append(item)
            continue
        provider_jobs += 1
        try:
            outcome = service.screen_detailed(packet, model=model)
        except (ModelProviderError, ValueError) as exc:
            requests = int(getattr(exc, "requests", 1))
            category = str(getattr(exc, "category", exc.__class__.__name__))
            provider_calls += requests
            failure_categories[category] += 1
            item["screening"] = {
                "status": "failed",
                "reason": "provider_error",
                "error_category": category,
            }
        else:
            provider_calls += outcome.requests
            input_tokens += outcome.input_tokens
            output_tokens += outcome.output_tokens
            total_cost += outcome.cost_usd
            item["screening"] = _result_payload(outcome.result, cached=outcome.cached)
            if adjacent and _screen_confirms_adjacent(item["screening"]):
                confirmed_adjacent += _remember_adjacent(job, learned_adjacent)
        items.append(item)

    items.sort(key=lambda item: int(item["source_order"]))
    ordered = sorted((item for item in items if item["active"]), key=_priority)
    shadow_order, shadow_scores = build_shadow_order(
        items,
        preferences=preferences,
        positive_titles=positive_titles,
        feedback_events=feedback_events,
    )
    for item in items:
        job_id = str(item.get("id") or "")
        if job_id in shadow_scores:
            item["shadow_personalization"] = shadow_scores[job_id]
    summary = _summary(
        items,
        provider_jobs,
        time.monotonic() - batch_started,
        failure_categories,
        provider_calls,
        input_tokens,
        output_tokens,
        total_cost,
    )
    LOGGER.info(
        "screening_batch_completed duration_seconds=%.3f attempted_jobs=%d succeeded_jobs=%d "
        "cached_jobs=%d failed_jobs=%d provider_requests=%d input_tokens=%d output_tokens=%d "
        "cost_usd=%s failure_categories=%s recommended_jobs=%d needs_review_jobs=%d",
        summary.duration_seconds,
        summary.attempted,
        summary.succeeded,
        summary.cached,
        summary.failed,
        summary.provider_calls,
        summary.input_tokens,
        summary.output_tokens,
        summary.cost_usd,
        json.dumps(summary.failure_categories, sort_keys=True, separators=(",", ":")),
        summary.recommended,
        summary.needs_review,
    )
    output = {
        "schema_version": SCREENING_QUEUE_SCHEMA_VERSION,
        "source_generated_at": payload.get("generated_at"),
        "source_prescreen_version": payload.get("prescreen_version"),
        "model": model,
        "summary": {
            **summary.__dict__,
            "cost_usd": str(summary.cost_usd),
        },
        # Canonical completeness view: source order remains newest-first.
        "jobs": items,
        # Advisory ordering only. Every active job appears exactly once.
        "suggested_order": [str(item.get("id") or "") for item in ordered],
        # Evaluation-only ordering. Notifications and canonical completeness do not use it.
        "shadow_personalized_order": shadow_order,
        "personalization_policy": {
            "mode": "shadow",
            "changes_visibility": False,
            "changes_notifications": False,
            "ignored_jobs_are_negative_feedback": False,
        },
        "adjacent_learning": {
            "candidates": adjacent_candidates,
            "learned_title_candidates": learned_title_candidates,
            "newly_confirmed_patterns": confirmed_adjacent,
            "suppressed_patterns": suppressed_patterns,
            "stored_patterns": len(learned_adjacent),
        },
    }
    atomic_write_json(output_path, output)
    if learned_adjacent or learned_path.exists():
        atomic_write_json(
            learned_path,
            {
                "schema_version": LEARNED_ADJACENT_SCHEMA_VERSION,
                "patterns": sorted(
                    learned_adjacent,
                    key=lambda item: (item.get("title", ""), item.get("seniority", "")),
                ),
            },
        )
    lines = [
        "# New Job Screening",
        "",
        f"Total active jobs: {summary.active}",
        f"Recommended: {summary.recommended}",
        f"Need review or screening: {summary.needs_review}",
        f"Additional jobs: {summary.additional}",
        "",
    ]
    for item in ordered:
        screen = item["screening"]
        if screen["status"] == "complete":
            result = screen["result"]
            label = f"{str(result['fit']).replace('_', ' ')} / {result['confidence']!s} confidence"
        else:
            label = f"{screen['status']} / {screen.get('reason', 'unknown')}"
        lines.append(f"- **{label.upper()}** — {item.get('title')} at {item.get('company')}")
    atomic_write_text(output_path.with_suffix(".md"), "\n".join(lines) + "\n")
    return summary


def load_notification_jobs(path: Path = DEFAULT_SCREENING_OUTPUT) -> list[dict[str, Any]]:
    """Return every active job in advisory order, with no relevance cutoff."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    raw_jobs = payload.get("jobs", [])
    jobs = {
        str(item.get("id") or ""): item
        for item in raw_jobs
        if isinstance(item, dict) and item.get("active") is True
    }
    order = payload.get("suggested_order", [])
    if not isinstance(order, list):
        raise ValueError("screening queue suggested_order must be a list")
    return [jobs[job_id] for value in order if (job_id := str(value)) in jobs]
