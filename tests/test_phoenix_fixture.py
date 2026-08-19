from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


def _run(workspace: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["RESUME_BUILDER_WORKSPACE"] = str(workspace)
    return subprocess.run(
        [sys.executable, "-m", "resume_builder", *arguments],
        cwd=workspace,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )


def test_phoenix_fixture_validates_compiles_and_prepares_review(tmp_path: Path) -> None:
    fixture = Path(__file__).parents[1] / "examples" / "phoenix-wright" / "workspace"
    workspace = tmp_path / "workspace"
    shutil.copytree(fixture, workspace)

    validation = _run(workspace, "validate", "--strict")
    assert validation.returncode == 0, validation.stderr or validation.stdout

    direction = _run(workspace, "direction", "validate")
    assert direction.returncode == 0, direction.stderr or direction.stdout

    synthesis = _run(
        workspace,
        "synthesis",
        "resumes/plans/senior-defense-attorney.yaml",
    )
    assert synthesis.returncode == 0, synthesis.stderr or synthesis.stdout

    verification = _run(
        workspace,
        "verify",
        "resumes/baselines/senior-defense-attorney.md",
    )
    assert verification.returncode == 0, verification.stderr or verification.stdout
    assert (workspace / "build" / "senior-defense-attorney.verify.json").is_file()
    assert (workspace / "build" / "reviews" / "senior-defense-attorney.cold.json").is_file()
