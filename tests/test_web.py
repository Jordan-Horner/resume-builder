from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from threading import Event, Thread

import pytest

from resume_builder.portal.app import create_app
from resume_builder.portal.service import JOBS_CONFIG, DashboardService
from resume_builder.workspace_management.setup import initialize_workspace
from resume_builder.workspace_management.sync import workspace_identity

testclient = pytest.importorskip("fastapi.testclient")
pytest.importorskip("multipart")
TestClient = testclient.TestClient


def test_active_job_search_prepares_recommended_queue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = tmp_path / JOBS_CONFIG
    config.parent.mkdir(parents=True)
    config.write_text("{}", encoding="utf-8")
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        DashboardService,
        "list_job_rows",
        lambda _self, **kwargs: calls.append(kwargs) or {},
    )

    with TestClient(create_app(tmp_path)):
        pass

    assert calls[0]["queue"] == "recommended"
    assert isinstance(calls[0]["view_filters"], str)


def _client(tmp_path: Path) -> TestClient:
    workspace = tmp_path / "workspace"
    initialize_workspace(
        workspace,
        git_name="Example User",
        git_email="example@example.invalid",
    )
    return TestClient(create_app(workspace))


def test_openrouter_can_be_configured_without_onboarding(tmp_path: Path, monkeypatch) -> None:
    import httpx

    from resume_builder.assistant.config import DEFAULT_AGENT_CONFIG
    from resume_builder.portal.service import OPENROUTER_SECRET_PATH

    client = _client(tmp_path)
    workspace = tmp_path / "workspace"
    monkeypatch.setattr(httpx, "get", lambda *a, **kw: httpx.Response(200, json={"data": {}}))
    response = client.put("/api/integrations/openrouter", json={"api_key": "fixture-key"})
    assert response.status_code == 200
    assert "fixture-key" not in response.text
    assert (workspace / DEFAULT_AGENT_CONFIG).is_file()
    secret = workspace / OPENROUTER_SECRET_PATH
    assert secret.read_text().strip() == "fixture-key"
    assert secret.stat().st_mode & 0o777 == 0o600
    original_config = (workspace / DEFAULT_AGENT_CONFIG).read_text()
    replacement = client.put("/api/integrations/openrouter", json={"api_key": "replacement-key"})
    assert replacement.status_code == 200
    assert (workspace / DEFAULT_AGENT_CONFIG).read_text() == original_config
    monkeypatch.setattr(httpx, "get", lambda *a, **kw: httpx.Response(401))
    rejected = client.put("/api/integrations/openrouter", json={"api_key": "rejected-fixture"})
    assert rejected.status_code == 400
    assert "rejected-fixture" not in rejected.text
    assert secret.read_text().strip() == "replacement-key"
    assert (workspace / DEFAULT_AGENT_CONFIG).read_text() == original_config


def test_bright_data_is_configured_from_integrations(tmp_path: Path) -> None:
    from resume_builder.opportunities.bright_data import (
        BRIGHT_DATA_SECRET_PATH,
        BRIGHT_DATA_SETTINGS_PATH,
    )

    client = _client(tmp_path)
    workspace = tmp_path / "workspace"
    response = client.put(
        "/api/integrations/bright-data",
        json={
            "api_token": "fixture-token",
            "enabled": True,
            "max_records_per_refresh": 75,
        },
    )

    assert response.status_code == 200
    assert "fixture-token" not in response.text
    secret = workspace / BRIGHT_DATA_SECRET_PATH
    assert secret.read_text(encoding="utf-8").strip() == "fixture-token"
    assert secret.stat().st_mode & 0o777 == 0o600
    assert (workspace / BRIGHT_DATA_SETTINGS_PATH).is_file()
    integration = next(
        item
        for item in client.get("/api/integrations").json()["integrations"]
        if item["id"] == "bright-data"
    )
    assert integration["status"] == "connected"
    assert integration["settings"] == {"enabled": True, "max_records_per_refresh": 75}


def test_bright_data_enrichment_has_a_direct_api(tmp_path: Path, monkeypatch) -> None:
    from resume_builder.portal.service import DashboardService

    result = {
        "requested": 5,
        "improved": 4,
        "no_change": 1,
        "failed": 0,
        "skipped_cached": 3,
        "message": "Bright Data checked 5 job(s): 4 improved.",
    }
    monkeypatch.setattr(DashboardService, "enrich_bright_data", lambda self: result)

    response = _client(tmp_path).post("/api/integrations/bright-data/enrich")

    assert response.status_code == 200
    assert response.json() == result


