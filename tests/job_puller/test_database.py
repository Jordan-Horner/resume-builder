import json
from datetime import UTC, datetime, timedelta

from job_puller.database import MIGRATION_1, InventoryDatabase
from job_puller.models import JobObservation, ProviderResult
from job_puller.work_modes import WorkMode, explicit_arrangement


def observation(
    provider="linkedin",
    job_id="1",
    source="https://linkedin.com/jobs/view/1",
    direct="",
    description="Production support and API operations. ",
):
    return JobObservation(
        provider=provider,
        provider_job_id=job_id,
        title="Senior Production Support Engineer",
        company="Example, Inc.",
        source_url=source,
        direct_apply_url=direct,
        location="United States (Remote)",
        description_html="<p>" + description * 10 + "</p>",
        description_text=description * 10,
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


def test_active_inventory_exposes_stable_consumer_projection(tmp_path):
    db = InventoryDatabase(tmp_path / "inventory.db")
    db.migrate()
    db.record_result(result(observation(direct="https://example.com/apply/1")))

    inventory = db.active_inventory()
    assert len(inventory) == 1
    assert inventory[0]["company"] == "Example, Inc."
    assert inventory[0]["title"] == "Senior Production Support Engineer"
    assert inventory[0]["description_quality"] == "complete"
    assert inventory[0]["work_modes"] == ["remote"]
    assert inventory[0]["providers"] == ["linkedin"]
    assert inventory[0]["url"] == "https://example.com/apply/1"


def test_job_ids_include_inactive_canonical_jobs(tmp_path):
    db = InventoryDatabase(tmp_path / "inventory.db")
    db.migrate()
    db.record_result(result(observation()))
    job_id = next(iter(db.job_ids()))
    with db.connect() as conn:
        conn.execute("UPDATE jobs SET status='closed' WHERE id=?", (job_id,))

    assert db.active_inventory() == []
    assert db.job_ids() == {job_id}


def test_active_job_ids_first_seen_since_excludes_historical_and_closed_jobs(tmp_path):
    db = InventoryDatabase(tmp_path / "inventory.db")
    db.migrate()
    started_at = datetime.now(UTC) - timedelta(minutes=1)
    db.record_result(result(observation(job_id="new")))
    active_id = next(iter(db.job_ids()))
    closed = observation(job_id="closed", source="https://example.com/closed")
    closed.company = "Closed Example, Inc."
    db.record_result(result(closed))
    closed_id = next(job_id for job_id in db.job_ids() if job_id != active_id)
    recent = observation(
        job_id="recent",
        source="https://example.com/recent",
        description="Distinct recent infrastructure engineering description. ",
    )
    recent.company = "Recent Example, Inc."
    db.record_result(result(recent))
    recent_id = next(job_id for job_id in db.job_ids() if job_id not in {active_id, closed_id})
    with db.connect() as conn:
        conn.execute("UPDATE jobs SET status='closed' WHERE id=?", (closed_id,))
        conn.execute(
            "UPDATE jobs SET first_seen_at=? WHERE id=?",
            ((started_at - timedelta(days=1)).isoformat(), active_id),
        )

    assert db.active_job_ids_first_seen_since(started_at) == {recent_id}


def test_run_metrics_are_persisted(tmp_path):
    db = InventoryDatabase(tmp_path / "inventory.db")
    db.migrate()
    run = result(observation())
    run.metrics = {"raw_results": 10, "accepted": 1}
    db.record_result(run)
    with db.connect() as conn:
        stored = conn.execute("SELECT metrics_json FROM scrape_runs").fetchone()[0]
    assert json.loads(stored) == run.metrics


def test_scrape_runs_since_reports_provider_coverage(tmp_path):
    db = InventoryDatabase(tmp_path / "inventory.db")
    db.migrate()
    started_at = datetime.now(UTC) - timedelta(minutes=1)
    db.record_result(result(observation()))

    runs = db.scrape_runs_since(started_at)

    assert runs == [
        {
            "source_key": "test:linkedin",
            "provider": "linkedin",
            "success": True,
            "suspicious_empty": False,
            "error": None,
            "outcome": "healthy",
            "retryable": False,
            "error_category": None,
        }
    ]


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
    assert version == 7
    assert "metrics_json" in columns
    with db.connect() as conn:
        cache_table = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='provider_detail_cache'"
        ).fetchone()
    assert cache_table is not None
    with db.connect() as conn:
        mode_tables = {
            row[0]
            for row in conn.execute(
                """SELECT name FROM sqlite_master
                   WHERE type='table' AND name IN ('observation_work_modes','job_work_modes')"""
            )
        }
    assert mode_tables == {"observation_work_modes", "job_work_modes"}
    with db.connect() as conn:
        repost_table = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='possible_reposts'"
        ).fetchone()
    assert repost_table is not None


