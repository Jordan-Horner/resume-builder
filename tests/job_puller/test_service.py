import sqlite3
import threading
import time
from datetime import UTC, datetime, timedelta

from job_puller.config import InventoryConfig
from job_puller.database import InventoryDatabase
from job_puller.models import JobObservation, ProviderResult
from job_puller.providers.linkedin import LinkedInGuestProvider
from job_puller.service import InventoryService


def config():
    return InventoryConfig.model_validate(
        {
            "search": {"families": [{"name": "backend", "titles": ["backend engineer"]}]},
            "providers": {
                "linkedin": {"enabled": True},
                "indeed": {"enabled": False},
                "greenhouse": {"enabled": False},
                "lever": {"enabled": False},
                "ashby": {"enabled": False},
                "smartrecruiters": {"enabled": False},
                "workday": {"enabled": False},
            },
        }
    )


def test_initial_cutoff_is_seven_days(tmp_path):
    db = InventoryDatabase(tmp_path / "inventory.db")
    db.migrate()
    service = InventoryService(config(), db)
    now = datetime(2026, 8, 27, tzinfo=UTC)
    assert service.cutoff("linkedin:guest", now) == now - timedelta(days=7)


def test_service_uses_direct_linkedin_provider(tmp_path):
    db = InventoryDatabase(tmp_path / "inventory.db")
    db.migrate()
    providers = InventoryService(config(), db).providers()
    assert len(providers) == 1
    assert isinstance(providers[0], LinkedInGuestProvider)
    assert providers[0].source_key == "linkedin:guest"
    assert providers[0].detail_cache is db


def test_service_can_select_one_provider_type(tmp_path):
    db = InventoryDatabase(tmp_path / "inventory.db")
    configured = config()
    configured.providers.indeed.enabled = True
    providers = InventoryService(configured, db).providers({"indeed"})
    assert len(providers) == 1
    assert providers[0].name == "indeed"


def test_scrape_reports_each_provider_before_fetching(tmp_path, monkeypatch):
    db = InventoryDatabase(tmp_path / "inventory.db")
    db.migrate()
    service = InventoryService(config(), db)
    events = []

    class StubProvider:
        name = "stub"
        source_key = "stub:board"

        def fetch(self, since, *, cancel=None):
            events.append(("fetch", since))
            now = datetime.now(UTC)
            return ProviderResult(
                source_key=self.source_key,
                provider=self.name,
                observations=[],
                started_at=now,
                completed_at=now,
                success=True,
                suspicious_empty=False,
            )

    monkeypatch.setattr(service, "providers", lambda _selected: [StubProvider()])

    summaries = service.scrape(
        on_provider_start=lambda index, total, source_key: events.append(
            ("start", index, total, source_key)
        )
    )

    assert events[0] == ("start", 1, 1, "stub:board")
    assert events[1][0] == "fetch"
    assert summaries[0].source_key == "stub:board"
    assert summaries[0].outcome == "healthy-empty"


def test_scrape_retries_retryable_empty_failure_once(tmp_path, monkeypatch):
    db = InventoryDatabase(tmp_path / "inventory.db")
    db.migrate()
    configured = config()
    configured.provider_retry_backoff_seconds = 0
    service = InventoryService(configured, db)
    attempts = 0

    class StubProvider:
        name = "stub"
        source_key = "stub:board"

        def fetch(self, since, *, cancel=None):
            nonlocal attempts
            attempts += 1
            now = datetime.now(UTC)
            return ProviderResult(
                source_key=self.source_key,
                provider=self.name,
                observations=[],
                started_at=now,
                completed_at=now,
                success=attempts > 1,
                error=None if attempts > 1 else "connection timeout",
            )

    monkeypatch.setattr(service, "providers", lambda _selected: [StubProvider()])

    summary = service.scrape()[0]

    assert attempts == 2
    assert summary.outcome == "healthy-empty"
    assert summary.metrics["fetch_attempts"] == 2


def test_scrape_reports_verified_direct_apply_enrichment(tmp_path, monkeypatch):
    db = InventoryDatabase(tmp_path / "inventory.db")
    db.migrate()
    service = InventoryService(config(), db)

    class StubProvider:
        name = "linkedin"
        source_key = "linkedin:guest"

        def fetch(self, since, *, cancel=None):
            now = datetime.now(UTC)
            return ProviderResult(
                source_key=self.source_key,
                provider=self.name,
                observations=[
                    JobObservation(
                        provider="linkedin",
                        provider_job_id="123",
                        title="AI Engineer",
                        company="Example",
                        source_url="https://www.linkedin.com/jobs/view/123",
                        direct_apply_url="https://apply.example.com/123",
                    )
                ],
                started_at=now,
                completed_at=now,
                success=True,
            )

    def enrich(observation, _timeout):
        observation.direct_apply_url = "https://jobs.ashbyhq.com/Example/123"
        observation.raw_payload["direct_apply_resolution"] = {"status": "resolved"}
        observation.raw_payload["ats_job_posting"] = {"url": observation.direct_apply_url}
        return observation

    monkeypatch.setattr(service, "providers", lambda _selected: [StubProvider()])
    monkeypatch.setattr("job_puller.service.enrich_observation", enrich)

    summary = service.scrape()[0]

    assert summary.metrics["direct_apply_links"] == 1
    assert summary.metrics["direct_apply_links_verified"] == 1
    assert summary.metrics["ats_postings_enriched"] == 1


