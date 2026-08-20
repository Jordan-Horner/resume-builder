from __future__ import annotations

import json
from pathlib import Path

import pytest

from resume_builder import synthesis


def add_fact(path: Path, fact_id: str, fact_type: str, extra: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"""---
schema_version: 2
id: {fact_id}
title: "Evidence"
type: {fact_type}
status: confirmed
category: profile
sources:
  - SRC-0123456789ab
themes:
  - evidence
{extra}
---

# Evidence

Supported evidence.
""",
        encoding="utf-8",
    )


def project(tmp_path: Path) -> tuple[Path, Path]:
    vault = tmp_path / "vault"
    (vault / "vault.json").parent.mkdir(parents=True)
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
    add_fact(vault / "facts" / "profile" / "ROLE-001.md", "ROLE-001", "role")
    add_fact(
        vault / "facts" / "profile" / "FACT-001.md",
        "FACT-001",
        "accomplishment",
    )
    add_fact(
        vault / "facts" / "profile" / "FACT-002.md",
        "FACT-002",
        "accomplishment",
    )
    resume = tmp_path / "resumes" / "baselines" / "example.md"
    resume.parent.mkdir(parents=True)
    resume.write_text("# Placeholder\n", encoding="utf-8")
    direction = tmp_path / "directions" / "example.md"
    direction.parent.mkdir()
    direction.write_text("# Direction\n", encoding="utf-8")
    plan = tmp_path / "resumes" / "plans" / "example.yaml"
    plan.parent.mkdir()
    plan.write_text(
        """version: 1
resume: resumes/baselines/example.md
direction: directions/example.md
target_argument: Demonstrate supported operational improvement.
progression: [ROLE-001]
stories:
  - id: operational-improvement
    section: experience
    role_ids: [ROLE-001]
    fact_ids: [FACT-001]
    primary_job: outcome
    priority: 5
    rationale: Use the strongest supported outcome.
exclusions: []
gaps: []
""",
        encoding="utf-8",
    )
    return vault, plan


def upgrade_to_v2(path: Path) -> None:
    """Replace the fixture plan with one core and one supporting story."""
    path.write_text(
        """version: 2
resume: resumes/baselines/example.md
direction: directions/example.md
target_argument: Demonstrate supported operational improvement.
summary_job: Establish the operating pattern proved by the selected evidence.
summary_fact_ids: [FACT-001]
progression: [ROLE-001]
stories:
  - id: operational-improvement
    section: experience
    role_ids: [ROLE-001]
    fact_ids: [FACT-001]
    primary_job: outcome
    priority: 5
    importance: core
    rationale: Use the strongest supported outcome.
  - id: supporting-detail
    section: experience
    role_ids: [ROLE-001]
    fact_ids: [FACT-002]
    primary_job: technical-depth
    priority: 3
    importance: supporting
    rationale: Add depth only when it improves the information budget.
exclusions: []
gaps: []
""",
        encoding="utf-8",
    )


def upgrade_to_v3(path: Path) -> None:
    """Replace the fixture with a decision-complete version 3 plan."""
    direction = path.parents[2] / "directions" / "example.md"
    direction.write_text(
        """---
priority_concepts:
  - id: operational-improvement
---

# Direction
""",
        encoding="utf-8",
    )
    path.write_text(
        """version: 3
resume: resumes/baselines/example.md
direction: directions/example.md
target_argument: Demonstrate supported operational improvement.
target_mode: direct
summary_job: Establish the operating pattern proved by the selected evidence.
summary_fact_ids: [FACT-001]
concept_fit:
  - concept_id: operational-improvement
    status: demonstrated
    fact_ids: [FACT-001]
    rationale: The selected outcome directly demonstrates the direction concept.
reviewer_risks:
  - id: outcome-clarity
    concern: The improvement could read as a responsibility instead of an outcome.
    status: resolved
    fact_ids: [FACT-001]
    planning_action: Lead the role with the outcome story.
presentation:
  competencies: omit
  competencies_job: Omit labels because the summary and experience already establish fit.
  compressed_role_ids: []
progression: [ROLE-001]
stories:
  - id: operational-improvement
    section: experience
    role_ids: [ROLE-001]
    fact_ids: [FACT-001]
    primary_job: outcome
    priority: 5
    importance: core
    rationale: Use the strongest supported outcome.
  - id: supporting-detail
    section: experience
    role_ids: [ROLE-001]
    fact_ids: [FACT-002]
    primary_job: technical-depth
    priority: 3
    importance: supporting
    rationale: Add depth only when it improves the information budget.
exclusions: []
gaps: []
""",
        encoding="utf-8",
    )


