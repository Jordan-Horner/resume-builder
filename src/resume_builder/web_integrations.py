"""Compatibility facade for portal integration setup."""

from .portal.integrations import (
    GMAIL_CLIENT_MAX_BYTES,
    OAUTH_SESSION_TIMEOUT_SECONDS,
    TELEGRAM_PAIRING_TIMEOUT_SECONDS,
    GmailOAuthSession,
    PortalIntegrationService,
    TelegramPairingSession,
)

__all__ = [
    "GMAIL_CLIENT_MAX_BYTES",
    "OAUTH_SESSION_TIMEOUT_SECONDS",
    "TELEGRAM_PAIRING_TIMEOUT_SECONDS",
    "GmailOAuthSession",
    "PortalIntegrationService",
    "TelegramPairingSession",
]
