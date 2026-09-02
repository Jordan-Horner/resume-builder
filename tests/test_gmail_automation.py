"""Tests for privacy-preserving Gmail application confirmation ingestion."""

from __future__ import annotations

import argparse
import base64
import json
import stat
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from resume_builder.applications import load_record
from resume_builder.gmail_automation import (
    GmailRuntimeState,
    _write_secret,
    classify_confirmation,
    parse_message,
    process_messages,
    scan,
)


def encoded(value: str) -> str:
    return base64.urlsafe_b64encode(value.encode()).decode().rstrip("=")


def gmail_payload(
    *,
    message_id: str = "gmail-1",
    subject: str = "Thank you for applying to Support Engineer at Akamai",
    body: str = "We received your application for the Support Engineer position at Akamai.",
    sender: str = "Akamai Recruiting <no-reply@myworkday.com>",
    received_at: datetime = datetime(2026, 9, 2, 14, 30, tzinfo=UTC),
) -> dict[str, Any]:
    return {
        "id": message_id,
        "threadId": f"thread-{message_id}",
        "historyId": "200",
        "internalDate": str(int(received_at.timestamp() * 1000)),
        "payload": {
            "mimeType": "multipart/alternative",
            "headers": [
                {"name": "From", "value": sender},
                {"name": "Subject", "value": subject},
                {"name": "Authentication-Results", "value": "mx.google; dmarc=pass"},
            ],
            "parts": [
                {"mimeType": "text/plain", "body": {"data": encoded(body)}},
                {
                    "mimeType": "text/html",
                    "body": {"data": encoded(f"<p>{body}</p>")},
                },
            ],
        },
    }


class FakeGateway:
    def __init__(self, messages: dict[str, dict[str, Any]]):
        self.messages = messages
        self.history_calls = 0

    def account_id(self) -> str:
        return "mailbox-opaque"

    def label_id(self, name: str) -> str:
        assert name == "Resume Builder"
        return "Label_123"

    def list_message_ids(self, *, query: str, label_id: str | None) -> list[str]:
        assert query
        return list(self.messages)

    def history_message_ids(
        self, *, start_history_id: str, label_id: str | None
    ) -> tuple[list[str], str]:
        assert start_history_id == "300"
        self.history_calls += 1
        return list(self.messages), "400"

    def get_message(self, message_id: str) -> dict[str, Any]:
        return self.messages[message_id]

    def current_history_id(self) -> str:
        return "300"


def test_parse_and_classify_application_confirmation_without_retaining_html():
    message = parse_message(gmail_payload())
    confirmation = classify_confirmation(message)

    assert message.sender == "no-reply@myworkday.com"
    assert "<p>" not in message.body
    assert confirmation is not None
    assert confirmation.company == "Akamai"
    assert confirmation.role == "Support Engineer"
    assert confirmation.confidence == 0.95


def test_classifier_rejects_job_alerts_and_incomplete_identity():
    alert = parse_message(
        gmail_payload(
            subject="Job alert: Support Engineer at Akamai",
            body="Thank you for applying filters. Here are recommended jobs.",
        )
    )
    incomplete = parse_message(
        gmail_payload(subject="Application received", body="We received your application.")
    )

    assert classify_confirmation(alert) is None
    assert classify_confirmation(incomplete) is None


def test_runtime_state_contains_only_identifiers_and_disposition(tmp_path: Path):
    state = GmailRuntimeState(tmp_path / "runtime" / "gmail.sqlite")
    message = parse_message(gmail_payload())
    state.record(
        account_id="mailbox-opaque",
        message=message,
        disposition="created",
        application_id="APP-1",
        event_id="EVT-1",
    )

    assert state.processed("mailbox-opaque", "gmail-1") is True
    raw = state.path.read_bytes()
    assert b"We received your application" not in raw
    assert b"Thank you for applying" not in raw
    assert state.status()["messages"] == 1


def test_secret_writer_is_owner_only_and_leaves_no_partial_file(tmp_path: Path):
    token = tmp_path / "credentials" / "gmail-token.json"

    _write_secret(token, '{"refresh_token":"opaque"}')
    _write_secret(token, '{"refresh_token":"replacement"}')

    assert token.read_text(encoding="utf-8") == '{"refresh_token":"replacement"}'
    assert stat.S_IMODE(token.stat().st_mode) == 0o600
    assert list(token.parent.glob("*.tmp")) == []


