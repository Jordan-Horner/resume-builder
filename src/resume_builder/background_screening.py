"""Shared bounded quick-screen runner for scheduled and portal job discovery."""

from __future__ import annotations

import os
from pathlib import Path

from .agent_config import DEFAULT_AGENT_CONFIG, load_agent_config
from .agent_openrouter import OpenRouterAdapter
from .job_screening_queue import ScreeningQueueSummary, build_screening_queue
from .jobs import (
    DEFAULT_CONFIG,
    DEFAULT_NEW_OUTPUT,
    DEFAULT_OUTPUT,
    DEFAULT_PREFERENCES,
    DEFAULT_REVIEW_OUTPUT,
    _shortlist,
)
from .screening_service import BACKGROUND_SCREEN_TIMEOUT_SECONDS, QUICK_SCREEN_PROVIDER_RETRIES

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


def prepare_background_screening_input(workspace: Path, *, display_limit: int = 50) -> Path:
    """Refresh the local active-job shortlist without contacting discovery providers."""
    root = workspace.expanduser().resolve()
    output_path = root / DEFAULT_OUTPUT
    code = _shortlist(
        root / DEFAULT_CONFIG,
        root / DEFAULT_PREFERENCES,
        display_limit,
        output_path=output_path,
        review_output_path=root / DEFAULT_REVIEW_OUTPUT,
    )
    if code != 0:
        raise RuntimeError("active job shortlist could not be prepared")
    return output_path


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
        adapter=OpenRouterAdapter(
            config,
            api_key=key,
            timeout_seconds=BACKGROUND_SCREEN_TIMEOUT_SECONDS,
            retries=QUICK_SCREEN_PROVIDER_RETRIES,
        ),
        model=config.models.fast,
        interpretation_model=config.models.fast,
        cache_path=root / DEFAULT_SCREENING_CACHE,
        input_path=input_path or root / DEFAULT_NEW_OUTPUT,
        output_path=root / DEFAULT_SCREENING_OUTPUT,
        config_path=root / DEFAULT_CONFIG,
        preferences_path=root / DEFAULT_PREFERENCES,
        # Background screening has its own explicit, user-configured batch budget.
        # AgentLimits.max_requests bounds one conversational agent turn; applying it
        # here silently reduced a 25-job backfill to the default six requests.
        max_provider_jobs=max_jobs,
        allow_provider=True,
        workspace=root,
    )
