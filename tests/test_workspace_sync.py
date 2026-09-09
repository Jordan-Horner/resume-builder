from __future__ import annotations

import json
import subprocess
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from resume_builder.workspace_management.locking import workspace_lock
from resume_builder.workspace_management.sync import (
    SSH_KEY_ENV,
    SSH_KNOWN_HOSTS_ENV,
    UPDATE_TOKEN_FILE_ENV,
    _git_environment,
    read_sync_status,
    run_forever,
    sync_once,
    workspace_identity,
)


def _git(path: Path, *arguments: str) -> str:
    result = subprocess.run(
        ("git", *arguments), cwd=path, check=True, capture_output=True, text=True
    )
    return result.stdout.strip()


def _repositories(tmp_path: Path) -> tuple[Path, Path]:
    remote = tmp_path / "remote.git"
    source = tmp_path / "source"
    checkout = tmp_path / "checkout"
    _git(tmp_path, "init", "--bare", str(remote))
    _git(tmp_path, "init", "-b", "release", str(source))
    _git(source, "config", "user.name", "Test User")
    _git(source, "config", "user.email", "test@example.invalid")
    (source / "vault").mkdir()
    (source / "vault" / "fact.md").write_text("one\n", encoding="utf-8")
    _git(source, "add", ".")
    _git(source, "commit", "-m", "Initial")
    _git(source, "remote", "add", "origin", str(remote))
    _git(source, "push", "-u", "origin", "release")
    _git(tmp_path, "clone", "--branch", "release", str(remote), str(checkout))
    return source, checkout


def _push(source: Path, content: str) -> None:
    (source / "vault" / "fact.md").write_text(content, encoding="utf-8")
    _git(source, "add", ".")
    _git(source, "commit", "-m", content.strip())
    _git(source, "push")


def test_sync_fast_forwards_upstream_and_keeps_unrelated_files(tmp_path: Path) -> None:
    source, checkout = _repositories(tmp_path)
    (checkout / "runtime").mkdir()
    (checkout / "runtime" / "local.json").write_text("local\n", encoding="utf-8")
    _push(source, "two\n")

    result = sync_once(checkout)

    assert result.status == "updated"
    assert result.branch == "release"
    assert (checkout / "vault" / "fact.md").read_text(encoding="utf-8") == "two\n"
    assert (checkout / "runtime" / "local.json").read_text(encoding="utf-8") == "local\n"


def test_sync_reports_a_current_checkout(tmp_path: Path) -> None:
    _source, checkout = _repositories(tmp_path)

    result = sync_once(checkout)

    assert result.status == "current"
    assert result.previous_revision == result.revision


