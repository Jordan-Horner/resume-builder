from __future__ import annotations

import hashlib
import json
from pathlib import Path

from resume_builder import plans, source_import, validation


def fact_content(fact_id: str, source_id: str, title: str) -> str:
    return f"""---
schema_version: 2
id: {fact_id}
title: {json.dumps(title)}
type: accomplishment
status: confirmed
category: employment
organization: example-corp
scope: organization
sources:
  - {source_id}
themes:
  - operations
---

# {title}

Grounded fact body.
"""


def employment_content(source_id: str, fact_ids: list[str]) -> str:
    indexed = "\n".join(f"  - {fact_id}" for fact_id in fact_ids)
    return f"""---
schema_version: 2
organization: "Example Corp"
slug: example-corp
status: confirmed
sources:
  - {source_id}
fact_ids:
{indexed}
---

# Example Corp
"""


def create_valid_vault(tmp_path: Path, run_main) -> tuple[Path, str]:
    source = tmp_path / "resume.md"
    source.write_text("Source evidence.\n", encoding="utf-8")
    vault = tmp_path / "vault"
    assert run_main(source_import.main, "--vault-root", vault, "--apply", source) == 0
    manifest = json.loads((vault / "sources" / "manifest.json").read_text())
    source_id = manifest["sources"][0]["id"]
    facts = vault / "facts" / "employment" / "example-corp"
    facts.mkdir(parents=True)
    (facts / "EMP-001.md").write_text(
        fact_content("EMP-001", source_id, "Existing fact"),
        encoding="utf-8",
    )
    employment = vault / "employment" / "example-corp.md"
    employment.write_text(
        employment_content(source_id, ["EMP-001"]),
        encoding="utf-8",
    )
    (vault / "hydration-report.md").write_text("# Hydration report\n", encoding="utf-8")
    assert validation.validate_vault(vault, strict=True)["valid"] is True
    return vault, source_id


def make_add_plan(vault: Path, source_id: str, path: Path) -> Path:
    employment = vault / "employment" / "example-corp.md"
    digest = hashlib.sha256(employment.read_bytes()).hexdigest()
    data = {
        "version": 1,
        "rationale": "Add a source-grounded accomplishment and update its index.",
        "writes": [
            {
                "path": "facts/employment/example-corp/EMP-002.md",
                "expected_sha256": None,
                "content": fact_content("EMP-002", source_id, "New fact"),
            },
            {
                "path": "employment/example-corp.md",
                "expected_sha256": digest,
                "content": employment_content(source_id, ["EMP-001", "EMP-002"]),
            },
        ],
    }
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_plan_preview_does_not_write(tmp_path: Path, run_main) -> None:
    vault, source_id = create_valid_vault(tmp_path, run_main)
    plan = make_add_plan(vault, source_id, tmp_path / "plan.json")

    assert run_main(plans.main, "preview", plan, "--vault-root", vault) == 0

    assert not (vault / "facts" / "employment" / "example-corp" / "EMP-002.md").exists()


def test_plan_apply_writes_validated_fact_and_index(tmp_path: Path, run_main) -> None:
    vault, source_id = create_valid_vault(tmp_path, run_main)
    plan = make_add_plan(vault, source_id, tmp_path / "plan.json")

    assert run_main(plans.main, "apply", plan, "--vault-root", vault) == 0

    assert (vault / "facts" / "employment" / "example-corp" / "EMP-002.md").is_file()
    assert validation.validate_vault(vault, strict=True)["valid"] is True


def test_plan_rejects_stale_expected_hash(tmp_path: Path, run_main) -> None:
    vault, source_id = create_valid_vault(tmp_path, run_main)
    plan = make_add_plan(vault, source_id, tmp_path / "plan.json")
    employment = vault / "employment" / "example-corp.md"
    employment.write_text(employment.read_text() + "\n", encoding="utf-8")

    assert run_main(plans.main, "apply", plan, "--vault-root", vault) == 2

    assert not (vault / "facts" / "employment" / "example-corp" / "EMP-002.md").exists()


def test_plan_rejects_noncanonical_target(tmp_path: Path, run_main) -> None:
    vault, _ = create_valid_vault(tmp_path, run_main)
    plan = tmp_path / "plan.json"
    plan.write_text(
        json.dumps(
            {
                "version": 1,
                "rationale": "Attempt an invalid write.",
                "writes": [
                    {
                        "path": "../outside.md",
                        "expected_sha256": None,
                        "content": "No.",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    assert run_main(plans.main, "validate", plan, "--vault-root", vault) == 2
