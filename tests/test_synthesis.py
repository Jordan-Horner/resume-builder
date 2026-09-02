from __future__ import annotations

import json
from pathlib import Path

import pytest

from resume_builder import selection_guard, selection_review, synthesis
from resume_builder.synthesis_models import summary_strategy_payload


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


def upgrade_to_v7(path: Path) -> None:
    """Replace the fixture with an explicit content template and visual theme."""
    upgrade_to_v6(path)
    templates = path.parents[2] / "templates"
    content = templates / "resume-templates" / "technical-classic.yaml"
    content.parent.mkdir(parents=True)
    content.write_text(
        """version: 1
id: technical-classic
section_order: [summary, experience, projects, education, certifications, skills]
required_sections: [summary, experience, skills]
optional_sections: [projects, education, certifications]
forbidden_sections: [competencies]
""",
        encoding="utf-8",
    )
    renderer = templates / "resume-template.html"
    renderer.write_text(
        "{{LANG}}{{PAGE_SIZE}}{{PAGE_WIDTH}}{{PAGE_MIN_HEIGHT}}{{TITLE}}"
        "{{HEADER_EVIDENCE}}{{NAME}}{{HEADLINE}}{{CONTACT}}{{PREVIEW_NOTICE}}"
        "{{REVIEW_ISSUES}}"
        "{{RESUME_SECTIONS}}",
        encoding="utf-8",
    )
    theme = templates / "themes" / "clean-teal.yaml"
    theme.parent.mkdir(parents=True)
    theme.write_text(
        """version: 1
id: clean-teal
renderer: templates/resume-template.html
""",
        encoding="utf-8",
    )
    text = path.read_text(encoding="utf-8")
    text = text.replace("version: 6", "version: 7", 1)
    text = text.replace(
        "direction: directions/example.md",
        """direction: directions/example.md
resume_template:
  content: technical-classic
  theme: clean-teal""",
        1,
    )
    path.write_text(text, encoding="utf-8")


def upgrade_to_v8(path: Path) -> None:
    """Require a visible role anchor for every experience placement."""
    upgrade_to_v7(path)
    text = path.read_text(encoding="utf-8")
    text = text.replace("version: 7", "version: 8", 1)
    text = text.replace(
        "    required_story_ids: [operational-improvement]",
        """    required_story_ids: [operational-improvement]
    role_anchor_story_ids: [operational-improvement]""",
        1,
    )
    path.write_text(text, encoding="utf-8")


def upgrade_to_v9(path: Path) -> None:
    """Require distinct role-anchor and selling stories for every placement."""
    upgrade_to_v8(path)
    text = path.read_text(encoding="utf-8")
    text = text.replace("version: 8", "version: 9", 1)
    text = text.replace(
        "    required_story_ids: [operational-improvement]",
        "    required_story_ids: [operational-improvement, supporting-detail]",
        1,
    )
    text = text.replace(
        "    optional_story_ids: [supporting-detail]", "    optional_story_ids: []", 1
    )
    text = text.replace("    importance: supporting", "    importance: core", 1)
    text = text.replace(
        "    role_anchor_story_ids: [operational-improvement]",
        """    role_anchor_story_ids: [operational-improvement]
    role_selling_story_ids: [supporting-detail]""",
        1,
    )
    path.write_text(text, encoding="utf-8")


def upgrade_to_v10(path: Path) -> None:
    """Expose scored core-job interpretations and their decision source."""
    upgrade_to_v9(path)
    text = path.read_text(encoding="utf-8")
    text = text.replace("version: 9", "version: 10", 1)
    text = text.replace(
        "    role_selling_story_ids: [supporting-detail]",
        """    role_selling_story_ids: [supporting-detail]
    core_job_candidates:
      - id: operational-owner
        description: Own the core operational workflow.
        confidence: 86
      - id: technical-specialist
        description: Provide technical depth within the workflow.
        confidence: 70
    selected_core_job_id: operational-owner
    core_job_decision: model-selected""",
        1,
    )
    path.write_text(text, encoding="utf-8")


