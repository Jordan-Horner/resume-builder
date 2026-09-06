from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from .config import InventoryConfig
from .database import InventoryDatabase
from .enrichment import enrich_observation
from .providers import (
    AshbyProvider,
    GreenhouseProvider,
    JazzHRProvider,
    JobSpyProvider,
    LeverProvider,
    LinkedInGuestProvider,
    RipplingProvider,
    SmartRecruitersProvider,
    WorkdayProvider,
)
from .providers.base import Provider

ATS_PROVIDER_CLASSES = {
    "jazzhr": JazzHRProvider,
    "rippling": RipplingProvider,
    "greenhouse": GreenhouseProvider,
    "lever": LeverProvider,
    "ashby": AshbyProvider,
    "smartrecruiters": SmartRecruitersProvider,
    "workday": WorkdayProvider,
}


@dataclass(slots=True)
class RunSummary:
    source_key: str
    provider: str
    success: bool
    suspicious_empty: bool
    fetched: int
    inserted: int
    updated: int
    error: str | None
    metrics: dict[str, int]
    outcome: str
    retryable: bool
    error_category: str | None


class InventoryService:
    def __init__(self, config: InventoryConfig, database: InventoryDatabase):
        self.config = config
        self.database = database

    def providers(self, selected: set[str] | None = None) -> list[Provider]:
        result: list[Provider] = []
        if self.config.providers.linkedin.enabled and (selected is None or "linkedin" in selected):
            result.append(
                LinkedInGuestProvider(
                    self.config.providers.linkedin,
                    self.config.search,
                    self.config.request_timeout_seconds,
                    detail_cache=self.database,
                )
            )
        if self.config.providers.indeed.enabled and (selected is None or "indeed" in selected):
            result.append(
                JobSpyProvider("indeed", self.config.providers.indeed, self.config.search)
            )
        for name, provider_class in ATS_PROVIDER_CLASSES.items():
            if selected is not None and name not in selected:
                continue
            settings = getattr(self.config.providers, name)
            if settings.enabled:
                for board in settings.boards:
                    if board.enabled:
                        result.append(
                            provider_class(
                                board,
                                self.config.request_timeout_seconds,
                                self.config.search,
                            )
                        )
        return result

    def ats_providers(self, name: str, *, include_disabled: bool = False) -> list[Provider]:
        provider_class = ATS_PROVIDER_CLASSES[name]
        settings = getattr(self.config.providers, name)
        if not settings.enabled and not include_disabled:
            return []
        return [
            provider_class(board, self.config.request_timeout_seconds, self.config.search)
            for board in settings.boards
            if board.enabled or include_disabled
        ]

    def cutoff(self, source_key: str, now: datetime | None = None) -> datetime:
        now = now or datetime.now(UTC)
        checkpoint = self.database.checkpoint(source_key)
        if checkpoint:
            return checkpoint - timedelta(hours=self.config.checkpoint_overlap_hours)
        return now - timedelta(days=self.config.initial_lookback_days)

    def scrape(
        self,
        selected: set[str] | None = None,
        *,
        on_provider_start: Callable[[int, int, str], None] | None = None,
    ) -> list[RunSummary]:
        summaries = []
        providers = self.providers(selected)
        total = len(providers)
        for index, provider in enumerate(providers, start=1):
            if on_provider_start is not None:
                on_provider_start(index, total, provider.source_key)
            cutoff = self.cutoff(provider.source_key)
            attempts = 0
            while True:
                attempts += 1
                result = provider.fetch(cutoff)
                if (
                    attempts >= self.config.provider_retry_attempts
                    or not result.retryable
                    or result.observations
                ):
                    break
                time.sleep(self.config.provider_retry_backoff_seconds * attempts)
            result.metrics["fetch_attempts"] = attempts
            if result.observations:
                enriched = []
                for observation in result.observations:
                    tracks_direct_apply = observation.provider in {"linkedin", "indeed"} and bool(
                        observation.direct_apply_url
                    )
                    enriched.append(
                        enrich_observation(observation, self.config.request_timeout_seconds)
                    )
                    if tracks_direct_apply:
                        result.metrics["direct_apply_links"] = (
                            result.metrics.get("direct_apply_links", 0) + 1
                        )
                        resolution = observation.raw_payload.get("direct_apply_resolution", {})
                        status = resolution.get("status") if isinstance(resolution, dict) else None
                        if status in {"resolved", "verified"}:
                            result.metrics["direct_apply_links_verified"] = (
                                result.metrics.get("direct_apply_links_verified", 0) + 1
                            )
                        elif status == "failed":
                            result.metrics["direct_apply_resolution_failed"] = (
                                result.metrics.get("direct_apply_resolution_failed", 0) + 1
                            )
                    ats_posting = observation.raw_payload.get("ats_job_posting")
                    if isinstance(ats_posting, dict):
                        result.metrics["ats_postings_enriched"] = (
                            result.metrics.get("ats_postings_enriched", 0) + 1
                        )
                result.observations = enriched
            inserted, updated = self.database.record_result(result)
            summaries.append(
                RunSummary(
                    result.source_key,
                    result.provider,
                    result.success,
                    result.suspicious_empty,
                    len(result.observations),
                    inserted,
                    updated,
                    result.error,
                    result.metrics,
                    result.outcome.value,
                    result.retryable,
                    result.error_category,
                )
            )
        return summaries
