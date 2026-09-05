"""Portal controls over the existing collector and jobs-new workflow."""

from __future__ import annotations

import fcntl
import json
import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

import yaml

from job_puller.config import InventoryConfig, load_config, resolve_database_path

from .atomic import atomic_write_json, atomic_write_text
from .discovery_activation import load_portfolio, preview_activation

CONFIG = Path("job-search/config/search.yml")
STATE = Path("job-search/web-scan.json")
LOCK = Path("job-search/web-scan.lock")
NAMES = {
    "linkedin": "LinkedIn",
    "indeed": "Indeed",
    "jazzhr": "JazzHR",
    "rippling": "Rippling",
    "greenhouse": "Greenhouse",
    "lever": "Lever",
    "ashby": "Ashby",
    "smartrecruiters": "SmartRecruiters",
    "workday": "Workday",
}


def _lock(root: Path) -> Any:
    path = root / LOCK
    path.parent.mkdir(parents=True, exist_ok=True)
    stream = path.open("a+")
    try:
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        stream.close()
        raise ValueError("A scan is already running. Wait for it to finish.") from None
    return stream


def source_status(root: Path) -> dict[str, Any]:
    config = load_config(root / CONFIG)
    providers = []
    for name in NAMES:
        settings = getattr(config.providers, name)
        boards = getattr(settings, "boards", None)
        providers.append(
            {
                "id": name,
                "name": NAMES[name],
                "enabled": settings.enabled,
                "detail": "Searches your selected roles"
                if boards is None
                else f"{sum(board.enabled for board in boards)} company boards available",
            }
        )
    state = (
        json.loads((root / STATE).read_text()) if (root / STATE).exists() else {"status": "idle"}
    )
    if state["status"] == "running":
        try:
            with _lock(root):
                state = json.loads((root / STATE).read_text())
                if state["status"] == "running":
                    state = {
                        "status": "failed",
                        "message": "The scan was interrupted. You can try again.",
                    }
        except ValueError:
            state["message"] = "Searching enabled sources…"
    return {"providers": providers, "scan": state}


def toggle_source(root: Path, provider: str, enabled: bool) -> dict[str, Any]:
    if provider not in NAMES or type(enabled) is not bool:
        raise ValueError("Choose a supported provider and an On/Off value.")
    with _lock(root):
        path = root / CONFIG
        raw = yaml.safe_load(path.read_text())
        raw.setdefault("providers", {}).setdefault(provider, {})["enabled"] = enabled
        # Allow all sources off without activating any collector or scheduler.
        probe = {**raw, "enabled": False}
        InventoryConfig.model_validate(probe)
        if not any(
            getattr(InventoryConfig.model_validate(probe).providers, key).enabled for key in NAMES
        ):
            raw["enabled"] = False
        atomic_write_text(path, yaml.safe_dump(raw, sort_keys=False))
    return source_status(root)


def start_scan(root: Path) -> dict[str, Any]:
    root = root.resolve()
    lock = _lock(root)
    try:
        path = root / CONFIG
        config = load_config(path)
        if not any(getattr(config.providers, key).enabled for key in NAMES):
            raise ValueError("Turn on at least one job source first.")
        raw = yaml.safe_load(path.read_text())
        if not config.search.families:
            portfolio = root / "build/job-search/cold-start-portfolio.json"
            if not portfolio.exists():
                raise ValueError("Finish saving your job preferences before scanning.")
            raw = yaml.safe_load(
                preview_activation(load_portfolio(portfolio), path.read_text()).rendered_config
            )
        raw["enabled"] = True
        raw["database_path"] = str(resolve_database_path(path, config.database_path))
        # Snapshot beside canonical config preserves relative registry resolution.
        snapshot = path.with_name("web-manual-scan.yml")
        InventoryConfig.model_validate(raw)
        atomic_write_text(snapshot, yaml.safe_dump(raw, sort_keys=False))
        atomic_write_json(
            root / STATE, {"status": "running", "message": "Searching enabled sources…"}
        )
        with (root / "job-search/web-scan.log").open("w") as log:
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "resume_builder.web_job_sources",
                    str(root),
                    str(snapshot),
                    str(lock.fileno()),
                ],
                cwd=root,
                stdout=log,
                stderr=log,
                pass_fds=(lock.fileno(),),
                start_new_session=True,
            )
            threading.Thread(target=process.wait, daemon=True).start()
    except Exception:
        atomic_write_json(
            root / STATE,
            {
                "status": "failed",
                "message": "Could not start the scan. Check your preferences and try again.",
            },
        )
        raise
    finally:
        lock.close()
    return source_status(root)


def run_worker(root: Path, snapshot: Path) -> None:
    from .jobs import main

    try:
        refresh_path = root / "job-search/latest-refresh.json"
        before = refresh_path.read_text() if refresh_path.exists() else None
        code = main(["--config", str(snapshot), "new"])
        after = refresh_path.read_text() if refresh_path.exists() else None
        if after is None or after == before:
            raise ValueError("The collector did not produce a new scan result.")
        manifest = json.loads(after)
        errors = [
            {
                "provider": run.get("provider"),
                "message": run.get("error")
                or run.get("error_category")
                or "Source did not complete",
            }
            for run in manifest.get("provider_runs", [])
            if not run.get("success", False)
        ]
        atomic_write_json(
            root / STATE,
            {
                "status": manifest.get("status", "failed"),
                "new_jobs": len(manifest.get("new_to_database_job_ids", [])),
                "errors": errors,
                "message": "Scan complete"
                if code == 0
                else "Some sources could not complete. You can try again.",
            },
        )
    except Exception:
        atomic_write_json(
            root / STATE,
            {
                "status": "failed",
                "message": "The scan failed. Check source availability and try again.",
            },
        )
        raise


if __name__ == "__main__":
    try:
        run_worker(Path(sys.argv[1]), Path(sys.argv[2]))
    finally:
        os.close(int(sys.argv[3]))