def upgrade_to_v4(path: Path) -> None:
    """Replace the fixture with a focused-claim version 4 plan."""
    upgrade_to_v3(path)
    text = path.read_text(encoding="utf-8")
    text = text.replace("version: 3", "version: 4", 1)
    text = text.replace(
        """    fact_ids: [FACT-001]
    primary_job: outcome""",
        """    fact_ids: [FACT-001, FACT-002]
    core_fact_ids: [FACT-001]
    claim_focus: Show the supported operational improvement.
    primary_job: outcome""",
        1,
    )
    text = text.replace(
        """    fact_ids: [FACT-002]
    primary_job: technical-depth""",
        """    fact_ids: [FACT-002]
    core_fact_ids: [FACT-002]
    claim_focus: Add distinct technical depth when space permits.
    primary_job: technical-depth""",
        1,
    )
    path.write_text(text, encoding="utf-8")


def upgrade_to_v5(path: Path) -> None:
    """Replace the fixture with a role-arc version 5 plan."""
    upgrade_to_v4(path)
    text = path.read_text(encoding="utf-8")
    text = text.replace("version: 4", "version: 5", 1)
    text = text.replace(
        "progression: [ROLE-001]",
        """role_arcs:
  - role_ids: [ROLE-001]
    emphasis: lead
    arc_focus: Show an operating result followed by distinct technical depth.
    story_ids: [operational-improvement, supporting-detail]
    selection_rationale: Give the only role enough space to make both supported signals visible.
    omitted_signals: []
progression: [ROLE-001]""",
        1,
    )
    path.write_text(text, encoding="utf-8")


def upgrade_to_v6(path: Path) -> None:
    """Replace the fixture with structured claims and a resolved page budget."""
    upgrade_to_v5(path)
    direction = path.parents[2] / "directions" / "example.md"
    direction.write_text(
        """---
priority_concepts:
  - id: operational-improvement
defaults:
  max_pages: 2
  page_format: letter
  minimum_coverage: 75
---

# Direction
""",
        encoding="utf-8",
    )
    text = path.read_text(encoding="utf-8")
    text = text.replace("version: 5", "version: 6", 1)
    text = text.replace(
        "direction: directions/example.md",
        """direction: directions/example.md
page_budget:
  max_pages: 2
  source: direction-default""",
        1,
    )
    text = text.replace(
        """    story_ids: [operational-improvement, supporting-detail]
    selection_rationale:""",
        """    required_dimensions: [outcome]
    required_story_ids: [operational-improvement]
    optional_story_ids: [supporting-detail]
    selection_rationale:""",
        1,
    )
    text = text.replace(
        """    claim_focus: Show the supported operational improvement.
    primary_job: outcome""",
        """    claim_focus: Show the supported operational improvement.
    claim:
      subject: candidate
      action: improved
      object: operational-process
      scope: null
      outcome: null
      composition: single-fact
      relationship: FACT-001 alone supports the action and object.
      evidence:
        action: [FACT-001]
        object: [FACT-001]
        scope: []
        outcome: []
    primary_job: outcome""",
        1,
    )
    text = text.replace(
        """    claim_focus: Add distinct technical depth when space permits.
    primary_job: technical-depth""",
        """    claim_focus: Add distinct technical depth when space permits.
    claim:
      subject: candidate
      action: added
      object: technical-depth
      scope: null
      outcome: null
      composition: single-fact
      relationship: FACT-002 alone supports the action and object.
      evidence:
        action: [FACT-002]
        object: [FACT-002]
        scope: []
        outcome: []
    primary_job: technical-depth""",
        1,
    )
    path.write_text(text, encoding="utf-8")


