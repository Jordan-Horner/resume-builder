"""Schedule private job discovery, Gmail reconciliation, and notifications."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import logging
import os
import signal
import sqlite3
import sys
import tempfile
import threading
import traceback
import uuid
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any, ClassVar, cast
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
import yaml

from job_puller.config import load_config as load_job_config

from . import gmail_automation, jobs
from .agent_config import DEFAULT_AGENT_CONFIG, load_agent_config
from .agent_openrouter import OpenRouterAdapter
from .atomic import atomic_write_text
from .job_screening_queue import (
    DEFAULT_SCREENING_OUTPUT,
    build_screening_queue,
    load_notification_jobs,
)

DEFAULT_CONFIG = Path("automation/config.yml")
DEFAULT_JOB_TIMES = ("08:00",)
DEFAULT_GMAIL_INTERVAL_HOURS = 4
DEFAULT_NOTIFICATION_RETRY_MINUTES = 5
DEFAULT_HEARTBEAT_HOURS = 6
TASKS = ("jobs", "gmail")
LOG_FORMAT_VERSION = 1
LOGGER = logging.getLogger("resume_builder.automation")
LOG_SUMMARY_FIELDS = {
    "jobs": (
        "refresh_status",
        "new_jobs",
        "reviewable_jobs",
        "screened_jobs",
        "recommended_jobs",
        "needs_review_jobs",
        "screening_status",
    ),
    "gmail": (
        "examined",
        "created",
        "linked",
        "rejected",
        "recruiter_contacts",
        "interviews",
        "assessments",
        "offers",
        "ignored",
        "ambiguous",
        "duplicates",
    ),
}


@dataclass(frozen=True)
class JobSchedule:
    enabled: bool
    times: tuple[time, ...]
    run_on_start: bool
    limit: int
    semantic_screening_enabled: bool = False
    semantic_screening_max_jobs: int = 6


@dataclass(frozen=True)
class GmailSchedule:
    enabled: bool
    every: timedelta
    run_on_start: bool


@dataclass(frozen=True)
class NotificationConfig:
    sink: str
    privacy: str
    webhook_env: str
    max_items: int
    quiet_start: time | None
    quiet_end: time | None


@dataclass(frozen=True)
class AutomationConfig:
    timezone: ZoneInfo
    jobs: JobSchedule
    gmail: GmailSchedule
    notifications: NotificationConfig


@dataclass(frozen=True)
class Notification:
    key: str
    title: str
    body: str
    priority: str = "normal"


class TaskExecutionError(RuntimeError):
    """Carry a content-free stage and category across one task boundary."""

    def __init__(self, stage: str, cause: BaseException):
        super().__init__(stage)
        self.stage = stage
        self.error_category = _safe_error(cause)


class _MaxLevelFilter(logging.Filter):
    def __init__(self, maximum: int):
        super().__init__()
        self.maximum = maximum

    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno <= self.maximum


class _DockerLogFormatter(logging.Formatter):
    """Render one stable JSON object per container-log line."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "level": record.levelname,
            "event": record.getMessage(),
            "log_version": LOG_FORMAT_VERSION,
        }
        fields = getattr(record, "event_fields", None)
        if isinstance(fields, dict):
            payload.update(fields)
        return json.dumps(payload, separators=(",", ":"), sort_keys=False)


class _ReadableLogFormatter(logging.Formatter):
    """Render compact operational events for an interactive container log."""

    EVENT_LABELS: ClassVar[dict[str, str]] = {
        "notification_delivered": "Notification delivered",
        "notification_failed": "Notification failed",
        "scan_completed": "Scan completed",
        "scan_failed": "Scan failed",
        "scan_scheduled": "Next scan scheduled",
        "scan_started": "Scan started",
        "schedule_updated": "Schedule updated",
        "service_heartbeat": "Service healthy",
        "service_start_failed": "Service failed to start",
        "service_started": "Service started",
        "service_stopped": "Service stopped",
    }

    @staticmethod
    def _value(value: object) -> str:
        if isinstance(value, bool):
            return "yes" if value else "no"
        if isinstance(value, str) and "T" in value:
            try:
                parsed = datetime.fromisoformat(value)
            except ValueError:
                pass
            else:
                return parsed.strftime("%b %d, %Y %I:%M %p %z").replace(" 0", " ")
        return str(value)

    @classmethod
    def _schedule(cls, fields: dict[str, object], task: str) -> str:
        if not fields.get(f"{task}_enabled", False):
            return f"{task}=off"
        previous = cls._value(fields.get(f"{task}_previous", "never"))
        upcoming = cls._value(fields.get(f"{task}_next", "unknown"))
        return f"{task}=on (last {previous}; next {upcoming})"

    def format(self, record: logging.LogRecord) -> str:
        event = record.getMessage()
        label = self.EVENT_LABELS.get(event, event.replace("_", " ").capitalize())
        fields = getattr(record, "event_fields", None)
        if not isinstance(fields, dict):
            fields = {}
        visible = dict(fields)
        details: list[str] = []
        if event in {"service_started", "service_heartbeat"}:
            state = visible.pop("state", None)
            if state:
                label = f"{label} ({state})"
            details.extend(
                [
                    self._schedule(visible, "jobs"),
                    self._schedule(visible, "gmail"),
                ]
            )
            for task in TASKS:
                for suffix in ("enabled", "previous", "next"):
                    visible.pop(f"{task}_{suffix}", None)
        for key, value in visible.items():
            details.append(f"{key}={self._value(value)}")
        prefix = f"{record.levelname:<7} {label}"
        return f"{prefix} | {' | '.join(details)}" if details else prefix


def _configure_logging() -> None:
    level_name = os.environ.get("RESUME_BUILDER_LOG_LEVEL", "INFO").upper()
    configured_level = getattr(logging, level_name, None)
    invalid_level = not isinstance(configured_level, int) or level_name not in {
        "DEBUG",
        "INFO",
        "WARNING",
        "ERROR",
    }
    level = logging.INFO if invalid_level else cast(int, configured_level)
    format_name = os.environ.get("RESUME_BUILDER_LOG_FORMAT", "text").lower()
    invalid_format = format_name not in {"text", "json"}
    for handler in LOGGER.handlers[:]:
        LOGGER.removeHandler(handler)
        handler.close()
    LOGGER.propagate = False
    LOGGER.setLevel(level)
    formatter: logging.Formatter = (
        _DockerLogFormatter() if format_name == "json" else _ReadableLogFormatter()
    )
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setLevel(level)
    stdout_handler.addFilter(_MaxLevelFilter(logging.INFO))
    stdout_handler.setFormatter(formatter)
    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setLevel(max(level, logging.WARNING))
    stderr_handler.setFormatter(formatter)
    LOGGER.addHandler(stdout_handler)
    LOGGER.addHandler(stderr_handler)
    if invalid_level:
        raise ValueError("RESUME_BUILDER_LOG_LEVEL must be DEBUG, INFO, WARNING, or ERROR")
    if invalid_format:
        raise ValueError("RESUME_BUILDER_LOG_FORMAT must be text or json")