def upgrade_to_v11(path: Path) -> None:
    """Require a structured summary strategy without changing visible prose."""
    upgrade_to_v10(path)
    text = path.read_text(encoding="utf-8")
    text = text.replace("version: 10", "version: 11", 1)
    text = text.replace(
        "summary_fact_ids: [FACT-001]",
        """summary_fact_ids: [FACT-001]
summary_strategy:
  reader_conclusion: Intended hiring conclusion for the planned resume.
  professional_frame: Evidence-supported professional frame.
  fit_posture:
    classification: direct
    controlling_criterion_ids: []
    bounded_criterion_ids: []
  operating_scope_fact_ids: [FACT-001]
  proof_anchor_story_id: operational-improvement
  delegated_to_body: [secondary detail]""",
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


def test_unresolved_reviewer_risk_rejects_whitespace_only_gap(tmp_path: Path) -> None:
    vault, path = project(tmp_path)
    upgrade_to_v3(path)
    text = path.read_text(encoding="utf-8")
    text = text.replace(
        "status: resolved\n    fact_ids: [FACT-001]",
        "status: unresolved\n    fact_ids: []",
        1,
    ).replace("gaps: []", 'gaps: [" "]', 1)
    path.write_text(text, encoding="utf-8")

    with pytest.raises(ValueError, match="synthesis gaps must be a list of non-empty strings"):
        synthesis.load_synthesis_plan(path, tmp_path, vault)


def test_unresolved_reviewer_risk_still_requires_a_gap(tmp_path: Path) -> None:
    vault, path = project(tmp_path)
    upgrade_to_v3(path)
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "status: resolved\n    fact_ids: [FACT-001]",
            "status: unresolved\n    fact_ids: []",
            1,
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="unresolved synthesis reviewer risks require"):
        synthesis.load_synthesis_plan(path, tmp_path, vault)


def test_synthesis_lists_strip_meaningful_values(tmp_path: Path) -> None:
    vault, path = project(tmp_path)
    upgrade_to_v3(path)
    text = path.read_text(encoding="utf-8")
    text = text.replace(
        "status: resolved\n    fact_ids: [FACT-001]",
        "status: unresolved\n    fact_ids: []",
        1,
    )
    text = text.replace("progression: [ROLE-001]", 'progression: [" ROLE-001 "]', 1)
    text = text.replace("gaps: []", 'gaps: ["  Missing verified scale  "]', 1)
    path.write_text(text, encoding="utf-8")

    plan = synthesis.load_synthesis_plan(path, tmp_path, vault)

    assert plan.progression == ("ROLE-001",)
    assert plan.gaps == ("Missing verified scale",)


def test_synthesis_lists_reject_duplicates_after_stripping(tmp_path: Path) -> None:
    vault, path = project(tmp_path)
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "gaps: []",
            'gaps: ["Missing verified scale", " Missing verified scale "]',
            1,
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="synthesis gaps must not contain duplicates"):
        synthesis.load_synthesis_plan(path, tmp_path, vault)


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


def test_v7_loads_named_content_template_and_theme(tmp_path: Path) -> None:
    vault, path = project(tmp_path)
    upgrade_to_v7(path)

    plan = synthesis.load_synthesis_plan(path, tmp_path, vault)

    assert plan.resume_template is not None
    assert plan.resume_template.content.template_id == "technical-classic"
    assert plan.resume_template.content.section_order[-1] == "skills"
    assert plan.resume_template.theme.theme_id == "clean-teal"


def test_v8_requires_role_anchor_from_required_stories(tmp_path: Path) -> None:
    vault, path = project(tmp_path)
    upgrade_to_v8(path)

    plan = synthesis.load_synthesis_plan(path, tmp_path, vault)

    assert plan.role_arcs[0].role_anchor_story_ids == ("operational-improvement",)


def test_v8_rejects_optional_story_as_role_anchor(tmp_path: Path) -> None:
    vault, path = project(tmp_path)
    upgrade_to_v8(path)
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "role_anchor_story_ids: [operational-improvement]",
            "role_anchor_story_ids: [supporting-detail]",
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="role_anchor_story_ids must reference required"):
        synthesis.load_synthesis_plan(path, tmp_path, vault)


def test_v8_rejects_missing_role_anchor_field(tmp_path: Path) -> None:
    vault, path = project(tmp_path)
    upgrade_to_v8(path)
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "    role_anchor_story_ids: [operational-improvement]\n",
            "",
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="role_anchor_story_ids"):
        synthesis.load_synthesis_plan(path, tmp_path, vault)


def test_v9_requires_distinct_selling_story_from_required_stories(tmp_path: Path) -> None:
    vault, path = project(tmp_path)
    upgrade_to_v9(path)

    plan = synthesis.load_synthesis_plan(path, tmp_path, vault)

    assert plan.role_arcs[0].role_anchor_story_ids == ("operational-improvement",)
    assert plan.role_arcs[0].role_selling_story_ids == ("supporting-detail",)


def test_v9_rejects_role_anchor_reused_as_selling_story(tmp_path: Path) -> None:
    vault, path = project(tmp_path)
    upgrade_to_v9(path)
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "role_selling_story_ids: [supporting-detail]",
            "role_selling_story_ids: [operational-improvement]",
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="both role anchors and selling stories"):
        synthesis.load_synthesis_plan(path, tmp_path, vault)


