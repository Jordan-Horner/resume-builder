from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from resume_builder.web import create_app


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
