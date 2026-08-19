from __future__ import annotations

import hashlib
import json
from pathlib import Path

from resume_builder import migration

LEGACY_FACT = """### EMP-001 — Incident leadership

**Type:** accomplishment
**Status:** confirmed
**Sources:** SRC-0123456789ab
**Themes:** incident-management, leadership

Coordinated a cross-functional response without losing the original wording.
"""


def add_source_registry(vault: Path) -> None:
    snapshot = vault / "sources" / "normalized" / "SRC-0123456789ab.md"
    snapshot.parent.mkdir(parents=True)
    snapshot.write_text("Grounded source\n", encoding="utf-8")
    snapshot_hash = hashlib.sha256(snapshot.read_bytes()).hexdigest()
    manifest = {
        "version": 1,
        "sources": [
            {
                "id": "SRC-0123456789ab",
                "sha256": "0123456789ab" + "0" * 52,
                "format": "md",
                "filenames": ["resume.md"],
                "snapshot": "sources/normalized/SRC-0123456789ab.md",
                "snapshot_sha256": snapshot_hash,
                "extracted_characters": 16,
                "extraction_status": "ok",
                "imported_at": "2026-08-16T00:00:00+00:00",
            }
        ],
    }
    (vault / "sources" / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (vault / "hydration-report.md").write_text("# Hydration report\n", encoding="utf-8")


def test_migration_preserves_fact_content_and_provenance(tmp_path: Path, run_main) -> None:
    vault = tmp_path / "vault"
    roles = vault / "roles"
    roles.mkdir(parents=True)
    add_source_registry(vault)
    for filename in migration.CATEGORY_FILES:
        (vault / filename).write_text("# Empty legacy category\n", encoding="utf-8")
    (roles / "example.md").write_text(
        """---
organization: "Example Corp"
slug: example-corp
status: confirmed
sources:
  - SRC-0123456789ab
---

# Example Corp

"""
        + LEGACY_FACT,
        encoding="utf-8",
    )

    assert run_main(migration.main, "--vault-root", vault, "--apply") == 0

    fact = (vault / "facts" / "employment" / "example-corp" / "EMP-001.md").read_text()
    employment = (vault / "employment" / "example-corp.md").read_text()
    assert "Coordinated a cross-functional response" in fact
    assert "SRC-0123456789ab" in fact
    assert "EMP-001" in employment
    assert json.loads((vault / "vault.json").read_text())["schema_version"] == 2
    assert not (vault / "roles").exists()
    backup = vault / "migrations" / "v0-original"
    assert (backup / "profile.md").is_file()
    assert (backup / "roles" / "example.md").is_file()
    assert (backup / "manifest.json").is_file()
    assert migration.validate_vault(vault, strict=True)["valid"] is True


def test_migration_refuses_unmatched_legacy_content(tmp_path: Path, run_main) -> None:
    vault = tmp_path / "vault"
    roles = vault / "roles"
    roles.mkdir(parents=True)
    add_source_registry(vault)
    for filename in migration.CATEGORY_FILES:
        content = "Unparsed career narrative.\n" if filename == "profile.md" else "# Empty\n"
        (vault / filename).write_text(content, encoding="utf-8")
    (roles / "example.md").write_text(
        """---
organization: "Example Corp"
slug: example-corp
status: confirmed
sources:
  - SRC-0123456789ab
---

# Example Corp

"""
        + LEGACY_FACT,
        encoding="utf-8",
    )

    assert run_main(migration.main, "--vault-root", vault, "--apply") == 2

    assert (vault / "profile.md").read_text() == "Unparsed career narrative.\n"
    assert not (vault / "vault.json").exists()
    assert not (vault / "facts").exists()
