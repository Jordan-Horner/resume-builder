from pathlib import Path

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
    assert "[program:telegram]" in rendered
    assert "resume-builder-web" in rendered
    assert "resume-builder automation run" in rendered
    assert "resume_builder.service telegram-worker" in rendered
    assert "stopasgroup=true" in rendered
    assert "killasgroup=true" in rendered


def test_managed_telegram_waits_when_configuration_is_absent(tmp_path: Path) -> None:
    assert telegram_configuration_status(tmp_path) == "not_configured"
