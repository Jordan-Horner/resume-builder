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
    assert payload["status"] == "degraded"
    assert payload["components"][0] == {
        "id": "portal",
        "name": "Portal",
        "status": "online",
        "detail": "Available",
    }
    telegram = next(item for item in payload["components"] if item["id"] == "telegram")
    assert telegram["status"] == "not_configured"


def test_resume_upload_route_returns_readable_validation_error(tmp_path: Path) -> None:
    client = _client(tmp_path)

    response = client.post(
        "/api/onboarding/resume",
        files={"file": ("resume.exe", b"not a resume")},
    )

    assert response.status_code == 400
    assert "unsupported resume type" in response.json()["detail"]
