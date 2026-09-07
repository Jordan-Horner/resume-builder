"""Tests for local inventory orchestration and deterministic prescreening."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import resume_builder.jobs as jobs_module
from resume_builder.jobs import (
    _contains_bounded,
    _load_preferences,
    _new_jobs,
    _prescreen,
    _prescreen_job_hash,
    _resolve_sources_after_refresh,
    _with_application_dispositions,
    _write_review_csv,
    get_job_screening_packet,
)


def job(**updates):
    payload = {
        "title": "Senior Production Support Engineer",
        "company": "Example",
        "description_text": "Python API incident response and cloud operations",
        "description_quality": "complete",
        "work_modes": ["remote"],
        "salary_min": 120000,
        "salary_currency": "USD",
    }
    payload.update(updates)
    return payload


def preferences(**updates):
    payload = {
        "accepted_work_modes": ["remote"],
        "desired_title_terms": ["production support engineer"],
        "interest_terms": ["incident response", "cloud"],
        "excluded_title_terms": [],
        "senior_title_terms": [],
        "accepted_senior_role_terms": [],
        "unwanted_title_terms": ["computer repair"],
        "excluded_companies": [],
        "job_dispositions": {},
        "accepted_location_terms": ["United States", "USA", "U.S.", "US"],
        "excluded_location_terms": ["Canada", "UK", "Netherlands", "Europe"],
        "include_unknown_locations": True,
        "minimum_salary": 100000,
    }
    payload.update(updates)
    return payload


def test_prescreen_separates_interest_constraints_and_keyword_readiness():
    result = _prescreen(job(), preferences(), {"python", "api", "incident", "cloud"})

    assert result["queue_state"] == "ready"
    assert result["interest"]["desired_title_terms"] == ["production support engineer"]
    assert result["constraints"]["work_mode_match"] is True
    assert "not an ATS score" in result["keyword_readiness"]["method"]


def test_prescreen_keeps_unwanted_and_mode_mismatch_distinct():
    unwanted = _prescreen(
        job(title="Computer Repair Technician"), preferences(), {"computer", "repair"}
    )
    onsite = _prescreen(job(work_modes=["onsite"]), preferences(), {"python"})

    assert unwanted["queue_state"] == "ready"
    assert unwanted["constraints"]["unwanted_title_terms"] == ["computer repair"]
    assert onsite["queue_state"] == "hard_conflict"
    assert onsite["review_eligible"] is True
    assert onsite["constraints"]["work_mode_match"] is False


def test_prescreen_does_not_apply_onsite_location_terms_to_remote_jobs():
    result = _prescreen(
        job(location="New York", work_modes=["remote"]),
        preferences(
            accepted_work_modes=["onsite", "remote"],
            accepted_location_terms=["Texas"],
            include_unknown_locations=False,
            screening_profile={"remote_location_terms": []},
        ),
        {"python", "api", "incident", "cloud"},
    )

    assert result["queue_state"] == "ready"
    assert result["constraints"]["location_match"] is False


def test_prescreen_does_not_apply_legacy_onsite_locations_to_remote_jobs():
    result = _prescreen(
        job(location="Canton, MA", work_modes=["remote"]),
        preferences(
            accepted_work_modes=["remote"],
            accepted_location_terms=["Florida"],
            include_unknown_locations=False,
            screening_profile={},
        ),
        {"python", "api", "incident", "cloud"},
    )

    assert result["queue_state"] == "ready"
    assert "location" not in result["constraints"]["hard_conflicts"]


def test_prescreen_hides_only_jobs_with_terminal_dispositions():
    applied = _prescreen(
        job(id="job-applied"),
        preferences(job_dispositions={"job-applied": "applied"}),
        {"python", "api", "incident", "cloud"},
    )
    other = _prescreen(
        job(id="job-other"),
        preferences(job_dispositions={"job-applied": "applied"}),
        {"python", "api", "incident", "cloud"},
    )

    assert applied["queue_state"] == "applied"
    assert applied["review_eligible"] is False
    assert applied["constraints"]["disposition"] == "applied"
    assert other["review_eligible"] is True


def test_bounded_exclusions_do_not_match_inside_other_words():
    assert _contains_bounded("Applied AI Engineer", ["PPLIED"]) == []
    assert _contains_bounded("PPLIED", ["pplied"]) == ["pplied"]


def test_bounded_exclusions_handle_company_suffixes_and_punctuation():
    assert _contains_bounded("Acme, Inc.", ["Acme"]) == ["Acme"]
    assert _contains_bounded("Acmeology", ["Acme"]) == []
    assert _contains_bounded("C# Developer", ["C#"]) == ["C#"]


def test_prescreen_company_exclusion_is_boundary_aware():
    included = _prescreen(
        job(company="Applied Systems"),
        preferences(excluded_companies=["PPLIED"]),
        {"python"},
    )
    excluded = _prescreen(
        job(company="PPLIED"),
        preferences(excluded_companies=["PPLIED"]),
        {"python"},
    )

    assert included["constraints"]["excluded_company"] is False
    assert excluded["constraints"]["excluded_company"] is True


def test_application_history_overlays_legacy_dispositions(tmp_path: Path):
    applications = tmp_path / "applications"
    applications.mkdir()
    (applications / "APP-20260902-example.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "application": {
                    "id": "APP-20260902-example",
                    "company": "Example",
                    "role": "Support Engineer",
                    "applied_on": "2026-09-02",
                    "created_at": "2026-09-02T12:00:00+00:00",
                    "job_id": "job-new-history",
                },
                "events": [
                    {
                        "id": "EVT-applied",
                        "status": "applied",
                        "effective_on": "2026-09-02",
                        "recorded_at": "2026-09-02T12:00:00+00:00",
                    },
                    {
                        "id": "EVT-rejected",
                        "status": "rejected",
                        "effective_on": "2026-09-05",
                        "recorded_at": "2026-09-05T12:00:00+00:00",
                    },
                ],
                "answers": [],
            }
        ),
        encoding="utf-8",
    )

    merged = _with_application_dispositions(
        preferences(job_dispositions={"job-legacy": "applied"}),
        applications,
    )

    assert merged["job_dispositions"] == {
        "job-legacy": "applied",
        "job-new-history": "rejected",
    }


def test_prescreen_keeps_badly_parsed_inventory_visible_for_review():
    result = _prescreen(job(company=""), preferences(), {"python", "api", "incident", "cloud"})

    assert result["queue_state"] == "needs_description"
    assert result["review_eligible"] is True
    assert result["keyword_readiness"]["percent"] <= 100


def test_prescreen_applies_configurable_title_and_location_filters():
    foreign = _prescreen(
        job(title="AI Platform Engineer-Anthropic-UK", location="UK-Remote"),
        preferences(),
        {"python"},
    )
    excluded_title = _prescreen(
        job(title="Director of Cloud SRE", location="US"),
        preferences(excluded_title_terms=["director"]),
        {"cloud"},
    )
    mixed = _prescreen(
        job(location="Remote (United States); Remote (Canada)"),
        preferences(),
        {"python", "api", "incident", "cloud"},
    )

    assert foreign["review_eligible"] is True
    assert foreign["queue_state"] == "hard_conflict"
    assert foreign["constraints"]["excluded_location_terms"] == ["UK"]
    assert excluded_title["review_eligible"] is True
    assert excluded_title["queue_state"] == "hard_conflict"
    assert excluded_title["constraints"]["excluded_title_terms"] == ["director"]
    assert mixed["review_eligible"] is True
    assert mixed["constraints"]["accepted_location_terms"] == ["United States"]


def test_location_term_matching_does_not_treat_australia_as_us():
    result = _prescreen(
        job(location="Australia", title="Cloud Engineer"),
        preferences(include_unknown_locations=False),
        {"cloud"},
    )

    assert result["constraints"]["accepted_location_terms"] == []
    assert result["review_eligible"] is True
    assert result["queue_state"] == "hard_conflict"


def test_prescreen_cache_invalidates_when_normalized_location_changes():
    original = job(
        location="Ontario, CA, US",
        description_hash="same-description",
        salary_currency="USD",
    )
    corrected = {
        **original,
        "location": "Ontario, Canada",
        "salary_currency": "CAD",
    }

    assert _prescreen_job_hash(original) != _prescreen_job_hash(corrected)


def test_senior_roles_are_allowed_only_for_configured_role_families():
    rules = preferences(
        senior_title_terms=["senior", "sr", "lead", "staff", "principal"],
        accepted_senior_role_terms=["site reliability", "SRE", "DevOps"],
    )

    qualified_family = _prescreen(
        job(title="Senior Site Reliability Engineer", location="US"),
        rules,
        {"reliability"},
    )
    unrelated_family = _prescreen(
        job(title="Senior Principal Automation Engineer - Advanced Manufacturing", location="US"),
        rules,
        {"automation"},
    )

    assert qualified_family["constraints"]["seniority_match"] is True
    assert qualified_family["review_eligible"] is True
    assert unrelated_family["constraints"]["seniority_match"] is False
    assert unrelated_family["review_eligible"] is True
    assert unrelated_family["queue_state"] == "hard_conflict"


def test_review_csv_contains_reviewable_jobs_sorted_newest_first(tmp_path: Path):
    results = [
        {
            **job(
                title="SRE",
                company="Lower",
                salary_min=100000,
                salary_max=120000,
                posted_at="2026-09-01T12:00:00Z",
            ),
            "prescreen": {"review_eligible": True},
        },
        {
            **job(
                title="SRE",
                company="Higher",
                salary_min=140000,
                salary_max=160000,
                posted_at="2026-09-02T12:00:00+00:00",
            ),
            "prescreen": {"review_eligible": True},
        },
        {
            **job(title="Azure Engineer", company="Filtered"),
            "prescreen": {"review_eligible": False},
        },
    ]
    output = tmp_path / "review.csv"

    count = _write_review_csv(results, output)

    assert count == 2
    assert output.read_text(encoding="utf-8").splitlines() == [
        "title,company,salary",
        "SRE,Higher,$140000-$160000",
        "SRE,Lower,$100000-$120000",
    ]


def test_preferences_validate_new_filter_fields(tmp_path: Path):
    path = tmp_path / "preferences.yml"
    path.write_text(
        """\
