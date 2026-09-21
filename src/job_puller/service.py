from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from .config import InventoryConfig
from .database import InventoryDatabase
from .enrichment import enrich_observation
from .models import ProviderResult
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

LOGGER = logging.getLogger(__name__)

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

    def _fetch_with_retry(self, provider: Provider, cancel: threading.Event) -> ProviderResult:
        cutoff = self.cutoff(provider.source_key)
        attempts = 0
        while True:
            attempts += 1
            result = provider.fetch(cutoff, cancel=cancel)
            if (
                attempts >= self.config.provider_retry_attempts
                or not result.retryable
                or result.observations
                or cancel.is_set()
            ):
                break
            time.sleep(self.config.provider_retry_backoff_seconds * attempts)
        result.metrics["fetch_attempts"] = attempts
        return result

    def _run_provider(self, provider: Provider) -> RunSummary:
        """Fetch one provider with a hard wall-clock deadline.

        Every HTTP call a provider makes already carries its own per-request
        timeout, but a provider that issues many sequential requests (a large
        Workday board, a deep LinkedIn detail-page scan) has no cap on total
        time otherwise. Running the attempt on a daemon thread and signaling
        `cancel` once the deadline passes lets cooperative providers (the ones
        with a per-item loop) stop making new requests and return whatever
        they already gathered, instead of continuing to run and write to the
        database in the background after this method has moved on. A provider
        that doesn't check `cancel` (or is genuinely stuck, not just slow)
        still can't be forced to stop; it exits later on its own once its
        in-flight request timeouts elapse, and by then no longer blocks
        dispatch.

        A provider bug (or a transient failure recording its result) must
        never escape this method: scrape() fans out over every provider with
        a plain thread pool, and one unhandled exception there would abort
        the whole run and silently drop every other provider's already-
        completed result. Every failure mode below is converted into a
        RunSummary instead of being raised.
        """
        deadline = self.config.provider_fetch_deadline_seconds
        cancel = threading.Event()
        completed: list[ProviderResult] = []
        crashed: list[Exception] = []

        def worker() -> None:
            try:
                completed.append(self._fetch_with_retry(provider, cancel))
            except Exception as exc:  # isolate provider bugs from the rest of the run
                crashed.append(exc)

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        thread.join(timeout=deadline)

        if not completed and not crashed:
            # Give a cooperative provider a short window to notice the signal
            # and return its own (possibly partial) result before we give up
            # and report a synthetic timeout.
            cancel.set()
            thread.join(timeout=self.config.provider_cancel_grace_seconds)

        now = datetime.now(UTC)
        if completed:
            result = completed[0]
        elif crashed:
            exc = crashed[0]
            LOGGER.warning(
                "provider_fetch_failed",
                extra={"source_key": provider.source_key, "error": str(exc)},
            )
            result = ProviderResult(
                provider.source_key,
                provider.name,
                [],
                now,
                now,
                False,
                error=f"{type(exc).__name__}: {exc}",
            )
        else:
            LOGGER.warning(
                "provider_fetch_abandoned",
                extra={"source_key": provider.source_key, "deadline": deadline},
            )
            result = ProviderResult(
                provider.source_key,
                provider.name,
                [],
                now,
                now,
                False,
                error=(
                    f"provider fetch exceeded {deadline:.0f}s deadline and did not "
                    f"respond to cancellation within {self.config.provider_cancel_grace_seconds:.0f}s"
                ),
            )

        try:
            return self._record_and_summarize(result)
        except Exception as exc:  # a write/enrichment failure must not abort the run either
            LOGGER.warning(
                "provider_result_not_recorded",
                extra={"source_key": provider.source_key, "error": str(exc)},
            )
            return RunSummary(
                result.source_key,
                result.provider,
                False,
                False,
                len(result.observations),
                0,
                0,
                f"fetched but failed to record: {type(exc).__name__}: {exc}",
                result.metrics,
                "failed",
                True,
                "unknown",
            )

    def _record_and_summarize(self, result: ProviderResult) -> RunSummary:
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
        return RunSummary(
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

    def _skip_summary(self, provider: Provider, reason: str) -> RunSummary:
        return RunSummary(
            provider.source_key,
            provider.name,
            False,
            False,
            0,
            0,
            0,
            reason,
            {},
            "skipped",
            True,
            "backoff",
        )

    def backoff_cooldown_hours(self, streak: int, error_category: str | None) -> float:
        threshold = self.config.provider_skip_after_consecutive_failures
        over = streak - threshold + 1
        configured = min(
            self.config.provider_skip_base_cooldown_hours * over,
            self.config.provider_skip_max_cooldown_hours,
        )
        # Never let a failed morning run suppress the next day's scan.
        cap = 12 if error_category in {"blocked", "rate-limited"} else 6
        return min(configured, cap)

    def scrape(
        self,
        selected: set[str] | None = None,
        *,
        source_keys: set[str] | None = None,
        on_provider_start: Callable[[int, int, str], None] | None = None,
        on_provider_skip: Callable[[str, str], None] | None = None,
    ) -> list[RunSummary]:
        providers = self.providers(selected)
        if source_keys is not None:
            providers = [provider for provider in providers if provider.source_key in source_keys]
        total = len(providers)
        now = datetime.now(UTC)
        backoff_status = self.database.provider_backoff_status(
            [provider.source_key for provider in providers]
        )

        threshold = self.config.provider_skip_after_consecutive_failures
        runnable: list[Provider] = []
        # Keyed rather than appended in dispatch order, so the final result can
        # be rebuilt in providers()'s original order regardless of how skips and
        # concurrent dispatch scheduling interleave.
        results: dict[str, RunSummary] = {}
        for provider in providers:
            streak, last_run_at, error_category = backoff_status.get(
                provider.source_key, (0, None, None)
            )
            if streak >= threshold and last_run_at is not None:
                cooldown_hours = self.backoff_cooldown_hours(streak, error_category)
                elapsed_hours = (now - last_run_at).total_seconds() / 3600
                if elapsed_hours < cooldown_hours:
                    reason = (
                        f"skipped after {streak} consecutive failures; "
                        f"retrying in {cooldown_hours - elapsed_hours:.1f}h"
                    )
                    self.database.record_skip(provider.source_key, provider.name, reason, now)
                    if on_provider_skip is not None:
                        on_provider_skip(provider.source_key, reason)
                    results[provider.source_key] = self._skip_summary(provider, reason)
                    continue
            runnable.append(provider)

        if runnable:
            started = len(results)  # skipped providers already counted toward total
            started_lock = threading.Lock()

            def dispatch(provider: Provider) -> RunSummary:
                nonlocal started
                with started_lock:
                    started += 1
                    index = started
                if on_provider_start is not None:
                    on_provider_start(index, total, provider.source_key)
                return self._run_provider(provider)

            with ThreadPoolExecutor(max_workers=self.config.provider_workers) as pool:
                for provider, summary in zip(runnable, pool.map(dispatch, runnable), strict=True):
                    results[provider.source_key] = summary

        return [results[provider.source_key] for provider in providers]
