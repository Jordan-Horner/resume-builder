from pathlib import Path

from resume_builder.web_career import list_skills
from resume_builder.workspace import initialize_workspace


def test_skills_ignore_macos_metadata_files(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    initialize_workspace(root, git_name="Example User", git_email="example@example.invalid")
    skills = root / "vault" / "facts" / "skills"
    skills.mkdir(parents=True, exist_ok=True)
    (skills / "SKILL-001.md").write_text(
        """---
schema_version: 2
id: SKILL-001
title: Incident response
type: responsibility
status: confirmed
category: skills
sources:
  - SRC-example
themes:
  - operations
---

Used incident response while supporting production systems.
""",
        encoding="utf-8",
    )
    (skills / "._SKILL-001.md").write_bytes(b"\x00\xa3metadata")

    result = list_skills(root)

    assert [item["id"] for item in result] == ["SKILL-001"]
