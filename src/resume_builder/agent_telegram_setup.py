"""Guided, private setup for a user-owned Telegram bot."""

from __future__ import annotations

import asyncio
import getpass
import os
import secrets
import time
import webbrowser
from collections.abc import Callable
from pathlib import Path

import yaml

from .agent_config import TelegramChannel, render_default_agent_config
from .agent_state import AgentState, default_agent_state_path
from .atomic import atomic_write_text
from .workspace_state import discover_workspace

TELEGRAM_WEB_URL = "https://web.telegram.org/"
BOTFATHER_URL = "https://t.me/BotFather"


def default_telegram_token_path(state_path: Path | None = None) -> Path:
    """Return the external owner-only path used for the personal bot token."""
    override = os.environ.get("RESUME_BUILDER_TELEGRAM_TOKEN_FILE", "").strip()
    if override:
        return Path(override).expanduser()
    state = state_path or default_agent_state_path()
    return state.expanduser().parent / "telegram-bot-token"


def resolve_telegram_token(
    config: TelegramChannel,
    *,
    token_path: Path | None = None,
) -> str:
    """Resolve a token from the environment first, then the owner-only setup file."""
    environment_token = os.environ.get(config.token_env, "").strip()
    if environment_token:
        return environment_token
    path = token_path or default_telegram_token_path()
    try:
        return path.expanduser().read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return ""


def write_telegram_token(path: Path, token: str) -> None:
    """Persist a validated token outside Git with owner-only permissions."""
    clean = token.strip()
    if not clean:
        raise ValueError("Telegram bot token cannot be empty")
    destination = path.expanduser()
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = destination.with_name(f".{destination.name}.{os.getpid()}.tmp")
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(clean + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
        os.chmod(destination, 0o600)
    finally:
        temporary.unlink(missing_ok=True)


def require_external_token_path(path: Path, config_path: Path) -> Path:
    """Reject credential locations inside the engine or discovered private workspace."""
    destination = path.expanduser().resolve()
    roots = [Path(__file__).resolve().parents[2]]
    workspace = discover_workspace(config_path.expanduser().parent)
    if workspace is not None:
        roots.append(workspace.resolve())
    if config_path.parent.name == "agent":
        roots.append(config_path.expanduser().parent.parent.resolve())
    for root in roots:
        try:
            destination.relative_to(root)
        except ValueError:
            continue
        raise ValueError("Telegram bot token file must be outside Git repositories")
    return destination


def enable_private_telegram(config_path: Path, *, user_id: int, chat_id: int) -> None:
    """Enable one private Telegram identity in the secret-free agent configuration."""
    try:
        payload = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        payload = yaml.safe_load(render_default_agent_config())
    if not isinstance(payload, dict):
        raise ValueError("agent configuration must be a mapping")
    channels = payload.setdefault("channels", {})
    if not isinstance(channels, dict):
        raise ValueError("agent channels configuration must be a mapping")
    telegram = channels.setdefault("telegram", {})
    if not isinstance(telegram, dict):
        raise ValueError("Telegram channel configuration must be a mapping")
    telegram.update(
        {
            "enabled": True,
            "token_env": str(telegram.get("token_env", "RESUME_BUILDER_TELEGRAM_BOT_TOKEN")),
            "allowed_user_ids": [user_id],
            "allowed_chat_ids": [chat_id],
            "private_chats_only": True,
            "history_max_turns": int(telegram.get("history_max_turns", 20)),
        }
    )
    atomic_write_text(config_path, yaml.safe_dump(payload, sort_keys=False))


async def validate_personal_bot(token: str) -> str:
    """Validate a bot token and return its username without exposing the token."""
    try:
        from telegram import Bot
    except ImportError as exc:
        raise ValueError(
            'Telegram support is missing; install with `pip install -e ".[telegram]"`'
        ) from exc
    try:
        async with Bot(token.strip()) as bot:
            identity = await bot.get_me()
            webhook = await bot.get_webhook_info()
    except Exception as exc:
        raise ValueError(f"Telegram rejected the bot token ({exc.__class__.__name__})") from exc
    if webhook.url:
        raise ValueError("Telegram bot has a webhook configured; remove it before local polling")
    if not identity.username:
        raise ValueError("Telegram bot does not have a username")
    return str(identity.username)


async def wait_for_pairing(
    token: str,
    pairing_code: str,
    state: AgentState,
    *,
    timeout_seconds: int,
) -> tuple[int, int]:
    """Consume updates until the one-use code arrives in a private chat."""
    try:
        from telegram import Bot
    except ImportError as exc:
        raise ValueError(
            'Telegram support is missing; install with `pip install -e ".[telegram]"`'
        ) from exc
    deadline = time.monotonic() + timeout_seconds
    offset: int | None = None
    expected = {pairing_code, f"/start {pairing_code}"}
    try:
        with state.telegram_service_lock():
            async with Bot(token.strip()) as bot:
                while time.monotonic() < deadline:
                    remaining = max(1, int(deadline - time.monotonic()))
                    updates = await bot.get_updates(
                        offset=offset,
                        timeout=min(20, remaining),
                        allowed_updates=["message"],
                    )
                    for update in updates:
                        offset = update.update_id + 1
                        user = update.effective_user
                        chat = update.effective_chat
                        message = update.effective_message
                        if (
                            user is not None
                            and chat is not None
                            and message is not None
                            and chat.type == "private"
                            and message.text in expected
                        ):
                            await bot.get_updates(offset=update.update_id + 1, timeout=0)
                            return user.id, chat.id
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f"Telegram pairing failed safely ({exc.__class__.__name__})") from exc
    raise ValueError("Telegram pairing timed out; run the setup command again")


