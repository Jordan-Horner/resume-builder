"""Private Telegram long-polling channel for the PydanticAI career agent."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from contextlib import suppress
from typing import Protocol

from .agent_config import AgentConfig, TelegramChannel
from .agent_contracts import InboundMessage, OutboundMessage
from .agent_state import AgentState, StoredUpdate
from .agent_telegram_setup import default_telegram_token_path, resolve_telegram_token

LOGGER = logging.getLogger(__name__)
TELEGRAM_MESSAGE_LIMIT = 4096
TELEGRAM_CHUNK_SIZE = 4000


def split_message(text: str, *, chunk_size: int = TELEGRAM_CHUNK_SIZE) -> tuple[str, ...]:
    """Split a reply on natural boundaries while remaining under Telegram's limit."""
    if not text:
        return ("I could not produce a response.",)
    chunks: list[str] = []
    remaining = text
    while len(remaining) > chunk_size:
        split_at = remaining.rfind("\n", 0, chunk_size + 1)
        if split_at < chunk_size // 2:
            split_at = remaining.rfind(" ", 0, chunk_size + 1)
        if split_at < chunk_size // 2:
            split_at = chunk_size
        chunks.append(remaining[:split_at].rstrip())
        remaining = remaining[split_at:].lstrip()
    if remaining:
        chunks.append(remaining)
    return tuple(chunks)


def validate_telegram_configuration(config: TelegramChannel) -> dict[str, bool]:
    """Return local, secret-free readiness checks for the Telegram channel."""
    try:
        import telegram  # noqa: F401
    except ImportError:
        dependency = False
    else:
        dependency = True
    return {
        "telegram_enabled": config.enabled,
        "telegram_dependency": dependency,
        "telegram_token": bool(resolve_telegram_token(config)),
        "telegram_user_allowlist": bool(config.allowed_user_ids),
        "telegram_chat_allowlist": bool(config.allowed_chat_ids),
    }


async def verify_telegram_identity(config: TelegramChannel) -> str:
    """Validate the configured bot token without exposing it."""
    try:
        from telegram import Bot
    except ImportError as exc:
        raise ValueError(
            'Telegram dependencies are missing; install with `pip install -e ".[telegram]"`'
        ) from exc
    token = resolve_telegram_token(config)
    if not token:
        raise ValueError(f"{config.token_env} is not configured")
    try:
        async with Bot(token) as bot:
            identity = await bot.get_me()
            webhook = await bot.get_webhook_info()
    except Exception as exc:
        raise ValueError(
            f"Telegram identity check failed safely ({exc.__class__.__name__})"
        ) from exc
    if webhook.url:
        raise ValueError("Telegram bot has a webhook configured; remove it before long polling")
    return f"@{identity.username}" if identity.username else str(identity.id)


async def discover_telegram_ids(
    config: TelegramChannel,
    state: AgentState,
) -> list[dict[str, object]]:
    """Read pending update identities without returning or logging message content."""
    try:
        from telegram import Bot
    except ImportError as exc:
        raise ValueError(
            'Telegram dependencies are missing; install with `pip install -e ".[telegram]"`'
        ) from exc
    token = resolve_telegram_token(config)
    if not token:
        raise ValueError(f"{config.token_env} is not configured")
    try:
        with state.telegram_service_lock():
            async with Bot(token) as bot:
                updates = await bot.get_updates(timeout=0, allowed_updates=["message"])
                if updates:
                    await bot.get_updates(
                        offset=max(update.update_id for update in updates) + 1,
                        timeout=0,
                    )
    except Exception as exc:
        raise ValueError(
            f"Telegram identity discovery failed safely ({exc.__class__.__name__})"
        ) from exc
    identities: dict[tuple[int, int], dict[str, object]] = {}
    for update in updates:
        user = update.effective_user
        chat = update.effective_chat
        if user is None or chat is None:
            continue
        identities[(user.id, chat.id)] = {
            "user_id": user.id,
            "chat_id": chat.id,
            "chat_type": chat.type,
        }
    return list(identities.values())


class AgentResponder(Protocol):
    """Narrow agent service surface required by the Telegram channel."""

    def respond(
        self,
        inbound: InboundMessage,
        *,
        channel_name: str,
        model_tier: str,
        history_max_turns: int,
        retain_history: bool,
    ) -> OutboundMessage: ...


