"""Tests for the private Telegram communication channel."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from resume_builder.agent_config import AgentConfig, load_agent_config, render_default_agent_config
from resume_builder.agent_contracts import InboundMessage, OutboundMessage
from resume_builder.agent_state import AgentState
from resume_builder.agent_telegram import TelegramAdapter, split_message


def telegram_config(tmp_path: Path) -> AgentConfig:
    path = tmp_path / "agent.yml"
    text = (
        render_default_agent_config()
        .replace(
            "enabled: false\n    token_env:",
            "enabled: true\n    token_env:",
        )
        .replace(
            "allowed_user_ids: []\n    allowed_chat_ids: []",
            "allowed_user_ids: [101]\n    allowed_chat_ids: [202]",
        )
    )
    path.write_text(text, encoding="utf-8")
    return load_agent_config(path)


class FakeService:
    def __init__(self, reply: str | None = None) -> None:
        self.calls: list[tuple[InboundMessage, dict[str, object]]] = []
        self.reply = reply

    def respond(self, inbound: InboundMessage, **kwargs: object) -> OutboundMessage:
        self.calls.append((inbound, kwargs))
        return OutboundMessage(
            inbound.conversation_id,
            self.reply if self.reply is not None else f"Reply to {inbound.text}",
        )


def test_split_message_stays_under_telegram_limit() -> None:
    chunks = split_message("word " * 2000)

    assert len(chunks) > 1
    assert all(0 < len(chunk) <= 4000 for chunk in chunks)
    assert all(len(chunk) < 4096 for chunk in chunks)


@pytest.mark.asyncio
async def test_telegram_rejects_unauthorized_sender_before_provider_call(tmp_path: Path) -> None:
    config = telegram_config(tmp_path)
    service = FakeService()
    adapter = TelegramAdapter(config, service, AgentState(tmp_path / "state.sqlite"))
    sent: list[str] = []

    async def send(text: str) -> None:
        sent.append(text)

    await adapter.process_text(
        update_id=1,
        user_id=999,
        chat_id=202,
        chat_type="private",
        text="What jobs are new?",
        send=send,
    )

    assert service.calls == []
    assert sent == []


@pytest.mark.asyncio
async def test_telegram_processes_authorized_update_only_once(tmp_path: Path) -> None:
    config = telegram_config(tmp_path)
    service = FakeService()
    state = AgentState(tmp_path / "state.sqlite")
    adapter = TelegramAdapter(config, service, state)
    sent: list[str] = []

    async def send(text: str) -> None:
        sent.append(text)

    request = {
        "update_id": 7,
        "user_id": 101,
        "chat_id": 202,
        "chat_type": "private",
        "text": "What jobs are new?",
        "send": send,
    }
    await adapter.process_text(**request)
    await adapter.process_text(**request)

    assert len(service.calls) == 1
    assert sent == ["Reply to What jobs are new?"]
    assert state.get_update(7) is not None
    assert state.get_update(7).status == "sent"
    assert state.get_update(7).chat_id is None
    assert service.calls[0][1]["retain_history"] is False


@pytest.mark.asyncio
async def test_ready_response_is_retried_without_another_provider_call(tmp_path: Path) -> None:
    config = telegram_config(tmp_path)
    service = FakeService()
    state = AgentState(tmp_path / "state.sqlite")
    state.start_update(
        8,
        user_id=101,
        chat_id=202,
        chat_type="private",
        request_text="Original request",
    )
    state.mark_update_ready(8, "Stored reply")
    adapter = TelegramAdapter(config, service, state)
    sent: list[str] = []

    async def send(text: str) -> None:
        sent.append(text)

    await adapter.process_text(
        update_id=8,
        user_id=101,
        chat_id=202,
        chat_type="private",
        text="Original request",
        send=send,
    )

    assert service.calls == []
    assert sent == ["Stored reply"]
    assert state.get_update(8).status == "sent"
    assert state.load_history("telegram", "202", max_turns=20)[-1].text == "Stored reply"


@pytest.mark.asyncio
async def test_delivery_recovery_resumes_at_first_unsent_chunk(tmp_path: Path) -> None:
    config = telegram_config(tmp_path)
    reply = f"{'a' * 4000}\nsecond chunk"
    service = FakeService(reply)
    state = AgentState(tmp_path / "state.sqlite")
    adapter = TelegramAdapter(config, service, state)
    attempts = 0
    initially_sent: list[str] = []

    async def fail_on_second_chunk(text: str) -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 2:
            raise OSError("network unavailable")
        initially_sent.append(text)

    await adapter.process_text(
        update_id=9,
        user_id=101,
        chat_id=202,
        chat_type="private",
        text="Original request",
        send=fail_on_second_chunk,
    )

    queued = state.get_update(9)
    assert queued is not None
    assert queued.status == "ready"
    assert queued.next_chunk == 1
    assert state.load_history("telegram", "202", max_turns=20) == ()

    recovered: list[tuple[int, str]] = []

    async def send_recovered(chat_id: int, text: str) -> None:
        recovered.append((chat_id, text))

    await adapter.recover_pending(send_recovered)

    assert recovered == [(202, "second chunk")]
    assert state.get_update(9).status == "sent"
    history = state.load_history("telegram", "202", max_turns=20)
    assert [turn.text for turn in history] == ["Original request", reply]


@pytest.mark.asyncio
async def test_processing_update_is_recovered_without_telegram_replay(tmp_path: Path) -> None:
    config = telegram_config(tmp_path)
    service = FakeService()
    state = AgentState(tmp_path / "state.sqlite")
    state.start_update(
        10,
        user_id=101,
        chat_id=202,
        chat_type="private",
        request_text="Resume this request",
    )
    adapter = TelegramAdapter(config, service, state)
    sent: list[tuple[int, str]] = []

    async def send(chat_id: int, text: str) -> None:
        sent.append((chat_id, text))

    await adapter.recover_pending(send)

    assert len(service.calls) == 1
    assert sent == [(202, "Reply to Resume this request")]
    assert state.get_update(10).status == "sent"


@pytest.mark.asyncio
async def test_forget_removes_history_and_pending_payloads(tmp_path: Path) -> None:
    config = telegram_config(tmp_path)
    state = AgentState(tmp_path / "state.sqlite")
    state.append_exchange("telegram", "202", "Private question", "Private answer", max_turns=20)
    state.start_update(
        11,
        user_id=101,
        chat_id=202,
        chat_type="private",
        request_text="Queued private question",
    )
    state.mark_update_ready(11, "Queued private answer")
    adapter = TelegramAdapter(config, FakeService(), state)

    removed = await adapter.forget(202)

    assert removed == 3
    assert state.load_history("telegram", "202", max_turns=20) == ()
    assert state.get_update(11) is None


def test_telegram_lock_prevents_a_second_consumer(tmp_path: Path) -> None:
    state = AgentState(tmp_path / "state.sqlite")

    with state.telegram_service_lock():
        with pytest.raises(ValueError, match="already running"):
            with state.telegram_service_lock():
                pass


def test_legacy_pending_payload_is_discarded_during_migration(tmp_path: Path) -> None:
    state_path = tmp_path / "legacy.sqlite"
    with sqlite3.connect(state_path) as connection:
        connection.execute(
            """
            CREATE TABLE telegram_updates(
                update_id INTEGER PRIMARY KEY,
                status TEXT NOT NULL,
                response_text TEXT,
                error_class TEXT,
                updated_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            "INSERT INTO telegram_updates VALUES (12, 'ready', 'private reply', NULL, '2026-01-01')"
        )

    state = AgentState(state_path)

    migrated = state.get_update(12)
    assert migrated is not None
    assert migrated.status == "failed"
    assert migrated.response_text is None


def test_clear_history_affects_only_selected_conversation(tmp_path: Path) -> None:
    state = AgentState(tmp_path / "state.sqlite")
    state.append_exchange("telegram", "202", "One", "Reply", max_turns=20)
    state.append_exchange("telegram", "303", "Other", "Reply", max_turns=20)

    assert state.clear_history("telegram", "202") == 2
    assert state.load_history("telegram", "202", max_turns=20) == ()
    assert len(state.load_history("telegram", "303", max_turns=20)) == 2
