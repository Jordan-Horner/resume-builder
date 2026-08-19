from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from resume_builder import evaluations
from resume_builder.synthesis import SynthesisPlan, SynthesisStory


def test_case_validation_does_not_require_or_open_resume(tmp_path: Path) -> None:
    case_dir = tmp_path / "evals" / "cases"
    case_dir.mkdir(parents=True)
    case = case_dir / "sealed.yaml"
    case.write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "id": "sealed",
                "lane": "Support",
                "resume": "resumes/baselines/support.md",
                "original_source_id": "SRC-0123456789ab",
                "original_sha256": "a" * 64,
                "snapshot_sha256": "b" * 64,
                "sealed": True,
                "required_role_ids": ["ROLE-001"],
                "material_fact_ids": ["FACT-001"],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    loaded = evaluations.load_case(case, tmp_path)

    assert loaded["sealed"] is True
    assert not loaded["resume_path"].exists()


def test_source_hash_is_checked_only_after_resume_exists(tmp_path: Path) -> None:
    case_dir = tmp_path / "evals" / "cases"
    case_dir.mkdir(parents=True)
    case = case_dir / "sealed.yaml"
    case.write_text(
        """version: 1
id: sealed
lane: Support
resume: resumes/baselines/support.md
original_source_id: SRC-0123456789ab
original_sha256: aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
snapshot_sha256: bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
sealed: true
required_role_ids: [ROLE-001]
material_fact_ids: [FACT-001]
""",
        encoding="utf-8",
    )
    vault = tmp_path / "vault"
    vault.mkdir()

    try:
        evaluations.grade_case(case, project_root=tmp_path, vault_root=vault)
    except ValueError as exc:
        assert "resume must exist before the original source is opened" in str(exc)
    else:
        raise AssertionError("missing resume should stop the holdout before source access")


def test_review_schema_requires_all_quality_dimensions(tmp_path: Path) -> None:
    review = tmp_path / "review.json"
    review.write_text(json.dumps({"dimensions": {}, "verdict": "on-par"}), encoding="utf-8")

    try:
        evaluations._review(review)
    except ValueError as exc:
        assert "dimensions must be" in str(exc)
    else:
        raise AssertionError("incomplete review should fail")


def test_compiled_selection_excludes_omitted_supporting_story(tmp_path: Path) -> None:
    plan = SynthesisPlan(
        source=tmp_path / "support.yaml",
        version=2,
        resume=tmp_path / "support.md",
        direction=tmp_path / "direction.md",
        target_argument="Show supported operational improvement.",
        summary_job="Lead with the measured improvement.",
        summary_fact_ids=("SUMMARY-001",),
        summary_body_fact_ids=(),
        progression=("ROLE-001",),
        stories=(
            SynthesisStory(
                story_id="core-story",
                section="experience",
                role_ids=("ROLE-001",),
                fact_ids=("FACT-CORE",),
                primary_job="show-outcome",
                priority=5,
                importance="core",
                rationale="Core proof.",
            ),
            SynthesisStory(
                story_id="supporting-story",
                section="experience",
                role_ids=("ROLE-001",),
                fact_ids=("FACT-OMITTED",),
                primary_job="add-context",
                priority=2,
                importance="supporting",
                rationale="Optional context.",
            ),
        ),
        exclusions=(),
        gaps=(),
    )
    payload: dict[str, Any] = {
        "summary_evidence": ["SUMMARY-001"],
        "experience": [{"evidence": ["ROLE-001"], "bullets": []}],
    }

    selected, roles = evaluations._compiled_selection(
        plan,
        payload,
        {"used_story_ids": ["core-story"], "omitted_story_ids": ["supporting-story"]},
    )

    assert selected == {"SUMMARY-001", "FACT-CORE"}
    assert "FACT-OMITTED" not in selected
    assert roles == {"ROLE-001"}


def test_compiled_selection_uses_actual_v4_evidence_not_the_available_pool(
    tmp_path: Path,
) -> None:
    plan = SynthesisPlan(
        source=tmp_path / "focused.yaml",
        version=4,
        resume=tmp_path / "focused.md",
        direction=tmp_path / "direction.md",
        target_argument="Show focused operational leadership.",
        summary_job="Lead with incident ownership.",
        summary_fact_ids=("SUMMARY-001",),
        summary_body_fact_ids=(),
        progression=("ROLE-001",),
        stories=(
            SynthesisStory(
                story_id="focused-story",
                section="experience",
                role_ids=("ROLE-001",),
                fact_ids=("FACT-CORE", "FACT-OPTIONAL"),
                primary_job="show-leadership",
                priority=5,
                importance="core",
                rationale="Lead with the supported claim.",
                claim_focus="Show operational leadership.",
                core_fact_ids=("FACT-CORE",),
            ),
        ),
        exclusions=(),
        gaps=(),
    )
    payload: dict[str, Any] = {
        "summary_evidence": ["SUMMARY-001"],
        "experience": [{"evidence": ["ROLE-001"], "bullets": []}],
    }

    selected, _ = evaluations._compiled_selection(
        plan,
        payload,
        {
            "used_story_ids": ["focused-story"],
            "selected_fact_ids": ["SUMMARY-001", "FACT-CORE"],
        },
    )

    assert selected == {"SUMMARY-001", "FACT-CORE"}
    assert "FACT-OPTIONAL" not in selected
