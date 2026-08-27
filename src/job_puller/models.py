from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from .work_modes import WorkArrangement, WorkMode, classify_work_arrangement


def utc_now() -> datetime:
    return datetime.now(UTC)


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
