"""Safely keep a mounted Git-backed workspace current with its upstream."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import shlex
import signal
import subprocess
import tempfile
import threading
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from ..atomic import atomic_write_json, atomic_write_text
from .locking import workspace_lock
from .state import discover_workspace

SYNC_INTERVAL_ENV = "RESUME_BUILDER_WORKSPACE_SYNC_INTERVAL_SECONDS"
DEFAULT_SYNC_INTERVAL_SECONDS = 300
SSH_KEY_ENV = "RESUME_BUILDER_WORKSPACE_SYNC_SSH_KEY_FILE"
SSH_KNOWN_HOSTS_ENV = "RESUME_BUILDER_WORKSPACE_SYNC_KNOWN_HOSTS_FILE"
TOKEN_FILE_ENV = "RESUME_BUILDER_WORKSPACE_SYNC_TOKEN_FILE"
UPDATE_TOKEN_FILE_ENV = "RESUME_BUILDER_UPDATE_TOKEN_FILE"
_ASKPASS = """#!/bin/sh
case "$1" in
  *sername*) printf '%s\\n' 'x-access-token' ;;
  *assword*) cat "$RESUME_BUILDER_GIT_TOKEN_FILE" ;;
  *) exit 1 ;;
esac
"""


@dataclass(frozen=True)
class SyncResult:
    status: str
    detail: str
    checked_at: str
    branch: str | None = None
    previous_revision: str | None = None
    revision: str | None = None
    workspace_id: str | None = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def workspace_identity(workspace: Path) -> str:
    """Return a content-free identifier for one resolved workspace path."""
    return hashlib.sha256(str(workspace.expanduser().resolve()).encode()).hexdigest()


def _git_environment() -> tuple[dict[str, str], str | None]:
    environment = os.environ.copy()
    environment["GIT_TERMINAL_PROMPT"] = "0"
    key_value = environment.get(SSH_KEY_ENV, "").strip()
    hosts_value = environment.get(SSH_KNOWN_HOSTS_ENV, "").strip()
    if bool(key_value) != bool(hosts_value):
        return environment, "SSH credentials are incomplete"
    if key_value:
        key = Path(key_value).expanduser()
        hosts = Path(hosts_value).expanduser()
        if not key.is_file() or not hosts.is_file():
            return environment, "SSH credential files are unavailable"
        environment["GIT_SSH_COMMAND"] = " ".join(
            (
                "ssh",
                "-i",
                shlex.quote(str(key)),
                "-o",
                "IdentitiesOnly=yes",
                "-o",
                "StrictHostKeyChecking=yes",
                "-o",
                f"UserKnownHostsFile={shlex.quote(str(hosts))}",
            )
        )
    token_value = (
        environment.get(TOKEN_FILE_ENV, "").strip()
        or environment.get(UPDATE_TOKEN_FILE_ENV, "").strip()
    )
    if token_value:
        token = Path(token_value).expanduser()
        if not token.is_file():
            return environment, "GitHub token file is unavailable"
        askpass = Path(tempfile.gettempdir()) / "resume-builder-git-askpass"
        if not askpass.is_file() or askpass.read_text(encoding="utf-8") != _ASKPASS:
            atomic_write_text(askpass, _ASKPASS)
            askpass.chmod(0o700)
        environment["GIT_ASKPASS"] = str(askpass)
        environment["GIT_ASKPASS_REQUIRE"] = "force"
        environment["RESUME_BUILDER_GIT_TOKEN_FILE"] = str(token)
    return environment, None


def _run(workspace: Path, *arguments: str, timeout: int = 60) -> subprocess.CompletedProcess[bytes]:
    environment, _error = _git_environment()
    return subprocess.run(
        ("git", *arguments),
        cwd=workspace,
        env=environment,
        check=False,
        capture_output=True,
        timeout=timeout,
    )


def _text(result: subprocess.CompletedProcess[bytes]) -> str:
    return result.stdout.decode("utf-8", "replace").strip()


def _paths(result: subprocess.CompletedProcess[bytes]) -> set[str]:
    return {item.decode("utf-8", "surrogateescape") for item in result.stdout.split(b"\0") if item}


def _result(
    status: str,
    detail: str,
    *,
    branch: str | None = None,
    previous_revision: str | None = None,
    revision: str | None = None,
    workspace_id: str | None = None,
) -> SyncResult:
    return SyncResult(
        status=status,
        detail=detail,
        checked_at=_now(),
        branch=branch,
        previous_revision=previous_revision,
        revision=revision,
        workspace_id=workspace_id,
    )


def sync_once(workspace: Path) -> SyncResult:
    """Fetch and fast-forward a workspace without replacing local work."""
    workspace = workspace.expanduser().resolve()
    identity = workspace_identity(workspace)
    _environment, credential_error = _git_environment()
    if credential_error:
        return _result("error", credential_error, workspace_id=identity)
    with workspace_lock(workspace, exclusive=True):
        return _sync_once_locked(workspace, identity)


def _sync_once_locked(workspace: Path, identity: str) -> SyncResult:
    """Perform one update while all workspace writers are excluded."""
    inside = _run(workspace, "rev-parse", "--is-inside-work-tree")
    if inside.returncode != 0 or _text(inside) != "true":
        return _result("not_configured", "Workspace is not Git-backed", workspace_id=identity)

    branch_result = _run(workspace, "branch", "--show-current")
    branch = _text(branch_result)
    if branch_result.returncode != 0 or not branch:
        return _result("blocked", "Workspace is not on a branch", workspace_id=identity)

    upstream_result = _run(
        workspace, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"
    )
    upstream = _text(upstream_result)
    if upstream_result.returncode != 0 or "/" not in upstream:
        return _result(
            "not_configured",
            "Current branch has no upstream",
            branch=branch,
            workspace_id=identity,
        )

    remote_result = _run(workspace, "config", "--get", f"branch.{branch}.remote")
    remote = _text(remote_result)
    if remote_result.returncode != 0 or not remote:
        return _result(
            "not_configured",
            "Current branch has no remote",
            branch=branch,
            workspace_id=identity,
        )
    merge_ref_result = _run(workspace, "config", "--get", f"branch.{branch}.merge")
    merge_ref = _text(merge_ref_result)
    if merge_ref_result.returncode != 0 or not merge_ref:
        return _result(
            "not_configured",
            "Current branch has no upstream ref",
            branch=branch,
            workspace_id=identity,
        )
    fetch = _run(workspace, "fetch", "--quiet", remote, merge_ref, timeout=120)
    if fetch.returncode != 0:
        return _result("error", "Remote update check failed", branch=branch, workspace_id=identity)

    head_result = _run(workspace, "rev-parse", "HEAD")
    upstream_head_result = _run(workspace, "rev-parse", "FETCH_HEAD")
    if head_result.returncode != 0 or upstream_head_result.returncode != 0:
        return _result("error", "Git revision check failed", branch=branch, workspace_id=identity)
    head = _text(head_result)
    upstream_head = _text(upstream_head_result)
    if head == upstream_head:
        return _result(
            "current",
            "Workspace is current",
            branch=branch,
            previous_revision=head,
            revision=head,
            workspace_id=identity,
        )

    ancestor = _run(workspace, "merge-base", "--is-ancestor", "HEAD", "FETCH_HEAD")
    if ancestor.returncode != 0:
        upstream_ancestor = _run(workspace, "merge-base", "--is-ancestor", "FETCH_HEAD", "HEAD")
        detail = (
            "Local commits have not been pushed"
            if upstream_ancestor.returncode == 0
            else "Local and upstream histories diverged"
        )
        return _result(
            "blocked",
            detail,
            branch=branch,
            previous_revision=head,
            revision=head,
            workspace_id=identity,
        )

    changed_upstream = _paths(
        _run(workspace, "diff", "--no-renames", "--name-only", "-z", "HEAD..FETCH_HEAD")
    )
    changed_local: set[str] = set()
    for arguments in (
        ("diff", "--no-renames", "--name-only", "-z"),
        ("diff", "--cached", "--no-renames", "--name-only", "-z"),
        ("ls-files", "--others", "--exclude-standard", "-z"),
    ):
        local = _run(workspace, *arguments)
        if local.returncode != 0:
            return _result(
                "error", "Local change check failed", branch=branch, workspace_id=identity
            )
        changed_local.update(_paths(local))
    if changed_upstream & changed_local:
        return _result(
            "blocked",
            "Upstream changes overlap local work",
            branch=branch,
            previous_revision=head,
            revision=head,
            workspace_id=identity,
        )

    merge = _run(workspace, "merge", "--ff-only", "--quiet", "--", "FETCH_HEAD", timeout=120)
    if merge.returncode != 0:
        return _result(
            "blocked",
            "Fast-forward could not be applied",
            branch=branch,
            previous_revision=head,
            revision=head,
            workspace_id=identity,
        )
    revision_result = _run(workspace, "rev-parse", "HEAD")
    revision = _text(revision_result) if revision_result.returncode == 0 else upstream_head
    return _result(
        "updated",
        "Workspace updated",
        branch=branch,
        previous_revision=head,
        revision=revision,
        workspace_id=identity,
    )


def read_sync_status(
    state_file: Path,
    *,
    workspace: Path | None = None,
    max_age_seconds: float | None = None,
) -> dict[str, object]:
    """Return the last content-free worker status."""
    if not state_file.is_file():
        return {"status": "waiting", "detail": "Update check has not run yet"}
    try:
        value = json.loads(state_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"status": "unknown", "detail": "Update status is unavailable"}
    if (
        not isinstance(value, dict)
        or not isinstance(value.get("status"), str)
        or not isinstance(value.get("detail"), str)
    ):
        return {"status": "unknown", "detail": "Update status is unavailable"}
    if workspace is not None and value.get("workspace_id") != workspace_identity(workspace):
        return {"status": "waiting", "detail": "Update check has not run for this workspace"}
    if max_age_seconds is not None:
        try:
            checked_at = datetime.fromisoformat(
                str(value.get("checked_at", "")).replace("Z", "+00:00")
            )
        except ValueError:
            return {"status": "unknown", "detail": "Update status has no valid timestamp"}
        age = (datetime.now(timezone.utc) - checked_at).total_seconds()
        if age > max_age_seconds:
            return {"status": "stale", "detail": "Workspace update check is overdue"}
    return value


def run_forever(
    workspace: Path,
    state_file: Path,
    *,
    interval_seconds: float,
    stop: threading.Event,
) -> None:
    """Run serialized update checks until the appliance stops."""
    state_file.parent.mkdir(parents=True, exist_ok=True)
    lock_path = state_file.with_suffix(".lock")
    with lock_path.open("a+b") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("Workspace sync already running", flush=True)
            return
        atomic_write_json(
            state_file,
            asdict(
                _result(
                    "checking",
                    "Checking workspace for updates",
                    workspace_id=workspace_identity(workspace),
                )
            ),
        )
        while not stop.is_set():
            try:
                result = sync_once(workspace)
            except (OSError, subprocess.SubprocessError):
                result = _result("error", "Workspace update check failed")
            atomic_write_json(state_file, asdict(result))
            print(f"Workspace sync: {result.status} - {result.detail}", flush=True)
            stop.wait(max(interval_seconds, 30.0))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Safely update a Git-backed workspace")
    parser.add_argument("--workspace", type=Path)
    parser.add_argument("--state-file", type=Path, required=True)
    parser.add_argument(
        "--interval-seconds",
        type=float,
        default=os.environ.get(SYNC_INTERVAL_ENV, str(DEFAULT_SYNC_INTERVAL_SECONDS)),
    )
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args(argv)
    workspace = args.workspace.expanduser().resolve() if args.workspace else discover_workspace()
    if workspace is None:
        parser.error("no Resume Builder workspace could be discovered")
    if args.once:
        result = sync_once(workspace)
        atomic_write_json(args.state_file, asdict(result))
        print(json.dumps(asdict(result), indent=2))
        return 0 if result.status in {"current", "updated", "not_configured"} else 1
    stop = threading.Event()
    signal.signal(signal.SIGINT, lambda _signum, _frame: stop.set())
    signal.signal(signal.SIGTERM, lambda _signum, _frame: stop.set())
    run_forever(
        workspace,
        args.state_file,
        interval_seconds=args.interval_seconds,
        stop=stop,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
