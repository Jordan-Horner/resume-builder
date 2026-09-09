"""Shared bounded quick-screen runner for scheduled and portal job discovery."""

from __future__ import annotations

import fcntl
import os
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from .assistant.config import DEFAULT_AGENT_CONFIG, load_agent_config
from .assistant.openrouter import OpenRouterAdapter
from .atomic import atomic_write_json
from .opportunities.cli import (
    DEFAULT_CONFIG,
    DEFAULT_NEW_OUTPUT,
    DEFAULT_OUTPUT,
    DEFAULT_PREFERENCES,
    DEFAULT_REVIEW_OUTPUT,
    _shortlist,
)
from .opportunities.screening_queue import ScreeningQueueSummary, build_screening_queue
from .opportunities.screening_service import (
    BACKGROUND_SCREEN_TIMEOUT_SECONDS,
    QUICK_SCREEN_PROVIDER_RETRIES,
)

DEFAULT_SCREENING_CACHE = Path("build/job-search/screening-cache.sqlite")
DEFAULT_SCREENING_OUTPUT = Path("job-search/new-job-screens.json")
DEFAULT_REPLENISHMENT_STATE = Path("job-search/screening-replenishment.json")
DEFAULT_REPLENISHMENT_LOCK = Path("job-search/screening-replenishment.lock")
DEFAULT_OPENROUTER_SECRET = Path("build/secrets/openrouter-key")


@contextmanager
def replenishment_lock(workspace: Path) -> Iterator[None]:
    """Serialize screening writers across the portal and scheduler processes."""
    path = workspace / DEFAULT_REPLENISHMENT_LOCK
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def replenishment_running(workspace: Path) -> bool:
    """Return whether a live process currently owns the workspace screening lease."""
    path = workspace / DEFAULT_REPLENISHMENT_LOCK
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        fcntl.flock(stream, fcntl.LOCK_UN)
    return False


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


def publish_replenishment_state(
    workspace: Path,
    *,
    status: str,
    batch_count: int,
    summary: ScreeningQueueSummary | None = None,
) -> None:
    payload: dict[str, object] = {
        "schema_version": 1,
        "status": status,
        "batch_count": batch_count,
        "updated_at": datetime.now(UTC).isoformat(),
    }
    if summary is not None:
        payload.update(
            active_jobs=summary.active,
            completed_jobs=summary.completed,
            pending_jobs=summary.pending,
            failed_jobs=summary.failed,
            recommended_jobs=summary.recommended,
        )
    atomic_write_json(workspace / DEFAULT_REPLENISHMENT_STATE, payload)


def run_background_replenishment(
    workspace: Path,
    *,
    max_jobs: int,
    input_path: Path | None = None,
    display_limit: int | None = None,
    on_batch: Callable[[ScreeningQueueSummary, int], None] | None = None,
) -> ScreeningQueueSummary:
    """Run bounded batches until the current eligible backlog stops advancing."""
    root = workspace.expanduser().resolve()
    batch_count = 0
    max_batches: int | None = None
    summary: ScreeningQueueSummary | None = None
    with replenishment_lock(root):
        if display_limit is not None:
            input_path = prepare_background_screening_input(root, display_limit=display_limit)
        publish_replenishment_state(root, status="running", batch_count=0)
        try:
            while True:
                summary = run_background_quick_screening(
                    root,
                    max_jobs=max_jobs,
                    input_path=input_path,
                )
                batch_count += 1
                if max_batches is None:
                    screenable = summary.completed + summary.pending
                    max_batches = max(1, (screenable + max_jobs - 1) // max_jobs + 1)
                publish_replenishment_state(
                    root,
                    status="running",
                    batch_count=batch_count,
                    summary=summary,
                )
                if on_batch is not None:
                    on_batch(summary, batch_count)
                if summary.pending == 0 or summary.succeeded == 0 or batch_count >= max_batches:
                    break
        except Exception:
            publish_replenishment_state(
                root,
                status="failed",
                batch_count=batch_count,
                summary=summary,
            )
            raise
        if summary is None:  # pragma: no cover - the loop always runs once
            raise RuntimeError("screening replenishment did not run")
        publish_replenishment_state(
            root,
            status="complete" if summary.pending == 0 else "partial",
            batch_count=batch_count,
            summary=summary,
        )
    return summary
