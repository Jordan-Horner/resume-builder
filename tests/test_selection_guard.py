from __future__ import annotations

import json
from pathlib import Path

import pytest

from resume_builder import selection_guard


def selection() -> dict[str, object]:
    return {
        "version": 1,
        "direction": "directions/defense.md",
        "target": None,
        "target_mode": "direct",
        "progression_role_ids": ["ROLE-001", "ROLE-002"],
        "stories": [
            {
                "id": "courtroom-win",
                "section": "experience",
                "role_ids": ["ROLE-001"],
                "importance": "core",
                "required": True,
                "used_fact_ids": ["FACT-001", "FACT-002"],
            },
            {
                "id": "investigation",
                "section": "experience",
                "role_ids": ["ROLE-002"],
                "importance": "supporting",
                "required": False,
                "used_fact_ids": ["FACT-003"],
            },
        ],
        "summary_fact_ids": ["FACT-001"],
        "role_arcs": [
            {
                "role_ids": ["ROLE-001"],
                "required_dimensions": ["courtroom-outcome"],
                "required_story_ids": ["courtroom-win"],
            },
            {
                "role_ids": ["ROLE-002"],
                "required_dimensions": ["investigation"],
                "required_story_ids": [],
            },
        ],
    }


def test_structural_losses_require_approval_but_wording_is_not_scored() -> None:
    previous = selection()
    assert (
        selection_guard.compare_selections(previous, dict(previous))["requires_approval"] is False
    )

    current = json.loads(json.dumps(previous))
    current["progression_role_ids"].remove("ROLE-002")
    current["stories"] = [current["stories"][0]]
    current["stories"][0]["used_fact_ids"] = ["FACT-001"]
    current["stories"][0]["importance"] = "supporting"
    current["stories"][0]["required"] = False
    current["summary_fact_ids"] = []
    current["role_arcs"] = []

    delta = selection_guard.compare_selections(previous, current)
    assert delta["requires_approval"] is True
    assert delta["blocking"]["removed_role_ids"] == ["ROLE-002"]
    assert delta["blocking"]["removed_story_ids"] == ["investigation"]
    assert delta["blocking"]["evidence_losses"] == [
        {"id": "courtroom-win", "removed_fact_ids": ["FACT-002"]}
    ]
    assert delta["blocking"]["demoted_stories"][0]["id"] == "courtroom-win"
    assert delta["blocking"]["removed_summary_fact_ids"] == ["FACT-001"]


def test_removing_role_anchor_assignment_requires_approval() -> None:
    previous = selection()
    previous["role_arcs"][0]["role_anchor_story_ids"] = ["courtroom-win"]
    current = json.loads(json.dumps(previous))
    current["role_arcs"][0]["role_anchor_story_ids"] = []

    delta = selection_guard.compare_selections(previous, current)

    assert delta["requires_approval"] is True
    assert delta["blocking"]["removed_role_anchor_story_ids"] == [
        {"role_ids": ["ROLE-001"], "story_ids": ["courtroom-win"]}
    ]


def test_removing_role_selling_assignment_requires_approval() -> None:
    previous = selection()
    previous["role_arcs"][0]["role_selling_story_ids"] = ["courtroom-win"]
    current = json.loads(json.dumps(previous))
    current["role_arcs"][0]["role_selling_story_ids"] = []

    delta = selection_guard.compare_selections(previous, current)

    assert delta["requires_approval"] is True
    assert delta["blocking"]["removed_role_selling_story_ids"] == [
        {"role_ids": ["ROLE-001"], "story_ids": ["courtroom-win"]}
    ]


def test_strategy_change_is_grouped_and_exact_approval_unblocks_it(tmp_path: Path) -> None:
    resume = tmp_path / "resumes" / "baselines" / "defense.md"
    resume.parent.mkdir(parents=True)
    resume.write_text("resume", encoding="utf-8")
    review = tmp_path / "build" / "reviews" / "defense.json"
    review.parent.mkdir(parents=True)
    review.write_text("{}", encoding="utf-8")
    previous = selection()
    selection_guard.write_selection_seal(tmp_path, resume, previous, review)

    current = json.loads(json.dumps(previous))
    current["progression_role_ids"].remove("ROLE-002")
    current["stories"] = [current["stories"][0]]
    current["role_arcs"] = [current["role_arcs"][0]]
    with pytest.raises(ValueError, match="strategy approval required"):
        selection_guard.guard_selection(tmp_path, resume, current)

    proposal = tmp_path / "build" / "revisions" / "defense.strategy.json"
    captured = json.loads(proposal.read_text(encoding="utf-8"))
    assert captured["blocking_changes"]["removed_role_ids"] == ["ROLE-002"]
    assert captured["blocking_changes"]["removed_story_ids"] == ["investigation"]

    approved = selection_guard.approve_proposal(
        Path("build/revisions/defense.strategy.json"),
        tmp_path,
        "The narrower target no longer needs the investigation role.",
    )
    assert approved["status"] == "approved"
    guarded = selection_guard.guard_selection(tmp_path, resume, current)
    assert guarded["status"] == "strategy-change-approved"

    current["summary_fact_ids"] = []
    with pytest.raises(ValueError, match="strategy approval required"):
        selection_guard.guard_selection(tmp_path, resume, current)


def test_automatic_repair_is_bounded_per_block_and_review_anchor(tmp_path: Path) -> None:
    resume = tmp_path / "resumes" / "baselines" / "defense.md"
    resume.parent.mkdir(parents=True)
    resume.write_text("resume", encoding="utf-8")
    digest = selection_guard.selection_digest(selection())

    selection_guard.record_repair_attempts(tmp_path, resume, digest, ["summary"])
    with pytest.raises(ValueError, match="already attempted"):
        selection_guard.record_repair_attempts(tmp_path, resume, digest, ["summary"])
    selection_guard.record_repair_attempts(tmp_path, resume, digest, ["experience[0].bullets[0]"])

    review = tmp_path / "build" / "reviews" / "defense.json"
    review.parent.mkdir(parents=True)
    review.write_text("new approved review", encoding="utf-8")
    selection_guard.write_selection_seal(tmp_path, resume, selection(), review)
    selection_guard.record_repair_attempts(tmp_path, resume, digest, ["summary"])
