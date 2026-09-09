from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from resume_builder import web_schedule
from resume_builder.automation import DEFAULT_CONFIG, load_config, render_default_config


def test_missing_schedule_is_reported_without_creating_configuration(tmp_path: Path) -> None:
    result = web_schedule.schedule_status(
        tmp_path,
        now=datetime(2026, 9, 5, 11, 0, tzinfo=UTC),
        state_path=tmp_path / "state.sqlite",
    )

    assert result["configured"] is False
    assert result["enabled"] is False
    assert result["times"] == ["08:00"]
    assert result["timezone"] == "America/New_York"
    assert result["next_run"] is None
    assert result["service_status"] == "offline"
    assert result["screening_enabled"] is False
    assert result["screening_max_jobs"] == 6
    assert result["current_stage"] == "idle"
    assert not (tmp_path / DEFAULT_CONFIG).exists()


def test_schedule_reports_searching_and_screening_artifact_stages(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / DEFAULT_CONFIG
    path.parent.mkdir(parents=True)
    path.write_text(
        render_default_config("America/New_York").replace("enabled: false", "enabled: true", 1),
        encoding="utf-8",
    )
    monkeypatch.setattr(web_schedule, "background_screening_configured", lambda _root: True)
    refresh = tmp_path / "job-search/latest-refresh.json"
    refresh.parent.mkdir(parents=True)
    refresh.write_text(
        json.dumps({"status": "in_progress", "started_at": "2026-09-05T12:00:00+00:00"}),
        encoding="utf-8",
    )

    searching = web_schedule.schedule_status(tmp_path, state_path=tmp_path / "state.sqlite")
    assert searching["current_stage"] == "searching"

    refresh.write_text(
        json.dumps({"status": "complete", "started_at": "2026-09-05T12:00:00+00:00"}),
        encoding="utf-8",
    )
    screening = web_schedule.schedule_status(tmp_path, state_path=tmp_path / "state.sqlite")
    assert screening["current_stage"] == "screening"


def test_stale_replenishment_state_does_not_report_screening(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / DEFAULT_CONFIG
    path.parent.mkdir(parents=True)
    path.write_text(
        render_default_config("America/New_York").replace("enabled: false", "enabled: true", 1),
        encoding="utf-8",
    )
    monkeypatch.setattr(web_schedule, "background_screening_configured", lambda _root: True)
    refresh = tmp_path / "job-search/latest-refresh.json"
    refresh.parent.mkdir(parents=True)
    refresh.write_text(
        json.dumps({"status": "complete", "started_at": "2026-09-05T12:00:00+00:00"}),
        encoding="utf-8",
    )
    replenishment = tmp_path / web_schedule.DEFAULT_REPLENISHMENT_STATE
    replenishment.write_text(json.dumps({"status": "running"}), encoding="utf-8")

    status = web_schedule.schedule_status(tmp_path, state_path=tmp_path / "state.sqlite")

    assert status["current_stage"] == "idle"


def test_stale_replenishment_state_does_not_report_live_screening(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / DEFAULT_CONFIG
    path.parent.mkdir(parents=True)
    path.write_text(
        render_default_config("America/New_York").replace("enabled: false", "enabled: true", 1),
        encoding="utf-8",
    )
    monkeypatch.setattr(web_schedule, "background_screening_configured", lambda _root: True)
    refresh = tmp_path / "job-search/latest-refresh.json"
    refresh.parent.mkdir(parents=True)
    refresh.write_text(
        json.dumps({"status": "complete", "started_at": "2026-09-05T12:00:00+00:00"}),
        encoding="utf-8",
    )
    replenishment = tmp_path / web_schedule.DEFAULT_REPLENISHMENT_STATE
    replenishment.write_text(json.dumps({"status": "running"}), encoding="utf-8")

    status = web_schedule.schedule_status(tmp_path, state_path=tmp_path / "state.sqlite")

    assert status["current_stage"] == "idle"


def test_save_schedule_reuses_automation_config_and_preserves_other_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / DEFAULT_CONFIG
    path.parent.mkdir(parents=True)
    path.write_text(render_default_config("America/Chicago"), encoding="utf-8")

    actions: list[bool] = []
    monkeypatch.setattr(web_schedule, "set_scheduler_enabled", actions.append)

    result = web_schedule.save_schedule(
        tmp_path,
        {"enabled": False, "times": ["17:30", "08:15", "08:15"]},
        now=datetime(2026, 9, 5, 11, 0, tzinfo=UTC),
        state_path=tmp_path / "state.sqlite",
    )

    saved = load_config(path)
    assert saved.jobs.enabled is False
    assert [item.strftime("%H:%M") for item in saved.jobs.times] == ["08:15", "17:30"]
    assert saved.gmail.enabled is True
    assert saved.notifications.sink == "console"
    assert result["configured"] is True
    assert result["next_run"] is None
    assert actions == [False]


def test_enabling_schedule_starts_managed_scheduler(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    actions: list[bool] = []
    monkeypatch.setattr(web_schedule, "set_scheduler_enabled", actions.append)

    web_schedule.save_schedule(
        tmp_path,
        {"enabled": True, "times": ["08:00"]},
        state_path=tmp_path / "state.sqlite",
    )

    assert actions == [True]
    assert load_config(tmp_path / DEFAULT_CONFIG).jobs.enabled is True


def test_save_schedule_persists_bounded_background_screening(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(web_schedule, "set_scheduler_enabled", lambda _enabled: None)

    result = web_schedule.save_schedule(
        tmp_path,
        {
            "enabled": True,
            "times": ["08:00"],
            "screening_enabled": True,
            "screening_max_jobs": 10,
        },
        state_path=tmp_path / "state.sqlite",
    )

    saved = load_config(tmp_path / DEFAULT_CONFIG)
    assert saved.jobs.semantic_screening_enabled is True
    assert saved.jobs.semantic_screening_max_jobs == 10
    assert result["screening_enabled"] is True
    assert result["screening_max_jobs"] == 10


def test_service_control_failure_restores_previous_schedule(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / DEFAULT_CONFIG
    path.parent.mkdir(parents=True)
    original = render_default_config("America/New_York", jobs_enabled=False, gmail_enabled=True)
    path.write_text(original, encoding="utf-8")

    def fail_control(_enabled: bool) -> None:
        raise RuntimeError("scheduler control failed")

    monkeypatch.setattr(web_schedule, "set_scheduler_enabled", fail_control)

    with pytest.raises(RuntimeError, match="scheduler control failed"):
        web_schedule.save_schedule(
            tmp_path,
            {"enabled": True, "times": ["09:00"]},
            state_path=tmp_path / "state.sqlite",
        )

    assert path.read_text(encoding="utf-8") == original


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"enabled": "yes", "times": ["08:00"]}, "enabled must be a boolean"),
        ({"enabled": True, "times": []}, "at least one"),
        ({"enabled": True, "times": ["8am"]}, "HH:MM"),
        (
            {"enabled": True, "times": ["08:00"], "screening_enabled": "yes"},
            "screening_enabled must be a boolean",
        ),
        (
            {"enabled": True, "times": ["08:00"], "screening_max_jobs": 26},
            "screening_max_jobs must be from 1 to 25",
        ),
    ],
)
def test_save_schedule_rejects_invalid_values_without_writing(
    tmp_path: Path, payload: dict[str, object], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        web_schedule.save_schedule(tmp_path, payload, state_path=tmp_path / "state.sqlite")
    assert not (tmp_path / DEFAULT_CONFIG).exists()