def test_synthesis_plan_validates_and_audits_compiled_stories(tmp_path: Path) -> None:
    vault, path = project(tmp_path)
    plan = synthesis.load_synthesis_plan(path, tmp_path, vault)
    payload = {
        "experience": [
            {
                "evidence": ["ROLE-001"],
                "bullets": [
                    {
                        "text": "Improved operations.",
                        "evidence": ["FACT-001"],
                        "story": "operational-improvement",
                    }
                ],
            }
        ],
        "projects": [],
    }

    result = synthesis.audit_synthesis(payload, plan)

    assert result["valid"] is True
    assert result["stories"] == 1


def test_synthesis_audit_rejects_missing_or_misplaced_story(tmp_path: Path) -> None:
    vault, path = project(tmp_path)
    plan = synthesis.load_synthesis_plan(path, tmp_path, vault)
    payload = {
        "experience": [
            {
                "evidence": ["ROLE-001"],
                "bullets": [{"text": "Improved operations.", "evidence": ["FACT-001"]}],
            }
        ],
        "projects": [],
    }

    with pytest.raises(ValueError, match="requires a planned story ID"):
        synthesis.audit_synthesis(payload, plan)


def test_synthesis_plan_rejects_duplicate_jobs_for_one_role(tmp_path: Path) -> None:
    vault, path = project(tmp_path)
    text = path.read_text(encoding="utf-8")
    path.write_text(
        text.replace(
            "exclusions: []",
            """  - id: second-story
    section: experience
    role_ids: [ROLE-001]
    fact_ids: [FACT-001]
    primary_job: outcome
    priority: 4
    rationale: This duplicates the first bullet's job.
exclusions: []""",
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="duplicate primary job"):
        synthesis.load_synthesis_plan(path, tmp_path, vault)


def test_synthesis_plan_rejects_role_scoped_fact_under_another_role(tmp_path: Path) -> None:
    vault, path = project(tmp_path)
    fact_path = vault / "facts" / "profile" / "FACT-001.md"
    text = fact_path.read_text(encoding="utf-8")
    fact_path.write_text(
        text.replace(
            "category: profile",
            "category: employment\norganization: example\nscope: role\nrole_ids:\n  - ROLE-002",
        ),
        encoding="utf-8",
    )
    add_fact(vault / "facts" / "profile" / "ROLE-002.md", "ROLE-002", "role")

    with pytest.raises(ValueError, match="outside its roles"):
        synthesis.load_synthesis_plan(path, tmp_path, vault)


def test_v2_reports_omitted_supporting_story(tmp_path: Path) -> None:
    vault, path = project(tmp_path)
    upgrade_to_v2(path)
    plan = synthesis.load_synthesis_plan(path, tmp_path, vault)
    payload = {
        "summary_evidence": ["FACT-001"],
        "experience": [
            {
                "evidence": ["ROLE-001"],
                "bullets": [
                    {
                        "text": "Improved operations.",
                        "evidence": ["FACT-001"],
                        "story": "operational-improvement",
                    }
                ],
            }
        ],
        "projects": [],
    }

    result = synthesis.audit_synthesis(payload, plan)

    assert result["version"] == 2
    assert result["used_story_ids"] == ["operational-improvement"]
    assert result["omitted_story_ids"] == ["supporting-detail"]
    assert result["summary_fact_ids"] == ["FACT-001"]


def test_v2_still_requires_core_stories(tmp_path: Path) -> None:
    vault, path = project(tmp_path)
    upgrade_to_v2(path)
    plan = synthesis.load_synthesis_plan(path, tmp_path, vault)
    payload = {
        "summary_evidence": ["FACT-001"],
        "experience": [{"evidence": ["ROLE-001"], "bullets": []}],
        "projects": [],
    }

    with pytest.raises(ValueError, match="core synthesis stories absent"):
        synthesis.audit_synthesis(payload, plan)


def test_v2_requires_planned_summary_evidence(tmp_path: Path) -> None:
    vault, path = project(tmp_path)
    upgrade_to_v2(path)
    plan = synthesis.load_synthesis_plan(path, tmp_path, vault)
    payload = {
        "summary_evidence": [],
        "experience": [
            {
                "evidence": ["ROLE-001"],
                "bullets": [
                    {
                        "text": "Improved operations.",
                        "evidence": ["FACT-001"],
                        "story": "operational-improvement",
                    }
                ],
            }
        ],
        "projects": [],
    }

    with pytest.raises(ValueError, match="summary evidence disagrees"):
        synthesis.audit_synthesis(payload, plan)


def test_v2_rejects_unplanned_summary_evidence(tmp_path: Path) -> None:
    vault, path = project(tmp_path)
    upgrade_to_v2(path)
    plan = synthesis.load_synthesis_plan(path, tmp_path, vault)
    payload = {
        "summary_evidence": ["FACT-001", "FACT-002"],
        "experience": [
            {
                "evidence": ["ROLE-001"],
                "bullets": [
                    {
                        "text": "Improved operations.",
                        "evidence": ["FACT-001"],
                        "story": "operational-improvement",
                    }
                ],
            }
        ],
        "projects": [],
    }

    with pytest.raises(ValueError, match=r"unexpected=.*FACT-002"):
        synthesis.audit_synthesis(payload, plan)


def test_v2_requires_role_scoped_summary_evidence_later_in_resume(tmp_path: Path) -> None:
    vault, path = project(tmp_path)
    fact_path = vault / "facts" / "profile" / "FACT-002.md"
    fact_path.write_text(
        fact_path.read_text(encoding="utf-8").replace(
            "category: profile",
            "category: employment\nscope: role\nrole_ids:\n  - ROLE-001",
        ),
        encoding="utf-8",
    )
    upgrade_to_v2(path)
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "summary_fact_ids: [FACT-001]",
            "summary_fact_ids: [FACT-001, FACT-002]",
        ),
        encoding="utf-8",
    )
    plan = synthesis.load_synthesis_plan(path, tmp_path, vault)
    payload = {
        "summary_evidence": ["FACT-001", "FACT-002"],
        "experience": [
            {
                "evidence": ["ROLE-001"],
                "bullets": [
                    {
                        "text": "Improved operations.",
                        "evidence": ["FACT-001"],
                        "story": "operational-improvement",
                    }
                ],
            }
        ],
        "projects": [],
    }

    with pytest.raises(ValueError, match=r"role-scoped.*not demonstrated later.*FACT-002"):
        synthesis.audit_synthesis(payload, plan)


