from __future__ import annotations

import json
from pathlib import Path

from resume_builder import source_import, validation


def test_imported_source_passes_non_strict_validation(tmp_path: Path, run_main) -> None:
    source = tmp_path / "resume.md"
    source.write_text("A grounded source.\n", encoding="utf-8")
    vault = tmp_path / "vault"
    assert run_main(source_import.main, "--vault-root", vault, "--apply", source) == 0

    result = validation.validate_vault(vault)

    assert result["valid"] is True
    assert result["registered_sources"] == 1
    assert result["facts"] == 0


def test_strict_validation_rejects_unhydrated_vault(tmp_path: Path, run_main) -> None:
    source = tmp_path / "resume.md"
    source.write_text("A grounded source.\n", encoding="utf-8")
    vault = tmp_path / "vault"
    assert run_main(source_import.main, "--vault-root", vault, "--apply", source) == 0

    result = validation.validate_vault(vault, strict=True)

    assert result["valid"] is False
    assert "no atomic fact files found" in result["errors"]
    assert "no employment files found" in result["errors"]


def test_report_summary_surfaces_counts() -> None:
    result = {
        "valid": True,
        "schema_version": 2,
        "facts": 12,
        "employment_files": 3,
        "registered_sources": 5,
        "warnings": [],
        "errors": [],
    }

    summary = validation.format_summary(result)

    assert "Vault: VALID" in summary
    assert "Facts: 12" in summary
    assert "Registered sources: 5" in summary


def test_malformed_manifest_entry_is_reported_without_crashing(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    (vault / "sources").mkdir(parents=True)
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
    (vault / "sources" / "manifest.json").write_text(
        json.dumps({"version": 1, "sources": [42]}),
        encoding="utf-8",
    )

    result = validation.validate_vault(vault)

    assert result["valid"] is False
    assert "manifest source 0 must be an object" in result["errors"]


def test_unsafe_config_path_is_rejected(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "vault.json").write_text(
        json.dumps(
            {
                "schema_version": 2,
                "facts_path": "../outside",
                "employment_path": "employment",
                "sources_manifest": "sources/manifest.json",
            }
        ),
        encoding="utf-8",
    )

    result = validation.validate_vault(vault)

    assert result["valid"] is False
    assert any("traversal" in error for error in result["errors"])


def test_overlapping_config_paths_are_rejected(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "vault.json").write_text(
        json.dumps(
            {
                "schema_version": 2,
                "facts_path": "content",
                "employment_path": "content/employment",
                "sources_manifest": "sources/manifest.json",
            }
        ),
        encoding="utf-8",
    )

    result = validation.validate_vault(vault)

    assert result["valid"] is False
    assert any("must not overlap" in error for error in result["errors"])
