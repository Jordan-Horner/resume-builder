"""Content-free component health for the local portal."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .agent_state import AgentState, default_agent_state_path
from .service import telegram_configuration_status
from .web_schedule import schedule_status


def system_status(workspace: Path) -> dict[str, Any]:
    """Report core and optional service state without exposing private data."""
    scheduler = schedule_status(workspace)["service_status"]
    telegram_config = telegram_configuration_status(workspace)
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
            "detail": "Running" if scheduler == "online" else "Starting or unavailable",
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
    return {
        "status": "healthy" if scheduler == "online" else "degraded",
        "components": components,
    }
