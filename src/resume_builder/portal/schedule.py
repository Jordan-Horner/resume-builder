"""Portal controls for the native job-discovery schedule."""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ..atomic import atomic_write_text
from ..automation import AutomationState, default_state_path, next_job_run
from ..background_screening import (
    DEFAULT_REPLENISHMENT_STATE,
    DEFAULT_SCREENING_OUTPUT,
    background_screening_configured,
    replenishment_running,
)
from ..scheduled_tasks.config import (
    DEFAULT_CONFIG,
    AutomationConfig,
    configure,
    load_config,
    render_default_config,
)
from ..service import managed_service_status, set_scheduler_enabled


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


def _current_job_stage(
    root: Path,
    *,
    screening_enabled: bool,
    last_run: dict[str, object] | None,
) -> str:
    """Infer the live discovery/screening stage from atomic published artifacts."""
    refresh_path = root / "job-search/latest-refresh.json"
    if not refresh_path.is_file():
        return "idle"
    try:
        refresh = json.loads(refresh_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "idle"
    status = refresh.get("status")
    if status in {"in_progress", "processing"}:
        return "searching"
    if status not in {"complete", "partial"} or not screening_enabled:
        return "idle"
    replenishment_path = root / DEFAULT_REPLENISHMENT_STATE
    if replenishment_path.is_file():
        try:
            replenishment = json.loads(replenishment_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            replenishment = {}
        if replenishment.get("status") == "running":
            return "screening" if replenishment_running(root) else "idle"
    started_at = str(refresh.get("started_at") or "")
    finished_at = str(last_run.get("finished_at") or "") if last_run else ""
    if started_at and finished_at >= started_at:
        return "idle"
    screen_path = root / DEFAULT_SCREENING_OUTPUT
    try:
        if (
            screen_path.is_file()
            and screen_path.stat().st_mtime_ns >= refresh_path.stat().st_mtime_ns
        ):
            return "idle"
    except OSError:
        return "idle"
    return "screening"


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
    screen_path = root / DEFAULT_SCREENING_OUTPUT
    try:
        recommendation_revision = str(screen_path.stat().st_mtime_ns)
    except OSError:
        recommendation_revision = "0"
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
        "screening_enabled": config.jobs.semantic_screening_enabled,
        "screening_max_jobs": config.jobs.semantic_screening_max_jobs,
        "screening_available": background_screening_configured(root),
        "current_stage": _current_job_stage(
            root,
            screening_enabled=config.jobs.semantic_screening_enabled,
            last_run=last_run,
        ),
        "recommendation_revision": recommendation_revision,
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
    screening_enabled_value = payload.get("screening_enabled")
    screening_max_jobs_value = payload.get("screening_max_jobs")
    unknown = sorted(set(payload) - {"enabled", "times", "screening_enabled", "screening_max_jobs"})
    if unknown:
        raise ValueError(f"Unknown schedule settings: {', '.join(unknown)}")
    if not isinstance(enabled, bool):
        raise ValueError("enabled must be a boolean")
    if not isinstance(times, list) or not times:
        raise ValueError("Choose at least one time for automatic scraping.")
    if not all(isinstance(value, str) for value in times):
        raise ValueError("Run times must use HH:MM.")
    if "screening_enabled" in payload and not isinstance(screening_enabled_value, bool):
        raise ValueError("screening_enabled must be a boolean")
    if "screening_max_jobs" in payload and (
        not isinstance(screening_max_jobs_value, int)
        or isinstance(screening_max_jobs_value, bool)
        or not 1 <= screening_max_jobs_value <= 25
    ):
        raise ValueError("screening_max_jobs must be from 1 to 25")

    config, _ = _load(root)
    screening_enabled = (
        screening_enabled_value
        if isinstance(screening_enabled_value, bool)
        else config.jobs.semantic_screening_enabled
    )
    screening_max_jobs = (
        screening_max_jobs_value
        if isinstance(screening_max_jobs_value, int)
        else config.jobs.semantic_screening_max_jobs
    )
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
            semantic_screening_enabled=screening_enabled,
            semantic_screening_max_jobs=screening_max_jobs,
        )
        set_scheduler_enabled(enabled)
    except (OSError, RuntimeError, ValueError):
        if previous is not None:
            atomic_write_text(path, previous)
        elif not existed:
            path.unlink(missing_ok=True)
        raise
    return schedule_status(root, now=now, state_path=state_path)