def test_job_screen_routes_use_one_status_read_and_an_explicit_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from resume_builder.portal.service import DashboardService

    result = {"status": "queued", "job_id": "job-1"}
    monkeypatch.setattr(DashboardService, "job_screen_status", lambda self, job_id: result)
    monkeypatch.setattr(
        DashboardService, "queue_job_screen", lambda self, job_id, refresh=False: result
    )
    completed: list[str] = []
    monkeypatch.setattr(
        DashboardService,
        "run_queued_job_screen",
        lambda self, job_id, refresh=False: completed.append(job_id),
    )
    client = _client(tmp_path)

    assert client.get("/api/jobs/job-1/screen-status").json() == result
    response = client.post("/api/jobs/job-1/screen")
    assert response.status_code == 202
    assert response.json() == result
    assert completed == ["job-1"]


def test_job_screen_never_exposes_raw_decoding_errors(tmp_path: Path, monkeypatch) -> None:
    from resume_builder.portal.service import DashboardService

    decoding_error = UnicodeDecodeError("utf-8", b"\xa3", 0, 1, "invalid start byte")
    monkeypatch.setattr(
        DashboardService,
        "queue_job_screen",
        lambda self, job_id, refresh=False: (_ for _ in ()).throw(decoding_error),
    )
    response = _client(tmp_path).post("/api/jobs/legacy-job/screen")

    assert response.status_code == 500
    assert response.json()["detail"] == (
        "Job screening could not read one of its inputs. Refresh your jobs and try again."
    )
    assert "codec" not in response.text


def test_job_feedback_routes_are_backend_owned(tmp_path: Path, monkeypatch) -> None:
    from resume_builder.portal.service import DashboardService

    result = {"job_id": "job-1", "latest": {"action": "interested"}}
    monkeypatch.setattr(DashboardService, "job_feedback", lambda self, job_id: result)
    monkeypatch.setattr(
        DashboardService,
        "record_job_feedback",
        lambda self, job_id, action, reasons: result,
    )
    client = _client(tmp_path)

    assert client.get("/api/jobs/job-1/feedback").json() == result
    response = client.post(
        "/api/jobs/job-1/feedback",
        json={"action": "interested", "reasons": ["day_to_day"]},
    )
    assert response.status_code == 200
    assert response.json() == result


def test_job_hide_route_keeps_reason_explicit(tmp_path: Path, monkeypatch) -> None:
    from resume_builder.portal.service import DashboardService

    result = {"job_id": "job-1", "reason": "closed", "personalization_updated": False}
    monkeypatch.setattr(DashboardService, "hide_job", lambda self, job_id, reason: result)

    response = _client(tmp_path).post("/api/jobs/job-1/hide", json={"reason": "closed"})

    assert response.status_code == 200
    assert response.json() == result


def test_screening_backfill_route_starts_standalone_worker(tmp_path: Path, monkeypatch) -> None:
    from resume_builder.portal.service import DashboardService

    calls: list[str] = []
    started = Event()
    release = Event()
    state = {
        "status": "running",
        "message": "Screening the next recommended jobs…",
        "enabled": True,
        "available": True,
        "max_jobs": 10,
    }
    monkeypatch.setattr(DashboardService, "screening_backfill_status", lambda self: state)
    monkeypatch.setattr(
        DashboardService,
        "queue_screening_backfill",
        lambda self: (True, state),
    )
    monkeypatch.setattr(
        DashboardService,
        "run_queued_screening_backfill",
        lambda self: (calls.append("screen"), started.set(), release.wait(timeout=1)),
    )
    with _client(tmp_path) as client:
        assert client.get("/api/jobs/screening-backfill").json() == state
        response = client.post("/api/jobs/screening-backfill")

        assert response.status_code == 202
        assert response.json() == state
        assert started.wait(timeout=1)
        assert calls == ["screen"]
        completed = Event()
        status_codes: list[int] = []

        def load_status() -> None:
            status_codes.append(client.get("/api/jobs/screening-backfill").status_code)
            completed.set()

        request = Thread(target=load_status)
        request.start()
        try:
            assert completed.wait(timeout=0.5), (
                "background screening blocked another portal request"
            )
            assert status_codes == [200]
        finally:
            release.set()
            request.join(timeout=1)