def test_v2_allows_organization_scoped_summary_evidence_without_role_guessing(
    tmp_path: Path,
) -> None:
    vault, path = project(tmp_path)
    fact_path = vault / "facts" / "profile" / "FACT-002.md"
    fact_path.write_text(
        fact_path.read_text(encoding="utf-8").replace(
            "category: profile", "category: employment\nscope: organization"
        ),
        encoding="utf-8",
    )
    upgrade_to_v2(path)
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "summary_fact_ids: [FACT-001]",
            "summary_fact_ids: [FACT-001, FACT-002]",
        ),
        encoding="utf-8",
    )
    plan = synthesis.load_synthesis_plan(path, tmp_path, vault)
    payload = {
        "summary_evidence": ["FACT-001", "FACT-002"],
        "experience": [
            {
                "evidence": ["ROLE-001"],
                "bullets": [
                    {
                        "text": "Improved operations.",
                        "evidence": ["FACT-001"],
                        "story": "operational-improvement",
                    }
                ],
            }
        ],
        "projects": [],
    }

    result = synthesis.audit_synthesis(payload, plan)

    assert result["valid"] is True
    assert result["summary_body_fact_ids"] == []


def test_v3_persists_fit_risks_and_presentation_strategy(tmp_path: Path) -> None:
    vault, path = project(tmp_path)
    upgrade_to_v3(path)
    plan = synthesis.load_synthesis_plan(path, tmp_path, vault)
    payload = {
        "summary_evidence": ["FACT-001"],
        "competencies": [],
        "experience": [
            {
                "evidence": ["ROLE-001"],
                "bullets": [
                    {
                        "text": "Improved operations.",
                        "evidence": ["FACT-001"],
                        "story": "operational-improvement",
                    }
                ],
            }
        ],
        "projects": [],
    }

    result = synthesis.audit_synthesis(payload, plan)

    assert result["version"] == 3
    assert result["target_mode"] == "direct"
    assert result["concept_fit"][0]["status"] == "demonstrated"
    assert result["reviewer_risks"][0]["status"] == "resolved"
    assert result["presentation"]["competencies"] == "omit"


