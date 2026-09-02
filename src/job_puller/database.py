from __future__ import annotations

import hashlib
import json
import re
import shutil
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .detail_cache import CachedProviderDetail
from .models import JobObservation, ProviderResult
from .normalize import canonical_url, description_hash, normalized_key
from .work_modes import WorkArrangement, WorkMode, display_work_mode

SCHEMA_VERSION = 7

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

MIGRATION_3 = """
CREATE TABLE IF NOT EXISTS provider_detail_cache (
    provider TEXT NOT NULL,
    provider_job_id TEXT NOT NULL,
    parser_version TEXT NOT NULL,
    response_body TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    PRIMARY KEY(provider, provider_job_id, parser_version)
);
CREATE INDEX IF NOT EXISTS idx_provider_detail_cache_expiry
ON provider_detail_cache(expires_at);
CREATE INDEX IF NOT EXISTS idx_jobs_exact_content
ON jobs(normalized_company, normalized_title, description_hash);
"""

MIGRATION_4 = """
CREATE TABLE IF NOT EXISTS application_url_aliases (
    alias_url TEXT PRIMARY KEY,
    target_url TEXT NOT NULL,
    verified_at TEXT NOT NULL,
    CHECK(alias_url<>target_url)
);
CREATE INDEX IF NOT EXISTS idx_application_url_alias_target
ON application_url_aliases(target_url);
"""

MIGRATION_5 = """
CREATE TABLE IF NOT EXISTS observation_work_modes (
    observation_id TEXT NOT NULL REFERENCES observations(id) ON DELETE CASCADE,
    mode TEXT NOT NULL CHECK(mode IN ('remote','hybrid','onsite','unknown')),
    evidence_source TEXT NOT NULL,
    evidence_rule TEXT NOT NULL,
    evidence_text TEXT NOT NULL DEFAULT '',
    PRIMARY KEY(observation_id, mode, evidence_source, evidence_rule)
);
CREATE INDEX IF NOT EXISTS idx_observation_work_modes_mode
ON observation_work_modes(mode, observation_id);
CREATE TABLE IF NOT EXISTS job_work_modes (
    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    mode TEXT NOT NULL CHECK(mode IN ('remote','hybrid','onsite','unknown')),
    PRIMARY KEY(job_id, mode)
);
CREATE INDEX IF NOT EXISTS idx_job_work_modes_mode
ON job_work_modes(mode, job_id);

INSERT OR IGNORE INTO observation_work_modes(
    observation_id, mode, evidence_source, evidence_rule, evidence_text
)
SELECT id,
       CASE WHEN remote=1 THEN 'remote' ELSE 'unknown' END,
       'legacy',
       CASE WHEN remote=1 THEN 'legacy_remote_true' ELSE 'legacy_not_remote_is_unknown' END,
       ''
FROM observations;

UPDATE jobs SET work_mode='unknown' WHERE work_mode<>'remote';
INSERT OR IGNORE INTO job_work_modes(job_id, mode)
SELECT id, CASE WHEN work_mode='remote' THEN 'remote' ELSE 'unknown' END FROM jobs;
"""

MIGRATION_6 = """
CREATE TABLE IF NOT EXISTS possible_reposts (
    earlier_job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    later_job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    reason TEXT NOT NULL,
    confidence REAL NOT NULL,
    first_seen_gap_days INTEGER NOT NULL,
    detected_at TEXT NOT NULL,
    PRIMARY KEY(earlier_job_id, later_job_id),
    CHECK(earlier_job_id<>later_job_id)
);
CREATE INDEX IF NOT EXISTS idx_possible_reposts_later
ON possible_reposts(later_job_id, detected_at);
"""

