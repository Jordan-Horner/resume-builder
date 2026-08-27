from __future__ import annotations

import json
from pathlib import Path

import pytest

from resume_builder import job_matching
from resume_builder.match_grading import classify_match


def judgment(
    criterion_id: str,
    *,
    importance: str = "required",
    requirement_type: str = "supporting",
    status: str = "met",
) -> dict[str, object]:
    has_evidence = status in {"met", "partial"}
    return {
        "criterion_id": criterion_id,
        "importance": importance,
        "requirement_type": requirement_type,
        "status": status,
        "evidence_sufficiency": "high" if status == "met" else "low",
        "confidence": "high",
        "evidence_blocks": ["experience[0].bullets[0]"] if has_evidence else [],
        "evidence_fact_ids": ["OPS-001"] if has_evidence else [],
        "substitution_basis": (
            "The posting explicitly permits an equivalent platform."
            if requirement_type == "mandatory-substitutable"
            else ""
        ),
        "gap": "Required proof is not visible." if status != "met" else "",
    }


def case(*criteria: dict[str, object], evidence_complete: bool = True) -> dict[str, object]:
    return {
        "version": 1,
        "evidence_complete": evidence_complete,
        "criteria": list(criteria),
    }


def test_classifier_keeps_resume_quality_separate_from_role_defining_gates() -> None:
    result = classify_match(
        case(
            judgment("foundation-models"),
            judgment(
                "ai-generated-code-debugging",
                requirement_type="mandatory-role-defining",
                status="undecidable",
            ),
            judgment(
                "cybersecurity",
                importance="preferred",
                requirement_type="preferred",
                status="partial",
            ),
        )
    )

    assert result["label"] == "Weak match"
    assert result["controlling_criterion_ids"] == ["ai-generated-code-debugging"]
    assert result["preferred_gap_ids"] == ["cybersecurity"]
    assert "score" not in result


def test_classifier_returns_partial_for_bridgeable_supporting_gap() -> None:
    result = classify_match(
        case(
            judgment("incident-response"),
            judgment("reporting", status="partial"),
        )
    )

    assert result["label"] == "Partial match"
    assert result["required_gap_ids"] == ["reporting"]


def test_classifier_returns_unknown_only_when_required_evidence_is_incomplete() -> None:
    result = classify_match(
        case(
            judgment(
                "platform-tenure",
                requirement_type="mandatory-role-defining",
                status="undecidable",
            ),
            evidence_complete=False,
        )
    )

    assert result["label"] == "Unknown match"
    assert result["controlling_criterion_ids"] == ["platform-tenure"]


def test_classifier_ignores_preferred_and_lifestyle_gaps_for_capability_label() -> None:
    result = classify_match(
        case(
            judgment("incident-response"),
            judgment(
                "preferred-tool",
                importance="preferred",
                requirement_type="preferred",
                status="not_met",
            ),
            judgment(
                "travel",
                importance="preferred",
                requirement_type="lifestyle",
                status="undecidable",
            ),
        )
    )

    assert result["label"] == "Strong match"
    assert result["preferred_gap_ids"] == ["preferred-tool", "travel"]
    assert result["lifestyle_risk_ids"] == ["travel"]


def test_classification_case_requires_evidence_for_positive_judgments() -> None:
    invalid = judgment("incident-response")
    invalid["evidence_fact_ids"] = []

    with pytest.raises(ValueError, match="requires evidence blocks and fact IDs"):
        classify_match(case(invalid))


def test_substitutable_requirement_requires_explicit_posting_basis() -> None:
    invalid = judgment(
        "workflow-platform",
        requirement_type="mandatory-substitutable",
    )
    invalid["substitution_basis"] = ""

    with pytest.raises(ValueError, match="explicit substitution basis"):
        classify_match(case(invalid))


def test_classify_command_is_read_only_and_returns_fixed_label(
    tmp_path: Path, run_main, capsys
) -> None:
    path = tmp_path / "case.json"
    path.write_text(
        json.dumps(case(judgment("incident-response"))),
        encoding="utf-8",
    )

    assert run_main(job_matching.main, "classify", path) == 0
    result = json.loads(capsys.readouterr().out)

    assert result["label"] == "Strong match"
    assert list(tmp_path.iterdir()) == [path]
