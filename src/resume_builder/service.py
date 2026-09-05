"""Run the portal and existing background services as one appliance."""

from __future__ import annotations

import argparse
import os
import shlex
import shutil
import signal
import subprocess
import sys
import threading
from collections.abc import Sequence
from pathlib import Path

from .agent_config import DEFAULT_AGENT_CONFIG, load_agent_config
from .agent_telegram_setup import resolve_telegram_token
from .atomic import atomic_write_text
from .automation import DEFAULT_CONFIG, load_config
from .workspace_state import discover_workspace

SUPERVISOR_CONFIG_ENV = "RESUME_BUILDER_SUPERVISOR_CONFIG"


def _command(parts: Sequence[str | Path]) -> str:
    return " ".join(shlex.quote(str(part)).replace("%", "%%") for part in parts)


def render_supervisor_config(
    *,
    workspace: Path,
    host: str,
    port: int,
    static_dir: Path,
    state_dir: Path = Path("/state"),
    scheduler_autostart: bool = True,
    gmail_autostart: bool = True,
) -> str:
    """Render the small, explicit process group used by the container."""
    portal = _command(
        (
            "resume-builder-web",
            "--workspace",
            workspace,
            "--host",
            host,
            "--port",
            str(port),
            "--static-dir",
            static_dir,
        )
    )
    scheduler = _command(("resume-builder", "automation", "run", "--task", "jobs"))
    gmail = _command(("resume-builder", "automation", "run", "--task", "gmail"))
    telegram = _command(
        (
            sys.executable,
            "-m",
            "resume_builder.service",
            "telegram-worker",
            "--workspace",
            workspace,
        )
    )
    directory = str(workspace).replace("%", "%%")
    pidfile = str(state_dir / "resume-builder.pid").replace("%", "%%")
    childlogdir = str(state_dir).replace("%", "%%")
    socket = "/tmp/resume-builder-supervisor.sock"
    scheduler_start = str(scheduler_autostart).lower()
    gmail_start = str(gmail_autostart).lower()
    return f"""\
[unix_http_server]
file={socket}
chmod=0700

[supervisord]
nodaemon=true
logfile=/dev/null
pidfile={pidfile}
childlogdir={childlogdir}

[rpcinterface:supervisor]
supervisor.rpcinterface_factory=supervisor.rpcinterface:make_main_rpcinterface

[supervisorctl]
serverurl=unix://{socket}

[program:portal]
command={portal}
directory={directory}
priority=10
autostart=true
autorestart=true
startsecs=2
stopasgroup=true
killasgroup=true
stdout_logfile=/dev/fd/1
stdout_logfile_maxbytes=0
stderr_logfile=/dev/fd/2
stderr_logfile_maxbytes=0

[program:scheduler]
command={scheduler}
directory={directory}
priority=20
autostart={scheduler_start}
autorestart=true
startsecs=2
stopasgroup=true
killasgroup=true
stdout_logfile=/dev/fd/1
stdout_logfile_maxbytes=0
stderr_logfile=/dev/fd/2
stderr_logfile_maxbytes=0

[program:gmail]
command={gmail}
directory={directory}
priority=25
autostart={gmail_start}
autorestart=true
startsecs=2
stopasgroup=true
killasgroup=true
stdout_logfile=/dev/fd/1
stdout_logfile_maxbytes=0
stderr_logfile=/dev/fd/2
stderr_logfile_maxbytes=0

[program:telegram]
command={telegram}
directory={directory}
priority=30
autostart=true
autorestart=true
startsecs=2
stopasgroup=true
killasgroup=true
stdout_logfile=/dev/fd/1
stdout_logfile_maxbytes=0
stderr_logfile=/dev/fd/2
stderr_logfile_maxbytes=0
"""


def managed_service_status(service: str) -> str | None:
    """Return a managed process state, or None outside the appliance."""
    config = os.environ.get(SUPERVISOR_CONFIG_ENV)
    supervisorctl = shutil.which("supervisorctl")
    if not config or supervisorctl is None:
        return None
    result = subprocess.run(
        (supervisorctl, "-c", config, "status", service),
        capture_output=True,
        check=False,
        text=True,
        timeout=10,
    )
    output = f"{result.stdout}\n{result.stderr}".upper()
    for state in ("RUNNING", "STARTING", "STOPPED", "EXITED", "FATAL", "BACKOFF"):
        if state in output:
            return state.lower()
    raise RuntimeError("Could not read the managed scheduler state.")