class TelegramAdapter:
    """Translate allowlisted Telegram updates into channel-neutral agent turns."""

    name = "telegram"

    def __init__(
        self,
        config: AgentConfig,
        service: AgentResponder,
        state: AgentState,
        *,
        model_tier: str = "fast",
    ):
        self.config = config.channels.telegram
        self.service = service
        self.state = state
        self.model_tier = model_tier
        self._update_lock = asyncio.Lock()

    def authorized(self, *, user_id: int, chat_id: int, chat_type: str) -> bool:
        if not self.config.enabled:
            return False
        if self.config.private_chats_only and chat_type != "private":
            return False
        return user_id in self.config.allowed_user_ids and chat_id in self.config.allowed_chat_ids

    async def process_text(
        self,
        *,
        update_id: int,
        user_id: int,
        chat_id: int,
        chat_type: str,
        text: str,
        send: Callable[[str], Awaitable[None]],
    ) -> None:
        """Process one message with authorization, deduplication, and safe delivery."""
        if not self.authorized(user_id=user_id, chat_id=chat_id, chat_type=chat_type):
            LOGGER.warning("Ignored an unauthorized Telegram update")
            return
        normalized = text.strip()
        if not normalized:
            return
        async with self._update_lock:
            stored = self.state.get_update(update_id)
            if stored is None:
                self.state.start_update(
                    update_id,
                    user_id=user_id,
                    chat_id=chat_id,
                    chat_type=chat_type,
                    request_text=normalized,
                )
                stored = self.state.get_update(update_id)
            if stored is None or stored.status in {"sent", "failed"}:
                return
            try:
                await self._resume_update(stored, send)
            except Exception as exc:
                LOGGER.error(
                    "Telegram reply delivery remains queued safely (%s)",
                    exc.__class__.__name__,
                )

    async def _resume_update(
        self,
        stored: StoredUpdate,
        send: Callable[[str], Awaitable[None]],
    ) -> None:
        if (
            stored.user_id is None
            or stored.chat_id is None
            or stored.chat_type is None
            or stored.request_text is None
        ):
            self.state.mark_update_failed(stored.update_id, "IncompleteDurableUpdate")
            return
        if not self.authorized(
            user_id=stored.user_id,
            chat_id=stored.chat_id,
            chat_type=stored.chat_type,
        ):
            self.state.mark_update_failed(stored.update_id, "AuthorizationRevoked")
            return
        if stored.status == "processing":
            try:
                outbound = await asyncio.to_thread(
                    self.service.respond,
                    InboundMessage(
                        str(stored.user_id),
                        str(stored.chat_id),
                        stored.request_text,
                    ),
                    channel_name=self.name,
                    model_tier=self.model_tier,
                    history_max_turns=self.config.history_max_turns,
                    retain_history=False,
                )
            except Exception as exc:
                self.state.mark_update_failed(stored.update_id, exc.__class__.__name__)
                LOGGER.error("Telegram agent turn failed safely (%s)", exc.__class__.__name__)
                await send("The agent could not complete that request. Please try again.")
                return
            self.state.mark_update_ready(stored.update_id, outbound.text)
            refreshed = self.state.get_update(stored.update_id)
            if refreshed is None:
                return
            stored = refreshed
        if stored.status != "ready" or stored.response_text is None:
            return
        chunks = split_message(stored.response_text)
        for index, chunk in enumerate(chunks[stored.next_chunk :], start=stored.next_chunk):
            await send(chunk)
            self.state.mark_chunk_sent(stored.update_id, index + 1)
        self.state.complete_update(
            stored.update_id,
            max_turns=self.config.history_max_turns,
        )

    async def recover_pending(
        self,
        send: Callable[[int, str], Awaitable[None]],
    ) -> None:
        """Resume captured model turns and reply delivery without Telegram replay."""
        async with self._update_lock:
            self.state.prune_updates()
            for stored in self.state.pending_updates():
                if stored.chat_id is None:
                    self.state.mark_update_failed(stored.update_id, "MissingChatId")
                    continue
                chat_id = stored.chat_id

                async def send_to_chat(text: str, *, chat_id: int = chat_id) -> None:
                    await send(chat_id, text)

                try:
                    await self._resume_update(stored, send_to_chat)
                except Exception as exc:
                    LOGGER.error(
                        "Telegram pending delivery remains queued safely (%s)",
                        exc.__class__.__name__,
                    )

    async def forget(self, chat_id: int) -> int:
        async with self._update_lock:
            return self.state.clear_telegram_conversation(chat_id)


