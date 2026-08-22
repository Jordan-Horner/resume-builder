from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from resume_builder import job_matching, previewing


def direction_markdown() -> str:
    return """---
schema_version: 1
slug: incident-operations
status: approved
maturity: provisional
target_titles:
  - Example Operations Lead
audiences:
  - Reliability leadership
positioning: Keep incident response organized and improve it through durable tooling.
priority_concepts:
  - id: incident-response
    label: Incident response
    weight: 5
    terms:
      - incident response
    evidence_themes:
      - incident-response
    basis: user-confirmed
    source_ids:
      - DIRSRC-001
de_emphasize: []
avoid_terms: []
defaults:
  max_pages: 2
  page_format: letter
  minimum_coverage: 75
success_criteria:
  - Demonstrate reliable incident response.
sources:
  - id: DIRSRC-001
    kind: user
    reference: User-selected role direction
    as_of: 2026-08-17
---

# Example Operations

Reusable role context.
"""


def target_markdown(*, digest: str | None = None) -> str:
    body = """# Job Posting Snapshot

## Qualifications

Incident response experience is required. Durable AI workflows are preferred.
"""
    body_digest = digest or job_matching.body_sha256(body)
    return f"""---
schema_version: 1
slug: example-incident-operations-2026-08-17
company: Example
role: Example Operations Lead
captured_at: 2026-08-17
source:
  kind: url
  reference: Official employer posting
  url: https://example.com/jobs/incident-operations
  published_at: 2026-08-17
  body_sha256: "{body_digest}"
direction: directions/incident-operations.md
criteria:
  - id: incident-response
    importance: required
    label: Incident response
    description: Has direct incident response experience.
    resume_evaluable: true
    source_section: Qualifications
  - id: ai-workflows
    importance: preferred
    label: Durable AI workflows
    description: Has built durable AI-assisted workflows.
    resume_evaluable: true
    source_section: Qualifications
  - id: work-eligibility
    importance: required
    label: Work eligibility
    description: Can work in the supported location.
    resume_evaluable: false
    source_section: Location
search_groups:
  - id: incident-response
    criterion_id: incident-response
    any_of:
      - incident response
      - incident management
  - id: ai-workflows
    criterion_id: ai-workflows
    any_of:
      - AI-assisted workflows
      - AI-powered workflows
---

{body}"""


def resume_markdown(*, ai_workflows: bool) -> str:
    summary = "Incident response leader"
    bullet = "Led incident response and coordinated reliable follow-through."
    if ai_workflows:
        summary = "Incident response leader who builds durable operational systems."
        bullet = (
            "Built AI-assisted workflows and led incident response with reliable follow-through."
        )
    return f"""---
version: 1
lang: en
page_format: letter
candidate:
  name: Example Person
  headline: Example Operations
  email: example@example.com
  evidence: [OPS-001]
---

# Professional Summary

{summary} <!-- evidence: OPS-001 -->

# Work Experience

## ExampleCo | Example Operations Lead | 2023 - Present <!-- evidence: OPS-001 -->

- {bullet} <!-- evidence: OPS-001 -->
"""


