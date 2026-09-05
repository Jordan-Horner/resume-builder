from __future__ import annotations

import json
from pathlib import Path

import yaml

from resume_builder.job_setup_defaults import scaffold_job_search
from resume_builder.web_career import (
    list_resumes,
    list_skills,
    resolve_resume_preview,
    set_skill_search_enabled,
)
from resume_builder.workspace import initialize_workspace


def _workspace(tmp_path: Path) -> Path:
    root = tmp_path / "workspace"
    initialize_workspace(root, git_name="Example User", git_email="example@example.invalid")
    return root


def _skill(root: Path, fact_id: str, title: str, *, status: str = "confirmed") -> None:
    path = root / "vault" / "facts" / "skills" / f"{fact_id}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"""---
schema_version: 2
id: {fact_id}
title: {title}
type: responsibility
status: {status}
category: skills
sources:
  - SRC-example
themes:
  - operations
---

# {title}

Used {title} while supporting production systems.
""",
        encoding="utf-8",
    )


def test_resume_library_keeps_imported_sources_out_of_generated_resumes(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    from resume_builder.layout import VaultLayout
    from resume_builder.source_import import apply_import_plan, build_import_plan

    upload = tmp_path / "Jordan Resume.md"
    upload.write_text("# Jordan Example\n\nProduction support engineer.\n", encoding="utf-8")
    layout = VaultLayout.load(root / "vault")
    plan = build_import_plan(layout, [str(upload)], [], document_kind="resume")
    apply_import_plan(layout, plan)

    library = list_resumes(root)

    assert [section["id"] for section in library["sections"]] == [
        "directional",
        "tailored",
    ]
    assert all(section["items"] == [] for section in library["sections"])


def test_resume_library_does_not_present_source_documents_as_resumes(
    tmp_path: Path,
) -> None:
    root = _workspace(tmp_path)
    from resume_builder.layout import VaultLayout
    from resume_builder.source_import import apply_import_plan, build_import_plan

    uploads = tmp_path / "uploads"
    uploads.mkdir()
    (uploads / "Jordan Resume.md").write_text("Resume source\n", encoding="utf-8")
    (uploads / "Jordan Resume.html").write_text("<p>Resume source</p>\n", encoding="utf-8")
    note = tmp_path / "incident-note.md"
    note.write_text("Career evidence that is not a resume.\n", encoding="utf-8")
    layout = VaultLayout.load(root / "vault")
    apply_import_plan(
        layout,
        build_import_plan(layout, [str(uploads)], [], document_kind="resume"),
    )
    apply_import_plan(layout, build_import_plan(layout, [str(note)], []))

    library = list_resumes(root)

    assert [section["id"] for section in library["sections"]] == [
        "directional",
        "tailored",
    ]
    assert all(section["items"] == [] for section in library["sections"])


def test_resume_library_ignores_macos_metadata_generated_resumes(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    baseline = root / "resumes" / "baselines"
    baseline.mkdir(parents=True, exist_ok=True)
    (baseline / "._support.md").write_bytes(b"\x00\xa3metadata")

    directional = next(
        section for section in list_resumes(root)["sections"] if section["id"] == "directional"
    )

    assert directional["items"] == []


def test_skills_are_derived_from_vault_facts_and_resume_evidence(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    _skill(root, "SKILL-001", "Incident response")
    _skill(root, "SKILL-002", "API troubleshooting")
    resume = root / "resumes" / "baselines" / "support-operations.md"
    resume.parent.mkdir(parents=True, exist_ok=True)
    resume.write_text(
        """---
version: 1
lang: en
page_format: letter
candidate:
  name: Example User
  headline: Support Operations
  email: example@example.invalid
  evidence: [SKILL-001]
---

# Professional Summary

Production support specialist. <!-- evidence: SKILL-001 -->

# Technical Skills

