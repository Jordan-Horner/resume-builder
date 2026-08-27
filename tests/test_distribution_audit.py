from __future__ import annotations

import importlib.util
import io
import tarfile
import zipfile
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[1] / "scripts" / "audit_distribution.py"
SPEC = importlib.util.spec_from_file_location("audit_distribution", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("could not load distribution audit")
AUDIT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUDIT)
audit_sdist = AUDIT.audit_sdist
audit_wheel = AUDIT.audit_wheel


def _wheel(path: Path, files: dict[str, bytes]) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        for name, payload in files.items():
            archive.writestr(name, payload)


def _sdist(path: Path, files: dict[str, bytes]) -> None:
    with tarfile.open(path, "w:gz") as archive:
        for name, payload in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))


def test_distribution_audit_accepts_cli_wheel_and_fictional_source(tmp_path: Path) -> None:
    wheel = tmp_path / "resume_builder-0.12.0-py3-none-any.whl"
    _wheel(
        wheel,
        {
            "job_puller/cli.py": b"# inventory cli",
            "resume_builder/cli.py": b"# cli",
            "resume_builder/evidence_questions.py": b"# questions",
            "resume_builder/resources/workspace/vault/README.md": b"# Empty vault",
            "resume_builder-0.12.0.dist-info/METADATA": b"Name: resume-builder",
        },
    )
    audit_wheel(wheel, ())

    sdist = tmp_path / "resume_builder-0.12.0.tar.gz"
    _sdist(
        sdist,
        {
            "resume_builder-0.12.0/AGENTS.md": b"# Instructions",
            "resume_builder-0.12.0/CLAUDE.md": b"@AGENTS.md",
            "resume_builder-0.12.0/.agents/skills/example/SKILL.md": b"canonical",
            "resume_builder-0.12.0/.claude/skills/example/SKILL.md": b"adapter",
            "resume_builder-0.12.0/src/resume_builder/cli.py": b"# cli",
            "resume_builder-0.12.0/examples/phoenix-wright/workspace/README.md": b"fictional",
        },
    )
    audit_sdist(sdist, ())


def test_distribution_audit_rejects_runtime_data_and_private_strings(tmp_path: Path) -> None:
    wheel = tmp_path / "leaky.whl"
    _wheel(
        wheel,
        {
            "job_puller/cli.py": b"# inventory cli",
            "resume_builder/cli.py": b"private-marker",
            "resume_builder/evidence_questions.py": b"# questions",
            "resume_builder/resources/workspace/vault/README.md": b"# Empty vault",
            "resume_builder-0.12.0.dist-info/METADATA": b"Name: resume-builder",
        },
    )
    with pytest.raises(ValueError, match="denylist"):
        audit_wheel(wheel, (b"private-marker",))

    sdist = tmp_path / "leaky.tar.gz"
    _sdist(
        sdist,
        {
            "resume_builder-0.12.0/workspace/vault/vault.json": b"{}",
            "resume_builder-0.12.0/examples/phoenix-wright/workspace/README.md": b"fictional",
        },
    )
    with pytest.raises(ValueError, match="private runtime path"):
        audit_sdist(sdist, ())
