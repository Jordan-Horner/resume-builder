from __future__ import annotations

import json
from pathlib import Path

import pytest
from pypdf import PdfReader

from resume_builder import pdf_rendering, rendering

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = (ROOT / "templates" / "resume-template.html").read_text(encoding="utf-8")


def test_default_template_uses_established_resume_palette() -> None:
    assert "--accent: #087f8c" in TEMPLATE
    assert "--secondary: #245f8f" in TEMPLATE
    assert "hsl(270" not in TEMPLATE


def payload() -> dict[str, object]:
    return {
        "version": 1,
        "lang": "en",
        "page_format": "letter",
        "candidate": {
            "name": "Test & Candidate",
            "headline": "Example Operations | Example Analysis",
            "email": "candidate@example.com",
            "github": {
                "url": "https://github.com/example",
                "display": "github.com/example",
            },
            "location": "Example location",
            "evidence": ["PROFILE-001", "PROFILE-003"],
        },
        "summary": "Support engineer who improves example workflows.",
        "summary_evidence": ["PROFILE-003"],
        "competencies": [
            {"text": "Priority Response", "evidence": ["SKILL-001"]},
        ],
        "experience": [
            {
                "company": "Example Organization",
                "role": "Example Specialist",
                "dates": "2023 - 2025",
                "evidence": ["EX-001"],
                "bullets": [
                    {
                        "text": "Reduced processing time from 1-2 hours to 20 minutes.",
                        "evidence": ["EX-005"],
                    }
                ],
            }
        ],
        "projects": [],
        "education": [],
        "certifications": [],
        "skills": [
            {
                "category": "Systems",
                "items": ["Linux", "AWS"],
                "evidence": ["SKILL-002"],
            }
        ],
    }


def fact_ids() -> set[str]:
    return {
        "PROFILE-001",
        "PROFILE-003",
        "SKILL-001",
        "SKILL-002",
        "EX-001",
        "EX-005",
    }


def test_render_payload_is_escaped_grounded_and_omits_empty_sections() -> None:
    rendered = rendering.render_payload(payload(), TEMPLATE, fact_ids())

    assert "Test &amp; Candidate" in rendered
    assert 'data-evidence="EX-005"' in rendered
    assert "Reduced processing time" in rendered
    assert "Selected Projects" not in rendered
    assert "Certifications" not in rendered
    assert not rendering.PLACEHOLDER.search(rendered)


def test_render_payload_highlights_and_indexes_language_issues_on_screen() -> None:
    rendered = rendering.render_payload(
        payload(),
        TEMPLATE,
        fact_ids(),
        review_issues={
            "experience[0].bullets[0]": "Lead with the supported outcome & simplify the clause."
        },
    )

    assert 'data-review-block="experience[0].bullets[0]"' in rendered
    assert 'data-review-status="changes-required"' in rendered
    assert "Needs review" in rendered
    assert "1 item needs revision" in rendered
    assert "Experience 1, bullet 1" in rendered
    assert "supported outcome &amp; simplify" in rendered
    assert 'href="#review-block-experience-0-bullets-0"' in rendered
    assert (
        ".review-panel,\n    .review-issue-badge,\n    .screen-reader-only {\n      display: none;"
        in rendered
    )


def test_render_payload_rejects_an_issue_for_an_unknown_block() -> None:
    with pytest.raises(ValueError, match="unknown narrative blocks"):
        rendering.render_payload(
            payload(),
            TEMPLATE,
            fact_ids(),
            review_issues={"experience[7].bullets[4]": "This cannot be placed."},
        )


def test_render_payload_rejects_an_old_template_that_cannot_show_issues() -> None:
    with pytest.raises(ValueError, match=r"template cannot display.*REVIEW_ISSUES"):
        rendering.render_payload(
            payload(),
            TEMPLATE.replace("{{REVIEW_ISSUES}}", ""),
            fact_ids(),
            review_issues={"summary": "Clarify the main claim."},
        )


@pytest.mark.browser
def test_review_annotations_are_screen_only_and_do_not_break_pdf_layout(tmp_path: Path) -> None:
    value = payload()
    rendered = rendering.render_payload(
        value,
        TEMPLATE,
        fact_ids(),
        review_issues={"summary": "Clarify this positioning statement before minting."},
    )
    html_path = tmp_path / "resume.html"
    pdf_path = tmp_path / "resume.pdf"
    html_path.write_text(rendered, encoding="utf-8")

    audit = pdf_rendering.render_pdf(html_path, pdf_path, value)

    extracted = "\n".join(page.extract_text() or "" for page in PdfReader(pdf_path).pages)
    assert audit["layout"] == {"horizontal_overflow": False, "overflowing_elements": []}
    assert "Clarify this positioning statement" not in extracted
    assert "Needs review" not in extracted


def test_render_payload_rejects_unknown_evidence() -> None:
    value = payload()
    value["summary_evidence"] = ["UNKNOWN-999"]

    with pytest.raises(ValueError, match="unknown fact IDs"):
        rendering.render_payload(value, TEMPLATE, fact_ids())


def test_render_payload_rejects_unsafe_contact_link() -> None:
    value = payload()
    candidate = value["candidate"]
    assert isinstance(candidate, dict)
    candidate["github"] = {"url": "javascript:alert(1)", "display": "unsafe"}

    with pytest.raises(ValueError, match="http or https"):
        rendering.render_payload(value, TEMPLATE, fact_ids())


def test_render_command_writes_only_under_build(tmp_path: Path, run_main) -> None:
    vault = tmp_path / "vault"
    facts = vault / "facts" / "profile"
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
    for fact_id in fact_ids():
        (facts / f"{fact_id}.md").write_text("fact\n", encoding="utf-8")
    templates = tmp_path / "templates"
    templates.mkdir()
    template = templates / "resume-template.html"
    template.write_text(TEMPLATE, encoding="utf-8")
    build = tmp_path / "build"
    build.mkdir()
    payload_path = build / "resume.json"
    payload_path.write_text(json.dumps(payload()), encoding="utf-8")
    output = build / "resume.html"

    assert (
        run_main(
            rendering.main,
            payload_path,
            "--output",
            output,
            "--vault-root",
            vault,
            "--template",
            template,
        )
        == 0
    )
    assert output.is_file()

    relative_output = Path("build/resume-relative.html")
    relative_template = Path("templates/resume-template.html")
    assert (
        run_main(
            rendering.main,
            payload_path,
            "--output",
            relative_output,
            "--vault-root",
            vault,
            "--template",
            relative_template,
        )
        == 0
    )
    assert (build / "resume-relative.html").is_file()

    outside = tmp_path / "outside.html"
    assert (
        run_main(
            rendering.main,
            payload_path,
            "--output",
            outside,
            "--vault-root",
            vault,
            "--template",
            template,
        )
        == 2
    )
    assert not outside.exists()
