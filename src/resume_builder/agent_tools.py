"""Small, explicit read-only tool surface for the initial agent cycle."""

from __future__ import annotations

import json
from pathlib import Path

from . import jobs
from .agent_contracts import AgentTool
from .automation import AutomationState


def build_read_only_tools(state_path: Path) -> tuple[AgentTool, ...]:
    """Create tools that cannot mutate the career workspace or external services."""

    def get_automation_status() -> dict[str, object]:
        """Return content-free job and Gmail scheduler health."""
        status = AutomationState(state_path).status()
        return {
            "tasks": status["tasks"],
            "pending_notifications": status["pending_notifications"],
        }

    def list_new_job_matches(limit: int = 10) -> list[dict[str, object]]:
        """List sanitized new jobs that deterministic prescreening marked for review."""
        if not 1 <= limit <= 25:
            raise ValueError("limit must be from 1 to 25")
        if not jobs.DEFAULT_NEW_OUTPUT.is_file():
            return []
        payload = json.loads(jobs.DEFAULT_NEW_OUTPUT.read_text(encoding="utf-8"))
        raw_jobs = payload.get("jobs", [])
        if not isinstance(raw_jobs, list):
            return []
        matches: list[dict[str, object]] = []
        for item in raw_jobs:
            if not isinstance(item, dict):
                continue
            screen = item.get("prescreen")
            if not isinstance(screen, dict) or screen.get("review_eligible") is not True:
                continue
            readiness = screen.get("keyword_readiness")
            matches.append(
                {
                    "id": item.get("id"),
                    "title": item.get("title"),
                    "company": item.get("company"),
                    "url": item.get("url"),
                    "category": screen.get("category"),
                    "keyword_readiness_percent": (
                        readiness.get("percent") if isinstance(readiness, dict) else None
                    ),
                }
            )
            if len(matches) == limit:
                break
        return matches

    return (
        AgentTool(
            name="get_automation_status",
            description="Return content-free status for scheduled job and Gmail scans.",
            handler=get_automation_status,
        ),
        AgentTool(
            name="list_new_job_matches",
            description="List sanitized newly discovered jobs marked as worth reviewing.",
            handler=list_new_job_matches,
        ),
    )
