"""Tests for private application history and outcome reporting."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from job_puller.database import InventoryDatabase
from job_puller.models import JobObservation, ProviderResult
from resume_builder.applications import (
    RATE_SAMPLE_FLOOR,
    _write_or_preview,
    append_answer,
    append_event,
    applied_job_ids,
    build_record,
    find_answers,
    load_record,
    main,
    migrate_dispositions,
    outcome_report,
    validate_history,
)
from resume_builder.layout import VaultLayout


def arguments(**updates) -> argparse.Namespace:
    values = {
        "company": "Example",
        "role": "DevOps Engineer",
        "on": "2026-09-02",
        "job_id": "job-123",
        "url": "https://example.com/jobs/123",
        "role_family": "devops",
        "screen_category": "SCREEN NEXT",
        "match_classification": "directly-demonstrated",
        "target": None,
        "resume": None,
        "note": None,
    }
    values.update(updates)
    return argparse.Namespace(**values)


def write_application(root: Path, workspace: Path, **updates) -> dict:
    record = build_record(arguments(**updates), workspace)
    _write_or_preview(root, record, apply=True)
    return record


def test_record_preview_does_not_write(tmp_path: Path):
    root = tmp_path / "applications"
    record = build_record(arguments(), tmp_path)

    result = _write_or_preview(root, record, apply=False)

    assert result["applied"] is False
    assert not root.exists()


def test_record_apply_pins_workspace_artifacts(tmp_path: Path):
    target = tmp_path / "targets" / "example.md"
    resume = tmp_path / "exports" / "resume.pdf"
    target.parent.mkdir()
    resume.parent.mkdir()
    target.write_text("posting", encoding="utf-8")
    resume.write_bytes(b"resume")
    root = tmp_path / "applications"

    record = build_record(arguments(target=target, resume=resume), tmp_path)
    result = _write_or_preview(root, record, apply=True)
    stored = load_record(Path(result["path"]))

    assert stored["application"]["target"]["path"] == "targets/example.md"
    assert stored["application"]["resume"]["path"] == "exports/resume.pdf"
    assert len(stored["application"]["resume"]["sha256"]) == 64
    assert stored["events"][0]["status"] == "applied"


def test_record_captures_existing_prescreen_decision(tmp_path: Path):
    shortlist = tmp_path / "job-search" / "shortlist.json"
    shortlist.parent.mkdir()
    shortlist.write_text(
        json.dumps(
            {
                "prescreen_version": 5,
                "jobs": [
                    {
                        "id": "job-123",
                        "analysis_key": "screen-hash",
                        "prescreen": {"category": "SCREEN NEXT"},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    record = build_record(arguments(screen_category=None), tmp_path)

    assert record["application"]["screen_category"] == "SCREEN NEXT"
    assert record["application"]["screen_snapshot"]["analysis_key"] == "screen-hash"
    assert len(record["application"]["screen_snapshot"]["sha256"]) == 64


def test_record_uses_newest_prescreen_snapshot(tmp_path: Path):
    job_search = tmp_path / "job-search"
    job_search.mkdir()
    (job_search / "new-jobs.json").write_text(
        json.dumps(
            {
                "generated_at": "2026-09-01T10:00:00+00:00",
                "prescreen_version": 5,
                "jobs": [
                    {
                        "id": "job-123",
                        "analysis_key": "old-hash",
                        "prescreen": {"category": "POSSIBLE FIT"},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (job_search / "shortlist.json").write_text(
        json.dumps(
            {
                "generated_at": "2026-09-02T10:00:00+00:00",
                "prescreen_version": 5,
                "jobs": [
                    {
                        "id": "job-123",
                        "analysis_key": "current-hash",
                        "prescreen": {"category": "SCREEN NEXT"},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    record = build_record(arguments(screen_category=None), tmp_path)

    assert record["application"]["screen_snapshot"]["path"] == "job-search/shortlist.json"
    assert record["application"]["screen_snapshot"]["analysis_key"] == "current-hash"


def test_artifacts_cannot_escape_private_workspace(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.md"
    outside.write_text("private", encoding="utf-8")

    with pytest.raises(ValueError, match="inside the private workspace"):
        build_record(arguments(target=outside), workspace)


def test_outcomes_are_append_only_and_idempotent(tmp_path: Path):
    root = tmp_path / "applications"
    record = write_application(root, tmp_path)
    application_id = record["application"]["id"]

    first = append_event(
        root,
        application_id,
        "rejected",
        "2026-09-05",
        stage="Resume review",
        feedback="We selected other candidates.",
        note=None,
        supersedes=None,
        apply=True,
    )
    second = append_event(
        root,
        application_id,
        "rejected",
        "2026-09-05",
        stage="Resume review",
        feedback="We selected other candidates.",
        note=None,
        supersedes=None,
        apply=True,
    )

    stored = load_record(root / f"{application_id}.json")
    assert first["event"]["id"] == second["event"]["id"]
    assert [event["status"] for event in stored["events"]] == ["applied", "rejected"]
    assert stored["events"][1]["feedback_verbatim"] == "We selected other candidates."


def test_automated_event_preserves_structured_provenance_without_message_content(tmp_path: Path):
    root = tmp_path / "applications"
    record = write_application(root, tmp_path)
    application_id = record["application"]["id"]

    result = append_event(
        root,
        application_id,
        "applied",
        "2026-09-02",
        stage=None,
        feedback=None,
        note=None,
        supersedes=None,
        apply=True,
        event_type="application_confirmed",
        occurred_at="2026-09-02T14:30:00+00:00",
        source_type="gmail-automation",
        source_reference="opaque-reference",
        confidence=0.97,
        classifier_version="rules-v1",
        automation_policy="confirmation-v1",
    )

    event = result["event"]
    assert event["event_type"] == "application_confirmed"
    assert event["occurred_at"] == "2026-09-02T14:30:00+00:00"
    assert event["source"] == {
        "type": "gmail-automation",
        "reference": "opaque-reference",
    }
    assert event["automation"]["confidence"] == 0.97


def test_outcome_correction_supersedes_an_earlier_event(tmp_path: Path):
    root = tmp_path / "applications"
    record = write_application(root, tmp_path)
    application_id = record["application"]["id"]
    wrong = append_event(
        root,
        application_id,
        "rejected",
        "2026-09-05",
        stage=None,
        feedback=None,
        note=None,
        supersedes=None,
        apply=True,
    )["event"]

    correction = append_event(
        root,
        application_id,
        "interview",
        "2026-09-05",
        stage="Recruiter screen",
        feedback=None,
        note="Corrected status",
        supersedes=wrong["id"],
        apply=True,
    )["event"]

    assert correction["supersedes"] == wrong["id"]
    assert len(load_record(root / f"{application_id}.json")["events"]) == 3
    report = outcome_report(root)
    assert report["interviews"] == 1


def test_backfilled_event_does_not_replace_later_current_outcome(tmp_path: Path):
    root = tmp_path / "applications"
    record = write_application(root, tmp_path)
    application_id = record["application"]["id"]
    append_event(
        root,
        application_id,
        "rejected",
        "2026-09-10",
        stage=None,
        feedback=None,
        note=None,
        supersedes=None,
        apply=True,
    )
    append_event(
        root,
        application_id,
        "interview",
        "2026-09-05",
        stage="Recruiter screen",
        feedback=None,
        note="Backfilled after the rejection was recorded.",
        supersedes=None,
        apply=True,
    )

    report = outcome_report(root)

    assert report["current_statuses"] == {"rejected": 1}
    assert report["pending"] == 0


def test_applied_job_ids_reads_history(tmp_path: Path):
    root = tmp_path / "applications"
    write_application(root, tmp_path, job_id="job-123")
    write_application(
        root,
        tmp_path,
        company="Another",
        role="Support Engineer",
        job_id="job-456",
    )

    assert applied_job_ids(root) == {"job-123", "job-456"}


def test_answers_preserve_evidence_and_are_retrievable(tmp_path: Path):
    root = tmp_path / "applications"
    record = write_application(root, tmp_path)
    application_id = record["application"]["id"]
    layout = VaultLayout.load(tmp_path / "vault", allow_missing=True)
    layout.initialize()
    for fact_id in ("EX-001", "EX-002"):
        (layout.facts / f"{fact_id}.md").write_text(
            f"---\nid: {fact_id}\nstatus: confirmed\ntitle: Example\n---\nSupported fact.\n",
            encoding="utf-8",
        )

    append_answer(
        root,
        application_id,
        "Briefly describe your experience working remotely.",
        "I work effectively in asynchronous teams.",
        state="submitted",
        evidence=["EX-002", "EX-001", "EX-001"],
        apply=True,
    )

    matches = find_answers(root, "remote asynchronous experience")
    assert len(matches) == 1
    assert matches[0]["company"] == "Example"
    assert matches[0]["evidence"] == ["EX-001", "EX-002"]


def test_answers_reject_unknown_evidence(tmp_path: Path):
    root = tmp_path / "applications"
    record = write_application(root, tmp_path)
    application_id = record["application"]["id"]
    VaultLayout.load(tmp_path / "vault", allow_missing=True).initialize()

    with pytest.raises(ValueError, match="unknown career facts"):
        append_answer(
            root,
            application_id,
            "Describe your API experience.",
            "I troubleshoot APIs.",
            state="draft",
            evidence=["UNKNOWN-001"],
            apply=False,
        )


def test_application_history_validation_checks_current_fact_status(tmp_path: Path):
    root = tmp_path / "applications"
    record = write_application(root, tmp_path)
    application_id = record["application"]["id"]
    layout = VaultLayout.load(tmp_path / "vault", allow_missing=True)
    layout.initialize()
    fact = layout.facts / "EX-001.md"
    fact.write_text(
        "---\nid: EX-001\nstatus: confirmed\ntitle: Example\n---\nSupported fact.\n",
        encoding="utf-8",
    )
    append_answer(
        root,
        application_id,
        "Describe your API experience.",
        "I troubleshoot APIs.",
        state="submitted",
        evidence=["EX-001"],
        apply=True,
    )
    assert validate_history(root)["valid"] is True

    fact.write_text(
        "---\nid: EX-001\nstatus: needs-review\ntitle: Example\n---\nSupported fact.\n",
        encoding="utf-8",
    )
    result = validate_history(root)
    assert result["valid"] is False
    assert result["errors"] == ["cited career fact now needs review: EX-001"]


def test_report_withholds_rates_below_sample_floor(tmp_path: Path):
    root = tmp_path / "applications"
    record = write_application(root, tmp_path)
    append_event(
        root,
        record["application"]["id"],
        "rejected",
        "2026-09-05",
        stage=None,
        feedback=None,
        note=None,
        supersedes=None,
        apply=True,
    )

    report = outcome_report(root)
    group = report["by_screen_category"][0]
    assert RATE_SAMPLE_FLOOR > group["concluded"]
    assert group["interview_rate"] is None
    assert group["offer_rate"] is None


def test_report_emits_rates_at_sample_floor(tmp_path: Path):
    root = tmp_path / "applications"
    for index in range(RATE_SAMPLE_FLOOR):
        record = write_application(
            root,
            tmp_path,
            company=f"Example {index}",
            job_id=f"job-{index}",
        )
        application_id = record["application"]["id"]
        if index < 2:
            append_event(
                root,
                application_id,
                "interview",
                "2026-09-03",
                stage="Recruiter screen",
                feedback=None,
                note=None,
                supersedes=None,
                apply=True,
            )
        append_event(
            root,
            application_id,
            "rejected",
            "2026-09-05",
            stage=None,
            feedback=None,
            note=None,
            supersedes=None,
            apply=True,
        )

    group = outcome_report(root)["by_screen_category"][0]
    assert group["interview_rate"] == 0.2
    assert group["offer_rate"] == 0.0


def test_pending_interviews_do_not_inflate_concluded_rate(tmp_path: Path):
    root = tmp_path / "applications"
    for index in range(RATE_SAMPLE_FLOOR):
        record = write_application(
            root,
            tmp_path,
            company=f"Concluded {index}",
            job_id=f"concluded-{index}",
        )
        append_event(
            root,
            record["application"]["id"],
            "rejected",
            "2026-09-05",
            stage=None,
            feedback=None,
            note=None,
            supersedes=None,
            apply=True,
        )
    pending = write_application(
        root,
        tmp_path,
        company="Pending",
        job_id="pending-interview",
    )
    append_event(
        root,
        pending["application"]["id"],
        "interview",
        "2026-09-05",
        stage="Technical screen",
        feedback=None,
        note=None,
        supersedes=None,
        apply=True,
    )

    group = outcome_report(root)["by_screen_category"][0]
    assert group["interviews"] == 1
    assert group["interview_rate"] == 0.0


def test_cli_requires_apply_before_writing(tmp_path: Path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".resume-builder.json").write_text("{}\n", encoding="utf-8")
    root = tmp_path / "applications"

    status = main(
        [
            "record",
            "--company",
            "Example",
            "--role",
            "Support Engineer",
            "--job-id",
            "job-1",
        ]
    )

    output = json.loads(capsys.readouterr().out)
    assert status == 0
    assert output["applied"] is False
    assert not root.exists()


def test_cli_refuses_application_storage_outside_private_workspace(
    tmp_path: Path, capsys, monkeypatch
):
    monkeypatch.chdir(tmp_path)

    status = main(["list"])

    captured = capsys.readouterr()
    assert status == 2
    assert "active private workspace" in captured.err


def test_legacy_disposition_migration_requires_real_application_dates(tmp_path: Path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    config = config_dir / "search.yml"
    config.write_text(
        "schema_version: 1\ndatabase_path: data/inventory.db\n"
        "search:\n  families: [{name: support, titles: [support engineer]}]\n",
        encoding="utf-8",
    )
    database = InventoryDatabase(tmp_path / "data" / "inventory.db")
    database.migrate()
    item = JobObservation(
        provider="greenhouse",
        provider_job_id="legacy-1",
        title="Support Engineer",
        company="Example",
        source_url="https://example.com/jobs/legacy-1",
        description_text="Technical support role. " * 20,
    )
    now = datetime.now(UTC)
    database.record_result(
        ProviderResult(
            source_key="greenhouse:example",
            provider="greenhouse",
            observations=[item],
            started_at=now,
            completed_at=now,
            success=True,
            authoritative_complete=True,
        )
    )
    job_id = next(iter(database.job_ids()))
    preferences = tmp_path / "preferences.yml"
    preferences.write_text(
        f"schema_version: 1\njob_dispositions:\n  {job_id}: applied\n",
        encoding="utf-8",
    )
    root = tmp_path / "applications"

    unresolved = migrate_dispositions(root, preferences, config, {}, apply=True)
    assert unresolved["applied"] is False
    assert unresolved["missing_application_dates"] == [job_id]
    assert not root.exists()

    migrated = migrate_dispositions(
        root,
        preferences,
        config,
        {job_id: "2026-08-15"},
        apply=True,
    )

    assert migrated["applied"] is True
    assert applied_job_ids(root) == {job_id}
