"""Tests for privacy-preserving Gmail application confirmation ingestion."""

from __future__ import annotations

import argparse
import base64
import json
import stat
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from resume_builder.applications import load_record
from resume_builder.gmail_automation import (
    DEFAULT_SCAN_QUERY,
    GMAIL_API_URL,
    GOOGLE_AUDIENCE_URL,
    GOOGLE_CLIENTS_URL,
    GOOGLE_PROJECT_URL,
    GmailRuntimeState,
    _classify_confirmation,
    _connect_step_payload,
    _follow_up_transition,
    _sender_domain_hash,
    _terminal_link,
    _validate_client_configuration,
    _write_secret,
    classify_confirmation,
    classify_lifecycle_event,
    parse_message,
    parser,
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


def test_classifier_accepts_common_transactional_confirmation_variants():
    thanks = parse_message(
        gmail_payload(subject="Thanks for applying to Support Engineer at Akamai")
    )
    sent = parse_message(
        gmail_payload(
            subject="Application received - Support Engineer at Akamai",
            body="Your application was sent. Application submitted.",
        )
    )

    assert classify_confirmation(thanks) is not None
    assert classify_confirmation(sent) is not None


def test_classifier_extracts_common_body_identity_formats():
    role_at_company = parse_message(
        gmail_payload(
            subject="Example Corp - Thank You for Applying",
            body=(
                "Thank you for applying for the Cloud Support Engineer role "
                "at Example Corp."
            ),
            sender="Example Recruiting <recruiting@example.com>",
        )
    )
    our_position = parse_message(
        gmail_payload(
            subject="Thanks for applying",
            body=(
                "Thank you for your interest in Example Corp. We are happy you chose "
                "to apply for our DevOps Engineer position."
            ),
            sender="Example Recruiting <recruiting@example.com>",
        )
    )

    first = classify_confirmation(role_at_company)
    second = classify_confirmation(our_position)

    assert first is not None
    assert (first.company, first.role) == ("Example Corp", "Cloud Support Engineer")
    assert second is not None
    assert (second.company, second.role) == ("Example Corp", "DevOps Engineer")


def test_classifier_rejects_nonsensical_or_malformed_identity_pairs():
    geography = parse_message(
        gmail_payload(subject="Thank you for applying to the at United States")
    )
    embedded_company = parse_message(
        gmail_payload(
            subject=(
                "Thank you for applying to Example Corp for the Security Engineer "
                "at Example Corp"
            )
        )
    )
    generic_future_language = parse_message(
        gmail_payload(
            subject="Thank you for applying to your skill set in the future at Example Corp"
        )
    )

    assert _classify_confirmation(geography) == (None, "invalid-identity-value")
    assert _classify_confirmation(embedded_company) == (None, "invalid-identity-value")
    assert _classify_confirmation(generic_future_language) == (None, "invalid-identity-value")


def test_thanks_for_your_interest_requires_body_context():
    ambiguous = parse_message(
        gmail_payload(
            subject="Thanks for your interest in Example Corp",
            body="We appreciate your interest in Example Corp.",
            sender="Example Recruiting <recruiting@example.com>",
        )
    )
    rejected = parse_message(
        gmail_payload(
            subject="Thanks for your interest in Example Corp",
            body=(
                "After careful consideration, we decided not to move forward "
                "with your application."
            ),
            sender="Example Recruiting <recruiting@example.com>",
        )
    )

    assert _classify_confirmation(ambiguous) == (None, "missing-confirmation-phrase")
    assert _classify_confirmation(rejected) == (None, "rejection-signal")


def test_conditional_rejection_boilerplate_is_not_a_rejection():
    message = parse_message(
        gmail_payload(
            subject="Thank you for your application to Example Corp",
            body=(
                "We received your application for the Support Engineer role at "
                "Example Corp. If you are not selected for this position, please "
                "consider future openings."
            ),
            sender="Example Recruiting <recruiting@example.com>",
        )
    )

    confirmation, reason = _classify_confirmation(message)

    assert reason == "confirmed"
    assert confirmation is not None


def test_move_forward_requires_negative_context():
    positive = parse_message(
        gmail_payload(
            subject="Application update from Example Corp",
            body=(
                "We received your application for the Support Engineer role at "
                "Example Corp and would like to move forward with your application."
            ),
            sender="Example Recruiting <recruiting@example.com>",
        )
    )
    unable = parse_message(
        gmail_payload(
            subject="Application update from Example Corp",
            body=(
                "We are unable to move forward with your application for the "
                "Support Engineer role at Example Corp."
            ),
            sender="Example Recruiting <recruiting@example.com>",
        )
    )
    not_moving = parse_message(
        gmail_payload(
            subject="An update from Example Corp",
            body="You are not moving forward in the process with Example Corp.",
            sender="Example Recruiting <recruiting@example.com>",
        )
    )

    assert _classify_confirmation(positive)[1] == "confirmed"
    assert _classify_confirmation(unable) == (None, "rejection-signal")
    assert _classify_confirmation(not_moving) == (None, "rejection-signal")


def test_quoted_rejection_text_does_not_override_current_message():
    message = parse_message(
        gmail_payload(
            subject="A new message from Example Corp",
            body=(
                "We would like to move forward with your application.\n\n"
                "On Tue, Sep 1, 2026 at 9:00 AM Recruiting wrote:\n"
                "> We are unable to move forward with your application."
            ),
            sender="Example Recruiting <recruiting@example.com>",
        )
    )

    event, reason = classify_lifecycle_event(message)

    assert event is None
    assert reason == "missing-confirmation-phrase"
    assert "unable to move forward" not in message.body


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
    assert b"myworkday.com" not in raw
    assert state.status()["messages"] == 1


def test_ambiguous_messages_require_explicit_replay(tmp_path: Path):
    state = GmailRuntimeState(tmp_path / "runtime" / "gmail.sqlite")
    message = parse_message(gmail_payload(message_id="unresolved"))
    state.record(
        account_id="mailbox-opaque",
        message=message,
        disposition="ambiguous",
        application_id=None,
        event_id=None,
    )

    assert state.processed("mailbox-opaque", "unresolved") is True
    assert (
        state.processed("mailbox-opaque", "unresolved", replay_ambiguous=True) is False
    )


def test_shared_recruiting_platform_domains_are_not_application_identity():
    assert _sender_domain_hash("updates@myworkday.com") is None
    assert _sender_domain_hash("jobs@notifications.greenhouse.io") is None
    assert _sender_domain_hash("recruiting@example.com") is not None


def test_follow_up_transitions_do_not_regress_or_reopen_terminal_applications():
    assert _follow_up_transition("recruiter_contact", "assessment") is None
    assert _follow_up_transition("interview_invited", "offer") is None
    assert _follow_up_transition("offer_received", "rejected") is None
    assert _follow_up_transition("assessment_invited", "screen_scheduled") == (
        "assessment",
        "Assessment",
    )


def test_secret_writer_is_owner_only_and_leaves_no_partial_file(tmp_path: Path):
    token = tmp_path / "credentials" / "gmail-token.json"

    _write_secret(token, '{"refresh_token":"opaque"}')
    _write_secret(token, '{"refresh_token":"replacement"}')

    assert token.read_text(encoding="utf-8") == '{"refresh_token":"replacement"}'
    assert stat.S_IMODE(token.stat().st_mode) == 0o600
    assert list(token.parent.glob("*.tmp")) == []


def desktop_client(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "installed": {
                    "client_id": "client.apps.googleusercontent.com",
                    "client_secret": "desktop-secret",
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                }
            }
        ),
        encoding="utf-8",
    )
    return path


