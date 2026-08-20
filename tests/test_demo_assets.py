from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parents[1]


def _run(*args: str, cwd: Path = ROOT) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "scripts/check_demo_assets.py", *args],
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
    )


def test_committed_phoenix_demo_assets_are_current() -> None:
    result = _run()
    assert result.returncode == 0, result.stdout + result.stderr


def test_demo_asset_check_detects_changed_input(tmp_path: Path) -> None:
    files = (
        "scripts/capture_demo_resume.py",
        "scripts/check_demo_assets.py",
        "docs/assets/phoenix-demo-assets.json",
        "docs/assets/phoenix-demo-flow.svg",
        "docs/assets/phoenix-wright-resume.jpg",
        "examples/phoenix-wright/README.md",
        "examples/phoenix-wright/workspace/directions/senior-defense-attorney.md",
        "examples/phoenix-wright/workspace/resumes/plans/senior-defense-attorney.yaml",
        "examples/phoenix-wright/workspace/resumes/baselines/senior-defense-attorney.md",
        "examples/phoenix-wright/workspace/resumes/selections/senior-defense-attorney.json",
        "examples/phoenix-wright/workspace/templates/resume-template.html",
    )
    for relative in files:
        source = ROOT / relative
        destination = tmp_path / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)

    resume = (
        tmp_path / "examples/phoenix-wright/workspace/resumes/baselines/senior-defense-attorney.md"
    )
    resume.write_text(resume.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    result = _run("--root", str(tmp_path), cwd=tmp_path)
    assert result.returncode == 1
    assert "stale demo input" in result.stdout
