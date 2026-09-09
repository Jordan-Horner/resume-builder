"""Compatibility facade for private Telegram assistant setup."""

from .assistant.telegram_setup import (
    BOTFATHER_URL,
    TELEGRAM_WEB_URL,
    default_telegram_token_path,
    enable_private_telegram,
    require_external_token_path,
    resolve_telegram_token,
    run_personal_telegram_setup,
    validate_personal_bot,
    wait_for_pairing,
    write_telegram_token,
)

__all__ = [
    "BOTFATHER_URL",
    "TELEGRAM_WEB_URL",
    "default_telegram_token_path",
    "enable_private_telegram",
    "require_external_token_path",
    "resolve_telegram_token",
    "run_personal_telegram_setup",
    "validate_personal_bot",
    "wait_for_pairing",
    "write_telegram_token",
]
