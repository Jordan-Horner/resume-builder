"""Shared bounded quick-screen runner for scheduled and portal job discovery."""

from __future__ import annotations

import os
from pathlib import Path

from .agent_config import DEFAULT_AGENT_CONFIG, load_agent_config
from .agent_openrouter import OpenRouterAdapter
from .job_screening_queue import ScreeningQueueSummary, build_screening_queue
from .jobs import DEFAULT_CONFIG, DEFAULT_NEW_OUTPUT, DEFAULT_PREFERENCES

DEFAULT_SCREENING_CACHE = Path("build/job-search/screening-cache.sqlite")
DEFAULT_SCREENING_OUTPUT = Path("job-search/new-job-screens.json")
DEFAULT_OPENROUTER_SECRET = Path("build/secrets/openrouter-key")


def _api_key(workspace: Path, env_name: str) -> str:
    override = os.environ.get("RESUME_BUILDER_OPENROUTER_KEY_FILE", "").strip()
    secret_path = (
        Path(override).expanduser().resolve() if override else workspace / DEFAULT_OPENROUTER_SECRET
    )
    if secret_path.is_file():
        return secret_path.read_text(encoding="utf-8").strip()
    return os.environ.get(env_name, "").strip()


def background_screening_configured(workspace: Path) -> bool:
    """Report whether the shared quick-screen provider configuration is usable."""
    root = workspace.expanduser().resolve()
    config_path = root / DEFAULT_AGENT_CONFIG
    if not config_path.is_file():
        return False
    try:
        config = load_agent_config(config_path)
    except (OSError, ValueError):
        return False
    return bool(_api_key(root, config.api_key_env))


def run_background_quick_screening(
    workspace: Path,
    *,
    max_jobs: int,
    input_path: Path | None = None,
) -> ScreeningQueueSummary:
    """Screen only locally eligible/relevant new jobs and share the portal cache."""
    root = workspace.expanduser().resolve()
    config = load_agent_config(root / DEFAULT_AGENT_CONFIG)
    key = _api_key(root, config.api_key_env)
    if not key:
        raise ValueError("Connect OpenRouter in Settings before enabling background screening")
    return build_screening_queue(
        adapter=OpenRouterAdapter(config, api_key=key),
        model=config.models.fast,
        cache_path=root / DEFAULT_SCREENING_CACHE,
        input_path=input_path or root / DEFAULT_NEW_OUTPUT,
        output_path=root / DEFAULT_SCREENING_OUTPUT,
        config_path=root / DEFAULT_CONFIG,
        preferences_path=root / DEFAULT_PREFERENCES,
        max_provider_jobs=min(max_jobs, config.limits.max_requests),
        allow_provider=True,
        workspace=root,
    )
