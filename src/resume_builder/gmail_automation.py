"""Privacy-preserving Gmail ingestion for automatic application confirmations."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import sqlite3
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from email.utils import parseaddr
from pathlib import Path
from typing import Any, Protocol

from bs4 import BeautifulSoup

from job_puller.config import load_config, resolve_database_path
from job_puller.database import InventoryDatabase

from .applications import (
    DEFAULT_ROOT as DEFAULT_APPLICATIONS_ROOT,
)
from .applications import (
    _write_or_preview,
    append_event,
    build_automated_record,
    iter_records,
)
from .jobs import DEFAULT_CONFIG

GMAIL_READONLY_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
CLASSIFIER_VERSION = "application-confirmation-rules-v1"
AUTOMATION_POLICY = "high-confidence-application-confirmation-v1"
AUTO_APPLY_THRESHOLD = 0.92
DEFAULT_LABEL = "Resume Builder"
DEFAULT_BACKFILL_QUERY = (
    '{"thank you for applying" "we received your application" '
    '"application has been received" "application was submitted" '
    '"application has been submitted"} newer_than:5y'
)
MAX_BODY_CHARS = 100_000
TOKEN = re.compile(r"[a-z0-9]+")
REQUISITION = re.compile(
    r"\b(?:job|requisition|req)(?:\s+(?:id|number|#))?\s*[:#-]?\s*([A-Z0-9][A-Z0-9-]{2,})\b",
    re.IGNORECASE,
)
CONFIRMATION_PHRASES = (
    re.compile(r"\bthank you for applying\b", re.IGNORECASE),
    re.compile(r"\bwe (?:have )?received your application\b", re.IGNORECASE),
    re.compile(r"\byour application (?:has been|was) (?:received|submitted)\b", re.IGNORECASE),
    re.compile(r"\bapplication (?:has been|was) successfully submitted\b", re.IGNORECASE),
)
EXCLUDED_PHRASES = (
    "job alert",
    "jobs you may be interested in",
    "recommended jobs",
    "complete your application",
    "application incomplete",
)
SUBJECT_IDENTITY_PATTERNS = (
    re.compile(
        r"thank you for applying (?:to|for) (?P<role>.+?) (?:at|with) (?P<company>.+)$",
        re.IGNORECASE,
    ),
    re.compile(
        r"application (?:received|submitted|confirmation)\s*[-:|]\s*"
        r"(?P<role>.+?)\s+(?:at|with|[-|])\s+(?P<company>.+)$",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?P<company>.+?)\s*[-:|]\s*application (?:received|confirmation)\s*"
        r"[-:|]\s*(?P<role>.+)$",
        re.IGNORECASE,
    ),
)
COMPANY_PATTERNS = (
    re.compile(r"thank you for applying (?:to|with) (?P<company>[^\n.!|]+)", re.IGNORECASE),
    re.compile(r"application (?:to|with) (?P<company>[^\n.!|]+)", re.IGNORECASE),
)
ROLE_PATTERNS = (
    re.compile(
        r"application (?:for|to) (?:the )?(?P<role>[^\n.!]{3,100}?) (?:position|role)\b",
        re.IGNORECASE,
    ),
    re.compile(r"position (?:of|for) (?P<role>[^\n.!]{3,100})", re.IGNORECASE),
    re.compile(r"role (?:of|for) (?P<role>[^\n.!]{3,100})", re.IGNORECASE),
)


@dataclass(frozen=True)
class GmailMessage:
    id: str
    thread_id: str
    history_id: str
    received_at: datetime
    sender: str
    subject: str
    body: str
    authentication_results: str


@dataclass(frozen=True)
class ApplicationConfirmation:
    company: str
    role: str
    requisition_id: str | None
    received_at: datetime
    confidence: float


class GmailGateway(Protocol):
    def account_id(self) -> str: ...

    def label_id(self, name: str) -> str: ...

    def list_message_ids(self, *, query: str, label_id: str | None) -> list[str]: ...

    def history_message_ids(
        self, *, start_history_id: str, label_id: str | None
    ) -> tuple[list[str], str]: ...

    def get_message(self, message_id: str) -> dict[str, Any]: ...

    def current_history_id(self) -> str: ...


class GmailRuntimeState:
    """External, content-free state for incremental and idempotent Gmail processing."""

    def __init__(self, path: Path):
        self.path = path.expanduser().resolve()

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor = os.open(self.path, os.O_WRONLY | os.O_CREAT, 0o600)
        os.close(descriptor)
        os.chmod(self.path, 0o600)
        with sqlite3.connect(self.path) as conn:
            conn.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS mailbox_state(
                    account_id TEXT PRIMARY KEY,
                    history_id TEXT,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS processed_messages(
                    account_id TEXT NOT NULL,
                    message_id TEXT NOT NULL,
                    thread_id TEXT NOT NULL,
                    received_at TEXT NOT NULL,
                    disposition TEXT NOT NULL,
                    application_id TEXT,
                    event_id TEXT,
                    classifier_version TEXT NOT NULL,
                    processed_at TEXT NOT NULL,
                    PRIMARY KEY(account_id, message_id)
                );
                """
            )
        os.chmod(self.path, 0o600)

    def history_id(self, account_id: str) -> str | None:
        if not self.path.is_file():
            return None
        with sqlite3.connect(self.path) as conn:
            row = conn.execute(
                "SELECT history_id FROM mailbox_state WHERE account_id=?", (account_id,)
            ).fetchone()
        return str(row[0]) if row and row[0] else None

    def set_history_id(self, account_id: str, history_id: str) -> None:
        self.initialize()
        now = datetime.now(UTC).isoformat()
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                """INSERT INTO mailbox_state(account_id, history_id, updated_at)
                   VALUES (?, ?, ?)
                   ON CONFLICT(account_id) DO UPDATE SET
                     history_id=excluded.history_id, updated_at=excluded.updated_at""",
                (account_id, history_id, now),
            )

    def processed(self, account_id: str, message_id: str) -> bool:
        if not self.path.is_file():
            return False
        with sqlite3.connect(self.path) as conn:
            row = conn.execute(
                """SELECT disposition, classifier_version FROM processed_messages
                   WHERE account_id=? AND message_id=?""",
                (account_id, message_id),
            ).fetchone()
        if row is None:
            return False
        return (
            str(row[0]) in {"created", "linked", "duplicate"} or str(row[1]) == CLASSIFIER_VERSION
        )

    def record(
        self,
        *,
        account_id: str,
        message: GmailMessage,
        disposition: str,
        application_id: str | None,
        event_id: str | None,
    ) -> None:
        self.initialize()
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                """INSERT INTO processed_messages(
                       account_id, message_id, thread_id, received_at, disposition,
                       application_id, event_id, classifier_version, processed_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(account_id, message_id) DO UPDATE SET
                     thread_id=excluded.thread_id,
                     received_at=excluded.received_at,
                     disposition=excluded.disposition,
                     application_id=excluded.application_id,
                     event_id=excluded.event_id,
                     classifier_version=excluded.classifier_version,
                     processed_at=excluded.processed_at
                   WHERE processed_messages.disposition NOT IN ('created','linked','duplicate')""",
                (
                    account_id,
                    message.id,
                    message.thread_id,
                    message.received_at.isoformat(),
                    disposition,
                    application_id,
                    event_id,
                    CLASSIFIER_VERSION,
                    datetime.now(UTC).isoformat(),
                ),
            )

    def status(self) -> dict[str, object]:
        if not self.path.is_file():
            return {"initialized": False, "path": str(self.path), "mailboxes": 0, "messages": 0}
        with sqlite3.connect(self.path) as conn:
            mailboxes = conn.execute("SELECT COUNT(*) FROM mailbox_state").fetchone()[0]
            messages = conn.execute("SELECT COUNT(*) FROM processed_messages").fetchone()[0]
            dispositions = {
                str(row[0]): int(row[1])
                for row in conn.execute(
                    "SELECT disposition, COUNT(*) FROM processed_messages GROUP BY disposition"
                )
            }
        return {
            "initialized": True,
            "path": str(self.path),
            "mailboxes": mailboxes,
            "messages": messages,
            "dispositions": dispositions,
        }