def test_reviewer_risk_can_cite_intentionally_excluded_evidence(tmp_path: Path) -> None:
    vault, path = project(tmp_path)
    add_fact(
        vault / "facts" / "profile" / "FACT-003.md",
        "FACT-003",
        "incident",
    )
    upgrade_to_v3(path)
    text = path.read_text(encoding="utf-8")
    text = text.replace(
        "fact_ids: [FACT-001]\n    planning_action: Lead the role with the outcome story.",
        "fact_ids: [FACT-003, FACT-001]\n    planning_action: Omit the adverse fact and lead with the outcome story.",
    )
    text = text.replace(
        "exclusions: []",
        "exclusions:\n  - fact_id: FACT-003\n    reason: The adverse fact does not advance the target argument.",
    )
    path.write_text(text, encoding="utf-8")

    plan = synthesis.load_synthesis_plan(path, tmp_path, vault)

    assert plan.reviewer_risks[0].fact_ids == ("FACT-003", "FACT-001")
    assert plan.exclusions[0][0] == "FACT-003"


def test_v3_requires_every_direction_concept_classification(tmp_path: Path) -> None:
    vault, path = project(tmp_path)
    upgrade_to_v3(path)
    direction = tmp_path / "directions" / "example.md"
    direction.write_text(
        direction.read_text(encoding="utf-8").replace(
            "---\n\n# Direction",
            "  - id: second-concept\n---\n\n# Direction",
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=r"classify every direction concept.*second-concept"):
        synthesis.load_synthesis_plan(path, tmp_path, vault)


def test_v3_rejects_unsupported_concept_with_evidence(tmp_path: Path) -> None:
    vault, path = project(tmp_path)
    upgrade_to_v3(path)
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "status: demonstrated",
            "status: unsupported",
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="fact_ids must be empty when status is unsupported"):
        synthesis.load_synthesis_plan(path, tmp_path, vault)


def test_v3_enforces_competencies_decision(tmp_path: Path) -> None:
    vault, path = project(tmp_path)
    upgrade_to_v3(path)
    plan = synthesis.load_synthesis_plan(path, tmp_path, vault)
    payload = {
        "summary_evidence": ["FACT-001"],
        "competencies": [{"text": "Operations", "evidence": ["FACT-001"]}],
        "experience": [
            {
                "evidence": ["ROLE-001"],
                "bullets": [
                    {
                        "text": "Improved operations.",
                        "evidence": ["FACT-001"],
                        "story": "operational-improvement",
                    }
                ],
            }
        ],
        "projects": [],
    }

    with pytest.raises(ValueError, match="competencies section disagrees"):
        synthesis.audit_synthesis(payload, plan)


