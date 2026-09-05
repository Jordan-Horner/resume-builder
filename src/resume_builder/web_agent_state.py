"""Web-channel delivery state in the existing private agent database."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from .agent_state import AgentState


def _now() -> str:
    return datetime.now(UTC).isoformat()


class WebAgentState(AgentState):
    """Keep transport history separate from authoritative resume and vault files."""

    def _initialize(self) -> None:
        super()._initialize()
        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS web_threads(
                    id TEXT PRIMARY KEY, resume_id TEXT, title TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS web_runs(
                    id TEXT NOT NULL, thread_id TEXT NOT NULL REFERENCES web_threads(id)
                    ON DELETE CASCADE, prompt TEXT NOT NULL, response TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL, created_at TEXT NOT NULL,
                    PRIMARY KEY(thread_id, id)
                );
                CREATE UNIQUE INDEX IF NOT EXISTS web_one_active_run ON web_runs(thread_id)
                    WHERE status = 'running';
                CREATE TABLE IF NOT EXISTS web_proposals(
                    id TEXT PRIMARY KEY, thread_id TEXT NOT NULL REFERENCES web_threads(id)
                    ON DELETE CASCADE, payload TEXT NOT NULL, status TEXT NOT NULL,
                    message TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL
                );
            """)

    def create_thread(self, resume_id: str | None) -> dict[str, Any]:
        identity = str(uuid4())
        with self._connect() as db:
            db.execute(
                "INSERT INTO web_threads VALUES (?, ?, ?, ?)",
                (identity, resume_id, "New conversation", _now()),
            )
        return self.thread(identity)

    def list_threads(self) -> list[dict[str, Any]]:
        with self._connect() as db:
            db.row_factory = sqlite3.Row
            return [
                dict(row)
                for row in db.execute(
                    "SELECT * FROM web_threads ORDER BY updated_at DESC LIMIT 100"
                )
            ]

    def thread(self, identity: str) -> dict[str, Any]:
        with self._connect() as db:
            db.row_factory = sqlite3.Row
            row = db.execute("SELECT * FROM web_threads WHERE id = ?", (identity,)).fetchone()
            if row is None:
                raise LookupError("Conversation not found")
            result = dict(row)
            runs = [
                dict(r)
                for r in db.execute(
                    "SELECT * FROM web_runs WHERE thread_id = ? ORDER BY rowid", (identity,)
                )
            ]
            result["runs"] = runs
            result["messages"] = [
                message
                for run in runs
                for message in (
                    [{"id": run["id"], "role": "user", "content": run["prompt"]}]
                    + (
                        [
                            {
                                "id": run["id"] + "-reply",
                                "role": "assistant",
                                "content": run["response"],
                            }
                        ]
                        if run["response"]
                        else []
                    )
                )
            ]
            result["proposals"] = [
                dict(r) | {"payload": json.loads(r["payload"])}
                for r in db.execute(
                    "SELECT * FROM web_proposals WHERE thread_id = ? ORDER BY rowid", (identity,)
                )
            ]
            return result

    def delete_thread(self, identity: str) -> None:
        self.thread(identity)
        with self._connect() as db:
            if db.execute(
                "SELECT 1 FROM web_proposals WHERE thread_id=? AND status='applying'", (identity,)
            ).fetchone():
                raise ValueError("Wait for the resume operation to finish")
            db.execute(
                "DELETE FROM agent_messages WHERE channel='web' AND conversation_id=?", (identity,)
            )
            db.execute("DELETE FROM web_threads WHERE id=?", (identity,))

    def begin_turn(self, identity: str, run_id: str, prompt: str) -> bool:
        self.thread(identity)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                "SELECT prompt FROM web_runs WHERE thread_id=? AND id=?", (identity, run_id)
            ).fetchone()
            if existing:
                if existing[0] != prompt:
                    raise ValueError("Request ID was already used for a different message")
                return False
            try:
                db.execute(
                    "INSERT INTO web_runs(id,thread_id,prompt,status,created_at) "
                    "VALUES (?,?,?,'running',?)",
                    (run_id, identity, prompt, _now()),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError("A response is already running in this conversation") from exc
            db.execute(
                "UPDATE web_threads SET title=?,updated_at=? WHERE id=?",
                (prompt[:80], _now(), identity),
            )
        return True

    def finish_turn(
        self, identity: str, run_id: str, response: str, status: str = "completed"
    ) -> None:
        with self._connect() as db:
            db.execute(
                "UPDATE web_runs SET response=?,status=? "
                "WHERE thread_id=? AND id=? AND status='running'",
                (response, status, identity, run_id),
            )

    def propose(self, identity: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.thread(identity)
        proposal_id = str(uuid4())
        with self._connect() as db:
            db.execute(
                "INSERT INTO web_proposals(id,thread_id,payload,status,created_at) "
                "VALUES (?,?,?,'pending',?)",
                (proposal_id, identity, json.dumps(payload), _now()),
            )
        return next(p for p in self.thread(identity)["proposals"] if p["id"] == proposal_id)

    def claim_proposal(self, identity: str, proposal_id: str) -> bool:
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT status FROM web_proposals WHERE thread_id=? AND id=?",
                (identity, proposal_id),
            ).fetchone()
            if row is None:
                raise LookupError("Proposed change not found")
            if row[0] != "pending":
                return False
            if db.execute(
                "SELECT 1 FROM web_proposals WHERE thread_id=? AND status='applying'",
                (identity,),
            ).fetchone():
                raise ValueError("Another change is still being reviewed in this conversation")
            db.execute("UPDATE web_proposals SET status='applying' WHERE id=?", (proposal_id,))
            return True

    def finish_proposal(self, identity: str, proposal_id: str, status: str, message: str) -> None:
        with self._connect() as db:
            db.execute(
                "UPDATE web_proposals SET status=?,message=? WHERE thread_id=? AND id=?",
                (status, message, identity, proposal_id),
            )

    def recover_interrupted(self) -> None:
        """Call once at server startup, never when opening another database connection."""
        with self._connect() as db:
            db.execute(
                "UPDATE web_runs SET status='interrupted',response=? WHERE status='running'",
                ("The server restarted before this response completed. Please try again.",),
            )
            db.execute(
                "UPDATE web_proposals SET status='interrupted',message=? WHERE status='applying'",
                (
                    "The server restarted during this edit. Review the current resume before "
                    "requesting another change; it has not been applied again.",
                ),
            )
