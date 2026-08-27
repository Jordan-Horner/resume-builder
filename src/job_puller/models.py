from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


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
    raw_payload: dict[str, Any] = field(default_factory=dict)
    parser_version: str = "1"


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
