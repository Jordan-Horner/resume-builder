from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from resume_builder.review_records import (
    load_review_record,
    main,
    narrative_block_inventory,
    narrative_blocks,
    review_freshness,
    sha256_text,
)


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _review_project(tmp_path: Path) -> tuple[Path, Path, dict[str, object]]:
    paths = {
        "resume": tmp_path / "resumes" / "tailored" / "example-role.md",
        "plan": tmp_path / "resumes" / "plans" / "example-role.yaml",
        "direction": tmp_path / "directions" / "role.md",
        "target": tmp_path / "targets" / "example-role-2026-08-17.md",
    }
    for path in paths.values():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"{path.name}\n", encoding="utf-8")
    paths["resume"].write_text(
        """---
version: 1
candidate:
  name: Example Candidate
  headline: Example Operations Lead
  email: candidate@example.com
  location: Example location
  evidence: [PROFILE-001]
---
# Professional Summary

Improves customer example operations through clear investigation practices.
<!-- evidence: PROFILE-001 -->
""",
        encoding="utf-8",
    )
    review_path = tmp_path / "build" / "reviews" / "example-role.json"
    review_path.parent.mkdir(parents=True)
    record: dict[str, object] = {
        "version": 2,
        "reviewed_at": "2026-08-17T12:00:00+00:00",
        "resume": {"path": "resumes/tailored/example-role.md", "sha256": _digest(paths["resume"])},
        "plan": {"path": "resumes/plans/example-role.yaml", "sha256": _digest(paths["plan"])},
        "direction": {"path": "directions/role.md", "sha256": _digest(paths["direction"])},
        "target": {
            "path": "targets/example-role-2026-08-17.md",
            "sha256": _digest(paths["target"]),
        },
        "verdict": "ready-with-optional-improvements",
        "hiring_read": "compelling",
        "findings": {"material": 0, "worthwhile": 1, "optional": 0},
        "next_action": {
            "route": "mint",
            "summary": "Mint when the user explicitly approves the draft.",
        },
        "editorial_review": {
            "scope": "all-narrative-prose",
            "status": "approved",
            "blocks": [
                {
                    "id": block_id,
                    "sha256": sha256_text(text),
                    "decision": "approved",
                    "note": "",
                }
                for block_id, text in narrative_blocks(paths["resume"]).items()
            ],
        },
    }
    review_path.write_text(json.dumps(record), encoding="utf-8")
    return review_path, paths["resume"], record


def test_review_record_is_current_until_an_input_changes(tmp_path: Path) -> None:
    review_path, resume, _ = _review_project(tmp_path)

    record = load_review_record(review_path, tmp_path)

    assert record.verdict == "ready-with-optional-improvements"
    assert review_freshness(record) == []

    resume.write_text("changed\n", encoding="utf-8")
    assert review_freshness(record) == ["example-role.md changed after review"]


def test_review_record_rejects_invalid_or_unsafe_metadata(tmp_path: Path) -> None:
    review_path, _, raw = _review_project(tmp_path)
    raw["verdict"] = "looks-good"
    review_path.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(ValueError, match="review verdict"):
        load_review_record(review_path, tmp_path)

    with pytest.raises(ValueError, match="directly under build/reviews"):
        load_review_record(tmp_path / "elsewhere.json", tmp_path)


def test_legacy_whole_resume_review_cannot_approve_prose(tmp_path: Path) -> None:
    review_path, _, raw = _review_project(tmp_path)
    raw["version"] = 1
    raw.pop("editorial_review")
    review_path.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(ValueError, match=r"fields mismatch|version 2, 3, 4, or 5"):
        load_review_record(review_path, tmp_path)


def test_v3_approved_review_requires_independent_cold_reviewer(tmp_path: Path) -> None:
    review_path, _, raw = _review_project(tmp_path)
    raw["version"] = 3
    raw["reviewer"] = {
        "method": "single-context-review",
        "context": "The writer reviewed its own draft.",
    }
    review_path.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(ValueError, match=r"requires reviewer\.method independent-cold-review"):
        load_review_record(review_path, tmp_path)

    reviewer = raw["reviewer"]
    assert isinstance(reviewer, dict)
    reviewer["method"] = "independent-cold-review"
    reviewer["context"] = "Fresh reviewer received the resume and block inventory only."
    review_path.write_text(json.dumps(raw), encoding="utf-8")

    record = load_review_record(review_path, tmp_path)

    assert record.version == 3
    assert record.reviewer_method == "independent-cold-review"


def test_review_record_requires_complete_block_coverage(tmp_path: Path) -> None:
    review_path, _, raw = _review_project(tmp_path)
    editorial = raw["editorial_review"]
    assert isinstance(editorial, dict)
    blocks = editorial["blocks"]
    assert isinstance(blocks, list)
    blocks.pop()
    review_path.write_text(json.dumps(raw), encoding="utf-8")

    record = load_review_record(review_path, tmp_path)

    assert review_freshness(record) == ["editorial review is missing narrative blocks: ['summary']"]


