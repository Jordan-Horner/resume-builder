from __future__ import annotations

import json
from pathlib import Path

from resume_builder.web_career import (
    archive_directional_resume,
    directional_resume_removal_impact,
    list_resumes,
    resolve_application_resume_preview,
    resolve_directional_resume_reference,
    resolve_resume_preview,
    restore_directional_resume,
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
        "retired",
    ]
    assert all(section["items"] == [] for section in library["sections"])


def test_directional_resume_removal_archives_only_the_resume(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    resume = root / "resumes" / "baselines" / "support.md"
    resume.parent.mkdir(parents=True, exist_ok=True)
    resume.write_text("# Support\n", encoding="utf-8")
    fact = root / "vault" / "facts" / "skills" / "SKILL-001.md"
    fact.parent.mkdir(parents=True, exist_ok=True)
    fact.write_text("vault evidence\n", encoding="utf-8")

    impact = directional_resume_removal_impact(root, "resumes/baselines/support.md")
    result = archive_directional_resume(root, impact)

    assert result["archived"] is True
    assert not resume.exists()
    assert (root / "resumes" / "archived" / "support.md").read_text() == "# Support\n"
    assert fact.read_text() == "vault evidence\n"


def test_used_directional_resume_is_retired_after_application_copy_is_preserved(
    tmp_path: Path,
) -> None:
    from resume_builder.applications import record_application

    root = _workspace(tmp_path)
    resume = root / "resumes" / "baselines" / "support.md"
    resume.parent.mkdir(parents=True, exist_ok=True)
    resume.write_text("# Support\n", encoding="utf-8")
    record_application(
        root / "applications",
        root,
        company="Example",
        role="Support Engineer",
        resume=resume,
    )
    application = next(iter((root / "applications").glob("APP-*.json")))
    legacy = json.loads(application.read_text(encoding="utf-8"))
    old_snapshot = root / legacy["application"]["resume"].pop("snapshot_path")
    old_snapshot.unlink()
    application.write_text(json.dumps(legacy), encoding="utf-8")

    impact = directional_resume_removal_impact(root, "resumes/baselines/support.md")
    result = archive_directional_resume(root, impact)

    assert impact["action"] == "retire"
    assert result["retired"] is True
    assert not resume.exists()
    assert (root / "resumes" / "archived" / "support.md").is_file()
    saved = json.loads(application.read_text(encoding="utf-8"))
    snapshot = root / saved["application"]["resume"]["snapshot_path"]
    assert snapshot.read_text(encoding="utf-8") == "# Support\n"


def test_retired_directional_resume_can_be_restored(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    retired = root / "resumes" / "archived" / "support.md"
    retired.parent.mkdir(parents=True, exist_ok=True)
    retired.write_text("# Support\n", encoding="utf-8")

    result = restore_directional_resume(root, "resumes/archived/support.md")

    assert result["restored"] is True
    assert (root / "resumes" / "baselines" / "support.md").read_text() == "# Support\n"
    assert not retired.exists()


def test_application_preview_uses_preserved_copy_after_source_changes(
    tmp_path: Path, monkeypatch
) -> None:
    from resume_builder.applications import record_application

    root = _workspace(tmp_path)
    resume = root / "resumes" / "baselines" / "support.md"
    resume.parent.mkdir(parents=True, exist_ok=True)
    resume.write_text("# Submitted version\n", encoding="utf-8")
    record = record_application(
        root / "applications",
        root,
        company="Example",
        role="Support Engineer",
        resume=resume,
    )
    resume.write_text("# New version\n", encoding="utf-8")
    rendered_from: list[Path] = []

    def render(_root: Path, source: Path) -> Path:
        rendered_from.append(source)
        return source

    monkeypatch.setattr("resume_builder.web_career._render_portal_preview", render)

    resolve_application_resume_preview(root, record["application"]["id"])

    assert rendered_from[0].read_text(encoding="utf-8") == "# Submitted version\n"


def test_directional_resume_can_be_resolved_by_visible_name(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    resume = root / "resumes" / "baselines" / "support.md"
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
  evidence: []
---

# Professional Summary

Evidence-backed resume.
""",
        encoding="utf-8",
    )

    assert resolve_directional_resume_reference(root, "Support") == "resumes/baselines/support.md"
    assert (
        resolve_directional_resume_reference(root, "resumes/baselines/support.md")
        == "resumes/baselines/support.md"
    )


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
        "retired",
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


def test_resume_library_preserves_skill_fact_evidence(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    _skill(root, "SKILL-001", "Incident response")
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

    resumes = [
        item
        for section in list_resumes(root)["sections"]
        for item in section["items"]
        if item["kind"] != "original"
    ]

    assert [item["kind"] for item in resumes] == ["directional"]
    assert all(item["skill_fact_ids"] == ["SKILL-001"] for item in resumes)


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


def test_directional_resume_uses_a_compact_headline_when_plan_has_no_direction(
    tmp_path: Path, monkeypatch
) -> None:
    root = _workspace(tmp_path)
    resume = root / "resumes" / "baselines" / "forward-deployed-engineer.md"
    resume.parent.mkdir(parents=True, exist_ok=True)
    resume.write_text("# Resume\n", encoding="utf-8")
    monkeypatch.setattr(
        "resume_builder.web_career.project_report",
        lambda *_args, **_kwargs: {
            "resumes": [
                {
                    "path": "resumes/baselines/forward-deployed-engineer.md",
                    "kind": "baseline",
                    "direction": None,
                }
            ]
        },
    )
    monkeypatch.setattr(
        "resume_builder.web_career.compile_markdown",
        lambda _text: {
            "candidate": {
                "headline": (
                    "Forward Deployed Engineer | Customer Technical Delivery | Cloud & Automation"
                )
            }
        },
    )

    directional = next(
        section for section in list_resumes(root)["sections"] if section["id"] == "directional"
    )

    assert directional["items"][0]["name"] == "Forward Deployed Engineer"
    assert directional["items"][0]["detail"] == ("Customer Technical Delivery · Cloud & Automation")


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


def test_resume_library_only_shows_minted_tailored_resumes(tmp_path: Path, monkeypatch) -> None:
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
