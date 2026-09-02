"""Privacy-preserving Gmail ingestion for automatic application confirmations."""

from __future__ import annotations

import argparse
import base64
import fcntl
import hashlib
import json
import os
import re
import sqlite3
import sys
from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
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
    current_application_status,
    iter_records,
)
from .jobs import DEFAULT_CONFIG

GMAIL_READONLY_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
CLASSIFIER_VERSION = "application-lifecycle-rules-v4"
AUTOMATION_POLICY = "high-confidence-application-lifecycle-v2"
AUTO_APPLY_THRESHOLD = 0.92
DEFAULT_LABEL = ""
GOOGLE_PROJECT_URL = "https://console.cloud.google.com/projectcreate"
GMAIL_API_URL = "https://console.cloud.google.com/apis/library/gmail.googleapis.com"
GOOGLE_AUTH_URL = "https://console.cloud.google.com/auth/overview"
GOOGLE_AUDIENCE_URL = "https://console.cloud.google.com/auth/audience"
GOOGLE_DATA_ACCESS_URL = "https://console.cloud.google.com/auth/scopes"
GOOGLE_CLIENTS_URL = "https://console.cloud.google.com/auth/clients"
CONFIRMATION_QUERY = (
    '{"thank you for applying" "thanks for applying" "we received your application" '
    '"application has been received" "application was submitted" '
    '"application has been submitted" "application submitted" '
    '"your application was sent"}'
)
REJECTION_QUERY_TERMS = (
    '"unable to move forward" "not moving forward" "not be moving forward" '
    '"other candidates" "another candidate" "position has been filled" "not selected"'
)
FOLLOW_UP_QUERY_TERMS = (
    '"schedule an interview" "invite you to interview" "interview availability" '
    '"phone screen" "recruiter screen" "technical assessment" "take-home assessment" '
    '"coding challenge" "pleased to offer you" "offer letter" "offer of employment"'
)
APPLICATION_ACTIVITY_QUERY = (
    f"{CONFIRMATION_QUERY[:-1]} {REJECTION_QUERY_TERMS} {FOLLOW_UP_QUERY_TERMS}}}"
)
DEFAULT_SCAN_QUERY = f"{APPLICATION_ACTIVITY_QUERY} newer_than:30d"
DEFAULT_BACKFILL_QUERY = f"{APPLICATION_ACTIVITY_QUERY} newer_than:5y"
MAX_BODY_CHARS = 100_000
TOKEN = re.compile(r"[a-z0-9]+")
REQUISITION = re.compile(
    r"\b(?:job|requisition|req)(?:\s+(?:id|number|#))?\s*[:#-]?\s*"
    r"([A-Z0-9-]*\d[A-Z0-9-]*)\b",
    re.IGNORECASE,
)
CONFIRMATION_PHRASES = (
    re.compile(r"\bthank you for applying\b", re.IGNORECASE),
    re.compile(r"\bthanks for applying\b", re.IGNORECASE),
    re.compile(r"\bwe (?:have )?received your application\b", re.IGNORECASE),
    re.compile(r"\byour application (?:has been|was) (?:received|submitted)\b", re.IGNORECASE),
    re.compile(r"\byour application (?:has been|was) sent\b", re.IGNORECASE),
    re.compile(r"\bapplication submitted\b", re.IGNORECASE),
    re.compile(r"\bapplication (?:has been|was) successfully submitted\b", re.IGNORECASE),
)
EXCLUDED_PHRASES = (
    "job alert",
    "jobs you may be interested in",
    "recommended jobs",
    "complete your application",
    "application incomplete",
)
REJECTION_PATTERNS = (
    re.compile(r"\b(?:decided|chosen|elected) not to move forward\b", re.IGNORECASE),
    re.compile(r"\b(?:unable|cannot|can't) to move forward\b", re.IGNORECASE),
    re.compile(r"\b(?:will|would) not be moving forward\b", re.IGNORECASE),
    re.compile(r"\b(?:you|your application) (?:are|is|were|was) not selected\b", re.IGNORECASE),
    re.compile(r"\b(?:position|role|opening) (?:has been|was) filled\b", re.IGNORECASE),
    re.compile(
        r"\bmove forward with (?:another|other|different|more qualified) candidates?\b",
        re.IGNORECASE,
    ),
    re.compile(r"\bnot moving forward (?:with|in)\b", re.IGNORECASE),
)
OFFER_PATTERNS = (
    re.compile(r"\b(?:pleased|delighted|excited) to offer you\b", re.IGNORECASE),
    re.compile(r"\bextend (?:you )?an? (?:formal )?offer\b", re.IGNORECASE),
    re.compile(r"\bformal offer letter\b", re.IGNORECASE),
    re.compile(r"\boffer of employment\b", re.IGNORECASE),
)
ASSESSMENT_PATTERNS = (
    re.compile(r"\binvit(?:e|ed|ing) you to (?:complete|take) (?:an? |the )?.*assessment\b", re.IGNORECASE),
    re.compile(r"\b(?:complete|take) (?:our |the |an? )?(?:technical |coding )?assessment\b", re.IGNORECASE),
    re.compile(r"\b(?:coding|technical) challenge\b", re.IGNORECASE),
    re.compile(r"\btake-home (?:assessment|assignment|exercise)\b", re.IGNORECASE),
)
INTERVIEW_PATTERNS = (
    re.compile(r"\binvit(?:e|ed|ing) you to (?:an? )?interview\b", re.IGNORECASE),
    re.compile(r"\b(?:schedule|scheduling|arrange) (?:an? |your |the )?interview\b", re.IGNORECASE),
    re.compile(r"\binterview availability\b", re.IGNORECASE),
    re.compile(r"\bwould like to interview you\b", re.IGNORECASE),
    re.compile(r"\b(?:phone|video|recruiter) screen\b", re.IGNORECASE),
)
RECRUITER_CONTACT_PATTERNS = (
    re.compile(
        r"\bwould like to (?:connect|speak|talk|discuss) (?:with you )?"
        r"(?:about|regarding) (?:your application|the|this|our)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\bschedule (?:a|an) (?:brief )?call to discuss (?:the|this|your)\b", re.IGNORECASE),
)
CONDITIONAL_REJECTION = re.compile(
    r"\bif (?:you|your application) (?:are|is|were) not selected\b",
    re.IGNORECASE,
)
SUBJECT_IDENTITY_PATTERNS = (
    re.compile(
        r"(?:thank you|thanks) for applying (?:to|for) "
        r"(?P<role>.+?) (?:at|with) (?P<company>.+)$",
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
    re.compile(
        r"(?:thank you|thanks) for applying (?:to|with) (?P<company>[^\n.!|]+)",
        re.IGNORECASE,
    ),
    re.compile(
        r"your application (?:has been|was) sent to (?P<company>[^\n.!|]+)",
        re.IGNORECASE,
    ),
    re.compile(r"company\s*[:|-]\s*(?P<company>[^\n.!|]+)", re.IGNORECASE),
    re.compile(r"application (?:to|with) (?P<company>[^\n.!|]+)", re.IGNORECASE),
    re.compile(r"(?:your|the) interest in (?P<company>[^\n.!|]+)", re.IGNORECASE),
    re.compile(r"(?:position|role) at (?P<company>[^\n.!|]+)", re.IGNORECASE),
    re.compile(r"(?:an? )?(?:update|message) from (?P<company>[^\n.!|]+)", re.IGNORECASE),
)
ROLE_PATTERNS = (
    re.compile(r"(?:job title|position|role)\s*[:|-]\s*(?P<role>[^\n|]{3,100})", re.IGNORECASE),
    re.compile(
        r"application (?:for|to) (?:the )?(?P<role>[^\n.!]{3,100}?) (?:position|role)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"applying for (?:the |our )?(?P<role>[^\n.!]{3,100}?) (?:position|role)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"apply for (?:the |our )?(?P<role>[^\n.!]{3,100}?) (?:position|role)\b",
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


@dataclass(frozen=True)
class GmailLifecycleEvent:
    event_type: str
    company: str | None
    role: str | None
    requisition_id: str | None
    received_at: datetime
    confidence: float


@dataclass(frozen=True)
class GmailSetupStep:
    title: str
    instruction: str
    link_label: str
    link: str


GMAIL_SETUP_STEPS = (
    GmailSetupStep(
        title="Create or select a Google Cloud project",
        instruction="Use a dedicated project or select one you already control.",
        link_label="Open Google Cloud project setup",
        link=GOOGLE_PROJECT_URL,
    ),
    GmailSetupStep(
        title="Enable the Gmail API",
        instruction="Confirm the intended project is selected, then enable the Gmail API.",
        link_label="Enable the Gmail API",
        link=GMAIL_API_URL,
    ),
    GmailSetupStep(
        title="Configure app information and audience",
        instruction=(
            "Enter the app and contact information. Choose Internal only for an account in the "
            "same Google Workspace organization; otherwise choose External. Then select Create."
        ),
        link_label="Configure Google Auth",
        link=GOOGLE_AUTH_URL,
    ),
    GmailSetupStep(
        title="Authorize the test account when using External",
        instruction=(
            "External only: add the Gmail account to Test users. Internal users can continue "
            "without adding a test user."
        ),
        link_label="Configure the OAuth audience",
        link=GOOGLE_AUDIENCE_URL,
    ),
    GmailSetupStep(
        title="Declare Gmail read-only access",
        instruction=f"Add the scope {GMAIL_READONLY_SCOPE} under Data Access.",
        link_label="Configure Gmail data access",
        link=GOOGLE_DATA_ACCESS_URL,
    ),
    GmailSetupStep(
        title="Create and download a Desktop OAuth client",
        instruction="Choose Desktop app, create the client, and download its JSON file.",
        link_label="Create a Desktop OAuth client",
        link=GOOGLE_CLIENTS_URL,
    ),
)


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

    @contextmanager
    def locked(self) -> Iterator[None]:
        """Prevent overlapping scans from applying the same mailbox changes."""
        lock_path = self.path.with_suffix(f"{self.path.suffix}.lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with lock_path.open("a+", encoding="utf-8") as stream:
            os.chmod(lock_path, 0o600)
            try:
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise ValueError("another Gmail scan is already running") from exc
            try:
                yield
            finally:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)

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
                    sender_domain_hash TEXT,
                    classifier_version TEXT NOT NULL,
                    processed_at TEXT NOT NULL,
                    PRIMARY KEY(account_id, message_id)
                );
                """
            )
            columns = {
                str(row[1])
                for row in conn.execute("PRAGMA table_info(processed_messages)").fetchall()
            }
            if "sender_domain_hash" not in columns:
                conn.execute("ALTER TABLE processed_messages ADD COLUMN sender_domain_hash TEXT")
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

    def processed(
        self, account_id: str, message_id: str, *, replay_ambiguous: bool = False
    ) -> bool:
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
        if replay_ambiguous and str(row[0]) == "ambiguous":
            return False
        return (
            str(row[0])
            in {
                "created",
                "linked",
                "rejected",
                "recruiter_contact",
                "interview",
                "assessment",
                "offer",
                "duplicate",
            }
            or str(row[1]) == CLASSIFIER_VERSION
        )

    def application_for_thread(self, account_id: str, thread_id: str) -> str | None:
        """Resolve a prior content-free thread association, when unique."""
        if not self.path.is_file() or not thread_id:
            return None
        with sqlite3.connect(self.path) as conn:
            rows = conn.execute(
                """SELECT DISTINCT application_id FROM processed_messages
                   WHERE account_id=? AND thread_id=? AND application_id IS NOT NULL""",
                (account_id, thread_id),
            ).fetchall()
        values = [str(row[0]) for row in rows if row[0]]
        return values[0] if len(values) == 1 else None

    def application_for_sender(self, account_id: str, sender: str) -> str | None:
        """Resolve one application previously associated with an opaque sender domain."""
        domain_hash = _sender_domain_hash(sender)
        if not self.path.is_file() or domain_hash is None:
            return None
        with sqlite3.connect(self.path) as conn:
            rows = conn.execute(
                """SELECT DISTINCT application_id FROM processed_messages
                   WHERE account_id=? AND sender_domain_hash=? AND application_id IS NOT NULL""",
                (account_id, domain_hash),
            ).fetchall()
        values = [str(row[0]) for row in rows if row[0]]
        return values[0] if len(values) == 1 else None

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
                       application_id, event_id, sender_domain_hash, classifier_version,
                       processed_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(account_id, message_id) DO UPDATE SET
                     thread_id=excluded.thread_id,
                     received_at=excluded.received_at,
                     disposition=excluded.disposition,
                     application_id=excluded.application_id,
                     event_id=excluded.event_id,
                     sender_domain_hash=excluded.sender_domain_hash,
                     classifier_version=excluded.classifier_version,
                     processed_at=excluded.processed_at
                   WHERE processed_messages.disposition NOT IN
                     ('created','linked','rejected','recruiter_contact','interview',
                      'assessment','offer','duplicate')""",
                (
                    account_id,
                    message.id,
                    message.thread_id,
                    message.received_at.isoformat(),
                    disposition,
                    application_id,
                    event_id,
                    _sender_domain_hash(message.sender),
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


def _validate_client_configuration(path: Path) -> Path:
    if not path.is_file():
        raise ValueError(f"Google OAuth client file not found: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Google OAuth client file is not valid JSON: {path}") from exc
    installed = payload.get("installed") if isinstance(payload, dict) else None
    if not isinstance(installed, dict):
        if isinstance(payload, dict) and "web" in payload:
            raise ValueError("Google OAuth client must use the Desktop app application type")
        raise ValueError("Google OAuth client JSON is missing its installed-app configuration")
    required = ("client_id", "client_secret", "auth_uri", "token_uri")
    missing = [key for key in required if not str(installed.get(key, "")).strip()]
    if missing:
        raise ValueError(
            "Google OAuth Desktop client JSON is missing: " + ", ".join(sorted(missing))
        )
    return path


def _connect_step_payload(number: int) -> dict[str, object]:
    if number < 1 or number > len(GMAIL_SETUP_STEPS):
        raise ValueError(f"Gmail setup step must be between 1 and {len(GMAIL_SETUP_STEPS)}")
    step = GMAIL_SETUP_STEPS[number - 1]
    if number < len(GMAIL_SETUP_STEPS):
        next_action: dict[str, str] = {
            "label": "Continue to the next setup step",
            "command": f"resume-builder gmail connect --step {number + 1}",
        }
    else:
        next_action = {
            "label": "Connect Gmail with the downloaded Desktop OAuth JSON",
            "command": (
                "resume-builder gmail connect --credentials /absolute/path/to/client.json"
            ),
        }
    return {
        "valid": True,
        "action": "gmail-oauth-setup",
        "status": "needs-user-action",
        "local_only": True,
        "email_content_retained": False,
        "step": {
            "number": number,
            "total": len(GMAIL_SETUP_STEPS),
            "title": step.title,
            "instruction": step.instruction,
            "link": {"label": step.link_label, "url": step.link},
        },
        "next": next_action,
    }


def _terminal_link(label: str, url: str) -> str:
    return f"\033]8;;{url}\033\\{label}\033]8;;\033\\"


def _print_connect_step(payload: dict[str, object]) -> None:
    step = payload["step"]
    next_action = payload["next"]
    assert isinstance(step, dict) and isinstance(next_action, dict)
    link = step["link"]
    assert isinstance(link, dict)
    print(f"Gmail setup · Step {step['number']} of {step['total']}")
    print(str(step["title"]))
    print(str(step["instruction"]))
    print("")
    print(_terminal_link(str(link["label"]), str(link["url"])))
    print(str(link["url"]))
    print("")
    print(f"Next: {next_action['command']}")


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


def _current_message_text(value: str) -> str:
    """Remove common quoted-reply sections before classification."""
    kept: list[str] = []
    for line in value.splitlines():
        stripped = line.strip()
        if re.match(r"^on .+ wrote:$", stripped, re.IGNORECASE):
            break
        if stripped.casefold() in {
            "-----original message-----",
            "---------- forwarded message ---------",
        }:
            break
        if stripped.startswith(">"):
            continue
        kept.append(line)
    return "\n".join(kept).strip()


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
        body=_current_message_text(body)[:MAX_BODY_CHARS],
        authentication_results=headers.get("authentication-results", ""),
    )


def _clean_identity(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip(" \t\r\n-:|,.;*")


def _valid_identity_pair(company: str, role: str) -> bool:
    company_identity = _identity(company)
    role_identity = _identity(role)
    invalid_companies = {
        "remote",
        "the united states",
        "united states",
        "us",
        "usa",
    }
    invalid_roles = {"a", "an", "job", "position", "role", "the"}
    invalid_role_fragments = {
        "your skill set",
        "future opportunities",
        "future openings",
        "another position",
        "another role",
    }
    if company_identity in invalid_companies or role_identity in invalid_roles:
        return False
    if len(TOKEN.findall(company)) < 1 or len(TOKEN.findall(role)) < 2:
        return False
    if any(fragment in role_identity for fragment in invalid_role_fragments):
        return False
    return not role_identity.startswith(f"{company_identity} for ")


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


def _authenticated(message: GmailMessage) -> bool:
    return any(
        token in message.authentication_results.casefold()
        for token in ("dmarc=pass", "dkim=pass", "spf=pass")
    )


def classify_lifecycle_event(message: GmailMessage) -> tuple[GmailLifecycleEvent | None, str]:
    """Classify current-message content without retaining it."""
    text = f"{message.subject}\n{message.body}"
    folded = text.casefold()
    rejection_text = CONDITIONAL_REJECTION.sub("", folded)
    if any(phrase in folded for phrase in EXCLUDED_PHRASES):
        return None, "excluded-nonconfirmation"
    company, role = _extract_identity(message.subject, message.body)
    requisition_match = REQUISITION.search(text)
    if any(pattern.search(rejection_text) for pattern in REJECTION_PATTERNS):
        confidence = 0.92 + (0.03 if _authenticated(message) else 0)
        if company and role and _valid_identity_pair(company, role):
            confidence += 0.02
        return (
            GmailLifecycleEvent(
                event_type="rejected",
                company=company,
                role=role,
                requisition_id=requisition_match.group(1) if requisition_match else None,
                received_at=message.received_at,
                confidence=round(min(confidence, 0.99), 2),
            ),
            "rejected",
        )
    follow_up_rules = (
        ("offer_received", OFFER_PATTERNS, 0.96),
        ("assessment_invited", ASSESSMENT_PATTERNS, 0.94),
        ("interview_invited", INTERVIEW_PATTERNS, 0.94),
        ("recruiter_contact", RECRUITER_CONTACT_PATTERNS, 0.92),
    )
    for event_type, patterns, base_confidence in follow_up_rules:
        if any(pattern.search(text) for pattern in patterns):
            confidence = base_confidence + (0.03 if _authenticated(message) else 0)
            return (
                GmailLifecycleEvent(
                    event_type=event_type,
                    company=company,
                    role=role,
                    requisition_id=requisition_match.group(1) if requisition_match else None,
                    received_at=message.received_at,
                    confidence=round(min(confidence, 0.99), 2),
                ),
                event_type,
            )
    if not any(pattern.search(text) for pattern in CONFIRMATION_PHRASES):
        return None, "missing-confirmation-phrase"
    if not company and not role:
        return None, "missing-company-and-role"
    if not company:
        return None, "missing-company"
    if not role:
        return None, "missing-role"
    if len(company) > 120 or len(role) > 160:
        return None, "invalid-identity-length"
    if not _valid_identity_pair(company, role):
        return None, "invalid-identity-value"
    confidence = 0.92 + (0.03 if _authenticated(message) else 0) + (
        0.02 if requisition_match else 0
    )
    return (
        GmailLifecycleEvent(
            event_type="application_confirmed",
            company=company,
            role=role,
            requisition_id=requisition_match.group(1) if requisition_match else None,
            received_at=message.received_at,
            confidence=round(min(confidence, 0.99), 2),
        ),
        "confirmed",
    )


def _classify_confirmation(
    message: GmailMessage,
) -> tuple[ApplicationConfirmation | None, str]:
    event, reason = classify_lifecycle_event(message)
    if event is None or event.event_type != "application_confirmed":
        return None, "rejection-signal" if event is not None else reason
    assert event.company is not None and event.role is not None
    return (
        ApplicationConfirmation(
            company=event.company,
            role=event.role,
            requisition_id=event.requisition_id,
            received_at=event.received_at,
            confidence=event.confidence,
        ),
        reason,
    )


def classify_confirmation(message: GmailMessage) -> ApplicationConfirmation | None:
    return _classify_confirmation(message)[0]


def _identity(value: str) -> str:
    return " ".join(TOKEN.findall(value.casefold()))


def _source_reference(account_id: str, message_id: str) -> str:
    return hashlib.sha256(f"{account_id}\x1f{message_id}".encode()).hexdigest()[:24]


def _sender_domain_hash(sender: str) -> str | None:
    domain = sender.rpartition("@")[2].strip().casefold()
    if not domain:
        return None
    shared_recruiting_domains = {
        "ashbyhq.com",
        "greenhouse.io",
        "icims.com",
        "lever.co",
        "myworkday.com",
        "smartrecruiters.com",
        "workday.com",
    }
    if any(domain == value or domain.endswith(f".{value}") for value in shared_recruiting_domains):
        return None
    return hashlib.sha256(domain.encode()).hexdigest()[:24]


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
    confirmation: ApplicationConfirmation,
    applications_root: Path,
    records: Iterable[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    matches = [
        record
        for record in (
            records if records is not None else (item for _, item in iter_records(applications_root))
        )
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


def _resolve_existing_application(
    event: GmailLifecycleEvent,
    records: list[dict[str, Any]],
    *,
    thread_application_id: str | None,
    sender_application_id: str | None,
) -> tuple[dict[str, Any] | None, float, str]:
    """Resolve a lifecycle event only when it identifies one existing application."""
    if event.requisition_id:
        matches = [
            record
            for record in records
            if _identity(str(record["application"].get("requisition_id", "")))
            == _identity(event.requisition_id)
        ]
        if len(matches) == 1:
            return matches[0], 1.0, "requisition"
    if event.company and event.role and _valid_identity_pair(event.company, event.role):
        matches = [
            record
            for record in records
            if _identity(record["application"]["company"]) == _identity(event.company)
            and _identity(record["application"]["role"]) == _identity(event.role)
        ]
        if len(matches) == 1:
            return matches[0], 0.99, "company-role"
    if thread_application_id:
        matches = [
            record
            for record in records
            if record["application"]["id"] == thread_application_id
        ]
        if len(matches) == 1:
            return matches[0], 0.97, "thread"
    if sender_application_id:
        matches = [
            record
            for record in records
            if record["application"]["id"] == sender_application_id
        ]
        if len(matches) == 1:
            return matches[0], 0.96, "sender-domain"
    if event.company:
        matches = [
            record
            for record in records
            if _identity(record["application"]["company"]) == _identity(event.company)
            and current_application_status(record) not in {"hired", "withdrawn", "rejected"}
        ]
        if len(matches) == 1:
            return matches[0], 0.94, "unique-company"
    return None, 0.0, "unresolved"


def _follow_up_transition(event_type: str, current_status: str) -> tuple[str, str | None] | None:
    transitions = {
        "rejected": ("rejected", None),
        "recruiter_contact": ("recruiter_contact", "Recruiter outreach"),
        "interview_invited": ("screen_scheduled", "Interview scheduling"),
        "assessment_invited": ("assessment", "Assessment"),
        "offer_received": ("offer", "Offer"),
    }
    target = transitions.get(event_type)
    if target is None or target[0] == current_status:
        return None
    if current_status in {"hired", "withdrawn", "rejected"}:
        return None
    if event_type == "recruiter_contact" and current_status not in {"applied", "no_response"}:
        return None
    if event_type == "interview_invited" and current_status in {
        "interview",
        "assessment",
        "final_interview",
        "offer",
    }:
        return None
    if event_type == "assessment_invited" and current_status in {
        "final_interview",
        "offer",
    }:
        return None
    return target


def process_messages(
    *,
    gateway: GmailGateway,
    state: GmailRuntimeState,
    workspace: Path,
    message_ids: Iterable[str],
    apply: bool,
    replay_ambiguous: bool = False,
) -> dict[str, object]:
    account_id = gateway.account_id()
    applications_root = workspace / DEFAULT_APPLICATIONS_ROOT
    inventory = _inventory(workspace)
    records = [record for _, record in iter_records(applications_root)]
    thread_associations: dict[str, str | None] = {}
    sender_associations: dict[str, str | None] = {}

    def associate(message: GmailMessage, application_id: str) -> None:
        if message.thread_id:
            prior = thread_associations.get(message.thread_id, application_id)
            thread_associations[message.thread_id] = (
                application_id if prior == application_id else None
            )
        domain_hash = _sender_domain_hash(message.sender)
        if domain_hash:
            prior = sender_associations.get(domain_hash, application_id)
            sender_associations[domain_hash] = application_id if prior == application_id else None

    summary: dict[str, Any] = {
        "examined": 0,
        "created": 0,
        "linked": 0,
        "rejected": 0,
        "recruiter_contacts": 0,
        "interviews": 0,
        "assessments": 0,
        "offers": 0,
        "ignored": 0,
        "ambiguous": 0,
        "ambiguous_reasons": {},
        "duplicates": 0,
        "ignored_reasons": {},
        "changes": [],
    }
    messages = [
        parse_message(gateway.get_message(message_id))
        for message_id in dict.fromkeys(message_ids)
        if not state.processed(account_id, message_id, replay_ambiguous=replay_ambiguous)
    ]
    for message in sorted(messages, key=lambda item: (item.received_at, item.id)):
        summary["examined"] += 1
        lifecycle_event, reason = classify_lifecycle_event(message)
        if lifecycle_event is None:
            summary["ignored"] += 1
            summary["ignored_reasons"][reason] = summary["ignored_reasons"].get(reason, 0) + 1
            if apply:
                state.record(
                    account_id=account_id,
                    message=message,
                    disposition="ignored",
                    application_id=None,
                    event_id=None,
                )
            continue
        if lifecycle_event.confidence < AUTO_APPLY_THRESHOLD:
            summary["ambiguous"] += 1
            summary["ambiguous_reasons"]["low-confidence"] = (
                summary["ambiguous_reasons"].get("low-confidence", 0) + 1
            )
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
        if lifecycle_event.event_type != "application_confirmed":
            thread_application_id = (
                thread_associations[message.thread_id]
                if message.thread_id in thread_associations
                else state.application_for_thread(account_id, message.thread_id)
            )
            domain_hash = _sender_domain_hash(message.sender)
            sender_application_id = (
                sender_associations[domain_hash]
                if domain_hash in sender_associations
                else state.application_for_sender(account_id, message.sender)
            )
            existing, match_confidence, match_method = _resolve_existing_application(
                lifecycle_event,
                records,
                thread_application_id=thread_application_id,
                sender_application_id=sender_application_id,
            )
            if existing is None or match_confidence < AUTO_APPLY_THRESHOLD:
                summary["ambiguous"] += 1
                ambiguity = f"{lifecycle_event.event_type}:unresolved-application"
                summary["ambiguous_reasons"][ambiguity] = (
                    summary["ambiguous_reasons"].get(ambiguity, 0) + 1
                )
                if apply:
                    state.record(
                        account_id=account_id,
                        message=message,
                        disposition="ambiguous",
                        application_id=None,
                        event_id=None,
                    )
                continue
            application_id = str(existing["application"]["id"])
            current_status = current_application_status(existing)
            transition = _follow_up_transition(lifecycle_event.event_type, current_status)
            if transition is None:
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
            status, stage = transition
            stored_event_type = (
                "rejection_received"
                if lifecycle_event.event_type == "rejected"
                else lifecycle_event.event_type
            )
            event_id: str | None = None
            if apply or (applications_root / f"{application_id}.json").is_file():
                result = append_event(
                    applications_root,
                    application_id,
                    status,
                    lifecycle_event.received_at.date().isoformat(),
                    stage=stage,
                    feedback=None,
                    note=None,
                    supersedes=None,
                    apply=apply,
                    event_type=stored_event_type,
                    occurred_at=lifecycle_event.received_at.isoformat(),
                    source_type="gmail-automation",
                    source_reference=reference,
                    confidence=lifecycle_event.confidence,
                    match_confidence=match_confidence,
                    classifier_version=CLASSIFIER_VERSION,
                    automation_policy=AUTOMATION_POLICY,
                )
                event_id = str(result["event"]["id"])
                if apply:
                    existing["events"].append(result["event"])
            action_by_event = {
                "rejected": "rejected",
                "recruiter_contact": "recruiter_contact",
                "interview_invited": "interview",
                "assessment_invited": "assessment",
                "offer_received": "offer",
            }
            counter_by_action = {
                "rejected": "rejected",
                "recruiter_contact": "recruiter_contacts",
                "interview": "interviews",
                "assessment": "assessments",
                "offer": "offers",
            }
            action = action_by_event[lifecycle_event.event_type]
            summary[counter_by_action[action]] += 1
            summary["changes"].append(
                {
                    "action": action,
                    "application_id": application_id,
                    "company": existing["application"]["company"],
                    "role": existing["application"]["role"],
                    "effective_on": lifecycle_event.received_at.date().isoformat(),
                    "status": status,
                    "stage": stage,
                    "confidence": lifecycle_event.confidence,
                    "match_confidence": match_confidence,
                    "match_method": match_method,
                }
            )
            associate(message, application_id)
            if apply:
                state.record(
                    account_id=account_id,
                    message=message,
                    disposition=action,
                    application_id=application_id,
                    event_id=event_id,
                )
            continue

        assert lifecycle_event.company is not None and lifecycle_event.role is not None
        confirmation = ApplicationConfirmation(
            company=lifecycle_event.company,
            role=lifecycle_event.role,
            requisition_id=lifecycle_event.requisition_id,
            received_at=lifecycle_event.received_at,
            confidence=lifecycle_event.confidence,
        )
        existing = _match_application(confirmation, applications_root, records)
        if existing is not None:
            application_id = str(existing["application"]["id"])
            if current_application_status(existing) in {"hired", "withdrawn", "rejected"} or (
                _already_confirmed(existing, confirmation.received_at.date().isoformat())
            ):
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
                requisition_id=confirmation.requisition_id,
            )
            try:
                result = _write_or_preview(applications_root, record, apply=apply)
            except ValueError as exc:
                if "already exists with different content" not in str(exc):
                    raise
                summary["ambiguous"] += 1
                summary["ambiguous_reasons"]["confirmation:record-conflict"] = (
                    summary["ambiguous_reasons"].get("confirmation:record-conflict", 0) + 1
                )
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
            records.append(record)
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
        associate(message, application_id)
        if apply:
            state.record(
                account_id=account_id,
                message=message,
                disposition=action,
                application_id=application_id,
                event_id=event_id,
            )
    return summary


def _scan_unlocked(
    *,
    gateway: GmailGateway,
    state: GmailRuntimeState,
    workspace: Path,
    label: str,
    query: str,
    backfill: bool,
    apply: bool,
    replay_ambiguous: bool = False,
) -> dict[str, object]:
    account_id = gateway.account_id()
    label_id = gateway.label_id(label) if label else None
    use_history = bool(label) and not backfill
    prior_history = state.history_id(account_id) if use_history else None
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
        replay_ambiguous=replay_ambiguous,
    )
    if apply and use_history:
        state.set_history_id(account_id, next_history)
    return {
        "valid": True,
        "applied": apply,
        "mode": "backfill" if backfill else ("labeled-incremental" if label else "query"),
        "history_recovered": recovered,
        "raw_messages_retained": 0,
        **result,
    }


def scan(
    *,
    gateway: GmailGateway,
    state: GmailRuntimeState,
    workspace: Path,
    label: str,
    query: str,
    backfill: bool,
    apply: bool,
    replay_ambiguous: bool = False,
) -> dict[str, object]:
    with state.locked():
        return _scan_unlocked(
            gateway=gateway,
            state=state,
            workspace=workspace,
            label=label,
            query=query,
            backfill=backfill,
            apply=apply,
            replay_ambiguous=replay_ambiguous,
        )


def parser() -> argparse.ArgumentParser:
    command_parser = argparse.ArgumentParser(prog="resume-builder gmail")
    command_parser.add_argument("--state", type=Path, default=default_state_path())
    command_parser.add_argument("--token", type=Path)
    commands = command_parser.add_subparsers(dest="command", required=True)

    connect = commands.add_parser("connect", help="Authorize one Gmail account read-only")
    connect.add_argument(
        "--credentials",
        type=Path,
        help="Desktop OAuth client JSON; omit to show the current setup step",
    )
    connect.add_argument("--step", type=int, default=1, help="Guided setup step to display")

    scan_parser = commands.add_parser("scan", help="Find recent application lifecycle messages")
    scan_parser.add_argument("--label", default=DEFAULT_LABEL)
    scan_parser.add_argument("--query", default=DEFAULT_SCAN_QUERY)
    scan_parser.add_argument("--apply", action="store_true")
    scan_parser.add_argument(
        "--replay-ambiguous",
        action="store_true",
        help="Reconsider previously unresolved messages against current applications",
    )

    backfill = commands.add_parser("backfill", help="Find historical application lifecycle messages")
    backfill.add_argument("--label", default="")
    backfill.add_argument("--query", default=DEFAULT_BACKFILL_QUERY)
    backfill.add_argument("--apply", action="store_true")
    backfill.add_argument(
        "--replay-ambiguous",
        action="store_true",
        help="Reconsider previously unresolved messages against current applications",
    )

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
            if args.credentials is None:
                payload = _connect_step_payload(args.step)
                if sys.stdout.isatty():
                    _print_connect_step(payload)
                else:
                    print(json.dumps(payload, indent=2))
                return 0
            credentials_path = _require_external(
                args.credentials, workspace, "Google OAuth client configuration"
            )
            _validate_client_configuration(credentials_path)
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
            replay_ambiguous=args.replay_ambiguous,
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
