from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .models import JobObservation, ProviderResult
from .normalize import canonical_url, description_hash, normalized_key

SCHEMA_VERSION = 2

MIGRATION_1 = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS scrape_runs (
    id TEXT PRIMARY KEY,
    source_key TEXT NOT NULL,
    provider TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT NOT NULL,
    success INTEGER NOT NULL,
    suspicious_empty INTEGER NOT NULL DEFAULT 0,
    observation_count INTEGER NOT NULL DEFAULT 0,
    inserted_count INTEGER NOT NULL DEFAULT 0,
    updated_count INTEGER NOT NULL DEFAULT 0,
    error TEXT
);
CREATE INDEX IF NOT EXISTS idx_scrape_runs_source ON scrape_runs(source_key, completed_at);
CREATE TABLE IF NOT EXISTS checkpoints (
    source_key TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    last_success_at TEXT NOT NULL,
    last_run_id TEXT NOT NULL REFERENCES scrape_runs(id)
);
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    normalized_company TEXT NOT NULL,
    normalized_title TEXT NOT NULL,
    display_company TEXT NOT NULL,
    display_title TEXT NOT NULL,
    location TEXT NOT NULL DEFAULT '',
    work_mode TEXT NOT NULL DEFAULT 'unknown',
    employment_type TEXT,
    salary_min REAL,
    salary_max REAL,
    salary_currency TEXT,
    salary_interval TEXT,
    posted_at TEXT,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','possibly_closed','closed','reopened')),
    closed_at TEXT,
    preferred_observation_id TEXT,
    canonical_apply_url TEXT NOT NULL DEFAULT '',
    description_text TEXT NOT NULL DEFAULT '',
    description_hash TEXT NOT NULL DEFAULT '',
    description_quality TEXT NOT NULL DEFAULT 'missing'
);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status, last_seen_at);
CREATE INDEX IF NOT EXISTS idx_jobs_company_title ON jobs(normalized_company, normalized_title);
CREATE TABLE IF NOT EXISTS observations (
    id TEXT PRIMARY KEY,
    observation_key TEXT NOT NULL UNIQUE,
    provider TEXT NOT NULL,
    source_key TEXT NOT NULL,
    provider_board_id TEXT NOT NULL DEFAULT '',
    provider_job_id TEXT NOT NULL DEFAULT '',
    source_url TEXT NOT NULL,
    canonical_source_url TEXT NOT NULL DEFAULT '',
    direct_apply_url TEXT NOT NULL DEFAULT '',
    canonical_apply_url TEXT NOT NULL DEFAULT '',
    title_raw TEXT NOT NULL,
    company_raw TEXT NOT NULL,
    location_raw TEXT NOT NULL DEFAULT '',
    description_html TEXT NOT NULL DEFAULT '',
    description_text TEXT NOT NULL DEFAULT '',
    description_hash TEXT NOT NULL DEFAULT '',
    description_quality TEXT NOT NULL DEFAULT 'missing',
    posted_at TEXT,
    salary_min REAL,
    salary_max REAL,
    salary_currency TEXT,
    salary_interval TEXT,
    employment_type TEXT,
    remote INTEGER,
    raw_payload_json TEXT,
    raw_payload_expires_at TEXT,
    parser_version TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    enrichment_status TEXT NOT NULL DEFAULT 'complete',
    enrichment_attempts INTEGER NOT NULL DEFAULT 0,
    missing_streak INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_observations_provider_id
ON observations(provider, provider_board_id, provider_job_id);
CREATE INDEX IF NOT EXISTS idx_observations_urls ON observations(canonical_source_url, canonical_apply_url);
CREATE TABLE IF NOT EXISTS job_observation_links (
    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    observation_id TEXT NOT NULL UNIQUE REFERENCES observations(id) ON DELETE CASCADE,
    merge_reason TEXT NOT NULL,
    merge_confidence REAL NOT NULL,
    linked_at TEXT NOT NULL,
    PRIMARY KEY(job_id, observation_id)
);
CREATE TABLE IF NOT EXISTS possible_duplicates (
    left_job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    right_job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    reason TEXT NOT NULL,
    confidence REAL NOT NULL,
    created_at TEXT NOT NULL,
    resolved_at TEXT,
    resolution TEXT,
    PRIMARY KEY(left_job_id, right_job_id)
);
CREATE VIRTUAL TABLE IF NOT EXISTS jobs_fts USING fts5(
    job_id UNINDEXED,
    title,
    company,
    location,
    description
);
"""

MIGRATION_2 = """
ALTER TABLE scrape_runs ADD COLUMN metrics_json TEXT NOT NULL DEFAULT '{}';
"""

MIGRATIONS = {1: MIGRATION_1, 2: MIGRATION_2}


def _iso(value: datetime | None) -> str | None:
    return value.astimezone(UTC).isoformat() if value else None


class InventoryDatabase:
    def __init__(self, path: Path, raw_retention_days: int = 30):
        self.path = path
        self.raw_retention_days = raw_retention_days
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA busy_timeout = 5000")
        return conn

    def migrate(self) -> None:
        existed = self.path.exists() and self.path.stat().st_size > 0
        with self.connect() as conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL
                )"""
            )
            current = conn.execute("SELECT COALESCE(MAX(version), 0) FROM schema_migrations").fetchone()[0]
        if current >= SCHEMA_VERSION:
            return
        if existed:
            backup_dir = self.path.parent / "backups"
            backup_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
            shutil.copy2(self.path, backup_dir / f"{self.path.stem}-pre-v{SCHEMA_VERSION}-{stamp}.db")
        with self.connect() as conn:
            for version in range(current + 1, SCHEMA_VERSION + 1):
                conn.executescript(MIGRATIONS[version])
                conn.execute(
                    "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                    (version, _iso(datetime.now(UTC))),
                )

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        conn = self.connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def checkpoint(self, source_key: str) -> datetime | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT last_success_at FROM checkpoints WHERE source_key = ?", (source_key,)
            ).fetchone()
        return datetime.fromisoformat(row[0]) if row else None

    def record_result(self, result: ProviderResult) -> tuple[int, int]:
        run_id = str(uuid.uuid4())
        inserted = 0
        updated = 0
        with self.transaction() as conn:
            for observation in result.observations:
                was_inserted = self._upsert_observation(
                    conn, observation, result.source_key, result.completed_at
                )
                inserted += int(was_inserted)
                updated += int(not was_inserted)
            conn.execute(
                """INSERT INTO scrape_runs(
                    id, source_key, provider, started_at, completed_at, success, suspicious_empty,
                    observation_count, inserted_count, updated_count, error, metrics_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    run_id,
                    result.source_key,
                    result.provider,
                    _iso(result.started_at),
                    _iso(result.completed_at),
                    int(result.success),
                    int(result.suspicious_empty),
                    len(result.observations),
                    inserted,
                    updated,
                    result.error,
                    json.dumps(result.metrics, sort_keys=True),
                ),
            )
            if result.success and not result.suspicious_empty:
                conn.execute(
                    """INSERT INTO checkpoints(source_key, provider, last_success_at, last_run_id)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(source_key) DO UPDATE SET
                      provider=excluded.provider,
                      last_success_at=excluded.last_success_at,
                      last_run_id=excluded.last_run_id""",
                    (result.source_key, result.provider, _iso(result.completed_at), run_id),
                )
            if result.success and result.authoritative_complete and not result.suspicious_empty:
                self._apply_authoritative_liveness(conn, result.source_key, result.completed_at)
            conn.execute(
                "UPDATE observations SET raw_payload_json = NULL WHERE raw_payload_expires_at < ?",
                (_iso(result.completed_at),),
            )
        return inserted, updated

    def _observation_key(self, observation: JobObservation) -> str:
        identity = observation.provider_job_id or canonical_url(observation.source_url)
        stable = "|".join([observation.provider, observation.provider_board_id, identity])
        return hashlib.sha256(stable.encode("utf-8")).hexdigest()

    def _upsert_observation(
        self, conn: sqlite3.Connection, observation: JobObservation, source_key: str, seen_at: datetime
    ) -> bool:
        key = self._observation_key(observation)
        existing = conn.execute("SELECT id FROM observations WHERE observation_key = ?", (key,)).fetchone()
        observation_id = existing[0] if existing else str(uuid.uuid4())
        text = observation.description_text.strip()
        quality = "complete" if len(text) >= 200 else "partial" if text else "missing"
        expires = seen_at + timedelta(days=self.raw_retention_days)
        values = (
            observation_id,
            key,
            observation.provider,
            source_key,
            observation.provider_board_id,
            observation.provider_job_id,
            observation.source_url,
            canonical_url(observation.source_url),
            observation.direct_apply_url,
            canonical_url(observation.direct_apply_url),
            observation.title,
            observation.company,
            observation.location,
            observation.description_html,
            text,
            description_hash(text),
            quality,
            _iso(observation.posted_at),
            observation.salary_min,
            observation.salary_max,
            observation.salary_currency,
            observation.salary_interval,
            observation.employment_type,
            None if observation.remote is None else int(observation.remote),
            json.dumps(observation.raw_payload, ensure_ascii=False, default=str),
            _iso(expires),
            observation.parser_version,
            _iso(seen_at),
            _iso(seen_at),
            "complete" if quality == "complete" else "pending",
        )
        if not existing:
            conn.execute(
                """INSERT INTO observations(
                    id, observation_key, provider, source_key, provider_board_id, provider_job_id, source_url,
                    canonical_source_url, direct_apply_url, canonical_apply_url, title_raw, company_raw,
                    location_raw, description_html, description_text, description_hash, description_quality,
                    posted_at, salary_min, salary_max, salary_currency, salary_interval, employment_type,
                    remote, raw_payload_json, raw_payload_expires_at, parser_version, first_seen_at,
                    last_seen_at, enrichment_status
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                values,
            )
            job_id, reason, confidence = self._find_canonical_job(conn, observation)
            if not job_id:
                job_id = self._create_job(conn, observation, observation_id, seen_at, quality, text)
                reason, confidence = "new_canonical_job", 1.0
            conn.execute(
                """INSERT INTO job_observation_links(
                    job_id, observation_id, merge_reason, merge_confidence, linked_at
                ) VALUES (?, ?, ?, ?, ?)""",
                (job_id, observation_id, reason, confidence, _iso(seen_at)),
            )
        else:
            conn.execute(
                """UPDATE observations SET
                    source_url=?, canonical_source_url=?, direct_apply_url=?, canonical_apply_url=?,
                    title_raw=?, company_raw=?, location_raw=?, description_html=?, description_text=?,
                    description_hash=?, description_quality=?, posted_at=COALESCE(?, posted_at),
                    salary_min=COALESCE(?, salary_min), salary_max=COALESCE(?, salary_max),
                    salary_currency=COALESCE(?, salary_currency),
                    salary_interval=COALESCE(?, salary_interval),
                    employment_type=COALESCE(?, employment_type), remote=COALESCE(?, remote),
                    raw_payload_json=?, raw_payload_expires_at=?, parser_version=?, last_seen_at=?,
                    enrichment_status=?, source_key=?, missing_streak=0 WHERE id=?""",
                (
                    observation.source_url,
                    canonical_url(observation.source_url),
                    observation.direct_apply_url,
                    canonical_url(observation.direct_apply_url),
                    observation.title,
                    observation.company,
                    observation.location,
                    observation.description_html,
                    text,
                    description_hash(text),
                    quality,
                    _iso(observation.posted_at),
                    observation.salary_min,
                    observation.salary_max,
                    observation.salary_currency,
                    observation.salary_interval,
                    observation.employment_type,
                    None if observation.remote is None else int(observation.remote),
                    json.dumps(observation.raw_payload, ensure_ascii=False, default=str),
                    _iso(expires),
                    observation.parser_version,
                    _iso(seen_at),
                    "complete" if quality == "complete" else "pending",
                    source_key,
                    observation_id,
                ),
            )
        self._refresh_job(conn, observation_id, seen_at)
        return not bool(existing)

    def _apply_authoritative_liveness(
        self, conn: sqlite3.Connection, source_key: str, completed_at: datetime
    ) -> None:
        completed = _iso(completed_at)
        conn.execute(
            """UPDATE observations SET missing_streak=missing_streak+1
               WHERE source_key=? AND last_seen_at < ?""",
            (source_key, completed),
        )
        affected = conn.execute(
            """SELECT DISTINCT l.job_id FROM observations o
               JOIN job_observation_links l ON l.observation_id=o.id
               WHERE o.source_key=? AND o.missing_streak>0""",
            (source_key,),
        ).fetchall()
        for row in affected:
            job_id = row[0]
            active_authoritative = conn.execute(
                """SELECT 1 FROM observations o
                   JOIN job_observation_links l ON l.observation_id=o.id
                   WHERE l.job_id=?
                     AND o.provider IN ('greenhouse','lever','ashby','smartrecruiters','workday')
                     AND o.missing_streak=0 LIMIT 1""",
                (job_id,),
            ).fetchone()
            if active_authoritative:
                continue
            streak = conn.execute(
                """SELECT MAX(o.missing_streak) FROM observations o
                   JOIN job_observation_links l ON l.observation_id=o.id WHERE l.job_id=?""",
                (job_id,),
            ).fetchone()[0]
            status = "closed" if streak >= 2 else "possibly_closed"
            conn.execute(
                """UPDATE jobs SET status=?,
                   closed_at=CASE WHEN ?='closed' THEN ? ELSE closed_at END
                   WHERE id=?""",
                (status, status, completed, job_id),
            )

    def _find_canonical_job(
        self, conn: sqlite3.Connection, observation: JobObservation
    ) -> tuple[str | None, str, float]:
        urls = {canonical_url(observation.source_url), canonical_url(observation.direct_apply_url)} - {""}
        for url in urls:
            row = conn.execute(
                """SELECT l.job_id FROM observations o
                JOIN job_observation_links l ON l.observation_id=o.id
                WHERE o.canonical_source_url=? OR o.canonical_apply_url=? LIMIT 1""",
                (url, url),
            ).fetchone()
            if row:
                return row[0], "canonical_url", 1.0
        return None, "", 0.0

    def _create_job(
        self,
        conn: sqlite3.Connection,
        observation: JobObservation,
        observation_id: str,
        seen_at: datetime,
        quality: str,
        text: str,
    ) -> str:
        job_id = str(uuid.uuid4())
        apply_url = canonical_url(observation.direct_apply_url) or canonical_url(observation.source_url)
        work_mode = (
            "remote" if observation.remote is True else "onsite" if observation.remote is False else "unknown"
        )
        conn.execute(
            """INSERT INTO jobs(
                id, normalized_company, normalized_title, display_company, display_title, location, work_mode,
                employment_type, salary_min, salary_max, salary_currency, salary_interval, posted_at,
                first_seen_at, last_seen_at, preferred_observation_id, canonical_apply_url,
                description_text, description_hash, description_quality
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                job_id,
                normalized_key(observation.company),
                normalized_key(observation.title),
                observation.company,
                observation.title,
                observation.location,
                work_mode,
                observation.employment_type,
                observation.salary_min,
                observation.salary_max,
                observation.salary_currency,
                observation.salary_interval,
                _iso(observation.posted_at),
                _iso(seen_at),
                _iso(seen_at),
                observation_id,
                apply_url,
                text,
                description_hash(text),
                quality,
            ),
        )
        self._record_possible_duplicates(conn, job_id, seen_at)
        return job_id

    def _record_possible_duplicates(self, conn: sqlite3.Connection, job_id: str, seen_at: datetime) -> None:
        current = conn.execute(
            "SELECT normalized_company, normalized_title FROM jobs WHERE id=?", (job_id,)
        ).fetchone()
        matches = conn.execute(
            """SELECT id FROM jobs WHERE id<>? AND normalized_company=? AND normalized_title=?""",
            (job_id, current[0], current[1]),
        ).fetchall()
        for match in matches:
            left, right = sorted((job_id, match[0]))
            conn.execute(
                """INSERT OR IGNORE INTO possible_duplicates(
                    left_job_id, right_job_id, reason, confidence, created_at
                ) VALUES (?, ?, 'same_normalized_company_title', 0.70, ?)""",
                (left, right, _iso(seen_at)),
            )

    def _refresh_job(self, conn: sqlite3.Connection, observation_id: str, seen_at: datetime) -> None:
        row = conn.execute(
            """SELECT j.id, j.status, j.description_quality, j.preferred_observation_id,
                      o.provider, o.company_raw, o.title_raw, o.location_raw, o.description_text,
                      o.description_hash, o.description_quality,
                      o.canonical_apply_url, o.canonical_source_url,
                      o.posted_at, o.salary_min, o.salary_max, o.salary_currency, o.salary_interval,
                      o.employment_type, o.remote
               FROM job_observation_links l JOIN jobs j ON j.id=l.job_id
               JOIN observations o ON o.id=l.observation_id WHERE o.id=?""",
            (observation_id,),
        ).fetchone()
        if not row:
            return
        priority = {
            "greenhouse": 100,
            "lever": 100,
            "ashby": 100,
            "smartrecruiters": 100,
            "workday": 100,
            "indeed": 50,
            "linkedin": 40,
        }
        current = conn.execute(
            "SELECT provider, description_quality FROM observations WHERE id=?", (row[3],)
        ).fetchone()
        current_score = (
            priority.get(current[0], 10) + (20 if current[1] == "complete" else 0) if current else -1
        )
        candidate_score = priority.get(row[4], 10) + (20 if row[10] == "complete" else 0)
        status = "reopened" if row[1] in {"closed", "possibly_closed"} else row[1]
        if candidate_score >= current_score:
            conn.execute(
                """UPDATE jobs SET display_company=?, display_title=?,
                    normalized_company=?, normalized_title=?,
                    location=?, work_mode=?, employment_type=COALESCE(?, employment_type),
                    salary_min=COALESCE(?, salary_min),
                    salary_max=COALESCE(?, salary_max), salary_currency=COALESCE(?, salary_currency),
                    salary_interval=COALESCE(?, salary_interval), posted_at=COALESCE(?, posted_at),
                    last_seen_at=?, status=?, closed_at=NULL, preferred_observation_id=?,
                    canonical_apply_url=?, description_text=?,
                    description_hash=?, description_quality=? WHERE id=?""",
                (
                    row[5],
                    row[6],
                    normalized_key(row[5]),
                    normalized_key(row[6]),
                    row[7],
                    "remote" if row[19] == 1 else "onsite" if row[19] == 0 else "unknown",
                    row[18],
                    row[14],
                    row[15],
                    row[16],
                    row[17],
                    row[13],
                    _iso(seen_at),
                    status,
                    observation_id,
                    row[11] or row[12],
                    row[8],
                    row[9],
                    row[10],
                    row[0],
                ),
            )
        else:
            conn.execute(
                "UPDATE jobs SET last_seen_at=?, status=?, closed_at=NULL WHERE id=?",
                (_iso(seen_at), status, row[0]),
            )
        self._refresh_fts(conn, row[0])

    def _refresh_fts(self, conn: sqlite3.Connection, job_id: str) -> None:
        row = conn.execute(
            "SELECT display_title, display_company, location, description_text FROM jobs WHERE id=?",
            (job_id,),
        ).fetchone()
        conn.execute("DELETE FROM jobs_fts WHERE job_id=?", (job_id,))
        conn.execute(
            "INSERT INTO jobs_fts(job_id, title, company, location, description) VALUES (?, ?, ?, ?, ?)",
            (job_id, row[0], row[1], row[2], row[3]),
        )

    def stats(self) -> dict[str, int]:
        with self.connect() as conn:
            return {
                "jobs": conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0],
                "active_jobs": conn.execute(
                    "SELECT COUNT(*) FROM jobs WHERE status IN ('active','reopened')"
                ).fetchone()[0],
                "observations": conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0],
                "complete_descriptions": conn.execute(
                    "SELECT COUNT(*) FROM jobs WHERE description_quality='complete'"
                ).fetchone()[0],
                "successful_runs": conn.execute(
                    "SELECT COUNT(*) FROM scrape_runs WHERE success=1 AND suspicious_empty=0"
                ).fetchone()[0],
                "failed_runs": conn.execute(
                    "SELECT COUNT(*) FROM scrape_runs WHERE success=0 OR suspicious_empty=1"
                ).fetchone()[0],
            }