schema_version: 1
accepted_location_terms: [US]
excluded_location_terms: [UK]
excluded_title_terms: [director]
senior_title_terms: [senior, sr]
accepted_senior_role_terms: [SRE]
job_dispositions:
  job-1: applied
include_unknown_locations: false
screening_profile:
  requires_sponsorship: true
  work_mode_strength: preferred
""",
        encoding="utf-8",
    )

    loaded = _load_preferences(path)

    assert loaded["accepted_location_terms"] == ["US"]
    assert loaded["job_dispositions"] == {"job-1": "applied"}
    assert loaded["include_unknown_locations"] is False
    assert loaded["screening_profile"]["requires_sponsorship"] is True


def test_preferences_reject_unknown_screening_profile_fields(tmp_path: Path):
    path = tmp_path / "preferences.yml"
    path.write_text(
        "schema_version: 1\nscreening_profile:\n  universal_remote_default: true\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Extra inputs are not permitted"):
        _load_preferences(path)


def test_preferences_validate_shadow_personalization(tmp_path: Path):
    path = tmp_path / "preferences.yml"
    path.write_text(
        """\
schema_version: 1
personalization:
  enabled: true
  mode: shadow
  exploration_fraction: 0.2
""",
        encoding="utf-8",
    )

    loaded = _load_preferences(path)

    assert loaded["personalization"]["mode"] == "shadow"


def test_shared_screening_packet_uses_active_inventory_and_bounded_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    preferences_path = tmp_path / "preferences.yml"
    preferences_path.write_text(
        """\