def test_feedback_response_does_not_wait_for_recommendation_screening(
    tmp_path: Path, monkeypatch
) -> None:
    from resume_builder.portal.service import DashboardService

    result = {"job_id": "job-1", "latest": {"action": "interested"}}
    started = Event()
    release = Event()
    monkeypatch.setattr(
        DashboardService,
        "record_job_feedback",
        lambda self, job_id, action, reasons: result,
    )
    monkeypatch.setattr(
        DashboardService,
        "queue_screening_backfill",
        lambda self, *, drain=False: (True, {"status": "running"}),
    )
    monkeypatch.setattr(
        DashboardService,
        "run_queued_screening_backfill",
        lambda self, *, drain=False: (started.set(), release.wait(timeout=1)),
    )

    with _client(tmp_path) as client:
        response = client.post(
            "/api/jobs/job-1/feedback",
            json={"action": "interested", "reasons": []},
        )

        assert response.status_code == 200
        assert response.json() == result
        assert started.wait(timeout=1)
        release.set()


def test_open_posting_route_records_passive_positive_once(tmp_path: Path, monkeypatch) -> None:
    from resume_builder.portal.service import DashboardService

    calls: list[str] = []
    monkeypatch.setattr(
        DashboardService,
        "record_job_open",
        lambda self, job_id: calls.append(job_id),
    )
    client = _client(tmp_path)

    response = client.post("/api/jobs/job-1/opened-posting")

    assert response.status_code == 204
    assert calls == ["job-1"]


@pytest.mark.parametrize("key", ["", "  ", None, 123, "a\nb", "x" * 513])
def test_openrouter_rejects_invalid_key_input(tmp_path: Path, key: object) -> None:
    client = _client(tmp_path)
    assert client.put("/api/integrations/openrouter", json={"api_key": key}).status_code == 400


@pytest.mark.parametrize("status,body", [(500, {}), (200, {}), (200, [])])
def test_openrouter_unexpected_response_does_not_save(
    tmp_path: Path, monkeypatch, status, body
) -> None:
    import httpx

    from resume_builder.portal.service import OPENROUTER_SECRET_PATH

    client = _client(tmp_path)
    monkeypatch.setattr(httpx, "get", lambda *a, **kw: httpx.Response(status, json=body))
    assert (
        client.put("/api/integrations/openrouter", json={"api_key": "fixture-key"}).status_code
        == 400
    )
    assert not (tmp_path / "workspace" / OPENROUTER_SECRET_PATH).exists()


def test_resume_upload_route_accepts_multipart_file(tmp_path: Path) -> None:
    client = _client(tmp_path)

    response = client.post(
        "/api/onboarding/resume",
        files={"file": ("resume.md", b"# Experience\n\nSupported production systems.\n")},
    )

    assert response.status_code == 201
    assert response.json() == {
        "filename": "resume.md",
        "added": 1,
        "already_registered": False,
        "registered_sources": 1,
    }
    assert client.get("/api/onboarding").json()["step"] == "ai_choice"


def test_career_material_upload_uses_the_same_resume_importer(tmp_path: Path) -> None:
    client = _client(tmp_path)

    response = client.post(
        "/api/career-material/resumes",
        files={"file": ("older-resume.md", b"# Experience\n\nSupported production systems.\n")},
    )

    assert response.status_code == 201
    assert response.json()["filename"] == "older-resume.md"
    assert response.json()["registered_sources"] == 1


