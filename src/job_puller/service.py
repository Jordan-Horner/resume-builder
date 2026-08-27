from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from .config import InventoryConfig
from .database import InventoryDatabase
from .enrichment import enrich_observation
from .providers import (
    AshbyProvider,
    GreenhouseProvider,
    JobSpyProvider,
    LeverProvider,
    SmartRecruitersProvider,
    WorkdayProvider,
)


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

    def providers(self):
        result = []
        if self.config.providers.linkedin.enabled:
            result.append(JobSpyProvider("linkedin", self.config.providers.linkedin, self.config.search))
        if self.config.providers.indeed.enabled:
            result.append(JobSpyProvider("indeed", self.config.providers.indeed, self.config.search))
        classes = {
            "greenhouse": GreenhouseProvider,
            "lever": LeverProvider,
            "ashby": AshbyProvider,
            "smartrecruiters": SmartRecruitersProvider,
            "workday": WorkdayProvider,
        }
        for name, provider_class in classes.items():
            settings = getattr(self.config.providers, name)
            if settings.enabled:
                for board in settings.boards:
                    result.append(provider_class(board, self.config.request_timeout_seconds))
        return result

    def cutoff(self, source_key: str, now: datetime | None = None) -> datetime:
        now = now or datetime.now(UTC)
        checkpoint = self.database.checkpoint(source_key)
        if checkpoint:
            return checkpoint - timedelta(hours=self.config.checkpoint_overlap_hours)
        return now - timedelta(days=self.config.initial_lookback_days)

    def scrape(self) -> list[RunSummary]:
        summaries = []
        for provider in self.providers():
            cutoff = self.cutoff(provider.source_key)
            result = provider.fetch(cutoff)
            if result.observations:
                enriched = []
                for observation in result.observations:
                    enriched.append(enrich_observation(observation, self.config.request_timeout_seconds))
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
