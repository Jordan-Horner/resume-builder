"""Tests for local inventory orchestration and deterministic prescreening."""

import json
from pathlib import Path

import pytest

import resume_builder.jobs as jobs_module
from resume_builder.jobs import (
    _load_preferences,
    _new_jobs,
    _prescreen,
    _prescreen_job_hash,
    _write_review_csv,
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

    assert result["category"] == "SCREEN NEXT"
    assert result["interest"]["desired_title_terms"] == ["production support engineer"]
    assert result["constraints"]["work_mode_match"] is True
    assert "not an ATS score" in result["keyword_readiness"]["method"]


def test_prescreen_keeps_unwanted_and_mode_mismatch_distinct():
    unwanted = _prescreen(
        job(title="Computer Repair Technician"), preferences(), {"computer", "repair"}
    )
    onsite = _prescreen(job(work_modes=["onsite"]), preferences(), {"python"})

    assert unwanted["category"] == "EASY BUT UNWANTED"
    assert onsite["category"] == "SKIP"
    assert onsite["constraints"]["work_mode_match"] is False


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

    assert applied["category"] == "APPLIED"
    assert applied["review_eligible"] is False
    assert applied["constraints"]["disposition"] == "applied"
    assert other["review_eligible"] is True


def test_prescreen_never_promotes_badly_parsed_inventory():
    result = _prescreen(job(company=""), preferences(), {"python", "api", "incident", "cloud"})

    assert result["category"] == "NEEDS REVIEW"
    assert result["review_eligible"] is False
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

    assert foreign["review_eligible"] is False
    assert foreign["constraints"]["excluded_location_terms"] == ["UK"]
    assert excluded_title["review_eligible"] is False
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
    assert result["review_eligible"] is False


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
    assert unrelated_family["review_eligible"] is False


def test_review_csv_contains_only_eligible_jobs_sorted_by_title_and_salary(tmp_path: Path):
    results = [
        {
            **job(title="SRE", company="Lower", salary_min=100000, salary_max=120000),
            "prescreen": {"review_eligible": True},
        },
        {
            **job(title="SRE", company="Higher", salary_min=140000, salary_max=160000),
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
""",
        encoding="utf-8",
    )

    loaded = _load_preferences(path)

    assert loaded["accepted_location_terms"] == ["US"]
    assert loaded["job_dispositions"] == {"job-1": "applied"}
    assert loaded["include_unknown_locations"] is False


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
