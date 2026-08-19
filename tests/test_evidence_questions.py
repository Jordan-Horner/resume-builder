from __future__ import annotations

import json
from pathlib import Path

import pytest

from resume_builder import evidence_questions, review_records


def _project(tmp_path: Path) -> tuple[Path, Path]:
    resume = tmp_path / "resumes" / "baselines" / "incident-management.md"
    resume.parent.mkdir(parents=True)
    resume.write_text("# Draft\n", encoding="utf-8")
    (tmp_path / "build" / "reviews").mkdir(parents=True)
    return tmp_path, resume


def _question_plan(tmp_path: Path, *, count: int = 1) -> Path:
    questions = [
        {
            "gap_key": f"incident-response.scale-{index + 1}",
            "gap": "scale",
            "subject": "Incident response leadership",
            "priority": index + 1,
            "question": f"How many teams did you coordinate in incident example {index + 1}?",
            "expected_value": "Clarifies the scale of a target-critical leadership story.",
            "evidence_searched": {
                "canonical_facts": True,
                "registered_sources": True,
                "notes": "No team count appears in the facts or registered snapshots.",
            },
        }
        for index in range(count)
    ]
    path = tmp_path / "build" / "reviews" / "incident-management.questions.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "resume": "resumes/baselines/incident-management.md",
                "questions": questions,
            }
        ),
        encoding="utf-8",
    )
    return path


def test_question_plan_records_stable_gaps_and_skips_rephrasing(tmp_path: Path) -> None:
    root, _ = _project(tmp_path)
    plan = _question_plan(tmp_path)

    preview = evidence_questions.question_plan(plan, root)
    assert len(preview["askable"]) == 1
    assert not (root / "editorial" / "evidence-questions.json").exists()

    applied = evidence_questions.question_plan(plan, root, apply=True)
    assert len(applied["askable"]) == 1
    repeated = evidence_questions.question_plan(plan, root)
    assert repeated["askable"] == []
    assert repeated["already_recorded"][0]["status"] == "asked"


def test_question_plan_caps_rounds_and_rejects_generic_or_unsearched_gaps(
    tmp_path: Path,
) -> None:
    root, _ = _project(tmp_path)
    with pytest.raises(ValueError, match="no more than five"):
        evidence_questions.question_plan(_question_plan(tmp_path, count=6), root)

    plan = _question_plan(tmp_path)
    payload = json.loads(plan.read_text(encoding="utf-8"))
    payload["questions"][0]["question"] = "Tell me more about your experience?"
    plan.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="too generic"):
        evidence_questions.question_plan(plan, root)

    payload["questions"][0]["question"] = "How many teams did you coordinate?"
    payload["questions"][0]["evidence_searched"]["registered_sources"] = False
    plan.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="facts and registered sources"):
        evidence_questions.question_plan(plan, root)


def test_unknown_resolution_is_final_and_stores_no_answer(tmp_path: Path) -> None:
    root, resume = _project(tmp_path)
    evidence_questions.question_plan(_question_plan(tmp_path), root, apply=True)

    result = evidence_questions.resolve_question(
        root,
        resume=resume,
        gap_key="incident-response.scale-1",
        status="unknown",
    )
    assert result["status"] == "unknown"
    history = json.loads(
        (root / "editorial" / "evidence-questions.json").read_text(encoding="utf-8")
    )
    assert history["entries"][0]["status"] == "unknown"
    assert "answer" not in history["entries"][0]
    with pytest.raises(ValueError, match="already resolved"):
        evidence_questions.resolve_question(
            root,
            resume=resume,
            gap_key="incident-response.scale-1",
            status="declined",
        )


def test_answered_resolution_requires_registered_career_note_source(tmp_path: Path) -> None:
    root, resume = _project(tmp_path)
    evidence_questions.question_plan(_question_plan(tmp_path), root, apply=True)
    with pytest.raises(ValueError, match="not registered"):
        evidence_questions.resolve_question(
            root,
            resume=resume,
            gap_key="incident-response.scale-1",
            status="answered",
            source_id="SRC-0123456789ab",
        )

    manifest = root / "vault" / "sources" / "manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        json.dumps({"version": 1, "sources": [{"id": "SRC-0123456789ab"}]}),
        encoding="utf-8",
    )
    fact = root / "vault" / "facts" / "accomplishment" / "EX-001.md"
    fact.parent.mkdir(parents=True)
    fact.write_text(
        """---
schema_version: 2
id: EX-001
sources:
  - SRC-0123456789ab
---

# Captured answer
""",
        encoding="utf-8",
    )
    result = evidence_questions.resolve_question(
        root,
        resume=resume,
        gap_key="incident-response.scale-1",
        status="answered",
        source_id="SRC-0123456789ab",
    )
    assert result["source_id"] == "SRC-0123456789ab"


def test_review_question_plan_cli_supports_preview_and_apply(tmp_path: Path, run_main) -> None:
    root, _ = _project(tmp_path)
    plan = _question_plan(tmp_path)

    assert run_main(review_records.main, "question-plan", plan, "--project-root", root) == 0
    assert (
        run_main(
            review_records.main,
            "question-plan",
            plan,
            "--project-root",
            root,
            "--apply",
        )
        == 0
    )
