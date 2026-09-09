"""Portal-native setup flows for optional Gmail and Telegram connections."""

from __future__ import annotations

import asyncio
import io
import secrets
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..agent_telegram_setup import (
    default_telegram_token_path,
    enable_private_telegram,
    require_external_token_path,
    validate_personal_bot,
    wait_for_pairing,
    write_telegram_token,
)
from ..assistant.state import AgentState, default_agent_state_path
from ..gmail_integration.orchestration import (
    GMAIL_READONLY_SCOPE,
    GMAIL_SETUP_STEPS,
    default_state_path,
    default_token_path,
    validate_client_configuration,
    write_gmail_token,
)

GMAIL_CLIENT_MAX_BYTES = 128 * 1024
TELEGRAM_PAIRING_TIMEOUT_SECONDS = 120
OAUTH_SESSION_TIMEOUT_SECONDS = 10 * 60


@dataclass
class GmailOAuthSession:
    flow: Any
    expires_at: float


@dataclass
class TelegramPairingSession:
    session_id: str
    username: str
    pairing_url: str
    expires_at: float
    status: str = "waiting"
    error: str = ""


class PortalIntegrationService:
    """Coordinate short-lived setup state without retaining browser-submitted secrets."""

    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace.expanduser().resolve()
        self._lock = threading.Lock()
        self._gmail_sessions: dict[str, GmailOAuthSession] = {}
        self._telegram_sessions: dict[str, TelegramPairingSession] = {}

    def gmail_setup(self) -> dict[str, Any]:
        return {
            "connected": default_token_path(default_state_path()).is_file(),
            "privacy": (
                "Read-only access is used to recognize application updates. "
                "Email content is processed temporarily and is not saved."
            ),
            "steps": [
                {
                    "number": number,
                    "total": len(GMAIL_SETUP_STEPS),
                    "title": step.title,
                    "instruction": step.instruction,
                    "link_label": step.link_label,
                    "link": step.link,
                }
                for number, step in enumerate(GMAIL_SETUP_STEPS, start=1)
            ],
        }

    def begin_gmail_oauth(
        self, filename: str, content: bytes, *, redirect_uri: str
    ) -> dict[str, str]:
        if Path(filename).suffix.casefold() != ".json":
            raise ValueError("Choose the JSON file downloaded from Google Cloud")
        if not content:
            raise ValueError("The Google OAuth file is empty")
        if len(content) > GMAIL_CLIENT_MAX_BYTES:
            raise ValueError("The Google OAuth file is unexpectedly large")
        client_config = validate_client_configuration(content)
        try:
            from google_auth_oauthlib.flow import Flow
        except ImportError as exc:
            raise ValueError(
                "Gmail connection support is unavailable in this installation"
            ) from exc

        state = secrets.token_urlsafe(32)
        flow = Flow.from_client_config(
            client_config,
            scopes=[GMAIL_READONLY_SCOPE],
            state=state,
        )
        flow.redirect_uri = redirect_uri
        authorization_url, returned_state = flow.authorization_url(
            access_type="offline",
            include_granted_scopes="true",
            prompt="consent",
        )
        if returned_state != state:
            raise ValueError("Google authorization could not start safely")
        with self._lock:
            self._remove_expired_gmail_sessions()
            self._gmail_sessions[state] = GmailOAuthSession(
                flow=flow,
                expires_at=time.monotonic() + OAUTH_SESSION_TIMEOUT_SECONDS,
            )
        return {"authorization_url": authorization_url}

    def complete_gmail_oauth(self, state: str, authorization_response: str) -> None:
        if not state:
            raise ValueError("Google did not return a valid authorization session")
        with self._lock:
            self._remove_expired_gmail_sessions()
            session = self._gmail_sessions.pop(state, None)
        if session is None:
            raise ValueError("This Gmail setup session expired. Start the connection again.")
        try:
            session.flow.fetch_token(authorization_response=authorization_response)
            credentials = session.flow.credentials
            from googleapiclient.discovery import build

            service = build("gmail", "v1", credentials=credentials, cache_discovery=False)
            service.users().getProfile(userId="me").execute()
        except Exception as exc:
            raise ValueError(
                "Google could not verify Gmail access. Start the connection again."
            ) from exc
        if not credentials.has_scopes([GMAIL_READONLY_SCOPE]):
            raise ValueError("Gmail read-only access was not granted")
        write_gmail_token(default_token_path(default_state_path()), credentials.to_json())

    def start_telegram_pairing(self, token: Any) -> dict[str, Any]:
        if not isinstance(token, str) or not token.strip():
            raise ValueError("Paste the bot token provided by BotFather")
        if len(token.strip()) > 512 or any(character.isspace() for character in token.strip()):
            raise ValueError("The Telegram bot token is not valid")
        try:
            username = asyncio.run(validate_personal_bot(token.strip()))
        except ValueError as exc:
            if "support is missing" in str(exc):
                raise ValueError(
                    "Telegram connection support is unavailable in this installation"
                ) from exc
            raise

        session_id = secrets.token_urlsafe(24)
        pairing_code = secrets.token_urlsafe(9)
        pairing_url = f"https://t.me/{username}?start={pairing_code}"
        session = TelegramPairingSession(
            session_id=session_id,
            username=username,
            pairing_url=pairing_url,
            expires_at=time.time() + TELEGRAM_PAIRING_TIMEOUT_SECONDS,
        )
        with self._lock:
            self._remove_expired_telegram_sessions()
            self._telegram_sessions[session_id] = session
        worker = threading.Thread(
            target=self._finish_telegram_pairing,
            args=(session_id, token.strip(), pairing_code),
            name=f"telegram-pairing-{session_id[:8]}",
            daemon=True,
        )
        worker.start()
        return self.telegram_pairing_status(session_id)

    def telegram_pairing_status(self, session_id: str) -> dict[str, Any]:
        with self._lock:
            session = self._telegram_sessions.get(session_id)
            if session is None:
                raise ValueError("This Telegram pairing session is no longer available")
            return {
                "session_id": session.session_id,
                "username": session.username,
                "pairing_url": session.pairing_url,
                "qr_url": f"/api/integrations/telegram/pairing/{session.session_id}/qr",
                "status": session.status,
                "error": session.error,
                "expires_at": datetime.fromtimestamp(session.expires_at, UTC).isoformat(),
            }

    def telegram_pairing_qr(self, session_id: str) -> bytes:
        with self._lock:
            session = self._telegram_sessions.get(session_id)
            if session is None:
                raise ValueError("This Telegram pairing session is no longer available")
            pairing_url = session.pairing_url
        try:
            import qrcode
            import qrcode.image.svg
        except ImportError as exc:
            raise ValueError("Telegram QR support is unavailable in this installation") from exc
        image = qrcode.make(
            pairing_url,
            image_factory=qrcode.image.svg.SvgPathImage,
            box_size=8,
            border=2,
        )
        output = io.BytesIO()
        image.save(output)
        return output.getvalue()

    def _finish_telegram_pairing(self, session_id: str, token: str, pairing_code: str) -> None:
        try:
            user_id, chat_id = asyncio.run(
                wait_for_pairing(
                    token,
                    pairing_code,
                    AgentState(default_agent_state_path()),
                    timeout_seconds=TELEGRAM_PAIRING_TIMEOUT_SECONDS,
                )
            )
            config_path = self.workspace / "agent/config.yml"
            destination = require_external_token_path(
                default_telegram_token_path(default_agent_state_path()),
                config_path,
            )
            write_telegram_token(destination, token)
            enable_private_telegram(config_path, user_id=user_id, chat_id=chat_id)
        except Exception as exc:
            with self._lock:
                session = self._telegram_sessions.get(session_id)
                if session is not None:
                    session.status = "failed"
                    session.error = self._telegram_error(str(exc))
            return
        with self._lock:
            session = self._telegram_sessions.get(session_id)
            if session is not None:
                session.status = "connected"

    @staticmethod
    def _telegram_error(message: str) -> str:
        if "timed out" in message:
            return "Pairing expired before Telegram received the Start message. Try again."
        if "already running" in message:
            return "Telegram is already active. Stop the existing connection before pairing again."
        return "Telegram could not finish pairing. Check the bot and try again."

    def _remove_expired_gmail_sessions(self) -> None:
        now = time.monotonic()
        expired = [
            key for key, session in self._gmail_sessions.items() if session.expires_at <= now
        ]
        for key in expired:
            self._gmail_sessions.pop(key, None)

    def _remove_expired_telegram_sessions(self) -> None:
        now = time.time()
        expired = [
            key
            for key, session in self._telegram_sessions.items()
            if session.expires_at + 300 <= now
        ]
        for key in expired:
            self._telegram_sessions.pop(key, None)