MIGRATION_7 = """
ALTER TABLE scrape_runs ADD COLUMN outcome TEXT NOT NULL DEFAULT 'failed';
ALTER TABLE scrape_runs ADD COLUMN retryable INTEGER NOT NULL DEFAULT 0;
ALTER TABLE scrape_runs ADD COLUMN error_category TEXT;
UPDATE scrape_runs SET
    outcome=CASE
        WHEN success=1 AND suspicious_empty=0 AND observation_count>0 THEN 'healthy'
        WHEN success=1 AND suspicious_empty=0 THEN 'healthy-empty'
        WHEN observation_count>0 THEN 'partial'
        ELSE 'failed'
    END,
    retryable=CASE WHEN suspicious_empty=1 THEN 1 ELSE 0 END,
    error_category=CASE WHEN suspicious_empty=1 THEN 'suspicious-empty' ELSE NULL END;
CREATE INDEX IF NOT EXISTS idx_scrape_runs_outcome
ON scrape_runs(outcome, completed_at);
"""

MIGRATIONS = {
    1: MIGRATION_1,
    2: MIGRATION_2,
    3: MIGRATION_3,
    4: MIGRATION_4,
    5: MIGRATION_5,
    6: MIGRATION_6,
    7: MIGRATION_7,
}


def _iso(value: datetime | None) -> str | None:
    return value.astimezone(UTC).isoformat() if value else None