def test_generated_resume_reader_renders_current_markdown_not_old_preview(tmp_path: Path) -> None:
    client = _client(tmp_path)
    workspace = tmp_path / "workspace"
    fact = workspace / "vault" / "facts" / "skills" / "SKILL-001.md"
    fact.parent.mkdir(parents=True, exist_ok=True)
    fact.write_text(
        """---
schema_version: 2
id: SKILL-001
title: Production support
type: responsibility
status: confirmed
category: skills
sources: [SRC-example]
---

# Production support

Supported production systems.
""",
        encoding="utf-8",
    )
    resume = workspace / "resumes" / "baselines" / "support.md"
    resume.parent.mkdir(parents=True, exist_ok=True)
    resume.write_text(
        """---
version: 1
lang: en
page_format: letter
candidate:
  name: Example User
  headline: Current Support Resume
  email: example@example.invalid
  evidence: [SKILL-001]
---

# Professional Summary

Production support specialist. <!-- evidence: SKILL-001 -->
""",
        encoding="utf-8",
    )
    rendered = workspace / "build" / "resumes" / "support" / "resume.html"
    rendered.parent.mkdir(parents=True)
    rendered.write_text("<!doctype html><title>Support resume</title>", encoding="utf-8")

    response = client.get(
        "/api/resume-preview",
        params={"resume_id": "resumes/baselines/support.md"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["content-security-policy"].startswith("sandbox;")
    assert "Current Support Resume" in response.text
    assert "<title>Support resume</title>" not in response.text
    assert "Previous preview" not in response.text
    assert "Refresh preview" not in response.text


def test_generated_resume_without_published_preview_renders_on_demand(tmp_path: Path) -> None:
    client = _client(tmp_path)
    workspace = tmp_path / "workspace"
    fact = workspace / "vault" / "facts" / "skills" / "SKILL-001.md"
    fact.parent.mkdir(parents=True, exist_ok=True)
    fact.write_text(
        """---
schema_version: 2
id: SKILL-001
title: Incident response
type: responsibility
status: confirmed
category: skills
sources: [SRC-example]
---

# Incident response

Supported production incidents.
""",
        encoding="utf-8",
    )
    resume = workspace / "resumes" / "baselines" / "support.md"
    resume.parent.mkdir(parents=True, exist_ok=True)
    resume.write_text(
        """---
version: 1
lang: en
page_format: letter
candidate:
  name: Example User
  headline: Support Engineer
  email: example@example.invalid
  evidence: [SKILL-001]
---

# Professional Summary

Production support specialist. <!-- evidence: SKILL-001 -->

# Technical Skills

- **Operations:** Incident response <!-- evidence: SKILL-001 -->
""",
        encoding="utf-8",
    )

    library = client.get("/api/resumes").json()
    item = library["sections"][0]["items"][0]
    response = client.get(item["preview_url"])

    assert item["preview_url"].startswith("/api/resume-preview?")
    assert response.status_code == 200
    assert "Support Engineer" in response.text
    assert "Current draft preview" not in response.text
    assert "Refresh preview" not in response.text


def test_resume_preview_rejects_files_outside_generated_resume_folders(tmp_path: Path) -> None:
    client = _client(tmp_path)

    response = client.get(
        "/api/resume-preview",
        params={"resume_id": "vault/vault.json"},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "generated resume was not found"


def test_removed_skills_api_is_not_available(tmp_path: Path) -> None:
    client = _client(tmp_path)

    assert client.get("/api/skills").status_code == 404
    assert client.put("/api/skills/SKILL-001/search", json={"enabled": True}).status_code == 404


def test_manual_onboarding_routes_through_preference_steps(tmp_path: Path) -> None:
    client = _client(tmp_path)
    client.post(
        "/api/onboarding/resume",
        files={"file": ("resume.md", b"# Experience\n\nSupported production systems.\n")},
    )

    started = client.post("/api/onboarding/start", json={"use_ai": False})
    assert started.status_code == 200
    assert started.json()["step"] == "roles"

    roles = client.post(
        "/api/onboarding/answer",
        json={
            "step": "roles",
            "answer": {"decisions": {}, "add": ["Technical Support Engineer"]},
        },
    )
    assert roles.status_code == 200
    assert roles.json()["step"] == "location"


def test_job_search_preferences_route_exposes_editable_defaults(tmp_path: Path) -> None:
    client = _client(tmp_path)

    response = client.get("/api/job-search/preferences")

    assert response.status_code == 200
    assert response.json()["titles"] == []
    assert response.json()["country"] == "United States"
    assert response.json()["revision"]


def test_career_library_route_exposes_vault_backed_resumes(tmp_path: Path) -> None:
    client = _client(tmp_path)

    resume_payload = client.get("/api/resumes").json()
    assert [section["id"] for section in resume_payload["sections"]] == [
        "directional",
        "tailored",
        "retired",
    ]
    assert all(section["items"] == [] for section in resume_payload["sections"])


def test_retired_resume_can_be_restored_through_portal(tmp_path: Path) -> None:
    client = _client(tmp_path)
    workspace = tmp_path / "workspace"
    retired = workspace / "resumes" / "archived" / "support.md"
    retired.parent.mkdir(parents=True, exist_ok=True)
    retired.write_text("# Support\n", encoding="utf-8")

    response = client.post(
        "/api/resumes/restore", json={"resume_id": "resumes/archived/support.md"}
    )

    assert response.status_code == 200
    assert response.json()["restored"] is True
    assert (workspace / "resumes" / "baselines" / "support.md").is_file()


@pytest.mark.parametrize(
    "payload", [{}, {"company": None, "blocked": True}, {"company": "Example", "blocked": "false"}]
)
def test_block_company_rejects_invalid_payload(tmp_path, payload):
    assert _client(tmp_path).put("/api/blocked-companies", json=payload).status_code == 400


@pytest.mark.parametrize("payload", [{}, {"enabled": "false"}, {"enabled": None}])
def test_source_toggle_rejects_invalid_payload(tmp_path, payload):
    assert _client(tmp_path).put("/api/job-sources/greenhouse", json=payload).status_code == 400


def test_scrape_schedule_routes_read_and_validate(tmp_path: Path) -> None:
    client = _client(tmp_path)
    current = client.get("/api/scrape-schedule")
    assert current.status_code == 200
    assert current.json()["times"] == ["08:00"]

    invalid = client.put("/api/scrape-schedule", json={"enabled": True, "times": []})
    assert invalid.status_code == 400
    assert "at least one" in invalid.json()["detail"]


def test_system_status_keeps_optional_services_out_of_core_health(tmp_path: Path) -> None:
    status = _client(tmp_path).get("/api/system/status")

    assert status.status_code == 200
    payload = status.json()
    assert payload["status"] == "healthy"
    assert payload["components"][0] == {
        "id": "portal",
        "name": "Portal",
        "status": "online",
        "detail": "Available",
    }
    workspace_sync = next(item for item in payload["components"] if item["id"] == "workspace-sync")
    assert workspace_sync["status"] == "disabled"
    telegram = next(item for item in payload["components"] if item["id"] == "telegram")
    assert telegram["status"] == "not_configured"
    scheduler = next(item for item in payload["components"] if item["id"] == "scheduler")
    assert scheduler["status"] == "disabled"


def test_system_status_surfaces_blocked_workspace_sync(tmp_path: Path, monkeypatch) -> None:
    state = tmp_path / "state"
    state.mkdir()
    workspace = tmp_path / "workspace"
    client = _client(tmp_path)
    (state / "workspace-sync.json").write_text(
        json.dumps(
            {
                "status": "blocked",
                "detail": "Upstream changes overlap local work",
                "checked_at": datetime.now(timezone.utc).isoformat(),
                "workspace_id": workspace_identity(workspace),
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("RESUME_BUILDER_STATE_DIR", str(state))
    monkeypatch.setenv("RESUME_BUILDER_WORKSPACE_SYNC_ENABLED", "true")

    payload = client.get("/api/system/status").json()

    workspace_sync = next(item for item in payload["components"] if item["id"] == "workspace-sync")
    assert workspace_sync == {
        "id": "workspace-sync",
        "name": "Workspace sync",
        "status": "blocked",
        "detail": "Upstream changes overlap local work",
    }
    assert payload["status"] == "degraded"


def test_system_status_rejects_a_stopped_workspace_sync_worker(tmp_path: Path, monkeypatch) -> None:
    from resume_builder.portal import system

    state = tmp_path / "state"
    state.mkdir()
    workspace = tmp_path / "workspace"
    client = _client(tmp_path)
    (state / "workspace-sync.json").write_text(
        json.dumps(
            {
                "status": "current",
                "detail": "Workspace is current",
                "checked_at": datetime.now(timezone.utc).isoformat(),
                "workspace_id": workspace_identity(workspace),
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("RESUME_BUILDER_STATE_DIR", str(state))
    monkeypatch.setenv("RESUME_BUILDER_WORKSPACE_SYNC_ENABLED", "true")
    monkeypatch.setattr(system, "managed_service_status", lambda _service: "fatal")

    payload = client.get("/api/system/status").json()

    workspace_sync = next(item for item in payload["components"] if item["id"] == "workspace-sync")
    assert workspace_sync["status"] == "error"
    assert workspace_sync["detail"] == "Workspace update worker is not running"
    assert payload["status"] == "degraded"


def test_resume_upload_route_returns_readable_validation_error(tmp_path: Path) -> None:
    client = _client(tmp_path)

    response = client.post(
        "/api/onboarding/resume",
        files={"file": ("resume.exe", b"not a resume")},
    )

    assert response.status_code == 400
    assert "unsupported resume type" in response.json()["detail"]


def test_role_preview_validates_titles_without_persisting(tmp_path: Path) -> None:
    client = _client(tmp_path)
    for scope in ("onboarding", "settings"):
        response = client.post(
            "/api/job-search/roles/preview",
            json={
                "scope": scope,
                "titles": ["Support Engineer", "support-engineer"],
            },
        )
        assert response.status_code == 200
        assert response.json()["titles"] == ["Support Engineer"]
        assert response.json()["remaining"] == 21
        invalid = client.post(
            "/api/job-search/roles/preview",
            json={
                "scope": scope,
                "titles": ["x"],
            },
        )
        assert invalid.status_code == 400
    assert not (tmp_path / "workspace" / "job-search" / "setup.json").exists()