- **Operations:** Incident response <!-- evidence: SKILL-001 -->
""",
        encoding="utf-8",
    )
    tailored = root / "resumes" / "tailored" / "acme-support.md"
    tailored.parent.mkdir(parents=True, exist_ok=True)
    tailored.write_text(resume.read_text(encoding="utf-8"), encoding="utf-8")

    skills = list_skills(root)
    resumes = [
        item
        for section in list_resumes(root)["sections"]
        for item in section["items"]
        if item["kind"] != "original"
    ]

    assert [item["id"] for item in skills] == ["SKILL-001", "SKILL-002"]
    assert skills[0]["resumes"] == ["Support Operations"]
    assert skills[1]["resumes"] == []
    assert [item["kind"] for item in resumes] == ["directional"]
    assert all(item["skill_fact_ids"] == ["SKILL-001"] for item in resumes)


def test_enabling_vault_skill_adds_capability_query_without_changing_titles(
    tmp_path: Path,
) -> None:
    root = _workspace(tmp_path)
    scaffold_job_search(root)
    _skill(root, "SKILL-001", "Incident response")
    preferences_path = root / "job-search" / "preferences.yml"
    preferences = yaml.safe_load(preferences_path.read_text(encoding="utf-8"))
    preferences["desired_title_terms"] = ["Production Support Engineer"]
    preferences_path.write_text(yaml.safe_dump(preferences, sort_keys=False), encoding="utf-8")

    result = set_skill_search_enabled(root, "SKILL-001", True)

    saved = yaml.safe_load(preferences_path.read_text(encoding="utf-8"))
    portfolio = json.loads(
        (root / "build" / "job-search" / "cold-start-portfolio.json").read_text()
    )
    assert result["search"]["enabled"] is True
    assert saved["desired_title_terms"] == ["Production Support Engineer"]
    assert saved["interest_terms"] == []
    assert not (root / "job-search" / "skill-search.json").exists()
    assert (root / "build" / "job-search" / "portfolio-before-last-portal-change.json").is_file()
    assert (root / "build" / "job-search" / "search-before-last-portal-change.yml").is_file()
    capability = next(
        item for item in portfolio["queries"] if item["lane"] == "capability_combination"
    )
    assert capability["query"] == "Incident response"
    assert capability["source_ids"] == ["vault:SKILL-001"]


def test_needs_review_skill_cannot_be_used_for_search(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    _skill(root, "SKILL-001", "Unverified platform", status="needs-review")

    try:
        set_skill_search_enabled(root, "SKILL-001", True)
    except ValueError as exc:
        assert "confirmed" in str(exc)
    else:
        raise AssertionError("needs-review skill was enabled")


def test_multiple_baselines_do_not_get_an_arbitrary_primary_label(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    baseline = root / "resumes" / "baselines"
    baseline.mkdir(parents=True, exist_ok=True)
    source = """---
version: 1
lang: en
page_format: letter
candidate:
  name: Example User
  headline: {headline}
  email: example@example.invalid
  evidence: []
---

# Professional Summary

Evidence-backed resume.
"""
    (baseline / "operations.md").write_text(source.format(headline="Operations"), encoding="utf-8")
    (baseline / "support.md").write_text(source.format(headline="Support"), encoding="utf-8")

    directional = next(
        section for section in list_resumes(root)["sections"] if section["id"] == "directional"
    )
    assert all("primary" not in item for item in directional["items"])


def test_portal_reader_renders_current_markdown_instead_of_old_preview(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "workspace"
    resume = root / "resumes" / "tailored" / "example.md"
    resume.parent.mkdir(parents=True)
    resume.write_text("# Example", encoding="utf-8")
    old_preview = root / "build" / "resumes" / "example" / "resume.html"
    old_preview.parent.mkdir(parents=True)
    old_preview.write_text("Previous preview · Refresh preview", encoding="utf-8")
    current_draft = old_preview.with_name("resume.portal.html")
    current_draft.write_text("Current draft preview", encoding="utf-8")
    monkeypatch.setattr(
        "resume_builder.web_career._render_portal_preview", lambda *_args: current_draft
    )

    resolved = resolve_resume_preview(root, "resumes/tailored/example.md")

    assert resolved["path"] == current_draft


def test_resume_library_only_shows_minted_tailored_resumes(
    tmp_path: Path, monkeypatch
) -> None:
    root = _workspace(tmp_path)
    source = """---
version: 1
lang: en
page_format: letter
candidate:
  name: Example User
  headline: {headline}
  email: example@example.invalid
  evidence: []
---

# Professional Summary

Evidence-backed resume.
"""
    tailored = root / "resumes" / "tailored"
    tailored.mkdir(parents=True, exist_ok=True)
    (tailored / "minted.md").write_text(source.format(headline="Minted"), encoding="utf-8")
    (tailored / "draft.md").write_text(source.format(headline="Draft"), encoding="utf-8")
    monkeypatch.setattr(
        "resume_builder.web_career.project_report",
        lambda *_args, **_kwargs: {
            "resumes": [
                {
                    "path": "resumes/tailored/minted.md",
                    "kind": "tailored",
                    "mint": {"status": "current"},
                    "direction": None,
                },
                {
                    "path": "resumes/tailored/draft.md",
                    "kind": "tailored",
                    "mint": {"status": "missing"},
                    "direction": None,
                },
            ]
        },
    )

    tailored_section = next(
        section for section in list_resumes(root)["sections"] if section["id"] == "tailored"
    )

    assert [item["name"] for item in tailored_section["items"]] == ["Minted"]
    assert tailored_section["items"][0]["detail"] == "Minted application resume"
