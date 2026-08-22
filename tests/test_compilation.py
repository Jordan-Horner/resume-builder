from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from resume_builder import (
    compilation,
    feedback_memory,
    language_review,
    minting,
    pdf_rendering,
    previewing,
    project_report,
    review_policy,
    review_records,
    selection_guard,
    selection_review,
    synthesis,
    verification,
)

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = (ROOT / "templates" / "resume-template.html").read_text(encoding="utf-8")


def resume_markdown() -> str:
    return """---
version: 1
lang: en
page_format: letter
candidate:
  name: Test Candidate
  headline: Example Operations | Example Analysis
  email: candidate@example.com
  location: Example location
  evidence: [PROFILE-001, PROFILE-003]
---
# Professional Summary

Support engineer who improves example workflows.
<!-- evidence: PROFILE-003 -->

# Core Competencies

- Priority Response <!-- evidence: SKILL-001 -->

# Work Experience

## Example Organization | Example Specialist | 2023 - 2025 | Remote <!-- evidence: EX-001 -->

- Reduced processing time through an integrated example workflow. <!-- story: investigation-speed -->
  <!-- evidence: EX-005 -->

# Selected Projects

## Example Project <!-- story: investigation-portal --> <!-- evidence: EX-007 -->

Created a test artifact for repeatable example steps.
<!-- evidence: EX-007 -->

**Technologies:** Tool A, Tool B <!-- evidence: EX-007 -->

# Education

- Example Degree | Example University | 2015 <!-- evidence: EDU-001 -->

# Certifications

- Example Certification | Example Issuer | 2024 <!-- evidence: CERT-001 -->

# Technical Skills

- **Systems:** Tool A, Tool B <!-- evidence: SKILL-002 -->
"""


def fact_ids() -> set[str]:
    return {
        "PROFILE-001",
        "PROFILE-003",
        "SKILL-001",
        "SKILL-002",
        "EX-001",
        "EX-005",
        "EX-007",
        "EDU-001",
        "CERT-001",
    }


def project(tmp_path: Path) -> tuple[Path, Path]:
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
        fact_type = "role" if fact_id == "EX-001" else "accomplishment"
        (facts / f"{fact_id}.md").write_text(
            f"""---
schema_version: 2
id: {fact_id}
title: "Resume evidence"
type: {fact_type}
status: confirmed
category: profile
sources:
  - SRC-0123456789ab
themes:
  - resume
---

# Resume evidence

Test Candidate is an Example Operations and Example Analysis support engineer in
Example location. The candidate improves example workflows and practices Priority Response.
At Example Organization, the candidate worked as an Example Specialist from 2023 - 2025 in a
remote role and reduced processing time through an integrated troubleshooting
workflow. The candidate created an Example Project, an internal interface for
repeatable investigation steps using Tool A and Tool B. The candidate earned an Associate of
Science from Example University in 2015 and an Example Certification
credential from Example Issuer in 2024. Systems include Tool A and Tool B.
""",
            encoding="utf-8",
        )
    templates = tmp_path / "templates"
    templates.mkdir()
    (templates / "resume-template.html").write_text(TEMPLATE, encoding="utf-8")
    resume = tmp_path / "resumes" / "baselines" / "support-operations.md"
    resume.parent.mkdir(parents=True)
    resume.write_text(resume_markdown(), encoding="utf-8")
    directions = tmp_path / "directions"
    directions.mkdir()
    (directions / "support-operations.md").write_text(
        """---
schema_version: 1
slug: support-operations
status: approved
maturity: provisional
target_titles: [Example Operations]
audiences: [Support leadership]
positioning: Improve example operations through investigation tooling.
essential_terms: []
priority_concepts:
  - id: investigation-tooling
    label: Investigation tooling
    weight: 5
    terms: [investigation tooling]
    evidence_themes: [resume]
    basis: user-confirmed
    source_ids: [DIRSRC-001]
de_emphasize: []
avoid_terms: []
defaults:
  max_pages: 2
  page_format: letter
  minimum_coverage: 75
success_criteria: [Lead with workflow improvement.]
sources:
  - id: DIRSRC-001
    kind: user
    reference: Test direction
    as_of: 2026-08-17
---

# Example Operations
""",
        encoding="utf-8",
    )
    plans = tmp_path / "resumes" / "plans"
    plans.mkdir()
    (plans / "support-operations.yaml").write_text(
        """version: 6
resume: resumes/baselines/support-operations.md
direction: directions/support-operations.md
page_budget:
  max_pages: 2
  source: direction-default
target_argument: Improve example operations through investigation tooling.
target_mode: direct
summary_job: Establish workflow-improvement experience.
summary_fact_ids: [PROFILE-003]
concept_fit:
  - concept_id: investigation-tooling
    status: demonstrated
    fact_ids: [EX-005, EX-007]
    rationale: The selected workflow and portal evidence demonstrate investigation tooling.
reviewer_risks: []
presentation:
  competencies: include
  competencies_job: Preserve one concise incident-response scanning label.
  compressed_role_ids: []
role_arcs:
  - role_ids: [EX-001]
    emphasis: lead
    arc_focus: Show a measurable workflow improvement.
    required_dimensions: [operational-outcome]
    required_story_ids: [investigation-speed]
    optional_story_ids: []
    selection_rationale: The one experience story carries the supported operating result.
    omitted_signals: []
progression: [EX-001]
stories:
  - id: investigation-speed
    section: experience
    role_ids: [EX-001]
    fact_ids: [EX-005]
    core_fact_ids: [EX-005]
    claim_focus: Reduce processing time through an integrated workflow.
    claim:
      subject: candidate
      action: reduced
      object: integrated-troubleshooting-workflow
      scope: null
      outcome: investigation-time-reduction
      composition: single-fact
      relationship: EX-005 alone supports the workflow and outcome.
      evidence:
        action: [EX-005]
        object: [EX-005]
        scope: []
        outcome: [EX-005]
    primary_job: operational-outcome
    priority: 5
    importance: core
    rationale: Lead with the strongest workflow outcome.
  - id: investigation-portal
    section: projects
    role_ids: []
    fact_ids: [EX-007]
    core_fact_ids: [EX-007]
    claim_focus: Create an internal example project.
    claim:
      subject: candidate
      action: created
      object: example-project
      scope: repeatable-investigation-steps
      outcome: null
      composition: single-fact
      relationship: EX-007 alone supports the portal and its function.
      evidence:
        action: [EX-007]
        object: [EX-007]
        scope: [EX-007]
        outcome: []
    primary_job: technical-tooling
    priority: 4
    importance: core
    rationale: Demonstrate reusable internal tooling.
exclusions: []
gaps: []
""",
        encoding="utf-8",
    )
    return vault, resume


def upgrade_compilation_project_to_v7(tmp_path: Path) -> None:
    templates = tmp_path / "templates"
    content = templates / "resume-templates" / "technical-complete.yaml"
    content.parent.mkdir(parents=True)
    content.write_text(
        """version: 1
id: technical-complete
section_order: [summary, competencies, experience, projects, education, certifications, skills]
required_sections: [summary, experience, skills]
optional_sections: [competencies, projects, education, certifications]
forbidden_sections: []
""",
        encoding="utf-8",
    )
    theme = templates / "themes" / "test-theme.yaml"
    theme.parent.mkdir(parents=True)
    renderer = templates / "themes" / "test-theme.html"
    renderer.write_text(
        "{{LANG}}{{PAGE_SIZE}}{{PAGE_WIDTH}}{{PAGE_MIN_HEIGHT}}{{TITLE}}"
        "{{HEADER_EVIDENCE}}{{NAME}}{{HEADLINE}}{{CONTACT}}{{PREVIEW_NOTICE}}"
        "{{REVIEW_ISSUES}}"
        "{{RESUME_SECTIONS}}",
        encoding="utf-8",
    )
    theme.write_text(
        """version: 1
id: test-theme
renderer: templates/themes/test-theme.html
""",
        encoding="utf-8",
    )
    plan = tmp_path / "resumes" / "plans" / "support-operations.yaml"
    plan.write_text(
        plan.read_text(encoding="utf-8")
        .replace("version: 6", "version: 7", 1)
        .replace(
            "direction: directions/support-operations.md",
            """direction: directions/support-operations.md
resume_template:
  content: technical-complete
  theme: test-theme""",
            1,
        ),
        encoding="utf-8",
    )