def test_scrape_runs_independent_providers_concurrently(tmp_path, monkeypatch):
    db = InventoryDatabase(tmp_path / "inventory.db")
    db.migrate()
    configured = config()
    configured.provider_workers = 2
    service = InventoryService(configured, db)
    barrier = threading.Barrier(2)

    class StubProvider:
        def __init__(self, key):
            self.name = "stub"
            self.source_key = key

        def fetch(self, since, *, cancel=None):
            try:
                barrier.wait(timeout=2)
                ran_concurrently = True
            except threading.BrokenBarrierError:
                ran_concurrently = False
            now = datetime.now(UTC)
            return ProviderResult(
                source_key=self.source_key,
                provider=self.name,
                observations=[],
                started_at=now,
                completed_at=now,
                success=ran_concurrently,
                error=None if ran_concurrently else "did not overlap with the other provider",
            )

    monkeypatch.setattr(
        service, "providers", lambda _selected: [StubProvider("stub:a"), StubProvider("stub:b")]
    )

    summaries = service.scrape()

    assert {summary.source_key for summary in summaries} == {"stub:a", "stub:b"}
    assert all(summary.outcome == "healthy-empty" for summary in summaries)


def test_scrape_abandons_a_provider_that_ignores_cancellation(tmp_path, monkeypatch):
    db = InventoryDatabase(tmp_path / "inventory.db")
    db.migrate()
    configured = config()
    configured.provider_fetch_deadline_seconds = 0.2
    configured.provider_cancel_grace_seconds = 0.2
    service = InventoryService(configured, db)

    class StubProvider:
        name = "stub"
        source_key = "stub:slow"

        def fetch(self, since, *, cancel=None):
            # A non-cooperative provider: it never checks `cancel`, so the
            # deadline and the grace period both have to elapse before
            # scrape() gives up on it.
            time.sleep(5)
            now = datetime.now(UTC)
            return ProviderResult(
                source_key=self.source_key,
                provider=self.name,
                observations=[],
                started_at=now,
                completed_at=now,
                success=True,
            )

    monkeypatch.setattr(service, "providers", lambda _selected: [StubProvider()])

    started = time.monotonic()
    summary = service.scrape()[0]
    elapsed = time.monotonic() - started

    assert elapsed < 2
    assert summary.outcome == "failed"
    assert "deadline" in (summary.error or "")
    assert "cancellation" in (summary.error or "")


def test_scrape_uses_a_cooperative_providers_partial_result_when_cancelled(tmp_path, monkeypatch):
    db = InventoryDatabase(tmp_path / "inventory.db")
    db.migrate()
    configured = config()
    configured.provider_fetch_deadline_seconds = 0.2
    configured.provider_cancel_grace_seconds = 5
    service = InventoryService(configured, db)

    class StubProvider:
        name = "stub"
        source_key = "stub:cooperative"

        def fetch(self, since, *, cancel=None):
            observations = []
            for item_id in range(1000):
                if cancel is not None and cancel.is_set():
                    break
                time.sleep(0.05)
                observations.append(
                    JobObservation(
                        provider=self.name,
                        provider_job_id=str(item_id),
                        title="Backend Engineer",
                        company="Example",
                        source_url=f"https://example.com/jobs/{item_id}",
                    )
                )
            now = datetime.now(UTC)
            return ProviderResult(
                source_key=self.source_key,
                provider=self.name,
                observations=observations,
                started_at=now,
                completed_at=now,
                success=False,
                error="cancelled after exceeding fetch deadline",
            )

    monkeypatch.setattr(service, "providers", lambda _selected: [StubProvider()])
    monkeypatch.setattr(
        "job_puller.service.enrich_observation", lambda observation, _timeout: observation
    )

    started = time.monotonic()
    summary = service.scrape()[0]
    elapsed = time.monotonic() - started

    # It should notice the cancel signal on its next loop iteration (~0.05s
    # ticks) well before the 5s grace period runs out, and scrape() should
    # use that real, partial result instead of fabricating a timeout.
    assert elapsed < 2
    assert summary.outcome == "partial"
    assert summary.error == "cancelled after exceeding fetch deadline"
    assert 0 < summary.fetched < 1000


