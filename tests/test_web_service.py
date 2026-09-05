import json
from datetime import UTC, datetime, timedelta

import pytest

from resume_builder import web_service
from resume_builder.web_service import DashboardService, _clean_description
from resume_builder.workspace import initialize_workspace


def job(job_id: str, *, title: str, mode: str, company: str = "Example") -> dict:
    return {
        "id": job_id,
        "title": title,
        "company": company,
        "location": "New York, NY",
        "employment_type": "fulltime",
        "salary_min": 100_000,
        "salary_max": 140_000,
        "salary_currency": "USD",
        "salary_interval": "yearly",
        "posted_at": "2026-09-01T12:00:00+00:00",
        "first_seen_at": "2026-09-02T12:00:00+00:00",
        "last_seen_at": "2026-09-03T12:00:00+00:00",
        "description_text": f"A {mode} role supporting production systems.",
        "work_modes": [mode],
        "providers": ["linkedin"],
        "url": f"https://example.com/{job_id}",
    }


@pytest.mark.parametrize("source", ["saved", "environment", "none"])
def test_openrouter_status_uses_same_credentials_after_restart(tmp_path, monkeypatch, source):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("RESUME_BUILDER_OPENROUTER_KEY_FILE", raising=False)
    service = DashboardService(tmp_path)
    token = "synthetic-test-credential"
    if source == "saved":
        service._save_openrouter_key(token)
    elif source == "environment":
        monkeypatch.setenv("OPENROUTER_API_KEY", token)
    restarted = DashboardService(tmp_path)
    status = next(item for item in restarted.list_integrations() if item["id"] == "openrouter")
    assert (status["status"] == "connected") == restarted._openrouter_configured()
    assert restarted._openrouter_configured() == (source != "none")
    assert token not in json.dumps(status)


@pytest.fixture
def inventory() -> list[dict]:
    return [
        job("remote-1", title="Support Engineer", mode="remote"),
        job("hybrid-1", title="Platform Engineer", mode="hybrid", company="Acme"),
        job("onsite-1", title="Systems Engineer", mode="onsite"),
    ]


def test_jobs_are_searchable_filterable_and_only_leave_after_disposition(
    tmp_path, inventory, monkeypatch
):
    monkeypatch.setattr(web_service, "iter_records", lambda _root: [])
    service = DashboardService(tmp_path, inventory_loader=lambda: inventory)

    assert [item["id"] for item in service.list_jobs(work_mode="hybrid")] == ["hybrid-1"]
    assert [item["id"] for item in service.list_jobs(search="acme")] == ["hybrid-1"]

    assert service.get_job("hybrid-1") is not None
    assert [item["id"] for item in service.list_jobs()] == [
        "remote-1",
        "hybrid-1",
        "onsite-1",
    ]

    service.mark_not_interested("hybrid-1")

    assert [item["id"] for item in service.list_jobs()] == ["remote-1", "onsite-1"]
    state = json.loads((tmp_path / "job-search/dashboard-state.json").read_text())
    assert state == {"schema_version": 2, "dismissed_job_ids": ["hybrid-1"]}


def test_mark_applied_creates_application_and_removes_job_from_queue(tmp_path, inventory):
    service = DashboardService(tmp_path, inventory_loader=lambda: inventory)

    record = service.mark_applied("remote-1")

    assert record["application"]["job_id"] == "remote-1"
    assert record["events"][0]["status"] == "applied"
    assert [item["id"] for item in service.list_jobs()] == ["hybrid-1", "onsite-1"]
    application = service.list_applications()[0]
    assert application["role"] == "Support Engineer"
    assert application["current_status"] == "applied"


def test_applied_jobs_do_not_appear_in_review_queue(tmp_path, inventory, monkeypatch):
    monkeypatch.setattr(
        web_service,
        "iter_records",
        lambda _root: [(tmp_path / "APP.json", {"application": {"job_id": "remote-1"}})],
    )
    service = DashboardService(tmp_path, inventory_loader=lambda: inventory)

    assert [item["id"] for item in service.list_jobs()] == ["hybrid-1", "onsite-1"]


def test_invalid_work_mode_is_rejected(tmp_path, inventory, monkeypatch):
    monkeypatch.setattr(web_service, "iter_records", lambda _root: [])
    service = DashboardService(tmp_path, inventory_loader=lambda: inventory)

    with pytest.raises(ValueError, match="unsupported work mode"):
        service.list_jobs(work_mode="anywhere")