def set_scheduler_enabled(enabled: bool) -> None:
    """Start or stop the appliance's scheduled job-scraping process."""
    config = os.environ.get(SUPERVISOR_CONFIG_ENV)
    supervisorctl = shutil.which("supervisorctl")
    if not config or supervisorctl is None:
        return
    current = managed_service_status("scheduler")
    running = current in {"running", "starting"}
    if running == enabled:
        return
    action = "start" if enabled else "stop"
    result = subprocess.run(
        (supervisorctl, "-c", config, action, "scheduler"),
        capture_output=True,
        check=False,
        text=True,
        timeout=20,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Could not {action} automatic scraping.")


def telegram_configuration_status(workspace: Path) -> str:
    """Return a content-free readiness state for the optional Telegram worker."""
    config_path = workspace / DEFAULT_AGENT_CONFIG
    if not config_path.is_file():
        return "not_configured"
    try:
        config = load_agent_config(config_path)
    except (OSError, ValueError):
        return "error"
    channel = config.channels.telegram
    if not channel.enabled:
        return "disabled"
    if not channel.allowed_user_ids or not channel.allowed_chat_ids:
        return "not_configured"
    return "ready" if resolve_telegram_token(channel) else "not_configured"


def _telegram_worker(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--poll-seconds", type=float, default=15.0)
    args = parser.parse_args(argv)
    stop = threading.Event()

    def stop_worker(_signum: int, _frame: object) -> None:
        stop.set()

    signal.signal(signal.SIGTERM, stop_worker)
    signal.signal(signal.SIGINT, stop_worker)
    previous = ""
    while not stop.is_set():
        status = telegram_configuration_status(args.workspace)
        if status == "ready":
            from . import agent

            try:
                result = agent.main(["serve", "--channel", "telegram"])
            except (OSError, RuntimeError, ValueError) as exc:
                print(f"Telegram worker failed: {exc.__class__.__name__}", flush=True)
            else:
                print(f"Telegram worker stopped with status {result}", flush=True)
            stop.wait(max(args.poll_seconds, 1.0))
            continue
        if status != previous:
            print(f"Telegram worker waiting: {status}", flush=True)
            previous = status
        stop.wait(max(args.poll_seconds, 1.0))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Start the complete local appliance under one process supervisor."""
    parser = argparse.ArgumentParser(description="Run the Resume Builder portal and services")
    parser.add_argument("--workspace", type=Path)
    parser.add_argument("--host", default=os.environ.get("RESUME_BUILDER_WEB_HOST", "0.0.0.0"))
    parser.add_argument(
        "--port", type=int, default=int(os.environ.get("RESUME_BUILDER_WEB_PORT", "8765"))
    )
    parser.add_argument(
        "--static-dir",
        type=Path,
        default=Path(os.environ.get("RESUME_BUILDER_WEB_STATIC_DIR", "/app/web/dist")),
    )
    args = parser.parse_args(argv)
    workspace = args.workspace.expanduser().resolve() if args.workspace else discover_workspace()
    if workspace is None:
        parser.error("no Resume Builder workspace could be discovered")
    supervisor = shutil.which("supervisord")
    if supervisor is None:
        parser.error('service dependencies are missing; install with pip install -e ".[web]"')
    state_root = Path(os.environ.get("RESUME_BUILDER_STATE_DIR", "/state")).expanduser()
    state_root.mkdir(parents=True, exist_ok=True)
    config_path = state_root / "supervisord.conf"
    scheduler_autostart = False
    gmail_autostart = False
    automation_config = workspace / DEFAULT_CONFIG
    if automation_config.is_file():
        try:
            configured = load_config(automation_config)
        except (OSError, ValueError):
            pass
        else:
            scheduler_autostart = configured.jobs.enabled
            gmail_autostart = configured.gmail.enabled
    os.environ[SUPERVISOR_CONFIG_ENV] = str(config_path)
    atomic_write_text(
        config_path,
        render_supervisor_config(
            workspace=workspace,
            host=args.host,
            port=args.port,
            static_dir=args.static_dir,
            state_dir=state_root,
            scheduler_autostart=scheduler_autostart,
            gmail_autostart=gmail_autostart,
        ),
    )
    os.execv(supervisor, (supervisor, "-n", "-c", str(config_path)))
    return 2  # pragma: no cover - os.execv replaces the process on success.


def _module_main(argv: Sequence[str]) -> int:
    if argv and argv[0] == "telegram-worker":
        return _telegram_worker(argv[1:])
    return main(argv)


if __name__ == "__main__":
    raise SystemExit(_module_main(sys.argv[1:]))
