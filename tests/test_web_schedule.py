from __future__ import annotations

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
    assert not (tmp_path / DEFAULT_CONFIG).exists()


def test_save_schedule_reuses_automation_config_and_preserves_other_settings(
    tmp_path: Path,
) -> None:
    path = tmp_path / DEFAULT_CONFIG
    path.parent.mkdir(parents=True)
    path.write_text(render_default_config("America/Chicago"), encoding="utf-8")

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


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"enabled": "yes", "times": ["08:00"]}, "enabled must be a boolean"),
        ({"enabled": True, "times": []}, "at least one"),
        ({"enabled": True, "times": ["8am"]}, "HH:MM"),
    ],
)
def test_save_schedule_rejects_invalid_values_without_writing(
    tmp_path: Path, payload: dict[str, object], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        web_schedule.save_schedule(tmp_path, payload, state_path=tmp_path / "state.sqlite")
    assert not (tmp_path / DEFAULT_CONFIG).exists()