def test_company_blocks_persist_without_deleting_jobs_or_applications(tmp_path, inventory):
    service = DashboardService(tmp_path, inventory_loader=lambda: inventory)
    service.mark_applied("remote-1")
    assert service.set_company_blocked("Example", True) == ["Example"]
    assert service.set_company_blocked("EXAMPLE", True) == ["Example"]
    reopened = DashboardService(tmp_path, inventory_loader=lambda: inventory)
    assert reopened.blocked_companies() == ["Example"]
    assert [item["id"] for item in reopened.list_jobs()] == ["hybrid-1"]
    assert reopened.get_job("onsite-1") is not None
    assert reopened.list_applications()[0]["current_status"] == "applied"
    reopened.set_company_blocked("example", False)
    assert [item["id"] for item in reopened.list_jobs()] == ["hybrid-1", "onsite-1"]


def test_company_block_uses_exact_normalized_name(tmp_path):
    inventory = [
        job("a", title="Engineer", mode="remote", company="Acme, Inc."),
        job("b", title="Engineer", mode="remote", company="ACME INC"),
        job("c", title="Engineer", mode="remote", company="Acme Labs"),
    ]
    service = DashboardService(tmp_path, inventory_loader=lambda: inventory)
    service.set_company_blocked("Acme, Inc.", True)
    assert [item["id"] for item in service.list_jobs()] == ["c"]


@pytest.mark.parametrize(
    "company,blocked", [("", True), ("!!!", True), (None, True), ("Example", "yes")]
)
def test_company_block_rejects_invalid_input(tmp_path, company, blocked):
    service = DashboardService(tmp_path, inventory_loader=lambda: [])
    with pytest.raises(ValueError):
        service.set_company_blocked(company, blocked)


def test_jobs_filter_by_recent_date_and_normalized_employment_type(
    tmp_path, inventory, monkeypatch
):
    monkeypatch.setattr(web_service, "iter_records", lambda _root: [])
    inventory[0]["posted_at"] = datetime.now(UTC).isoformat()
    inventory[0]["employment_type"] = "Full-time"
    inventory[1]["posted_at"] = (datetime.now(UTC) - timedelta(days=8)).isoformat()
    inventory[1]["employment_type"] = "Contract"
    service = DashboardService(tmp_path, inventory_loader=lambda: inventory)

    recent = service.list_jobs(date_days=1)
    full_time = service.list_jobs(employment_type="fulltime")
    contract = service.list_jobs(employment_type="contract")

    assert [item["id"] for item in recent] == ["remote-1"]
    assert {item["id"] for item in full_time} == {"remote-1", "onsite-1"}
    assert [item["id"] for item in contract] == ["hybrid-1"]


def test_provider_html_is_converted_to_safe_readable_description():
    description = """
    <div class="content-intro"><p><strong><span>About Us</span></strong></p></div>
    <p><span>Build careers across 180 countries.</span></p>
    <script>alert('not content')</script>
    """

    cleaned = _clean_description(description)

    assert cleaned == "About Us\n\nBuild careers across 180 countries."
    assert "<span" not in cleaned
    assert "alert" not in cleaned


def test_existing_job_uses_explicit_description_pay_range(tmp_path, monkeypatch):
    raw = job("salary-1", title="Technical Support Engineer", mode="onsite")
    raw.update(
        {
            "salary_min": None,
            "salary_max": None,
            "salary_currency": None,
            "salary_interval": None,
            "description_text": "<p>Pay Range</p><p>$62,300 - $115,700 per year</p>",
        }
    )
    monkeypatch.setattr(web_service, "iter_records", lambda _root: [])
    service = DashboardService(tmp_path, inventory_loader=lambda: [raw])

    projected = service.list_jobs()[0]

    assert projected["salary_min"] == 62_300
    assert projected["salary_max"] == 115_700
    assert projected["salary_currency"] == "USD"
    assert projected["salary_interval"] == "yearly"


def test_application_projection_includes_current_status_and_history(tmp_path, monkeypatch):
    record = {
        "application": {
            "id": "APP-1",
            "company": "Example",
            "role": "Support Engineer",
            "job_id": "remote-1",
            "application_url": "https://example.com/apply",
            "applied_on": "2026-08-01",
            "created_at": "2026-08-01T12:00:00+00:00",
        },
        "events": [
            {
                "id": "EVT-1",
                "status": "applied",
                "effective_on": "2026-08-01",
                "recorded_at": "2026-08-01T12:00:00+00:00",
                "stage": None,
                "note": None,
            },
            {
                "id": "EVT-2",
                "status": "interview",
                "effective_on": "2026-08-04",
                "recorded_at": "2026-08-04T12:00:00+00:00",
                "stage": "Hiring manager",
                "note": "Video call",
            },
        ],
    }
    monkeypatch.setattr(
        web_service, "iter_records", lambda _root: [(tmp_path / "APP-1.json", record)]
    )
    service = DashboardService(tmp_path, inventory_loader=lambda: [])

    projected = service.list_applications()[0]

    assert projected["current_status"] == "interview"
    assert projected["events"][0]["stage"] == "Hiring manager"