def test_changes_required_review_must_name_rejected_prose(tmp_path: Path) -> None:
    review_path, _, raw = _review_project(tmp_path)
    raw["verdict"] = "needs-revision"
    raw["next_action"] = {"route": "rebuild", "summary": "Rewrite the rejected block."}
    editorial = raw["editorial_review"]
    assert isinstance(editorial, dict)
    editorial["status"] = "changes-required"
    blocks = editorial["blocks"]
    assert isinstance(blocks, list)
    first = blocks[0]
    assert isinstance(first, dict)
    first["decision"] = "revise"
    first["note"] = "The headline is generic and does not identify the target clearly."
    review_path.write_text(json.dumps(raw), encoding="utf-8")

    record = load_review_record(review_path, tmp_path)

    assert record.editorial_status == "changes-required"
    assert record.editorial_blocks[0].decision == "revise"


def test_review_cli_lists_blocks_and_validates_record(tmp_path: Path, run_main, capsys) -> None:
    review_path, resume, _ = _review_project(tmp_path)

    assert (
        run_main(
            main,
            "blocks",
            resume.relative_to(tmp_path),
            "--project-root",
            tmp_path,
        )
        == 0
    )
    listed = json.loads(capsys.readouterr().out)
    assert [block["id"] for block in listed["blocks"]] == ["candidate.headline", "summary"]
    assert listed["blocks"][0]["context"] == {
        "section": "Header",
        "candidate_name": "Example Candidate",
    }
    assert listed["blocks"][1]["context"] == {
        "section": "Professional Summary",
        "headline": "Example Operations Lead",
    }
    assert listed["blocks"][1]["advisories"] == []

    assert run_main(main, "validate", review_path, "--project-root", tmp_path) == 0
    validated = json.loads(capsys.readouterr().out)
    assert validated["valid"] is True
    assert validated["blocks"] == 2


def test_review_inventory_includes_role_neighbors_and_repetition_advisory(tmp_path: Path) -> None:
    resume = tmp_path / "resumes" / "tailored" / "context-test.md"
    resume.parent.mkdir(parents=True)
    resume.write_text(
        """---
version: 1
candidate:
  name: Example Candidate
  headline: Engineering Support Leadership
  email: candidate@example.com
  location: Example location
  evidence: [PROFILE-001]
---
# Professional Summary

Leads complex engineering support work. <!-- evidence: PROFILE-001 -->

# Work Experience

## Example Organization | Example Tech Lead | 2025 - 2026 <!-- evidence: EX-002 -->

- As Tech Lead, directed incident response. <!-- evidence: EX-003 -->
- Built support automation. <!-- evidence: EX-004 -->

## Example Organization B | Example Specialist | 2021 - 2023 <!-- evidence: EY-001 -->

- Served as incident commander. <!-- evidence: EY-012 -->

# Education

- Bachelor of Science | Example University | 2020 <!-- evidence: EDU-001 -->

# Technical Skills

- **Support:** Incident response <!-- evidence: SKILL-001 -->
""",
        encoding="utf-8",
    )

    inventory = narrative_block_inventory(resume)
    blocks = {block.id: block for block in inventory}
    first = blocks["experience[0].bullets[0]"]
    second = blocks["experience[0].bullets[1]"]
    other_role = blocks["experience[1].bullets[0]"]

    assert first.context == {
        "section": "Work Experience",
        "company": "Example Organization",
        "role": "Example Tech Lead",
        "dates": "2025 - 2026",
        "location": None,
        "previous_block": None,
        "next_block": "Built support automation.",
    }
    assert first.advisories == (
        "opening may repeat the visible role heading; verify that it adds scope, "
        "authority, chronology, contrast, or necessary qualification",
    )
    assert second.context["previous_block"] == "As Tech Lead, directed incident response."
    assert second.advisories == ()
    assert other_role.context["company"] == "Example Organization B"
    assert other_role.context["role"] == "Example Specialist"
    assert other_role.context["previous_block"] is None


def test_review_inventory_does_not_flag_role_context_that_adds_authority(tmp_path: Path) -> None:
    resume = tmp_path / "resumes" / "tailored" / "authority-test.md"
    resume.parent.mkdir(parents=True)
    resume.write_text(
        """---
version: 1
candidate:
  name: Example Candidate
  headline: Engineering Support Leadership
  email: candidate@example.com
  location: Example location
  evidence: [PROFILE-001]
---
# Professional Summary

Leads complex engineering support work. <!-- evidence: PROFILE-001 -->

# Work Experience

## Example Organization B | Example Specialist | 2021 - 2023 <!-- evidence: EY-001 -->

- As acting incident commander, coordinated response. <!-- evidence: EY-012 -->

# Education

- Bachelor of Science | Example University | 2020 <!-- evidence: EDU-001 -->

# Technical Skills

- **Support:** Incident response <!-- evidence: SKILL-001 -->
""",
        encoding="utf-8",
    )

    block = next(
        item for item in narrative_block_inventory(resume) if item.id == "experience[0].bullets[0]"
    )

    assert block.advisories == ()


