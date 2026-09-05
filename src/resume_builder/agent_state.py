"""External, non-authoritative state for conversational agent channels."""

from __future__ import annotations

import fcntl
import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .agent_contracts import ConversationTurn


@dataclass(frozen=True)
class StoredUpdate:
    """A durable Telegram request and its delivery progress."""

    update_id: int
    status: str
    user_id: int | None
    chat_id: int | None
    chat_type: str | None
    request_text: str | None
    response_text: str | None
    next_chunk: int


class AgentState:
    """Persist bounded chat history and channel delivery deduplication outside Git."""

    def __init__(self, path: Path):
        self.path = path.expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            try:
                descriptor = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except FileExistsError:
                pass
            else:
                os.close(descriptor)
        self._initialize()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA secure_delete = ON")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS agent_messages(
                    channel TEXT NOT NULL,
                    conversation_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
                    text TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(channel, conversation_id, sequence)
                );
                CREATE TABLE IF NOT EXISTS telegram_updates(
                    update_id INTEGER PRIMARY KEY,
                    status TEXT NOT NULL CHECK(status IN ('processing', 'ready', 'sent', 'failed')),
                    user_id INTEGER,
                    chat_id INTEGER,
                    chat_type TEXT,
                    request_text TEXT,
                    response_text TEXT,
                    next_chunk INTEGER NOT NULL DEFAULT 0,
                    error_class TEXT,
                    updated_at TEXT NOT NULL
                );
                """
            )
            columns = {
                str(row[1])
                for row in connection.execute("PRAGMA table_info(telegram_updates)").fetchall()
            }
            migrations = {
                "user_id": "ALTER TABLE telegram_updates ADD COLUMN user_id INTEGER",
                "chat_id": "ALTER TABLE telegram_updates ADD COLUMN chat_id INTEGER",
                "chat_type": "ALTER TABLE telegram_updates ADD COLUMN chat_type TEXT",
                "request_text": "ALTER TABLE telegram_updates ADD COLUMN request_text TEXT",
                "next_chunk": (
                    "ALTER TABLE telegram_updates ADD COLUMN next_chunk INTEGER NOT NULL DEFAULT 0"
                ),
            }
            for column, statement in migrations.items():
                if column not in columns:
                    connection.execute(statement)
            connection.execute(
                """
                UPDATE telegram_updates
                SET status = 'failed', response_text = NULL, error_class = 'LegacyUnrecoverable',
                    updated_at = ?
                WHERE status IN ('processing', 'ready')
                  AND (user_id IS NULL OR chat_id IS NULL OR request_text IS NULL)
                """,
                (datetime.now(UTC).isoformat(),),
            )
        os.chmod(self.path, 0o600)

    @contextmanager
    def telegram_service_lock(self) -> Iterator[None]:
        """Prevent Telegram polling and ID discovery from consuming updates concurrently."""
        lock_path = self.path.with_suffix(f"{self.path.suffix}.telegram.lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with lock_path.open("a+", encoding="utf-8") as stream:
            os.chmod(lock_path, 0o600)
            try:
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise ValueError("the Telegram service or ID discovery is already running") from exc
            try:
                yield
            finally:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)

    def telegram_service_is_running(self) -> bool:
        """Return whether a Telegram polling process holds the channel lock."""
        lock_path = self.path.with_suffix(f"{self.path.suffix}.telegram.lock")
        if not lock_path.is_file():
            return False
        with lock_path.open("r+", encoding="utf-8") as stream:
            try:
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return True
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        return False

    def load_history(
        self,
        channel: str,
        conversation_id: str,
        *,
        max_turns: int,
    ) -> tuple[ConversationTurn, ...]:
        """Load the latest bounded user/assistant exchanges in chronological order."""
        maximum_messages = max_turns * 2
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT role, text
                FROM agent_messages
                WHERE channel = ? AND conversation_id = ?
                ORDER BY sequence DESC
                LIMIT ?
                """,
                (channel, conversation_id, maximum_messages),
            ).fetchall()
        rows.reverse()
        return tuple(ConversationTurn(role=row[0], text=row[1]) for row in rows)

    def append_exchange(
        self,
        channel: str,
        conversation_id: str,
        user_text: str,
        assistant_text: str,
        *,
        max_turns: int,
    ) -> None:
        """Append one successful exchange and prune older messages."""
        now = datetime.now(UTC).isoformat()
        with self._connect() as connection:
            self._append_exchange(
                connection,
                channel,
                conversation_id,
                user_text,
                assistant_text,
                max_turns=max_turns,
                now=now,
            )

    @staticmethod
    def _append_exchange(
        connection: sqlite3.Connection,
        channel: str,
        conversation_id: str,
        user_text: str,
        assistant_text: str,
        *,
        max_turns: int,
        now: str,
    ) -> None:
        current = connection.execute(
            """
            SELECT COALESCE(MAX(sequence), 0)
            FROM agent_messages
            WHERE channel = ? AND conversation_id = ?
            """,
            (channel, conversation_id),
        ).fetchone()
        sequence = int(current[0])
        connection.executemany(
            """
            INSERT INTO agent_messages(
                channel, conversation_id, sequence, role, text, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                (channel, conversation_id, sequence + 1, "user", user_text, now),
                (channel, conversation_id, sequence + 2, "assistant", assistant_text, now),
            ),
        )
        connection.execute(
            """
            DELETE FROM agent_messages
            WHERE channel = ? AND conversation_id = ? AND sequence NOT IN (
                SELECT sequence
                FROM agent_messages
                WHERE channel = ? AND conversation_id = ?
                ORDER BY sequence DESC
                LIMIT ?
            )
            """,
            (channel, conversation_id, channel, conversation_id, max_turns * 2),
        )

    def clear_history(self, channel: str, conversation_id: str) -> int:
        """Remove retained history for one channel conversation."""
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM agent_messages WHERE channel = ? AND conversation_id = ?",
                (channel, conversation_id),
            )
        return cursor.rowcount

    def clear_telegram_conversation(self, chat_id: int) -> int:
        """Remove history and every retained Telegram payload for one chat."""
        with self._connect() as connection:
            messages = connection.execute(
                "DELETE FROM agent_messages WHERE channel = 'telegram' AND conversation_id = ?",
                (str(chat_id),),
            ).rowcount
            updates = connection.execute(
                "DELETE FROM telegram_updates WHERE chat_id = ?",
                (chat_id,),
            ).rowcount
        return messages + updates

    def get_update(self, update_id: int) -> StoredUpdate | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT update_id, status, user_id, chat_id, chat_type, request_text,
                       response_text, next_chunk
                FROM telegram_updates
                WHERE update_id = ?
                """,
                (update_id,),
            ).fetchone()
        return StoredUpdate(*row) if row is not None else None

    def pending_updates(self) -> tuple[StoredUpdate, ...]:
        """Return durable work that must be generated or delivered."""
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT update_id, status, user_id, chat_id, chat_type, request_text,
                       response_text, next_chunk
                FROM telegram_updates
                WHERE status IN ('processing', 'ready')
                ORDER BY update_id
                """
            ).fetchall()
        return tuple(StoredUpdate(*row) for row in rows)

    def start_update(
        self,
        update_id: int,
        *,
        user_id: int,
        chat_id: int,
        chat_type: str,
        request_text: str,
    ) -> bool:
        """Durably capture a new update before model processing begins."""
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO telegram_updates(
                    update_id, status, user_id, chat_id, chat_type, request_text, updated_at
                ) VALUES (?, 'processing', ?, ?, ?, ?, ?)
                """,
                (
                    update_id,
                    user_id,
                    chat_id,
                    chat_type,
                    request_text,
                    datetime.now(UTC).isoformat(),
                ),
            )
        return cursor.rowcount == 1

    def mark_update_ready(self, update_id: int, response_text: str) -> None:
        """Store a completed agent response before attempting channel delivery."""
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE telegram_updates
                SET status = 'ready', response_text = ?, next_chunk = 0,
                    error_class = NULL, updated_at = ?
                WHERE update_id = ?
                """,
                (response_text, datetime.now(UTC).isoformat(), update_id),
            )

    def mark_chunk_sent(self, update_id: int, next_chunk: int) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE telegram_updates
                SET next_chunk = ?, updated_at = ?
                WHERE update_id = ?
                """,
                (next_chunk, datetime.now(UTC).isoformat(), update_id),
            )

    def complete_update(self, update_id: int, *, max_turns: int) -> None:
        """Atomically retain a delivered exchange and erase its queued payload."""
        now = datetime.now(UTC).isoformat()
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT chat_id, request_text, response_text
                FROM telegram_updates
                WHERE update_id = ? AND status = 'ready'
                """,
                (update_id,),
            ).fetchone()
            if row is None or row[0] is None or row[1] is None or row[2] is None:
                raise ValueError("Telegram update is not ready for completion")
            self._append_exchange(
                connection,
                "telegram",
                str(row[0]),
                str(row[1]),
                str(row[2]),
                max_turns=max_turns,
                now=now,
            )
            connection.execute(
                """
                UPDATE telegram_updates
                SET status = 'sent', user_id = NULL, chat_id = NULL, chat_type = NULL,
                    request_text = NULL, response_text = NULL, error_class = NULL,
                    updated_at = ?
                WHERE update_id = ?
                """,
                (now, update_id),
            )

    def mark_update_failed(self, update_id: int, error_class: str) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE telegram_updates
                SET status = 'failed', user_id = NULL, chat_id = NULL, chat_type = NULL,
                    request_text = NULL, response_text = NULL, error_class = ?, updated_at = ?
                WHERE update_id = ?
                """,
                (error_class, datetime.now(UTC).isoformat(), update_id),
            )

    def prune_updates(self, *, retention_days: int = 30) -> int:
        """Delete old terminal deduplication rows after their replay window expires."""
        cutoff = (datetime.now(UTC) - timedelta(days=retention_days)).isoformat()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                DELETE FROM telegram_updates
                WHERE status IN ('sent', 'failed') AND updated_at < ?
                """,
                (cutoff,),
            )
        return cursor.rowcount


def default_agent_state_path() -> Path:
    """Return the external runtime path for non-authoritative agent conversations."""
    configured = os.environ.get("RESUME_BUILDER_AGENT_STATE", "").strip()
    if configured:
        return Path(configured).expanduser()
    return Path.home() / "Library" / "Application Support" / "Resume Builder" / "agent-state.sqlite"
