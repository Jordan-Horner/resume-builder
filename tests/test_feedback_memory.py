from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from resume_builder import feedback_memory


def _fact(path: Path, fact_id: str, fact_type: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"""---
schema_version: 2
id: {fact_id}
title: Evidence
type: {fact_type}
status: confirmed
category: profile
sources:
  - SRC-0123456789ab
themes:
  - evidence
---

# Evidence

Supported evidence.
""",
        encoding="utf-8",
    )


def project(tmp_path: Path) -> tuple[Path, Path, Path]:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "vault.json").write_text(
        json.dumps(
            {
                "schema_version": 2,
                "facts_path": "facts",
                "employment_path": "employment",
                "sources_manifest": "sources/manifest.json",
            }
        ),
        encoding="utf-8",
    )
    _fact(vault / "facts" / "ROLE-001.md", "ROLE-001", "role")
    _fact(vault / "facts" / "FACT-001.md", "FACT-001", "accomplishment")
    direction = tmp_path / "directions" / "support.md"
    direction.parent.mkdir()
    direction.write_text("# Direction\n", encoding="utf-8")
    resume = tmp_path / "resumes" / "baselines" / "support.md"
    resume.parent.mkdir(parents=True)
    resume.write_text(
        """---
version: 1
candidate:
  name: Candidate
  headline: Support Engineer
  evidence: [FACT-001]
---
# Professional Summary

Support engineer who resolves customer issues.
<!-- evidence: FACT-001 -->

# Work Experience

## Example | Support Engineer | 2022 - Present <!-- evidence: ROLE-001 -->

- Traced customer-impacting defects across service boundaries. <!-- story: investigation -->
  <!-- evidence: FACT-001 -->
""",
        encoding="utf-8",
    )
    plan = tmp_path / "resumes" / "plans" / "support.yaml"
    plan.parent.mkdir()
    plan.write_text(
        """version: 1
resume: resumes/baselines/support.md
direction: directions/support.md
target_argument: Demonstrate support investigation.
progression: [ROLE-001]
stories:
  - id: investigation
    section: experience
    role_ids: [ROLE-001]
    fact_ids: [FACT-001]
    primary_job: technical-depth
    priority: 5
    rationale: Show cross-service investigation.
exclusions: []
gaps: []
""",
        encoding="utf-8",
    )
    return vault, resume, plan


def feedback_plan(
    tmp_path: Path,
    resume: Path,
    *,
    instruction: str,
    block_text: str = "Traced customer-impacting defects across service boundaries.",
    promotion: str = "durable",
) -> Path:
    plan = tmp_path / "build" / "feedback-plan.json"
    plan.parent.mkdir(parents=True, exist_ok=True)
    plan.write_text(
        json.dumps(
            {
                "version": 1,
                "resume": resume.relative_to(tmp_path).as_posix(),
                "block": {
                    "id": "experience[0].bullets[0]",
                    "sha256": hashlib.sha256(block_text.encode()).hexdigest(),
                },
                "feedback": {
                    "subject_key": "investigated-event-terminology",
                    "kind": "terminology",
                    "strength": "hard",
                    "promotion": promotion,
                    "scope": {
                        "level": "facts",
                        "fact_ids": ["FACT-001"],
                        "resume": None,
                        "story_id": None,
                        "direction": None,
                        "section": "experience",
                    },
                    "summary": "Defects overstates what was established.",
                    "instruction": instruction,
                    "must_preserve": ["Cross-service customer investigation"],
                    "must_avoid": ["Do not imply a confirmed software defect"],
                    "preferred_examples": ["customer issues"],
                    "supersedes": [],
                },
            }
        ),
        encoding="utf-8",
    )
    return plan


def accept_for_unit_test(
    tmp_path: Path,
    session_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, object]:
    """Exercise promotion while the preview gate is covered by integration tests."""
    monkeypatch.setattr(
        feedback_memory,
        "_acceptance_result",
        lambda *_args: {
            "resume_sha256": "0" * 64,
            "build_manifest": "build/example.manifest.json",
            "build_sha256": "1" * 64,
            "review_record": "build/reviews/example.json",
            "review_sha256": "2" * 64,
            "preview_manifest": "build/example.preview.json",
            "preview_sha256": "3" * 64,
            "output": "build/example.html",
            "output_sha256": "4" * 64,
            "effective_digest": "5" * 64,
        },
    )
    return feedback_memory.accept_feedback(
        tmp_path,
        session_id=session_id,
        preview=Path("build/example.preview.json"),
    )


def test_missing_feedback_directories_are_a_valid_empty_install(tmp_path: Path) -> None:
    assert feedback_memory.validate_feedback_memory(tmp_path) == {
        "valid": True,
        "sessions": 0,
        "open_sessions": 0,
        "rules": 0,
        "active_rules": 0,
        "errors": [],
    }