class GoogleGmailGateway:
    def __init__(self, service: Any):
        self.service = service

    def account_id(self) -> str:
        address = str(self.service.users().getProfile(userId="me").execute()["emailAddress"])
        return hashlib.sha256(address.casefold().encode()).hexdigest()[:20]

    def label_id(self, name: str) -> str:
        labels = self.service.users().labels().list(userId="me").execute().get("labels", [])
        for label in labels:
            if str(label.get("name", "")).casefold() == name.casefold():
                return str(label["id"])
        raise ValueError(f'Gmail label not found: "{name}"')

    def list_message_ids(self, *, query: str, label_id: str | None) -> list[str]:
        ids: list[str] = []
        token: str | None = None
        while True:
            request: dict[str, Any] = {"userId": "me", "q": query, "maxResults": 500}
            if label_id:
                request["labelIds"] = [label_id]
            if token:
                request["pageToken"] = token
            payload = self.service.users().messages().list(**request).execute()
            ids.extend(str(item["id"]) for item in payload.get("messages", []))
            token = payload.get("nextPageToken")
            if not token:
                return ids

    def history_message_ids(
        self, *, start_history_id: str, label_id: str | None
    ) -> tuple[list[str], str]:
        ids: set[str] = set()
        token: str | None = None
        latest = start_history_id
        while True:
            request: dict[str, Any] = {
                "userId": "me",
                "startHistoryId": start_history_id,
                "historyTypes": ["messageAdded", "labelAdded"],
                "maxResults": 500,
            }
            if label_id:
                request["labelId"] = label_id
            if token:
                request["pageToken"] = token
            payload = self.service.users().history().list(**request).execute()
            latest = str(payload.get("historyId", latest))
            for history in payload.get("history", []):
                for entry in history.get("messagesAdded", []):
                    ids.add(str(entry["message"]["id"]))
                for entry in history.get("labelsAdded", []):
                    ids.add(str(entry["message"]["id"]))
            token = payload.get("nextPageToken")
            if not token:
                return sorted(ids), latest

    def get_message(self, message_id: str) -> dict[str, Any]:
        return (
            self.service.users().messages().get(userId="me", id=message_id, format="full").execute()
        )

    def current_history_id(self) -> str:
        return str(self.service.users().getProfile(userId="me").execute()["historyId"])