def test_source_health_exposes_latest_outcome_and_problem_streak(tmp_path):
    db = InventoryDatabase(tmp_path / "inventory.db")
    db.migrate()
    healthy = result(observation(), datetime(2026, 8, 1, tzinfo=UTC))
    db.record_result(healthy)
    for day in (2, 3):
        failed = ProviderResult(
            source_key="test:linkedin",
            provider="linkedin",
            observations=[],
            started_at=datetime(2026, 8, day, tzinfo=UTC),
            completed_at=datetime(2026, 8, day, 0, 1, tzinfo=UTC),
            success=False,
            error="connection timeout",
        )
        db.record_result(failed)

    assert db.source_health()[0]["outcome"] == "failed"
    assert db.source_health()[0]["problem_streak"] == 2
    assert db.source_health()[0]["retryable"] is True


def test_possible_reposts_require_distinct_dates_and_posting_identities(tmp_path):
    db = InventoryDatabase(tmp_path / "inventory.db")
    db.migrate()
    start = datetime(2026, 7, 1, tzinfo=UTC)
    first = observation(job_id="old", source="https://example.com/jobs/old")
    first.description_text = "First version of the production support role. " * 10
    first.description_html = f"<p>{first.description_text}</p>"
    second = observation(job_id="new", source="https://example.com/jobs/new")
    second.description_text = "Later version with a sufficiently different description. " * 10
    second.description_html = f"<p>{second.description_text}</p>"
    db.record_result(result(first, start))
    db.record_result(result(second, start + timedelta(days=30)))
    with db.connect() as conn:
        earlier_job_id = conn.execute(
            "SELECT id FROM jobs WHERE first_seen_at=?", (start.isoformat(),)
        ).fetchone()[0]
        conn.execute(
            "UPDATE jobs SET status='closed', closed_at=? WHERE id=?",
            ((start + timedelta(days=15)).isoformat(), earlier_job_id),
        )

    candidates = db.possible_reposts()

    assert len(candidates) == 1
    assert candidates[0]["first_seen_gap_days"] == 30
    assert candidates[0]["confidence"] == 0.85
    with db.connect() as conn:
        stored = conn.execute("SELECT COUNT(*) FROM possible_reposts").fetchone()[0]
    assert stored == 0


def test_possible_reposts_exclude_concurrent_roles_and_aggregators(tmp_path):
    db = InventoryDatabase(tmp_path / "inventory.db")
    db.migrate()
    start = datetime(2026, 7, 1, tzinfo=UTC)
    first = observation(job_id="one", source="https://example.com/jobs/one")
    first.description_text = "First distinct role description. " * 10
    first.description_html = f"<p>{first.description_text}</p>"
    second = observation(job_id="two", source="https://example.com/jobs/two")
    second.description_text = "Second distinct role description. " * 10
    second.description_html = f"<p>{second.description_text}</p>"
    db.record_result(result(first, start))
    db.record_result(result(second, start))
    assert db.possible_reposts() == []

    with db.connect() as conn:
        jobs = conn.execute("SELECT id FROM jobs ORDER BY id").fetchall()
        conn.execute(
            "UPDATE jobs SET first_seen_at=? WHERE id=?",
            ((start + timedelta(days=30)).isoformat(), jobs[-1][0]),
        )
    assert db.possible_reposts(aggregator_companies={"Example, Inc."}) == []