def _log(level: int, event: str, **fields: object) -> None:
    LOGGER.log(level, event, extra={"event_fields": fields})


def _safe_stack(exc: BaseException) -> str:
    root = exc.__cause__ or exc
    frames = traceback.extract_tb(root.__traceback__)
    return ">".join(f"{Path(frame.filename).name}:{frame.lineno}:{frame.name}" for frame in frames)


def _package_version() -> str:
    try:
        return version("resume-builder")
    except PackageNotFoundError:
        return "unknown"


def default_state_path() -> Path:
    """Return the external operational-state path."""
    override = os.environ.get("RESUME_BUILDER_AUTOMATION_STATE")
    if override:
        return Path(override).expanduser()
    return gmail_automation.default_state_path().with_name("automation-state.sqlite")


def _mapping(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a mapping")
    return value


def _boolean(payload: dict[str, Any], key: str, default: bool) -> bool:
    value = payload.get(key, default)
    if not isinstance(value, bool):
        raise ValueError(f"{key} must be true or false")
    return value


def _parse_job_times(values: object) -> tuple[time, ...]:
    if not isinstance(values, list) or not values:
        raise ValueError("jobs.times must contain at least one HH:MM value")
    parsed: set[time] = set()
    for value in values:
        if not isinstance(value, str) or len(value) != 5:
            raise ValueError("jobs.times values must use HH:MM")
        try:
            parsed.add(time.fromisoformat(value))
        except ValueError as exc:
            raise ValueError(f"invalid jobs.times value: {value}") from exc
    return tuple(sorted(parsed))


def _parse_clock(value: object, label: str) -> time:
    if not isinstance(value, str) or len(value) != 5:
        raise ValueError(f"{label} must use HH:MM")
    try:
        return time.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"invalid {label}: {value}") from exc


def load_config(path: Path) -> AutomationConfig:
    """Load and strictly validate one private automation configuration."""
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(
            f"automation configuration not found: {path}; run `resume-builder automation init`"
        ) from exc
    except yaml.YAMLError as exc:
        raise ValueError(f"invalid automation YAML: {exc}") from exc
    payload = _mapping(raw, "automation configuration")
    allowed = {"schema_version", "timezone", "jobs", "gmail", "notifications"}
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise ValueError(f"unknown automation settings: {', '.join(unknown)}")
    if payload.get("schema_version") != 1:
        raise ValueError("automation schema_version must be 1")
    timezone_name = payload.get("timezone")
    if not isinstance(timezone_name, str) or not timezone_name:
        raise ValueError("timezone must be an IANA timezone name")
    try:
        timezone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"unknown timezone: {timezone_name}") from exc

    job_payload = _mapping(payload.get("jobs", {}), "jobs")
    gmail_payload = _mapping(payload.get("gmail", {}), "gmail")
    notification_payload = _mapping(payload.get("notifications", {}), "notifications")
    for section, values, allowed_keys in (
        (
            "jobs",
            job_payload,
            {"enabled", "times", "run_on_start", "limit", "semantic_screening"},
        ),
        ("gmail", gmail_payload, {"enabled", "every_hours", "run_on_start"}),
        (
            "notifications",
            notification_payload,
            {"sink", "privacy", "webhook_env", "max_items", "quiet_hours"},
        ),
    ):
        extra = sorted(set(values) - allowed_keys)
        if extra:
            raise ValueError(f"unknown {section} settings: {', '.join(extra)}")

    job_limit = job_payload.get("limit", 50)
    if not isinstance(job_limit, int) or isinstance(job_limit, bool) or not 1 <= job_limit <= 500:
        raise ValueError("jobs.limit must be an integer from 1 to 500")
    screening_payload = _mapping(
        job_payload.get("semantic_screening", {}), "jobs.semantic_screening"
    )
    screening_extra = sorted(set(screening_payload) - {"enabled", "max_jobs_per_run"})
    if screening_extra:
        raise ValueError("unknown jobs.semantic_screening settings: " + ", ".join(screening_extra))
    screening_limit = screening_payload.get("max_jobs_per_run", 6)
    if (
        not isinstance(screening_limit, int)
        or isinstance(screening_limit, bool)
        or not 1 <= screening_limit <= 25
    ):
        raise ValueError("jobs.semantic_screening.max_jobs_per_run must be from 1 to 25")
    interval = gmail_payload.get("every_hours", DEFAULT_GMAIL_INTERVAL_HOURS)
    if (
        not isinstance(interval, int | float)
        or isinstance(interval, bool)
        or not 1 <= interval <= 168
    ):
        raise ValueError("gmail.every_hours must be from 1 to 168")
    sink = notification_payload.get("sink", "console")
    if sink not in {"console", "discord", "disabled"}:
        raise ValueError("notifications.sink must be console, discord, or disabled")
    privacy = notification_payload.get("privacy", "summary")
    if privacy not in {"counts-only", "summary"}:
        raise ValueError("notifications.privacy must be counts-only or summary")
    webhook_env = notification_payload.get("webhook_env", "RESUME_BUILDER_DISCORD_WEBHOOK")
    if not isinstance(webhook_env, str) or not webhook_env:
        raise ValueError("notifications.webhook_env must name an environment variable")
    max_items = notification_payload.get("max_items", 10)
    if not isinstance(max_items, int) or isinstance(max_items, bool) or not 1 <= max_items <= 25:
        raise ValueError("notifications.max_items must be an integer from 1 to 25")
    quiet_payload = notification_payload.get("quiet_hours")
    quiet_start: time | None = None
    quiet_end: time | None = None
    if quiet_payload is not None:
        quiet = _mapping(quiet_payload, "notifications.quiet_hours")
        if set(quiet) != {"start", "end"}:
            raise ValueError("notifications.quiet_hours requires only start and end")
        quiet_start = _parse_clock(quiet["start"], "notifications.quiet_hours.start")
        quiet_end = _parse_clock(quiet["end"], "notifications.quiet_hours.end")

    return AutomationConfig(
        timezone=timezone,
        jobs=JobSchedule(
            enabled=_boolean(job_payload, "enabled", True),
            times=_parse_job_times(job_payload.get("times", list(DEFAULT_JOB_TIMES))),
            run_on_start=_boolean(job_payload, "run_on_start", True),
            limit=job_limit,
            semantic_screening_enabled=_boolean(screening_payload, "enabled", False),
            semantic_screening_max_jobs=screening_limit,
        ),
        gmail=GmailSchedule(
            enabled=_boolean(gmail_payload, "enabled", True),
            every=timedelta(hours=float(interval)),
            run_on_start=_boolean(gmail_payload, "run_on_start", True),
        ),
        notifications=NotificationConfig(
            sink=str(sink),
            privacy=str(privacy),
            webhook_env=webhook_env,
            max_items=max_items,
            quiet_start=quiet_start,
            quiet_end=quiet_end,
        ),
    )