def run_telegram_service(adapter: TelegramAdapter) -> int:
    """Run the Telegram channel until the process receives a stop signal."""
    checks = validate_telegram_configuration(adapter.config)
    if not all(checks.values()):
        failed = ", ".join(name for name, passed in checks.items() if not passed)
        raise ValueError(f"Telegram channel is not ready: {failed}")
    try:
        from telegram import Update
        from telegram.constants import ChatAction
        from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters
    except ImportError as exc:
        raise ValueError(
            'Telegram dependencies are missing; install with `pip install -e ".[telegram]"`'
        ) from exc

    token = resolve_telegram_token(
        adapter.config,
        token_path=default_telegram_token_path(adapter.state.path),
    )
    recovery_task: asyncio.Task[None] | None = None

    async def recover(application: Application) -> None:
        async def send(chat_id: int, text: str) -> None:
            await application.bot.send_message(chat_id=chat_id, text=text)

        await adapter.recover_pending(send)

    async def recovery_loop(application: Application) -> None:
        while True:
            await recover(application)
            await asyncio.sleep(30)

    async def post_init(application: Application) -> None:
        nonlocal recovery_task
        await recover(application)
        recovery_task = asyncio.create_task(
            recovery_loop(application),
            name="telegram-durable-recovery",
        )

    async def post_shutdown(application: Application) -> None:
        del application
        if recovery_task is not None:
            recovery_task.cancel()
            with suppress(asyncio.CancelledError):
                await recovery_task

    try:
        application = (
            Application.builder()
            .token(token)
            .post_init(post_init)
            .post_shutdown(post_shutdown)
            .build()
        )
    except Exception as exc:
        raise ValueError(
            f"Telegram service initialization failed safely ({exc.__class__.__name__})"
        ) from exc

    async def authorized(update: Update) -> bool:
        user = update.effective_user
        chat = update.effective_chat
        return bool(
            user
            and chat
            and adapter.authorized(user_id=user.id, chat_id=chat.id, chat_type=chat.type)
        )

    async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        del context
        if not await authorized(update) or update.effective_message is None:
            return
        await update.effective_message.reply_text(
            "Resume Builder is connected. I can report automation status and help review "
            "new jobs. My available tools are read-only."
        )

    async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        del context
        if not await authorized(update) or update.effective_message is None:
            return
        await update.effective_message.reply_text(
            "Send a question normally. Use /new to clear this conversation, /forget to "
            "remove retained history, or /status to ask about the automation."
        )

    async def clear(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        del context
        if not await authorized(update) or update.effective_chat is None:
            return
        await adapter.forget(update.effective_chat.id)
        if update.effective_message is not None:
            await update.effective_message.reply_text("Conversation history cleared.")

    async def status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await authorized(update) or update.effective_message is None:
            return
        await handle_text(
            update,
            context,
            override="Report the current automation status concisely.",
        )

    async def handle_text(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE | None,
        *,
        override: str | None = None,
    ) -> None:
        user = update.effective_user
        chat = update.effective_chat
        message = update.effective_message
        if user is None or chat is None or message is None:
            return
        text = override if override is not None else message.text
        if text is None:
            return
        if context is not None:
            await context.bot.send_chat_action(chat_id=chat.id, action=ChatAction.TYPING)

        async def send(value: str) -> None:
            await message.reply_text(value)

        await adapter.process_text(
            update_id=update.update_id,
            user_id=user.id,
            chat_id=chat.id,
            chat_type=chat.type,
            text=text,
            send=send,
        )

    async def handle_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        del update
        error = context.error
        error_name = error.__class__.__name__ if error is not None else "UnknownError"
        LOGGER.error("Telegram update handling failed safely (%s)", error_name)

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("new", clear))
    application.add_handler(CommandHandler("forget", clear))
    application.add_handler(CommandHandler("status", status))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    application.add_error_handler(handle_error)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("telegram.request").setLevel(logging.WARNING)
    try:
        with adapter.state.telegram_service_lock():
            application.run_polling(allowed_updates=["message"], drop_pending_updates=False)
    except Exception as exc:
        raise ValueError(f"Telegram polling failed safely ({exc.__class__.__name__})") from exc
    return 0