def test_review_inventory_flags_low_information_and_unresolved_authority_openings(
    tmp_path: Path,
) -> None:
    resume = tmp_path / "resumes" / "tailored" / "contribution-test.md"
    resume.parent.mkdir(parents=True)
    resume.write_text(
        """---
version: 1
candidate:
  name: Example Candidate
  headline: Engineering Support Leadership
  email: candidate@example.com
  location: Example location
  evidence: [PROFILE-001]
---
# Professional Summary

Leads complex engineering support work. <!-- evidence: PROFILE-001 -->

# Work Experience

## Example Organization B | Example Specialist | 2021 - 2023 <!-- evidence: EY-001 -->

- Used Python to investigate alerts. <!-- evidence: EY-007 -->
- Participated in or led enterprise customer calls. <!-- evidence: EY-004 -->

# Education

- Bachelor of Science | Example University | 2020 <!-- evidence: EDU-001 -->

# Technical Skills

- **Support:** Incident response <!-- evidence: SKILL-001 -->
""",
        encoding="utf-8",
    )

    blocks = {block.id: block for block in narrative_block_inventory(resume)}

    assert (
        "tool use rather than the candidate's contribution"
        in blocks["experience[0].bullets[0]"].advisories[0]
    )
    assert "authority unresolved" in blocks["experience[0].bullets[1]"].advisories[0]


def test_review_inventory_flags_nested_lists_but_not_coherent_long_bullet(tmp_path: Path) -> None:
    resume = tmp_path / "resumes" / "tailored" / "density-test.md"
    resume.parent.mkdir(parents=True)
    resume.write_text(
        """---
version: 1
candidate:
  name: Example Candidate
  headline: Engineering Support Leadership
  email: candidate@example.com
  location: Example location
  evidence: [PROFILE-001]
---
# Professional Summary

Leads complex engineering support work. <!-- evidence: PROFILE-001 -->

# Work Experience

## Example Organization | Example Operations Lead | 2025 - 2026 <!-- evidence: EX-002 -->

- Directed incident response during high-severity customer issues, coordinating investigations, live troubleshooting, engineering updates, and resolution across databases, APIs, logs, cloud systems, and connected workflows. <!-- evidence: EX-003 -->
- Owned high-severity, customer-facing production issues from investigation through resolution, leading live troubleshooting across databases, APIs, logs, and cloud systems while coordinating engineering updates. <!-- evidence: EX-004 -->

## Example Organization C | Cloud Engineer | 2022 - 2023 <!-- evidence: EZ-001 -->

- As one of two primary engineers, delivered a highly available multi-region AWS environment with Terraform across development, UAT, and production; investigated REST-service and CloudTrail failures and validated changes before rollout. <!-- evidence: EZ-002 -->

# Education

- Bachelor of Science | Example University | 2020 <!-- evidence: EDU-001 -->

# Technical Skills

- **Support:** Incident response <!-- evidence: SKILL-001 -->
""",
        encoding="utf-8",
    )

    blocks = {block.id: block for block in narrative_block_inventory(resume)}

    assert blocks["experience[0].bullets[0]"].advisories == (
        "block may contain nested lists competing with its main claim; verify that each "
        "enumerated detail materially improves proof, scope, outcome, or differentiation",
    )
    assert blocks["experience[0].bullets[1]"].advisories == (
        "block may contain nested lists competing with its main claim; verify that each "
        "enumerated detail materially improves proof, scope, outcome, or differentiation",
    )
    assert blocks["experience[1].bullets[0]"].advisories == ()


def test_approved_advisory_requires_reviewer_note(tmp_path: Path) -> None:
    review_path, resume, raw = _review_project(tmp_path)
    resume.write_text(
        resume.read_text(encoding="utf-8").replace(
            "Improves customer example operations through clear investigation practices.",
            "Improves investigations across databases, APIs, logs, cloud systems, and "
            "connected workflows, coordinating support, engineering, customers, and leaders.",
        ),
        encoding="utf-8",
    )
    raw["resume"] = {
        "path": "resumes/tailored/example-role.md",
        "sha256": _digest(resume),
    }
    editorial = raw["editorial_review"]
    assert isinstance(editorial, dict)
    editorial["blocks"] = [
        {
            "id": block.id,
            "sha256": sha256_text(block.text),
            "decision": "approved",
            "note": "",
        }
        for block in narrative_block_inventory(resume)
    ]
    review_path.write_text(json.dumps(raw), encoding="utf-8")

    record = load_review_record(review_path, tmp_path)

    assert review_freshness(record) == [
        "approved narrative blocks with advisories require a reviewer note: ['summary']"
    ]
    raw_blocks = editorial["blocks"]
    assert isinstance(raw_blocks, list)
    summary = next(block for block in raw_blocks if block["id"] == "summary")
    summary["note"] = "The list is deliberate because it defines the operating scope."
    review_path.write_text(json.dumps(raw), encoding="utf-8")
    assert review_freshness(load_review_record(review_path, tmp_path)) == []