def test_v9_rejects_missing_selling_story_field(tmp_path: Path) -> None:
    vault, path = project(tmp_path)
    upgrade_to_v9(path)
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "    role_selling_story_ids: [supporting-detail]\n",
            "",
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="role_selling_story_ids"):
        synthesis.load_synthesis_plan(path, tmp_path, vault)


def test_v10_loads_scored_core_job_candidates(tmp_path: Path) -> None:
    vault, path = project(tmp_path)
    upgrade_to_v10(path)

    plan = synthesis.load_synthesis_plan(path, tmp_path, vault)

    arc = plan.role_arcs[0]
    assert arc.selected_core_job_id == "operational-owner"
    assert arc.core_job_decision == "model-selected"
    assert [(item.candidate_id, item.confidence) for item in arc.core_job_candidates] == [
        ("operational-owner", 86),
        ("technical-specialist", 70),
    ]


def test_v10_requires_user_confirmation_when_core_job_scores_are_close(
    tmp_path: Path,
) -> None:
    vault, path = project(tmp_path)
    upgrade_to_v10(path)
    path.write_text(
        path.read_text(encoding="utf-8").replace("confidence: 70", "confidence: 80", 1),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=r"core job candidates are close \(6 point margin\)"):
        synthesis.load_synthesis_plan(path, tmp_path, vault)


def test_v10_accepts_user_confirmed_close_core_job_scores(tmp_path: Path) -> None:
    vault, path = project(tmp_path)
    upgrade_to_v10(path)
    path.write_text(
        path.read_text(encoding="utf-8")
        .replace("confidence: 70", "confidence: 80", 1)
        .replace("core_job_decision: model-selected", "core_job_decision: user-confirmed", 1),
        encoding="utf-8",
    )

    plan = synthesis.load_synthesis_plan(path, tmp_path, vault)

    assert plan.role_arcs[0].core_job_decision == "user-confirmed"


def test_v10_reports_core_job_scores_in_role_arc_payload(tmp_path: Path) -> None:
    vault, path = project(tmp_path)
    upgrade_to_v10(path)
    plan = synthesis.load_synthesis_plan(path, tmp_path, vault)

    assert plan.summary_strategy is None
    payload = synthesis.role_arc_payloads(plan)[0]

    assert payload["core_job"] == {
        "selected_id": "operational-owner",
        "decision": "model-selected",
        "candidates": [
            {
                "id": "operational-owner",
                "description": "Own the core operational workflow.",
                "confidence": 86,
            },
            {
                "id": "technical-specialist",
                "description": "Provide technical depth within the workflow.",
                "confidence": 70,
            },
        ],
    }


def test_v11_loads_and_reports_structured_summary_strategy(tmp_path: Path) -> None:
    vault, path = project(tmp_path)
    upgrade_to_v11(path)

    plan = synthesis.load_synthesis_plan(path, tmp_path, vault)
    assert plan.summary_strategy is not None
    assert plan.summary_strategy.fit_posture.classification == "direct"
    assert plan.summary_strategy.operating_scope_fact_ids == ("FACT-001",)
    assert plan.summary_strategy.proof_anchor_story_id == "operational-improvement"
    assert summary_strategy_payload(plan.summary_strategy) == {
        "reader_conclusion": "Intended hiring conclusion for the planned resume.",
        "professional_frame": "Evidence-supported professional frame.",
        "fit_posture": {
            "classification": "direct",
            "controlling_criterion_ids": [],
            "bounded_criterion_ids": [],
        },
        "operating_scope_fact_ids": ["FACT-001"],
        "proof_anchor_story_id": "operational-improvement",
        "delegated_to_body": ["secondary detail"],
    }

    payload = {
        "section_order": [
            "summary",
            "experience",
            "projects",
            "education",
            "certifications",
            "skills",
        ],
        "summary": {"text": "Improves important operational work.", "evidence": ["FACT-001"]},
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
                    },
                    {
                        "text": "Added technical depth.",
                        "evidence": ["FACT-002"],
                        "story": "supporting-detail",
                    },
                ],
            }
        ],
        "projects": [],
        "education": [],
        "certifications": [],
        "skills": [],
    }
    audited = synthesis.audit_synthesis(payload, plan)
    assert audited["summary_strategy"] == summary_strategy_payload(plan.summary_strategy)
    selected = selection_guard.build_selection(plan, audited)
    assert selected["summary_strategy"] == summary_strategy_payload(plan.summary_strategy)
    manifest = tmp_path / "build" / "resumes" / "operations" / "build-manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text("{}", encoding="utf-8")
    package_path = selection_review.build_selection_review_package(
        tmp_path,
        plan.resume,
        plan,
        selected,
        manifest=manifest,
    )
    package = json.loads(package_path.read_text(encoding="utf-8"))
    assert package["review_context"]["summary_strategy"] == summary_strategy_payload(
        plan.summary_strategy
    )