def render_default_config(
    timezone: str,
    *,
    jobs_enabled: bool = True,
    gmail_enabled: bool = True,
) -> str:
    """Render a human-editable low-noise default configuration."""
    jobs_value = str(jobs_enabled).lower()
    gmail_value = str(gmail_enabled).lower()
    return f"""\
schema_version: 1
timezone: {timezone}

jobs:
  enabled: {jobs_value}
  times: [\"08:00\"]
  run_on_start: true
  limit: 50
  semantic_screening:
    # Enabling this authorizes bounded posting/profile packets to be sent to
    # the provider configured in agent/config.yml on every job run.
    enabled: false
    max_jobs_per_run: 6

gmail:
  enabled: {gmail_value}
  every_hours: 4
  run_on_start: true

notifications:
  # Change to discord after setting RESUME_BUILDER_DISCORD_WEBHOOK.
  sink: console
  privacy: summary
  webhook_env: RESUME_BUILDER_DISCORD_WEBHOOK
  max_items: 10
  quiet_hours:
    start: "21:00"
    end: "07:00"
"""


def config_payload(config: AutomationConfig) -> dict[str, object]:
    """Serialize configuration without including notification credentials."""
    notifications: dict[str, object] = {
        "sink": config.notifications.sink,
        "privacy": config.notifications.privacy,
        "webhook_env": config.notifications.webhook_env,
        "max_items": config.notifications.max_items,
    }
    if config.notifications.quiet_start is not None and config.notifications.quiet_end is not None:
        notifications["quiet_hours"] = {
            "start": config.notifications.quiet_start.strftime("%H:%M"),
            "end": config.notifications.quiet_end.strftime("%H:%M"),
        }
    return {
        "schema_version": 1,
        "timezone": str(config.timezone),
        "jobs": {
            "enabled": config.jobs.enabled,
            "times": [value.strftime("%H:%M") for value in config.jobs.times],
            "run_on_start": config.jobs.run_on_start,
            "limit": config.jobs.limit,
            "semantic_screening": {
                "enabled": config.jobs.semantic_screening_enabled,
                "max_jobs_per_run": config.jobs.semantic_screening_max_jobs,
            },
        },
        "gmail": {
            "enabled": config.gmail.enabled,
            "every_hours": config.gmail.every.total_seconds() / 3600,
            "run_on_start": config.gmail.run_on_start,
        },
        "notifications": notifications,
    }


def configure(
    path: Path,
    config: AutomationConfig,
    *,
    timezone: str | None,
    job_times: list[str] | None,
    gmail_hours: float | None,
    notification_sink: str | None,
    privacy: str | None,
    job_enabled: bool | None = None,
) -> AutomationConfig:
    """Apply explicit schedule changes and revalidate the resulting file."""
    payload = config_payload(config)
    if timezone is not None:
        payload["timezone"] = timezone
    job_payload = _mapping(payload["jobs"], "jobs")
    if job_enabled is not None:
        job_payload["enabled"] = job_enabled
    if job_times:
        job_payload["times"] = job_times
    gmail_payload = _mapping(payload["gmail"], "gmail")
    if gmail_hours is not None:
        gmail_payload["every_hours"] = gmail_hours
    notification_payload = _mapping(payload["notifications"], "notifications")
    if notification_sink is not None:
        notification_payload["sink"] = notification_sink
    if privacy is not None:
        notification_payload["privacy"] = privacy
    rendered = yaml.safe_dump(payload, sort_keys=False)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(rendered)
        validated = load_config(temporary)
        atomic_write_text(path, rendered)
        return validated
    finally:
        temporary.unlink(missing_ok=True)


