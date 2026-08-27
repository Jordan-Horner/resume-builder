"""Tests for local inventory orchestration and deterministic prescreening."""

from resume_builder.jobs import _prescreen


def job(**updates):
    payload = {
        "title": "Senior Production Support Engineer",
        "company": "Example",
        "description_text": "Python API incident response and cloud operations",
        "description_quality": "complete",
        "work_modes": ["remote"],
        "salary_min": 120000,
    }
    payload.update(updates)
    return payload


def preferences(**updates):
    payload = {
        "accepted_work_modes": ["remote"],
        "desired_title_terms": ["production support engineer"],
        "interest_terms": ["incident response", "cloud"],
        "unwanted_title_terms": ["computer repair"],
        "excluded_companies": [],
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
    assert result["keyword_readiness"]["percent"] <= 100