def test_scrape_skips_a_provider_still_within_its_backoff_cooldown(tmp_path, monkeypatch):
    db = InventoryDatabase(tmp_path / "inventory.db")
    db.migrate()
    configured = config()
    configured.provider_skip_after_consecutive_failures = 2
    configured.provider_skip_base_cooldown_hours = 1
    service = InventoryService(configured, db)
    recent_failure = datetime.now(UTC) - timedelta(minutes=5)
    for _ in range(2):
        db.record_result(
            ProviderResult(
                source_key="linkedin:guest",
                provider="linkedin",
                observations=[],
                started_at=recent_failure,
                completed_at=recent_failure,
                success=False,
                error="connection timeout",
            )
        )
    calls = []

    class StubProvider:
        name = "linkedin"
        source_key = "linkedin:guest"

        def fetch(self, since, *, cancel=None):
            calls.append(since)
            now = datetime.now(UTC)
            return ProviderResult(
                source_key=self.source_key,
                provider=self.name,
                observations=[],
                started_at=now,
                completed_at=now,
                success=True,
            )

    monkeypatch.setattr(service, "providers", lambda _selected: [StubProvider()])
    skips = []
    before = datetime.now(UTC) - timedelta(seconds=1)

    summaries = service.scrape(on_provider_skip=lambda key, reason: skips.append((key, reason)))

    assert calls == []
    assert summaries[0].outcome == "skipped"
    assert skips == [("linkedin:guest", summaries[0].error)]

    # The skip itself must be visible in run history (e.g. for --retry-failed
    # to tell "chose not to try" apart from "never ran"), not just printed.
    recorded = db.scrape_runs_since(before)
    assert recorded == [
        {
            "source_key": "linkedin:guest",
            "provider": "linkedin",
            "success": False,
            "suspicious_empty": False,
            "error": summaries[0].error,
            "outcome": "skipped",
            "retryable": True,
            "error_category": "backoff",
        }
    ]


def test_scrape_retries_a_provider_once_its_backoff_cooldown_elapses(tmp_path, monkeypatch):
    db = InventoryDatabase(tmp_path / "inventory.db")
    db.migrate()
    configured = config()
    configured.provider_skip_after_consecutive_failures = 2
    configured.provider_skip_base_cooldown_hours = 1
    service = InventoryService(configured, db)
    old_failure = datetime.now(UTC) - timedelta(hours=2)
    for _ in range(2):
        db.record_result(
            ProviderResult(
                source_key="linkedin:guest",
                provider="linkedin",
                observations=[],
                started_at=old_failure,
                completed_at=old_failure,
                success=False,
                error="connection timeout",
            )
        )
    calls = []

    class StubProvider:
        name = "linkedin"
        source_key = "linkedin:guest"

        def fetch(self, since, *, cancel=None):
            calls.append(since)
            now = datetime.now(UTC)
            return ProviderResult(
                source_key=self.source_key,
                provider=self.name,
                observations=[],
                started_at=now,
                completed_at=now,
                success=True,
            )

    monkeypatch.setattr(service, "providers", lambda _selected: [StubProvider()])

    summaries = service.scrape()

    assert len(calls) == 1
    assert summaries[0].outcome == "healthy-empty"


def test_scrape_isolates_a_provider_that_raises_instead_of_returning(tmp_path, monkeypatch):
    db = InventoryDatabase(tmp_path / "inventory.db")
    db.migrate()
    service = InventoryService(config(), db)

    class BrokenProvider:
        name = "stub"
        source_key = "stub:broken"

        def fetch(self, since, *, cancel=None):
            raise ValueError("provider bug, not a timeout")

    class HealthyProvider:
        name = "stub"
        source_key = "stub:healthy"

        def fetch(self, since, *, cancel=None):
            now = datetime.now(UTC)
            return ProviderResult(
                source_key=self.source_key,
                provider=self.name,
                observations=[],
                started_at=now,
                completed_at=now,
                success=True,
            )

    monkeypatch.setattr(
        service, "providers", lambda _selected: [BrokenProvider(), HealthyProvider()]
    )

    summaries = service.scrape()

    by_source = {summary.source_key: summary for summary in summaries}
    assert by_source["stub:healthy"].outcome == "healthy-empty"
    assert by_source["stub:broken"].outcome == "failed"
    assert "ValueError" in (by_source["stub:broken"].error or "")
    assert "provider bug, not a timeout" in (by_source["stub:broken"].error or "")
    assert "deadline" not in (by_source["stub:broken"].error or "")


