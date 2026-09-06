from __future__ import annotations

import stat
import time
from pathlib import Path

import pytest

from resume_builder.agent_config import load_agent_config
from resume_builder.web import create_app
from resume_builder.web_integrations import PortalIntegrationService
from resume_builder.workspace import initialize_workspace

testclient = pytest.importorskip("fastapi.testclient")
pytest.importorskip("multipart")
TestClient = testclient.TestClient


def _workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    initialize_workspace(
        workspace,
        git_name="Example User",
        git_email="example@example.invalid",
    )
    return workspace


def test_integration_api_never_exposes_setup_commands(tmp_path: Path) -> None:
    response = TestClient(create_app(_workspace(tmp_path))).get("/api/integrations")

    assert response.status_code == 200
    assert "setup_command" not in response.text
    assert "resume-builder" not in response.text


def test_gmail_setup_and_authorization_are_available_through_portal_routes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        PortalIntegrationService,
        "begin_gmail_oauth",
        lambda self, filename, content, redirect_uri: {
            "authorization_url": "https://accounts.google.test/authorize"
        },
    )
    completed: list[tuple[str, str]] = []
    monkeypatch.setattr(
        PortalIntegrationService,
        "complete_gmail_oauth",
        lambda self, state, authorization_response: completed.append(
            (state, authorization_response)
        ),
    )
    client = TestClient(create_app(_workspace(tmp_path)))

    setup = client.get("/api/integrations/gmail/setup")
    assert setup.status_code == 200
    assert len(setup.json()["steps"]) == 6
    assert "read-only" in setup.json()["privacy"].casefold()

    authorization = client.post(
        "/api/integrations/gmail/authorize",
        files={"file": ("client.json", b'{"installed": {}}', "application/json")},
    )
    assert authorization.status_code == 200
    assert authorization.json() == {"authorization_url": "https://accounts.google.test/authorize"}

    callback = client.get("/?state=safe-state&code=code", follow_redirects=False)
    assert callback.status_code == 303
    assert callback.headers["location"] == "/settings/integrations?gmail=connected"
    assert completed and completed[0][0] == "safe-state"


def test_telegram_pairing_validates_and_saves_one_private_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import resume_builder.web_integrations as integrations

    workspace = _workspace(tmp_path)
    runtime = tmp_path / "runtime"
    token_path = runtime / "telegram-bot-token"
    state_path = runtime / "agent-state.sqlite"

    async def validate(_token: str) -> str:
        return "career_helper_bot"

    async def pair(
        _token: str,
        _code: str,
        _state: object,
        *,
        timeout_seconds: int,
    ) -> tuple[int, int]:
        assert timeout_seconds == 120
        return 101, 202

    monkeypatch.setattr(integrations, "validate_personal_bot", validate)
    monkeypatch.setattr(integrations, "wait_for_pairing", pair)
    monkeypatch.setattr(integrations, "default_agent_state_path", lambda: state_path)
    monkeypatch.setattr(integrations, "default_telegram_token_path", lambda _path=None: token_path)
    service = PortalIntegrationService(workspace)

    started = service.start_telegram_pairing("private-token")
    assert "private-token" not in str(started)
    deadline = time.monotonic() + 2
    current = started
    while current["status"] == "waiting" and time.monotonic() < deadline:
        time.sleep(0.01)
        current = service.telegram_pairing_status(started["session_id"])

    assert current["status"] == "connected"
    assert token_path.read_text(encoding="utf-8").strip() == "private-token"
    assert stat.S_IMODE(token_path.stat().st_mode) == 0o600
    config = load_agent_config(workspace / "agent/config.yml")
    assert config.channels.telegram.allowed_user_ids == (101,)
    assert config.channels.telegram.allowed_chat_ids == (202,)


@pytest.mark.parametrize("token", [None, "", "with spaces", "x" * 513])
def test_telegram_pairing_rejects_invalid_tokens_before_network_access(
    tmp_path: Path, token: object
) -> None:
    with pytest.raises(ValueError):
        PortalIntegrationService(_workspace(tmp_path)).start_telegram_pairing(token)
