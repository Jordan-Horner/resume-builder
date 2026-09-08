from pathlib import Path

from resume_builder.job_screening import (
    Confidence,
    CriterionAssessment,
    CriterionAssessmentOutcome,
)
from resume_builder.resume_screening import (
    DirectionalResumeCandidate,
    classify_directional_resumes,
    load_directional_resume_candidates,
    match_directional_resumes_by_cited_facts,
)
from resume_builder.screening_evidence import (
    CriterionEvidenceMatch,
    CriterionEvidenceStatus,
)


def _criterion(
    criterion_id: str,
    label: str,
    *,
    importance: str = "required",
    requirement_type: str = "supporting",
) -> CriterionEvidenceMatch:
    return CriterionEvidenceMatch(
        criterion_id=criterion_id,
        label=label,
        description=f"Demonstrate {label}.",
        importance=importance,
        requirement_type=requirement_type,
        status=CriterionEvidenceStatus.DEMONSTRATED_CANDIDATE,
        fact_ids=[f"FACT-{criterion_id.upper()}"][:3],
    )


def _assessment(
    criterion_id: str,
    outcome: CriterionAssessmentOutcome,
    fact_id: str,
) -> CriterionAssessment:
    return CriterionAssessment(
        criterion_id=criterion_id,
        outcome=outcome,
        confidence=Confidence.HIGH,
        fact_ids=[fact_id] if outcome != CriterionAssessmentOutcome.UNKNOWN else [],
        explanation=f"Assessment for {criterion_id}.",
    )


def test_resume_match_reuses_gate_first_classifier_and_selects_closest_resume() -> None:
    criteria = [
        _criterion(
            "incident-response",
            "Incident response",
            requirement_type="mandatory-role-defining",
        ),
        _criterion("terraform", "Terraform"),
    ]
    assessments = [
        _assessment(
            "incident-response",
            CriterionAssessmentOutcome.SUPPORTED,
            "FACT-INCIDENT-RESPONSE",
        ),
        _assessment("terraform", CriterionAssessmentOutcome.SUPPORTED, "FACT-TERRAFORM"),
    ]
    candidates = [
        DirectionalResumeCandidate(
            resume_id="resumes/baselines/sre.md",
            name="Site Reliability Engineer",
            sha256="a" * 64,
            fact_ids=["FACT-INCIDENT-RESPONSE", "FACT-TERRAFORM"],
        ),
        DirectionalResumeCandidate(
            resume_id="resumes/baselines/support.md",
            name="Technical Support Engineer",
            sha256="b" * 64,
            fact_ids=["FACT-INCIDENT-RESPONSE"],
        ),
    ]

    result = classify_directional_resumes(
        candidates,
        criteria,
        assessments,
        posting_complete=True,
    )

    assert result is not None
    assert result.label == "Strong match"
    assert result.resume_id == "resumes/baselines/sre.md"
    assert result.strongest_overlap == ["Incident response", "Terraform"]
    assert result.primary_gap is None
    assert result.alternative is not None
    assert result.alternative.label == "Unknown match"


def test_resume_match_does_not_turn_unretrieved_resume_evidence_into_a_weak_match() -> None:
    criterion = _criterion(
        "incident-response",
        "Incident response",
        requirement_type="mandatory-role-defining",
    )
    candidate = DirectionalResumeCandidate(
        resume_id="resumes/baselines/backend.md",
        name="Backend Engineer",
        sha256="a" * 64,
        fact_ids=["FACT-OTHER"],
    )

    result = classify_directional_resumes(
        [candidate],
        [criterion],
        [
            _assessment(
                "incident-response",
                CriterionAssessmentOutcome.SUPPORTED,
                "FACT-INCIDENT-RESPONSE",
            )
        ],
        posting_complete=True,
    )

    assert result is not None
    assert result.label == "Unknown match"
    assert result.primary_gap == "Incident response"


def test_loading_directional_resumes_uses_visible_name_and_content_hash(tmp_path: Path) -> None:
    folder = tmp_path / "resumes" / "baselines"
    folder.mkdir(parents=True)
    (folder / "sre.md").write_text(
        """---
version: 1
lang: en
page_format: letter
candidate:
  name: Example Person
  headline: Site Reliability Engineer
  email: example@example.invalid
  evidence: [FACT-SRE]
---

# Professional Summary

Operates reliable production services. <!-- evidence: FACT-SRE -->
""",
        encoding="utf-8",
    )
    (folder / "broken.md").write_text("# Not a canonical resume\n", encoding="utf-8")

    candidates = load_directional_resume_candidates(tmp_path)

    assert len(candidates) == 1
    assert candidates[0].name == "Site Reliability Engineer"
    assert candidates[0].fact_ids == ["FACT-SRE"]
    assert len(candidates[0].sha256) == 64


def test_posting_wide_match_selects_only_unique_evidence_winner() -> None:
    candidates = [
        DirectionalResumeCandidate(
            resume_id="resumes/baselines/sre.md",
            name="Site Reliability Engineer",
            sha256="a" * 64,
            fact_ids=["FACT-INCIDENT", "FACT-TERRAFORM"],
        ),
        DirectionalResumeCandidate(
            resume_id="resumes/baselines/support.md",
            name="Technical Support Engineer",
            sha256="b" * 64,
            fact_ids=["FACT-INCIDENT"],
        ),
    ]

    result = match_directional_resumes_by_cited_facts(
        candidates,
        ["FACT-INCIDENT", "FACT-TERRAFORM"],
    )

    assert result is not None
    assert result.resume_id == "resumes/baselines/sre.md"
    assert result.label == "Strong match"
    assert result.alternative is not None
    assert result.alternative.resume_id == "resumes/baselines/support.md"


def test_posting_wide_match_abstains_when_multiple_resumes_tie() -> None:
    candidates = [
        DirectionalResumeCandidate(
            resume_id=f"resumes/baselines/{name}.md",
            name=name.title(),
            sha256=character * 64,
            fact_ids=["FACT-SHARED"],
        )
        for name, character in (("sre", "a"), ("support", "b"))
    ]

    assert match_directional_resumes_by_cited_facts(candidates, ["FACT-SHARED"]) is None
