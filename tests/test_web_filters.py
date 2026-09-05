import json

import pytest

from resume_builder.web_filters import ViewFilters, matches_view
from resume_builder.web_service import DashboardService


def listing(**overrides):
    return {
        "id": "one",
        "title": "Senior Support Engineer",
        "company": "Example",
        "work_modes": ["remote"],
        "location": "USA",
        "salary_min": 80_000,
        "salary_max": 120_000,
        "salary_currency": "USD",
        "salary_interval": "yearly",
        "employment_type": "fulltime",
        **overrides,
    }


def test_legacy_roles_do_not_hide_jobs_and_modes_use_any_selected_option():
    view = ViewFilters(
        roles=["Platform Engineer", "Support Engineer"], workModes=["remote", "hybrid"]
    )
    assert matches_view(listing(), view)
    assert matches_view(listing(work_modes=["hybrid"]), view)
    assert not matches_view(listing(work_modes=["onsite"]), view)
    assert matches_view(listing(title="Production Support Analyst"), view)
    assert matches_view(listing(work_modes=[]), view)
    assert not matches_view(
        listing(work_modes=[]), view.model_copy(update={"includeUnknownMode": False})
    )


def test_locations_use_aliases_and_cities_do_not_exclude_remote():
    view = ViewFilters(country="United States", locations=["Boston"])
    assert matches_view(listing(location="U.S.A."), view)
    assert matches_view(listing(location="Boston, MA", work_modes=["onsite"]), view)
    assert not matches_view(listing(location="Austin, TX", work_modes=["onsite"]), view)
    assert not matches_view(listing(location="Australia"), view)
    assert matches_view(listing(location="Remote"), view)
    assert matches_view(
        listing(location="Remote"), view.model_copy(update={"includeUnmatchedLocation": True})
    )


def test_minimum_uses_range_ceiling_and_explicit_unknown_policy():
    view = ViewFilters(minimumPay=100_000)
    assert matches_view(listing(), view)
    assert not matches_view(listing(salary_max=90_000), view)
    assert matches_view(listing(salary_max=100_000), view)
    assert matches_view(listing(salary_min=None, salary_max=None), view)
    strict = view.model_copy(update={"includeUnknownPay": False})
    assert not matches_view(listing(salary_min=None, salary_max=None), strict)
    assert not matches_view(listing(salary_currency="CAD"), strict)
    assert not matches_view(listing(salary_interval="hourly"), strict)
    assert matches_view(
        listing(salary_min=40, salary_max=60, salary_interval="hourly"),
        ViewFilters(minimumPay=50, period="hour"),
    )


def test_multiple_employment_types_filter_inventory(tmp_path):
    service = DashboardService(
        tmp_path,
        inventory_loader=lambda: [
            listing(),
            listing(id="two", employment_type="contract"),
            listing(id="three", employment_type="parttime"),
        ],
    )
    view = ViewFilters(employmentTypes=["fulltime", "contract"])
    assert [item["id"] for item in service.list_jobs(view_filters=view.model_dump_json())] == [
        "one",
        "two",
    ]


def test_country_scope_applies_to_all_providers_and_cannot_be_cleared(tmp_path, monkeypatch):
    jobs = [
        listing(id="us", providers=["greenhouse"], location="Boston, MA"),
        listing(id="foreign", providers=["ashby"], location="Toronto, Canada"),
        listing(id="unknown", providers=["linkedin"], location="Remote"),
    ]
    service = DashboardService(tmp_path, inventory_loader=lambda: jobs)
    monkeypatch.setattr(service, "job_filter_defaults", lambda: {"country": "United States"})
    for view in [ViewFilters(), ViewFilters(country="Canada", includeUnmatchedLocation=True)]:
        assert [item["id"] for item in service.list_jobs(view_filters=view.model_dump_json())] == [
            "us",
            "unknown",
        ]
    assert service.get_job("foreign") is not None


def test_country_scope_keeps_bare_city_and_respects_explicit_country(tmp_path, monkeypatch):
    jobs = [
        listing(id="city", location="San Francisco", work_modes=["onsite"]),
        listing(id="foreign", location="San Francisco", country="Canada"),
        listing(id="remote", location="Remote"),
    ]
    service = DashboardService(tmp_path, inventory_loader=lambda: jobs)
    monkeypatch.setattr(service, "job_filter_defaults", lambda: {"country": "United States"})
    assert [item["id"] for item in service.list_jobs()] == ["city", "remote"]
    assert [
        item["id"]
        for item in service.list_jobs(
            view_filters=ViewFilters(locations=["Boston"]).model_dump_json()
        )
    ] == ["remote"]


def test_local_state_filter_preserves_remote_but_not_foreign_remote():
    view = ViewFilters(country="USA", locations=["Massachusetts"])
    assert matches_view(listing(location="Boston, MA", work_modes=["hybrid"]), view)
    assert not matches_view(listing(location="Austin, TX", work_modes=["hybrid"]), view)
    assert matches_view(listing(location="Austin, TX", work_modes=["remote"]), view)
    assert not matches_view(listing(location="Toronto, Canada", work_modes=["remote"]), view)


def test_defaults_load_preferences_without_mutation(tmp_path):
    import yaml

    from resume_builder.job_setup_defaults import neutral_preferences

    preferences = neutral_preferences()
    preferences.update(
        desired_title_terms=["Support Engineer"],
        accepted_work_modes=["remote", "hybrid"],
        accepted_location_terms=["Boston"],
        minimum_salary=100_000,
        preferred_salary=125_000,
        salary_currency="USD",
        salary_period="year",
    )
    preferences["screening_profile"]["intended_work_country"] = "United States"
    path = tmp_path / "job-search/preferences.yml"
    path.parent.mkdir()
    path.write_text(yaml.safe_dump(preferences))
    original = path.read_bytes()
    service = DashboardService(tmp_path, inventory_loader=lambda: [])
    defaults = service.job_filter_defaults()
    assert defaults["roles"] == []
    assert defaults["workModes"] == ["remote", "hybrid"]
    assert defaults["country"] == "United States"
    assert defaults["locations"] == []
    assert defaults["minimumPay"] == 100_000
    assert "preferred_salary" not in defaults
    assert path.read_bytes() == original


@pytest.mark.parametrize(
    "values", [{"minimumPay": -1}, {"workModes": ["invalid"]}, {"period": "fortnight"}]
)
def test_reject_invalid_filter_payload(tmp_path, values):
    with pytest.raises(ValueError):
        DashboardService(tmp_path, inventory_loader=lambda: []).list_jobs(
            view_filters=json.dumps(values)
        )


def test_api_filters_before_count_and_limit(tmp_path, monkeypatch):
    pytest.importorskip("multipart")
    from fastapi.testclient import TestClient

    from resume_builder.web import create_app

    monkeypatch.setattr(
        DashboardService,
        "_load_inventory",
        lambda self: [
            listing(id="one"),
            listing(id="two"),
            listing(id="three", title="Accountant"),
        ],
    )
    client = TestClient(create_app(tmp_path))
    response = client.get(
        "/api/jobs",
        params={
            "view_filters": ViewFilters(roles=["Support Engineer"]).model_dump_json(),
            "limit": 1,
        },
    )
    assert response.status_code == 200
    assert response.json()["count"] == 3
    assert len(response.json()["jobs"]) == 1
    assert client.get("/api/jobs", params={"view_filters": '{"minimumPay":-1}'}).status_code == 400
