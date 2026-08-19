from __future__ import annotations

import hashlib
import json
from pathlib import Path

from resume_builder import schema_upgrade


def source_registry(vault: Path) -> None:
    snapshot = vault / "sources" / "normalized" / "SRC-0123456789ab.md"
    snapshot.parent.mkdir(parents=True)
    snapshot.write_text("Grounded source\n", encoding="utf-8")
    manifest = {
        "version": 1,
        "sources": [
            {
                "id": "SRC-0123456789ab",
                "sha256": "0123456789ab" + "0" * 52,
                "format": "md",
                "filenames": ["resume.md"],
                "snapshot": "sources/normalized/SRC-0123456789ab.md",
                "snapshot_sha256": hashlib.sha256(snapshot.read_bytes()).hexdigest(),
                "extracted_characters": 16,
                "extraction_status": "ok",
                "imported_at": "2026-08-16T00:00:00+00:00",
            }
        ],
    }
    (vault / "sources" / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (vault / "hydration-report.md").write_text("# Hydration report\n", encoding="utf-8")


def fact(fact_id: str, fact_type: str) -> str:
    return f"""---
schema_version: 1
id: {fact_id}
title: "Evidence"
type: {fact_type}
status: confirmed
category: employment
organization: example
sources:
  - SRC-0123456789ab
themes:
  - evidence
---

# Evidence

Supported evidence.
"""


def project(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    facts = vault / "facts" / "employment" / "example"
    facts.mkdir(parents=True)
    (vault / "vault.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "facts_path": "facts",
                "employment_path": "employment",
                "sources_manifest": "sources/manifest.json",
            }
        ),
        encoding="utf-8",
    )
    for fact_id, fact_type in (
        ("EX-001", "role"),
        ("EX-002", "role"),
        ("EX-003", "accomplishment"),
    ):
        (facts / f"{fact_id}.md").write_text(fact(fact_id, fact_type), encoding="utf-8")
    employment = vault / "employment"
    employment.mkdir()
    (employment / "example.md").write_text(
        """---
schema_version: 1
organization: "Example"
slug: example
status: confirmed
sources:
  - SRC-0123456789ab
fact_ids:
  - EX-001
  - EX-002
  - EX-003
---

# Example
""",
        encoding="utf-8",
    )
    source_registry(vault)
    return vault


def test_upgrade_defaults_ambiguous_multi_role_fact_to_organization(tmp_path: Path) -> None:
    vault = project(tmp_path)

    plan = schema_upgrade.build_upgrade_plan(vault)

    upgraded = dict(plan.writes)[vault / "facts" / "employment" / "example" / "EX-003.md"]
    assert "scope: organization" in upgraded
    assert plan.organization_scoped == ("EX-003",)


def test_upgrade_applies_reviewed_role_map_and_creates_recovery_copy(
    tmp_path: Path, run_main
) -> None:
    vault = project(tmp_path)
    role_map = tmp_path / "roles.json"
    role_map.write_text(
        json.dumps({"version": 1, "assignments": {"EX-003": ["EX-002"]}}),
        encoding="utf-8",
    )

    assert (
        run_main(
            schema_upgrade.main,
            "--vault-root",
            vault,
            "--role-map",
            role_map,
            "--apply",
        )
        == 0
    )

    upgraded = (vault / "facts" / "employment" / "example" / "EX-003.md").read_text()
    assert "schema_version: 2" in upgraded
    assert "scope: role" in upgraded
    assert "  - EX-002" in upgraded
    assert json.loads((vault / "vault.json").read_text())["schema_version"] == 2
    assert (vault / "migrations" / "v1-original" / "manifest.json").is_file()
    assert schema_upgrade.validate_vault(vault, strict=True)["valid"] is True
