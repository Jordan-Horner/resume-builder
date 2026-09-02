"""Tests for low-noise scheduled automation and notifications."""

from __future__ import annotations

import json
import sys
import threading
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from resume_builder import jobs as jobs_module
from resume_builder.automation import (
    LOGGER,
    AutomationService,
    AutomationState,
    JobSchedule,
    Notification,
    NotificationConfig,
    TaskExecutionError,
    _configure_logging,
    _in_quiet_hours,
    _run_jobs,
    configure,
    gmail_notification,
    job_notification,
    load_config,
    next_job_run,
    render_default_config,
    run_forever,
)
from resume_builder.automation import main as automation_main


def write_config(path: Path, **updates: object) -> None:
    payload = {
        "schema_version": 1,
        "timezone": "America/New_York",
        "jobs": {"enabled": True, "times": ["08:00", "17:00"], "run_on_start": True},
        "gmail": {"enabled": True, "every_hours": 4, "run_on_start": True},
        "notifications": {"sink": "console", "privacy": "summary", "max_items": 10},
    }
    payload.update(updates)
    path.write_text(json.dumps(payload), encoding="utf-8")


def notification_config(*, privacy: str = "summary") -> NotificationConfig:
    return NotificationConfig(
        sink="console",
        privacy=privacy,
        webhook_env="RESUME_BUILDER_DISCORD_WEBHOOK",
        max_items=10,
        quiet_start=time(21),
        quiet_end=time(7),
    )


@pytest.fixture
def configured_logs() -> Iterator[Callable[[], None]]:
    yield _configure_logging
    for handler in LOGGER.handlers[:]:
        LOGGER.removeHandler(handler)
        handler.close()
    LOGGER.propagate = True


def log_events(output: str) -> list[dict[str, object]]:
    return [json.loads(line) for line in output.splitlines() if line.startswith("{")]


def test_default_config_uses_daily_jobs_and_low_frequency_gmail(tmp_path: Path) -> None:
    path = tmp_path / "config.yml"
    path.write_text(render_default_config("America/New_York"), encoding="utf-8")

    config = load_config(path)

    assert config.jobs.times == (time(8),)
    assert config.gmail.every == timedelta(hours=4)
    assert config.notifications.sink == "console"


def test_config_accepts_two_daily_job_times(tmp_path: Path) -> None:
    path = tmp_path / "config.yml"
    write_config(path)

    config = load_config(path)

    assert config.jobs.times == (time(8), time(17))
    assert str(config.timezone) == "America/New_York"


def test_configure_updates_daily_times_and_gmail_interval(tmp_path: Path) -> None:
    path = tmp_path / "config.yml"
    path.write_text(render_default_config("America/New_York"), encoding="utf-8")

    updated = configure(
        path,
        load_config(path),
        timezone=None,
        job_times=["07:30", "16:30"],
        gmail_hours=6,
        notification_sink="discord",
        privacy="counts-only",
    )

    assert updated.jobs.times == (time(7, 30), time(16, 30))
    assert updated.gmail.every == timedelta(hours=6)
    assert updated.notifications.sink == "discord"
    assert "RESUME_BUILDER_DISCORD_WEBHOOK" in path.read_text(encoding="utf-8")
    assert "discord.com" not in path.read_text(encoding="utf-8")


def test_configure_rejects_invalid_schedule_without_replacing_config(tmp_path: Path) -> None:
    path = tmp_path / "config.yml"
    path.write_text(render_default_config("America/New_York"), encoding="utf-8")
    original = path.read_text(encoding="utf-8")

    with pytest.raises(ValueError, match=r"jobs\.times values must use HH:MM"):
        configure(
            path,
            load_config(path),
            timezone=None,
            job_times=["not-a-time"],
            gmail_hours=None,
            notification_sink=None,
            privacy=None,
        )

    assert path.read_text(encoding="utf-8") == original


def test_config_rejects_unknown_settings(tmp_path: Path) -> None:
    path = tmp_path / "config.yml"
    write_config(path, unexpected=True)

    with pytest.raises(ValueError, match="unknown automation settings"):
        load_config(path)


