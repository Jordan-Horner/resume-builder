from pathlib import Path
from types import SimpleNamespace

import pytest
from test_feedback_memory import project

from resume_builder import web_agent_resume as editing


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
