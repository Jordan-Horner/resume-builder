import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_feedback_memory import project

from resume_builder.agent_contracts import ModelProviderTimeoutError
from resume_builder.portal import resume_editing as editing


def proposal(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    _, resume, _ = project(tmp_path)
    source = resume.read_text()
    return resume, {
        "resume_id": "resumes/baselines/support.md",
        "revision": editing.digest(source),
        "block_id": "summary",
        "before": "Support engineer who resolves customer issues.",
        "after": "Support engineer focused on resolving customer issues.",
        "instruction": "Use the selected summary wording.",
    }


def test_replacements_preserve_other_blocks_and_evidence(tmp_path: Path) -> None:
    resume, change = proposal(tmp_path)
    before = resume.read_text()
    after, original = editing.replacement_source(before, "summary", change["after"])
    assert original == change["before"]
    assert after == before.replace(original, change["after"])
    with pytest.raises(ValueError):
        editing.replacement_source(before, "summary", "# Changed\nNew section")


def test_stale_or_tailored_changes_never_reach_model(tmp_path: Path) -> None:
    resume, change = proposal(tmp_path)
    resume.write_text(resume.read_text() + "\n")
    with pytest.raises(ValueError, match="changed"):
        editing.apply_wording(tmp_path, change, SimpleNamespace(), "model", "fixture")
    with pytest.raises(ValueError):
        editing.resume_path(tmp_path, "resumes/tailored/example.md")
    with pytest.raises(ValueError):
        editing.resume_path(tmp_path, "../outside.md")


def test_factual_changes_are_rejected_before_writing(tmp_path: Path) -> None:
    resume, change = proposal(tmp_path)
    before = resume.read_bytes()
    adapter = SimpleNamespace(
        run_structured=lambda request: SimpleNamespace(
            output=editing.WordingCheck(wording_only=False, reason="Changed authorship")
        )
    )
    with pytest.raises(ValueError, match="factual claim"):
        editing.apply_wording(tmp_path, change, adapter, "model", "fixture")
    assert resume.read_bytes() == before
    assert not (tmp_path / "build/feedback").exists()


def test_factual_check_timeout_is_retryable_and_does_not_write_resume(tmp_path: Path) -> None:
    resume, change = proposal(tmp_path)
    before = resume.read_bytes()

    def timeout(request: object) -> None:
        raise ModelProviderTimeoutError("deadline")

    adapter = SimpleNamespace(run_structured=timeout)

    with pytest.raises(ValueError, match=r"timed out.*unchanged.*retry"):
        editing.apply_wording(tmp_path, change, adapter, "fast-model", "fixture-timeout")

    assert resume.read_bytes() == before
    telemetry = list((tmp_path / "build/performance/resume-edits").glob("*.json"))
    record = json.loads(telemetry[0].read_text())
    assert record["outcome"] == "equivalence-timeout"
    assert record["error_class"] == "ModelProviderTimeoutError"


def test_edit_records_feedback_and_does_not_report_failed_review_as_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resume, change = proposal(tmp_path)
    adapter = SimpleNamespace(
        run_structured=lambda request: SimpleNamespace(
            output=editing.WordingCheck(wording_only=True, reason="Same claim")
        )
    )

    def fail(*args: object, **kwargs: object) -> None:
        raise ValueError("Review failed")

    monkeypatch.setattr(editing, "build_resume", fail)
    with pytest.raises(ValueError, match="wording was saved"):
        editing.apply_wording(tmp_path, change, adapter, "model", "fixture")
    assert change["after"] in resume.read_text()
    assert list((tmp_path / "build/feedback").glob("FB-*.json"))
    assert not (tmp_path / "exports").exists()


def test_success_uses_existing_review_and_preview_not_mint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resume, change = proposal(tmp_path)
    calls: list[str] = []
    adapter = SimpleNamespace(
        run_structured=lambda request: SimpleNamespace(
            output=editing.WordingCheck(wording_only=True, reason="Same claim")
        )
    )
    monkeypatch.setattr(editing, "build_resume", lambda *a, **kw: calls.append("compile"))
    monkeypatch.setattr(editing, "prepare_language_review", lambda *a, **kw: {"cached": True})
    monkeypatch.setattr(editing, "preview_resume", lambda *a, **kw: calls.append("preview") or {})
    result = editing.apply_wording(tmp_path, change, adapter, "model", "fixture")
    assert calls == ["compile", "preview"]
    assert "updated and reviewed" in result
    assert change["after"] in resume.read_text()


def test_success_routes_equivalence_to_fast_model_and_records_timings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _resume, change = proposal(tmp_path)
    requests: list[object] = []
    equivalence_adapter = SimpleNamespace(
        run_structured=lambda request: (
            requests.append(request)
            or SimpleNamespace(
                output=editing.WordingCheck(wording_only=True, reason="Same claim"), requests=1
            )
        )
    )
    language_adapter = SimpleNamespace()
    monkeypatch.setattr(editing, "build_resume", lambda *a, **kw: None)
    monkeypatch.setattr(
        editing,
        "prepare_language_review",
        lambda *a, **kw: {"cached": True, "pending_blocks": 0},
    )
    monkeypatch.setattr(editing, "preview_resume", lambda *a, **kw: {})

    editing.apply_wording(
        tmp_path,
        change,
        language_adapter,
        "writing-model",
        "fixture-routing",
        equivalence_adapter=equivalence_adapter,
        equivalence_model="fast-model",
    )

    assert len(requests) == 1
    request = requests[0]
    assert request.model == "fast-model"
    assert request.max_output_tokens == 128
    telemetry = list((tmp_path / "build/performance/resume-edits").glob("*.json"))
    assert len(telemetry) == 1
    record = json.loads(telemetry[0].read_text())
    assert record["outcome"] == "completed"
    assert record["models"] == {
        "equivalence": "fast-model",
        "language": "writing-model",
    }
    assert record["pending_language_blocks"] == 0
    assert record["provider_requests"]["equivalence"] == 1
    assert record["resume_id_sha256"] != change["resume_id"]
    assert record["total_ms"] >= 0


def test_changed_block_language_review_keeps_safe_output_budget(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _resume, change = proposal(tmp_path)
    equivalence_adapter = SimpleNamespace(
        run_structured=lambda request: SimpleNamespace(
            output=editing.WordingCheck(wording_only=True, reason="Same claim"), requests=1
        )
    )
    language_requests: list[object] = []
    language_adapter = SimpleNamespace(
        run_structured=lambda request: (
            language_requests.append(request)
            or SimpleNamespace(
                output=editing.LanguageDecisions(
                    status="approved",
                    blocks=[
                        editing.LanguageBlock(
                            id="summary",
                            sha256="fixture-hash",
                            decision="approved",
                            note="Clear and complete.",
                        )
                    ],
                ),
                requests=1,
            )
        )
    )
    review_dir = tmp_path / "build/reviews"
    review_dir.mkdir(parents=True)
    (review_dir / "cold.json").write_text(json.dumps({"blocks": [{"id": "summary"}]}))
    (review_dir / "decisions.json").write_text(json.dumps({"reviewer": {}, "language_review": {}}))
    monkeypatch.setattr(editing, "build_resume", lambda *a, **kw: None)
    monkeypatch.setattr(
        editing,
        "prepare_language_review",
        lambda *a, **kw: {
            "cached": False,
            "pending_blocks": 1,
            "review_inputs": {
                "cold_read": {"path": "build/reviews/cold.json"},
                "decisions": "build/reviews/decisions.json",
            },
        },
    )
    monkeypatch.setattr(editing, "finalize_language_review", lambda *a, **kw: {})
    monkeypatch.setattr(editing, "preview_resume", lambda *a, **kw: {})

    editing.apply_wording(
        tmp_path,
        change,
        language_adapter,
        "writing-model",
        "fixture-language-budget",
        equivalence_adapter=equivalence_adapter,
        equivalence_model="fast-model",
    )

    assert len(language_requests) == 1
    assert language_requests[0].model == "writing-model"
    assert language_requests[0].max_output_tokens is None
