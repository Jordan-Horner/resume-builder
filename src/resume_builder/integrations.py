"""Interactive, secret-safe setup guidance for optional external integrations."""

from __future__ import annotations

import shlex
from collections.abc import Sequence
from pathlib import Path

INTEGRATION_CHOICES = {
    "1": "telegram",
    "2": "gmail",
    "3": "discord",
}


def parse_integration_choices(value: str) -> tuple[str, ...]:
    """Normalize a comma-separated integration selection without accepting surprises."""
    normalized = value.strip().casefold()
    if normalized in {"", "none", "n", "no", "skip"}:
        return ()
    if normalized == "all":
        return tuple(INTEGRATION_CHOICES.values())
    aliases = {
        **INTEGRATION_CHOICES,
        "telegram": "telegram",
        "gmail": "gmail",
        "discord": "discord",
    }
    selected: list[str] = []
    for raw in normalized.split(","):
        choice = aliases.get(raw.strip())
        if choice is None:
            raise ValueError("choose Telegram, Gmail, Discord, all, or none")
        if choice not in selected:
            selected.append(choice)
    return tuple(selected)


def integration_setup_guide(integrations: Sequence[str], workspace: Path) -> str:
    """Render setup steps without collecting or persisting credentials."""
    unknown = sorted(set(integrations) - set(INTEGRATION_CHOICES.values()))
    if unknown:
        raise ValueError(f"unknown integrations: {', '.join(unknown)}")
    root = workspace.expanduser().resolve()
    lines = [
        "### Optional integrations",
        "",
        f"Run these commands from your private workspace: `cd {shlex.quote(str(root))}`.",
        "Never paste bot tokens, API keys, webhooks, or OAuth files into chat or Git.",
    ]
    if not integrations:
        lines.extend(
            [
                "",
                "No integrations selected. You can return with "
                "`resume-builder onboard integrations`.",
            ]
        )
        return "\n".join(lines)
    if "telegram" in integrations:
        lines.extend(
            [
                "",
                "#### Telegram conversations",
                "",
                "Use a private bot that belongs only to you. The guided setup opens Telegram "
                "Web, where its QR login avoids moving the BotFather token from your phone. "
                "Resume Builder receives only the private bot token, not access to your "
                "personal Telegram account.",
                "",
                '1. Install the optional channel: `python -m pip install -e ".[telegram]"`.',
                "2. Run `resume-builder agent telegram-setup`.",
                "3. Scan Telegram Web's QR code, create the bot with BotFather, and paste its "
                "token into the wizard's hidden prompt.",
                "4. Scan the one-use pairing QR and tap Start. The wizard validates the token, "
                "detects your private chat, and configures both allowlists automatically.",
                "5. Set `OPENROUTER_API_KEY` in the same environment.",
                "6. Validate with `resume-builder agent doctor --channel telegram`.",
                "7. Start it with `resume-builder agent serve --channel telegram`.",
                "   For an always-on container, use "
                "`docker compose --profile telegram up -d telegram-agent`.",
            ]
        )
    if "gmail" in integrations:
        lines.extend(
            [
                "",
                "#### Gmail application tracking",
                "",
                '1. Install the optional dependency: `python -m pip install -e ".[gmail]"`.',
                "2. Run the guided read-only OAuth setup: `resume-builder gmail connect`.",
                "3. Keep the downloaded Desktop OAuth file outside both repositories.",
                "4. Preview a scan with `resume-builder gmail scan` before using `--apply`.",
            ]
        )
    if "discord" in integrations:
        lines.extend(
            [
                "",
                "#### Discord notifications",
                "",
                "1. Create an incoming webhook for the private destination channel.",
                "2. Put it only in your shell environment: "
                '`export RESUME_BUILDER_DISCORD_WEBHOOK="..."`.',
                "3. Initialize automation if needed: "
                "`resume-builder automation init --timezone America/New_York`.",
                "4. Enable summarized notifications: `resume-builder automation configure "
                "--notifications discord --privacy summary`.",
                "5. Validate with `resume-builder automation doctor`.",
            ]
        )
    return "\n".join(lines)


def interactive_integration_setup(workspace: Path) -> str:
    """Ask which optional integrations to explain and return the selected guide."""
    print("\nOptional integrations can be configured now or later.")
    if input("Would you like to set up any integrations now? [y/N]: ").strip().casefold() not in {
        "y",
        "yes",
    }:
        return integration_setup_guide((), workspace)
    print("  1. Telegram — private conversations with the career agent")
    print("  2. Gmail — read-only application-status tracking")
    print("  3. Discord — one-way automation notifications")
    selection = input("Choose one or more, separated by commas [none]: ")
    return integration_setup_guide(parse_integration_choices(selection), workspace)
