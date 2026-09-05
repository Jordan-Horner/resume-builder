from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from .compensation import extract_compensation_range
from .work_modes import WorkArrangement, WorkMode, classify_work_arrangement


def utc_now() -> datetime:
    return datetime.now(UTC)


class ProviderOutcome(str, Enum):
    HEALTHY = "healthy"
    HEALTHY_EMPTY = "healthy-empty"
    PARTIAL = "partial"
    CAPPED = "capped"
    BLOCKED = "blocked"
    FAILED = "failed"


@dataclass(slots=True)
class JobObservation:
    provider: str
    provider_job_id: str
    title: str
    company: str
    source_url: str
    provider_board_id: str = ""
    direct_apply_url: str = ""
    location: str = ""
    description_html: str = ""
    description_text: str = ""
    posted_at: datetime | None = None
    salary_min: float | None = None
    salary_max: float | None = None
    salary_currency: str | None = None
    salary_interval: str | None = None
    employment_type: str | None = None
    remote: bool | None = None
    work_arrangement: WorkArrangement | None = None
    raw_payload: dict[str, Any] = field(default_factory=dict)
    parser_version: str = "1"

    def __post_init__(self) -> None:
        if self.salary_min is None and self.salary_max is None:
            compensation = extract_compensation_range(self.description_text)
            if compensation is not None:
                self.salary_min = compensation.minimum
                self.salary_max = compensation.maximum
                self.salary_currency = self.salary_currency or compensation.currency
                self.salary_interval = self.salary_interval or compensation.interval
        if self.work_arrangement is None:
            self.work_arrangement = classify_work_arrangement(
                title=self.title,
                location=self.location,
                description=self.description_text,
                legacy_remote=self.remote,
            )

    @property
    def work_modes(self) -> frozenset[WorkMode]:
        assert self.work_arrangement is not None
        return self.work_arrangement.available_modes


@dataclass(slots=True)
class ProviderResult:
    source_key: str
    provider: str
    observations: list[JobObservation]
    started_at: datetime
    completed_at: datetime
    success: bool
    error: str | None = None
    suspicious_empty: bool = False
    authoritative_complete: bool = False
    metrics: dict[str, int] = field(default_factory=dict)

    @property
    def outcome(self) -> ProviderOutcome:
        error = (self.error or "").casefold()
        blocked_markers = ("captcha", "challenge", "forbidden", "unauthorized", "status 403")
        if any(marker in error for marker in blocked_markers):
            return ProviderOutcome.BLOCKED
        if self.success and any(
            self.metrics.get(key, 0) > 0 for key in ("saturated_queries", "scan_limit_reached")
        ):
            return ProviderOutcome.CAPPED
        if self.success and self.observations:
            return ProviderOutcome.HEALTHY
        if self.success and not self.suspicious_empty:
            return ProviderOutcome.HEALTHY_EMPTY
        if self.observations:
            return ProviderOutcome.PARTIAL
        return ProviderOutcome.FAILED

    @property
    def error_category(self) -> str | None:
        if self.outcome == ProviderOutcome.BLOCKED:
            return "blocked"
        if self.suspicious_empty:
            return "suspicious-empty"
        error = (self.error or "").casefold()
        if not error:
            return None
        if any(marker in error for marker in ("timeout", "timed out", "connection", "network")):
            return "transport"
        if any(marker in error for marker in ("status 4", "status 5", "http")):
            return "http"
        if any(marker in error for marker in ("parse", "json", "schema")):
            return "parse"
        return "unknown"

    @property
    def retryable(self) -> bool:
        if self.outcome in {
            ProviderOutcome.HEALTHY,
            ProviderOutcome.HEALTHY_EMPTY,
            ProviderOutcome.CAPPED,
            ProviderOutcome.BLOCKED,
        }:
            return False
        error = (self.error or "").casefold()
        return (
            self.suspicious_empty
            or self.error_category == "transport"
            or any(
                marker in error for marker in ("status 429", "status 5", "temporarily unavailable")
            )
        )