def test_v4_allows_focused_evidence_and_reports_unused_optional_facts(tmp_path: Path) -> None:
    vault, path = project(tmp_path)
    upgrade_to_v4(path)
    plan = synthesis.load_synthesis_plan(path, tmp_path, vault)
    payload = {
        "summary_evidence": ["FACT-001"],
        "competencies": [],
        "experience": [
            {
                "evidence": ["ROLE-001"],
                "bullets": [
                    {
                        "text": "Improved operations.",
                        "evidence": ["FACT-001"],
                        "story": "operational-improvement",
                    }
                ],
            }
        ],
        "projects": [],
    }

    result = synthesis.audit_synthesis(payload, plan)

    assert plan.stories[0].claim_focus == "Show the supported operational improvement."
    assert plan.stories[0].core_fact_ids == ("FACT-001",)
    assert result["version"] == 4
    assert result["body_fact_ids"] == ["FACT-001"]
    assert result["selected_fact_ids"] == ["FACT-001"]
    assert result["unused_optional_fact_ids"] == ["FACT-002"]
    assert result["story_evidence"] == [
        {
            "story_id": "operational-improvement",
            "claim_focus": "Show the supported operational improvement.",
            "core_fact_ids": ["FACT-001"],
            "available_fact_ids": ["FACT-001", "FACT-002"],
            "used_fact_ids": ["FACT-001"],
            "unused_optional_fact_ids": ["FACT-002"],
        }
    ]


def test_v4_rejects_missing_core_or_unplanned_story_evidence(tmp_path: Path) -> None:
    vault, path = project(tmp_path)
    upgrade_to_v4(path)
    plan = synthesis.load_synthesis_plan(path, tmp_path, vault)
    payload = {
        "summary_evidence": ["FACT-001"],
        "competencies": [],
        "experience": [
            {
                "evidence": ["ROLE-001"],
                "bullets": [
                    {
                        "text": "Added context.",
                        "evidence": ["FACT-002"],
                        "story": "operational-improvement",
                    }
                ],
            }
        ],
        "projects": [],
    }

    with pytest.raises(ValueError, match=r"missing_core=.*FACT-001"):
        synthesis.audit_synthesis(payload, plan)

    payload["experience"][0]["bullets"][0]["evidence"] = ["FACT-001", "FACT-999"]
    with pytest.raises(ValueError, match=r"unexpected=.*FACT-999"):
        synthesis.audit_synthesis(payload, plan)


def test_v4_requires_core_facts_to_belong_to_the_story(tmp_path: Path) -> None:
    vault, path = project(tmp_path)
    upgrade_to_v4(path)
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "core_fact_ids: [FACT-001]",
            "core_fact_ids: [FACT-999]",
            1,
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=r"cites unknown facts|subset of fact_ids"):
        synthesis.load_synthesis_plan(path, tmp_path, vault)


def test_v5_reports_role_story_allocation_without_imposing_a_fixed_count(
    tmp_path: Path,
) -> None:
    vault, path = project(tmp_path)
    upgrade_to_v5(path)
    plan = synthesis.load_synthesis_plan(path, tmp_path, vault)
    payload = {
        "summary_evidence": ["FACT-001"],
        "competencies": [],
        "experience": [
            {
                "evidence": ["ROLE-001"],
                "bullets": [
                    {
                        "text": "Improved operations.",
                        "evidence": ["FACT-001"],
                        "story": "operational-improvement",
                    }
                ],
            }
        ],
        "projects": [],
    }

    result = synthesis.audit_synthesis(payload, plan)

    assert result["version"] == 5
    assert result["role_arcs"] == [
        {
            "role_ids": ["ROLE-001"],
            "emphasis": "lead",
            "arc_focus": "Show an operating result followed by distinct technical depth.",
            "story_ids": ["operational-improvement", "supporting-detail"],
            "primary_jobs": ["outcome", "technical-depth"],
            "planned_story_count": 2,
            "used_story_ids": ["operational-improvement"],
            "used_story_count": 1,
            "omitted_story_ids": ["supporting-detail"],
            "selection_rationale": (
                "Give the only role enough space to make both supported signals visible."
            ),
            "omitted_signals": [],
        }
    ]