def test_sync_reports_a_non_git_workspace_without_modifying_it(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    result = sync_once(workspace)

    assert result.status == "not_configured"
    assert result.detail == "Workspace is not Git-backed"


def test_sync_reports_a_branch_without_an_upstream(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    _git(tmp_path, "init", "-b", "main", str(workspace))
    _git(workspace, "config", "user.name", "Test User")
    _git(workspace, "config", "user.email", "test@example.invalid")
    (workspace / "fact.md").write_text("one\n", encoding="utf-8")
    _git(workspace, "add", "fact.md")
    _git(workspace, "commit", "-m", "Initial")

    result = sync_once(workspace)

    assert result.status == "not_configured"
    assert result.detail == "Current branch has no upstream"


def test_sync_blocks_overlapping_local_work(tmp_path: Path) -> None:
    source, checkout = _repositories(tmp_path)
    (checkout / "vault" / "fact.md").write_text("local\n", encoding="utf-8")
    _push(source, "remote\n")

    result = sync_once(checkout)

    assert result.status == "blocked"
    assert result.detail == "Upstream changes overlap local work"
    assert (checkout / "vault" / "fact.md").read_text(encoding="utf-8") == "local\n"


def test_sync_blocks_local_commits_without_rewriting_them(tmp_path: Path) -> None:
    _source, checkout = _repositories(tmp_path)
    _git(checkout, "config", "user.name", "Test User")
    _git(checkout, "config", "user.email", "test@example.invalid")
    (checkout / "local.md").write_text("local\n", encoding="utf-8")
    _git(checkout, "add", "local.md")
    _git(checkout, "commit", "-m", "Local")
    revision = _git(checkout, "rev-parse", "HEAD")

    result = sync_once(checkout)

    assert result.status == "blocked"
    assert result.detail == "Local commits have not been pushed"
    assert _git(checkout, "rev-parse", "HEAD") == revision


def test_sync_blocks_diverged_history(tmp_path: Path) -> None:
    source, checkout = _repositories(tmp_path)
    _git(checkout, "config", "user.name", "Test User")
    _git(checkout, "config", "user.email", "test@example.invalid")
    (checkout / "local.md").write_text("local\n", encoding="utf-8")
    _git(checkout, "add", "local.md")
    _git(checkout, "commit", "-m", "Local")
    _push(source, "remote\n")

    result = sync_once(checkout)

    assert result.status == "blocked"
    assert result.detail == "Local and upstream histories diverged"


def test_sync_rejects_incomplete_ssh_credentials(tmp_path: Path, monkeypatch) -> None:
    _source, checkout = _repositories(tmp_path)
    monkeypatch.setenv(SSH_KEY_ENV, str(tmp_path / "missing-key"))

    result = sync_once(checkout)

    assert result.status == "error"
    assert result.detail == "SSH credentials are incomplete"


def test_git_environment_reuses_the_private_update_token(tmp_path: Path, monkeypatch) -> None:
    token = tmp_path / "github-token"
    token.write_text("synthetic-token", encoding="utf-8")
    monkeypatch.setenv(UPDATE_TOKEN_FILE_ENV, str(token))

    environment, error = _git_environment()

    assert error is None
    password = subprocess.run(
        (environment["GIT_ASKPASS"], "Password for GitHub"),
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    assert password.stdout == "synthetic-token"
    assert "synthetic-token" not in environment["GIT_ASKPASS"]


def test_git_environment_configures_strict_ssh_files(tmp_path: Path, monkeypatch) -> None:
    key = tmp_path / "key"
    hosts = tmp_path / "known-hosts"
    key.write_text("synthetic-key", encoding="utf-8")
    hosts.write_text("github.example synthetic-key", encoding="utf-8")
    monkeypatch.setenv(SSH_KEY_ENV, str(key))
    monkeypatch.setenv(SSH_KNOWN_HOSTS_ENV, str(hosts))

    environment, error = _git_environment()

    assert error is None
    assert str(key) in environment["GIT_SSH_COMMAND"]
    assert "StrictHostKeyChecking=yes" in environment["GIT_SSH_COMMAND"]


def test_git_environment_rejects_a_missing_token_file(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv(UPDATE_TOKEN_FILE_ENV, str(tmp_path / "missing-token"))

    _environment, error = _git_environment()

    assert error == "GitHub token file is unavailable"


def test_status_rejects_another_workspace_and_stale_results(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    other = tmp_path / "other"
    workspace.mkdir()
    other.mkdir()
    state = tmp_path / "sync.json"
    checked_at = datetime.now(timezone.utc) - timedelta(minutes=20)
    state.write_text(
        json.dumps(
            {
                "status": "current",
                "detail": "Workspace is current",
                "checked_at": checked_at.isoformat(),
                "workspace_id": workspace_identity(workspace),
            }
        ),
        encoding="utf-8",
    )

    wrong_workspace = read_sync_status(state, workspace=other, max_age_seconds=60)
    stale = read_sync_status(state, workspace=workspace, max_age_seconds=60)

    assert wrong_workspace["status"] == "waiting"
    assert stale == {"status": "stale", "detail": "Workspace update check is overdue"}


def test_status_handles_missing_and_malformed_state(tmp_path: Path) -> None:
    state = tmp_path / "sync.json"
    assert read_sync_status(state)["status"] == "waiting"
    state.write_text("not-json", encoding="utf-8")
    assert read_sync_status(state)["status"] == "unknown"
    state.write_text('{"status": 1, "detail": null}', encoding="utf-8")
    assert read_sync_status(state)["status"] == "unknown"


def test_worker_records_that_its_first_check_is_starting(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    state = tmp_path / "state" / "sync.json"
    stop = threading.Event()
    stop.set()

    run_forever(workspace, state, interval_seconds=30, stop=stop)

    payload = json.loads(state.read_text(encoding="utf-8"))
    assert payload["status"] == "checking"
    assert payload["workspace_id"] == workspace_identity(workspace)


def test_sync_waits_for_an_active_workspace_writer(tmp_path: Path) -> None:
    _source, checkout = _repositories(tmp_path)
    finished = threading.Event()

    def run_sync() -> None:
        sync_once(checkout)
        finished.set()

    with workspace_lock(checkout, exclusive=True):
        worker = threading.Thread(target=run_sync)
        worker.start()
        assert not finished.wait(0.1)
    worker.join(timeout=5)

    assert finished.is_set()