def test_oauth_client_configuration_requires_desktop_application(tmp_path: Path):
    desktop = desktop_client(tmp_path / "desktop.json")
    web = tmp_path / "web.json"
    web.write_text(json.dumps({"web": {"client_id": "wrong-type"}}), encoding="utf-8")

    assert _validate_client_configuration(desktop) == desktop
    try:
        _validate_client_configuration(web)
    except ValueError as exc:
        assert "Desktop app" in str(exc)
    else:
        raise AssertionError("web OAuth clients must be rejected")


def test_connect_setup_returns_one_structured_step_at_a_time():
    first = _connect_step_payload(1)
    third = _connect_step_payload(3)
    fourth = _connect_step_payload(4)
    final = _connect_step_payload(6)

    assert first["step"] == {
        "number": 1,
        "total": 6,
        "title": "Create or select a Google Cloud project",
        "instruction": "Use a dedicated project or select one you already control.",
        "link": {"label": "Open Google Cloud project setup", "url": GOOGLE_PROJECT_URL},
    }
    assert first["next"]["command"] == "resume-builder gmail connect --step 2"
    assert "Internal only" in third["step"]["instruction"]
    assert "otherwise choose External" in third["step"]["instruction"]
    assert fourth["step"]["link"]["url"] == GOOGLE_AUDIENCE_URL
    assert final["step"]["link"]["url"] == GOOGLE_CLIENTS_URL
    assert "--credentials" in final["next"]["command"]


def test_connect_setup_rejects_unknown_step():
    try:
        _connect_step_payload(7)
    except ValueError as exc:
        assert "between 1 and 6" in str(exc)
    else:
        raise AssertionError("unknown Gmail setup steps must be rejected")


