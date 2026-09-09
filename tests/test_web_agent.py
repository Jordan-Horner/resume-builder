from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from resume_builder.agent_config import DEFAULT_AGENT_CONFIG, render_default_agent_config
from resume_builder.portal.app import create_app
from resume_builder.portal.assistant_routes import asyncio as web_agent_asyncio
from resume_builder.portal.service import DashboardService


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("RESUME_BUILDER_AGENT_STATE", str(tmp_path / "agent.sqlite"))
    return TestClient(create_app(tmp_path))


def test_assistant_threads_are_persistent_and_validated(client: TestClient) -> None:
    created = client.post("/api/assistant/threads", json={"resume_id": None})
    assert created.status_code == 201
    identity = created.json()["id"]
    assert client.get(f"/api/assistant/threads/{identity}").json()["messages"] == []
    assert client.get("/api/assistant/threads").json()["threads"][0]["id"] == identity
    assert (
        client.post("/api/assistant/threads", json={"resume_id": "../secrets"}).status_code == 400
    )
    assert client.delete(f"/api/assistant/threads/{identity}").status_code == 204
    assert client.get(f"/api/assistant/threads/{identity}").status_code == 404


def test_assistant_rejects_unknown_job_context(client: TestClient) -> None:
    response = client.post("/api/assistant/threads", json={"job_id": "missing-job"})

    assert response.status_code == 400
    assert response.json()["detail"] == "Choose an existing job"


def test_assistant_resolves_job_context_once_when_attached(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RESUME_BUILDER_AGENT_STATE", str(tmp_path / "agent.sqlite"))
    lookups = 0

    def identity(_self: DashboardService, job_id: str) -> dict[str, object]:
        nonlocal lookups
        lookups += 1
        return {"id": job_id, "title": "DevOps Engineer", "company": "Zoom"}

    monkeypatch.setattr(DashboardService, "get_job_identity", identity)
    local_client = TestClient(create_app(tmp_path))

    created = local_client.post("/api/assistant/threads", json={"job_id": "job-123"}).json()
    restored = local_client.get(f"/api/assistant/threads/{created['id']}").json()

    assert created["context_name"] == "DevOps Engineer at Zoom"
    assert restored["context_name"] == "DevOps Engineer at Zoom"
    assert lookups == 1


def test_cross_origin_writes_and_direct_agent_access_are_rejected(client: TestClient) -> None:
    assert (
        client.post(
            "/api/assistant/threads", json={}, headers={"Origin": "https://evil.example"}
        ).status_code
        == 403
    )
    assert client.post("/api/assistant/ag-ui", json={}).status_code == 403


def test_missing_configuration_is_honest(client: TestClient) -> None:
    assert client.get("/api/assistant/status").json() == {"configured": False, "online": True}


def test_direct_assistant_runs_validate_messages_and_configuration(client: TestClient) -> None:
    identity = client.post("/api/assistant/threads", json={}).json()["id"]

    invalid = client.post(
        f"/api/assistant/threads/{identity}/runs",
        json={"run_id": "run-one", "prompt": "   "},
    )
    unconfigured = client.post(
        f"/api/assistant/threads/{identity}/runs",
        json={"run_id": "run-one", "prompt": "Review my search"},
    )

    assert invalid.status_code == 400
    assert unconfigured.status_code == 409
    assert client.get(f"/api/assistant/threads/{identity}").json()["messages"] == []


def test_configured_assistant_run_launches_from_the_request_event_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RESUME_BUILDER_AGENT_STATE", str(tmp_path / "agent.sqlite"))
    config_path = tmp_path / DEFAULT_AGENT_CONFIG
    config_path.parent.mkdir(parents=True)
    config_path.write_text(render_default_agent_config(), encoding="utf-8")
    monkeypatch.setattr(DashboardService, "_openrouter_configured", lambda _self: True)

    async def unavailable_worker(*_args: object, **_kwargs: object) -> None:
        raise OSError("worker unavailable in test")

    monkeypatch.setattr(web_agent_asyncio, "create_subprocess_exec", unavailable_worker)
    with TestClient(create_app(tmp_path)) as configured_client:
        identity = configured_client.post("/api/assistant/threads", json={}).json()["id"]
        response = configured_client.post(
            f"/api/assistant/threads/{identity}/runs",
            json={"run_id": "run-one", "prompt": "Review my search"},
        )

    assert response.status_code == 202
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["messages"][0] == {
        "id": "run-one",
        "role": "user",
        "content": "Review my search",
    }
