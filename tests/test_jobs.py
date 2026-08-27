"""Tests for local inventory orchestration and deterministic prescreening."""

from pathlib import Path

from resume_builder.jobs import _load_preferences, _prescreen, _write_review_csv


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
include_unknown_locations: false
""",
        encoding="utf-8",
    )

    loaded = _load_preferences(path)

    assert loaded["accepted_location_terms"] == ["US"]
    assert loaded["include_unknown_locations"] is False
