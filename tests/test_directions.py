from __future__ import annotations

import json
from pathlib import Path

import pytest

from resume_builder import directions
from resume_builder.synthesis import ConceptFit, SynthesisPlan


def direction_markdown(*, basis: str = "user-confirmed", source_kind: str = "user") -> str:
    return f"""---
schema_version: 1
slug: support-operations
status: approved
maturity: provisional
target_titles:
  - Example Operations Lead
audiences:
  - Support leadership
positioning: Turn difficult escalations into repeatable example operations.
priority_concepts:
  - id: incident-management
    label: Incident management
    weight: 5
    terms:
      - incident management
    evidence_themes:
      - incident-response
    basis: {basis}
    source_ids:
      - DIRSRC-001
de_emphasize:
  - General customer service
avoid_terms:
  - Call center
defaults:
  max_pages: 2
  page_format: letter
  minimum_coverage: 75
success_criteria:
  - Lead with operational improvement.
sources:
  - id: DIRSRC-001
    kind: {source_kind}
    reference: User direction intake
    as_of: 2026-08-16
---

# Example Operations

This profile shapes selection and positioning; it does not introduce candidate facts.
"""


def resume_markdown(summary: str = "Incident management improves example operations.") -> str:
    return f"""---
version: 1
lang: en
page_format: letter
candidate:
  name: Example Person
  headline: Example Operations
  email: example@example.com
  evidence: [SUP-001]
---
# Professional Summary

{summary} <!-- evidence: SUP-001 -->
"""


def project(tmp_path: Path) -> tuple[Path, Path, Path]:
    vault = tmp_path / "vault"
    facts = vault / "facts" / "skills"
    facts.mkdir(parents=True)
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
    (facts / "SUP-001.md").write_text(
        """---
schema_version: 2
id: SUP-001
title: "Incident management"
type: responsibility
status: confirmed
category: skills
sources:
  - SRC-0123456789ab
themes:
  - incident-response
---

# Incident management

Managed incident response and improved example operations.
""",
        encoding="utf-8",
    )
    profile = tmp_path / "directions" / "support-operations.md"
    profile.parent.mkdir()
    profile.write_text(direction_markdown(), encoding="utf-8")
    resume = tmp_path / "resumes" / "baselines" / "support-operations.md"
    resume.parent.mkdir(parents=True)
    resume.write_text(resume_markdown(), encoding="utf-8")
    return vault, profile, resume


def test_direction_profile_validates_and_enforces_source_basis(tmp_path: Path) -> None:
    path = tmp_path / "support-operations.md"
    path.write_text(direction_markdown(), encoding="utf-8")

    profile, body = directions.parse_direction(path)
    assert profile["maturity"] == "provisional"
    assert body.startswith("# Example Operations")

    path.write_text(
        direction_markdown(basis="research-supported", source_kind="user"), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="requires a research source"):
        directions.parse_direction(path)


def test_direction_validate_and_audit_commands(tmp_path: Path, run_main) -> None:
    vault, profile, resume = project(tmp_path)

    assert run_main(directions.main, "validate", profile, "--vault-root", vault) == 0
    assert run_main(directions.main, "audit", profile, resume, "--vault-root", vault) == 0

    resume.write_text(resume_markdown("Workflow documentation."), encoding="utf-8")
    fact_path = vault / "facts" / "skills" / "SUP-001.md"
    fact_path.write_text(
        fact_path.read_text(encoding="utf-8").replace("incident-response", "documentation"),
        encoding="utf-8",
    )
    assert run_main(directions.main, "audit", profile, resume, "--vault-root", vault) == 1


def test_direction_validation_reports_unknown_vault_theme_as_candidate_gap(
    tmp_path: Path, run_main
) -> None:
    vault, profile, _ = project(tmp_path)
    profile.write_text(
        direction_markdown().replace("incident-response", "missing-theme"), encoding="utf-8"
    )

    parsed, _ = directions.parse_direction(profile)
    warnings = directions.theme_reference_warnings(parsed, vault)
    assert "candidate gap" in warnings[0]
    assert run_main(directions.main, "validate", profile, "--vault-root", vault) == 0


def test_phrase_matching_uses_token_boundaries() -> None:
    assert directions.phrase_present("SQL", directions.normalize_phrase("SQL operations"))
    assert not directions.phrase_present("SQL", directions.normalize_phrase("NoSQL operations"))
    assert directions.phrase_present("workflow", directions.normalize_phrase("Built a workflow."))
    assert directions.phrase_present(
        "incident.io", directions.normalize_phrase("Used incident.io.")
    )


def test_direction_separates_evidence_from_same_claim_term_alignment(tmp_path: Path) -> None:
    vault, profile_path, _ = project(tmp_path)
    profile, _ = directions.parse_direction(profile_path)
    payload = {
        "candidate": {
            "name": "Example Person",
            "headline": "Example Operations",
            "evidence": ["SUP-001"],
        },
        "summary": "Incident management",
        "summary_evidence": [],
    }

    result = directions.audit_direction(profile, payload, vault)

    assert result["score"] == 100
    assert result["evidence_score"] == 100
    assert result["experience_evidence_score"] == 0
    assert result["vocabulary_score"] == 100
    assert result["concepts"][0]["coverage"] == "full"
    assert result["concepts"][0]["listed_only_fact_ids"] == ["SUP-001"]
    assert result["editorial_status"] == "not-reviewed"
    assert result["concepts"][0]["alignment_coverage"] == "partial"
    assert result["concepts"][0]["matched_claims"] == []


