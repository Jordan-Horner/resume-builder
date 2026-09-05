"""Portal controls for the native job-discovery schedule."""

from __future__ import annotations

import os
import sqlite3
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .atomic import atomic_write_text
from .automation import (
    DEFAULT_CONFIG,
    AutomationConfig,
    AutomationState,
    configure,
    default_state_path,
    load_config,
    next_job_run,
    render_default_config,
)
from .service import managed_service_status, set_scheduler_enabled


def _default_timezone() -> str:
    candidate = os.environ.get("TZ", "America/New_York")
    try:
        ZoneInfo(candidate)
    except ZoneInfoNotFoundError:
        return "America/New_York"
    return candidate


def _default_config() -> AutomationConfig:
    descriptor, name = tempfile.mkstemp(prefix="resume-builder-automation-", suffix=".yml")
    path = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(
                render_default_config(
                    _default_timezone(),
                    jobs_enabled=False,
                    gmail_enabled=False,
                )
            )
        return load_config(path)
    finally:
        path.unlink(missing_ok=True)


def _load(root: Path) -> tuple[AutomationConfig, bool]:
    path = root / DEFAULT_CONFIG
    return (load_config(path), True) if path.is_file() else (_default_config(), False)


def _state_status(path: Path) -> tuple[str, dict[str, object] | None]:
    state = AutomationState(path)
    try:
        managed = managed_service_status("scheduler")
        running = (
            managed in {"running", "starting"}
            if managed is not None
            else state.service_is_running(service="jobs") or state.service_is_running()
        )
        last_run = state.last_run("jobs")
    except (OSError, RuntimeError, ValueError, sqlite3.Error):
        return "unknown", None
    return ("online" if running else "offline"), last_run


def schedule_status(
    root: Path,
    *,
    now: datetime | None = None,
    state_path: Path | None = None,
) -> dict[str, Any]:
    """Describe the configured job schedule and its live scheduler state."""
    config, configured = _load(root)
    current = now or datetime.now(UTC)
    service_status, last_run = _state_status(state_path or default_state_path())
    next_run = next_job_run(current, config.jobs, config.timezone) if config.jobs.enabled else None
    return {
        "configured": configured,
        "enabled": config.jobs.enabled,
        "times": [value.strftime("%H:%M") for value in config.jobs.times],
        "timezone": str(config.timezone),
        "next_run": next_run.astimezone(config.timezone).isoformat(timespec="seconds")
        if next_run
        else None,
        "last_run": last_run.get("finished_at") if last_run else None,
        "service_status": service_status,
    }


def save_schedule(
    root: Path,
    payload: dict[str, object],
    *,
    now: datetime | None = None,
    state_path: Path | None = None,
) -> dict[str, Any]:
    """Validate and persist portal changes through the native scheduler config."""
    enabled = payload.get("enabled")
    times = payload.get("times")
    unknown = sorted(set(payload) - {"enabled", "times"})
    if unknown:
        raise ValueError(f"Unknown schedule settings: {', '.join(unknown)}")
    if not isinstance(enabled, bool):
        raise ValueError("enabled must be a boolean")
    if not isinstance(times, list) or not times:
        raise ValueError("Choose at least one time for automatic scraping.")
    if not all(isinstance(value, str) for value in times):
        raise ValueError("Run times must use HH:MM.")

    config, _ = _load(root)
    path = root / DEFAULT_CONFIG
    path.parent.mkdir(parents=True, exist_ok=True)
    existed = path.is_file()
    previous = path.read_text(encoding="utf-8") if existed else None
    try:
        configure(
            path,
            config,
            timezone=None,
            job_times=times,
            gmail_hours=None,
            notification_sink=None,
            privacy=None,
            job_enabled=enabled,
        )
        set_scheduler_enabled(enabled)
    except (OSError, RuntimeError, ValueError):
        if previous is not None:
            atomic_write_text(path, previous)
        elif not existed:
            path.unlink(missing_ok=True)
        raise
    return schedule_status(root, now=now, state_path=state_path)
