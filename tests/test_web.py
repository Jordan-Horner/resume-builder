from __future__ import annotations

from pathlib import Path

import pytest

from resume_builder.web import create_app
from resume_builder.workspace import initialize_workspace

testclient = pytest.importorskip("fastapi.testclient")
pytest.importorskip("multipart")
TestClient = testclient.TestClient


def _client(tmp_path: Path) -> TestClient:
    workspace = tmp_path / "workspace"
    initialize_workspace(
        workspace,
        git_name="Example User",
        git_email="example@example.invalid",
    )
    return TestClient(create_app(workspace))


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


def test_career_library_routes_expose_vault_backed_resumes_and_skills(tmp_path: Path) -> None:
    client = _client(tmp_path)

    resume_payload = client.get("/api/resumes").json()
    assert [section["id"] for section in resume_payload["sections"]] == [
        "directional",
        "tailored",
    ]
    assert all(section["items"] == [] for section in resume_payload["sections"])
    assert client.get("/api/skills").json() == {"skills": []}


def test_skill_search_route_rejects_invalid_payload(tmp_path: Path) -> None:
    response = _client(tmp_path).put("/api/skills/SKILL-001/search", json={"enabled": "yes"})

    assert response.status_code == 400
    assert response.json()["detail"] == "enabled must be true or false"


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
    telegram = next(item for item in payload["components"] if item["id"] == "telegram")
    assert telegram["status"] == "not_configured"
    scheduler = next(item for item in payload["components"] if item["id"] == "scheduler")
    assert scheduler["status"] == "disabled"


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