def test_terminal_setup_link_uses_clickable_escape_and_visible_target():
    rendered = _terminal_link("Enable Gmail", GMAIL_API_URL)

    assert rendered.startswith("\033]8;;")
    assert "Enable Gmail" in rendered
    assert GMAIL_API_URL in rendered


def test_connect_command_defaults_to_guided_setup():
    args = parser().parse_args(["connect"])

    assert args.credentials is None
    assert args.step == 1


def test_scan_can_explicitly_replay_ambiguous_messages():
    args = parser().parse_args(["scan", "--replay-ambiguous"])

    assert args.replay_ambiguous is True


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


def test_default_scan_uses_confirmation_query_without_a_label(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / ".resume-builder.json").write_text("{}\n", encoding="utf-8")
    state = GmailRuntimeState(tmp_path / "runtime" / "gmail.sqlite")
    gateway = FakeGateway({"gmail-1": gmail_payload()})

    result = scan(
        gateway=gateway,
        state=state,
        workspace=workspace,
        label="",
        query=DEFAULT_SCAN_QUERY,
        backfill=False,
        apply=True,
    )
    repeated = scan(
        gateway=gateway,
        state=state,
        workspace=workspace,
        label="",
        query=DEFAULT_SCAN_QUERY,
        backfill=False,
        apply=True,
    )

    assert result["mode"] == "query"
    assert result["created"] == 1
    assert repeated["examined"] == 0
    assert state.history_id("mailbox-opaque") is None
    assert gateway.history_calls == 0


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


def test_confirmation_then_rejection_updates_one_application_chronologically(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / ".resume-builder.json").write_text("{}\n", encoding="utf-8")
    state = GmailRuntimeState(tmp_path / "runtime" / "gmail.sqlite")
    confirmation = gmail_payload(
        message_id="confirmation",
        subject="Thank you for applying to Support Engineer at Example Corp",
        body="We received your application for the Support Engineer role at Example Corp.",
        sender="Example Recruiting <recruiting@example.com>",
        received_at=datetime(2026, 8, 20, 14, 30, tzinfo=UTC),
    )
    rejection = gmail_payload(
        message_id="rejection",
        subject="Application update from Example Corp",
        body=(
            "We are unable to move forward with your application for the "
            "Support Engineer role at Example Corp."
        ),
        sender="Example Recruiting <recruiting@example.com>",
        received_at=datetime(2026, 8, 25, 14, 30, tzinfo=UTC),
    )
    gateway = FakeGateway({"rejection": rejection, "confirmation": confirmation})

    result = process_messages(
        gateway=gateway,
        state=state,
        workspace=workspace,
        message_ids=["rejection", "confirmation"],
        apply=True,
    )

    assert result["created"] == 1
    assert result["rejected"] == 1
    assert [change["action"] for change in result["changes"]] == ["created", "rejected"]
    stored = load_record(next((workspace / "applications").glob("APP-*.json")))
    assert [event["status"] for event in stored["events"]] == ["applied", "rejected"]
    rejection_event = stored["events"][1]
    assert rejection_event["event_type"] == "rejection_received"
    assert rejection_event["automation"]["match_confidence"] == 0.99
    serialized = json.dumps(stored)
    assert "unable to move forward" not in serialized
    assert "rejection" not in rejection_event["source"]["reference"]


def test_unmatched_rejection_never_creates_an_application(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / ".resume-builder.json").write_text("{}\n", encoding="utf-8")
    state = GmailRuntimeState(tmp_path / "runtime" / "gmail.sqlite")
    gateway = FakeGateway(
        {
            "update": gmail_payload(
                message_id="update",
                subject="Application update from Example Corp",
                body=(
                    "We are unable to move forward with your application for the "
                    "Support Engineer role at Example Corp."
                ),
                sender="Example Recruiting <recruiting@example.com>",
            )
        }
    )

    result = process_messages(
        gateway=gateway,
        state=state,
        workspace=workspace,
        message_ids=["update"],
        apply=True,
    )

    assert result["ambiguous"] == 1
    assert result["created"] == 0
    assert result["rejected"] == 0
    assert list((workspace / "applications").glob("APP-*.json")) == []


