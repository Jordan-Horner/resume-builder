import json
from datetime import UTC, datetime, timedelta

import pytest
import yaml

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


def test_primary_resume_uses_explicit_resume_source_instead_of_longest_source(tmp_path):
    initialize_workspace(tmp_path, git_name="Example User", git_email="example@example.invalid")
    layout = web_service.VaultLayout.load(tmp_path / "vault")
    note = tmp_path / "very-long-note.md"
    note.write_text("not a resume " * 1000, encoding="utf-8")
    resume = tmp_path / "resume.md"
    resume.write_text("Support Engineer\n", encoding="utf-8")
    web_service.apply_import_plan(
        layout,
        web_service.build_import_plan(layout, [str(note)], []),
    )
    resume_plan = web_service.build_import_plan(
        layout,
        [str(resume)],
        [],
        document_kind="resume",
    )
    web_service.apply_import_plan(layout, resume_plan)

    document = DashboardService(tmp_path)._primary_resume_document()

    resume_entry = next(
        item for item in resume_plan.manifest["sources"] if item["document_kind"] == "resume"
    )
    assert document.source_id == resume_entry["id"]
    assert "Support Engineer" in document.content


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


def test_mark_applied_pins_the_only_directional_resume_when_no_target_exists(tmp_path, inventory):
    resume = tmp_path / "resumes" / "baselines" / "support.md"
    resume.parent.mkdir(parents=True)
    resume.write_text("# Support resume\n", encoding="utf-8")
    service = DashboardService(tmp_path, inventory_loader=lambda: inventory)

    record = service.mark_applied("remote-1")

    assert record["application"]["resume"]["path"] == "resumes/baselines/support.md"
    assert len(record["application"]["resume"]["sha256"]) == 64
    application = service.list_applications()[0]
    assert application["resume"]["name"] == "Support"
    assert application["resume"]["kind"] == "directional"
    assert application["resume"]["detail"] == "Closest directional resume"
    assert application["resume_attribution"] == "directional"


