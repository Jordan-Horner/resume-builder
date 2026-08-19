from __future__ import annotations

import json
from pathlib import Path

import pytest

from resume_builder import (
    compilation,
    feedback_memory,
    minting,
    pdf_rendering,
    previewing,
    project_report,
    review_records,
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


def write_approved_review(tmp_path: Path, resume: Path) -> Path:
    """Create the complete editorial approval required by mint tests."""
    plan = tmp_path / "resumes" / "plans" / "support-operations.yaml"
    direction = tmp_path / "directions" / "support-operations.md"
    review = tmp_path / "build" / "reviews" / "support-operations.json"
    review.parent.mkdir(parents=True, exist_ok=True)
    build_manifest = tmp_path / "build" / "support-operations.manifest.json"
    package = review_records.build_review_package(resume, tmp_path)
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
                    "path": "build/support-operations.manifest.json",
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
    stale_pdf = tmp_path / "build" / "support-operations.pdf"
    stale_pdf.parent.mkdir()
    stale_pdf.write_bytes(b"stale")
    stale_mint = tmp_path / "build" / "support-operations.mint.json"
    stale_mint.write_text("{}", encoding="utf-8")
    published_html = tmp_path / "build" / "support-operations.html"
    published_html.write_text("last published preview", encoding="utf-8")
    published_preview = tmp_path / "build" / "support-operations.preview.json"
    published_preview.write_text("{}", encoding="utf-8")

    assert run_main(compilation.main, resume, "--vault-root", vault) == 0

    payload_path = tmp_path / "build" / "support-operations.json"
    html_path = tmp_path / "build" / "support-operations.html"
    assert payload_path.is_file()
    assert html_path.read_text(encoding="utf-8") == "last published preview"
    manifest_path = tmp_path / "build" / "support-operations.manifest.json"
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


def test_preview_requires_review_then_publishes_html_for_final_approval(
    tmp_path: Path, run_main
) -> None:
    vault, resume = project(tmp_path)

    assert run_main(previewing.main, resume, "--vault-root", vault) == 2
    assert not (tmp_path / "build" / "support-operations.html").exists()

    assert run_main(compilation.main, resume, "--vault-root", vault) == 0
    write_approved_review(tmp_path, resume)
    assert run_main(previewing.main, resume, "--vault-root", vault) == 0

    html_path = tmp_path / "build" / "support-operations.html"
    rendered = html_path.read_text(encoding="utf-8")
    assert "Test Candidate" in rendered
    assert "Language reviewed" in rendered
    assert "Awaiting your final approval" in rendered
    assert 'data-evidence="EX-005"' in rendered
    assert ' - <span class="certification-org">Example Issuer</span>' in rendered
    assert "<!-- evidence:" not in rendered
    preview_manifest = json.loads(
        (tmp_path / "build" / "support-operations.preview.json").read_text(encoding="utf-8")
    )
    assert preview_manifest["phase"] == "preview"
    assert preview_manifest["review_record"]["status"] == "approved"
    assert preview_manifest["review_statuses"] == {
        "evidence_integrity": "claim-checked",
        "language_review": "approved",
        "role_fit": "compelling",
        "career_verdict": "ready-to-mint",
        "user_review": "pending",
    }
    assert preview_manifest["final_review_status"] == "awaiting-user-approval"
    assert preview_manifest["output"]["path"] == "build/support-operations.html"


def test_compile_preserves_published_preview_but_marks_it_stale(tmp_path: Path, run_main) -> None:
    vault, resume = project(tmp_path)
    assert run_main(compilation.main, resume, "--vault-root", vault) == 0
    write_approved_review(tmp_path, resume)
    assert run_main(previewing.main, resume, "--vault-root", vault) == 0
    html_path = tmp_path / "build" / "support-operations.html"
    published_html = html_path.read_text(encoding="utf-8")

    assert run_main(compilation.main, resume, "--vault-root", vault) == 0

    stale_html = html_path.read_text(encoding="utf-8")
    assert stale_html != published_html
    assert "Previous preview · Current build changed · Review required" in stale_html
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


def test_review_and_preview_reject_a_changed_compiled_payload(tmp_path: Path, run_main) -> None:
    vault, resume = project(tmp_path)
    assert run_main(compilation.main, resume, "--vault-root", vault) == 0
    review_path = write_approved_review(tmp_path, resume)
    payload_path = tmp_path / "build" / "support-operations.json"
    payload_path.write_text(payload_path.read_text(encoding="utf-8") + "\n", encoding="utf-8")

    record = review_records.load_review_record(review_path, tmp_path)

    assert "support-operations.json changed after evidence review" in (
        review_records.review_freshness(record)
    )
    assert run_main(previewing.main, resume, "--vault-root", vault) == 2


def test_review_package_separates_cold_read_and_rejects_changed_build_output(
    tmp_path: Path, run_main
) -> None:
    vault, resume = project(tmp_path)
    assert run_main(compilation.main, resume, "--vault-root", vault) == 0

    package_path = review_records.build_review_package(resume, tmp_path)
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

    payload_path = tmp_path / "build" / "support-operations.json"
    payload_path.write_text(payload_path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="output changed after compilation"):
        review_records.build_review_package(resume, tmp_path)


def test_review_wording_repair_applies_exact_block_and_preserves_evidence(
    tmp_path: Path,
    run_main,
    capsys,
) -> None:
    vault, resume = project(tmp_path)
    assert run_main(compilation.main, resume, "--vault-root", vault) == 0
    capsys.readouterr()
    review_records.build_review_package(resume, tmp_path)
    decisions_path = tmp_path / "build" / "reviews" / "support-operations.decisions.json"
    decisions = json.loads(decisions_path.read_text(encoding="utf-8"))
    assert decisions["version"] == 2
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


def test_review_wording_repair_rejects_unstructured_or_stale_changes(tmp_path: Path) -> None:
    vault, resume = project(tmp_path)
    compilation.build_resume(resume, vault_root=vault)
    review_records.build_review_package(resume, tmp_path)
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
    review_records.build_review_package(resume, tmp_path)
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
    previewing.preview_resume(resume, vault_root=vault)
    accepted = feedback_memory.accept_feedback(
        tmp_path,
        session_id=str(session["session_id"]),
        preview=Path("build/support-operations.preview.json"),
    )
    assert accepted["accepted"][0]["route"] == "memory"
    assert (
        verification.build_manifest_freshness(
            tmp_path / "build" / "support-operations.manifest.json",
            tmp_path,
        )
        == []
    )
    review_records.require_editorial_approval(resume, tmp_path)
    feedback_memory.retire_feedback_rule(
        str(accepted["accepted"][0]["rule"]),
        "Test that only builds using this rule become stale.",
        tmp_path,
    )
    assert "applicable feedback guidance changed after compilation" in (
        verification.build_manifest_freshness(
            tmp_path / "build" / "support-operations.manifest.json",
            tmp_path,
        )
    )


def test_new_applicable_open_feedback_invalidates_an_existing_build(tmp_path: Path) -> None:
    vault, resume = project(tmp_path)
    compilation.build_resume(resume, vault_root=vault)
    manifest = tmp_path / "build" / "support-operations.manifest.json"
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
    assert first["state"]["state"] == "awaiting-review"
    assert first["checks"]["build"]["planned_stories"] == 2
    assert first["checks"]["build"]["used_stories"] == 2
    assert first["checks"]["prose_preflight"]["blocks"] == 7
    package = tmp_path / first["review_inputs"]["package"]["path"]
    package_digest = review_records.sha256_file(package)

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
    assert review_records.sha256_file(package) == package_digest

    decisions_path = tmp_path / first["review_inputs"]["decisions"]
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
    assert verification.workflow_state(resume, tmp_path)["state"] == "reviewed"

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


def test_preview_requires_an_explanation_for_accepted_fit_risk(tmp_path: Path, run_main) -> None:
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

    assert run_main(previewing.main, resume, "--vault-root", vault) == 2
    assert (
        run_main(
            previewing.main,
            resume,
            "--vault-root",
            vault,
            "--accept-review-risk",
        )
        == 2
    )
    assert (
        run_main(
            previewing.main,
            resume,
            "--vault-root",
            vault,
            "--accept-review-risk",
            "--review-risk-note",
            "User accepts the documented role-scope tradeoff for this application.",
        )
        == 0
    )
    preview = json.loads(
        (tmp_path / "build" / "support-operations.preview.json").read_text(encoding="utf-8")
    )
    assert preview["review_statuses"]["career_verdict"] == "needs-revision"
    assert preview["review_statuses"]["role_fit"] == "weak-or-misaligned"
    assert preview["risk_acceptance"]["accepted"] is True


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
    assert current["next_action"]["route"] == "critique"
    assert "1 baselines" in project_report.format_summary(current)

    write_approved_review(tmp_path, resume)
    reviewed = project_report.project_report(vault, strict=True)

    assert reviewed["resumes"][0]["critique"]["status"] == "current"
    assert reviewed["resumes"][0]["critique"]["evidence_status"] == "claim-checked"
    assert reviewed["resumes"][0]["critique"]["language_status"] == "approved"
    assert reviewed["next_action"]["route"] == "assess-regression-coverage"

    resume.write_text(resume.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    stale = project_report.project_report(vault, strict=True)

    assert stale["resumes"][0]["build"]["status"] == "stale"
    assert stale["next_action"]["route"] == "compile"


def test_mint_command_creates_audited_pdf(tmp_path: Path, run_main, monkeypatch) -> None:
    vault, resume = project(tmp_path)
    assert run_main(compilation.main, resume, "--vault-root", vault) == 0
    write_approved_review(tmp_path, resume)
    assert run_main(previewing.main, resume, "--vault-root", vault) == 0
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
    assert called["html"] == tmp_path / "build" / "support-operations.html"
    assert called["pdf"] == tmp_path / "build" / "support-operations.pdf"
    manifest = json.loads(
        (tmp_path / "build" / "support-operations.mint.json").read_text(encoding="utf-8")
    )
    assert manifest["phase"] == "mint"
    assert manifest["valid"] is True
    assert manifest["review_record"]["verdict"] == "ready-to-mint"
    assert manifest["preview_manifest"]["path"] == "build/support-operations.preview.json"
    assert manifest["user_approval"]["status"] == "approved-for-mint"
    assert project_report._mint_status(resume, tmp_path)["status"] == "current"
    html_path = tmp_path / "build" / "support-operations.html"
    html_path.write_text(html_path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    assert project_report._mint_status(resume, tmp_path)["status"] == "stale"


def test_mint_rejects_missing_or_stale_editorial_review(tmp_path: Path, run_main) -> None:
    vault, resume = project(tmp_path)

    assert run_main(minting.main, resume, "--vault-root", vault) == 2

    assert run_main(compilation.main, resume, "--vault-root", vault) == 0
    write_approved_review(tmp_path, resume)
    assert run_main(previewing.main, resume, "--vault-root", vault) == 0
    resume.write_text(resume.read_text(encoding="utf-8") + "\n", encoding="utf-8")

    assert run_main(minting.main, resume, "--vault-root", vault) == 2


def test_mint_cannot_bypass_rejected_language(tmp_path: Path, run_main) -> None:
    vault, resume = project(tmp_path)
    assert run_main(compilation.main, resume, "--vault-root", vault) == 0
    review_path = write_approved_review(tmp_path, resume)
    review = json.loads(review_path.read_text(encoding="utf-8"))
    review["verdict"] = "needs-revision"
    review["next_action"] = {"route": "rebuild", "summary": "Rewrite rejected prose."}
    editorial = review["language_review"]
    editorial["status"] = "changes-required"
    editorial["blocks"][0]["decision"] = "revise"
    editorial["blocks"][0]["note"] = "The headline is generic and needs clearer language."
    review_path.write_text(json.dumps(review), encoding="utf-8")

    assert (
        run_main(
            minting.main,
            resume,
            "--vault-root",
            vault,
            "--accept-review-risk",
        )
        == 2
    )
    assert not (tmp_path / "build" / "support-operations.pdf").exists()


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
    assert not (tmp_path / "build" / "support-operations.html").exists()


def test_compile_normalizes_ats_characters(tmp_path: Path, run_main) -> None:
    vault, resume = project(tmp_path)
    resume.write_text(resume_markdown().replace("Support engineer", "Support engineer—operator"))

    assert run_main(compilation.main, resume, "--vault-root", vault) == 0
    payload = json.loads((tmp_path / "build" / "support-operations.json").read_text())
    manifest = json.loads((tmp_path / "build" / "support-operations.manifest.json").read_text())
    assert payload["summary"].startswith("Support engineer-operator")
    assert manifest["ats_replacements"] == {"U+2014": 1}


@pytest.mark.browser
def test_mint_pdf_end_to_end(tmp_path: Path, run_main) -> None:
    vault, resume = project(tmp_path)
    assert run_main(compilation.main, resume, "--vault-root", vault) == 0
    write_approved_review(tmp_path, resume)
    assert run_main(previewing.main, resume, "--vault-root", vault) == 0

    assert (
        run_main(
            minting.main,
            resume,
            "--vault-root",
            vault,
        )
        == 0
    )
    pdf = tmp_path / "build" / "support-operations.pdf"
    manifest = json.loads(
        (tmp_path / "build" / "support-operations.mint.json").read_text(encoding="utf-8")
    )
    assert pdf.read_bytes().startswith(b"%PDF")
    assert manifest["pdf_audit"]["extraction"]["pages"] <= 2
    assert manifest["pdf_audit"]["extraction"]["claims_recovered"] >= 9


def test_strict_page_budget_retains_audited_draft(tmp_path: Path, run_main, monkeypatch) -> None:
    vault, resume = project(tmp_path)
    assert run_main(compilation.main, resume, "--vault-root", vault) == 0
    write_approved_review(tmp_path, resume)
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
    assert (tmp_path / "build" / "support-operations.pdf").is_file()
    manifest = json.loads(
        (tmp_path / "build" / "support-operations.mint.json").read_text(encoding="utf-8")
    )
    assert manifest["valid"] is False
    assert "draft PDF was retained" in manifest["errors"][0]
