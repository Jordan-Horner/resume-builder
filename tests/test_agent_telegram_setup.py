"""Tests for guided personal Telegram setup."""

from __future__ import annotations

import stat
import sys
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest

from resume_builder.agent_config import load_agent_config, render_default_agent_config
from resume_builder.agent_state import AgentState
from resume_builder.agent_telegram_setup import (
    enable_private_telegram,
    require_external_token_path,
    resolve_telegram_token,
    run_personal_telegram_setup,
    wait_for_pairing,
    write_telegram_token,
)


def test_token_file_is_owner_only_and_resolves_without_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "agent.yml"
    config_path.write_text(render_default_agent_config(), encoding="utf-8")
    config = load_agent_config(config_path)
    token_path = tmp_path / "external" / "telegram-token"
    monkeypatch.delenv(config.channels.telegram.token_env, raising=False)

    write_telegram_token(token_path, "private-token")

    assert stat.S_IMODE(token_path.stat().st_mode) == 0o600
    assert (
        resolve_telegram_token(config.channels.telegram, token_path=token_path) == "private-token"
    )


def test_environment_token_takes_precedence_over_token_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "agent.yml"
    config_path.write_text(render_default_agent_config(), encoding="utf-8")
    config = load_agent_config(config_path)
    token_path = tmp_path / "telegram-token"
    write_telegram_token(token_path, "file-token")
    monkeypatch.setenv(config.channels.telegram.token_env, "environment-token")

    assert (
        resolve_telegram_token(config.channels.telegram, token_path=token_path)
        == "environment-token"
    )


def test_enable_private_telegram_writes_only_identity_configuration(tmp_path: Path) -> None:
    config_path = tmp_path / "agent.yml"
    config_path.write_text(render_default_agent_config(), encoding="utf-8")

    enable_private_telegram(config_path, user_id=101, chat_id=202)

    config = load_agent_config(config_path)
    assert config.channels.telegram.enabled is True
    assert config.channels.telegram.allowed_user_ids == (101,)
    assert config.channels.telegram.allowed_chat_ids == (202,)
    assert config.channels.telegram.private_chats_only is True
    assert "private-token" not in config_path.read_text(encoding="utf-8")


def test_token_path_cannot_be_inside_workspace(tmp_path: Path) -> None:
    config_path = tmp_path / "workspace" / "agent" / "config.yml"

    with pytest.raises(ValueError, match="outside Git repositories"):
        require_external_token_path(tmp_path / "workspace" / "secret", config_path)


@pytest.mark.asyncio
async def test_pairing_accepts_only_matching_code_from_private_chat(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    @dataclass
    class Update:
        update_id: int
        effective_user: object
        effective_chat: object
        effective_message: object

    updates = [
        Update(
            1,
            SimpleNamespace(id=10),
            SimpleNamespace(id=-20, type="group"),
            SimpleNamespace(text="/start expected-code"),
        ),
        Update(
            2,
            SimpleNamespace(id=11),
            SimpleNamespace(id=21, type="private"),
            SimpleNamespace(text="unrelated message"),
        ),
        Update(
            3,
            SimpleNamespace(id=12),
            SimpleNamespace(id=22, type="private"),
            SimpleNamespace(text="/start expected-code"),
        ),
    ]

    class FakeBot:
        def __init__(self, _token: str) -> None:
            pass

        async def __aenter__(self) -> FakeBot:
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        async def get_updates(self, **kwargs: object) -> list[Update]:
            return [] if kwargs.get("timeout") == 0 else updates

    monkeypatch.setitem(sys.modules, "telegram", SimpleNamespace(Bot=FakeBot))

    identity = await wait_for_pairing(
        "private-token",
        "expected-code",
        AgentState(tmp_path / "state.sqlite"),
        timeout_seconds=30,
    )

    assert identity == (12, 22)


def test_personal_setup_validates_stores_and_pairs_without_printing_token(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    async def validate(_token: str) -> str:
        return "my_private_bot"

    async def pair(
        _token: str,
        pairing_code: str,
        _state: object,
        *,
        timeout_seconds: int,
    ) -> tuple[int, int]:
        assert pairing_code == "one-use-code"
        assert timeout_seconds == 30
        return 101, 202

    qr_urls: list[str] = []
    monkeypatch.setattr("resume_builder.agent_telegram_setup.validate_personal_bot", validate)
    monkeypatch.setattr("resume_builder.agent_telegram_setup.wait_for_pairing", pair)
    monkeypatch.setattr("resume_builder.agent_telegram_setup._print_qr", qr_urls.append)
    monkeypatch.setattr(
        "resume_builder.agent_telegram_setup.secrets.token_urlsafe",
        lambda _size: "one-use-code",
    )
    config_path = tmp_path / "workspace" / "agent" / "config.yml"
    state_path = tmp_path / "runtime" / "agent-state.sqlite"
    token_path = tmp_path / "runtime" / "telegram-token"

    result = run_personal_telegram_setup(
        config_path=config_path,
        state_path=state_path,
        token_path=token_path,
        timeout_seconds=30,
        open_browser=False,
        read=lambda _prompt: "",
        read_secret=lambda _prompt: "123:private-token",
    )

    assert result == 0
    assert token_path.read_text(encoding="utf-8").strip() == "123:private-token"
    assert qr_urls == ["https://t.me/my_private_bot?start=one-use-code"]
    assert load_agent_config(config_path).channels.telegram.allowed_user_ids == (101,)
    output = capsys.readouterr().out
    assert "123:private-token" not in output
    assert "Connected @my_private_bot" in output