def test_v5_rejects_story_missing_from_role_arc(tmp_path: Path) -> None:
    vault, path = project(tmp_path)
    upgrade_to_v5(path)
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "story_ids: [operational-improvement, supporting-detail]",
            "story_ids: [operational-improvement]",
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=r"stories missing from role_arcs.*supporting-detail"):
        synthesis.load_synthesis_plan(path, tmp_path, vault)


def test_v5_requires_compression_strategy_to_match_role_arcs(tmp_path: Path) -> None:
    vault, path = project(tmp_path)
    upgrade_to_v5(path)
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "compressed_role_ids: []",
            "compressed_role_ids: [ROLE-001]",
            1,
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="compressed emphasis disagrees with presentation"):
        synthesis.load_synthesis_plan(path, tmp_path, vault)


def test_v5_rejects_role_arc_story_from_another_placement(tmp_path: Path) -> None:
    vault, path = project(tmp_path)
    upgrade_to_v5(path)
    add_fact(vault / "facts" / "profile" / "ROLE-002.md", "ROLE-002", "role")
    path.write_text(
        path.read_text(encoding="utf-8")
        .replace("progression: [ROLE-001]", "progression: [ROLE-001, ROLE-002]")
        .replace("role_ids: [ROLE-001]", "role_ids: [ROLE-002]", 1),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="story_ids disagree with role placement"):
        synthesis.load_synthesis_plan(path, tmp_path, vault)


def test_v6_resolves_page_budget_and_structured_claims(tmp_path: Path) -> None:
    vault, path = project(tmp_path)
    upgrade_to_v6(path)

    plan = synthesis.load_synthesis_plan(path, tmp_path, vault)

    assert plan.page_budget == synthesis.PageBudget(max_pages=2, source="direction-default")
    assert plan.stories[0].claim is not None
    assert plan.stories[0].claim.evidence.fact_ids == ("FACT-001",)
    assert plan.role_arcs[0].required_story_ids == ("operational-improvement",)
    assert plan.role_arcs[0].optional_story_ids == ("supporting-detail",)


def test_v6_rejects_page_budget_drift(tmp_path: Path) -> None:
    vault, path = project(tmp_path)
    upgrade_to_v6(path)
    path.write_text(
        path.read_text(encoding="utf-8").replace("max_pages: 2", "max_pages: 1", 1),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="page budget disagrees"):
        synthesis.load_synthesis_plan(path, tmp_path, vault)


def test_v6_requires_resume_evidence_to_match_claim_boundary(tmp_path: Path) -> None:
    vault, path = project(tmp_path)
    upgrade_to_v6(path)
    plan = synthesis.load_synthesis_plan(path, tmp_path, vault)
    payload = {
        "summary_evidence": ["FACT-001"],
        "competencies": [],
        "experience": [
            {
                "evidence": ["ROLE-001"],
                "bullets": [
                    {
                        "text": "Improved operations with extra unsupported detail.",
                        "evidence": ["FACT-001", "FACT-002"],
                        "story": "operational-improvement",
                    }
                ],
            }
        ],
        "projects": [],
    }

    with pytest.raises(ValueError, match="structured claim"):
        synthesis.audit_synthesis(payload, plan)


def test_v3_keeps_exact_story_evidence_behavior(tmp_path: Path) -> None:
    vault, path = project(tmp_path)
    upgrade_to_v3(path)
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "fact_ids: [FACT-001]\n    primary_job: outcome",
            "fact_ids: [FACT-001, FACT-002]\n    primary_job: outcome",
            1,
        ),
        encoding="utf-8",
    )
    plan = synthesis.load_synthesis_plan(path, tmp_path, vault)
    payload = {
        "summary_evidence": ["FACT-001"],
        "competencies": [],
        "experience": [
            {
                "evidence": ["ROLE-001"],
                "bullets": [
                    {
                        "text": "Improved operations.",
                        "evidence": ["FACT-001"],
                        "story": "operational-improvement",
                    }
                ],
            }
        ],
        "projects": [],
    }

    with pytest.raises(ValueError, match="evidence disagrees"):
        synthesis.audit_synthesis(payload, plan)