def test_evidence_supported_paraphrase_passes_without_configured_vocabulary(
    tmp_path: Path,
) -> None:
    vault, profile_path, _ = project(tmp_path)
    profile, _ = directions.parse_direction(profile_path)
    payload = {
        "page_format": "letter",
        "candidate": {
            "name": "Example Person",
            "headline": "Service Reliability",
            "evidence": ["SUP-001"],
        },
        "summary": "Kept production response organized and repeatable.",
        "summary_evidence": ["SUP-001"],
    }

    result = directions.audit_direction(profile, payload, vault)

    assert result["passes"] is True
    assert result["evidence_passes"] is True
    assert result["evidence_score"] == 100
    assert result["experience_evidence_score"] == 0
    assert result["vocabulary_score"] == 0
    assert result["concepts"][0]["vocabulary_coverage"] == "missing"


def test_direction_reports_experience_evidence_separately(tmp_path: Path) -> None:
    vault, profile_path, _ = project(tmp_path)
    profile, _ = directions.parse_direction(profile_path)
    payload = {
        "page_format": "letter",
        "candidate": {
            "name": "Example Person",
            "headline": "Example Operations",
            "evidence": ["SUP-001"],
        },
        "summary": "Keeps production response organized.",
        "summary_evidence": [],
        "experience": [
            {
                "company": "Example",
                "role": "Support Lead",
                "dates": "2024 - Present",
                "evidence": ["SUP-001"],
                "bullets": [],
            }
        ],
    }

    result = directions.audit_direction(profile, payload, vault)

    assert result["evidence_score"] == 100
    assert result["experience_evidence_score"] == 100
    assert result["concepts"][0]["experience_evidence_fact_ids"] == ["SUP-001"]
    assert result["concepts"][0]["listed_only_fact_ids"] == []


def test_direction_reports_v3_target_mode_and_planned_fit(tmp_path: Path) -> None:
    vault, profile_path, resume_path = project(tmp_path)
    profile, _ = directions.parse_direction(profile_path)
    plan = SynthesisPlan(
        source=tmp_path / "resumes" / "plans" / "support-operations.yaml",
        version=3,
        resume=resume_path,
        direction=profile_path,
        target_argument="Test an adjacent direction.",
        summary_job="Establish the transferable operating pattern.",
        summary_fact_ids=("SUP-001",),
        summary_body_fact_ids=(),
        progression=(),
        stories=(),
        exclusions=(),
        gaps=("Direct incident-program ownership is not established.",),
        target_mode="adjacent",
        concept_fit=(
            ConceptFit(
                concept_id="incident-management",
                status="transferable",
                fact_ids=("SUP-001",),
                rationale="Adjacent support evidence demonstrates the operating pattern.",
            ),
        ),
    )
    payload = {
        "page_format": "letter",
        "candidate": {
            "name": "Example Person",
            "headline": "Example Operations",
            "evidence": ["SUP-001"],
        },
        "summary": "Keeps production response organized.",
        "summary_evidence": ["SUP-001"],
    }

    result = directions.audit_direction(profile, payload, vault, plan=plan)

    assert result["target_mode"] == "adjacent"
    assert result["fit_breakdown"]["transferable"] == ["incident-management"]
    assert result["concepts"][0]["planned_fit"] == "transferable"


def test_essential_terminology_is_a_small_explicit_gate(tmp_path: Path) -> None:
    vault, profile_path, _ = project(tmp_path)
    profile_path.write_text(
        direction_markdown().replace(
            "priority_concepts:", "essential_terms:\n  - example operations\npriority_concepts:"
        ),
        encoding="utf-8",
    )
    profile, _ = directions.parse_direction(profile_path)
    payload = {
        "page_format": "letter",
        "candidate": {
            "name": "Example Person",
            "headline": "Service Reliability",
            "evidence": ["SUP-001"],
        },
        "summary": "Kept production response organized and repeatable.",
        "summary_evidence": ["SUP-001"],
    }

    result = directions.audit_direction(profile, payload, vault)

    assert result["evidence_score"] == 100
    assert result["essential_terminology"]["missing"] == ["example operations"]
    assert result["passes"] is False


def test_repeated_direction_terms_and_copied_labels_warn_without_failing(
    tmp_path: Path,
) -> None:
    vault, profile_path, _ = project(tmp_path)
    profile_path.write_text(
        direction_markdown()
        .replace("Incident management", "Customer outcomes")
        .replace("incident management", "customer outcomes"),
        encoding="utf-8",
    )
    profile, _ = directions.parse_direction(profile_path)
    payload = {
        "page_format": "letter",
        "candidate": {
            "name": "Example Person",
            "headline": "Customer Outcomes",
            "evidence": ["SUP-001"],
        },
        "summary": (
            "Customer outcomes customer outcomes customer outcomes customer outcomes "
            "customer outcomes customer outcomes."
        ),
        "summary_evidence": ["SUP-001"],
        "competencies": [
            {"text": "Customer Outcomes", "evidence": ["SUP-001"]},
            {"text": "Customer outcomes for teams", "evidence": ["SUP-001"]},
            {"text": "Customer outcomes in delivery", "evidence": ["SUP-001"]},
            {"text": "Customer outcomes under pressure", "evidence": ["SUP-001"]},
            {"text": "Customer outcomes at scale", "evidence": ["SUP-001"]},
        ],
    }

    result = directions.audit_direction(profile, payload, vault)

    assert result["passes"] is True
    assert result["style_diagnostics"]["target_term_concentration"]
    assert result["style_diagnostics"]["copied_concept_labels"]
    assert result["style_diagnostics"]["advisory_only"] is True
