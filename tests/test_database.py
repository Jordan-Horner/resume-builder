import json
from datetime import UTC, datetime, timedelta

from job_puller.database import MIGRATION_1, InventoryDatabase
from job_puller.models import JobObservation, ProviderResult


def observation(provider="linkedin", job_id="1", source="https://linkedin.com/jobs/view/1", direct=""):
    return JobObservation(
        provider=provider,
        provider_job_id=job_id,
        title="Senior Production Support Engineer",
        company="Example, Inc.",
        source_url=source,
        direct_apply_url=direct,
        location="United States (Remote)",
        description_html="<p>" + "Production support and API operations. " * 10 + "</p>",
        description_text="Production support and API operations. " * 10,
        remote=True,
        raw_payload={"id": job_id},
    )


def result(item, when=None, suspicious=False, success=True):
    when = when or datetime.now(UTC)
    return ProviderResult(
        source_key=f"test:{item.provider}",
        provider=item.provider,
        observations=[item],
        started_at=when - timedelta(seconds=1),
        completed_at=when,
        success=success,
        suspicious_empty=suspicious,
    )


def test_migrate_and_insert(tmp_path):
    db = InventoryDatabase(tmp_path / "inventory.db")
    db.migrate()
    inserted, updated = db.record_result(result(observation()))
    assert (inserted, updated) == (1, 0)
    assert db.stats()["jobs"] == 1
    assert db.stats()["observations"] == 1
    assert db.stats()["complete_descriptions"] == 1


def test_run_metrics_are_persisted(tmp_path):
    db = InventoryDatabase(tmp_path / "inventory.db")
    db.migrate()
    run = result(observation())
    run.metrics = {"raw_results": 10, "accepted": 1}
    db.record_result(run)
    with db.connect() as conn:
        stored = conn.execute("SELECT metrics_json FROM scrape_runs").fetchone()[0]
    assert json.loads(stored) == run.metrics


def test_existing_v1_database_migrates_to_run_metrics(tmp_path):
    db = InventoryDatabase(tmp_path / "inventory.db")
    with db.connect() as conn:
        conn.executescript(MIGRATION_1)
        conn.execute(
            "INSERT INTO schema_migrations(version, applied_at) VALUES (1, ?)",
            (datetime.now(UTC).isoformat(),),
        )

    db.migrate()

    with db.connect() as conn:
        version = conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
        columns = {row[1] for row in conn.execute("PRAGMA table_info(scrape_runs)")}
    assert version == 2
    assert "metrics_json" in columns


def test_repeated_observation_is_idempotent(tmp_path):
    db = InventoryDatabase(tmp_path / "inventory.db")
    db.migrate()
    item = observation()
    db.record_result(result(item))
    inserted, updated = db.record_result(result(item))
    assert (inserted, updated) == (0, 1)
    assert db.stats()["jobs"] == 1
    assert db.stats()["observations"] == 1


def test_provider_identity_survives_url_change(tmp_path):
    db = InventoryDatabase(tmp_path / "inventory.db")
    db.migrate()
    db.record_result(result(observation(source="https://example.com/jobs/1?ref=old")))
    inserted, updated = db.record_result(result(observation(source="https://example.com/jobs/1?ref=new")))
    assert (inserted, updated) == (0, 1)
    assert db.stats()["observations"] == 1


def test_direct_url_merges_observations_and_prefers_ats(tmp_path):
    db = InventoryDatabase(tmp_path / "inventory.db")
    db.migrate()
    ats_url = "https://boards.greenhouse.io/example/jobs/42"
    db.record_result(result(observation(direct=ats_url)))
    ats = observation(provider="greenhouse", job_id="42", source=ats_url, direct=ats_url)
    db.record_result(result(ats))
    assert db.stats()["jobs"] == 1
    assert db.stats()["observations"] == 2
    with db.connect() as conn:
        row = conn.execute("SELECT canonical_apply_url FROM jobs").fetchone()
        assert row[0] == ats_url


def test_successful_run_advances_checkpoint(tmp_path):
    db = InventoryDatabase(tmp_path / "inventory.db")
    db.migrate()
    when = datetime.now(UTC).replace(microsecond=0)
    db.record_result(result(observation(), when=when))
    assert db.checkpoint("test:linkedin") == when


def test_suspicious_empty_does_not_advance_checkpoint(tmp_path):
    db = InventoryDatabase(tmp_path / "inventory.db")
    db.migrate()
    when = datetime.now(UTC)
    empty = ProviderResult("test:linkedin", "linkedin", [], when, when, True, suspicious_empty=True)
    db.record_result(empty)
    assert db.checkpoint("test:linkedin") is None


def test_two_authoritative_absences_close_without_deleting(tmp_path):
    db = InventoryDatabase(tmp_path / "inventory.db")
    db.migrate()
    first_time = datetime.now(UTC).replace(microsecond=0)
    first = observation(provider="greenhouse", job_id="1", source="https://boards.example/jobs/1")
    initial = result(first, when=first_time)
    initial.authoritative_complete = True
    db.record_result(initial)

    replacement = observation(provider="greenhouse", job_id="2", source="https://boards.example/jobs/2")
    second = result(replacement, when=first_time + timedelta(hours=1))
    second.authoritative_complete = True
    db.record_result(second)
    with db.connect() as conn:
        status = conn.execute("SELECT status FROM jobs WHERE canonical_apply_url LIKE '%/1'").fetchone()[0]
    assert status == "possibly_closed"

    third = result(replacement, when=first_time + timedelta(hours=2))
    third.authoritative_complete = True
    db.record_result(third)
    with db.connect() as conn:
        rows = conn.execute("SELECT status FROM jobs ORDER BY canonical_apply_url").fetchall()
    assert [row[0] for row in rows] == ["closed", "active"]


def test_similarity_creates_review_suggestion_not_merge(tmp_path):
    db = InventoryDatabase(tmp_path / "inventory.db")
    db.migrate()
    db.record_result(result(observation(job_id="1", source="https://example.com/jobs/1")))
    db.record_result(result(observation(job_id="2", source="https://example.com/jobs/2")))
    assert db.stats()["jobs"] == 2
    with db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM possible_duplicates").fetchone()[0] == 1