def _fresh_workspace(tmp_path):
    root = tmp_path / "workspace"
    initialize_workspace(
        root,
        git_name="Example User",
        git_email="example@example.invalid",
    )
    return root


def test_fresh_workspace_starts_resume_onboarding(tmp_path):
    service = DashboardService(_fresh_workspace(tmp_path), inventory_loader=lambda: [])

    assert service.onboarding_status() == {
        "needs_onboarding": True,
        "step": "resume",
        "progress": 1,
        "resume_count": 0,
        "resume_names": [],
        "openrouter_configured": False,
        "setup": None,
    }


def test_resume_upload_is_registered_and_survives_refresh(tmp_path):
    root = _fresh_workspace(tmp_path)
    service = DashboardService(root, inventory_loader=lambda: [])

    result = service.import_resume(
        "Jordan Example Resume.md",
        b"# Experience\n\nSupported production systems and customer incidents.\n",
    )

    assert result == {
        "filename": "Jordan Example Resume.md",
        "added": 1,
        "already_registered": False,
        "registered_sources": 1,
    }
    assert DashboardService(root, inventory_loader=lambda: []).onboarding_status() == {
        "needs_onboarding": True,
        "step": "ai_choice",
        "progress": 1,
        "resume_count": 1,
        "resume_names": ["Jordan Example Resume.md"],
        "openrouter_configured": False,
        "setup": None,
    }
    assert not list((root / "build" / "onboarding-uploads").glob("resume-*"))


def test_duplicate_resume_upload_is_idempotent(tmp_path):
    root = _fresh_workspace(tmp_path)
    service = DashboardService(root, inventory_loader=lambda: [])
    content = b"# Experience\n\nSupported production systems.\n"

    service.import_resume("resume.md", content)
    duplicate = service.import_resume("copy.md", content)

    assert duplicate["added"] == 0
    assert duplicate["already_registered"] is True
    assert duplicate["registered_sources"] == 1


def test_country_search_matches_aliases_without_substring_collisions(tmp_path):
    american = job("us", title="Engineer", mode="remote")
    american["location"] = "Remote, U.S.A."
    australian = job("au", title="Engineer", mode="remote")
    australian["location"] = "Australia"
    service = DashboardService(tmp_path, inventory_loader=lambda: [american, australian])
    for query in ["US", "USA", "United States"]:
        assert [item["id"] for item in service.list_jobs(search=query)] == ["us"]


def test_portal_skips_eligibility_and_supports_back_and_reload(tmp_path):
    service = DashboardService(_fresh_workspace(tmp_path), inventory_loader=lambda: [])
    service.import_resume("resume.md", b"# Experience\nSupported production systems.")
    service.start_preference_setup(use_ai=False)
    service.answer_preference_step("roles", {"add": ["Support Engineer"]})
    assert service.onboarding_status()["step"] == "location"
    assert service.previous_preference_step()["step"] == "roles"
    service.answer_preference_step("roles", {"decisions": {}})
    result = service.answer_preference_step(
        "location",
        {
            "search_country": "Canada",
            "accepted_work_modes": ["remote"],
        },
    )
    assert result["step"] == "compensation"
    assert result["setup"]["eligibility"]["authorized_to_work"] is None
    assert result["setup"]["eligibility"]["holds_clearance_or_public_trust"] is None
    assert service.previous_preference_step()["step"] == "location"
    assert service.previous_preference_step()["step"] == "roles"


def test_manual_onboarding_activates_searches_without_starting_a_scrape(tmp_path):
    root = _fresh_workspace(tmp_path)
    service = DashboardService(root, inventory_loader=lambda: [])
    service.import_resume(
        "resume.md",
        b"# Experience\n\nSupported production systems and customer incidents.\n",
    )

    started = service.start_preference_setup(use_ai=False)
    assert started["step"] == "roles"
    after_roles = service.answer_preference_step(
        "roles", {"decisions": {}, "add": ["Technical Support Engineer"]}
    )
    assert after_roles["step"] == "location"
    assert after_roles["progress"] == 3
    service.answer_preference_step(
        "eligibility",
        {
            "intended_country": "United States",
            "authorized_to_work": True,
            "requires_sponsorship": False,
            "held_clearances": [],
            "willing_to_obtain_clearance": False,
        },
    )
    service.answer_preference_step(
        "location",
        {
            "search_country": "Canada",
            "accepted_work_modes": ["remote", "hybrid"],
            "accepted_onsite_locations": ["New York"],
            "remote_location_terms": ["US"],
        },
    )
    service.answer_preference_step("compensation", {"skipped": True})
    completed = service.answer_preference_step("review", {"action": "save"})

    assert completed["needs_onboarding"] is False
    assert completed["step"] == "complete"
    assert completed["setup"]["eligibility"]["authorized_to_work"] is True
    assert completed["setup"]["eligibility"]["intended_country"] == "Canada"
    search = (root / "job-search/config/search.yml").read_text(encoding="utf-8")
    preferences = (root / "job-search/preferences.yml").read_text(encoding="utf-8")
    assert "enabled: true" in search
    assert "resume-discovery-" in search
    assert "Technical Support Engineer" in search
    assert "Technical Support Engineer" in preferences
    assert not (root / "build/job-search/latest-refresh.json").exists()
    assert not (root / "build/job-search/web-scan.json").exists()