class AutomationState:
    """External task history and content-limited notification outbox."""

    def __init__(self, path: Path):
        self.path = path.expanduser().resolve()

    @contextmanager
    def locked(self, service: str | None = None) -> Iterator[None]:
        suffix = f".{service}.lock" if service else ".lock"
        lock_path = self.path.with_suffix(f"{self.path.suffix}{suffix}")
        lock_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with lock_path.open("a+", encoding="utf-8") as stream:
            os.chmod(lock_path, 0o600)
            try:
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise ValueError("another Resume Builder automation service is running") from exc
            try:
                yield
            finally:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor = os.open(self.path, os.O_WRONLY | os.O_CREAT, 0o600)
        os.close(descriptor)
        os.chmod(self.path, 0o600)

        with sqlite3.connect(self.path) as connection:
            connection.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS task_runs(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    finished_at TEXT NOT NULL,
                    status TEXT NOT NULL,
                    summary_json TEXT NOT NULL,
                    error_category TEXT
                );
                CREATE TABLE IF NOT EXISTS notification_outbox(
                    notification_key TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    body TEXT NOT NULL,
                    priority TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    delivered_at TEXT,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT
                );
                CREATE TABLE IF NOT EXISTS service_runtime(
                    singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
                    running INTEGER NOT NULL CHECK(running IN (0, 1)),
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS service_heartbeats(
                    service TEXT PRIMARY KEY,
                    running INTEGER NOT NULL CHECK(running IN (0, 1)),
                    updated_at TEXT NOT NULL
                );
                """
            )
        os.chmod(self.path, 0o600)

    def service_is_running(self, *, service: str | None = None) -> bool:
        """Return whether the scheduler has a fresh heartbeat or holds its lock."""
        if self.path.is_file():
            try:
                with sqlite3.connect(self.path) as connection:
                    if service:
                        row = connection.execute(
                            "SELECT running, updated_at FROM service_heartbeats WHERE service = ?",
                            (service,),
                        ).fetchone()
                    else:
                        row = connection.execute(
                            "SELECT running, updated_at FROM service_runtime WHERE singleton = 1"
                        ).fetchone()
                if row is not None:
                    updated_at = datetime.fromisoformat(str(row[1]))
                    if bool(row[0]) and datetime.now(UTC) - updated_at <= timedelta(minutes=2):
                        return True
                    if not bool(row[0]):
                        return False
            except (OSError, sqlite3.Error, ValueError):
                LOGGER.debug("scheduler heartbeat unavailable; falling back to lock", exc_info=True)
        suffix = f".{service}.lock" if service else ".lock"
        lock_path = self.path.with_suffix(f"{self.path.suffix}{suffix}")
        if not lock_path.is_file():
            return False
        with lock_path.open("r+", encoding="utf-8") as stream:
            try:
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return True
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        return False

    def record_service_heartbeat(self, *, running: bool, service: str | None = None) -> None:
        """Persist a content-free scheduler heartbeat for portable liveness checks."""
        if not self.path.is_file():
            self.initialize()
        with sqlite3.connect(self.path) as connection:
            if service:
                connection.execute(
                    """
                    INSERT INTO service_heartbeats(service, running, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(service) DO UPDATE SET
                        running = excluded.running,
                        updated_at = excluded.updated_at
                    """,
                    (service, int(running), datetime.now(UTC).isoformat()),
                )
            else:
                connection.execute(
                    """
                    INSERT INTO service_runtime(singleton, running, updated_at)
                    VALUES (1, ?, ?)
                    ON CONFLICT(singleton) DO UPDATE SET
                        running = excluded.running,
                        updated_at = excluded.updated_at
                    """,
                    (int(running), datetime.now(UTC).isoformat()),
                )

    def record_run(
        self,
        task: str,
        started_at: datetime,
        status: str,
        summary: dict[str, object],
        error_category: str | None = None,
    ) -> None:
        self.initialize()
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                """INSERT INTO task_runs(
                       task, started_at, finished_at, status, summary_json, error_category
                   ) VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    task,
                    started_at.astimezone(UTC).isoformat(),
                    datetime.now(UTC).isoformat(),
                    status,
                    json.dumps(summary, sort_keys=True),
                    error_category,
                ),
            )

    def last_run(self, task: str) -> dict[str, object] | None:
        if not self.path.is_file():
            return None
        with sqlite3.connect(self.path) as connection:
            row = connection.execute(
                """SELECT started_at, finished_at, status, summary_json, error_category
                   FROM task_runs WHERE task=? ORDER BY id DESC LIMIT 1""",
                (task,),
            ).fetchone()
        if row is None:
            return None
        return {
            "started_at": row[0],
            "finished_at": row[1],
            "status": row[2],
            "summary": json.loads(row[3]),
            "error_category": row[4],
        }

    def enqueue(self, notification: Notification) -> None:
        self.initialize()
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                """INSERT OR IGNORE INTO notification_outbox(
                       notification_key, title, body, priority, created_at
                   ) VALUES (?, ?, ?, ?, ?)""",
                (
                    notification.key,
                    notification.title,
                    notification.body,
                    notification.priority,
                    datetime.now(UTC).isoformat(),
                ),
            )

    def pending_notifications(self) -> list[Notification]:
        if not self.path.is_file():
            return []
        with sqlite3.connect(self.path) as connection:
            rows = connection.execute(
                """SELECT notification_key, title, body, priority
                   FROM notification_outbox WHERE delivered_at IS NULL ORDER BY created_at"""
            ).fetchall()
        return [Notification(*map(str, row)) for row in rows]

    def delivery_succeeded(self, key: str) -> None:
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                """UPDATE notification_outbox
                   SET delivered_at=?, attempts=attempts+1, last_error=NULL
                   WHERE notification_key=?""",
                (datetime.now(UTC).isoformat(), key),
            )

    def delivery_failed(self, key: str, error: str) -> None:
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                """UPDATE notification_outbox
                   SET attempts=attempts+1, last_error=? WHERE notification_key=?""",
                (error[:200], key),
            )

    def status(self) -> dict[str, object]:
        pending = 0
        if self.path.is_file():
            with sqlite3.connect(self.path) as connection:
                pending = int(
                    connection.execute(
                        "SELECT COUNT(*) FROM notification_outbox WHERE delivered_at IS NULL"
                    ).fetchone()[0]
                )
        return {
            "state_path": str(self.path),
            "tasks": {task: self.last_run(task) for task in TASKS},
            "pending_notifications": pending,
        }


def _safe_error(exc: BaseException) -> str:
    return exc.__class__.__name__


def _notification_key(prefix: str, identities: Sequence[str]) -> str:
    digest = hashlib.sha256("\n".join(sorted(identities)).encode()).hexdigest()[:20]
    return f"{prefix}:{digest}"