def project(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    vault = tmp_path / "vault"
    facts = vault / "facts" / "employment" / "example"
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
    (facts / "OPS-001.md").write_text(
        """---
schema_version: 2
id: OPS-001
title: Incident operations and AI workflows
type: accomplishment
status: confirmed
category: employment
sources:
  - SRC-0123456789ab
themes:
  - incident-response
  - workflow-automation
---

# Incident operations and AI workflows

Example Person has worked at ExampleCo as an Example Operations Lead from 2023 to
the present. They led incident response, coordinated reliable follow-through, and
built durable AI-assisted workflows and operational systems.
""",
        encoding="utf-8",
    )
    direction = tmp_path / "directions" / "incident-operations.md"
    direction.parent.mkdir()
    direction.write_text(direction_markdown(), encoding="utf-8")
    target = tmp_path / "targets" / "example-incident-operations-2026-08-17.md"
    target.parent.mkdir()
    target.write_text(target_markdown(), encoding="utf-8")
    baseline = tmp_path / "resumes" / "baselines" / "incident-operations.md"
    baseline.parent.mkdir(parents=True)
    baseline.write_text(resume_markdown(ai_workflows=False), encoding="utf-8")
    tailored = tmp_path / "resumes" / "tailored" / "example-incident-operations.md"
    tailored.parent.mkdir(parents=True)
    tailored.write_text(resume_markdown(ai_workflows=True), encoding="utf-8")
    return vault, target, baseline, tailored


def nested_keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {key for item in value.values() for key in nested_keys(item)}
    if isinstance(value, list):
        return {key for item in value for key in nested_keys(item)}
    return set()


def test_target_contract_validates_snapshot_and_semantic_boundary(tmp_path: Path) -> None:
    target = tmp_path / "example-incident-operations-2026-08-17.md"
    target.write_text(target_markdown(), encoding="utf-8")

    metadata, body = job_matching.parse_target(target)

    assert metadata["company"] == "Example"
    assert metadata["criteria"][2]["resume_evaluable"] is False
    assert body.startswith("# Job Posting Snapshot")

    target.write_text(target_markdown(digest="0" * 64), encoding="utf-8")
    with pytest.raises(ValueError, match=r"does not match source\.body_sha256"):
        job_matching.parse_target(target)


def test_preview_job_context_uses_the_pinned_target_identity(tmp_path: Path) -> None:
    target = tmp_path / "targets" / "example-incident-operations-2026-08-17.md"
    target.parent.mkdir()
    target.write_text(target_markdown(), encoding="utf-8")
    digest = hashlib.sha256(target.read_bytes()).hexdigest()

    context = previewing._job_context(
        {"path": "targets/example-incident-operations-2026-08-17.md", "sha256": digest},
        tmp_path,
    )

    assert context == {
        "company": "Example",
        "role": "Example Operations Lead",
        "label": "Example — Example Operations Lead",
        "target_path": "targets/example-incident-operations-2026-08-17.md",
        "target_sha256": digest,
    }

    target.write_text(target.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="pinned job posting changed"):
        previewing._job_context(
            {"path": "targets/example-incident-operations-2026-08-17.md", "sha256": digest},
            tmp_path,
        )

    invalid = target_markdown().replace(
        "criterion_id: incident-response", "criterion_id: work-eligibility", 1
    )
    target.write_text(invalid, encoding="utf-8")
    with pytest.raises(ValueError, match="not resume-evaluable"):
        job_matching.parse_target(target)


def test_exact_retrieval_separates_listing_from_demonstrated_evidence(tmp_path: Path) -> None:
    target_path = tmp_path / "example-incident-operations-2026-08-17.md"
    target_path.write_text(target_markdown(), encoding="utf-8")
    target, _ = job_matching.parse_target(target_path)
    payload = {
        "candidate": {
            "name": "Example Person",
            "headline": "Incident response",
            "evidence": ["OPS-001"],
        },
        "summary": "Builds operational systems.",
        "summary_evidence": ["OPS-001"],
        "experience": [
            {
                "company": "ExampleCo",
                "role": "Lead",
                "dates": "2023 - Present",
                "evidence": ["OPS-001"],
                "bullets": [
                    {
                        "text": "Built AI-assisted workflows.",
                        "evidence": ["OPS-001"],
                    }
                ],
            }
        ],
    }

    result = job_matching.exact_retrieval(target, payload)
    by_id = {group["id"]: group for group in result["groups"]}

    assert by_id["incident-response"]["found"] is True
    assert by_id["incident-response"]["demonstrated"] is False
    assert by_id["ai-workflows"]["demonstrated"] is True
    assert result["listed_without_demonstration_group_ids"] == ["incident-response"]
    assert job_matching.phrase_occurrences("SQL", "SQL and NoSQL") == 1


def test_match_writes_reproducible_report_and_baseline_delta(tmp_path: Path) -> None:
    vault, target, baseline, tailored = project(tmp_path)

    result = job_matching.match_job(target, tailored, baseline=baseline, vault_root=vault)

    assert result["scope"] == "resume-only job match"
    assert result["target"]["sha256"]
    assert result["target"]["direction_sha256"]
    assert result["resume"]["sha256"]
    assert result["comparison"]["baseline"]["sha256"]
    assert result["comparison"]["delta"]["retrieval"]["gained_group_ids"] == ["ai-workflows"]
    assert result["comparison"]["delta"]["retrieval"]["lost_group_ids"] == []
    assert result["comparison"]["delta"]["evidence"]["removed_fact_ids"] == []
    assert "score" not in nested_keys(result)
    json_path = tmp_path / result["outputs"][0]
    report_path = tmp_path / result["outputs"][1]
    assert json_path.is_file()
    assert report_path.is_file()
    report = report_path.read_text(encoding="utf-8")
    assert "not an ATS score or hiring verdict" in report
    assert "Retrieval gained: ai-workflows" in report


def test_markdown_report_neutralizes_untrusted_posting_text(tmp_path: Path) -> None:
    vault, target, baseline, tailored = project(tmp_path)
    result = job_matching.match_job(target, tailored, baseline=baseline, vault_root=vault)

    company = 'Example\n\n## Forged section\n<img src="https://attacker.invalid/pixel">'
    role = "[Operations Lead](https://attacker.invalid)"
    matched_term = "incident response\n| forged | table | row |"
    target_path = "targets/unsafe``name.md"
    result["target"]["company"] = company
    result["target"]["role"] = role
    result["target"]["path"] = target_path
    result["resume"]["audit"]["exact_retrieval"]["groups"][0]["matches"][0]["term"] = matched_term

    report = job_matching.markdown_report(result)

    assert result["target"]["company"] == company
    assert result["target"]["role"] == role
    assert result["target"]["path"] == target_path
    assert "\n## Forged section" not in report
    assert "<img" not in report
    assert r"\[Operations Lead\](https\://attacker\.invalid)" in report
    assert "| forged | table | row |" not in report
    assert "incident response \\| forged \\| table \\| row \\|" in report
    assert "``` targets/unsafe``name.md ```" in report
    assert report.count("\n## Required judgment\n") == 1


def test_match_command_reports_findings_without_treating_them_as_failure(
    tmp_path: Path, run_main, capsys
) -> None:
    vault, target, baseline, tailored = project(tmp_path)

    assert run_main(job_matching.main, target, baseline, "--vault-root", vault) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["required_missing_group_ids"] == []

    assert (
        run_main(
            job_matching.main,
            target,
            tailored,
            "--baseline",
            baseline,
            "--vault-root",
            vault,
        )
        == 0
    )

    outside = tmp_path / "outside.md"
    outside.write_text(target_markdown(), encoding="utf-8")
    assert run_main(job_matching.main, outside, baseline, "--vault-root", vault) == 2


def test_target_validation_discovers_canonical_records(tmp_path: Path, run_main, capsys) -> None:
    vault, target, _, _ = project(tmp_path)

    assert run_main(job_matching.main, "validate", "--vault-root", vault) == 0
    result = json.loads(capsys.readouterr().out)

    assert result["count"] == 1
    assert result["targets"][0]["path"] == target.relative_to(tmp_path).as_posix()
    assert result["targets"][0]["body_sha256"]


def test_baseline_comparison_enforces_canonical_paths(tmp_path: Path) -> None:
    vault, target, baseline, _ = project(tmp_path)

    with pytest.raises(ValueError, match="target must be under resumes/tailored"):
        job_matching.match_job(target, baseline, baseline=baseline, vault_root=vault)