def test_possible_reposts_exclude_overlapping_active_postings(tmp_path):
    db = InventoryDatabase(tmp_path / "inventory.db")
    db.migrate()
    start = datetime(2026, 7, 1, tzinfo=UTC)
    first = observation(job_id="one", source="https://example.com/jobs/one")
    first.description_text = "First concurrently active role description. " * 10
    second = observation(job_id="two", source="https://example.com/jobs/two")
    second.description_text = "Second concurrently active role description. " * 10
    db.record_result(result(first, start))
    db.record_result(result(second, start + timedelta(days=30)))

    assert db.possible_reposts() == []


def test_legacy_false_remote_is_persisted_as_unknown_not_onsite(tmp_path):
    db = InventoryDatabase(tmp_path / "inventory.db")
    db.migrate()
    item = observation()
    item.remote = False
    item.work_arrangement = None
    item.__post_init__()

    db.record_result(result(item))

    with db.connect() as conn:
        observation_modes = conn.execute("SELECT mode FROM observation_work_modes").fetchall()
        job = conn.execute("SELECT work_mode FROM jobs").fetchone()
        job_modes = conn.execute("SELECT mode FROM job_work_modes").fetchall()
    assert [row[0] for row in observation_modes] == ["unknown"]
    assert job[0] == "unknown"
    assert [row[0] for row in job_modes] == ["unknown"]


def test_multiple_explicit_work_modes_are_preserved(tmp_path):
    db = InventoryDatabase(tmp_path / "inventory.db")
    db.migrate()
    item = observation()
    item.work_arrangement = explicit_arrangement(
        [WorkMode.REMOTE, WorkMode.ONSITE],
        source="provider",
        rule="structured_locations",
    )

    db.record_result(result(item))

    with db.connect() as conn:
        observation_modes = {
            row[0] for row in conn.execute("SELECT mode FROM observation_work_modes")
        }
        job = conn.execute("SELECT work_mode FROM jobs").fetchone()
        job_modes = {row[0] for row in conn.execute("SELECT mode FROM job_work_modes")}
    assert observation_modes == {"remote", "onsite"}
    assert job[0] == "mixed"
    assert job_modes == {"remote", "onsite"}


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
    inserted, updated = db.record_result(
        result(observation(source="https://example.com/jobs/1?ref=new"))
    )
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


def test_verified_greenhouse_redirect_merges_without_losing_observations(tmp_path):
    db = InventoryDatabase(tmp_path / "inventory.db")
    db.migrate()
    short_url = "https://grnh.se/example"
    target_url = "https://job-boards.greenhouse.io/example/jobs/42?gh_src=example"
    commercial = observation(
        provider="indeed",
        job_id="indeed-42",
        direct=short_url,
        description="Short syndicated description. ",
    )
    ats = observation(
        provider="greenhouse",
        job_id="42",
        source="https://job-boards.greenhouse.io/example/jobs/42",
        direct="https://job-boards.greenhouse.io/example/jobs/42",
        description="Complete direct ATS description. ",
    )
    db.record_result(result(commercial))
    db.record_result(result(ats))
    assert db.stats()["jobs"] == 2

    recorded, updated, merged = db.record_verified_redirects([(short_url, target_url)])

    assert (recorded, updated, merged) == (1, 1, 1)
    assert db.stats()["jobs"] == 1
    assert db.stats()["observations"] == 2
    with db.connect() as conn:
        providers = {row[0] for row in conn.execute("SELECT provider FROM observations").fetchall()}
        merge_reasons = {
            row[0]
            for row in conn.execute("SELECT merge_reason FROM job_observation_links").fetchall()
        }
    assert providers == {"indeed", "greenhouse"}
    assert "canonical_url" in merge_reasons


def test_verified_alias_prevents_future_greenhouse_duplicate(tmp_path):
    db = InventoryDatabase(tmp_path / "inventory.db")
    db.migrate()
    short_url = "https://grnh.se/example"
    target_url = "https://job-boards.greenhouse.io/example/jobs/42"
    db.record_verified_redirects([(short_url, target_url)])
    db.record_result(
        result(
            observation(
                provider="indeed",
                job_id="indeed-42",
                direct=short_url,
                description="Syndicated description. ",
            )
        )
    )
    db.record_result(
        result(
            observation(
                provider="greenhouse",
                job_id="42",
                source=target_url,
                direct=target_url,
                description="Direct description. ",
            )
        )
    )
    assert db.stats()["jobs"] == 1
    assert db.stats()["observations"] == 2


