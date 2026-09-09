"""Content-free runtime state for privacy-preserving Gmail ingestion."""

from __future__ import annotations

import fcntl
import hashlib
import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

CLASSIFIER_VERSION = "application-lifecycle-rules-v8"


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


def sender_domain_hash(sender: str) -> str | None:
    """Return an opaque company-domain identity, excluding shared recruiters."""
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


class GmailRuntimeState:
    """External, content-free state for incremental and idempotent Gmail processing."""

    def __init__(self, path: Path):
        self.path = path.expanduser().resolve()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

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
        with self._connect() as connection:
            connection.executescript(
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
                for row in connection.execute("PRAGMA table_info(processed_messages)").fetchall()
            }
            if "sender_domain_hash" not in columns:
                connection.execute(
                    "ALTER TABLE processed_messages ADD COLUMN sender_domain_hash TEXT"
                )
        os.chmod(self.path, 0o600)

    def history_id(self, account_id: str) -> str | None:
        if not self.path.is_file():
            return None
        with self._connect() as connection:
            row = connection.execute(
                "SELECT history_id FROM mailbox_state WHERE account_id=?", (account_id,)
            ).fetchone()
        return str(row[0]) if row and row[0] else None

    def set_history_id(self, account_id: str, history_id: str) -> None:
        self.initialize()
        now = datetime.now(UTC).isoformat()
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO mailbox_state(account_id, history_id, updated_at)
                   VALUES (?, ?, ?)
                   ON CONFLICT(account_id) DO UPDATE SET
                     history_id=excluded.history_id, updated_at=excluded.updated_at""",
                (account_id, history_id, now),
            )

    def processed(
        self,
        account_id: str,
        message_id: str,
        *,
        replay_ambiguous: bool = False,
        classifier_version: str = CLASSIFIER_VERSION,
    ) -> bool:
        if not self.path.is_file():
            return False
        with self._connect() as connection:
            row = connection.execute(
                """SELECT disposition, classifier_version FROM processed_messages
                   WHERE account_id=? AND message_id=?""",
                (account_id, message_id),
            ).fetchone()
        if row is None:
            return False
        if str(row[0]) in {"provider_error", "budget_exhausted"}:
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
            or str(row[1]) == classifier_version
        )

    def application_for_thread(self, account_id: str, thread_id: str) -> str | None:
        """Resolve a prior content-free thread association, when unique."""
        if not self.path.is_file() or not thread_id:
            return None
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT DISTINCT application_id FROM processed_messages
                   WHERE account_id=? AND thread_id=? AND application_id IS NOT NULL""",
                (account_id, thread_id),
            ).fetchall()
        values = [str(row[0]) for row in rows if row[0]]
        return values[0] if len(values) == 1 else None

    def application_for_sender(self, account_id: str, sender: str) -> str | None:
        """Resolve one application previously associated with an opaque sender domain."""
        domain_hash = sender_domain_hash(sender)
        if not self.path.is_file() or domain_hash is None:
            return None
        with self._connect() as connection:
            rows = connection.execute(
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
        classifier_version: str = CLASSIFIER_VERSION,
    ) -> None:
        self.initialize()
        with self._connect() as connection:
            connection.execute(
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
                    sender_domain_hash(message.sender),
                    classifier_version,
                    datetime.now(UTC).isoformat(),
                ),
            )

    def status(self) -> dict[str, object]:
        if not self.path.is_file():
            return {"initialized": False, "path": str(self.path), "mailboxes": 0, "messages": 0}
        with self._connect() as connection:
            mailboxes = connection.execute("SELECT COUNT(*) FROM mailbox_state").fetchone()[0]
            messages = connection.execute("SELECT COUNT(*) FROM processed_messages").fetchone()[0]
            dispositions = {
                str(row[0]): int(row[1])
                for row in connection.execute(
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