def test_mark_applied_does_not_guess_between_multiple_directional_resumes(tmp_path, inventory):
    folder = tmp_path / "resumes" / "baselines"
    folder.mkdir(parents=True)
    (folder / "support.md").write_text("# Support\n", encoding="utf-8")
    (folder / "platform.md").write_text("# Platform\n", encoding="utf-8")
    service = DashboardService(tmp_path, inventory_loader=lambda: inventory)

    record = service.mark_applied("remote-1")

    assert record["application"]["resume"] is None
    assert service.list_applications()[0]["resume_attribution"] == "not_recorded"


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
    monkeypatch.setattr(
        web_service,
        "activate_setup",
        lambda *_args: (_ for _ in ()).throw(ValueError("activation failed")),
    )

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
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config.setdefault("providers", {}).setdefault("linkedin", {})["enabled"] = False
    config["search"]["families"].insert(
        0,
        {
            "name": "manual-sre",
            "enabled": True,
            "titles": ["Site Reliability Engineer"],
        },
    )
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")

    starting_config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert starting_config["providers"]["linkedin"]["enabled"] is False
    assert starting_config["search"]["families"][0]["name"] == "manual-sre"

    current = service.job_search_preferences()
    updated = service.update_job_search_preferences(
        {
            "revision": current["revision"],
            "titles": ["Platform Engineer", "Support Engineer"],
            "country": "United States",
            "work_modes": ["remote", "hybrid"],
            "onsite_locations": ["New York, NY"],
            "remote_location_terms": ["USA"],
            "clearance_preference": "prefer",
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
    assert updated["clearance_preference"] == "prefer"
    assert "manual-sre" in rendered
    assert "Site Reliability Engineer" in rendered
    assert "linkedin:" in rendered and "enabled: false" in rendered
    assert "Platform Engineer" in rendered and "Support Engineer" in rendered
    assert "Technical Support Engineer" not in rendered
    assert not (root / "build/job-search/latest-refresh.json").exists()
    saved_preferences = yaml.safe_load(
        (root / "job-search/preferences.yml").read_text(encoding="utf-8")
    )
    assert saved_preferences["clearance_preference"] == "prefer"


def test_search_preferences_update_migrates_active_legacy_workspace(tmp_path):
    root = _fresh_workspace(tmp_path)
    preferences_path = root / "job-search/preferences.yml"
    preferences = yaml.safe_load(preferences_path.read_text(encoding="utf-8"))
    preferences.update(
        {
            "desired_title_terms": ["Support Engineer"],
            "accepted_work_modes": ["remote"],
            "minimum_salary": 80_000,
            "salary_currency": "USD",
            "salary_period": "year",
        }
    )
    preferences_path.write_text(yaml.safe_dump(preferences, sort_keys=False), encoding="utf-8")
    config_path = root / "job-search/config/search.yml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config["enabled"] = True
    config["search"]["families"] = [
        {"name": "manual-support", "enabled": True, "titles": ["Support Engineer"]}
    ]
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    service = DashboardService(root, inventory_loader=lambda: [])

    current = service.job_search_preferences()
    updated = service.update_job_search_preferences(
        {
            **current,
            "titles": ["Support Engineer", "Platform Engineer"],
            "compensation": {
                "skipped": False,
                "minimum": 85_000,
                "target": None,
                "currency": "USD",
                "period": "year",
            },
        }
    )

    assert current["status"] == "active"
    assert updated["titles"] == ["Support Engineer", "Platform Engineer"]
    setup = web_service.load_setup_state(root)
    assert setup is not None
    assert setup.status == web_service.SetupStatus.ACTIVE
    assert setup.session_id.startswith("legacy-")
    rendered = config_path.read_text(encoding="utf-8")
    assert "manual-support" in rendered
    assert "Platform Engineer" in rendered


def test_search_preferences_update_still_requires_inactive_setup(tmp_path):
    root = _fresh_workspace(tmp_path)
    service = DashboardService(root, inventory_loader=lambda: [])
    current = service.job_search_preferences()

    with pytest.raises(ValueError, match="finish job-search setup"):
        service.update_job_search_preferences(
            {
                **current,
                "titles": ["Support Engineer"],
                "country": "United States",
                "work_modes": ["remote"],
                "compensation": {"skipped": True},
            }
        )


def test_search_preferences_keep_skill_terms_out_of_role_titles(tmp_path):
    root = _fresh_workspace(tmp_path)
    service = DashboardService(root, inventory_loader=lambda: [])
    service.import_resume("resume.md", b"# Experience\n\nSupported production systems.\n")
    service.start_preference_setup(use_ai=False)
    service.answer_preference_step(
        "roles", {"decisions": {}, "add": ["Technical Support Engineer"]}
    )
    service.answer_preference_step(
        "location", {"search_country": "United States", "accepted_work_modes": ["remote"]}
    )
    service.answer_preference_step("compensation", {"skipped": True})
    service.answer_preference_step("review", {"action": "save"})
    preferences_path = root / "job-search/preferences.yml"
    preferences = yaml.safe_load(preferences_path.read_text(encoding="utf-8"))
    preferences["interest_terms"] = ["Incident response"]
    preferences_path.write_text(yaml.safe_dump(preferences, sort_keys=False), encoding="utf-8")

    result = service.job_search_preferences()

    assert result["titles"] == ["Technical Support Engineer"]
    assert result["skill_terms"] == ["Incident response"]


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


def test_revisit_suggestion_choice_preserves_session_and_answers(tmp_path):
    root = _fresh_workspace(tmp_path)
    service = DashboardService(root, inventory_loader=lambda: [])
    service.import_resume("resume.md", b"# Experience\n\nSupported production systems.\n")
    first = service.start_preference_setup(use_ai=False)
    service.answer_preference_step("roles", {"titles": ["Support Engineer"]})
    service.answer_preference_step(
        "location", {"search_country": "Canada", "accepted_work_modes": ["remote"]}
    )
    service.answer_preference_step("compensation", {"skipped": True})
    service.previous_preference_step()
    service.previous_preference_step()
    service.previous_preference_step()
    back = service.previous_preference_step()
    assert back["step"] == "ai_choice"
    reloaded = DashboardService(root, inventory_loader=lambda: [])
    assert reloaded.onboarding_status()["step"] == "ai_choice"
    resumed = reloaded.start_preference_setup(use_ai=False)
    assert resumed["step"] == "roles"
    assert resumed["setup"]["session_id"] == first["setup"]["session_id"]
    assert resumed["setup"]["eligibility"]["intended_country"] == "Canada"
    assert resumed["setup"]["compensation"]["skipped"] is True
    assert any(role["title"] == "Support Engineer" for role in resumed["setup"]["roles"])


def test_role_preview_uses_shared_identity_and_live_skill_capacity(tmp_path):
    from resume_builder.discovery_portfolio import ColdStartPortfolio, ColdStartQuery
    from resume_builder.job_setup_defaults import PORTFOLIO_PATH

    root = _fresh_workspace(tmp_path)
    service = DashboardService(root, inventory_loader=lambda: [])
    portfolio = ColdStartPortfolio(
        generated_at="2026-09-05T00:00:00+00:00",
        resume_hash="test",
        queries=[
            ColdStartQuery(
                query_id="skill-one",
                lane="capability_combination",
                query="Python",
                source_ids=["vault:skill-one"],
                reason="Confirmed skill",
            )
        ],
    )
    path = root / PORTFOLIO_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(portfolio.model_dump_json(), encoding="utf-8")
    for scope in ("onboarding", "settings"):
        result = service.preview_role_titles(
            {
                "scope": scope,
                "titles": [" Support   Engineer ", "support-engineer"],
            }
        )
        assert result["titles"] == ["Support Engineer"]
        assert result["remaining"] == 20
        with pytest.raises(ValueError, match="roles and skills"):
            service.preview_role_titles(
                {"scope": scope, "titles": [f"Role {n}" for n in range(22)]}
            )
        assert (
            service.preview_role_titles({"scope": scope, "titles": ["Python"]})["remaining"] == 21
        )
