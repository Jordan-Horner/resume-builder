import json
from pathlib import Path

import pytest
import yaml

from resume_builder import web_job_sources as sources
from resume_builder.automation import DEFAULT_CONFIG, render_default_config
from resume_builder.job_setup_defaults import scaffold_job_search


def test_toggles_persist_without_starting_scans(tmp_path: Path) -> None:
    scaffold_job_search(tmp_path)
    for provider in sources.NAMES:
        sources.toggle_source(tmp_path, provider, False)
    assert not any(item["enabled"] for item in sources.source_status(tmp_path)["providers"])
    assert not (tmp_path / sources.STATE).exists()
    assert yaml.safe_load((tmp_path / sources.CONFIG).read_text())["enabled"] is False
    with pytest.raises(ValueError, match="at least one"):
        sources.start_scan(tmp_path)
    sources.toggle_source(tmp_path, "indeed", True)
    assert next(
        item for item in sources.source_status(tmp_path)["providers"] if item["id"] == "indeed"
    )["enabled"]


def test_invalid_toggle_and_duplicate_scan_are_rejected(tmp_path: Path) -> None:
    scaffold_job_search(tmp_path)
    with pytest.raises(ValueError):
        sources.toggle_source(tmp_path, "unknown", True)
    with pytest.raises(ValueError):
        sources.toggle_source(tmp_path, "indeed", "false")
    with sources._lock(tmp_path), pytest.raises(ValueError, match="already running"):
        sources.start_scan(tmp_path)


def test_manual_scan_uses_snapshot_not_activation(tmp_path: Path, monkeypatch) -> None:
    scaffold_job_search(tmp_path)
    automation_config = tmp_path / DEFAULT_CONFIG
    automation_config.parent.mkdir(parents=True)
    automation_config.write_text(
        render_default_config("America/New_York", jobs_enabled=False, gmail_enabled=True),
        encoding="utf-8",
    )
    path = tmp_path / sources.CONFIG
    raw = yaml.safe_load(path.read_text())
    raw["search"]["families"] = [{"name": "support", "titles": ["Support Engineer"]}]
    path.write_text(yaml.safe_dump(raw))
    before = path.read_text()
    calls = []

    class Process:
        def __init__(self, args, **kwargs):
            calls.append((args, kwargs))

        def wait(self):
            return 0

    monkeypatch.setattr(sources.subprocess, "Popen", Process)
    sources.start_scan(tmp_path)
    assert path.read_text() == before
    snapshot = yaml.safe_load(path.with_name("web-manual-scan.yml").read_text())
    assert snapshot["enabled"] is True
    assert Path(snapshot["database_path"]).is_absolute()
    assert calls[0][0][2] == "resume_builder.web_job_sources"
    assert calls[0][1]["cwd"] == tmp_path


def test_worker_reuses_jobs_new_and_reports_partial_result(tmp_path: Path, monkeypatch) -> None:
    from resume_builder import jobs

    scaffold_job_search(tmp_path)
    calls = []

    def run(args):
        calls.append(args)
        (tmp_path / "job-search/latest-refresh.json").write_text(
            json.dumps(
                {
                    "status": "partial",
                    "new_to_database_job_ids": ["job1"],
                    "provider_runs": [
                        {"provider": "indeed", "success": False, "error_category": "rate_limit"}
                    ],
                }
            )
        )
        return 1

    monkeypatch.setattr(jobs, "main", run)
    sources.run_worker(tmp_path, tmp_path / sources.CONFIG)
    state = json.loads((tmp_path / sources.STATE).read_text())
    assert state["status"] == "partial"
    assert state["new_jobs"] == 1
    assert state["errors"][0]["message"] == "rate_limit"
    assert calls[0][-1] == "new"
