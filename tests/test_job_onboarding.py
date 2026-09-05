from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml

from resume_builder import source_import
from resume_builder.discovery_evidence import ResumeDocument, evidence_set, extract_title_seed
from resume_builder.job_onboarding import (
    JobSearchSetupAnswer,
    SetupStatus,
    SetupStep,
    activate,
    activation_preview,
    apply_answer,
    evidence_update_preview,
    onboarding_status,
    scaffold_job_search,
    start_setup,
)
from resume_builder.workspace import initialize_workspace


def _hydrated_workspace(tmp_path: Path) -> Path:
    root = tmp_path / "workspace"
    initialize_workspace(root, git_name="Example User", git_email="example@example.invalid")
    source = tmp_path / "fictional-resume.md"
    source.write_text(
        """# Experience

## Example Cloud | Reliability Engineer | 2024 - 2026
- Supported Kubernetes services on AWS and investigated production incidents.

## Example Desk | Support Specialist | 2018 - 2020
- Resolved technical support requests.

# Technical Skills
- AWS, Kubernetes, Linux
""",
        encoding="utf-8",
    )
    layout = root / "vault"
    plan = source_import.build_import_plan(
        source_import.VaultLayout.load(layout, allow_missing=True), [str(source)], []
    )
    source_import.apply_import_plan(source_import.VaultLayout.load(layout), plan)
    manifest = json.loads((layout / "sources" / "manifest.json").read_text(encoding="utf-8"))
    source_id = manifest["sources"][0]["id"]
    fact_dir = layout / "facts" / "employment" / "example-cloud"
    fact_dir.mkdir(parents=True)
    (fact_dir / "EMP-001.md").write_text(
        f"""---
schema_version: 2
id: EMP-001
title: "Reliability work"
type: responsibility
status: confirmed
category: employment
organization: example-cloud
scope: organization
sources:
  - {source_id}
themes:
  - reliability
---

# Reliability work

Supported production services.
""",
        encoding="utf-8",
    )
    (layout / "employment" / "example-cloud.md").write_text(
        f"""---
schema_version: 2
organization: "Example Cloud"
slug: example-cloud
status: confirmed
sources:
  - {source_id}
fact_ids:
  - EMP-001
---

# Example Cloud
""",
        encoding="utf-8",
    )
    return root


def _answer(state, answer: dict) -> JobSearchSetupAnswer:
    return JobSearchSetupAnswer(
        session_id=state.session_id,
        step=state.step,
        answer=answer,
    )


def test_multiple_documents_deduplicate_content_and_titles() -> None:
    content = """# Experience
## Example | Reliability Engineer | 2024 - 2026
- Supported AWS services.
"""
    evidence = evidence_set(
        [
            ResumeDocument(source_id="SRC-A", content=content),
            ResumeDocument(source_id="SRC-B", content=content),
        ]
    )
    titles = extract_title_seed(evidence.documents)

    assert len(evidence.documents) == 1
    assert [item.query_title for item in titles.historical_titles] == ["Reliability Engineer"]


def test_fresh_workspace_has_neutral_inactive_job_search(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    initialize_workspace(root, git_name="Example User", git_email="example@example.invalid")

    preferences = yaml.safe_load((root / "job-search" / "preferences.yml").read_text())
    config = yaml.safe_load((root / "job-search" / "config" / "search.yml").read_text())

    assert preferences["desired_title_terms"] == []
    assert preferences["screening_profile"] == {}
    assert config["enabled"] is False
    assert config["search"]["families"] == []
    assert onboarding_status(root)["status"] == "needs_sources"


def test_job_setup_saves_inactive_configuration_then_activates(tmp_path: Path) -> None:
    root = _hydrated_workspace(tmp_path)
    state = start_setup(root)
    assert state.step == SetupStep.ROLES
    assert any(item.title == "Reliability Engineer" for item in state.roles)
    assert any(item.title == "Support Specialist" for item in state.roles)

    state = apply_answer(root, _answer(state, {"decisions": {}, "add": ["Cloud Engineer"]}))
    state = apply_answer(
        root,
        _answer(
            state,
            {
                "intended_country": "United States",
                "authorized_to_work": True,
                "requires_sponsorship": False,
                "held_clearances": [],
                "holds_clearance_or_public_trust": True,
                "willing_to_obtain_clearance": False,
            },
        ),
    )
    state = apply_answer(
        root,
        _answer(
            state,
            {
                "accepted_work_modes": ["remote", "hybrid"],
                "accepted_onsite_locations": ["Texas"],
                "remote_location_terms": [],
            },
        ),
    )
    state = apply_answer(root, _answer(state, {"skipped": True}))
    assert state.step == SetupStep.REVIEW
    state = apply_answer(root, _answer(state, {"action": "save"}))

    assert state.status == SetupStatus.READY_TO_ACTIVATE
    config_path = root / "job-search" / "config" / "search.yml"
    assert yaml.safe_load(config_path.read_text())["enabled"] is False
    assert not (root / "job-search" / "new-jobs.json").exists()
    preferences = yaml.safe_load((root / "job-search" / "preferences.yml").read_text())
    assert preferences["accepted_work_modes"] == ["remote", "hybrid"]
    assert preferences["screening_profile"]["authorized_to_work"] is True
    assert preferences["screening_profile"]["holds_clearance_or_public_trust"] is True

    preview = activation_preview(root)
    assert preview["scan_started"] is False
    active = activate(root, preview["confirmation_hash"])

    assert active.status == SetupStatus.ACTIVE
    assert yaml.safe_load(config_path.read_text())["enabled"] is True
    assert not (root / "job-search" / "new-jobs.json").exists()

    manifest_path = root / "vault" / "sources" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    snapshot = root / "vault" / manifest["sources"][0]["snapshot"]
    snapshot.write_text(
        snapshot.read_text(encoding="utf-8")
        + "\n# Experience\n## Example Systems | Platform Engineer | 2026 - Present\n- Supported Linux services.\n",
        encoding="utf-8",
    )
    manifest["sources"][0]["snapshot_sha256"] = hashlib.sha256(snapshot.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    assert onboarding_status(root)["evidence_update_available"] is True
    update = evidence_update_preview(root)
    assert [item["title"] for item in update["added"]] == ["Platform Engineer"]
    assert update["active_searches_changed"] is False


def test_scaffold_does_not_replace_existing_preferences(tmp_path: Path) -> None:
    root = tmp_path
    path = root / "job-search" / "preferences.yml"
    path.parent.mkdir(parents=True)
    path.write_text("custom: true\n", encoding="utf-8")

    installed = scaffold_job_search(root)

    assert path.read_text(encoding="utf-8") == "custom: true\n"
    assert "job-search/preferences.yml" not in installed