def test_next_job_run_obeys_local_timezone() -> None:
    schedule = JobSchedule(True, (time(8), time(17)), True, 50)
    now = datetime(2026, 9, 2, 15, 0, tzinfo=UTC)  # 11:00 in New York

    next_run = next_job_run(now, schedule, ZoneInfo("America/New_York"))

    assert next_run == datetime(2026, 9, 2, 21, 0, tzinfo=UTC)


def test_quiet_hours_cross_midnight() -> None:
    config = notification_config()
    assert _in_quiet_hours(
        datetime(2026, 9, 3, 3, 0, tzinfo=UTC),
        ZoneInfo("America/New_York"),
        config,
    )
    assert not _in_quiet_hours(
        datetime(2026, 9, 3, 16, 0, tzinfo=UTC),
        ZoneInfo("America/New_York"),
        config,
    )


def test_job_notification_ignores_empty_results_and_explains_matches() -> None:
    match = {
        "id": "job-1",
        "title": "Cloud Support Engineer",
        "company": "Example",
        "url": "https://example.invalid/jobs/1",
        "prescreen": {
            "interest": {
                "desired_title_terms": ["support engineer"],
                "interest_terms": ["cloud"],
            }
        },
    }

    assert job_notification([], notification_config()) is None
    result = job_notification([match], notification_config())

    assert result is not None
    assert "Cloud Support Engineer at Example" in result.body
    assert "support engineer, cloud" in result.body


def test_counts_only_notification_omits_company_and_role() -> None:
    result = gmail_notification(
        {
            "changes": [
                {
                    "application_id": "APP-example",
                    "action": "interview",
                    "company": "Example",
                    "role": "Support Engineer",
                    "effective_on": "2026-09-02",
                }
            ]
        },
        notification_config(privacy="counts-only"),
    )

    assert result is not None
    assert result.priority == "high"
    assert "Example" not in result.body
    assert "Support Engineer" not in result.body


def test_outbox_deduplicates_and_survives_delivery_failure(tmp_path: Path) -> None:
    state = AutomationState(tmp_path / "runtime" / "automation.sqlite")
    notification = Notification("same-event", "Update", "One change")

    state.enqueue(notification)
    state.enqueue(notification)

    assert state.pending_notifications() == [notification]
    state.delivery_failed(notification.key, "TimeoutError")
    assert state.pending_notifications() == [notification]
    state.delivery_succeeded(notification.key)
    assert state.pending_notifications() == []


