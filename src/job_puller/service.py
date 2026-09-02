from __future__ import annotations

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
            result = provider.fetch(cutoff)
            if result.observations:
                enriched = []
                for observation in result.observations:
                    enriched.append(
                        enrich_observation(observation, self.config.request_timeout_seconds)
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
                )
            )
        return summaries
