from __future__ import annotations

import subprocess
import sys


def test_module_cli_lists_commands() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "resume_builder", "--help"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "hydrate" in result.stdout
    assert "validate" in result.stdout
    assert "report" in result.stdout
    assert "plan" in result.stdout
    assert "render" in result.stdout
    assert "compile" in result.stdout
    assert "verify" in result.stdout
    assert "mint" in result.stdout
    assert "preview" in result.stdout
    assert "direction" in result.stdout
    assert "match" in result.stdout
    assert "review" in result.stdout
    assert "feedback" in result.stdout
