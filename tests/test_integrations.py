"""Tests for optional integration setup guidance."""

from __future__ import annotations

from pathlib import Path

import pytest

from resume_builder.integrations import (
    integration_setup_guide,
    interactive_integration_setup,
    parse_integration_choices,
)
from resume_builder.job_onboarding import main as onboarding_main
from resume_builder.workspace import initialize_workspace


def test_parse_integration_choices_supports_names_numbers_and_all() -> None:
    assert parse_integration_choices("1, gmail, 3") == ("telegram", "gmail", "discord")
    assert parse_integration_choices("all") == ("telegram", "gmail", "discord")
    assert parse_integration_choices("none") == ()


def test_parse_integration_choices_rejects_unknown_values() -> None:
    with pytest.raises(ValueError, match="choose Telegram"):
        parse_integration_choices("slack")


def test_telegram_guide_uses_private_qr_pairing_without_personal_account_access(
    tmp_path: Path,
) -> None:
    guide = integration_setup_guide(("telegram",), tmp_path / "Private Workspace")

    assert "resume-builder agent telegram-setup" in guide
    assert "hidden prompt" in guide
    assert "one-use pairing QR" in guide
    assert "not access to your personal Telegram account" in guide
    assert "configures both allowlists automatically" in guide
    assert "Gmail application tracking" not in guide


def test_interactive_guide_can_select_multiple_integrations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    answers = iter(("yes", "1,3"))
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))

    guide = interactive_integration_setup(tmp_path)

    assert "Telegram conversations" in guide
    assert "Discord notifications" in guide
    assert "Gmail application tracking" not in guide


def test_declined_integrations_explain_how_to_return(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("builtins.input", lambda _prompt: "no")

    guide = interactive_integration_setup(tmp_path)

    assert "No integrations selected" in guide
    assert "resume-builder onboard integrations" in guide


def test_existing_user_can_reopen_integrations_wizard(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    run_main,
    capsys: pytest.CaptureFixture[str],
) -> None:
    workspace = tmp_path / "workspace"
    initialize_workspace(workspace)
    answers = iter(("yes", "telegram"))
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))

    assert run_main(onboarding_main, "--workspace", workspace, "integrations") == 0

    output = capsys.readouterr().out
    assert "Telegram conversations" in output
    assert "resume-builder agent doctor --channel telegram" in output


def test_integrations_command_supports_structured_noninteractive_selection(
    tmp_path: Path,
    run_main,
    capsys: pytest.CaptureFixture[str],
) -> None:
    workspace = tmp_path / "workspace"
    initialize_workspace(workspace)

    assert (
        run_main(
            onboarding_main,
            "--workspace",
            workspace,
            "--json",
            "integrations",
            "--select",
            "telegram,gmail",
        )
        == 0
    )

    output = capsys.readouterr().out
    assert '"kind": "integration_setup"' in output
    assert "Telegram conversations" in output
    assert "Gmail application tracking" in output
    assert "Discord notifications" not in output