def _reviewable_jobs(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    reviewable = []
    for item in payload.get("jobs", []):
        if not isinstance(item, dict):
            continue
        prescreen = item.get("prescreen")
        constraints = prescreen.get("constraints") if isinstance(prescreen, dict) else None
        disposition = constraints.get("disposition") if isinstance(constraints, dict) else None
        if not disposition:
            reviewable.append(item)
    return reviewable


def job_notification(
    matches: list[dict[str, Any]], config: NotificationConfig
) -> Notification | None:
    if not matches:
        return None
    identities = [str(item.get("id", "")) for item in matches]
    completed = []
    unresolved = 0
    for item in matches:
        screen = item.get("screening")
        if isinstance(screen, dict) and screen.get("status") == "complete":
            result = screen.get("result")
            if isinstance(result, dict):
                completed.append(result)
                continue
        unresolved += 1
    recommended = sum(
        str(result.get("recommendation")) in {"pursue", "pursue_as_stretch"} for result in completed
    )
    verify = sum(str(result.get("recommendation")) == "verify_eligibility" for result in completed)
    needs_review = unresolved + verify
    additional = max(0, len(matches) - recommended - needs_review)
    overview = (
        f"{recommended} recommended; {needs_review} need review or screening; "
        f"{additional} additional."
    )
    if config.privacy == "counts-only":
        body = f"{len(matches)} new job(s). {overview}"
    else:
        lines = []
        for item in matches[: config.max_items]:
            screen = item.get("screening")
            note = ""
            if isinstance(screen, dict) and screen.get("status") == "complete":
                result = screen.get("result")
                if isinstance(result, dict):
                    fit = str(result.get("fit") or "unknown").replace("_", " ")
                    confidence = str(result.get("confidence") or "unknown")
                    note = f" — {fit}, {confidence} confidence"
            elif isinstance(screen, dict):
                note = f" — {str(screen.get('status') or 'unscreened').replace('_', ' ')}"
            else:
                note = " — unscreened"
            url = str(item.get("url") or "")
            link = f" — {url}" if url.startswith(("https://", "http://")) else ""
            lines.append(f"• {item.get('title')} at {item.get('company')}{note}{link}")
        remaining = len(matches) - len(lines)
        if remaining:
            lines.append(f"• …and {remaining} more")
        body = f"{len(matches)} new job(s). {overview}\n" + "\n".join(lines)
    return Notification(
        key=_notification_key("jobs", identities),
        title="Resume Builder found new jobs",
        body=body,
    )


def gmail_notification(
    result: dict[str, object], config: NotificationConfig
) -> Notification | None:
    raw_changes = result.get("changes", [])
    changes = (
        [item for item in raw_changes if isinstance(item, dict)]
        if isinstance(raw_changes, list)
        else []
    )
    if not changes:
        return None
    identities = [
        f"{item.get('application_id')}:{item.get('action')}:{item.get('effective_on', item.get('applied_on', ''))}"
        for item in changes
    ]
    urgent = any(item.get("action") in {"interview", "assessment", "offer"} for item in changes)
    if config.privacy == "counts-only":
        body = f"{len(changes)} application update(s) were recorded."
    else:
        lines = [
            f"• {str(item.get('action', 'updated')).replace('_', ' ').title()}: "
            f"{item.get('role')} at {item.get('company')}"
            for item in changes[: config.max_items]
        ]
        remaining = len(changes) - len(lines)
        if remaining:
            lines.append(f"• …and {remaining} more")
        body = f"{len(changes)} application update(s):\n" + "\n".join(lines)
    return Notification(
        key=_notification_key("gmail", identities),
        title="Important application update" if urgent else "Application tracker updated",
        body=body,
        priority="high" if urgent else "normal",
    )


def failure_notification(task: str, occurred_at: datetime) -> Notification:
    """Build one generic daily health alert after repeated task failures."""
    return Notification(
        key=f"health:{task}:{occurred_at.astimezone(UTC).date().isoformat()}",
        title="Resume Builder automation needs attention",
        body=f"The {task} scanner failed three consecutive attempts. Check automation status.",
        priority="high",
    )


def _discord_url(config: NotificationConfig) -> str:
    value = os.environ.get(config.webhook_env, "")
    parsed = urlparse(value)
    if parsed.scheme != "https" or parsed.hostname not in {"discord.com", "discordapp.com"}:
        raise ValueError(f"{config.webhook_env} must contain an HTTPS Discord webhook URL")
    if not parsed.path.startswith("/api/webhooks/"):
        raise ValueError(f"{config.webhook_env} is not a Discord webhook URL")
    return value


def deliver(notification: Notification, config: NotificationConfig) -> None:
    """Deliver one content-limited notification without exposing its credential."""
    message = f"**{notification.title}**\n{notification.body}"
    if config.sink == "disabled":
        return
    if config.sink == "console":
        print(f"\n{notification.title}\n{notification.body}", flush=True)
        return
    response = httpx.post(
        _discord_url(config),
        json={"content": message[:2000], "allowed_mentions": {"parse": []}},
        timeout=15,
    )
    response.raise_for_status()


def _ensure_external(path: Path, workspace: Path) -> Path:
    resolved = path.expanduser().resolve()
    if resolved == workspace or resolved.is_relative_to(workspace):
        raise ValueError("automation state must be outside the private workspace")
    engine = Path(__file__).resolve().parents[2]
    if resolved == engine or resolved.is_relative_to(engine):
        raise ValueError("automation state must be outside the Resume Builder engine")
    return resolved


def _run_jobs(config: AutomationConfig) -> dict[str, object]:
    if jobs.DEFAULT_CONFIG.is_file():
        try:
            discovery = load_job_config(jobs.DEFAULT_CONFIG)
        except ValueError as exc:
            raise TaskExecutionError("configure", exc) from exc
        if not discovery.enabled:
            return {
                "exit_code": 0,
                "refresh_status": "setup_required",
                "new_jobs": 0,
                "reviewable_jobs": 0,
                "screened_jobs": 0,
                "recommended_jobs": 0,
                "needs_review_jobs": 0,
                "screening_status": "disabled",
                "matches": [],
            }
    try:
        with Path(os.devnull).open("w", encoding="utf-8") as null_stream:
            with redirect_stdout(null_stream), redirect_stderr(null_stream):
                exit_code = jobs.main(["new", "--limit", str(config.jobs.limit)])
    except Exception as exc:
        raise TaskExecutionError("collect", exc) from exc
    manifest: dict[str, Any] = {}
    try:
        if jobs.DEFAULT_LATEST_REFRESH.is_file():
            manifest = json.loads(jobs.DEFAULT_LATEST_REFRESH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TaskExecutionError("publish", exc) from exc
    refresh_status = manifest.get("status")
    if refresh_status not in {"complete", "partial"}:
        stage = "publish" if refresh_status == "processing" else "collect"
        raise TaskExecutionError(stage, RuntimeError("job discovery did not finalize"))
    if not jobs.DEFAULT_NEW_OUTPUT.is_file():
        raise TaskExecutionError("publish", FileNotFoundError("new-job output was not published"))
    screening_status = "disabled"
    screened_jobs = 0
    recommended_jobs = 0
    needs_review_jobs = 0
    try:
        matches = _reviewable_jobs(jobs.DEFAULT_NEW_OUTPUT)
        if config.jobs.semantic_screening_enabled:
            try:
                agent_config = load_agent_config(DEFAULT_AGENT_CONFIG)
                screening_limit = min(
                    config.jobs.semantic_screening_max_jobs,
                    agent_config.limits.max_requests,
                )
                queue_summary = build_screening_queue(
                    adapter=OpenRouterAdapter(agent_config),
                    model=agent_config.models.fast,
                    cache_path=default_state_path().with_name("screening-cache.sqlite"),
                    max_provider_jobs=screening_limit,
                    allow_provider=True,
                )
                matches = load_notification_jobs(DEFAULT_SCREENING_OUTPUT)
                screening_status = "complete" if queue_summary.failed == 0 else "partial"
                screened_jobs = queue_summary.completed
                recommended_jobs = queue_summary.recommended
                needs_review_jobs = queue_summary.needs_review
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                screening_status = "unavailable"
                needs_review_jobs = len(matches)
                _log(
                    logging.WARNING,
                    "semantic_screening_unavailable",
                    stage="screen",
                    error_category=_safe_error(exc),
                )
        else:
            needs_review_jobs = len(matches)
    except (OSError, json.JSONDecodeError, TypeError) as exc:
        raise TaskExecutionError("match", exc) from exc
    return {
        "exit_code": exit_code,
        "refresh_status": refresh_status,
        "new_jobs": len(manifest.get("new_to_database_job_ids", [])),
        "reviewable_jobs": len(matches),
        "screened_jobs": screened_jobs,
        "recommended_jobs": recommended_jobs,
        "needs_review_jobs": needs_review_jobs,
        "screening_status": screening_status,
        "matches": matches,
    }


def _run_gmail(workspace: Path) -> dict[str, object]:
    state_path = Path(
        os.environ.get("RESUME_BUILDER_GMAIL_STATE", str(gmail_automation.default_state_path()))
    )
    state_path = _ensure_external(state_path, workspace)
    token_path = Path(
        os.environ.get(
            "RESUME_BUILDER_GMAIL_TOKEN",
            str(gmail_automation.default_token_path(state_path)),
        )
    ).expanduser()
    token_path = _ensure_external(token_path, workspace)
    try:
        gateway = gmail_automation.google_gateway(token_path)
    except Exception as exc:
        raise TaskExecutionError("authenticate", exc) from exc
    try:
        return gmail_automation.scan(
            gateway=gateway,
            state=gmail_automation.GmailRuntimeState(state_path),
            workspace=workspace,
            label=gmail_automation.DEFAULT_LABEL,
            query=gmail_automation.DEFAULT_SCAN_QUERY,
            backfill=False,
            apply=True,
        )
    except Exception as exc:
        raise TaskExecutionError("reconcile", exc) from exc


TaskRunner = Callable[[], dict[str, object]]


class AutomationService:
    def __init__(
        self,
        *,
        workspace: Path,
        config: AutomationConfig,
        state: AutomationState,
        config_path: Path | None = None,
        job_runner: TaskRunner | None = None,
        gmail_runner: TaskRunner | None = None,
    ):
        self.workspace = workspace
        self.config = config
        self.state = state
        self.config_path = config_path
        self._config_signature = self._current_config_signature()
        self.runners = {
            "jobs": job_runner,
            "gmail": gmail_runner,
        }

    def _current_config_signature(self) -> tuple[int, int] | None:
        if self.config_path is None:
            return None
        stat = self.config_path.stat()
        return stat.st_mtime_ns, stat.st_size

    def reload_config(self) -> bool:
        """Reload an atomically replaced config while the service remains online."""
        signature = self._current_config_signature()
        if signature == self._config_signature or self.config_path is None:
            return False
        self.config = load_config(self.config_path)
        self._config_signature = signature
        return True

    def run_task(self, task: str, *, trigger: str = "manual", attempt: int = 1) -> bool:
        started = datetime.now(UTC)
        run_id = uuid.uuid4().hex[:12]
        _log(
            logging.INFO,
            "scan_started",
            task=task,
            run_id=run_id,
            trigger=trigger,
            attempt=attempt,
        )
        try:
            runner = self.runners[task]
            if runner is not None:
                result = runner()
            elif task == "jobs":
                result = _run_jobs(self.config)
            else:
                result = _run_gmail(self.workspace)
            public_summary = {key: value for key, value in result.items() if key != "matches"}
            run_status = "partial" if result.get("refresh_status") == "partial" else "success"
            self.state.record_run(task, started, run_status, public_summary)
            raw_matches = result.get("matches", [])
            matches = (
                [item for item in raw_matches if isinstance(item, dict)]
                if isinstance(raw_matches, list)
                else []
            )
            notification = (
                job_notification(matches, self.config.notifications)
                if task == "jobs"
                else gmail_notification(result, self.config.notifications)
            )
            if notification is not None:
                self.state.enqueue(notification)
            summary_fields = {
                key: public_summary[key]
                for key in LOG_SUMMARY_FIELDS[task]
                if isinstance(public_summary.get(key), int | float | bool | str)
            }
            _log(
                logging.INFO,
                "scan_completed",
                task=task,
                run_id=run_id,
                trigger=trigger,
                attempt=attempt,
                status=run_status,
                stage="complete",
                duration_seconds=round((datetime.now(UTC) - started).total_seconds(), 3),
                **summary_fields,
            )
            return True
        except Exception as exc:
            category = (
                exc.error_category if isinstance(exc, TaskExecutionError) else _safe_error(exc)
            )
            stage = exc.stage if isinstance(exc, TaskExecutionError) else "task"
            self.state.record_run(task, started, "failed", {}, category)
            _log(
                logging.ERROR,
                "scan_failed",
                task=task,
                run_id=run_id,
                trigger=trigger,
                attempt=attempt,
                status="failed",
                stage=stage,
                error_category=category,
                duration_seconds=round((datetime.now(UTC) - started).total_seconds(), 3),
                stack=_safe_stack(exc),
            )
            return False

    def deliver_pending(self, now: datetime | None = None) -> bool:
        successful = True
        current = now or datetime.now(UTC)
        for notification in self.state.pending_notifications():
            if notification.priority != "high" and _in_quiet_hours(
                current, self.config.timezone, self.config.notifications
            ):
                continue
            try:
                deliver(notification, self.config.notifications)
                self.state.delivery_succeeded(notification.key)
                _log(
                    logging.INFO,
                    "notification_delivered",
                    stage="notify",
                    sink=self.config.notifications.sink,
                    priority=notification.priority,
                )
            except Exception as exc:
                successful = False
                category = _safe_error(exc)
                self.state.delivery_failed(notification.key, category)
                _log(
                    logging.ERROR,
                    "notification_failed",
                    stage="notify",
                    error_category=category,
                    stack=_safe_stack(exc),
                )
        return successful

    def run_once(self, tasks: Sequence[str]) -> bool:
        task_results = [self.run_task(task, trigger="manual") for task in tasks]
        notifications_delivered = self.deliver_pending()
        return all(task_results) and notifications_delivered


def _last_finished(state: AutomationState, task: str) -> datetime | None:
    last = state.last_run(task)
    if last is None or not isinstance(last.get("finished_at"), str):
        return None
    return datetime.fromisoformat(str(last["finished_at"])).astimezone(UTC)


def _in_quiet_hours(now: datetime, timezone: ZoneInfo, config: NotificationConfig) -> bool:
    if config.quiet_start is None or config.quiet_end is None:
        return False
    local_time = now.astimezone(timezone).time().replace(tzinfo=None)
    if config.quiet_start < config.quiet_end:
        return config.quiet_start <= local_time < config.quiet_end
    return local_time >= config.quiet_start or local_time < config.quiet_end


def next_job_run(now: datetime, schedule: JobSchedule, timezone: ZoneInfo) -> datetime:
    """Return the next configured local job time after *now*."""
    local = now.astimezone(timezone)
    for offset in range(0, 8):
        date = local.date() + timedelta(days=offset)
        for scheduled_time in schedule.times:
            candidate = datetime.combine(date, scheduled_time, timezone)
            if candidate > local:
                return candidate.astimezone(UTC)
    raise AssertionError("a daily job schedule must yield a next run")


def _jobs_due(now: datetime, config: AutomationConfig, state: AutomationState) -> bool:
    last = _last_finished(state, "jobs")
    if last is None:
        return config.jobs.run_on_start
    local_now = now.astimezone(config.timezone)
    candidates = [
        datetime.combine(local_now.date(), scheduled, config.timezone).astimezone(UTC)
        for scheduled in config.jobs.times
    ]
    latest_due = max((candidate for candidate in candidates if candidate <= now), default=None)
    return latest_due is not None and last < latest_due


def _gmail_due(now: datetime, config: AutomationConfig, state: AutomationState) -> bool:
    last = _last_finished(state, "gmail")
    return config.gmail.run_on_start if last is None else now >= last + config.gmail.every


def _local_timestamp(value: datetime, timezone: ZoneInfo) -> str:
    return value.astimezone(timezone).isoformat(timespec="minutes")


def _schedule_log_fields(service: AutomationService, due: dict[str, datetime]) -> dict[str, object]:
    fields: dict[str, object] = {"timezone": str(service.config.timezone)}
    for task, enabled in (
        ("jobs", service.config.jobs.enabled),
        ("gmail", service.config.gmail.enabled),
    ):
        fields[f"{task}_enabled"] = enabled
        if not enabled:
            continue
        previous = _last_finished(service.state, task)
        fields[f"{task}_previous"] = (
            _local_timestamp(previous, service.config.timezone) if previous else "never"
        )
        fields[f"{task}_next"] = _local_timestamp(due[task], service.config.timezone)
    return fields


def run_forever(
    service: AutomationService,
    stop: threading.Event,
    tasks: Sequence[str] = TASKS,
) -> int:
    """Run due tasks and retry pending alerts until asked to stop."""
    selected = tuple(dict.fromkeys(tasks))
    if not selected or any(task not in TASKS for task in selected):
        raise ValueError("automation service requires at least one valid task")
    service_name = selected[0] if len(selected) == 1 else "automation"
    with service.state.locked(service_name):
        service.state.initialize()
        service.state.record_service_heartbeat(running=True, service=service_name)
        now = datetime.now(UTC)
        job_last = _last_finished(service.state, "jobs")
        gmail_last = _last_finished(service.state, "gmail")
        due = {
            "jobs": (
                now
                if (job_last is None and service.config.jobs.run_on_start)
                or _jobs_due(now, service.config, service.state)
                else next_job_run(now, service.config.jobs, service.config.timezone)
            ),
            "gmail": (
                now
                if gmail_last is None and service.config.gmail.run_on_start
                else (
                    gmail_last + service.config.gmail.every
                    if gmail_last
                    else now + service.config.gmail.every
                )
            ),
        }
        _log(
            logging.INFO,
            "service_started",
            version=_package_version(),
            state=(
                "ready"
                if (service.config.jobs.enabled and due["jobs"] <= now)
                or (service.config.gmail.enabled and due["gmail"] <= now)
                else "waiting"
            ),
            **_schedule_log_fields(service, due),
        )
        failures = {task: 0 for task in TASKS}
        next_delivery = now
        next_heartbeat = now + timedelta(hours=DEFAULT_HEARTBEAT_HOURS)
        while not stop.is_set():
            service.state.record_service_heartbeat(running=True, service=service_name)
            now = datetime.now(UTC)
            if service.reload_config():
                job_last = _last_finished(service.state, "jobs")
                gmail_last = _last_finished(service.state, "gmail")
                due["jobs"] = next_job_run(now, service.config.jobs, service.config.timezone)
                due["gmail"] = (
                    gmail_last + service.config.gmail.every
                    if gmail_last and gmail_last + service.config.gmail.every > now
                    else now + service.config.gmail.every
                )
                _log(
                    logging.INFO,
                    "schedule_updated",
                    **_schedule_log_fields(service, due),
                )
            ran = False
            for task, enabled in (
                ("jobs", service.config.jobs.enabled),
                ("gmail", service.config.gmail.enabled),
            ):
                if task not in selected or not enabled or now < due[task]:
                    continue
                attempt = failures[task] + 1
                trigger = "retry" if failures[task] else "scheduled"
                succeeded = service.run_task(task, trigger=trigger, attempt=attempt)
                ran = True
                if succeeded:
                    failures[task] = 0
                    due[task] = (
                        next_job_run(now, service.config.jobs, service.config.timezone)
                        if task == "jobs"
                        else now + service.config.gmail.every
                    )
                else:
                    failures[task] += 1
                    if failures[task] <= 2:
                        due[task] = now + timedelta(minutes=DEFAULT_NOTIFICATION_RETRY_MINUTES)
                    else:
                        service.state.enqueue(failure_notification(task, now))
                        failures[task] = 0
                        due[task] = (
                            next_job_run(now, service.config.jobs, service.config.timezone)
                            if task == "jobs"
                            else now + service.config.gmail.every
                        )
                _log(
                    logging.INFO,
                    "scan_scheduled",
                    task=task,
                    next_run=_local_timestamp(due[task], service.config.timezone),
                    reason="retry" if failures[task] else "schedule",
                )
            if now >= next_delivery:
                service.deliver_pending(now)
                next_delivery = now + timedelta(minutes=DEFAULT_NOTIFICATION_RETRY_MINUTES)
            if now >= next_heartbeat:
                _log(
                    logging.INFO,
                    "service_heartbeat",
                    state="waiting",
                    **_schedule_log_fields(service, due),
                )
                next_heartbeat = now + timedelta(hours=DEFAULT_HEARTBEAT_HOURS)
            wait_seconds = 30 if ran else 60
            stop.wait(wait_seconds)
        _log(logging.INFO, "service_stopped", state="stopped")
        service.state.record_service_heartbeat(running=False, service=service_name)
    return 0


def _parser() -> argparse.ArgumentParser:
    command_parser = argparse.ArgumentParser(prog="resume-builder automation")
    command_parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    command_parser.add_argument("--state", type=Path, default=default_state_path())
    commands = command_parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init", help="Create a low-noise automation configuration")
    init.add_argument("--timezone", default=os.environ.get("TZ", "America/New_York"))
    init.add_argument(
        "--disabled",
        action="store_true",
        help="Create an inactive configuration for portal-first setup",
    )
    configure_parser = commands.add_parser("configure", help="Update schedules and alerts")
    configure_parser.add_argument("--timezone")
    configure_parser.add_argument("--job-time", action="append")
    configure_parser.add_argument("--gmail-hours", type=float)
    configure_parser.add_argument("--notifications", choices=("console", "discord", "disabled"))
    configure_parser.add_argument("--privacy", choices=("counts-only", "summary"))
    once = commands.add_parser("once", help="Run configured scanners once")
    once.add_argument("--task", choices=("all", *TASKS), default="all")
    run = commands.add_parser("run", help="Run the automation service continuously")
    run.add_argument("--task", choices=("all", *TASKS), default="all")
    status = commands.add_parser("status", help="Show content-free automation health")
    status.add_argument("--healthcheck", action="store_true")
    commands.add_parser("doctor", help="Validate automation, credentials, and workspace paths")
    return command_parser


def _doctor(
    workspace: Path, config_path: Path, state_path: Path, config: AutomationConfig
) -> dict[str, object]:
    job_setup_required = False
    if config.jobs.enabled and jobs.DEFAULT_CONFIG.is_file():
        try:
            job_setup_required = not load_job_config(jobs.DEFAULT_CONFIG).enabled
        except ValueError:
            job_setup_required = False
    checks: dict[str, bool] = {
        "workspace": (workspace / ".resume-builder.json").is_file()
        or (workspace / "vault" / "vault.json").is_file(),
        "automation_config": config_path.is_file(),
        "state_is_external": not state_path.is_relative_to(workspace),
        "job_config": not config.jobs.enabled or jobs.DEFAULT_CONFIG.is_file(),
        "job_preferences": not config.jobs.enabled or jobs.DEFAULT_PREFERENCES.is_file(),
    }
    gmail_state = Path(
        os.environ.get("RESUME_BUILDER_GMAIL_STATE", str(gmail_automation.default_state_path()))
    ).expanduser()
    gmail_token = Path(
        os.environ.get(
            "RESUME_BUILDER_GMAIL_TOKEN",
            str(gmail_automation.default_token_path(gmail_state)),
        )
    ).expanduser()
    checks["gmail_token"] = not config.gmail.enabled or (
        gmail_token.is_file() and os.access(gmail_token, os.R_OK)
    )
    checks["gmail_state_is_external"] = (
        not config.gmail.enabled or not gmail_state.resolve().is_relative_to(workspace)
    )
    if config.jobs.semantic_screening_enabled:
        try:
            agent_config = load_agent_config(DEFAULT_AGENT_CONFIG)
        except (OSError, ValueError):
            checks["semantic_screening_config"] = False
            checks["semantic_screening_key"] = False
        else:
            checks["semantic_screening_config"] = True
            checks["semantic_screening_key"] = bool(
                os.environ.get(agent_config.api_key_env, "").strip()
            )
    try:
        if config.notifications.sink == "discord":
            _discord_url(config.notifications)
        checks["notification"] = True
    except ValueError:
        checks["notification"] = False
    return {
        "healthy": all(checks.values()),
        "ready": all(checks.values()) and not job_setup_required,
        "setup_required": job_setup_required,
        "checks": checks,
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    structured_logs = args.command in {"once", "run"}
    if structured_logs:
        try:
            _configure_logging()
        except ValueError as exc:
            _log(
                logging.ERROR,
                "service_start_failed",
                stage="logging",
                error_category=_safe_error(exc),
                stack=_safe_stack(exc),
            )
            return 2
    workspace = Path.cwd().resolve()
    if (
        not (workspace / ".resume-builder.json").is_file()
        and not (workspace / "vault" / "vault.json").is_file()
    ):
        if structured_logs:
            _log(
                logging.ERROR,
                "service_start_failed",
                stage="workspace",
                error_category="WorkspaceNotConfigured",
            )
        else:
            print("automation commands require an active private workspace", file=sys.stderr)
        return 2
    config_path = args.config.expanduser()
    if args.command == "init":
        if config_path.exists():
            print(f"Automation configuration already exists: {config_path}")
            return 0
        try:
            ZoneInfo(args.timezone)
        except ZoneInfoNotFoundError:
            print(f"Unknown timezone: {args.timezone}", file=sys.stderr)
            return 2
        atomic_write_text(
            config_path,
            render_default_config(
                args.timezone,
                jobs_enabled=not args.disabled,
                gmail_enabled=not args.disabled,
            ),
        )
        print(f"Created {config_path}")
        print("Run `resume-builder automation doctor` before starting the service.")
        return 0
    try:
        config = load_config(config_path)
        state_path = _ensure_external(args.state, workspace)
        state = AutomationState(state_path)
        if args.command == "configure":
            updated = configure(
                config_path,
                config,
                timezone=args.timezone,
                job_times=args.job_time,
                gmail_hours=args.gmail_hours,
                notification_sink=args.notifications,
                privacy=args.privacy,
            )
            print(yaml.safe_dump(config_payload(updated), sort_keys=False), end="")
            print("Run `resume-builder automation doctor` to verify the deployment.")
            return 0
        if args.command == "doctor":
            result = _doctor(workspace, config_path, state_path, config)
            print(json.dumps(result, indent=2))
            return 0 if result["healthy"] else 2
        if args.command == "status":
            result = state.status()
            if args.healthcheck:
                healthy = any(
                    (
                        state.service_is_running(),
                        state.service_is_running(service="jobs"),
                        state.service_is_running(service="gmail"),
                    )
                )
            else:
                task_statuses = result["tasks"]
                healthy = isinstance(task_statuses, dict) and all(
                    item is None
                    or (isinstance(item, dict) and item.get("status") in {"success", "partial"})
                    for item in task_statuses.values()
                )
            result["healthy"] = healthy
            print(json.dumps(result, indent=2))
            return 0 if healthy or not args.healthcheck else 2
        service = AutomationService(
            workspace=workspace,
            config=config,
            config_path=config_path,
            state=state,
        )
        if args.command == "once":
            selected = TASKS if args.task == "all" else (args.task,)
            enabled = tuple(
                task
                for task in selected
                if (task == "jobs" and config.jobs.enabled)
                or (task == "gmail" and config.gmail.enabled)
            )
            with state.locked():
                return 0 if service.run_once(enabled) else 2
        stop = threading.Event()

        def stop_service(_signum: int, _frame: object) -> None:
            stop.set()

        signal.signal(signal.SIGTERM, stop_service)
        signal.signal(signal.SIGINT, stop_service)
        selected = TASKS if args.task == "all" else (args.task,)
        return run_forever(service, stop, selected)
    except (OSError, ValueError, sqlite3.Error, json.JSONDecodeError) as exc:
        if structured_logs:
            _log(
                logging.ERROR,
                "service_start_failed",
                stage="startup",
                error_category=_safe_error(exc),
                stack=_safe_stack(exc),
            )
        else:
            print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
