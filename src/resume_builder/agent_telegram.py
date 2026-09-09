"""Compatibility facade for the assistant's Telegram transport."""

from .assistant.telegram import (
    LOGGER,
    TELEGRAM_CHUNK_SIZE,
    TELEGRAM_MESSAGE_LIMIT,
    AgentResponder,
    TelegramAdapter,
    discover_telegram_ids,
    run_telegram_service,
    split_message,
    validate_telegram_configuration,
    verify_telegram_identity,
)

__all__ = [
    "LOGGER",
    "TELEGRAM_CHUNK_SIZE",
    "TELEGRAM_MESSAGE_LIMIT",
    "AgentResponder",
    "TelegramAdapter",
    "discover_telegram_ids",
    "run_telegram_service",
    "split_message",
    "validate_telegram_configuration",
    "verify_telegram_identity",
]