def test_workday_requisition_identity_merges_url_variants(tmp_path):
    db = InventoryDatabase(tmp_path / "inventory.db")
    db.migrate()
    commercial = observation(
        provider="indeed",
        job_id="indeed-r29937",
        direct=(
            "https://example.wd5.myworkdayjobs.com/en-US/Careers/job/Remote/Senior-Engineer_R29937"
        ),
        description="Syndicated description. ",
    )
    ats = observation(
        provider="workday",
        job_id="R29937",
        source="https://example.wd5.myworkdayjobs.com/job/Remote/Senior-Engineer_R29937",
        direct="https://example.wd5.myworkdayjobs.com/job/Remote/Senior-Engineer_R29937",
        description="Direct Workday description. ",
    )
    db.record_result(result(commercial))
    db.record_result(result(ats))
    assert db.stats()["jobs"] == 1
    assert db.stats()["observations"] == 2


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

    replacement = observation(
        provider="greenhouse",
        job_id="2",
        source="https://boards.example/jobs/2",
        description="A different active requisition. ",
    )
    second = result(replacement, when=first_time + timedelta(hours=1))
    second.authoritative_complete = True
    db.record_result(second)
    with db.connect() as conn:
        status = conn.execute(
            "SELECT status FROM jobs WHERE canonical_apply_url LIKE '%/1'"
        ).fetchone()[0]
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
    db.record_result(
        result(
            observation(
                job_id="2",
                source="https://example.com/jobs/2",
                description="A similar title with different responsibilities. ",
            )
        )
    )
    assert db.stats()["jobs"] == 2
    with db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM possible_duplicates").fetchone()[0] == 1


def test_exact_company_title_description_merges_location_variants(tmp_path):
    db = InventoryDatabase(tmp_path / "inventory.db")
    db.migrate()
    first = observation(job_id="1", source="https://example.com/jobs/1")
    second = observation(job_id="2", source="https://example.com/jobs/2")
    second.location = "Remote, New York"
    db.record_result(result(first))
    db.record_result(result(second))
    assert db.stats()["jobs"] == 1
    assert db.stats()["observations"] == 2
    with db.connect() as conn:
        reasons = {row[0] for row in conn.execute("SELECT merge_reason FROM job_observation_links")}
    assert reasons == {"new_canonical_job", "exact_company_title_description"}


def test_provider_detail_cache_is_parser_versioned(tmp_path):
    db = InventoryDatabase(tmp_path / "inventory.db")
    db.migrate()
    fetched = datetime.now(UTC)
    expires = fetched + timedelta(hours=24)
    db.put_provider_detail("linkedin", "123", "parser-v1", "<html>one</html>", fetched, expires)
    entry = db.get_provider_detail("linkedin", "123", "parser-v1")
    assert entry is not None
    assert entry.response_body == "<html>one</html>"
    assert entry.expires_at == expires
    assert db.get_provider_detail("linkedin", "123", "parser-v2") is None


def test_reconcile_existing_exact_duplicates_preserves_observations(tmp_path):
    db = InventoryDatabase(tmp_path / "inventory.db")
    db.migrate()
    first = observation(job_id="1", source="https://example.com/jobs/1")
    second = observation(
        job_id="2",
        source="https://example.com/jobs/2",
        description="Initially different responsibilities. ",
    )
    db.record_result(result(first))
    db.record_result(result(second))
    with db.transaction() as conn:
        target = conn.execute(
            "SELECT description_text, description_hash FROM jobs ORDER BY first_seen_at, id LIMIT 1"
        ).fetchone()
        conn.execute(
            """UPDATE jobs SET description_text=?, description_hash=?
               WHERE id<>(SELECT id FROM jobs ORDER BY first_seen_at, id LIMIT 1)""",
            (target[0], target[1]),
        )

    assert db.reconcile_exact_duplicates() == 1
    assert db.stats()["jobs"] == 1
    assert db.stats()["observations"] == 2