@pytest.mark.parametrize(
    ("body", "event_type", "counter", "expected_status"),
    [
        (
            "We would like to speak with you about your application for the Support "
            "Engineer role at Example Corp.",
            "recruiter_contact",
            "recruiter_contacts",
            "recruiter_contact",
        ),
        (
            "We invite you to interview. This concerns your application for the Support "
            "Engineer role at Example Corp.",
            "interview_invited",
            "interviews",
            "screen_scheduled",
        ),
        (
            "Please complete the technical assessment for your application for the Support "
            "Engineer role at Example Corp.",
            "assessment_invited",
            "assessments",
            "assessment",
        ),
        (
            "We are pleased to offer you the Support Engineer role at Example Corp. Your "
            "application for the Support Engineer role was successful.",
            "offer_received",
            "offers",
            "offer",
        ),
    ],
)
def test_follow_up_lifecycle_events_update_a_unique_existing_application(
    tmp_path: Path,
    body: str,
    event_type: str,
    counter: str,
    expected_status: str,
):
    from resume_builder.applications import _write_or_preview, build_record

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / ".resume-builder.json").write_text("{}\n", encoding="utf-8")
    root = workspace / "applications"
    record = build_record(
        argparse.Namespace(
            company="Example Corp",
            role="Support Engineer",
            on="2026-08-20",
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
    _write_or_preview(root, record, apply=True)
    state = GmailRuntimeState(tmp_path / "runtime" / "gmail.sqlite")
    gateway = FakeGateway(
        {
            "follow-up": gmail_payload(
                message_id="follow-up",
                subject="Application update from Example Corp",
                body=body,
                sender="Example Recruiting <recruiting@example.com>",
                received_at=datetime(2026, 8, 25, 14, 30, tzinfo=UTC),
            )
        }
    )

    classified, _ = classify_lifecycle_event(parse_message(gateway.messages["follow-up"]))
    assert classified is not None
    assert classified.event_type == event_type

    result = process_messages(
        gateway=gateway,
        state=state,
        workspace=workspace,
        message_ids=["follow-up"],
        apply=True,
    )

    assert result[counter] == 1
    stored = load_record(root / f"{record['application']['id']}.json")
    assert stored["events"][-1]["status"] == expected_status
    assert stored["events"][-1]["event_type"] == event_type
    assert "application for" not in json.dumps(stored)


def test_direct_company_domain_can_link_an_identity_free_interview_follow_up(tmp_path: Path):
    from resume_builder.applications import _write_or_preview, build_record

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / ".resume-builder.json").write_text("{}\n", encoding="utf-8")
    root = workspace / "applications"
    record = build_record(
        argparse.Namespace(
            company="Example Corp",
            role="Support Engineer",
            on="2026-08-20",
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
    _write_or_preview(root, record, apply=True)
    state = GmailRuntimeState(tmp_path / "runtime" / "gmail.sqlite")
    confirmation = parse_message(
        gmail_payload(
            message_id="confirmation",
            sender="Example Recruiting <notifications@example.com>",
        )
    )
    state.record(
        account_id="mailbox-opaque",
        message=confirmation,
        disposition="linked",
        application_id=record["application"]["id"],
        event_id=record["events"][0]["id"],
    )
    gateway = FakeGateway(
        {
            "interview": gmail_payload(
                message_id="interview",
                subject="Next steps",
                body="We would like to interview you. Please share your availability.",
                sender="Recruiter <recruiter@example.com>",
            )
        }
    )

    result = process_messages(
        gateway=gateway,
        state=state,
        workspace=workspace,
        message_ids=["interview"],
        apply=True,
    )

    assert result["interviews"] == 1
    assert result["changes"][0]["match_method"] == "sender-domain"


def test_preview_reuses_company_domain_associations_learned_in_the_same_batch(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / ".resume-builder.json").write_text("{}\n", encoding="utf-8")
    state = GmailRuntimeState(tmp_path / "runtime" / "gmail.sqlite")
    confirmation = gmail_payload(
        message_id="confirmation",
        subject="Thank you for applying to Support Engineer at Example Corp",
        body="We received your application for the Support Engineer role at Example Corp.",
        sender="Example Recruiting <notifications@example.com>",
        received_at=datetime(2026, 8, 20, 14, 30, tzinfo=UTC),
    )
    interview = gmail_payload(
        message_id="interview",
        subject="Next steps",
        body="We would like to interview you. Please share your availability.",
        sender="Recruiter <recruiter@example.com>",
        received_at=datetime(2026, 8, 25, 14, 30, tzinfo=UTC),
    )
    gateway = FakeGateway({"interview": interview, "confirmation": confirmation})

    result = process_messages(
        gateway=gateway,
        state=state,
        workspace=workspace,
        message_ids=["interview", "confirmation"],
        apply=False,
    )

    assert result["created"] == 1
    assert result["interviews"] == 1
    assert result["changes"][1]["match_method"] == "sender-domain"
    assert state.path.exists() is False
