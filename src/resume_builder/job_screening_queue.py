"""Build a complete, non-hiding semantic screening view of newly discovered jobs."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from .agent_contracts import ModelAdapter, ModelProviderError
from .applications import applied_job_ids
from .atomic import atomic_write_json, atomic_write_text
from .job_personalization import build_shadow_order
from .job_screening import (
    Confidence,
    FitOutcome,
    Recommendation,
    ScreeningCache,
    ScreeningResult,
)
from .jobs import (
    DEFAULT_CONFIG,
    DEFAULT_NEW_OUTPUT,
    DEFAULT_PREFERENCES,
    _database,
    _load_preferences,
    _with_application_dispositions,
    get_job_screening_packet,
)
from .screening_service import ScreeningService

DEFAULT_SCREENING_OUTPUT = Path("job-search/new-job-screens.json")
SCREENING_QUEUE_SCHEMA_VERSION = 1
RECOMMENDED = {Recommendation.PURSUE, Recommendation.PURSUE_AS_STRETCH}
QUEUE_JOB_FIELDS = ("id", "title", "company", "url", "posted_at", "first_seen_at")


@dataclass(frozen=True)
class ScreeningQueueSummary:
    total: int
    active: int
    completed: int
    cached: int
    provider_calls: int
    recommended: int
    needs_review: int
    additional: int
    failed: int
    input_tokens: int
    output_tokens: int
    cost_usd: Decimal


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
            "hard_conflicts": (
                constraints.get("hard_conflicts", []) if isinstance(constraints, dict) else []
            ),
        }
    return {**view, "source_order": source_order, "active": active}


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
            Recommendation.DEPRIORITIZE.value: 6,
            Recommendation.DO_NOT_APPLY.value: 7,
        }.get(recommendation, 5)
    confidence_rank = {
        Confidence.HIGH.value: 0,
        Confidence.MEDIUM.value: 1,
        Confidence.LOW.value: 2,
    }.get(str(result.get("confidence")), 3)
    return fit_rank, confidence_rank, int(item["source_order"])


def _summary(
    items: list[dict[str, Any]],
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
    )
    return ScreeningQueueSummary(
        total=len(items),
        active=len(active_items),
        completed=len(complete),
        cached=sum(bool(item["screening"].get("cached")) for item in complete),
        provider_calls=provider_calls,
        recommended=recommended,
        needs_review=needs_review,
        additional=max(0, len(active_items) - recommended - needs_review),
        failed=statuses["failed"],
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=cost,
    )


def build_screening_queue(
    *,
    adapter: ModelAdapter,
    model: str,
    cache_path: Path,
    input_path: Path = DEFAULT_NEW_OUTPUT,
    output_path: Path = DEFAULT_SCREENING_OUTPUT,
    config_path: Path = DEFAULT_CONFIG,
    preferences_path: Path = DEFAULT_PREFERENCES,
    max_provider_jobs: int = 6,
    allow_provider: bool = False,
) -> ScreeningQueueSummary:
    """Screen a complete new-job set without allowing any result to hide a job."""
    if not 1 <= max_provider_jobs <= 25:
        raise ValueError("max_provider_jobs must be from 1 to 25")
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    raw_jobs = payload.get("jobs")
    if not isinstance(raw_jobs, list):
        raise ValueError("new-job artifact must contain a jobs list")

    cache = ScreeningCache(cache_path)
    service = ScreeningService(adapter, cache)
    items: list[dict[str, Any]] = []
    provider_calls = 0
    input_tokens = 0
    output_tokens = 0
    total_cost = Decimal("0")
    for source_order, raw in enumerate(raw_jobs):
        if not isinstance(raw, dict):
            raise ValueError("new-job artifact contains a non-object job")
        job = dict(raw)
        prescreen = job.get("prescreen")
        constraints = prescreen.get("constraints") if isinstance(prescreen, dict) else None
        disposition = constraints.get("disposition") if isinstance(constraints, dict) else None
        active = not bool(disposition)
        item = _job_view(job, source_order=source_order, active=active)
        if not active:
            item["screening"] = {"status": "not_active", "reason": "durable_disposition"}
            items.append(item)
            continue

        packet = get_job_screening_packet(
            str(job.get("id") or ""),
            config_path=config_path,
            preferences_path=preferences_path,
        )
        cached = cache.get(packet, model)
        if cached is not None:
            item["screening"] = _result_payload(cached, cached=True)
            items.append(item)
            continue
        if packet.eligibility.value == "ineligible":
            outcome = service.screen_detailed(packet, model=model)
            item["screening"] = _result_payload(outcome.result, cached=False)
            items.append(item)
            continue
        if not allow_provider:
            item["screening"] = {
                "status": "unscreened",
                "reason": "provider_authorization_required",
            }
            items.append(item)
            continue
        if provider_calls >= max_provider_jobs:
            item["screening"] = {"status": "unscreened", "reason": "run_budget_exhausted"}
            items.append(item)
            continue
        provider_calls += 1
        try:
            outcome = service.screen_detailed(packet, model=model)
        except (ModelProviderError, ValueError) as exc:
            item["screening"] = {
                "status": "failed",
                "reason": "provider_error",
                "error_category": exc.__class__.__name__,
            }
        else:
            input_tokens += outcome.input_tokens
            output_tokens += outcome.output_tokens
            total_cost += outcome.cost_usd
            item["screening"] = _result_payload(outcome.result, cached=outcome.cached)
        items.append(item)

    ordered = sorted((item for item in items if item["active"]), key=_priority)
    preferences = (
        _with_application_dispositions(_load_preferences(preferences_path))
        if preferences_path.exists()
        else {}
    )
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
    shadow_order, shadow_scores = build_shadow_order(
        items,
        preferences=preferences,
        positive_titles=positive_titles,
    )
    for item in items:
        job_id = str(item.get("id") or "")
        if job_id in shadow_scores:
            item["shadow_personalization"] = shadow_scores[job_id]
    summary = _summary(items, provider_calls, input_tokens, output_tokens, total_cost)
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
    }
    atomic_write_json(output_path, output)
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
