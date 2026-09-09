"""Configuration models and persistence for scheduled automation."""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from datetime import time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml

from ..atomic import atomic_write_text

DEFAULT_CONFIG = Path("automation/config.yml")
DEFAULT_JOB_TIMES = ("08:00",)
DEFAULT_GMAIL_INTERVAL_HOURS = 4


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
    start: \"21:00\"
    end: \"07:00\"
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
    semantic_screening_enabled: bool | None = None,
    semantic_screening_max_jobs: int | None = None,
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
    screening_payload = _mapping(job_payload["semantic_screening"], "jobs.semantic_screening")
    if semantic_screening_enabled is not None:
        screening_payload["enabled"] = semantic_screening_enabled
    if semantic_screening_max_jobs is not None:
        screening_payload["max_jobs_per_run"] = semantic_screening_max_jobs
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