def upgrade_compilation_theme_to_v2(tmp_path: Path) -> Path:
    theme = tmp_path / "templates" / "themes" / "test-theme.yaml"
    renderer = tmp_path / "templates" / "themes" / "test-theme.html"
    stylesheet = tmp_path / "templates" / "themes" / "test-theme.css"
    renderer.write_text(
        (ROOT / "templates" / "renderers" / "ats-single-column.html").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    stylesheet.write_text(":root { --accent: #222222; }\n", encoding="utf-8")
    theme.write_text(
        """version: 2
id: test-theme
display_name: Test Theme
description: Test composable theme
category: test
renderer: templates/themes/test-theme.html
stylesheet: templates/themes/test-theme.css
""",
        encoding="utf-8",
    )
    return stylesheet


def approve_selection_review(tmp_path: Path, resume: Path) -> Path:
    """Approve the complete non-prose strategy before language review."""
    plan = synthesis.load_synthesis_plan(
        tmp_path / "resumes" / "plans" / f"{resume.stem}.yaml", tmp_path, tmp_path / "vault"
    )
    manifest_path = tmp_path / "build" / "resumes" / resume.stem / "resume.manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    selected = selection_guard.build_selection(plan, manifest["synthesis"])
    selection_review.build_selection_review_package(
        tmp_path, resume, plan, selected, manifest=manifest_path
    )
    paths = selection_review.selection_review_paths(tmp_path, resume)
    decisions = json.loads(paths["decisions"].read_text(encoding="utf-8"))
    decisions["reviewer"]["context"] = "Fresh reviewer saw only the selection case."
    decisions["argument"] = {"decision": "approved", "note": "Complete target argument."}
    for item in decisions["stories"]:
        item["decision"] = "approved"
        item["note"] = "Selected or omitted appropriately."
    for item in decisions["exclusions"]:
        item["decision"] = "approved"
        item["note"] = "Intentional exclusion is appropriate."
    for item in decisions["role_arcs"]:
        item["decision"] = "approved"
        item["note"] = "Role retains a distinct hiring contribution."
    decisions["verdict"] = "approved"
    paths["decisions"].write_text(json.dumps(decisions), encoding="utf-8")
    selection_review.finalize_selection_review(paths["decisions"], tmp_path)
    return paths["record"]


def build_language_package(resume: Path, tmp_path: Path) -> Path:
    write_language_review(tmp_path, resume)
    approve_selection_review(tmp_path, resume)
    return review_records.build_review_package(resume, tmp_path)


def complete_selection_decisions(
    tmp_path: Path,
    resume: Path,
    *,
    story_decision: str = "approved",
) -> Path:
    """Fill the generated selection decision contract for focused gate tests."""
    paths = selection_review.selection_review_paths(tmp_path, resume)
    decisions = json.loads(paths["decisions"].read_text(encoding="utf-8"))
    decisions["reviewer"]["context"] = "Reviewer received only the frozen selection case."
    decisions["argument"] = {"decision": "approved", "note": "Argument is coherent."}
    for item in decisions["stories"]:
        item["decision"] = story_decision
        item["note"] = (
            "Rebuild the complete evidence selection."
            if story_decision != "approved"
            else "Appropriate selection decision."
        )
    for item in decisions["exclusions"]:
        item["decision"] = story_decision
        item["note"] = (
            "Rebuild the complete evidence selection."
            if story_decision != "approved"
            else "Appropriate intentional exclusion."
        )
    for item in decisions["role_arcs"]:
        item["decision"] = "approved"
        item["note"] = "Role contribution is intact."
    decisions["verdict"] = "changes-required" if story_decision == "strategy-revise" else "approved"
    paths["decisions"].write_text(json.dumps(decisions), encoding="utf-8")
    return paths["decisions"]


def write_approved_review(tmp_path: Path, resume: Path) -> Path:
    """Create the complete editorial approval required by mint tests."""
    plan = tmp_path / "resumes" / "plans" / "support-operations.yaml"
    direction = tmp_path / "directions" / "support-operations.md"
    review = tmp_path / "build" / "reviews" / "support-operations.json"
    review.parent.mkdir(parents=True, exist_ok=True)
    build_manifest = tmp_path / "build" / "resumes" / "support-operations" / "resume.manifest.json"
    package = build_language_package(resume, tmp_path)
    cold_read = tmp_path / "build" / "reviews" / "support-operations.cold.json"
    evidence = json.loads(build_manifest.read_text(encoding="utf-8"))["evidence"]
    review.write_text(
        json.dumps(
            {
                "version": 4,
                "reviewed_at": "2026-08-17T12:00:00+00:00",
                "reviewer": {
                    "method": "independent-cold-review",
                    "context": "Reviewer used the generated cold-read package before its appendix.",
                },
                "resume": {
                    "path": "resumes/baselines/support-operations.md",
                    "sha256": review_records.sha256_file(resume),
                },
                "plan": {
                    "path": "resumes/plans/support-operations.yaml",
                    "sha256": review_records.sha256_file(plan),
                },
                "direction": {
                    "path": "directions/support-operations.md",
                    "sha256": review_records.sha256_file(direction),
                },
                "target": None,
                "build_manifest": {
                    "path": "build/resumes/support-operations/resume.manifest.json",
                    "sha256": review_records.sha256_file(build_manifest),
                },
                "cold_read": {
                    "path": "build/reviews/support-operations.cold.json",
                    "sha256": review_records.sha256_file(cold_read),
                },
                "review_package": {
                    "path": "build/reviews/support-operations.package.json",
                    "sha256": review_records.sha256_file(package),
                },
                "evidence_integrity": {
                    "status": "claim-checked",
                    "method": "deterministic-structured-claims",
                    "structured_claims": evidence["structured_claims_checked"],
                },
                "verdict": "ready-to-mint",
                "hiring_read": "compelling",
                "findings": {"material": 0, "worthwhile": 0, "optional": 0},
                "next_action": {
                    "route": "mint",
                    "summary": "Mint when the user explicitly approves the draft.",
                },
                "language_review": {
                    "scope": "all-narrative-prose",
                    "status": "approved",
                    "blocks": [
                        {
                            "id": block_id,
                            "sha256": review_records.sha256_text(text),
                            "decision": "approved",
                            "note": "",
                        }
                        for block_id, text in review_records.narrative_blocks(resume).items()
                    ],
                },
            }
        ),
        encoding="utf-8",
    )
    return review


def write_language_review(
    tmp_path: Path,
    resume: Path,
    *,
    revise_block: str | None = None,
) -> Path:
    """Create the standalone independent language record used by preview and mint."""
    manifest = tmp_path / "build" / "resumes" / resume.stem / "resume.manifest.json"
    if verification.build_manifest_freshness(manifest, tmp_path):
        compilation.build_resume(resume, vault_root=tmp_path / "vault")
    prepared = language_review.prepare_language_review(resume, tmp_path)
    if prepared["cached"]:
        return language_review.language_review_paths(tmp_path, resume)["record"]
    decisions_path = language_review.language_review_paths(tmp_path, resume)["decisions"]
    decisions = json.loads(decisions_path.read_text(encoding="utf-8"))
    decisions["reviewer"]["context"] = (
        "Fresh reviewer received only the generated cold-read blocks and their visible context."
    )
    decisions["language_review"]["status"] = (
        "changes-required" if revise_block is not None else "approved"
    )
    for block in decisions["language_review"]["blocks"]:
        if block["id"] == revise_block:
            block["decision"] = "revise"
            block["note"] = "The sentence is unnatural and needs a clearer direct clause."
        else:
            block["decision"] = "approved"
            cold = json.loads(
                language_review.language_review_paths(tmp_path, resume)["cold"].read_text(
                    encoding="utf-8"
                )
            )
            advisory_ids = {item["id"] for item in cold["blocks"] if item.get("advisories")}
            block["note"] = (
                "The flagged wording is clear in its visible context."
                if block["id"] in advisory_ids
                else ""
            )
    decisions_path.write_text(json.dumps(decisions), encoding="utf-8")
    language_review.finalize_language_review(decisions_path, tmp_path)
    return language_review.language_review_paths(tmp_path, resume)["record"]


def test_compile_markdown_preserves_structure_and_evidence() -> None:
    payload = compilation.compile_markdown(resume_markdown())

    assert payload["candidate"]["name"] == "Test Candidate"
    assert payload["summary_evidence"] == ["PROFILE-003"]
    assert payload["competencies"] == [{"text": "Priority Response", "evidence": ["SKILL-001"]}]
    assert payload["experience"][0]["company"] == "Example Organization"
    assert payload["experience"][0]["location"] == "Remote"
    assert payload["experience"][0]["bullets"][0]["evidence"] == ["EX-005"]
    assert payload["experience"][0]["bullets"][0]["story"] == "investigation-speed"
    assert payload["projects"][0]["tech"] == "Tool A, Tool B"
    assert payload["projects"][0]["story"] == "investigation-portal"
    assert payload["education"][0]["org"] == "Example University"
    assert payload["certifications"][0]["year"] == "2024"
    assert payload["skills"][0]["items"] == ["Tool A", "Tool B"]


def test_compile_markdown_rejects_ungrounded_or_unrecognized_content() -> None:
    with pytest.raises(ValueError, match="summary requires an evidence comment"):
        compilation.compile_markdown(
            resume_markdown().replace("<!-- evidence: PROFILE-003 -->", "", 1)
        )

    with pytest.raises(ValueError, match="unsupported level-one section"):
        compilation.compile_markdown(resume_markdown() + "\n# Publications\n\nSomething\n")


def test_compile_command_writes_review_input_without_web_preview(tmp_path: Path, run_main) -> None:
    vault, resume = project(tmp_path)
    stale_pdf = tmp_path / "build" / "resumes" / "support-operations" / "resume.pdf"
    stale_pdf.parent.mkdir(parents=True)
    stale_pdf.write_bytes(b"stale")
    stale_mint = tmp_path / "build" / "resumes" / "support-operations" / "resume.mint.json"
    stale_mint.write_text("{}", encoding="utf-8")
    published_html = tmp_path / "build" / "resumes" / "support-operations" / "resume.html"
    published_html.write_text("last published preview", encoding="utf-8")
    published_preview = (
        tmp_path / "build" / "resumes" / "support-operations" / "resume.preview.json"
    )
    published_preview.write_text("{}", encoding="utf-8")

    assert run_main(compilation.main, resume, "--vault-root", vault) == 0

    payload_path = tmp_path / "build" / "resumes" / "support-operations" / "resume.json"
    html_path = tmp_path / "build" / "resumes" / "support-operations" / "resume.html"
    assert payload_path.is_file()
    assert html_path.read_text(encoding="utf-8") == "last published preview"
    manifest_path = tmp_path / "build" / "resumes" / "support-operations" / "resume.manifest.json"
    assert manifest_path.is_file()
    assert stale_pdf.read_bytes() == b"stale"
    assert stale_mint.is_file()
    assert published_preview.is_file()
    assert json.loads(payload_path.read_text(encoding="utf-8"))["version"] == 1
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["phase"] == "build"
    assert manifest["synthesis"]["stories"] == 2
    assert manifest["synthesis"]["sha256"]
    assert "pdf_audit" not in manifest
    assert manifest["evidence"]["claims_checked"] == 9
    assert manifest["evidence"]["facts"][0]["sha256"]
    assert manifest["outputs"][0]["sha256"]
    assert manifest["editorial_status"] == "unreviewed"
    assert manifest["review_statuses"]["evidence_integrity"] == "claim-checked"
    assert manifest["review_statuses"]["language_review"] == "unreviewed"

    outside = tmp_path / "outside"
    assert (
        run_main(
            compilation.main,
            resume,
            "--vault-root",
            vault,
            "--output-base",
            outside,
        )
        == 2
    )
    assert not outside.with_suffix(".html").exists()


def test_preview_requires_language_review_then_publishes_html_for_editing(
    tmp_path: Path, run_main
) -> None:
    vault, resume = project(tmp_path)

    assert run_main(previewing.main, resume, "--vault-root", vault) == 2
    write_language_review(tmp_path, resume)
    assert run_main(previewing.main, resume, "--vault-root", vault) == 0

    html_path = tmp_path / "build" / "resumes" / "support-operations" / "resume.html"
    rendered = html_path.read_text(encoding="utf-8")
    assert "Test Candidate" in rendered
    assert "Language reviewed" in rendered
    assert "Edit or mint when ready" in rendered
    assert 'data-evidence="EX-005"' in rendered
    assert ' - <span class="certification-org">Example Issuer</span>' in rendered
    assert "<!-- evidence:" not in rendered
    preview_manifest = json.loads(
        (tmp_path / "build" / "resumes" / "support-operations" / "resume.preview.json").read_text(
            encoding="utf-8"
        )
    )
    assert preview_manifest["phase"] == "preview"
    assert preview_manifest["version"] == 4
    assert "review_record" not in preview_manifest
    assert preview_manifest["review_statuses"] == {
        "evidence_integrity": "claim-checked",
        "language_review": "approved",
        "role_fit": "strong-and-well-positioned",
        "career_verdict": "not-required",
        "user_review": "pending",
    }
    assert preview_manifest["language_review"]["issues"] == []
    assert preview_manifest["hybrid_review"]["career_review"]["run"] is False
    assert preview_manifest["final_review_status"] == "awaiting-user-approval"
    assert preview_manifest["output"]["path"] == "build/resumes/support-operations/resume.html"
    assert preview_manifest["user_handoff"] == {
        "required": True,
        "action": "present-preview",
        "presentation_policy": {
            "mode": "exclusive-current-stage",
            "supersedes_prior_handoffs": True,
            "append_to_rendered_markdown": False,
        },
        "artifact": {
            "path": "build/resumes/support-operations/resume.html",
            "media_type": "text/html",
            "label": "Open the current resume preview",
        },
        "approval": {
            "required": True,
            "status": "pending",
            "next_action_on_approval": "mint",
        },
        "presentation": {
            "title": "Resume Preview",
            "summary": (
                "Your resume passed its independent language review. Review it and tell me "
                "what to change. "
                'When it looks right, reply "Mint" to create the PDF.'
            ),
            "review_heading": "Review your resume",
            "guidance_heading": "What to check",
            "guidance": ("Confirm that the content feels accurate and sounds like you."),
            "response_prompt": 'Reply "Mint" to create the PDF, or tell me what to change.',
        },
    }

    result = previewing.preview_resume(resume, vault_root=vault)
    handoff = result["user_handoff"]
    assert handoff["required"] is True
    assert handoff["action"] == "present-preview"
    assert handoff["presentation_policy"] == {
        "mode": "exclusive-current-stage",
        "supersedes_prior_handoffs": True,
        "append_to_rendered_markdown": False,
    }
    assert handoff["artifact"]["absolute_path"] == str(html_path.resolve())
    assert str(html_path.resolve()) in handoff["artifact"]["markdown"]
    assert handoff["rendered_markdown"] == (
        "## Resume Preview\n\n"
        "Your resume passed its independent language review. Review it and tell me what to "
        'change. When it looks right, reply "Mint" to create the PDF.\n\n'
        "### Review your resume\n\n"
        f"[Open the full resume preview](<{html_path.resolve()}>)\n\n"
        "### What to check\n\n"
        "Confirm that the content feels accurate and sounds like you.\n\n"
        'Reply "Mint" to create the PDF, or tell me what to change.'
    )
    assert handoff["approval"] == {
        "required": True,
        "status": "pending",
        "next_action_on_approval": "mint",
    }


def test_preview_does_not_require_a_selection_review(tmp_path: Path, run_main) -> None:
    vault, resume = project(tmp_path)
    write_language_review(tmp_path, resume)
    assert run_main(previewing.main, resume, "--vault-root", vault) == 0
    assert not selection_review.selection_review_paths(tmp_path, resume)["record"].exists()


def test_hybrid_review_route_uses_strong_improvable_and_exploratory_paths(
    tmp_path: Path, run_main, capsys
) -> None:
    vault, _resume = project(tmp_path)
    plan = synthesis.load_synthesis_plan(
        Path("resumes/plans/support-operations.yaml"), tmp_path, vault
    )

    strong = review_policy.hybrid_review_route(plan)
    improvable = review_policy.hybrid_review_route(replace(plan, target_mode="adjacent"))
    exploratory = review_policy.hybrid_review_route(replace(plan, target_mode="exploratory"))

    assert strong["fit"]["band"] == "strong-and-well-positioned"
    assert strong["career_review"]["run"] is False
    assert improvable["fit"]["band"] == "competitive-but-improvable"
    assert improvable["career_review"]["run"] is True
    assert exploratory["fit"]["band"] == "weak-or-exploratory"
    assert exploratory["career_review"]["run"] is False
    assert exploratory["career_review"]["next_action"] == "surface-evidence-gap"
    assert (
        run_main(
            review_records.main,
            "route",
            "resumes/baselines/support-operations.md",
            "--project-root",
            tmp_path,
        )
        == 0
    )
    routed = json.loads(capsys.readouterr().out)
    assert routed["fit"]["band"] == "strong-and-well-positioned"


def test_language_review_reuses_unchanged_approved_blocks(tmp_path: Path) -> None:
    vault, resume = project(tmp_path)
    write_language_review(tmp_path, resume)
    resume.write_text(
        resume.read_text(encoding="utf-8").replace(
            "Created a test artifact for repeatable example steps.",
            "Created a repeatable test artifact for example investigation steps.",
        ),
        encoding="utf-8",
    )
    compilation.build_resume(resume, vault_root=vault)

    prepared = language_review.prepare_language_review(resume, tmp_path)
    assert prepared["pending_blocks"] == 1
    assert prepared["review_inputs"]["prior_approved_blocks"] == 6
    paths = language_review.language_review_paths(tmp_path, resume)
    cold = json.loads(paths["cold"].read_text(encoding="utf-8"))
    assert [block["id"] for block in cold["blocks"]] == ["projects[0].description"]
    assert cold["review_standard"] == language_review.LANGUAGE_REVIEW_STANDARD
    assert cold["review_standard"]["version"] == 2
    assert "actor, action, object" in cold["review_standard"]["context_test"]
    assert "unstated premise" in cold["review_standard"]["unstated_premise_rule"]
    assert "semantically generic object" in cold["review_standard"]["concrete_object_rule"]
    assert (
        "system, deliverable, operation, or change"
        in cold["review_standard"]["concrete_object_rule"]
    )
    assert "exact-word matching" in cold["review_standard"]["boundary"]
    assert "banned-term list" in cold["review_standard"]["boundary"]

    decisions = json.loads(paths["decisions"].read_text(encoding="utf-8"))
    decisions["reviewer"]["context"] = (
        "Fresh reviewer received only the changed block with its visible neighboring context."
    )
    decisions["language_review"]["status"] = "approved"
    decisions["language_review"]["blocks"][0]["decision"] = "approved"
    paths["decisions"].write_text(json.dumps(decisions), encoding="utf-8")
    result = language_review.finalize_language_review(paths["decisions"], tmp_path)

    assert result["reviewed_blocks"] == 1
    assert result["carried_blocks"] == 6
    assert language_review.language_review_freshness(paths["record"], tmp_path, resume) == []


def test_career_review_package_requires_approved_standalone_language(tmp_path: Path) -> None:
    vault, resume = project(tmp_path)
    compilation.build_resume(resume, vault_root=vault)
    approve_selection_review(tmp_path, resume)

    with pytest.raises(ValueError, match="current independent natural-language review"):
        review_records.build_review_package(resume, tmp_path)


def test_improvable_fit_requires_deeper_career_review_before_preview(
    tmp_path: Path, run_main
) -> None:
    vault, resume = project(tmp_path)
    plan_path = tmp_path / "resumes" / "plans" / "support-operations.yaml"
    plan_path.write_text(
        plan_path.read_text(encoding="utf-8").replace(
            "target_mode: direct", "target_mode: adjacent"
        ),
        encoding="utf-8",
    )
    write_language_review(tmp_path, resume)

    assert run_main(previewing.main, resume, "--vault-root", vault) == 2
    write_approved_review(tmp_path, resume)
    carried = json.loads(
        (tmp_path / "build" / "reviews" / "support-operations.decisions.json").read_text(
            encoding="utf-8"
        )
    )
    assert carried["language_review"]["status"] == "approved"
    assert all(block["decision"] == "approved" for block in carried["language_review"]["blocks"])
    assert run_main(previewing.main, resume, "--vault-root", vault) == 0


def test_legacy_career_review_cannot_satisfy_improvable_route(tmp_path: Path, run_main) -> None:
    vault, resume = project(tmp_path)
    plan_path = tmp_path / "resumes" / "plans" / "support-operations.yaml"
    plan_path.write_text(
        plan_path.read_text(encoding="utf-8").replace(
            "target_mode: direct", "target_mode: adjacent"
        ),
        encoding="utf-8",
    )
    write_language_review(tmp_path, resume)
    review_path = write_approved_review(tmp_path, resume)
    review = json.loads(review_path.read_text(encoding="utf-8"))
    review["version"] = 3
    review["editorial_review"] = review.pop("language_review")
    review.pop("build_manifest")
    review.pop("cold_read")
    review.pop("review_package")
    review.pop("evidence_integrity")
    review_path.write_text(json.dumps(review), encoding="utf-8")

    assert run_main(previewing.main, resume, "--vault-root", vault) == 2


def test_preview_rebuilds_for_a_different_template_before_requiring_review(
    tmp_path: Path,
) -> None:
    vault, resume = project(tmp_path)
    write_language_review(tmp_path, resume)
    alternate = tmp_path / "templates" / "alternate.html"
    alternate.write_text(
        (tmp_path / "templates" / "resume-template.html").read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="language review build_manifest changed"):
        previewing.preview_resume(resume, vault_root=vault, template=alternate)

    manifest = json.loads(
        (tmp_path / "build" / "resumes" / resume.stem / "resume.manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert manifest["template"]["path"] == "templates/alternate.html"


def test_preview_rebuilds_for_a_different_plan_before_requiring_review(tmp_path: Path) -> None:
    vault, resume = project(tmp_path)
    write_language_review(tmp_path, resume)
    original = tmp_path / "resumes" / "plans" / "support-operations.yaml"
    alternate = original.parent / "alternate" / original.name
    alternate.parent.mkdir()
    alternate.write_text(original.read_text(encoding="utf-8"), encoding="utf-8")

    with pytest.raises(ValueError, match="language review build_manifest changed"):
        previewing.preview_resume(resume, vault_root=vault, synthesis_plan=alternate)

    manifest = json.loads(
        (tmp_path / "build" / "resumes" / resume.stem / "resume.manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert manifest["synthesis"]["path"] == "resumes/plans/alternate/support-operations.yaml"


def test_preview_handoff_identifies_a_tailored_resume() -> None:
    presentation = previewing._handoff_presentation(
        tailored=True,
        language_status="approved",
        language_issues=0,
    )

    assert presentation["summary"].startswith("Your tailored resume")
    assert "status_heading" not in presentation
    assert "status_items" not in presentation


def test_preview_handoff_identifies_the_company_and_role() -> None:
    presentation = previewing._handoff_presentation(
        tailored=True,
        language_status="approved",
        language_issues=0,
        job_label="Cursor — Support Operations Systems Lead",
    )

    assert presentation["title"] == "Cursor — Support Operations Systems Lead Resume Preview"
    assert "tailored resume for Cursor — Support Operations Systems Lead" in presentation["summary"]


def test_compile_preserves_published_preview_but_marks_it_stale(tmp_path: Path, run_main) -> None:
    vault, resume = project(tmp_path)
    assert run_main(compilation.main, resume, "--vault-root", vault) == 0
    write_approved_review(tmp_path, resume)
    write_language_review(tmp_path, resume)
    assert run_main(previewing.main, resume, "--vault-root", vault) == 0
    html_path = tmp_path / "build" / "resumes" / "support-operations" / "resume.html"
    published_html = html_path.read_text(encoding="utf-8")

    assert run_main(compilation.main, resume, "--vault-root", vault) == 0

    stale_html = html_path.read_text(encoding="utf-8")
    assert stale_html != published_html
    assert "Previous preview · Current draft changed · Refresh preview" in stale_html
    assert "Test Candidate" in stale_html
    status = project_report._preview_status(resume, tmp_path)
    assert status["status"] == "stale"
    assert "preview build_manifest file changed" in status["reasons"]


def test_review_becomes_stale_when_one_reviewed_fact_changes(tmp_path: Path, run_main) -> None:
    vault, resume = project(tmp_path)
    assert run_main(compilation.main, resume, "--vault-root", vault) == 0
    review_path = write_approved_review(tmp_path, resume)
    fact_path = vault / "facts" / "profile" / "EX-005.md"
    fact_path.write_text(fact_path.read_text(encoding="utf-8") + "\n", encoding="utf-8")

    record = review_records.load_review_record(review_path, tmp_path)

    assert "EX-005.md changed after evidence review" in review_records.review_freshness(record)
    language_path = language_review.language_review_paths(tmp_path, resume)["record"]
    assert any(
        "build fact" in reason and "changed" in reason
        for reason in language_review.language_review_freshness(
            language_path,
            tmp_path,
            resume,
        )
    )


def test_preview_rebuild_requires_a_fresh_language_review(tmp_path: Path, run_main) -> None:
    vault, resume = project(tmp_path)
    assert run_main(compilation.main, resume, "--vault-root", vault) == 0
    review_path = write_approved_review(tmp_path, resume)
    write_language_review(tmp_path, resume)
    payload_path = tmp_path / "build" / "resumes" / "support-operations" / "resume.json"
    payload_path.write_text(payload_path.read_text(encoding="utf-8") + "\n", encoding="utf-8")

    record = review_records.load_review_record(review_path, tmp_path)

    assert "resume.json changed after evidence review" in (review_records.review_freshness(record))
    assert run_main(previewing.main, resume, "--vault-root", vault) == 2
    write_language_review(tmp_path, resume)
    assert run_main(previewing.main, resume, "--vault-root", vault) == 0
    manifest = json.loads(
        (tmp_path / "build" / "resumes" / "support-operations" / "resume.manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert manifest["outputs"][0]["sha256"] == compilation.sha256_file(payload_path)


def test_review_package_separates_cold_read_and_rejects_changed_build_output(
    tmp_path: Path, run_main
) -> None:
    vault, resume = project(tmp_path)
    assert run_main(compilation.main, resume, "--vault-root", vault) == 0

    package_path = build_language_package(resume, tmp_path)
    cold_path = tmp_path / "build" / "reviews" / "support-operations.cold.json"
    cold = json.loads(cold_path.read_text(encoding="utf-8"))
    package = json.loads(package_path.read_text(encoding="utf-8"))

    assert "blocks" in cold
    assert "selection_appendix" not in cold
    assert package["cold_read"]["path"] == "build/reviews/support-operations.cold.json"
    assert "blocks" not in package["cold_read"]
    assert "selection_appendix" in package
    decisions_path = tmp_path / "build" / "reviews" / "support-operations.decisions.json"
    decisions = json.loads(decisions_path.read_text(encoding="utf-8"))
    decisions["reviewer"]["context"] = "Review is in progress."
    decisions_path.write_text(json.dumps(decisions), encoding="utf-8")
    package_digest = review_records.sha256_file(package_path)

    assert review_records.build_review_package(resume, tmp_path) == package_path
    assert review_records.sha256_file(package_path) == package_digest
    assert json.loads(decisions_path.read_text(encoding="utf-8"))["reviewer"]["context"] == (
        "Review is in progress."
    )

    payload_path = tmp_path / "build" / "resumes" / "support-operations" / "resume.json"
    payload_path.write_text(payload_path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match=r"build is stale: .*output\[0\].*changed"):
        review_records.build_review_package(resume, tmp_path)


def test_review_wording_repair_applies_exact_block_and_preserves_evidence(
    tmp_path: Path,
    run_main,
    capsys,
) -> None:
    vault, resume = project(tmp_path)
    assert run_main(compilation.main, resume, "--vault-root", vault) == 0
    capsys.readouterr()
    build_language_package(resume, tmp_path)
    decisions_path = tmp_path / "build" / "reviews" / "support-operations.decisions.json"
    decisions = json.loads(decisions_path.read_text(encoding="utf-8"))
    assert decisions["version"] == 2
    for block in decisions["language_review"]["blocks"]:
        block["decision"] = "approved"
    target = next(
        block
        for block in decisions["language_review"]["blocks"]
        if block["id"] == "experience[0].bullets[0]"
    )
    target["decision"] = "revise"
    target["note"] = "Lead with the supported investigation outcome."
    target["repair"] = {
        "kind": "wording-only",
        "replacement": "Reduced processing time with a repeatable troubleshooting workflow.",
    }
    decisions["language_review"]["status"] = "changes-required"
    decisions["verdict"] = "needs-revision"
    decisions["hiring_read"] = "credible-but-not-yet-differentiated"
    decisions["next_action"] = {"route": "rebuild", "summary": "Apply the wording repair."}
    decisions_path.write_text(json.dumps(decisions), encoding="utf-8")

    assert (
        run_main(
            review_records.main,
            "apply-repairs",
            decisions_path,
            "--project-root",
            tmp_path,
        )
        == 0
    )
    result = json.loads(capsys.readouterr().out)
    assert result["repairs_applied"] == ["experience[0].bullets[0]"]
    source = resume.read_text(encoding="utf-8")
    assert "Reduced processing time with a repeatable troubleshooting workflow." in source
    assert "<!-- story: investigation-speed -->" in source
    assert "<!-- evidence: EX-005 -->" in source
    assert review_records.narrative_blocks(resume)["experience[0].bullets[0]"] == (
        "Reduced processing time with a repeatable troubleshooting workflow."
    )

    compilation.build_resume(resume, vault_root=vault)
    build_language_package(resume, tmp_path)
    next_decisions = json.loads(decisions_path.read_text(encoding="utf-8"))
    changed = next(
        block
        for block in next_decisions["language_review"]["blocks"]
        if block["id"] == "experience[0].bullets[0]"
    )
    unchanged = next(
        block
        for block in next_decisions["language_review"]["blocks"]
        if block["id"] == "candidate.headline"
    )
    assert changed["decision"] == "approved"
    assert changed["repair"] is None
    assert unchanged["decision"] == "approved"

    changed["decision"] = "approved"
    unchanged["decision"] = "revise"
    unchanged["note"] = "A second reviewer tried to reopen this unchanged block."
    next_decisions["reviewer"]["context"] = "Repair reviewer received the changed block."
    next_decisions["verdict"] = "needs-revision"
    next_decisions["hiring_read"] = "credible-but-not-yet-differentiated"
    next_decisions["next_action"] = {"route": "rebuild", "summary": "Reopen headline."}
    next_decisions["language_review"]["status"] = "changes-required"
    decisions_path.write_text(json.dumps(next_decisions), encoding="utf-8")
    with pytest.raises(ValueError, match=r"cannot reopen .*approved.*block"):
        review_records.finalize_review_record(decisions_path, tmp_path)


def test_review_wording_repair_rejects_unstructured_or_stale_changes(tmp_path: Path) -> None:
    vault, resume = project(tmp_path)
    compilation.build_resume(resume, vault_root=vault)
    build_language_package(resume, tmp_path)
    decisions_path = tmp_path / "build" / "reviews" / "support-operations.decisions.json"
    decisions = json.loads(decisions_path.read_text(encoding="utf-8"))
    block = decisions["language_review"]["blocks"][0]
    block["decision"] = "revise"
    block["note"] = "Repair the headline."
    block["repair"] = {
        "kind": "wording-only",
        "replacement": "Example Operations\n<!-- evidence: EX-005 -->",
    }
    decisions_path.write_text(json.dumps(decisions), encoding="utf-8")
    with pytest.raises(ValueError, match="one visible prose block"):
        review_records.apply_review_repairs(decisions_path, tmp_path)

    block["repair"]["replacement"] = "Example Operations | Priority Response"
    decisions_path.write_text(json.dumps(decisions), encoding="utf-8")
    resume.write_text(resume.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="resume changed after the cold-read"):
        review_records.apply_review_repairs(decisions_path, tmp_path)


def test_applicable_feedback_memory_requires_post_cold_review_compliance(
    tmp_path: Path,
) -> None:
    vault, resume = project(tmp_path)
    feedback_plan = tmp_path / "build" / "feedback-plan.json"
    feedback_plan.parent.mkdir(parents=True, exist_ok=True)
    bullet = "Reduced processing time through an integrated example workflow."
    feedback_plan.write_text(
        json.dumps(
            {
                "version": 1,
                "resume": "resumes/baselines/support-operations.md",
                "block": {
                    "id": "experience[0].bullets[0]",
                    "sha256": review_records.sha256_text(bullet),
                },
                "feedback": {
                    "subject_key": "investigation-workflow-terminology",
                    "kind": "terminology",
                    "strength": "hard",
                    "promotion": "durable",
                    "scope": {
                        "level": "facts",
                        "fact_ids": ["EX-005"],
                        "resume": None,
                        "story_id": None,
                        "direction": None,
                        "section": "experience",
                    },
                    "summary": "Keep the workflow terminology accurate.",
                    "instruction": "Describe this as an investigation workflow.",
                    "must_preserve": ["Investigation workflow"],
                    "must_avoid": ["Do not call it an incident-response manual"],
                    "preferred_examples": [],
                    "supersedes": [],
                },
            }
        ),
        encoding="utf-8",
    )
    session = feedback_memory.record_feedback(feedback_plan, tmp_path)
    compilation.build_resume(resume, vault_root=vault)
    build_language_package(resume, tmp_path)
    decisions_path = tmp_path / "build" / "reviews" / "support-operations.decisions.json"
    decisions = json.loads(decisions_path.read_text(encoding="utf-8"))
    assert decisions["version"] == 3
    assert len(decisions["feedback_review"]["rules"]) == 1
    assert decisions["feedback_review"]["rules"][0]["id"] == session["session_id"]

    decisions["reviewer"]["context"] = (
        "Fresh reviewer used only the pinned cold-read package before the appendix."
    )
    decisions["verdict"] = "ready-to-mint"
    decisions["hiring_read"] = "compelling"
    decisions["next_action"] = {"route": "mint", "summary": "Mint after user approval."}
    decisions["language_review"]["status"] = "approved"
    for block in decisions["language_review"]["blocks"]:
        block["decision"] = "approved"
    decisions_path.write_text(json.dumps(decisions), encoding="utf-8")
    with pytest.raises(ValueError, match=r"feedback review\.status"):
        review_records.finalize_review_record(decisions_path, tmp_path)

    decisions["feedback_review"]["status"] = "approved"
    decisions["feedback_review"]["rules"][0]["decision"] = "complies"
    decisions_path.write_text(json.dumps(decisions), encoding="utf-8")
    result = review_records.finalize_review_record(decisions_path, tmp_path)
    assert result["version"] == 5
    assert result["feedback_status"] == "approved"
    assert result["feedback_rules"] == 1

    review_path = tmp_path / "build" / "reviews" / "support-operations.json"
    version_five = json.loads(review_path.read_text(encoding="utf-8"))
    version_four = dict(version_five)
    version_four["version"] = 4
    version_four.pop("feedback_review")
    review_path.write_text(json.dumps(version_four), encoding="utf-8")
    with pytest.raises(ValueError, match=r"version 5.*applied feedback guidance"):
        review_records.require_editorial_approval(resume, tmp_path)
    review_path.write_text(json.dumps(version_five), encoding="utf-8")

    write_language_review(tmp_path, resume)
    previewing.preview_resume(resume, vault_root=vault)
    accepted = feedback_memory.accept_feedback(
        tmp_path,
        session_id=str(session["session_id"]),
        preview=Path("build/resumes/support-operations/resume.preview.json"),
    )
    assert accepted["accepted"][0]["route"] == "memory"
    assert (
        verification.build_manifest_freshness(
            tmp_path / "build" / "resumes" / "support-operations" / "resume.manifest.json",
            tmp_path,
        )
        == []
    )
    feedback_memory.retire_feedback_rule(
        str(accepted["accepted"][0]["rule"]),
        "Test that only builds using this rule become stale.",
        tmp_path,
    )
    assert "applicable feedback guidance changed after compilation" in (
        verification.build_manifest_freshness(
            tmp_path / "build" / "resumes" / "support-operations" / "resume.manifest.json",
            tmp_path,
        )
    )
    language_path = language_review.language_review_paths(tmp_path, resume)["record"]
    assert "applicable feedback guidance changed after compilation" in (
        language_review.language_review_freshness(language_path, tmp_path, resume)
    )


def test_new_applicable_open_feedback_invalidates_an_existing_build(tmp_path: Path) -> None:
    vault, resume = project(tmp_path)
    compilation.build_resume(resume, vault_root=vault)
    manifest = tmp_path / "build" / "resumes" / "support-operations" / "resume.manifest.json"
    assert verification.build_manifest_freshness(manifest, tmp_path) == []

    feedback_plan = tmp_path / "build" / "feedback-plan.json"
    bullet = "Reduced processing time through an integrated example workflow."
    feedback_plan.write_text(
        json.dumps(
            {
                "version": 1,
                "resume": "resumes/baselines/support-operations.md",
                "block": {
                    "id": "experience[0].bullets[0]",
                    "sha256": review_records.sha256_text(bullet),
                },
                "feedback": {
                    "subject_key": "workflow-description",
                    "kind": "presentation",
                    "strength": "preference",
                    "promotion": "local",
                    "scope": {
                        "level": "resume",
                        "fact_ids": [],
                        "resume": "resumes/baselines/support-operations.md",
                        "story_id": None,
                        "direction": None,
                        "section": "experience",
                    },
                    "summary": "Describe the workflow more directly.",
                    "instruction": "Keep this workflow description concise.",
                    "must_preserve": ["Investigation workflow"],
                    "must_avoid": ["Do not enumerate every implementation detail"],
                    "preferred_examples": [],
                    "supersedes": [],
                },
            }
        ),
        encoding="utf-8",
    )
    feedback_memory.record_feedback(feedback_plan, tmp_path)

    assert verification.build_manifest_freshness(manifest, tmp_path) == [
        "applicable feedback guidance changed after compilation"
    ]


@pytest.mark.parametrize(
    ("relative", "reason"),
    [
        (
            "templates/resume-templates/technical-complete.yaml",
            "build resume template content file changed",
        ),
        ("templates/themes/test-theme.yaml", "build resume template theme file changed"),
    ],
)
def test_v7_registry_changes_invalidate_builds(
    tmp_path: Path,
    relative: str,
    reason: str,
) -> None:
    vault, resume = project(tmp_path)
    upgrade_compilation_project_to_v7(tmp_path)
    compilation.build_resume(resume, vault_root=vault)
    manifest = tmp_path / "build" / "resumes" / "support-operations" / "resume.manifest.json"
    assert verification.build_manifest_freshness(manifest, tmp_path) == []
    registry = tmp_path / relative
    registry.write_text(registry.read_text(encoding="utf-8") + "\n", encoding="utf-8")

    assert reason in verification.build_manifest_freshness(manifest, tmp_path)


def test_v7_build_pins_registry_inputs_and_compiled_section_order(tmp_path: Path) -> None:
    vault, resume = project(tmp_path)
    upgrade_compilation_project_to_v7(tmp_path)

    compilation.build_resume(resume, vault_root=vault)

    base = tmp_path / "build" / "resumes" / "support-operations" / "resume"
    manifest = json.loads(base.with_suffix(".manifest.json").read_text(encoding="utf-8"))
    payload = json.loads(base.with_suffix(".json").read_text(encoding="utf-8"))
    selected = manifest["synthesis"]["resume_template"]
    assert selected["content"]["path"] == ("templates/resume-templates/technical-complete.yaml")
    assert selected["content"]["sha256"]
    assert selected["theme"]["path"] == "templates/themes/test-theme.yaml"
    assert selected["theme"]["sha256"]
    assert selected["renderer"]["path"] == "templates/themes/test-theme.html"
    assert selected["renderer"]["sha256"]
    assert payload["section_order"] == [
        "summary",
        "competencies",
        "experience",
        "projects",
        "education",
        "certifications",
        "skills",
    ]


def test_v7_build_composes_and_pins_version_2_theme_stylesheet(tmp_path: Path) -> None:
    vault, resume = project(tmp_path)
    upgrade_compilation_project_to_v7(tmp_path)
    stylesheet = upgrade_compilation_theme_to_v2(tmp_path)

    compilation.build_resume(resume, vault_root=vault)

    manifest_path = tmp_path / "build" / "resumes" / "support-operations" / "resume.manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    selected = manifest["synthesis"]["resume_template"]
    assert selected["theme"]["version"] == 2
    assert selected["stylesheet"]["path"] == "templates/themes/test-theme.css"
    assert selected["stylesheet"]["sha256"] == compilation.sha256_file(stylesheet)
    assert manifest["template_composition_sha256"]
    assert verification.build_manifest_freshness(manifest_path, tmp_path) == []

    stylesheet.write_text(":root { --accent: #333333; }\n", encoding="utf-8")

    assert "build resume template stylesheet file changed" in verification.build_manifest_freshness(
        manifest_path, tmp_path
    )


def test_preview_rejects_tampered_theme_composition_digest(tmp_path: Path) -> None:
    vault, resume = project(tmp_path)
    upgrade_compilation_project_to_v7(tmp_path)
    upgrade_compilation_theme_to_v2(tmp_path)
    compilation.build_resume(resume, vault_root=vault)
    base = tmp_path / "build" / "resumes" / "support-operations" / "resume"
    manifest_path = base.with_suffix(".manifest.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["template_composition_sha256"] = "0" * 64
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="theme composition changed"):
        previewing._current_build(resume, tmp_path, vault, base)


def test_verify_caches_checks_and_drives_review_to_published_state(
    tmp_path: Path,
    run_main,
    capsys,
) -> None:
    vault, resume = project(tmp_path)

    assert (
        run_main(
            verification.main,
            resume,
            "--vault-root",
            vault,
            "--skip-vault-validation",
        )
        == 0
    )
    first = json.loads(capsys.readouterr().out)
    assert first["cached"] is False
    assert first["state"]["state"] == "awaiting-selection-review"
    assert first["checks"]["build"]["planned_stories"] == 2
    assert first["checks"]["build"]["used_stories"] == 2
    assert first["checks"]["prose_preflight"]["blocks"] == 7
    selection_case = tmp_path / first["review_inputs"]["selection_case"]["path"]
    package_digest = review_records.sha256_file(selection_case)

    assert (
        run_main(
            verification.main,
            resume,
            "--vault-root",
            vault,
            "--skip-vault-validation",
        )
        == 0
    )
    second = json.loads(capsys.readouterr().out)
    assert second["cached"] is True
    assert review_records.sha256_file(selection_case) == package_digest

    write_language_review(tmp_path, resume)
    approve_selection_review(tmp_path, resume)
    assert (
        run_main(
            verification.main,
            resume,
            "--vault-root",
            vault,
            "--skip-vault-validation",
        )
        == 0
    )
    language = json.loads(capsys.readouterr().out)
    assert language["cached"] is False
    assert language["state"]["state"] == "awaiting-review"

    decisions_path = tmp_path / language["review_inputs"]["decisions"]
    decisions = json.loads(decisions_path.read_text(encoding="utf-8"))
    decisions["reviewer"]["context"] = "Fresh reviewer used only the pinned cold-read package."
    decisions["verdict"] = "ready-to-mint"
    decisions["hiring_read"] = "compelling"
    decisions["next_action"] = {
        "route": "mint",
        "summary": "Mint after the user approves the published preview.",
    }
    decisions["language_review"]["status"] = "approved"
    for block in decisions["language_review"]["blocks"]:
        block["decision"] = "approved"
    decisions_path.write_text(json.dumps(decisions), encoding="utf-8")

    assert (
        run_main(
            review_records.main,
            "finalize",
            decisions_path,
            "--project-root",
            tmp_path,
        )
        == 0
    )
    finalized = json.loads(capsys.readouterr().out)
    assert finalized["valid"] is True
    assert finalized["blocks"] == 7
    assert finalized["selection_seal"] == "resumes/selections/support-operations.json"
    seal = json.loads((tmp_path / finalized["selection_seal"]).read_text(encoding="utf-8"))
    assert seal["selection_sha256"] == selection_guard.selection_digest(seal["selection"])
    assert {story["id"] for story in seal["selection"]["stories"]} == {
        "investigation-speed",
        "investigation-portal",
    }
    assert verification.workflow_state(resume, tmp_path)["state"] == "preview-ready"

    write_language_review(tmp_path, resume)
    assert run_main(previewing.main, resume, "--vault-root", vault) == 0
    preview = json.loads(capsys.readouterr().out)
    assert preview["preview_mode"] == {
        "kind": "continuous-web",
        "pagination": "PDF page count is calculated only during minting",
        "experience_bullets": 1,
    }
    assert verification.workflow_state(resume, tmp_path)["state"] == "published"

    resume.write_text(resume.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    assert verification.workflow_state(resume, tmp_path)["state"] == "draft"


def test_selection_gate_reviews_omitted_candidates_before_creating_language_inputs(
    tmp_path: Path,
) -> None:
    vault, resume = project(tmp_path)
    first = verification.verify_resume(
        resume,
        vault_root=vault,
        skip_vault_validation=True,
    )

    assert set(first["review_inputs"]) == {"selection_case", "selection_decisions"}
    assert not (tmp_path / "build" / "reviews" / "support-operations.cold.json").exists()
    package = json.loads(
        (tmp_path / first["review_inputs"]["selection_case"]["path"]).read_text(encoding="utf-8")
    )
    assert package["version"] == 1
    assert [(story["id"], story["selected"]) for story in package["stories"]] == [
        ("investigation-speed", True),
        ("investigation-portal", True),
    ]
    assert package["review_standard"]["story_composition_test"] == [
        "Identify one dominant hiring claim for every selected story.",
        "Require every additional action or accomplishment to strengthen that claim as method, scope, constraint, reliability, or result.",
        "Do not combine details merely because they share a fact file, role, employer, system, or time period.",
        "Use strategy-revise when the plan should integrate the relationship more clearly, trim a nonessential detail, or return a distinct target-relevant accomplishment to the role arc.",
    ]
    assert package["role_balance"]["advisory_only"] is True
    assert package["review_standard"]["role_balance_test"][0].startswith(
        "Inspect any material backward allocation"
    )
    decisions = json.loads(
        (tmp_path / first["review_inputs"]["selection_decisions"]).read_text(encoding="utf-8")
    )
    assert set(decisions["stories"][0]) == {"id", "selected", "decision", "note"}
    assert "score" not in json.dumps(package).lower()


def test_rejected_selection_cannot_reach_language_review(tmp_path: Path) -> None:
    vault, resume = project(tmp_path)
    verification.verify_resume(resume, vault_root=vault, skip_vault_validation=True)
    decisions = complete_selection_decisions(tmp_path, resume, story_decision="strategy-revise")

    result = selection_review.finalize_selection_review(decisions, tmp_path)

    assert result["status"] == "changes-required"
    with pytest.raises(ValueError, match="selection review is stale or incomplete"):
        review_records.build_review_package(resume, tmp_path)


def test_selection_user_decision_returns_exact_workflow_handoff(tmp_path: Path) -> None:
    vault, resume = project(tmp_path)
    verification.verify_resume(resume, vault_root=vault, skip_vault_validation=True)
    paths = selection_review.selection_review_paths(tmp_path, resume)
    decisions = json.loads(paths["decisions"].read_text(encoding="utf-8"))
    decisions["reviewer"]["context"] = "Reviewer received only the frozen selection case."
    decisions["argument"] = {"decision": "approved", "note": "Argument remains coherent."}
    for item in decisions["stories"]:
        item["decision"] = "approved"
        item["note"] = "Appropriate selection."
    for item in decisions["exclusions"]:
        item["decision"] = "approved"
        item["note"] = "Appropriate exclusion."
    for item in decisions["role_arcs"]:
        item["decision"] = "needs-user-decision"
        item["note"] = "Changing this arc would remove a protected hiring signal."
    decisions["verdict"] = "needs-user-decision"
    paths["decisions"].write_text(json.dumps(decisions), encoding="utf-8")
    selection_review.finalize_selection_review(paths["decisions"], tmp_path)

    result = verification.verify_resume(
        resume,
        vault_root=vault,
        skip_vault_validation=True,
    )

    assert result["state"]["state"] == "awaiting-user-decision"
    assert set(result["review_inputs"]) == {"user_decision"}
    assert (
        result["review_inputs"]["user_decision"]["role_arc_decisions"][0]["decision"]
        == "needs-user-decision"
    )


def test_approved_role_balance_inversion_requires_contextual_note(tmp_path: Path) -> None:
    vault, resume = project(tmp_path)
    verification.verify_resume(resume, vault_root=vault, skip_vault_validation=True)
    paths = selection_review.selection_review_paths(tmp_path, resume)
    package = json.loads(paths["package"].read_text(encoding="utf-8"))
    role_ids = package["role_arcs"][0]["role_ids"]
    package["role_balance"] = {
        "status": "user-decision",
        "advisory_only": True,
        "inversions": [{"older_role_ids": role_ids, "resolution": "user-decision"}],
    }
    paths["package"].write_text(json.dumps(package), encoding="utf-8")
    decisions = json.loads(paths["decisions"].read_text(encoding="utf-8"))
    decisions["selection_package"]["sha256"] = compilation.sha256_file(paths["package"])
    decisions["reviewer"]["context"] = "Reviewer received only the frozen selection case."
    decisions["argument"] = {"decision": "approved", "note": "Argument remains coherent."}
    for item in decisions["stories"]:
        item["decision"] = "approved"
        item["note"] = "Appropriate selection."
    for item in decisions["exclusions"]:
        item["decision"] = "approved"
        item["note"] = "Appropriate exclusion."
    for item in decisions["role_arcs"]:
        item["decision"] = "approved"
        item["note"] = ""
    decisions["verdict"] = "approved"
    paths["decisions"].write_text(json.dumps(decisions), encoding="utf-8")

    with pytest.raises(ValueError, match="approves a role-balance inversion"):
        selection_review.finalize_selection_review(paths["decisions"], tmp_path)


def test_preview_cannot_bypass_unresolved_role_balance(tmp_path: Path) -> None:
    _vault, resume = project(tmp_path)
    synthesis_record = {
        "role_balance": {
            "status": "user-decision",
            "inversions": [{"older_role_ids": ["ROLE-001"]}],
        }
    }

    with pytest.raises(ValueError, match="run resume-builder verify"):
        previewing._require_resolved_role_balance(resume, tmp_path, synthesis_record)


def test_wording_change_does_not_reopen_approved_selection(tmp_path: Path) -> None:
    vault, resume = project(tmp_path)
    compilation.build_resume(resume, vault_root=vault)
    record = approve_selection_review(tmp_path, resume)
    resume.write_text(
        resume.read_text(encoding="utf-8").replace(
            "Support engineer who improves example workflows.",
            "Support engineer improving example workflows.",
        ),
        encoding="utf-8",
    )

    assert selection_review.selection_review_freshness(record, tmp_path) == []


def test_plan_prose_and_role_word_counts_do_not_reopen_selection_review(
    tmp_path: Path,
) -> None:
    vault, resume = project(tmp_path)
    compilation.build_resume(resume, vault_root=vault)
    record = approve_selection_review(tmp_path, resume)
    package_path = selection_review.selection_review_paths(tmp_path, resume)["package"]
    package_sha256 = compilation.sha256_file(package_path)

    resume.write_text(
        resume.read_text(encoding="utf-8").replace(
            "Reduced processing time through an integrated example workflow.",
            "Reduced processing time through a carefully integrated example workflow.",
        ),
        encoding="utf-8",
    )
    plan_path = tmp_path / "resumes" / "plans" / "support-operations.yaml"
    plan_path.write_text(
        plan_path.read_text(encoding="utf-8").replace(
            "Lead with the strongest workflow outcome.",
            "Lead with the clearest supported workflow outcome.",
        ),
        encoding="utf-8",
    )
    compilation.build_resume(resume, vault_root=vault)
    plan = synthesis.load_synthesis_plan(plan_path, tmp_path, vault)
    manifest_path = tmp_path / "build" / "resumes" / resume.stem / "resume.manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    selected = selection_guard.build_selection(plan, manifest["synthesis"])

    selection_review.build_selection_review_package(
        tmp_path,
        resume,
        plan,
        selected,
        manifest=manifest_path,
        role_balance=manifest["synthesis"]["role_balance"],
    )

    assert compilation.sha256_file(package_path) == package_sha256
    assert (
        selection_review.selection_review_freshness(
            record,
            tmp_path,
            strategy_sha256=selection_review.selection_strategy_digest(plan, selected),
        )
        == []
    )


def test_semantically_identical_package_rewrite_does_not_reopen_selection_review(
    tmp_path: Path,
) -> None:
    vault, resume = project(tmp_path)
    compilation.build_resume(resume, vault_root=vault)
    record = approve_selection_review(tmp_path, resume)
    package_path = selection_review.selection_review_paths(tmp_path, resume)["package"]
    package = json.loads(package_path.read_text(encoding="utf-8"))
    package["review_context"]["target_argument"] = "Updated planning rationale only."
    package_path.write_text(json.dumps(package), encoding="utf-8")
    plan_path = tmp_path / "resumes" / "plans" / "support-operations.yaml"
    plan = synthesis.load_synthesis_plan(plan_path, tmp_path, vault)
    manifest_path = tmp_path / "build" / "resumes" / resume.stem / "resume.manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    selected = selection_guard.build_selection(plan, manifest["synthesis"])

    assert (
        selection_review.selection_review_freshness(
            record,
            tmp_path,
            strategy_sha256=selection_review.selection_strategy_digest(plan, selected),
        )
        == []
    )
    assert selection_review.selection_review_freshness(record, tmp_path) == []


def test_wording_only_edit_carries_forward_sealed_career_judgment(
    tmp_path: Path,
) -> None:
    vault, resume = project(tmp_path)
    plan_path = tmp_path / "resumes" / "plans" / "support-operations.yaml"
    plan_path.write_text(
        plan_path.read_text(encoding="utf-8").replace(
            "target_mode: direct", "target_mode: adjacent"
        ),
        encoding="utf-8",
    )
    compilation.build_resume(resume, vault_root=vault)
    write_language_review(tmp_path, resume)
    review_path = write_approved_review(tmp_path, resume)
    plan = synthesis.load_synthesis_plan(plan_path, tmp_path, vault)
    manifest_path = tmp_path / "build" / "resumes" / resume.stem / "resume.manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    selected = selection_guard.build_selection(plan, manifest["synthesis"])
    selection_guard.write_selection_seal(tmp_path, resume, selected, review_path)

    resume.write_text(
        resume.read_text(encoding="utf-8").replace(
            "Support engineer who improves example workflows.",
            "Support engineer focused on improving example workflows.",
        ),
        encoding="utf-8",
    )
    compilation.build_resume(resume, vault_root=vault)
    write_language_review(tmp_path, resume)

    verified = verification.verify_resume(
        resume,
        vault_root=vault,
        skip_vault_validation=True,
    )

    assert verified["state"]["state"] == "preview-ready"
    assert verified["checks"]["selection_review"]["status"] == "approved"
    assert verified["review_inputs"]["carried_career_review"]["carried_forward"] is True

    previewing.preview_resume(resume, vault_root=vault)
    preview_manifest = json.loads(
        (tmp_path / "build" / "resumes" / resume.stem / "resume.preview.json").read_text(
            encoding="utf-8"
        )
    )
    assert preview_manifest["career_review"]["carried_forward"] is True


def test_fact_change_reopens_approved_selection(tmp_path: Path) -> None:
    vault, resume = project(tmp_path)
    compilation.build_resume(resume, vault_root=vault)
    record = approve_selection_review(tmp_path, resume)
    fact = vault / "facts" / "profile" / "EX-007.md"
    fact.write_text(
        fact.read_text(encoding="utf-8").replace("Resume evidence", "Changed evidence"),
        encoding="utf-8",
    )

    assert selection_review.selection_review_freshness(record, tmp_path) == [
        "selection review fact EX-007 changed or is missing"
    ]


def test_selection_decisions_cannot_hide_an_omitted_candidate(tmp_path: Path) -> None:
    vault, resume = project(tmp_path)
    verification.verify_resume(resume, vault_root=vault, skip_vault_validation=True)
    paths = selection_review.selection_review_paths(tmp_path, resume)
    decisions = json.loads(paths["decisions"].read_text(encoding="utf-8"))
    decisions["reviewer"]["context"] = "Reviewer received only the frozen selection case."
    decisions["argument"] = {"decision": "approved", "note": "Complete."}
    decisions["stories"] = decisions["stories"][:-1]
    for item in decisions["stories"]:
        item["decision"] = "approved"
    for item in decisions["exclusions"]:
        item["decision"] = "approved"
    for item in decisions["role_arcs"]:
        item["decision"] = "approved"
    decisions["verdict"] = "approved"
    paths["decisions"].write_text(json.dumps(decisions), encoding="utf-8")

    with pytest.raises(ValueError, match="every selected and omitted candidate"):
        selection_review.finalize_selection_review(paths["decisions"], tmp_path)


def test_verify_blocks_a_new_review_cycle_that_silently_removes_a_reviewed_story(
    tmp_path: Path,
    run_main,
    capsys,
) -> None:
    vault, resume = project(tmp_path)
    assert (
        run_main(
            verification.main,
            resume,
            "--vault-root",
            vault,
            "--skip-vault-validation",
        )
        == 0
    )
    verified = json.loads(capsys.readouterr().out)
    assert verified["state"]["state"] == "awaiting-selection-review"
    write_language_review(tmp_path, resume)
    approve_selection_review(tmp_path, resume)
    assert (
        run_main(
            verification.main,
            resume,
            "--vault-root",
            vault,
            "--skip-vault-validation",
        )
        == 0
    )
    verified = json.loads(capsys.readouterr().out)
    decisions_path = tmp_path / verified["review_inputs"]["decisions"]
    decisions = json.loads(decisions_path.read_text(encoding="utf-8"))
    decisions["reviewer"]["context"] = "Fresh reviewer used only the cold-read package."
    decisions["verdict"] = "ready-to-mint"
    decisions["hiring_read"] = "compelling"
    decisions["next_action"] = {"route": "mint", "summary": "Ready for user approval."}
    decisions["language_review"]["status"] = "approved"
    for block in decisions["language_review"]["blocks"]:
        block["decision"] = "approved"
    decisions_path.write_text(json.dumps(decisions), encoding="utf-8")
    review_records.finalize_review_record(decisions_path, tmp_path)

    source = resume.read_text(encoding="utf-8")
    before_projects, remainder = source.split("# Selected Projects\n", 1)
    _, after_projects = remainder.split("# Education\n", 1)
    resume.write_text(f"{before_projects}# Education\n{after_projects}", encoding="utf-8")
    plan_path = tmp_path / "resumes" / "plans" / "support-operations.yaml"
    plan_text = plan_path.read_text(encoding="utf-8")
    head, marker, tail = plan_text.rpartition("importance: core")
    assert marker
    plan_path.write_text(f"{head}importance: supporting{tail}", encoding="utf-8")

    compilation.build_resume(resume, vault_root=vault)
    assert (
        run_main(
            verification.main,
            resume,
            "--vault-root",
            vault,
            "--skip-vault-validation",
        )
        == 2
    )
    error = json.loads(capsys.readouterr().err)
    assert "strategy approval required" in error["error"]
    proposal_path = tmp_path / "build" / "revisions" / "support-operations.strategy.json"
    proposal = json.loads(proposal_path.read_text(encoding="utf-8"))
    assert proposal["blocking_changes"]["removed_story_ids"] == ["investigation-portal"]

    approved = selection_guard.approve_proposal(
        Path("build/revisions/support-operations.strategy.json"),
        tmp_path,
        "The user approved dropping this project for the narrower strategy.",
    )
    assert approved["status"] == "approved"
    assert (
        run_main(
            verification.main,
            resume,
            "--vault-root",
            vault,
            "--skip-vault-validation",
        )
        == 0
    )
    allowed = json.loads(capsys.readouterr().out)
    assert allowed["checks"]["build"]["selection_guard"]["status"] == ("strategy-change-approved")


def test_optional_review_risk_does_not_block_the_preview_loop(tmp_path: Path, run_main) -> None:
    vault, resume = project(tmp_path)
    assert run_main(compilation.main, resume, "--vault-root", vault) == 0
    review_path = write_approved_review(tmp_path, resume)
    review = json.loads(review_path.read_text(encoding="utf-8"))
    review["verdict"] = "needs-revision"
    review["hiring_read"] = "weak-or-misaligned"
    review["next_action"] = {
        "route": "direction",
        "summary": "Accept or change the documented role-fit tradeoff.",
    }
    review_path.write_text(json.dumps(review), encoding="utf-8")

    write_language_review(tmp_path, resume)
    assert run_main(previewing.main, resume, "--vault-root", vault) == 0
    preview = json.loads(
        (tmp_path / "build" / "resumes" / "support-operations" / "resume.preview.json").read_text(
            encoding="utf-8"
        )
    )
    assert preview["review_statuses"]["career_verdict"] == "needs-revision"
    assert preview["review_statuses"]["role_fit"] == "weak-or-misaligned"
    assert preview["career_review"]["next_action"] == (
        "Accept or change the documented role-fit tradeoff."
    )
    assert (
        "still flags one positioning tradeoff" in preview["user_handoff"]["presentation"]["summary"]
    )
    assert (
        "Accept or change the documented role-fit tradeoff."
        in preview["user_handoff"]["presentation"]["summary"]
    )
    assert "risk_acceptance" not in preview


def test_project_report_tracks_current_and_stale_builds(
    tmp_path: Path, run_main, monkeypatch
) -> None:
    vault, resume = project(tmp_path)
    assert run_main(compilation.main, resume, "--vault-root", vault) == 0
    monkeypatch.setattr(
        project_report,
        "validate_vault",
        lambda _root, strict=False: {
            "valid": True,
            "schema_version": 2,
            "facts": len(fact_ids()),
            "employment_files": 1,
            "registered_sources": 1,
            "warnings": [],
            "errors": [],
        },
    )

    current = project_report.project_report(vault, strict=True)

    assert current["valid"] is True
    assert current["resumes"][0]["build"]["status"] == "current"
    assert current["next_action"]["route"] == "preview"
    assert "1 baselines" in project_report.format_summary(current)

    write_approved_review(tmp_path, resume)
    reviewed = project_report.project_report(vault, strict=True)

    assert reviewed["resumes"][0]["critique"]["status"] == "current"
    assert reviewed["resumes"][0]["critique"]["evidence_status"] == "claim-checked"
    assert reviewed["resumes"][0]["critique"]["language_status"] == "approved"
    assert reviewed["next_action"]["route"] == "preview"

    resume.write_text(resume.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    stale = project_report.project_report(vault, strict=True)

    assert stale["resumes"][0]["build"]["status"] == "stale"
    assert stale["next_action"]["route"] == "preview"


def test_project_report_rejects_same_stem_build_owned_by_another_resume(
    tmp_path: Path, run_main
) -> None:
    vault, baseline = project(tmp_path)
    assert run_main(compilation.main, baseline, "--vault-root", vault) == 0
    tailored = tmp_path / "resumes" / "tailored" / baseline.name
    tailored.parent.mkdir(parents=True, exist_ok=True)
    tailored.write_text(baseline.read_text(encoding="utf-8"), encoding="utf-8")

    baseline_status = project_report._build_status(baseline, tmp_path, vault)
    tailored_status = project_report._build_status(tailored, tmp_path, vault)

    assert baseline_status["status"] == "current"
    assert tailored_status["status"] == "stale"
    assert "build names a different resume source" in tailored_status["reasons"]


def test_project_report_routes_progressive_onboarding_before_first_baseline() -> None:
    empty_vault = {"valid": False, "registered_sources": 0, "facts": 0}
    registered_vault = {"valid": False, "registered_sources": 1, "facts": 0}
    hydrated_vault = {"valid": True, "registered_sources": 1, "facts": 3}
    evaluations = {"unsealed": 0, "uncovered_baselines": []}

    assert (
        project_report._next_action(empty_vault, [], [], [], evaluations, ["empty"])["route"]
        == "needs-sources"
    )
    assert (
        project_report._next_action(registered_vault, [], [], [], evaluations, ["facts"])["route"]
        == "needs-hydration"
    )
    direction_action = project_report._next_action(hydrated_vault, [], [], [], evaluations, [])
    assert direction_action["route"] == "needs-direction"
    onboarding = project_report._onboarding_status(direction_action, hydrated_vault)
    assert onboarding["active"] is True
    assert "Choose a target direction first" in onboarding["message"]
    assert (
        project_report._next_action(
            hydrated_vault,
            [{"slug": "support-operations"}],
            [],
            [],
            evaluations,
            [],
        )["route"]
        == "build-baseline"
    )


def test_initial_draft_readiness_requires_role_and_experience_evidence() -> None:
    assert (
        project_report._initial_draft_readiness(
            {
                "facts": 2,
                "types": {"role": 1, "responsibility": 1},
            }
        )["ready"]
        is True
    )
    missing_role = project_report._initial_draft_readiness(
        {
            "facts": 2,
            "types": {"role": 0, "responsibility": 2},
        }
    )
    assert missing_role["ready"] is False
    assert "no supported role chronology" in missing_role["reasons"]


def test_mint_command_creates_audited_pdf(tmp_path: Path, run_main, monkeypatch) -> None:
    vault, resume = project(tmp_path)
    write_language_review(tmp_path, resume)
    assert run_main(previewing.main, resume, "--vault-root", vault) == 0
    preview_manifest_path = (
        tmp_path / "build" / "resumes" / "support-operations" / "resume.preview.json"
    )
    preview_manifest = json.loads(preview_manifest_path.read_text(encoding="utf-8"))
    preview_manifest["job_context"] = {
        "company": "Example",
        "role": "Example Operations Lead",
        "label": "Example — Example Operations Lead",
        "target_path": "targets/example.md",
        "target_sha256": "a" * 64,
    }
    preview_manifest_path.write_text(json.dumps(preview_manifest), encoding="utf-8")
    called: dict[str, Path] = {}

    def fake_render_pdf(
        html_path: Path, output: Path, payload: dict[str, object], browser: Path | None = None
    ) -> dict[str, object]:
        called["html"] = html_path
        called["pdf"] = output
        called["browser"] = browser or Path()
        assert payload["candidate"] == compilation.compile_markdown(resume_markdown())["candidate"]
        output.write_bytes(b"%PDF-compiled-test")
        return {
            "layout": {"horizontal_overflow": False, "overflowing_elements": []},
            "extraction": {"pages": 1, "extractable_pages": 1, "claims_recovered": 10},
        }

    monkeypatch.setattr(minting, "render_pdf", fake_render_pdf)

    assert run_main(minting.main, resume, "--vault-root", vault) == 0
    assert called["html"] == tmp_path / "build" / "resumes" / "support-operations" / "resume.html"
    assert called["pdf"] == tmp_path / "build" / "resumes" / "support-operations" / "resume.pdf"
    submission = (
        tmp_path / "exports" / "resumes" / "support-operations" / "Test-Candidate-Resume.pdf"
    )
    assert submission.read_bytes() == b"%PDF-compiled-test"
    assert "support-operations" not in submission.name.lower()
    manifest = json.loads(
        (tmp_path / "build" / "resumes" / "support-operations" / "resume.mint.json").read_text(
            encoding="utf-8"
        )
    )
    assert manifest["phase"] == "mint"
    assert manifest["valid"] is True
    assert manifest["version"] == 4
    assert "review_record" not in manifest
    assert manifest["language_review"]["status"] == "approved"
    assert (
        manifest["preview_manifest"]["path"]
        == "build/resumes/support-operations/resume.preview.json"
    )
    assert manifest["user_approval"]["status"] == "approved-for-mint"
    assert manifest["job_context"]["label"] == "Example — Example Operations Lead"
    assert manifest["submission_output"]["path"] == (
        "exports/resumes/support-operations/Test-Candidate-Resume.pdf"
    )
    assert manifest["submission_output"]["label"] == "Example — Example Operations Lead resume"
    assert project_report._mint_status(resume, tmp_path)["status"] == "current"
    html_path = tmp_path / "build" / "resumes" / "support-operations" / "resume.html"
    html_path.write_text(html_path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    assert project_report._mint_status(resume, tmp_path)["status"] == "stale"


def test_mint_rejects_missing_or_stale_preview(tmp_path: Path, run_main) -> None:
    vault, resume = project(tmp_path)

    assert run_main(minting.main, resume, "--vault-root", vault) == 2

    write_language_review(tmp_path, resume)
    assert run_main(previewing.main, resume, "--vault-root", vault) == 0
    resume.write_text(resume.read_text(encoding="utf-8") + "\n", encoding="utf-8")

    assert run_main(minting.main, resume, "--vault-root", vault) == 2


def test_mint_is_blocked_by_changes_required_language_review(tmp_path: Path, run_main) -> None:
    vault, resume = project(tmp_path)
    revise_block = next(iter(review_records.narrative_blocks(resume)))
    write_language_review(tmp_path, resume, revise_block=revise_block)

    assert run_main(previewing.main, resume, "--vault-root", vault) == 0
    preview = json.loads(
        (tmp_path / "build" / "resumes" / "support-operations" / "resume.preview.json").read_text(
            encoding="utf-8"
        )
    )
    assert preview["review_statuses"]["language_review"] == "changes-required"
    assert preview["language_review"]["issues"][0]["id"] == revise_block
    rendered = (tmp_path / "build" / "resumes" / "support-operations" / "resume.html").read_text(
        encoding="utf-8"
    )
    assert f'data-review-block="{revise_block}"' in rendered
    assert 'data-review-status="changes-required"' in rendered
    assert "1 item needs revision" in rendered
    assert "The sentence is unnatural and needs a clearer direct clause." in rendered
    preview_status = project_report._preview_status(resume, tmp_path)
    assert preview_status["status"] == "current"
    assert preview_status["release_readiness"] == "revise-language"
    assert verification.workflow_state(resume, tmp_path)["state"] == "revision-required"
    next_action = project_report._next_action(
        {
            "valid": True,
            "registered_sources": 1,
            "facts": 2,
            "types": {"role": 1, "accomplishment": 1},
        },
        [{"slug": "support-operations"}],
        [
            {
                "kind": "baseline",
                "path": "resumes/baselines/support-operations.md",
                "plan": {"status": "valid"},
                "build": {"status": "current"},
                "preview": preview_status,
            }
        ],
        [],
        {"unsealed": 0, "uncovered_baselines": []},
        [],
    )
    assert next_action["route"] == "revise-language"
    assert run_main(minting.main, resume, "--vault-root", vault) == 2
    assert not (tmp_path / "build" / "resumes" / "support-operations" / "resume.pdf").exists()


def test_pdf_renderer_rejects_missing_explicit_browser(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="browser does not exist"):
        pdf_rendering.render_pdf(
            tmp_path / "resume.html",
            tmp_path / "resume.pdf",
            compilation.compile_markdown(resume_markdown()),
            tmp_path / "missing-browser",
        )


def test_compile_rejects_unsupported_numeric_claim(tmp_path: Path, run_main) -> None:
    vault, resume = project(tmp_path)
    resume.write_text(resume_markdown().replace("Reduced processing", "Reduced 73% processing"))

    assert run_main(compilation.main, resume, "--vault-root", vault) == 2
    assert not (tmp_path / "build" / "resumes" / "support-operations" / "resume.html").exists()


def test_compile_normalizes_ats_characters(tmp_path: Path, run_main) -> None:
    vault, resume = project(tmp_path)
    resume.write_text(resume_markdown().replace("Support engineer", "Support engineer—operator"))

    assert run_main(compilation.main, resume, "--vault-root", vault) == 0
    payload = json.loads(
        (tmp_path / "build" / "resumes" / "support-operations" / "resume.json").read_text()
    )
    manifest = json.loads(
        (tmp_path / "build" / "resumes" / "support-operations" / "resume.manifest.json").read_text()
    )
    assert payload["summary"].startswith("Support engineer-operator")
    assert manifest["ats_replacements"] == {"U+2014": 1}


@pytest.mark.browser
def test_mint_pdf_end_to_end(tmp_path: Path, run_main) -> None:
    vault, resume = project(tmp_path)
    upgrade_compilation_project_to_v7(tmp_path)
    upgrade_compilation_theme_to_v2(tmp_path)
    write_language_review(tmp_path, resume)
    assert run_main(previewing.main, resume, "--vault-root", vault) == 0
    html = (tmp_path / "build" / "resumes" / "support-operations" / "resume.html").read_text(
        encoding="utf-8"
    )
    assert "--accent: #222222" in html
    assert "{{THEME_CSS}}" not in html

    assert (
        run_main(
            minting.main,
            resume,
            "--vault-root",
            vault,
        )
        == 0
    )
    pdf = tmp_path / "exports" / "resumes" / "support-operations" / "Test-Candidate-Resume.pdf"
    manifest = json.loads(
        (tmp_path / "build" / "resumes" / "support-operations" / "resume.mint.json").read_text(
            encoding="utf-8"
        )
    )
    assert pdf.read_bytes().startswith(b"%PDF")
    assert manifest["pdf_audit"]["extraction"]["pages"] <= 2
    assert manifest["pdf_audit"]["extraction"]["claims_recovered"] >= 9


def test_strict_page_budget_retains_audited_draft(tmp_path: Path, run_main, monkeypatch) -> None:
    vault, resume = project(tmp_path)
    write_language_review(tmp_path, resume)
    assert run_main(previewing.main, resume, "--vault-root", vault) == 0

    def oversized_pdf(
        html_path: Path, output: Path, payload: dict[str, object], browser: Path | None = None
    ) -> dict[str, object]:
        output.write_bytes(b"%PDF-oversized-test")
        return {
            "layout": {"horizontal_overflow": False, "overflowing_elements": []},
            "extraction": {"pages": 3, "extractable_pages": 3, "claims_recovered": 9},
        }

    monkeypatch.setattr(minting, "render_pdf", oversized_pdf)

    assert (
        run_main(
            minting.main,
            resume,
            "--vault-root",
            vault,
            "--max-pages",
            "2",
        )
        == 2
    )
    assert (tmp_path / "build" / "resumes" / "support-operations" / "resume.pdf").is_file()
    assert not (tmp_path / "exports").exists()
    manifest = json.loads(
        (tmp_path / "build" / "resumes" / "support-operations" / "resume.mint.json").read_text(
            encoding="utf-8"
        )
    )
    assert manifest["valid"] is False
    assert "draft PDF was retained" in manifest["errors"][0]