def test_v11_accepts_direct_fit_with_bounded_gaps(tmp_path: Path) -> None:
    vault, path = project(tmp_path)
    upgrade_to_v11(path)
    path.write_text(
        path.read_text(encoding="utf-8")
        .replace("classification: direct", "classification: direct-with-bounded-gaps", 1)
        .replace("bounded_criterion_ids: []", "bounded_criterion_ids: [criterion-b]", 1),
        encoding="utf-8",
    )

    plan = synthesis.load_synthesis_plan(path, tmp_path, vault)

    assert plan.summary_strategy is not None
    assert plan.summary_strategy.fit_posture.bounded_criterion_ids == ("criterion-b",)


@pytest.mark.parametrize(
    ("replacement", "message"),
    [
        (
            "operating_scope_fact_ids: [FACT-002]",
            "operating scope must be included in summary_fact_ids",
        ),
        (
            "proof_anchor_story_id: supporting-detail",
            "proof anchor core facts must be included in summary_fact_ids",
        ),
        (
            "classification: adjacent",
            "fit posture disagrees with target_mode",
        ),
    ],
)
def test_v11_rejects_incoherent_summary_strategy(
    tmp_path: Path,
    replacement: str,
    message: str,
) -> None:
    vault, path = project(tmp_path)
    upgrade_to_v11(path)
    original = {
        "operating_scope_fact_ids: [FACT-002]": "operating_scope_fact_ids: [FACT-001]",
        "proof_anchor_story_id: supporting-detail": (
            "proof_anchor_story_id: operational-improvement"
        ),
        "classification: adjacent": "classification: direct",
    }[replacement]
    path.write_text(
        path.read_text(encoding="utf-8").replace(original, replacement, 1),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=message):
        synthesis.load_synthesis_plan(path, tmp_path, vault)


def test_v11_requires_bounded_gap_for_direct_bounded_posture(tmp_path: Path) -> None:
    vault, path = project(tmp_path)
    upgrade_to_v11(path)
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "classification: direct", "classification: direct-with-bounded-gaps", 1
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="requires bounded criteria"):
        synthesis.load_synthesis_plan(path, tmp_path, vault)


def test_v7_rejects_duplicate_content_template_sections(tmp_path: Path) -> None:
    vault, path = project(tmp_path)
    upgrade_to_v7(path)
    content = tmp_path / "templates" / "resume-templates" / "technical-classic.yaml"
    content.write_text(
        content.read_text(encoding="utf-8").replace(
            "section_order: [summary, experience",
            "section_order: [summary, summary, experience",
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="section_order must not contain duplicates"):
        synthesis.load_synthesis_plan(path, tmp_path, vault)


@pytest.mark.parametrize(
    ("renderer", "message"),
    [
        (
            "{{NAME}}{{HEADLINE}}{{CONTACT}}{{PREVIEW_NOTICE}}{{REVIEW_ISSUES}}",
            "required placeholder exactly once",
        ),
        (
            "{{LANG}}{{PAGE_SIZE}}{{PAGE_WIDTH}}{{PAGE_MIN_HEIGHT}}{{TITLE}}"
            "{{HEADER_EVIDENCE}}{{NAME}}{{HEADLINE}}{{CONTACT}}{{PREVIEW_NOTICE}}"
            "{{REVIEW_ISSUES}}"
            "{{RESUME_SECTIONS}}{{SKILLS_SECTION}}",
            "legacy section placeholders",
        ),
    ],
)
def test_v7_rejects_theme_renderer_that_can_omit_or_reorder_sections(
    tmp_path: Path,
    renderer: str,
    message: str,
) -> None:
    vault, path = project(tmp_path)
    upgrade_to_v7(path)
    (tmp_path / "templates" / "resume-template.html").write_text(renderer, encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        synthesis.load_synthesis_plan(path, tmp_path, vault)


def test_v7_rejects_section_architecture_drift(tmp_path: Path) -> None:
    vault, path = project(tmp_path)
    upgrade_to_v7(path)
    plan = synthesis.load_synthesis_plan(path, tmp_path, vault)
    payload = {
        "section_order": ["summary", "skills", "experience"],
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
        "education": [],
        "certifications": [],
        "skills": [{"category": "Systems", "items": ["Linux"], "evidence": ["FACT-001"]}],
    }

    with pytest.raises(ValueError, match="section architecture disagrees"):
        synthesis.audit_synthesis(payload, plan)


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