schema_version: 1
accepted_work_modes: [remote]
screening_profile:
  supported_capabilities: [incident response]
""",
        encoding="utf-8",
    )

    class ScreeningInventory:
        def active_inventory(self):
            return [
                job(
                    id="fictional-shared",
                    location="Remote",
                    url="https://example.invalid/jobs/shared",
                    description_hash="fictional-hash",
                )
            ]

    monkeypatch.setattr(jobs_module, "_database", lambda _path: ScreeningInventory())
    monkeypatch.setattr(
        jobs_module, "_resume_corpus", lambda _preferences, _root=Path("."): ("incident", "h")
    )

    packet = get_job_screening_packet(
        "fictional-shared",
        config_path=tmp_path / "search.yml",
        preferences_path=preferences_path,
    )

    assert packet.job.id == "fictional-shared"
    assert packet.job.description_hash == "fictional-hash"
    assert packet.profile.supported_capabilities == ["incident response"]


class FakeInventory:
    def __init__(self):
        self.refreshed = False

    def job_ids(self):
        return {"existing"} if not self.refreshed else {"existing", "new", "inactive-new"}

    def active_inventory(self):
        return [{"id": "existing"}, {"id": "new"}]

    def active_job_ids_first_seen_since(self, _started_at):
        return set()

    def scrape_runs_since(self, _started_at):
        return [
            {
                "source_key": "test:indeed",
                "provider": "indeed",
                "success": True,
                "suspicious_empty": False,
                "error": None,
            }
        ]


def test_new_jobs_shortlists_only_canonical_database_delta(tmp_path: Path, monkeypatch):
    inventory = FakeInventory()
    manifest_path = tmp_path / "latest-refresh.json"
    captured = {}

    monkeypatch.setattr(jobs_module, "_database", lambda _path: inventory)
    monkeypatch.setattr(jobs_module, "DEFAULT_LATEST_REFRESH", manifest_path)

    def refresh(args):
        captured["provider_args"] = args
        inventory.refreshed = True
        return 0

    def shortlist(*args, **kwargs):
        captured["shortlist_args"] = args
        captured["shortlist_kwargs"] = kwargs
        return 0

    monkeypatch.setattr(jobs_module, "puller_main", refresh)
    monkeypatch.setattr(jobs_module, "_shortlist", shortlist)

    status = _new_jobs(Path("search.yml"), Path("preferences.yml"), 25, ["indeed"])

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert status == 0
    assert manifest["status"] == "complete"
    assert manifest["new_to_database_job_ids"] == ["new"]
    assert "pre_refresh_job_ids" not in manifest
    assert manifest["provider_runs"][0]["source_key"] == "test:indeed"
    assert captured["provider_args"] == [
        "--config",
        "search.yml",
        "scrape",
        "--provider",
        "indeed",
    ]
    assert captured["shortlist_kwargs"]["included_job_ids"] == {"new"}


def test_new_jobs_resolves_linkedin_sources_before_shortlisting(tmp_path: Path, monkeypatch):
    inventory = FakeInventory()
    manifest_path = tmp_path / "latest-refresh.json"
    events = []
    monkeypatch.setattr(jobs_module, "_database", lambda _path: inventory)
    monkeypatch.setattr(jobs_module, "DEFAULT_LATEST_REFRESH", manifest_path)
    monkeypatch.setattr(
        inventory,
        "scrape_runs_since",
        lambda _started_at: [{"provider": "linkedin", "success": True}],
    )

    def refresh(_args):
        inventory.refreshed = True
        events.append("refresh")
        return 0

    def resolve(*_args):
        events.append("resolve")
        return {"status": "complete", "targets": 1, "applied": 1}

    def shortlist(*_args, **_kwargs):
        events.append("shortlist")
        return 0

    monkeypatch.setattr(jobs_module, "puller_main", refresh)
    monkeypatch.setattr(jobs_module, "_resolve_sources_after_refresh", resolve)
    monkeypatch.setattr(jobs_module, "_shortlist", shortlist)

    assert _new_jobs(Path("search.yml"), Path("preferences.yml"), 25, None) == 0

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert events == ["refresh", "resolve", "shortlist"]
    assert manifest["source_resolution"] == {"status": "complete", "targets": 1, "applied": 1}


def test_automatic_source_resolution_failure_is_visible_but_nonfatal(monkeypatch):
    monkeypatch.setattr(
        jobs_module,
        "load_config",
        lambda _path: (_ for _ in ()).throw(ValueError("catalog unavailable")),
    )

    report = _resolve_sources_after_refresh(
        FakeInventory(),
        Path("search.yml"),
        jobs_module.datetime.now(jobs_module.UTC),
        [{"provider": "linkedin", "success": True}],
    )

    assert report == {
        "status": "unavailable",
        "error_category": "ValueError",
        "error": "catalog unavailable",
    }


def test_automatic_source_resolution_applies_configured_bounds(tmp_path: Path, monkeypatch):
    import job_puller.source_resolution as resolution_module

    started_at = jobs_module.datetime.now(jobs_module.UTC)
    captured = {}
    settings = SimpleNamespace(
        enabled=True,
        max_targets_per_refresh=75,
        max_board_requests_per_refresh=30,
        max_probe_companies=8,
        workers=6,
        catalog_cache_hours=12,
    )
    monkeypatch.setattr(
        jobs_module,
        "load_config",
        lambda _path: SimpleNamespace(
            source_resolution=settings,
            request_timeout_seconds=19,
        ),
    )
    monkeypatch.setattr(
        resolution_module.AtsCatalog,
        "load",
        lambda path, **kwargs: (
            captured.update(catalog_path=path, catalog_kwargs=kwargs)
            or SimpleNamespace(
                add_configured_boards=lambda _config: SimpleNamespace(
                    boards_for=lambda _company: []
                )
            )
        ),
    )
    fresh_target = SimpleNamespace(job_id="fresh", company="Fresh Co")
    backlog_target = SimpleNamespace(job_id="backlog", company="Backlog Co")
    targets = [fresh_target, backlog_target]
    target_calls = []
    monkeypatch.setattr(
        resolution_module,
        "linkedin_targets",
        lambda *_args, **kwargs: (
            target_calls.append(kwargs) or ([fresh_target] if kwargs.get("seen_since") else targets)
        ),
    )

    def resolve(database, catalog, **kwargs):
        captured.update(database=database, catalog=catalog, resolve_kwargs=kwargs)
        return resolution_module.ResolutionReport(targets=2, applied=1)

    monkeypatch.setattr(resolution_module, "resolve_linkedin_sources", resolve)
    database = FakeInventory()

    report = _resolve_sources_after_refresh(
        database,
        tmp_path / "config" / "search.yml",
        started_at,
        [{"provider": "linkedin", "success": True}],
    )

    assert report["status"] == "complete"
    assert report["targets"] == 2
    assert report["applied"] == 1
    assert captured["database"] is database
    assert captured["catalog_path"] == tmp_path / "cache" / "ats-source-catalog"
    assert captured["resolve_kwargs"] == {
        "timeout": 19,
        "apply": True,
        "include_probes": True,
        "max_probe_companies": 8,
        "max_board_requests": 30,
        "workers": 6,
        "targets": targets,
    }
    assert target_calls == [
        {"seen_since": started_at, "limit": 75},
        {},
    ]


def test_automatic_source_resolution_uses_enabled_bright_data_after_free_funnel(
    tmp_path: Path, monkeypatch
):
    import job_puller.source_resolution as resolution_module
    import resume_builder.bright_data as bright_data_module

    started_at = jobs_module.datetime.now(jobs_module.UTC)
    settings = SimpleNamespace(
        enabled=True,
        max_targets_per_refresh=75,
        max_board_requests_per_refresh=30,
        max_probe_companies=8,
        workers=6,
        catalog_cache_hours=12,
    )
    monkeypatch.setattr(
        jobs_module,
        "load_config",
        lambda _path: SimpleNamespace(
            source_resolution=settings,
            request_timeout_seconds=19,
        ),
    )
    board_discovered = False
    catalog = SimpleNamespace(boards_for=lambda _company: [object()] if board_discovered else [])
    monkeypatch.setattr(
        resolution_module.AtsCatalog,
        "load",
        lambda *_args, **_kwargs: SimpleNamespace(add_configured_boards=lambda _config: catalog),
    )
    target = resolution_module.LinkedInTarget(
        job_id="job-1",
        observation_id="observation-1",
        title="Platform Engineer",
        company="Example",
        location="",
        description="",
        posted_at=None,
        source_url="https://www.linkedin.com/jobs/view/platform-engineer-1234567890",
    )
    captured_target = resolution_module.LinkedInTarget(
        job_id=target.job_id,
        observation_id=target.observation_id,
        title=target.title,
        company=target.company,
        location=target.location,
        description=target.description,
        posted_at=target.posted_at,
        direct_apply_url="https://jobs.ashbyhq.com/example/job-1",
        source_url=target.source_url,
    )
    backlog_target = resolution_module.LinkedInTarget(
        job_id="job-old",
        observation_id="observation-old",
        title="Older Platform Engineer",
        company="Example",
        location="",
        description="",
        posted_at=None,
        source_url="https://www.linkedin.com/jobs/view/older-platform-engineer-1234567891",
    )
    target_calls = 0

    def targets(*_args, **kwargs):
        nonlocal target_calls
        target_calls += 1
        if kwargs.get("seen_since") is not None:
            return [target]
        return [captured_target, backlog_target] if target_calls == 4 else [target, backlog_target]

    monkeypatch.setattr(resolution_module, "linkedin_targets", targets)
    resolve_calls = []

    def resolve(*_args, **kwargs):
        resolve_calls.append(kwargs)
        return resolution_module.ResolutionReport(
            targets=1,
            applied=1 if len(resolve_calls) == 2 else 0,
        )

    monkeypatch.setattr(resolution_module, "resolve_linkedin_sources", resolve)
    captured = {}
    monkeypatch.setattr(
        bright_data_module,
        "load_bright_data_settings",
        lambda workspace: (
            captured.update(workspace=workspace)
            or bright_data_module.BrightDataSettings(enabled=True, max_records_per_refresh=7)
        ),
    )
    monkeypatch.setattr(bright_data_module, "bright_data_key", lambda _workspace: "token")

    def save_boards(*_args, **_kwargs):
        nonlocal board_discovered
        board_discovered = True
        return {"added": 1, "boards": [{"provider": "ashby", "id": "example"}]}

    monkeypatch.setattr(bright_data_module, "save_captured_boards", save_boards)

    def enrich(database, targets, **kwargs):
        captured.update(database=database, targets=targets, enrich_kwargs=kwargs)
        return {"status": "complete", "requested": 1, "received": 1, "applied": 1}

    monkeypatch.setattr(bright_data_module, "enrich_linkedin_targets", enrich)
    database = FakeInventory()
    workspace = tmp_path / "workspace"

    report = _resolve_sources_after_refresh(
        database,
        workspace / "job-search" / "config" / "search.yml",
        started_at,
        [{"provider": "linkedin", "success": True}],
    )

    assert report["bright_data"]["status"] == "complete"
    assert report["bright_data"]["requested"] == 1
    assert report["bright_data"]["received"] == 1
    assert report["bright_data"]["applied"] == 1
    assert report["bright_data"]["ats_followup"]["applied"] == 1
    assert captured["workspace"] == workspace
    assert captured["database"] is database
    assert captured["targets"] == [target]
    assert captured["enrich_kwargs"] == {"api_token": "token", "limit": 7, "timeout": 60}
    assert len(resolve_calls) == 2
    assert resolve_calls[1]["targets"] == [captured_target, backlog_target]
    assert resolve_calls[1]["apply"] is True
    assert resolve_calls[1]["max_board_requests"] == 7


def test_automatic_source_resolution_prioritizes_known_boards_before_target_cap(
    tmp_path: Path, monkeypatch
):
    import job_puller.source_resolution as resolution_module

    started_at = jobs_module.datetime.now(jobs_module.UTC)
    settings = SimpleNamespace(
        enabled=True,
        max_targets_per_refresh=1,
        max_board_requests_per_refresh=40,
        max_probe_companies=8,
        workers=12,
        catalog_cache_hours=24,
    )
    monkeypatch.setattr(
        jobs_module,
        "load_config",
        lambda _path: SimpleNamespace(
            source_resolution=settings,
            request_timeout_seconds=30,
        ),
    )
    fresh_target = SimpleNamespace(job_id="fresh", company="Unknown Co")
    known_backlog_target = SimpleNamespace(job_id="known", company="Known Co")
    monkeypatch.setattr(
        resolution_module,
        "linkedin_targets",
        lambda *_args, **kwargs: (
            [fresh_target] if kwargs.get("seen_since") else [fresh_target, known_backlog_target]
        ),
    )
    catalog = SimpleNamespace(
        boards_for=lambda company: [object()] if company == "Known Co" else []
    )
    monkeypatch.setattr(
        resolution_module.AtsCatalog,
        "load",
        lambda *_args, **_kwargs: SimpleNamespace(add_configured_boards=lambda _config: catalog),
    )
    captured = {}

    def resolve(_database, _catalog, **kwargs):
        captured.update(kwargs)
        return resolution_module.ResolutionReport(targets=1, applied=1)

    monkeypatch.setattr(resolution_module, "resolve_linkedin_sources", resolve)

    report = _resolve_sources_after_refresh(
        FakeInventory(),
        tmp_path / "config" / "search.yml",
        started_at,
        [{"provider": "linkedin", "success": True}],
    )

    assert report["applied"] == 1
    assert captured["targets"] == [known_backlog_target]


def test_automatic_source_resolution_skips_catalog_when_no_targets(tmp_path: Path, monkeypatch):
    import job_puller.source_resolution as resolution_module

    settings = SimpleNamespace(
        enabled=True,
        max_targets_per_refresh=100,
        max_board_requests_per_refresh=40,
        max_probe_companies=8,
        workers=12,
        catalog_cache_hours=24,
    )
    monkeypatch.setattr(
        jobs_module,
        "load_config",
        lambda _path: SimpleNamespace(
            source_resolution=settings,
            request_timeout_seconds=30,
        ),
    )
    monkeypatch.setattr(
        resolution_module,
        "linkedin_targets",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        resolution_module.AtsCatalog,
        "load",
        lambda *_args, **_kwargs: pytest.fail("catalog should not load without targets"),
    )

    report = _resolve_sources_after_refresh(
        FakeInventory(),
        tmp_path / "config" / "search.yml",
        jobs_module.datetime.now(jobs_module.UTC),
        [{"provider": "linkedin", "success": True}],
    )

    assert report["status"] == "complete"
    assert report["targets"] == 0
    assert report["board_requests_submitted"] == 0


def test_new_jobs_rejects_an_overlapping_refresh(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(jobs_module, "DEFAULT_LATEST_REFRESH", tmp_path / "latest-refresh.json")

    def locked(*_args):
        raise BlockingIOError

    monkeypatch.setattr(jobs_module.fcntl, "flock", locked)

    with pytest.raises(ValueError, match="another job discovery scan"):
        _new_jobs(Path("search.yml"), Path("preferences.yml"), 25, None)


def test_new_jobs_marks_failed_refresh_without_reusing_old_delta(tmp_path: Path, monkeypatch):
    inventory = FakeInventory()
    manifest_path = tmp_path / "latest-refresh.json"
    captured = {}

    monkeypatch.setattr(jobs_module, "_database", lambda _path: inventory)
    monkeypatch.setattr(jobs_module, "DEFAULT_LATEST_REFRESH", manifest_path)
    monkeypatch.setattr(inventory, "scrape_runs_since", lambda _started_at: [])
    monkeypatch.setattr(jobs_module, "puller_main", lambda _args: 1)
    monkeypatch.setattr(
        jobs_module,
        "_shortlist",
        lambda *args, **kwargs: captured.update(kwargs) or 0,
    )

    status = _new_jobs(Path("search.yml"), Path("preferences.yml"), 50, None)

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert status == 1
    assert manifest["status"] == "failed"
    assert manifest["new_to_database_job_ids"] == []
    assert captured["included_job_ids"] == set()


def test_new_jobs_can_retry_only_retryable_provider_types(tmp_path: Path, monkeypatch):
    inventory = FakeInventory()
    manifest_path = tmp_path / "latest-refresh.json"
    manifest_path.write_text(
        json.dumps(
            {
                "provider_runs": [
                    {"provider": "indeed", "retryable": True},
                    {"provider": "linkedin", "retryable": False},
                ]
            }
        ),
        encoding="utf-8",
    )
    captured = {}
    monkeypatch.setattr(jobs_module, "_database", lambda _path: inventory)
    monkeypatch.setattr(jobs_module, "DEFAULT_LATEST_REFRESH", manifest_path)

    def refresh(args):
        captured["provider_args"] = args
        inventory.refreshed = True
        return 0

    monkeypatch.setattr(jobs_module, "puller_main", refresh)
    monkeypatch.setattr(jobs_module, "_shortlist", lambda *args, **kwargs: 0)

    assert (
        _new_jobs(
            Path("search.yml"),
            Path("preferences.yml"),
            25,
            None,
            retry_failed=True,
        )
        == 0
    )
    assert captured["provider_args"] == [
        "--config",
        "search.yml",
        "scrape",
        "--provider",
        "indeed",
    ]


def test_new_jobs_labels_partial_provider_coverage(tmp_path: Path, monkeypatch):
    inventory = FakeInventory()
    manifest_path = tmp_path / "latest-refresh.json"
    captured = {}

    monkeypatch.setattr(jobs_module, "_database", lambda _path: inventory)
    monkeypatch.setattr(jobs_module, "DEFAULT_LATEST_REFRESH", manifest_path)

    def partial_refresh(_args):
        inventory.refreshed = True
        return 1

    monkeypatch.setattr(jobs_module, "puller_main", partial_refresh)
    monkeypatch.setattr(
        jobs_module,
        "_shortlist",
        lambda *args, **kwargs: captured.update(kwargs) or 0,
    )

    status = _new_jobs(Path("search.yml"), Path("preferences.yml"), 50, None)

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert status == 1
    assert manifest["status"] == "partial"
    assert manifest["new_to_database_job_ids"] == ["new"]
    assert captured["included_job_ids"] == {"new"}
    assert captured["heading"] == "New Jobs — Partial Refresh"


def test_new_jobs_leaves_in_progress_manifest_when_refresh_is_interrupted(
    tmp_path: Path, monkeypatch
):
    inventory = FakeInventory()
    manifest_path = tmp_path / "latest-refresh.json"

    monkeypatch.setattr(jobs_module, "_database", lambda _path: inventory)
    monkeypatch.setattr(jobs_module, "DEFAULT_LATEST_REFRESH", manifest_path)

    def interrupt(_args):
        raise KeyboardInterrupt

    monkeypatch.setattr(jobs_module, "puller_main", interrupt)

    with pytest.raises(KeyboardInterrupt):
        _new_jobs(Path("search.yml"), Path("preferences.yml"), 50, None)

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["status"] == "in_progress"
    assert manifest["new_to_database_job_ids"] == []


def test_new_jobs_recovers_jobs_created_before_an_interrupted_refresh(tmp_path: Path, monkeypatch):
    inventory = FakeInventory()
    inventory.refreshed = True
    manifest_path = tmp_path / "latest-refresh.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "status": "in_progress",
                "started_at": "2026-09-01T12:00:00+00:00",
                "new_to_database_job_ids": [],
            }
        ),
        encoding="utf-8",
    )
    captured = {}

    monkeypatch.setattr(jobs_module, "_database", lambda _path: inventory)
    monkeypatch.setattr(jobs_module, "DEFAULT_LATEST_REFRESH", manifest_path)
    monkeypatch.setattr(
        inventory,
        "active_job_ids_first_seen_since",
        lambda _started_at: {"new"},
    )
    monkeypatch.setattr(jobs_module, "puller_main", lambda _args: 0)
    monkeypatch.setattr(
        jobs_module,
        "_shortlist",
        lambda *args, **kwargs: captured.update(kwargs) or 0,
    )

    status = _new_jobs(Path("search.yml"), Path("preferences.yml"), 50, None)

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert status == 0
    assert manifest["status"] == "complete"
    assert manifest["recovered_job_ids"] == ["new"]
    assert manifest["new_to_database_job_ids"] == ["new"]
    assert captured["included_job_ids"] == {"new"}


def test_new_jobs_keeps_processing_manifest_if_shortlist_generation_fails(
    tmp_path: Path, monkeypatch
):
    inventory = FakeInventory()
    manifest_path = tmp_path / "latest-refresh.json"

    monkeypatch.setattr(jobs_module, "_database", lambda _path: inventory)
    monkeypatch.setattr(jobs_module, "DEFAULT_LATEST_REFRESH", manifest_path)

    def refresh(_args):
        inventory.refreshed = True
        return 0

    def fail_shortlist(*_args, **_kwargs):
        raise OSError("output unavailable")

    monkeypatch.setattr(jobs_module, "puller_main", refresh)
    monkeypatch.setattr(jobs_module, "_shortlist", fail_shortlist)

    with pytest.raises(OSError, match="output unavailable"):
        _new_jobs(Path("search.yml"), Path("preferences.yml"), 50, None)

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["status"] == "processing"
    assert manifest["new_to_database_job_ids"] == ["new"]


def test_resolve_sources_forwards_provider_filter(monkeypatch):
    captured = []
    monkeypatch.setattr(jobs_module, "puller_main", lambda args: captured.extend(args) or 0)

    assert (
        jobs_module.main(["resolve-sources", "--provider", "workday", "--max-requests", "100"]) == 0
    )
    provider_arg = captured.index("--provider")
    assert captured[provider_arg : provider_arg + 2] == ["--provider", "workday"]
    request_arg = captured.index("--max-requests")
    assert captured[request_arg : request_arg + 2] == ["--max-requests", "100"]