def test_high_confidence_confirmation_creates_application_automatically(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / ".resume-builder.json").write_text("{}\n", encoding="utf-8")
    state = GmailRuntimeState(tmp_path / "runtime" / "gmail.sqlite")
    gateway = FakeGateway({"gmail-1": gmail_payload()})

    result = process_messages(
        gateway=gateway,
        state=state,
        workspace=workspace,
        message_ids=["gmail-1"],
        apply=True,
    )

    assert result["created"] == 1
    application_id = result["changes"][0]["application_id"]
    record = load_record(workspace / "applications" / f"{application_id}.json")
    event = record["events"][0]
    assert event["status"] == "applied"
    assert event["event_type"] == "application_confirmed"
    assert event["source"]["type"] == "gmail-automation"
    assert event["automation"]["policy"]
    serialized = json.dumps(record)
    assert "We received your application" not in serialized
    assert "gmail-1" not in serialized


def test_confirmation_links_matching_manual_application_without_duplicate(tmp_path: Path):
    from resume_builder.applications import _write_or_preview, build_record

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / ".resume-builder.json").write_text("{}\n", encoding="utf-8")
    root = workspace / "applications"
    original = build_record(
        argparse.Namespace(
            company="Akamai",
            role="Support Engineer",
            on="2026-09-02",
            job_id=None,
            url=None,
            role_family=None,
            screen_category=None,
            match_classification=None,
            target=None,
            resume=None,
            note=None,
        ),
        workspace,
    )
    _write_or_preview(root, original, apply=True)
    state = GmailRuntimeState(tmp_path / "runtime" / "gmail.sqlite")
    gateway = FakeGateway({"gmail-1": gmail_payload()})

    result = process_messages(
        gateway=gateway,
        state=state,
        workspace=workspace,
        message_ids=["gmail-1"],
        apply=True,
    )

    assert result["linked"] == 1
    assert result["created"] == 0
    assert len(list(root.glob("APP-*.json"))) == 1
    stored = load_record(next(root.glob("APP-*.json")))
    assert len(stored["events"]) == 2


def test_incremental_scan_advances_cursor_only_when_applied(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / ".resume-builder.json").write_text("{}\n", encoding="utf-8")
    state = GmailRuntimeState(tmp_path / "runtime" / "gmail.sqlite")
    gateway = FakeGateway({"gmail-1": gmail_payload()})

    preview = scan(
        gateway=gateway,
        state=state,
        workspace=workspace,
        label="Resume Builder",
        query="newer_than:30d",
        backfill=False,
        apply=False,
    )
    assert preview["created"] == 1
    assert state.history_id("mailbox-opaque") is None
    assert not state.path.exists()

    applied = scan(
        gateway=gateway,
        state=state,
        workspace=workspace,
        label="Resume Builder",
        query="newer_than:30d",
        backfill=False,
        apply=True,
    )
    assert applied["created"] == 1
    assert state.history_id("mailbox-opaque") == "300"

    repeated = scan(
        gateway=gateway,
        state=state,
        workspace=workspace,
        label="Resume Builder",
        query="newer_than:30d",
        backfill=False,
        apply=True,
    )
    assert repeated["examined"] == 0
    assert gateway.history_calls == 1


def test_second_confirmation_for_same_application_is_content_free_duplicate(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / ".resume-builder.json").write_text("{}\n", encoding="utf-8")
    state = GmailRuntimeState(tmp_path / "runtime" / "gmail.sqlite")
    gateway = FakeGateway(
        {
            "gmail-1": gmail_payload(message_id="gmail-1"),
            "gmail-2": gmail_payload(message_id="gmail-2"),
        }
    )

    result = process_messages(
        gateway=gateway,
        state=state,
        workspace=workspace,
        message_ids=["gmail-1", "gmail-2"],
        apply=True,
    )

    assert result["created"] == 1
    assert result["duplicates"] == 1
    stored = load_record(next((workspace / "applications").glob("APP-*.json")))
    assert len(stored["events"]) == 1
