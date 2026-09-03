"""Tests for complete, non-hiding new-job semantic screening queues."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import resume_builder.job_screening_queue as queue_module
from resume_builder.agent_contracts import StructuredModelReply, StructuredModelRequest
from resume_builder.agent_openrouter import AgentProviderError
from resume_builder.job_screening import (
    Confidence,
    FitOutcome,
    SemanticScreen,
    build_screening_packet,
)
from resume_builder.job_screening_queue import build_screening_queue, load_notification_jobs


class QueueAdapter:
    def __init__(self, *, fail: bool = False) -> None:
        self.calls = 0
        self.fail = fail

    def run(self, request: object) -> object:
        raise AssertionError("free-form model path must not be used")

    def run_structured(self, request: StructuredModelRequest) -> StructuredModelReply:
        self.calls += 1
        if self.fail:
            raise AgentProviderError("fictional safe failure")
        return StructuredModelReply(
            output=SemanticScreen(
                fit=FitOutcome.STRONG_MATCH,
                confidence=Confidence.LOW,
                strengths=["The fictional evidence supports the central work."],
                gaps=[],
                unknowns=[],
                reasoning_summary="Relevant work is supported, but confidence remains limited.",
            ),
            model=request.model,
            requests=1,
            input_tokens=100,
            output_tokens=25,
            cost_usd="0.01",
        )


def _packet(job_id: str):
    description = (
        "We will not sponsor employment visas."
        if job_id == "blocked"
        else "Support production operations and incident response."
    )
    profile = {"supported_capabilities": ["production operations"]}
    if job_id == "blocked":
        profile["requires_sponsorship"] = True
    return build_screening_packet(
        {
            "id": job_id,
            "title": "Operations Engineer",
            "company": "Fictional Company",
            "location": "Remote",
            "work_modes": ["remote"],
            "description_text": description,
            "description_quality": "complete",
            "url": f"https://example.invalid/jobs/{job_id}",
        },
        {
            "accepted_work_modes": [],
            "accepted_location_terms": [],
            "include_unknown_locations": True,
            "screening_profile": profile,
        },
        {},
    )


def _input(path: Path, ids: list[str]) -> None:
    path.write_text(
        json.dumps(
            {
                "generated_at": "2026-09-03T12:00:00+00:00",
                "prescreen_version": 6,
                "jobs": [
                    {
                        "id": job_id,
                        "title": f"Role {job_id}",
                        "company": "Fictional Company",
                        "url": f"https://example.invalid/{job_id}",
                        "prescreen": {"review_eligible": True},
                    }
                    for job_id in ids
                ],
            }
        ),
        encoding="utf-8",
    )


def test_queue_keeps_every_job_and_bounds_provider_work(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "new.json"
    output = tmp_path / "screens.json"
    _input(source, ["recommended", "blocked", "waiting"])
    monkeypatch.setattr(
        queue_module, "get_job_screening_packet", lambda job_id, **_: _packet(job_id)
    )
    adapter = QueueAdapter()

    summary = build_screening_queue(
        adapter=adapter,
        model="fictional/model",
        cache_path=tmp_path / "cache.sqlite",
        input_path=source,
        output_path=output,
        max_provider_jobs=1,
        allow_provider=True,
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert [item["id"] for item in payload["jobs"]] == ["recommended", "blocked", "waiting"]
    assert all("description_text" not in item for item in payload["jobs"])
    assert set(payload["suggested_order"]) == {"recommended", "blocked", "waiting"}
    assert set(payload["shadow_personalized_order"]) == {
        "recommended",
        "blocked",
        "waiting",
    }
    assert payload["personalization_policy"]["changes_notifications"] is False
    assert payload["suggested_order"][0] == "recommended"
    assert summary.active == 3
    assert summary.completed == 2
    assert summary.provider_calls == 1
    assert summary.recommended == 1
    assert summary.needs_review == 1
    assert summary.additional == 1
    assert summary.input_tokens == 100
    assert summary.output_tokens == 25
    assert str(summary.cost_usd) == "0.01"
    assert adapter.calls == 1
    assert len(load_notification_jobs(output)) == 3


def test_queue_without_authorization_uses_no_provider_and_marks_all_unknowns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "new.json"
    output = tmp_path / "screens.json"
    _input(source, ["one", "two"])
    monkeypatch.setattr(
        queue_module, "get_job_screening_packet", lambda job_id, **_: _packet(job_id)
    )
    adapter = QueueAdapter()

    summary = build_screening_queue(
        adapter=adapter,
        model="fictional/model",
        cache_path=tmp_path / "cache.sqlite",
        input_path=source,
        output_path=output,
        allow_provider=False,
    )

    assert adapter.calls == 0
    assert summary.needs_review == 2
    assert all(
        item["screening"]["status"] == "unscreened"
        for item in json.loads(output.read_text(encoding="utf-8"))["jobs"]
    )


def test_legacy_review_flag_cannot_hide_a_job_without_a_disposition(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "new.json"
    output = tmp_path / "screens.json"
    _input(source, ["legacy-skip"])
    payload = json.loads(source.read_text(encoding="utf-8"))
    payload["prescreen_version"] = 5
    payload["jobs"][0]["prescreen"] = {
        "review_eligible": False,
        "category": "SKIP",
        "constraints": {"disposition": None},
    }
    source.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(
        queue_module, "get_job_screening_packet", lambda job_id, **_: _packet(job_id)
    )

    summary = build_screening_queue(
        adapter=QueueAdapter(),
        model="fictional/model",
        cache_path=tmp_path / "cache.sqlite",
        input_path=source,
        output_path=output,
        allow_provider=False,
    )

    assert summary.active == 1
    assert json.loads(output.read_text(encoding="utf-8"))["suggested_order"] == ["legacy-skip"]


def test_provider_failure_remains_visible_and_consumes_the_attempt_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "new.json"
    output = tmp_path / "screens.json"
    _input(source, ["fails", "waiting"])
    monkeypatch.setattr(
        queue_module, "get_job_screening_packet", lambda job_id, **_: _packet(job_id)
    )
    adapter = QueueAdapter(fail=True)

    summary = build_screening_queue(
        adapter=adapter,
        model="fictional/model",
        cache_path=tmp_path / "cache.sqlite",
        input_path=source,
        output_path=output,
        max_provider_jobs=1,
        allow_provider=True,
    )

    statuses = [
        item["screening"]["status"]
        for item in json.loads(output.read_text(encoding="utf-8"))["jobs"]
    ]
    assert statuses == ["failed", "unscreened"]
    assert summary.provider_calls == 1
    assert summary.failed == 1
    assert summary.needs_review == 2
    assert adapter.calls == 1