def test_latest_session_revision_is_the_only_revision_promoted_and_resolved(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault, resume, synthesis_plan = project(tmp_path)
    plan_path = feedback_plan(
        tmp_path,
        resume,
        instruction="Describe the events as failures, not confirmed defects.",
    )
    first = feedback_memory.record_feedback(plan_path, tmp_path)
    assert first["current_revision"] == 1

    feedback_plan(
        tmp_path,
        resume,
        instruction="Describe the events as customer issues, not confirmed defects.",
    )
    second = feedback_memory.record_feedback(plan_path, tmp_path)
    assert second["session_id"] == first["session_id"]
    assert second["current_revision"] == 2

    accepted = accept_for_unit_test(tmp_path, str(second["session_id"]), monkeypatch)
    assert accepted["accepted"][0]["revision"] == 1
    rule_path = tmp_path / "editorial" / "rules" / f"{second['rule_id']}.json"
    rule = json.loads(rule_path.read_text(encoding="utf-8"))
    assert len(rule["revisions"]) == 1
    assert rule["revisions"][0]["source_session_revision"] == 2
    assert rule["revisions"][0]["instruction"] == (
        "Describe the events as customer issues, not confirmed defects."
    )

    resolved = feedback_memory.resolve_feedback(synthesis_plan, tmp_path, vault)
    assert resolved["count"] == 1
    assert resolved["rules"][0]["revision"] == 1
    assert resolved["rules"][0]["instruction"] == rule["revisions"][0]["instruction"]
    assert feedback_memory.validate_feedback_memory(tmp_path)["active_rules"] == 1


def test_new_feedback_after_acceptance_creates_a_new_accepted_rule_revision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, resume, _ = project(tmp_path)
    plan_path = feedback_plan(tmp_path, resume, instruction="Say customer failures.")
    recorded = feedback_memory.record_feedback(plan_path, tmp_path)
    accept_for_unit_test(tmp_path, str(recorded["session_id"]), monkeypatch)

    feedback_plan(tmp_path, resume, instruction="Say customer issues.")
    revised = feedback_memory.record_feedback(plan_path, tmp_path)
    accept_for_unit_test(tmp_path, str(revised["session_id"]), monkeypatch)

    rule_path = tmp_path / "editorial" / "rules" / f"{revised['rule_id']}.json"
    rule = json.loads(rule_path.read_text(encoding="utf-8"))
    assert rule["current_revision"] == 2
    assert [item["instruction"] for item in rule["revisions"]] == [
        "Say customer failures.",
        "Say customer issues.",
    ]


def test_open_feedback_is_visible_during_revision_but_not_future_memory(
    tmp_path: Path,
) -> None:
    vault, resume, synthesis_plan = project(tmp_path)
    plan_path = feedback_plan(tmp_path, resume, instruction="Keep this wording local.")
    feedback_memory.record_feedback(plan_path, tmp_path)

    assert feedback_memory.resolve_feedback(synthesis_plan, tmp_path, vault)["count"] == 0
    current = feedback_memory.resolve_feedback(
        synthesis_plan,
        tmp_path,
        vault,
        include_open=True,
    )
    assert current["count"] == 1
    assert current["rules"][0]["source"] == "open-session"


def test_explicit_session_revision_can_correct_the_feedback_classification(
    tmp_path: Path,
) -> None:
    _, resume, _ = project(tmp_path)
    plan_path = feedback_plan(tmp_path, resume, instruction="Avoid confirmed-defect wording.")
    first = feedback_memory.record_feedback(plan_path, tmp_path)
    data = json.loads(plan_path.read_text(encoding="utf-8"))
    data["feedback"]["kind"] = "authority"
    data["feedback"]["instruction"] = "Do not claim authority to confirm a software defect."
    plan_path.write_text(json.dumps(data), encoding="utf-8")

    revised = feedback_memory.record_feedback(
        plan_path,
        tmp_path,
        session_id=str(first["session_id"]),
    )

    assert revised["session_id"] == first["session_id"]
    assert revised["rule_id"] != first["rule_id"]
    assert revised["current_revision"] == 2
    session = json.loads((tmp_path / str(revised["session"])).read_text(encoding="utf-8"))
    assert session["identity"]["kind"] == "authority"
    assert session["revisions"][-1]["instruction"] == (
        "Do not claim authority to confirm a software defect."
    )


def test_acceptance_requires_the_reviewed_preview(tmp_path: Path) -> None:
    _, resume, _ = project(tmp_path)
    plan_path = feedback_plan(tmp_path, resume, instruction="Say customer issues.")
    recorded = feedback_memory.record_feedback(plan_path, tmp_path)

    with pytest.raises(ValueError, match="requires --preview"):
        feedback_memory.accept_feedback(tmp_path, session_id=str(recorded["session_id"]))


def test_feedback_rejects_stale_block_hash_and_unrelated_fact_scope(tmp_path: Path) -> None:
    _, resume, _ = project(tmp_path)
    plan_path = feedback_plan(
        tmp_path,
        resume,
        instruction="Use customer issues.",
        block_text="An earlier version of this sentence.",
    )
    with pytest.raises(ValueError, match="block hash"):
        feedback_memory.record_feedback(plan_path, tmp_path)

    data = json.loads(plan_path.read_text(encoding="utf-8"))
    data["block"]["sha256"] = hashlib.sha256(
        b"Traced customer-impacting defects across service boundaries."
    ).hexdigest()
    data["feedback"]["scope"]["fact_ids"] = ["OTHER-001"]
    plan_path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="facts used by the selected block"):
        feedback_memory.record_feedback(plan_path, tmp_path)


def test_non_durable_feedback_closes_without_creating_a_rule(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, resume, _ = project(tmp_path)
    plan_path = feedback_plan(
        tmp_path,
        resume,
        instruction="Shorten this one sentence.",
        promotion="none",
    )
    recorded = feedback_memory.record_feedback(plan_path, tmp_path)
    accepted = accept_for_unit_test(tmp_path, str(recorded["session_id"]), monkeypatch)
    assert accepted["accepted"][0]["route"] == "closed"
    assert not (tmp_path / "editorial" / "rules").exists()