def _workday_reference_matches(provider_job_id: str, url: str) -> bool:
    job_id = provider_job_id.strip()
    if not job_id or not url:
        return False
    return bool(
        re.search(
            rf"(?:_|/){re.escape(job_id)}(?:-\d+)?(?:[/?#]|$)",
            url,
            flags=re.IGNORECASE,
        )
    )


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
            current = conn.execute(
                "SELECT COALESCE(MAX(version), 0) FROM schema_migrations"
            ).fetchone()[0]
        if current >= SCHEMA_VERSION:
            return
        if existed:
            backup_dir = self.path.parent / "backups"
            backup_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
            shutil.copy2(
                self.path, backup_dir / f"{self.path.stem}-pre-v{SCHEMA_VERSION}-{stamp}.db"
            )
        with self.connect() as conn:
            for version in range(current + 1, SCHEMA_VERSION + 1):
                conn.executescript(MIGRATIONS[version])
                conn.execute(
                    "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                    (version, _iso(datetime.now(UTC))),
                )
            if current < 3:
                self._reconcile_exact_duplicates(conn)
            if current < 4:
                self._recanonicalize_observation_urls(conn)
                self._reconcile_url_duplicates(conn)

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

    def active_application_links(self) -> list[dict[str, object]]:
        """Return direct application links that currently back active inventory jobs."""
        with self.connect() as conn:
            rows = conn.execute(
                """SELECT o.direct_apply_url AS url, o.company_raw AS company, COUNT(*) AS observations
                   FROM observations o
                   JOIN job_observation_links l ON l.observation_id=o.id
                   JOIN jobs j ON j.id=l.job_id
                   WHERE o.direct_apply_url<>''
                     AND o.provider IN ('indeed','linkedin')
                     AND j.status IN ('active','reopened')
                   GROUP BY o.direct_apply_url, o.company_raw
                   ORDER BY observations DESC, company, url"""
            ).fetchall()
        return [dict(row) for row in rows]

    def reconcile_exact_duplicates(self) -> int:
        with self.transaction() as conn:
            return self._reconcile_exact_duplicates(conn)

    def record_verified_redirects(self, redirects: list[tuple[str, str]]) -> tuple[int, int, int]:
        """Persist Greenhouse short-link redirects and reconcile exact URL matches."""
        recorded = 0
        updated = 0
        now = _iso(datetime.now(UTC))
        with self.transaction() as conn:
            for source, target in redirects:
                alias_url = canonical_url(source)
                target_url = canonical_url(target)
                if not alias_url.startswith("https://grnh.se/") or not target_url.startswith(
                    "https://"
                ):
                    continue
                cursor = conn.execute(
                    """INSERT INTO application_url_aliases(alias_url, target_url, verified_at)
                       VALUES (?, ?, ?)
                       ON CONFLICT(alias_url) DO UPDATE SET
                         target_url=excluded.target_url, verified_at=excluded.verified_at""",
                    (alias_url, target_url, now),
                )
                recorded += cursor.rowcount
                cursor = conn.execute(
                    """UPDATE observations SET canonical_apply_url=?
                       WHERE canonical_apply_url=? AND direct_apply_url<>''""",
                    (target_url, alias_url),
                )
                updated += cursor.rowcount
            merged = self._reconcile_url_duplicates(conn)
        return recorded, updated, merged

    def reconcile_provider_identities(self) -> int:
        """Merge exact Workday requisition identities across syndicated URL variants."""
        with self.transaction() as conn:
            rows = conn.execute(
                """SELECT DISTINCT
                         ats_job.id AS ats_job_id,
                         ats.provider_job_id AS provider_job_id,
                         commercial_job.id AS commercial_job_id,
                         commercial.direct_apply_url AS commercial_url
                   FROM observations ats
                   JOIN job_observation_links ats_link ON ats_link.observation_id=ats.id
                   JOIN jobs ats_job ON ats_job.id=ats_link.job_id
                   JOIN jobs commercial_job
                     ON commercial_job.normalized_company=ats_job.normalized_company
                    AND commercial_job.normalized_title=ats_job.normalized_title
                    AND commercial_job.id<>ats_job.id
                   JOIN job_observation_links commercial_link
                     ON commercial_link.job_id=commercial_job.id
                   JOIN observations commercial
                     ON commercial.id=commercial_link.observation_id
                   WHERE ats.provider='workday'
                     AND commercial.provider IN ('indeed','linkedin')
                     AND commercial.direct_apply_url<>''"""
            ).fetchall()
            matches: dict[str, set[str]] = {}
            for row in rows:
                if _workday_reference_matches(row[1], row[3]):
                    matches.setdefault(row[0], set()).add(row[2])
            merged = 0
            now = datetime.now(UTC)
            for ats_job_id, commercial_jobs in matches.items():
                if len(commercial_jobs) != 1:
                    continue
                survivor = next(iter(commercial_jobs))
                self._merge_job_into(
                    conn,
                    survivor,
                    ats_job_id,
                    "exact_provider_job_identity",
                    1.0,
                    now,
                )
                merged += 1
        return merged

    def _recanonicalize_observation_urls(self, conn: sqlite3.Connection) -> None:
        rows = conn.execute("SELECT id, source_url, direct_apply_url FROM observations").fetchall()
        for row in rows:
            conn.execute(
                """UPDATE observations
                   SET canonical_source_url=?, canonical_apply_url=? WHERE id=?""",
                (
                    canonical_url(row[1]),
                    self._canonical_application_url(conn, row[2]),
                    row[0],
                ),
            )

    def _reconcile_url_duplicates(self, conn: sqlite3.Connection) -> int:
        urls = conn.execute(
            """WITH observation_urls AS (
                   SELECT id, canonical_source_url AS url FROM observations
                   WHERE canonical_source_url<>''
                   UNION
                   SELECT id, canonical_apply_url AS url FROM observations
                   WHERE canonical_apply_url<>''
               )
               SELECT u.url FROM observation_urls u
               JOIN job_observation_links l ON l.observation_id=u.id
               GROUP BY u.url HAVING COUNT(DISTINCT l.job_id)>1"""
        ).fetchall()
        merged = 0
        now = datetime.now(UTC)
        for (url,) in urls:
            rows = conn.execute(
                """SELECT DISTINCT l.job_id, j.first_seen_at
                   FROM observations o
                   JOIN job_observation_links l ON l.observation_id=o.id
                   JOIN jobs j ON j.id=l.job_id
                   WHERE o.canonical_source_url=? OR o.canonical_apply_url=?
                   ORDER BY j.first_seen_at, l.job_id""",
                (url, url),
            ).fetchall()
            if len(rows) < 2:
                continue
            survivor = rows[0][0]
            for row in rows[1:]:
                self._merge_job_into(conn, survivor, row[0], "canonical_url", 1.0, now)
                merged += 1
        return merged

    def _merge_job_into(
        self,
        conn: sqlite3.Connection,
        survivor: str,
        duplicate: str,
        reason: str,
        confidence: float,
        now: datetime,
    ) -> None:
        observation_ids = [
            item[0]
            for item in conn.execute(
                "SELECT observation_id FROM job_observation_links WHERE job_id=?",
                (duplicate,),
            ).fetchall()
        ]
        conn.execute(
            "DELETE FROM possible_duplicates WHERE left_job_id=? OR right_job_id=?",
            (duplicate, duplicate),
        )
        conn.execute(
            """UPDATE job_observation_links
               SET job_id=?, merge_reason=?, merge_confidence=? WHERE job_id=?""",
            (survivor, reason, confidence, duplicate),
        )
        conn.execute("DELETE FROM jobs_fts WHERE job_id=?", (duplicate,))
        conn.execute("DELETE FROM jobs WHERE id=?", (duplicate,))
        for observation_id in observation_ids:
            self._refresh_job(conn, observation_id, now)

    def _reconcile_exact_duplicates(self, conn: sqlite3.Connection) -> int:
        groups = conn.execute(
            """SELECT normalized_company, normalized_title, description_hash
               FROM jobs WHERE description_hash<>''
               GROUP BY normalized_company, normalized_title, description_hash
               HAVING COUNT(*) > 1"""
        ).fetchall()
        merged = 0
        now = datetime.now(UTC)
        for company, title, content_hash in groups:
            rows = conn.execute(
                """SELECT id FROM jobs
                   WHERE normalized_company=? AND normalized_title=? AND description_hash=?
                   ORDER BY first_seen_at, id""",
                (company, title, content_hash),
            ).fetchall()
            survivor = rows[0][0]
            for row in rows[1:]:
                self._merge_job_into(
                    conn,
                    survivor,
                    row[0],
                    "exact_company_title_description",
                    0.98,
                    now,
                )
                merged += 1
            self._record_possible_duplicates(conn, survivor, now)
        return merged

    def get_provider_detail(
        self, provider: str, provider_job_id: str, parser_version: str
    ) -> CachedProviderDetail | None:
        with self.connect() as conn:
            row = conn.execute(
                """SELECT response_body, fetched_at, expires_at
                   FROM provider_detail_cache
                   WHERE provider=? AND provider_job_id=? AND parser_version=?""",
                (provider, provider_job_id, parser_version),
            ).fetchone()
        if row is None:
            return None
        return CachedProviderDetail(
            response_body=row[0],
            fetched_at=datetime.fromisoformat(row[1]),
            expires_at=datetime.fromisoformat(row[2]),
        )

    def put_provider_detail(
        self,
        provider: str,
        provider_job_id: str,
        parser_version: str,
        response_body: str,
        fetched_at: datetime,
        expires_at: datetime,
    ) -> None:
        with self.transaction() as conn:
            conn.execute(
                """INSERT INTO provider_detail_cache(
                    provider, provider_job_id, parser_version, response_body, fetched_at, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(provider, provider_job_id, parser_version) DO UPDATE SET
                    response_body=excluded.response_body,
                    fetched_at=excluded.fetched_at,
                    expires_at=excluded.expires_at""",
                (
                    provider,
                    provider_job_id,
                    parser_version,
                    response_body,
                    _iso(fetched_at),
                    _iso(expires_at),
                ),
            )

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
            self._reconcile_url_duplicates(conn)
            conn.execute(
                """INSERT INTO scrape_runs(
                    id, source_key, provider, started_at, completed_at, success, suspicious_empty,
                    observation_count, inserted_count, updated_count, error, metrics_json,
                    outcome, retryable, error_category
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
                    result.outcome.value,
                    int(result.retryable),
                    result.error_category,
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
            conn.execute(
                "DELETE FROM provider_detail_cache WHERE expires_at < ?",
                (_iso(result.completed_at),),
            )
        return inserted, updated

    def _observation_key(self, observation: JobObservation) -> str:
        identity = observation.provider_job_id or canonical_url(observation.source_url)
        stable = "|".join([observation.provider, observation.provider_board_id, identity])
        return hashlib.sha256(stable.encode("utf-8")).hexdigest()

    def _canonical_application_url(self, conn: sqlite3.Connection, value: str) -> str:
        url = canonical_url(value)
        if not url:
            return ""
        row = conn.execute(
            "SELECT target_url FROM application_url_aliases WHERE alias_url=?", (url,)
        ).fetchone()
        return row[0] if row else url

    def _replace_observation_work_modes(
        self,
        conn: sqlite3.Connection,
        observation_id: str,
        arrangement: WorkArrangement,
    ) -> None:
        conn.execute(
            "DELETE FROM observation_work_modes WHERE observation_id=?",
            (observation_id,),
        )
        evidenced_modes: set[WorkMode] = set()
        for item in arrangement.evidence:
            conn.execute(
                """INSERT INTO observation_work_modes(
                       observation_id, mode, evidence_source, evidence_rule, evidence_text
                   ) VALUES (?, ?, ?, ?, ?)""",
                (observation_id, item.mode.value, item.source, item.rule, item.matched_text),
            )
            evidenced_modes.add(item.mode)
        for mode in arrangement.available_modes - evidenced_modes:
            conn.execute(
                """INSERT INTO observation_work_modes(
                       observation_id, mode, evidence_source, evidence_rule, evidence_text
                   ) VALUES (?, ?, 'inferred', 'mode_without_evidence', '')""",
                (observation_id, mode.value),
            )

    def _observation_work_modes(
        self, conn: sqlite3.Connection, observation_id: str
    ) -> frozenset[WorkMode]:
        rows = conn.execute(
            "SELECT DISTINCT mode FROM observation_work_modes WHERE observation_id=?",
            (observation_id,),
        ).fetchall()
        return frozenset(WorkMode(row[0]) for row in rows) or frozenset({WorkMode.UNKNOWN})

    def _replace_job_work_modes(
        self, conn: sqlite3.Connection, job_id: str, modes: frozenset[WorkMode]
    ) -> None:
        conn.execute("DELETE FROM job_work_modes WHERE job_id=?", (job_id,))
        conn.executemany(
            "INSERT INTO job_work_modes(job_id, mode) VALUES (?, ?)",
            ((job_id, mode.value) for mode in sorted(modes, key=lambda item: item.value)),
        )

    def _upsert_observation(
        self,
        conn: sqlite3.Connection,
        observation: JobObservation,
        source_key: str,
        seen_at: datetime,
    ) -> bool:
        key = self._observation_key(observation)
        existing = conn.execute(
            "SELECT id FROM observations WHERE observation_key = ?", (key,)
        ).fetchone()
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
            self._canonical_application_url(conn, observation.direct_apply_url),
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
                    self._canonical_application_url(conn, observation.direct_apply_url),
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
        assert observation.work_arrangement is not None
        self._replace_observation_work_modes(conn, observation_id, observation.work_arrangement)
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
                     AND o.provider IN (
                         'jazzhr','rippling','greenhouse','lever','ashby','smartrecruiters','workday'
                     )
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
        urls = {
            canonical_url(observation.source_url),
            self._canonical_application_url(conn, observation.direct_apply_url),
        } - {""}
        for url in urls:
            row = conn.execute(
                """SELECT l.job_id FROM observations o
                JOIN job_observation_links l ON l.observation_id=o.id
                WHERE o.canonical_source_url=? OR o.canonical_apply_url=? LIMIT 1""",
                (url, url),
            ).fetchone()
            if row:
                return row[0], "canonical_url", 1.0
        identity_match = self._find_provider_identity_job(conn, observation)
        if identity_match:
            return identity_match, "exact_provider_job_identity", 1.0
        text = observation.description_text.strip()
        content_hash = description_hash(text) if text else ""
        if content_hash:
            row = conn.execute(
                """SELECT id FROM jobs
                   WHERE normalized_company=? AND normalized_title=? AND description_hash=?
                   LIMIT 1""",
                (
                    normalized_key(observation.company),
                    normalized_key(observation.title),
                    content_hash,
                ),
            ).fetchone()
            if row:
                return row[0], "exact_company_title_description", 0.98
        return None, "", 0.0

    def _find_provider_identity_job(
        self, conn: sqlite3.Connection, observation: JobObservation
    ) -> str | None:
        company = normalized_key(observation.company)
        title = normalized_key(observation.title)
        if observation.provider == "workday" and observation.provider_job_id:
            rows = conn.execute(
                """SELECT DISTINCT l.job_id, o.direct_apply_url
                   FROM observations o
                   JOIN job_observation_links l ON l.observation_id=o.id
                   JOIN jobs j ON j.id=l.job_id
                   WHERE o.provider IN ('indeed','linkedin')
                     AND j.normalized_company=? AND j.normalized_title=?""",
                (company, title),
            ).fetchall()
            matches = {
                row[0]
                for row in rows
                if _workday_reference_matches(observation.provider_job_id, row[1])
            }
            return next(iter(matches)) if len(matches) == 1 else None
        if observation.provider in {"indeed", "linkedin"} and observation.direct_apply_url:
            rows = conn.execute(
                """SELECT DISTINCT l.job_id, o.provider_job_id
                   FROM observations o
                   JOIN job_observation_links l ON l.observation_id=o.id
                   JOIN jobs j ON j.id=l.job_id
                   WHERE o.provider='workday'
                     AND j.normalized_company=? AND j.normalized_title=?""",
                (company, title),
            ).fetchall()
            matches = {
                row[0]
                for row in rows
                if _workday_reference_matches(row[1], observation.direct_apply_url)
            }
            return next(iter(matches)) if len(matches) == 1 else None
        return None

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
        apply_url = canonical_url(observation.direct_apply_url) or canonical_url(
            observation.source_url
        )
        work_mode = display_work_mode(observation.work_modes)
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
        self._replace_job_work_modes(conn, job_id, observation.work_modes)
        self._record_possible_duplicates(conn, job_id, seen_at)
        return job_id

    def _record_possible_duplicates(
        self, conn: sqlite3.Connection, job_id: str, seen_at: datetime
    ) -> None:
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

    def _refresh_job(
        self, conn: sqlite3.Connection, observation_id: str, seen_at: datetime
    ) -> None:
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
            "jazzhr": 100,
            "rippling": 100,
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
            priority.get(current[0], 10) + (20 if current[1] == "complete" else 0)
            if current
            else -1
        )
        candidate_score = priority.get(row[4], 10) + (20 if row[10] == "complete" else 0)
        status = "reopened" if row[1] in {"closed", "possibly_closed"} else row[1]
        if candidate_score >= current_score:
            candidate_modes = self._observation_work_modes(conn, observation_id)
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
                    display_work_mode(candidate_modes),
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
            self._replace_job_work_modes(conn, row[0], candidate_modes)
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

    def job_ids(self) -> set[str]:
        """Return every canonical job ID, including inactive and reopened jobs."""
        with self.connect() as conn:
            return {str(row[0]) for row in conn.execute("SELECT id FROM jobs")}

    def active_job_ids_first_seen_since(self, started_at: datetime) -> set[str]:
        """Return active canonical jobs first created after an interrupted refresh began."""
        with self.connect() as conn:
            return {
                str(row[0])
                for row in conn.execute(
                    """SELECT id FROM jobs
                       WHERE status IN ('active','reopened') AND first_seen_at >= ?""",
                    (_iso(started_at),),
                )
            }

    def scrape_runs_since(self, started_at: datetime) -> list[dict[str, object]]:
        """Return provider coverage recorded during one orchestration refresh."""
        with self.connect() as conn:
            rows = conn.execute(
                """SELECT source_key, provider, success, suspicious_empty, error,
                          outcome, retryable, error_category
                   FROM scrape_runs
                   WHERE started_at >= ?
                   ORDER BY started_at, id""",
                (_iso(started_at),),
            ).fetchall()
        return [
            {
                "source_key": str(row[0]),
                "provider": str(row[1]),
                "success": bool(row[2]),
                "suspicious_empty": bool(row[3]),
                "error": row[4],
                "outcome": str(row[5]),
                "retryable": bool(row[6]),
                "error_category": row[7],
            }
            for row in rows
        ]

    def source_health(self) -> list[dict[str, object]]:
        """Return one current health summary per configured source seen by the inventory."""
        with self.connect() as conn:
            rows = conn.execute(
                """SELECT source_key, provider, completed_at, outcome, retryable,
                          error_category, error, metrics_json
                   FROM scrape_runs ORDER BY source_key, completed_at DESC, id DESC"""
            ).fetchall()
            checkpoints = {
                str(row[0]): str(row[1])
                for row in conn.execute(
                    "SELECT source_key, last_success_at FROM checkpoints"
                ).fetchall()
            }
        grouped: dict[str, list[sqlite3.Row]] = {}
        for row in rows:
            grouped.setdefault(str(row[0]), []).append(row)
        health: list[dict[str, object]] = []
        healthy = {"healthy", "healthy-empty", "capped"}
        for source_key, source_rows in sorted(grouped.items()):
            latest = source_rows[0]
            problem_streak = 0
            for row in source_rows:
                if str(row[3]) in healthy:
                    break
                problem_streak += 1
            health.append(
                {
                    "source_key": source_key,
                    "provider": str(latest[1]),
                    "outcome": str(latest[3]),
                    "last_run_at": str(latest[2]),
                    "last_success_at": checkpoints.get(source_key),
                    "problem_streak": problem_streak,
                    "retryable": bool(latest[4]),
                    "error_category": latest[5],
                    "error": latest[6],
                    "metrics": json.loads(str(latest[7])),
                }
            )
        return health

    def active_inventory(self) -> list[dict[str, object]]:
        """Return the stable, consumer-facing active inventory projection."""
        with self.connect() as conn:
            rows = conn.execute(
                """SELECT j.id, j.display_company AS company, j.display_title AS title,
                          j.location, j.employment_type, j.salary_min, j.salary_max,
                          j.salary_currency, j.salary_interval, j.posted_at,
                          j.first_seen_at, j.last_seen_at, j.status,
                          j.description_text, j.description_hash, j.description_quality,
                          COALESCE(GROUP_CONCAT(DISTINCT wm.mode), 'unknown') AS work_modes,
                          COALESCE(GROUP_CONCAT(DISTINCT o.provider), '') AS providers,
                          COALESCE(NULLIF(j.canonical_apply_url, ''),
                                   MAX(NULLIF(o.direct_apply_url, '')),
                                   MAX(o.source_url), '') AS url
                   FROM jobs j
                   LEFT JOIN job_work_modes wm ON wm.job_id=j.id
                   LEFT JOIN job_observation_links l ON l.job_id=j.id
                   LEFT JOIN observations o ON o.id=l.observation_id
                   WHERE j.status IN ('active','reopened')
                   GROUP BY j.id
                   ORDER BY COALESCE(j.posted_at, j.first_seen_at) DESC, j.id"""
            ).fetchall()
        inventory: list[dict[str, object]] = []
        for row in rows:
            item = dict(row)
            item["work_modes"] = sorted(set(str(item["work_modes"]).split(",")))
            item["providers"] = sorted(filter(None, set(str(item["providers"]).split(","))))
            inventory.append(item)
        return inventory

    def application_candidates(self, job_ids: set[str]) -> list[dict[str, object]]:
        """Return stable identity fields for legacy applied-job migration."""
        if not job_ids:
            return []
        placeholders = ",".join("?" for _ in job_ids)
        with self.connect() as conn:
            rows = conn.execute(
                f"""SELECT j.id, j.display_company AS company, j.display_title AS role,
                            COALESCE(NULLIF(j.canonical_apply_url, ''),
                                     MAX(NULLIF(o.direct_apply_url, '')),
                                     MAX(o.source_url), '') AS url
                     FROM jobs j
                     LEFT JOIN job_observation_links l ON l.job_id=j.id
                     LEFT JOIN observations o ON o.id=l.observation_id
                     WHERE j.id IN ({placeholders})
                     GROUP BY j.id ORDER BY j.id""",
                tuple(sorted(job_ids)),
            ).fetchall()
        return [dict(row) for row in rows]

    def refresh_possible_reposts(
        self,
        *,
        window_days: int = 90,
        min_span_days: int = 1,
        aggregator_companies: set[str] | None = None,
    ) -> list[dict[str, object]]:
        """Derive conservative same-company, same-title repost relationships."""
        if window_days < 1 or min_span_days < 1 or min_span_days > window_days:
            raise ValueError("repost span must be positive and no greater than the window")
        aggregators = {normalized_key(value) for value in (aggregator_companies or set())}
        with self.connect() as conn:
            rows = conn.execute(
                """SELECT j.id, j.normalized_company, j.normalized_title, j.display_company,
                          j.display_title, j.first_seen_at,
                          COALESCE(NULLIF(j.canonical_apply_url, ''), MAX(o.canonical_source_url), '')
                             AS representative_url,
                          GROUP_CONCAT(DISTINCT COALESCE(NULLIF(o.provider_job_id, ''),
                                                        o.canonical_source_url)) AS identities,
                          j.status, j.closed_at
                   FROM jobs j
                   LEFT JOIN job_observation_links l ON l.job_id=j.id
                   LEFT JOIN observations o ON o.id=l.observation_id
                   GROUP BY j.id
                   ORDER BY j.first_seen_at, j.id"""
            ).fetchall()
            candidates: list[dict[str, object]] = []
            for left_index, earlier in enumerate(rows):
                if str(earlier[1]) in aggregators:
                    continue
                earlier_seen = datetime.fromisoformat(str(earlier[5]))
                earlier_tokens = frozenset(str(earlier[2]).split())
                if not earlier_tokens:
                    continue
                for later in rows[left_index + 1 :]:
                    if earlier[1] != later[1]:
                        continue
                    if earlier_tokens != frozenset(str(later[2]).split()):
                        continue
                    later_seen = datetime.fromisoformat(str(later[5]))
                    gap = (later_seen.date() - earlier_seen.date()).days
                    if gap < min_span_days or gap > window_days:
                        continue
                    if earlier[8] != "closed" or not earlier[9]:
                        continue
                    closed_at = datetime.fromisoformat(str(earlier[9]))
                    if closed_at > later_seen:
                        continue
                    earlier_identities = set(str(earlier[7] or "").split(","))
                    later_identities = set(str(later[7] or "").split(","))
                    if earlier_identities & later_identities:
                        continue
                    if earlier[6] and later[6] and earlier[6] == later[6]:
                        continue
                    candidates.append(
                        {
                            "earlier_job_id": str(earlier[0]),
                            "later_job_id": str(later[0]),
                            "company": str(later[3]),
                            "title": str(later[4]),
                            "first_seen_gap_days": gap,
                            "reason": (
                                "same employer and exact title-token identity under a new posting "
                                "identity after the earlier posting closed"
                            ),
                            "confidence": 0.85,
                        }
                    )
            conn.execute("DELETE FROM possible_reposts")
            detected_at = _iso(datetime.now(UTC))
            conn.executemany(
                """INSERT INTO possible_reposts(
                       earlier_job_id, later_job_id, reason, confidence,
                       first_seen_gap_days, detected_at
                   ) VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    (
                        item["earlier_job_id"],
                        item["later_job_id"],
                        item["reason"],
                        item["confidence"],
                        item["first_seen_gap_days"],
                        detected_at,
                    )
                    for item in candidates
                ),
            )
        return candidates
