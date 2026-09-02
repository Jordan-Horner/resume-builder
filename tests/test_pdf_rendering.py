from __future__ import annotations

from pathlib import Path

import pytest
from reportlab.pdfgen.canvas import Canvas

from resume_builder.pdf_rendering import (
    audit_pdf,
    normalized_tokens,
    tokens_recovered,
)


def payload() -> dict[str, object]:
    return {
        "candidate": {
            "name": "Test Candidate",
            "headline": "Support Engineer",
            "evidence": ["P-001"],
        },
        "summary": "Improves example workflows.",
        "summary_evidence": ["P-002"],
        "competencies": [],
        "experience": [],
        "projects": [],
        "education": [],
        "certifications": [],
        "skills": [],
    }


def make_pdf(path: Path, lines: list[str]) -> None:
    document = Canvas(str(path))
    for index, line in enumerate(lines):
        if index:
            document.showPage()
        document.drawString(72, 720, line)
    document.save()


def test_pdf_audit_recovers_claims_and_rejects_empty_pages(tmp_path: Path) -> None:
    good = tmp_path / "good.pdf"
    make_pdf(
        good,
        ["Test Candidate Support Engineer Professional Summary Improves example workflows."],
    )
    result = audit_pdf(good, payload())
    assert result["pages"] == 1
    assert result["extractable_pages"] == 1
    assert result["claims_recovered"] == 4
    assert result["ats_readability"]["status"] == "PASS"
    assert result["ats_readability"]["parseability_score"] == 100

    empty = tmp_path / "empty.pdf"
    make_pdf(empty, [""])
    with pytest.raises(ValueError, match="pages have no text"):
        audit_pdf(empty, payload())


def test_extraction_token_helpers_are_punctuation_insensitive() -> None:
    assert normalized_tokens("Support—Operations + AWS") == ["support", "operations", "+", "aws"]
    assert tokens_recovered("Support Operations", "Operations for Support")


def test_pdf_audit_rejects_scrambled_reading_order(tmp_path: Path) -> None:
    path = tmp_path / "scrambled.pdf"
    make_pdf(
        path,
        ["Professional Summary Improves example workflows. Test Candidate Support Engineer"],
    )

    with pytest.raises(ValueError, match="reading-order"):
        audit_pdf(path, payload())