def test_scrape_isolates_a_provider_whose_result_fails_to_record(tmp_path, monkeypatch):
    db = InventoryDatabase(tmp_path / "inventory.db")
    db.migrate()
    service = InventoryService(config(), db)

    class StubProvider:
        name = "stub"
        source_key = "stub:board"

        def fetch(self, since, *, cancel=None):
            now = datetime.now(UTC)
            return ProviderResult(
                source_key=self.source_key,
                provider=self.name,
                observations=[],
                started_at=now,
                completed_at=now,
                success=True,
            )

    def broken_record_result(_result):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(service, "providers", lambda _selected: [StubProvider()])
    monkeypatch.setattr(db, "record_result", broken_record_result)

    summaries = service.scrape()

    assert len(summaries) == 1
    assert summaries[0].outcome == "failed"
    assert summaries[0].source_key == "stub:board"
    assert "database is locked" in (summaries[0].error or "")


def test_scrape_preserves_providers_original_order_across_skips_and_dispatch(tmp_path, monkeypatch):
    db = InventoryDatabase(tmp_path / "inventory.db")
    db.migrate()
    configured = config()
    configured.provider_skip_after_consecutive_failures = 2
    configured.provider_skip_base_cooldown_hours = 1
    configured.provider_workers = 4
    service = InventoryService(configured, db)
    recent_failure = datetime.now(UTC) - timedelta(minutes=5)
    for _ in range(2):
        db.record_result(
            ProviderResult(
                source_key="stub:b",
                provider="stub",
                observations=[],
                started_at=recent_failure,
                completed_at=recent_failure,
                success=False,
                error="connection timeout",
            )
        )

    class RunnableProvider:
        def __init__(self, key):
            self.name = "stub"
            self.source_key = key

        def fetch(self, since, *, cancel=None):
            now = datetime.now(UTC)
            return ProviderResult(
                source_key=self.source_key,
                provider=self.name,
                observations=[],
                started_at=now,
                completed_at=now,
                success=True,
            )

    class SkippedProvider:
        name = "stub"
        source_key = "stub:b"

        def fetch(self, since, *, cancel=None):
            raise AssertionError("a backed-off provider must not be fetched")

    # Order: a (runnable), b (skipped), c (runnable), d (runnable) - the skip
    # sits in the middle, and dispatch order among runnable providers is not
    # guaranteed, so this can only pass if the result is reordered at the end.
    ordered_providers = [
        RunnableProvider("stub:a"),
        SkippedProvider(),
        RunnableProvider("stub:c"),
        RunnableProvider("stub:d"),
    ]
    monkeypatch.setattr(service, "providers", lambda _selected: ordered_providers)

    summaries = service.scrape()

    assert [summary.source_key for summary in summaries] == [
        "stub:a",
        "stub:b",
        "stub:c",
        "stub:d",
    ]
    assert summaries[1].outcome == "skipped"


def test_scrape_progress_counter_accounts_for_skipped_providers(tmp_path, monkeypatch):
    db = InventoryDatabase(tmp_path / "inventory.db")
    db.migrate()
    configured = config()
    configured.provider_skip_after_consecutive_failures = 2
    configured.provider_skip_base_cooldown_hours = 1
    service = InventoryService(configured, db)
    recent_failure = datetime.now(UTC) - timedelta(minutes=5)
    for _ in range(2):
        db.record_result(
            ProviderResult(
                source_key="linkedin:guest",
                provider="linkedin",
                observations=[],
                started_at=recent_failure,
                completed_at=recent_failure,
                success=False,
                error="connection timeout",
            )
        )

    class SkippedProvider:
        name = "linkedin"
        source_key = "linkedin:guest"

        def fetch(self, since, *, cancel=None):
            raise AssertionError("a backed-off provider must not be fetched")

    class RunnableProvider:
        def __init__(self, key):
            self.name = "stub"
            self.source_key = key

        def fetch(self, since, *, cancel=None):
            now = datetime.now(UTC)
            return ProviderResult(
                source_key=self.source_key,
                provider=self.name,
                observations=[],
                started_at=now,
                completed_at=now,
                success=True,
            )

    monkeypatch.setattr(
        service,
        "providers",
        lambda _selected: [
            SkippedProvider(),
            RunnableProvider("stub:a"),
            RunnableProvider("stub:b"),
        ],
    )
    starts: list[tuple[int, int]] = []

    summaries = service.scrape(
        on_provider_start=lambda index, total, source_key: starts.append((index, total))
    )

    assert len(summaries) == 3
    assert {index for index, _ in starts} == {2, 3}
    assert all(total == 3 for _, total in starts)