def default_state_path() -> Path:
    override = os.environ.get("RESUME_BUILDER_GMAIL_STATE")
    if override:
        return Path(override).expanduser()
    if sys.platform == "darwin":
        return (
            Path.home()
            / "Library"
            / "Application Support"
            / "Resume Builder"
            / "gmail-state.sqlite"
        )
    base = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
    return base / "resume-builder" / "gmail-state.sqlite"


def default_token_path(state_path: Path) -> Path:
    override = os.environ.get("RESUME_BUILDER_GMAIL_TOKEN")
    return Path(override).expanduser() if override else state_path.parent / "gmail-token.json"


def _require_external(path: Path, workspace: Path, label: str) -> Path:
    resolved = path.expanduser().resolve()
    engine = Path(__file__).resolve().parents[2]
    for repository in (workspace.resolve(), engine):
        try:
            resolved.relative_to(repository)
        except ValueError:
            continue
        raise ValueError(f"{label} must be outside the private workspace and engine repository")
    return resolved


def _write_secret(path: Path, content: str) -> None:
    """Atomically write an owner-only credential file outside both repositories."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    finally:
        temporary.unlink(missing_ok=True)


def connect_google(credentials_path: Path, token_path: Path) -> None:
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError as exc:
        raise ValueError(
            'Gmail support is not installed; install with `pip install -e ".[gmail]"`'
        ) from exc
    if not credentials_path.is_file():
        raise ValueError(f"Google OAuth client file not found: {credentials_path}")
    flow = InstalledAppFlow.from_client_secrets_file(
        str(credentials_path), scopes=[GMAIL_READONLY_SCOPE]
    )
    credentials = flow.run_local_server(port=0, access_type="offline", prompt="consent")
    _write_secret(token_path, credentials.to_json())


def google_gateway(token_path: Path) -> GoogleGmailGateway:
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
    except ImportError as exc:
        raise ValueError(
            'Gmail support is not installed; install with `pip install -e ".[gmail]"`'
        ) from exc
    if not token_path.is_file():
        raise ValueError("Gmail is not connected; run `resume-builder gmail connect` first")
    credentials = Credentials.from_authorized_user_file(str(token_path), [GMAIL_READONLY_SCOPE])
    if credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())
        _write_secret(token_path, credentials.to_json())
    if not credentials.valid:
        raise ValueError("Gmail credentials are invalid; reconnect the account")
    return GoogleGmailGateway(build("gmail", "v1", credentials=credentials, cache_discovery=False))


def _decode(data: str) -> str:
    if not data:
        return ""
    padding = "=" * (-len(data) % 4)
    try:
        return base64.urlsafe_b64decode(data + padding).decode("utf-8", errors="replace")
    except ValueError:
        return ""


def _body_parts(payload: dict[str, Any]) -> tuple[list[str], list[str]]:
    plain: list[str] = []
    html: list[str] = []
    queue = [payload]
    while queue:
        part = queue.pop()
        queue.extend(item for item in part.get("parts", []) if isinstance(item, dict))
        mime = str(part.get("mimeType", "")).casefold()
        data = str(part.get("body", {}).get("data", ""))
        if not data:
            continue
        decoded = _decode(data)
        if mime == "text/plain":
            plain.append(decoded)
        elif mime == "text/html":
            html.append(decoded)
    return plain, html


def parse_message(payload: dict[str, Any]) -> GmailMessage:
    headers = {
        str(item.get("name", "")).casefold(): str(item.get("value", ""))
        for item in payload.get("payload", {}).get("headers", [])
    }
    plain, html = _body_parts(payload.get("payload", {}))
    if plain:
        body = "\n".join(plain)
    else:
        body = "\n".join(
            BeautifulSoup(value, "html.parser").get_text("\n", strip=True) for value in html
        )
    received = datetime.fromtimestamp(int(payload["internalDate"]) / 1000, tz=UTC)
    return GmailMessage(
        id=str(payload["id"]),
        thread_id=str(payload.get("threadId", "")),
        history_id=str(payload.get("historyId", "")),
        received_at=received,
        sender=parseaddr(headers.get("from", ""))[1],
        subject=headers.get("subject", "").strip(),
        body=body[:MAX_BODY_CHARS],
        authentication_results=headers.get("authentication-results", ""),
    )


def _clean_identity(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip(" \t\r\n-:|,.;")


def _extract_identity(subject: str, body: str) -> tuple[str | None, str | None]:
    for pattern in SUBJECT_IDENTITY_PATTERNS:
        match = pattern.search(subject)
        if match:
            return _clean_identity(match.group("company")), _clean_identity(match.group("role"))
    combined = f"{subject}\n{body}"
    company = next(
        (
            _clean_identity(match.group("company"))
            for pattern in COMPANY_PATTERNS
            if (match := pattern.search(combined))
        ),
        None,
    )
    role = next(
        (
            _clean_identity(match.group("role"))
            for pattern in ROLE_PATTERNS
            if (match := pattern.search(combined))
        ),
        None,
    )
    return company, role


def classify_confirmation(message: GmailMessage) -> ApplicationConfirmation | None:
    text = f"{message.subject}\n{message.body}"
    folded = text.casefold()
    if any(phrase in folded for phrase in EXCLUDED_PHRASES):
        return None
    if not any(pattern.search(text) for pattern in CONFIRMATION_PHRASES):
        return None
    company, role = _extract_identity(message.subject, message.body)
    if not company or not role or len(company) > 120 or len(role) > 160:
        return None
    requisition_match = REQUISITION.search(text)
    authenticated = any(
        token in message.authentication_results.casefold()
        for token in ("dmarc=pass", "dkim=pass", "spf=pass")
    )
    confidence = 0.92 + (0.03 if authenticated else 0) + (0.02 if requisition_match else 0)
    return ApplicationConfirmation(
        company=company,
        role=role,
        requisition_id=requisition_match.group(1) if requisition_match else None,
        received_at=message.received_at,
        confidence=round(min(confidence, 0.99), 2),
    )


def _identity(value: str) -> str:
    return " ".join(TOKEN.findall(value.casefold()))


def _source_reference(account_id: str, message_id: str) -> str:
    return hashlib.sha256(f"{account_id}\x1f{message_id}".encode()).hexdigest()[:24]


def _inventory(workspace: Path) -> list[dict[str, object]]:
    config_path = workspace / DEFAULT_CONFIG
    if not config_path.is_file():
        return []
    config = load_config(config_path)
    database_path = resolve_database_path(config_path, config.database_path)
    if not database_path.is_file():
        return []
    return InventoryDatabase(database_path, config.raw_payload_retention_days).active_inventory()


def _match_job(
    confirmation: ApplicationConfirmation, inventory: Iterable[dict[str, object]]
) -> dict[str, object] | None:
    matches = [
        job
        for job in inventory
        if _identity(str(job.get("company", ""))) == _identity(confirmation.company)
        and _identity(str(job.get("title", ""))) == _identity(confirmation.role)
    ]
    return matches[0] if len(matches) == 1 else None


def _match_application(
    confirmation: ApplicationConfirmation, applications_root: Path
) -> dict[str, Any] | None:
    matches = [
        record
        for _, record in iter_records(applications_root)
        if _identity(record["application"]["company"]) == _identity(confirmation.company)
        and _identity(record["application"]["role"]) == _identity(confirmation.role)
        and abs(
            (
                date.fromisoformat(record["application"]["applied_on"])
                - confirmation.received_at.date()
            ).days
        )
        <= 3
    ]
    return matches[0] if len(matches) == 1 else None


def _already_confirmed(record: dict[str, Any], applied_on: str) -> bool:
    return any(
        event.get("event_type") == "application_confirmed"
        and event.get("effective_on") == applied_on
        for event in record["events"]
    )


def process_messages(
    *,
    gateway: GmailGateway,
    state: GmailRuntimeState,
    workspace: Path,
    message_ids: Iterable[str],
    apply: bool,
) -> dict[str, object]:
    account_id = gateway.account_id()
    applications_root = workspace / DEFAULT_APPLICATIONS_ROOT
    inventory = _inventory(workspace)
    summary: dict[str, Any] = {
        "examined": 0,
        "created": 0,
        "linked": 0,
        "ignored": 0,
        "ambiguous": 0,
        "duplicates": 0,
        "changes": [],
    }
    for message_id in message_ids:
        if state.processed(account_id, message_id):
            continue
        message = parse_message(gateway.get_message(message_id))
        summary["examined"] += 1
        confirmation = classify_confirmation(message)
        if confirmation is None:
            summary["ignored"] += 1
            if apply:
                state.record(
                    account_id=account_id,
                    message=message,
                    disposition="ignored",
                    application_id=None,
                    event_id=None,
                )
            continue
        if confirmation.confidence < AUTO_APPLY_THRESHOLD:
            summary["ambiguous"] += 1
            if apply:
                state.record(
                    account_id=account_id,
                    message=message,
                    disposition="ambiguous",
                    application_id=None,
                    event_id=None,
                )
            continue
        reference = _source_reference(account_id, message.id)
        existing = _match_application(confirmation, applications_root)
        if existing is not None:
            application_id = str(existing["application"]["id"])
            if _already_confirmed(existing, confirmation.received_at.date().isoformat()):
                summary["duplicates"] += 1
                if apply:
                    state.record(
                        account_id=account_id,
                        message=message,
                        disposition="duplicate",
                        application_id=application_id,
                        event_id=None,
                    )
                continue
            result = append_event(
                applications_root,
                application_id,
                "applied",
                confirmation.received_at.date().isoformat(),
                stage=None,
                feedback=None,
                note=None,
                supersedes=None,
                apply=apply,
                event_type="application_confirmed",
                occurred_at=confirmation.received_at.isoformat(),
                source_type="gmail-automation",
                source_reference=reference,
                confidence=confirmation.confidence,
                classifier_version=CLASSIFIER_VERSION,
                automation_policy=AUTOMATION_POLICY,
            )
            event_id = str(result["event"]["id"])
            summary["linked"] += 1
            action = "linked"
        else:
            job = _match_job(confirmation, inventory)
            job_id = str(job["id"]) if job else None
            application_url = (str(job.get("url", "")) or None) if job else None
            record = build_automated_record(
                company=confirmation.company,
                role=confirmation.role,
                applied_on=confirmation.received_at.date().isoformat(),
                occurred_at=confirmation.received_at.isoformat(),
                source_reference=reference,
                confidence=confirmation.confidence,
                classifier_version=CLASSIFIER_VERSION,
                automation_policy=AUTOMATION_POLICY,
                workspace=workspace,
                job_id=job_id,
                application_url=application_url,
            )
            try:
                result = _write_or_preview(applications_root, record, apply=apply)
            except ValueError as exc:
                if "already exists with different content" not in str(exc):
                    raise
                summary["ambiguous"] += 1
                if apply:
                    state.record(
                        account_id=account_id,
                        message=message,
                        disposition="ambiguous",
                        application_id=None,
                        event_id=None,
                    )
                continue
            application_id = str(record["application"]["id"])
            event_id = str(record["events"][0]["id"])
            summary["created"] += 1
            action = "created"
        summary["changes"].append(
            {
                "action": action,
                "application_id": application_id,
                "company": confirmation.company,
                "role": confirmation.role,
                "applied_on": confirmation.received_at.date().isoformat(),
                "confidence": confirmation.confidence,
            }
        )
        if apply:
            state.record(
                account_id=account_id,
                message=message,
                disposition=action,
                application_id=application_id,
                event_id=event_id,
            )
    return summary


def scan(
    *,
    gateway: GmailGateway,
    state: GmailRuntimeState,
    workspace: Path,
    label: str,
    query: str,
    backfill: bool,
    apply: bool,
) -> dict[str, object]:
    account_id = gateway.account_id()
    label_id = gateway.label_id(label) if label else None
    prior_history = None if backfill else state.history_id(account_id)
    recovered = False
    if prior_history:
        try:
            message_ids, next_history = gateway.history_message_ids(
                start_history_id=prior_history, label_id=label_id
            )
        except Exception as exc:
            if getattr(getattr(exc, "resp", None), "status", None) != 404:
                raise
            message_ids = gateway.list_message_ids(query=query, label_id=label_id)
            next_history = gateway.current_history_id()
            recovered = True
    else:
        message_ids = gateway.list_message_ids(query=query, label_id=label_id)
        next_history = gateway.current_history_id()
    result = process_messages(
        gateway=gateway,
        state=state,
        workspace=workspace,
        message_ids=message_ids,
        apply=apply,
    )
    if apply:
        state.set_history_id(account_id, next_history)
    return {
        "valid": True,
        "applied": apply,
        "mode": "backfill" if backfill else "incremental",
        "history_recovered": recovered,
        "raw_messages_retained": 0,
        **result,
    }


def parser() -> argparse.ArgumentParser:
    command_parser = argparse.ArgumentParser(prog="resume-builder gmail")
    command_parser.add_argument("--state", type=Path, default=default_state_path())
    command_parser.add_argument("--token", type=Path)
    commands = command_parser.add_subparsers(dest="command", required=True)

    connect = commands.add_parser("connect", help="Authorize one Gmail account read-only")
    connect.add_argument("--credentials", type=Path, required=True)

    scan_parser = commands.add_parser("scan", help="Process new labeled Gmail messages")
    scan_parser.add_argument("--label", default=DEFAULT_LABEL)
    scan_parser.add_argument("--query", default="newer_than:30d")
    scan_parser.add_argument("--apply", action="store_true")

    backfill = commands.add_parser("backfill", help="Find historical application confirmations")
    backfill.add_argument("--label", default="")
    backfill.add_argument("--query", default=DEFAULT_BACKFILL_QUERY)
    backfill.add_argument("--apply", action="store_true")

    commands.add_parser("status", help="Show content-free Gmail runtime state")
    disconnect = commands.add_parser("disconnect", help="Delete local Gmail credentials and state")
    disconnect.add_argument("--apply", action="store_true")
    return command_parser


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    workspace = Path.cwd().resolve()
    if not (workspace / ".resume-builder.json").is_file():
        print("gmail commands require an active private workspace", file=sys.stderr)
        return 2
    try:
        state_path = _require_external(args.state, workspace, "Gmail runtime state")
        token_path = _require_external(
            args.token or default_token_path(state_path), workspace, "Gmail OAuth token"
        )
        state = GmailRuntimeState(state_path)
        if args.command == "connect":
            credentials_path = _require_external(
                args.credentials, workspace, "Google OAuth client configuration"
            )
            connect_google(credentials_path, token_path)
            print(json.dumps({"connected": True, "token_path": str(token_path)}, indent=2))
            return 0
        if args.command == "status":
            print(json.dumps({**state.status(), "connected": token_path.is_file()}, indent=2))
            return 0
        if args.command == "disconnect":
            result = {
                "applied": args.apply,
                "token_removed": token_path.is_file(),
                "state_removed": state_path.is_file(),
            }
            if args.apply:
                token_path.unlink(missing_ok=True)
                state_path.unlink(missing_ok=True)
                state_path.with_suffix(state_path.suffix + "-wal").unlink(missing_ok=True)
                state_path.with_suffix(state_path.suffix + "-shm").unlink(missing_ok=True)
            print(json.dumps(result, indent=2))
            return 0
        gateway = google_gateway(token_path)
        result = scan(
            gateway=gateway,
            state=state,
            workspace=workspace,
            label=args.label,
            query=args.query,
            backfill=args.command == "backfill",
            apply=args.apply,
        )
        print(json.dumps(result, indent=2))
        return 0
    except (OSError, ValueError, sqlite3.Error) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except Exception as exc:
        if exc.__class__.__module__.startswith(("google.", "googleapiclient.", "httplib2")):
            print(f"Gmail API error: {exc}", file=sys.stderr)
            return 2
        raise


if __name__ == "__main__":
    raise SystemExit(main())
