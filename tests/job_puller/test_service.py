from datetime import UTC, datetime, timedelta

from job_puller.config import InventoryConfig
from job_puller.database import InventoryDatabase
from job_puller.models import ProviderResult
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

        def fetch(self, since):
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

        def fetch(self, since):
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