def test_onboarding_does_not_claim_completion_when_activation_fails(tmp_path, monkeypatch):
    root = _fresh_workspace(tmp_path)
    service = DashboardService(root, inventory_loader=lambda: [])
    service.import_resume("resume.md", b"# Experience\n\nSupported production systems.\n")
    service.start_preference_setup(use_ai=False)
    service.answer_preference_step("roles", {"decisions": {}, "add": ["Support Engineer"]})
    service.answer_preference_step(
        "location", {"search_country": "United States", "accepted_work_modes": ["remote"]}
    )
    service.answer_preference_step("compensation", {"skipped": True})
    monkeypatch.setattr(web_service, "activate_setup", lambda *_args: (_ for _ in ()).throw(ValueError("activation failed")))

    with pytest.raises(ValueError, match="activation failed"):
        service.answer_preference_step("review", {"action": "save"})

    status = service.onboarding_status()
    assert status["needs_onboarding"] is True
    assert status["step"] == "activation"
    assert not (root / "job-search/web-onboarding.json").exists()

    (root / "job-search/web-onboarding.json").write_text(
        json.dumps({"schema_version": 2, "completed": True}), encoding="utf-8"
    )
    assert service.onboarding_status()["needs_onboarding"] is True


def test_search_preferences_update_preserves_providers_and_manual_families(tmp_path):
    root = _fresh_workspace(tmp_path)
    service = DashboardService(root, inventory_loader=lambda: [])
    service.import_resume("resume.md", b"# Experience\n\nSupported production systems.\n")
    service.start_preference_setup(use_ai=False)
    service.answer_preference_step(
        "roles", {"decisions": {}, "add": ["Technical Support Engineer"]}
    )
    service.answer_preference_step(
        "location",
        {"search_country": "United States", "accepted_work_modes": ["remote"]},
    )
    service.answer_preference_step("compensation", {"skipped": True})
    service.answer_preference_step("review", {"action": "save"})
    config_path = root / "job-search/config/search.yml"
    config = config_path.read_text(encoding="utf-8")
    config = config.replace(
        "providers: {}",
        "providers:\n  linkedin:\n    enabled: false",
    ).replace(
        "  families:\n",
        "  families:\n  - name: manual-sre\n    enabled: true\n    titles:\n    - Site Reliability Engineer\n",
    )
    config_path.write_text(config, encoding="utf-8")

    current = service.job_search_preferences()
    updated = service.update_job_search_preferences(
        {
            "revision": current["revision"],
            "titles": ["Platform Engineer", "Support Engineer"],
            "country": "United States",
            "work_modes": ["remote", "hybrid"],
            "onsite_locations": ["New York, NY"],
            "remote_location_terms": ["USA"],
            "compensation": {
                "skipped": False,
                "minimum": 90000,
                "target": 125000,
                "currency": "USD",
                "period": "year",
            },
        }
    )

    rendered = config_path.read_text(encoding="utf-8")
    assert updated["titles"] == ["Platform Engineer", "Support Engineer"]
    assert "manual-sre" in rendered
    assert "Site Reliability Engineer" in rendered
    assert "linkedin:" in rendered and "enabled: false" in rendered
    assert "Platform Engineer" in rendered and "Support Engineer" in rendered
    assert "Technical Support Engineer" not in rendered
    assert not (root / "build/job-search/latest-refresh.json").exists()


@pytest.mark.parametrize(
    ("filename", "content", "message"),
    [
        ("resume.exe", b"not a resume", "unsupported resume type"),
        ("resume.md", b"", "uploaded resume is empty"),
        ("resume.md", b" \n\t", "no readable resume text"),
    ],
)
def test_resume_upload_rejects_invalid_input(tmp_path, filename, content, message):
    service = DashboardService(_fresh_workspace(tmp_path), inventory_loader=lambda: [])

    with pytest.raises(ValueError, match=message):
        service.import_resume(filename, content)


def test_skipping_onboarding_is_persistent(tmp_path):
    root = _fresh_workspace(tmp_path)
    service = DashboardService(root, inventory_loader=lambda: [])

    service.skip_onboarding()

    assert (
        DashboardService(root, inventory_loader=lambda: []).onboarding_status()["needs_onboarding"]
        is False
    )
