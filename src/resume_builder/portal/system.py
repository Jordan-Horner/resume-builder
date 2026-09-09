"""Content-free component health for the local portal."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from ..assistant.state import AgentState, default_agent_state_path
from ..scheduled_tasks.supervisor import (
    managed_service_status,
    telegram_configuration_status,
)
from ..workspace_management.sync import read_sync_status
from .schedule import schedule_status


def system_status(workspace: Path) -> dict[str, Any]:
    """Report core and optional service state without exposing private data."""
    schedule = schedule_status(workspace)
    scheduler = schedule["service_status"] if schedule["enabled"] else "disabled"
    telegram_config = telegram_configuration_status(workspace)
    sync_enabled = os.environ.get("RESUME_BUILDER_WORKSPACE_SYNC_ENABLED", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    state_root = Path(os.environ.get("RESUME_BUILDER_STATE_DIR", "/state")).expanduser()
    try:
        interval = max(
            float(os.environ.get("RESUME_BUILDER_WORKSPACE_SYNC_INTERVAL_SECONDS", "300")),
            30.0,
        )
    except ValueError:
        interval = 300.0
    workspace_sync = (
        read_sync_status(
            state_root / "workspace-sync.json",
            workspace=workspace,
            max_age_seconds=interval * 2 + 30,
        )
        if sync_enabled
        else {"status": "disabled", "detail": "Off"}
    )
    if sync_enabled:
        try:
            sync_process = managed_service_status("workspace-sync")
        except (OSError, RuntimeError, ValueError):
            sync_process = "unknown"
        if sync_process not in {None, "running", "starting"}:
            workspace_sync = {
                "status": "error",
                "detail": "Workspace update worker is not running",
            }
    telegram = telegram_config
    if telegram_config == "ready":
        try:
            state_path = Path(
                os.environ.get("RESUME_BUILDER_AGENT_STATE", str(default_agent_state_path()))
            )
            telegram = (
                "online" if AgentState(state_path).telegram_service_is_running() else "offline"
            )
        except (OSError, ValueError):
            telegram = "unknown"
    components = [
        {"id": "portal", "name": "Portal", "status": "online", "detail": "Available"},
        {
            "id": "scheduler",
            "name": "Scheduler",
            "status": scheduler,
            "detail": {
                "online": "Running",
                "disabled": "Off",
                "offline": "Enabled but unavailable",
                "unknown": "Status unavailable",
            }.get(scheduler, "Status unavailable"),
        },
        {
            "id": "workspace-sync",
            "name": "Workspace sync",
            "status": workspace_sync["status"],
            "detail": workspace_sync["detail"],
        },
        {
            "id": "telegram",
            "name": "Telegram",
            "status": telegram,
            "detail": {
                "online": "Connected",
                "offline": "Configured but unavailable",
                "disabled": "Off",
                "not_configured": "Not configured",
                "error": "Configuration needs attention",
                "unknown": "Status unavailable",
            }.get(telegram, "Status unavailable"),
        },
    ]
    sync_ready = not sync_enabled or workspace_sync["status"] in {
        "current",
        "updated",
    }
    return {
        "status": ("healthy" if scheduler in {"online", "disabled"} and sync_ready else "degraded"),
        "components": components,
    }