def test_pending_routine_notification_does_not_make_status_unhealthy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / ".resume-builder.json").write_text("{}", encoding="utf-8")
    config_path = workspace / "automation" / "config.yml"
    config_path.parent.mkdir()
    config_path.write_text(render_default_config("America/New_York"), encoding="utf-8")
    state_path = tmp_path / "runtime" / "automation.sqlite"
    state = AutomationState(state_path)
    state.enqueue(Notification("routine", "Jobs", "One match"))
    monkeypatch.chdir(workspace)

    assert automation_main(["--state", str(state_path), "status", "--healthcheck"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["healthy"] is True
    assert payload["pending_notifications"] == 1


def test_quiet_hours_delay_routine_alerts_but_not_interviews(tmp_path: Path, capsys) -> None:
    config_path = tmp_path / "config.yml"
    config_path.write_text(render_default_config("America/New_York"), encoding="utf-8")
    state = AutomationState(tmp_path / "runtime" / "automation.sqlite")
    state.enqueue(Notification("routine", "Jobs", "One match"))
    state.enqueue(Notification("urgent", "Interview", "Respond soon", priority="high"))
    service = AutomationService(workspace=tmp_path, config=load_config(config_path), state=state)

    delivered = service.deliver_pending(datetime(2026, 9, 3, 3, 0, tzinfo=UTC))

    assert delivered is True
    assert [item.key for item in state.pending_notifications()] == ["routine"]
    assert "Interview" in capsys.readouterr().out


def test_run_once_runs_gmail_even_when_jobs_fail(
    tmp_path: Path, capsys, configured_logs: Callable[[], None]
) -> None:
    configured_logs()
    config_path = tmp_path / "config.yml"
    config_path.write_text(render_default_config("America/New_York"), encoding="utf-8")
    called: list[str] = []

    def fail_jobs() -> dict[str, object]:
        called.append("jobs")
        raise RuntimeError("provider details must not be persisted")

    def run_gmail() -> dict[str, object]:
        called.append("gmail")
        return {"changes": [], "examined": 0}

    service = AutomationService(
        workspace=tmp_path,
        config=load_config(config_path),
        state=AutomationState(tmp_path / "runtime" / "automation.sqlite"),
        job_runner=fail_jobs,
        gmail_runner=run_gmail,
    )

    assert service.run_once(("jobs", "gmail")) is False
    assert called == ["jobs", "gmail"]
    error_events = log_events(capsys.readouterr().err)
    assert error_events[0]["event"] == "scan_failed"
    assert error_events[0]["error_category"] == "RuntimeError"
    assert service.state.last_run("jobs")["error_category"] == "RuntimeError"


def test_task_history_excludes_job_match_details(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yml"
    config_path.write_text(render_default_config("America/New_York"), encoding="utf-8")
    state = AutomationState(tmp_path / "runtime" / "automation.sqlite")
    service = AutomationService(
        workspace=tmp_path,
        config=load_config(config_path),
        state=state,
        job_runner=lambda: {
            "new_jobs": 1,
            "interesting_jobs": 1,
            "matches": [
                {
                    "id": "job-1",
                    "title": "Support Engineer",
                    "company": "Example",
                    "prescreen": {"interest": {}},
                }
            ],
        },
    )

    assert service.run_task("jobs") is True

    history = state.last_run("jobs")
    assert history is not None
    assert "matches" not in history["summary"]


def test_task_logs_privacy_safe_start_and_summary(
    tmp_path: Path, capsys, configured_logs: Callable[[], None]
) -> None:
    configured_logs()
    config_path = tmp_path / "config.yml"
    config_path.write_text(render_default_config("America/New_York"), encoding="utf-8")
    service = AutomationService(
        workspace=tmp_path,
        config=load_config(config_path),
        state=AutomationState(tmp_path / "runtime" / "automation.sqlite"),
        gmail_runner=lambda: {
            "examined": 3,
            "changes": [],
            "private_detail": "must not be logged",
        },
    )

    assert service.run_task("gmail") is True
    events = log_events(capsys.readouterr().out)
    assert [event["event"] for event in events] == ["scan_started", "scan_completed"]
    assert events[0]["task"] == "gmail"
    assert events[0]["trigger"] == "manual"
    assert isinstance(events[0]["run_id"], str)
    assert events[1]["status"] == "success"
    assert events[1]["examined"] == 3
    assert "must not be logged" not in json.dumps(events)


def test_service_logs_startup_schedule_before_waiting(
    tmp_path: Path, capsys, configured_logs: Callable[[], None]
) -> None:
    configured_logs()
    config_path = tmp_path / "config.yml"
    config_path.write_text(render_default_config("America/New_York"), encoding="utf-8")
    service = AutomationService(
        workspace=tmp_path,
        config=load_config(config_path),
        state=AutomationState(tmp_path / "runtime" / "automation.sqlite"),
    )
    stop = threading.Event()
    stop.set()

    assert run_forever(service, stop) == 0
    events = log_events(capsys.readouterr().out)
    assert [event["event"] for event in events] == ["service_started", "service_stopped"]
    assert events[0]["state"] == "ready"
    assert events[0]["jobs_previous"] == "never"
    assert isinstance(events[0]["jobs_next"], str)
    assert isinstance(events[0]["gmail_next"], str)
    assert events[0]["log_version"] == 1


def test_failure_log_omits_exception_message(
    tmp_path: Path, capsys, configured_logs: Callable[[], None]
) -> None:
    configured_logs()
    config_path = tmp_path / "config.yml"
    config_path.write_text(render_default_config("America/New_York"), encoding="utf-8")

    def fail() -> dict[str, object]:
        raise RuntimeError("private provider response must not be logged")

    service = AutomationService(
        workspace=tmp_path,
        config=load_config(config_path),
        state=AutomationState(tmp_path / "runtime" / "automation.sqlite"),
        job_runner=fail,
    )

    assert service.run_task("jobs") is False
    captured = capsys.readouterr()
    events = log_events(captured.err)
    assert events[0]["event"] == "scan_failed"
    assert events[0]["stage"] == "task"
    assert events[0]["error_category"] == "RuntimeError"
    assert "private provider response" not in captured.err
    assert "test_automation.py" in str(events[0]["stack"])


def test_job_cli_output_is_suppressed_and_failure_stage_is_safe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    config_path = tmp_path / "config.yml"
    config_path.write_text(render_default_config("America/New_York"), encoding="utf-8")
    manifest = tmp_path / "latest-refresh.json"
    manifest.write_text('{"status":"failed"}', encoding="utf-8")
    monkeypatch.setattr(jobs_module, "DEFAULT_LATEST_REFRESH", manifest)
    monkeypatch.setattr(jobs_module, "DEFAULT_NEW_OUTPUT", tmp_path / "new-jobs.json")

    def noisy_failure(_argv: list[str]) -> int:
        print("private provider response")
        print("private provider error", file=sys.stderr)
        return 2

    monkeypatch.setattr(jobs_module, "main", noisy_failure)

    with pytest.raises(TaskExecutionError) as captured_error:
        _run_jobs(load_config(config_path))

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""
    assert captured_error.value.stage == "collect"
    assert captured_error.value.error_category == "RuntimeError"


def test_unfinalized_job_manifest_is_a_publish_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = tmp_path / "config.yml"
    config_path.write_text(render_default_config("America/New_York"), encoding="utf-8")
    manifest = tmp_path / "latest-refresh.json"
    manifest.write_text('{"status":"processing"}', encoding="utf-8")
    prior_output = tmp_path / "new-jobs.json"
    prior_output.write_text('{"jobs":[]}', encoding="utf-8")
    monkeypatch.setattr(jobs_module, "DEFAULT_LATEST_REFRESH", manifest)
    monkeypatch.setattr(jobs_module, "DEFAULT_NEW_OUTPUT", prior_output)
    monkeypatch.setattr(jobs_module, "main", lambda _argv: 2)

    with pytest.raises(TaskExecutionError) as captured_error:
        _run_jobs(load_config(config_path))

    assert captured_error.value.stage == "publish"


def test_restart_with_persistent_state_does_not_rescan(
    tmp_path: Path, configured_logs: Callable[[], None]
) -> None:
    configured_logs()
    config_path = tmp_path / "config.yml"
    config_path.write_text(render_default_config("America/New_York"), encoding="utf-8")
    state = AutomationState(tmp_path / "runtime" / "automation.sqlite")
    state.record_run("jobs", datetime.now(UTC), "success", {})
    state.record_run("gmail", datetime.now(UTC), "success", {})
    calls: list[str] = []

    class OneLoopEvent(threading.Event):
        def wait(self, timeout: float | None = None) -> bool:
            self.set()
            return True

    for _ in range(2):
        service = AutomationService(
            workspace=tmp_path,
            config=load_config(config_path),
            state=state,
            job_runner=lambda: calls.append("jobs") or {},
            gmail_runner=lambda: calls.append("gmail") or {},
        )
        assert run_forever(service, OneLoopEvent()) == 0

    assert calls == []


def test_partial_job_coverage_is_visible_without_discarding_matches(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yml"
    config_path.write_text(render_default_config("America/New_York"), encoding="utf-8")
    state = AutomationState(tmp_path / "runtime" / "automation.sqlite")
    service = AutomationService(
        workspace=tmp_path,
        config=load_config(config_path),
        state=state,
        job_runner=lambda: {
            "refresh_status": "partial",
            "new_jobs": 1,
            "interesting_jobs": 0,
            "matches": [],
        },
    )

    assert service.run_task("jobs") is True
    history = state.last_run("jobs")
    assert history is not None
    assert history["status"] == "partial"