def _print_qr(url: str) -> None:
    try:
        import qrcode
    except ImportError as exc:
        raise ValueError(
            'Telegram QR support is missing; install with `pip install -e ".[telegram]"`'
        ) from exc
    code = qrcode.QRCode(border=1)
    code.add_data(url)
    code.make(fit=True)
    code.print_ascii(invert=True)


def run_personal_telegram_setup(
    *,
    config_path: Path,
    state_path: Path,
    token_path: Path | None = None,
    timeout_seconds: int = 120,
    open_browser: bool = True,
    read: Callable[[str], str] = input,
    read_secret: Callable[[str], str] = getpass.getpass,
) -> int:
    """Guide bot creation, securely capture its token, and pair one private chat."""
    if timeout_seconds < 10 or timeout_seconds > 600:
        raise ValueError("Telegram pairing timeout must be between 10 and 600 seconds")
    if not config_path.exists():
        atomic_write_text(config_path, render_default_agent_config())
        print(f"Created {config_path}")

    print("Personal Telegram setup")
    print("1. Telegram Web will show a QR code. Scan it with Telegram on your phone.")
    print("2. In Telegram Web, open BotFather and create your private bot with /newbot.")
    print("3. Copy the resulting bot token; it will be entered in a hidden prompt here.")
    print(f"Telegram Web: {TELEGRAM_WEB_URL}")
    print(f"BotFather: {BOTFATHER_URL}")
    if open_browser:
        webbrowser.open(TELEGRAM_WEB_URL)
    read("Press Enter after BotFather has created the bot: ")
    token = read_secret("Paste the bot token (hidden): ").strip()
    if not token:
        raise ValueError("Telegram bot token cannot be empty")
    username = asyncio.run(validate_personal_bot(token))
    destination = require_external_token_path(
        token_path or default_telegram_token_path(state_path),
        config_path,
    )
    write_telegram_token(destination, token)

    pairing_code = secrets.token_urlsafe(9)
    pairing_url = f"https://t.me/{username}?start={pairing_code}"
    print(f"\nVerified @{username}. Scan this one-use pairing QR code:")
    _print_qr(pairing_url)
    print(f"If scanning is unavailable, open: {pairing_url}")
    print("Tap Start in Telegram. Waiting for the matching private message...")
    user_id, chat_id = asyncio.run(
        wait_for_pairing(
            token,
            pairing_code,
            AgentState(state_path),
            timeout_seconds=timeout_seconds,
        )
    )
    enable_private_telegram(config_path, user_id=user_id, chat_id=chat_id)
    print(f"Connected @{username} to one private Telegram chat.")
    print(f"Token saved outside Git with owner-only access: {destination}")
    print("Next: set OPENROUTER_API_KEY, then run:")
    print("  resume-builder agent doctor --channel telegram")
    print("  resume-builder agent serve --channel telegram")
    return 0
