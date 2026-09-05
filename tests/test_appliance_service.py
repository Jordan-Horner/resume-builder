from pathlib import Path

from resume_builder import service
from resume_builder.automation import load_config, render_default_config
from resume_builder.service import render_supervisor_config, telegram_configuration_status


def test_portal_managed_automation_defaults_are_inactive(tmp_path: Path) -> None:
    path = tmp_path / "config.yml"
    path.write_text(
        render_default_config(
            "America/New_York",
            jobs_enabled=False,
            gmail_enabled=False,
        ),
        encoding="utf-8",
    )

    config = load_config(path)

    assert config.jobs.enabled is False
    assert config.gmail.enabled is False


def test_supervisor_runs_portal_scheduler_and_managed_telegram(tmp_path: Path) -> None:
    rendered = render_supervisor_config(
        workspace=tmp_path / "Private Workspace",
        host="0.0.0.0",
        port=8765,
        static_dir=Path("/app/web/dist"),
    )

    assert "[program:portal]" in rendered
    assert "[program:scheduler]" in rendered
    assert "[program:gmail]" in rendered
    assert "[program:telegram]" in rendered
    assert "resume-builder-web" in rendered
    assert "resume-builder automation run --task jobs" in rendered
    assert "resume-builder automation run --task gmail" in rendered
    assert "resume_builder.service telegram-worker" in rendered
    assert "[unix_http_server]" in rendered
    assert "[supervisorctl]" in rendered
    assert "stopasgroup=true" in rendered
    assert "killasgroup=true" in rendered


def test_supervisor_can_start_jobs_independently_from_gmail(tmp_path: Path) -> None:
    rendered = render_supervisor_config(
        workspace=tmp_path,
        host="0.0.0.0",
        port=8765,
        static_dir=Path("/app/web/dist"),
        scheduler_autostart=False,
        gmail_autostart=True,
    )

    scheduler = rendered.split("[program:scheduler]", 1)[1].split("[program:gmail]", 1)[0]
    gmail = rendered.split("[program:gmail]", 1)[1].split("[program:telegram]", 1)[0]
    assert "autostart=false" in scheduler
    assert "autostart=true" in gmail


def test_managed_telegram_waits_when_configuration_is_absent(tmp_path: Path) -> None:
    assert telegram_configuration_status(tmp_path) == "not_configured"


def test_schedule_toggle_starts_the_actual_managed_process(tmp_path: Path, monkeypatch) -> None:
    calls: list[tuple[str, ...]] = []
    monkeypatch.setenv(service.SUPERVISOR_CONFIG_ENV, str(tmp_path / "supervisord.conf"))
    monkeypatch.setattr(service.shutil, "which", lambda _name: "/usr/bin/supervisorctl")

    def run(command, **_kwargs):
        calls.append(tuple(command))
        output = "scheduler STOPPED" if "status" in command else "scheduler STARTED"
        return service.subprocess.CompletedProcess(command, 0, stdout=output, stderr="")

    monkeypatch.setattr(service.subprocess, "run", run)

    service.set_scheduler_enabled(True)

    assert calls[0][-2:] == ("status", "scheduler")
    assert calls[1][-2:] == ("start", "scheduler")
