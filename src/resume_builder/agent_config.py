"""Strict, secret-free configuration for the private career agent."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import yaml

DEFAULT_AGENT_CONFIG = Path("agent/config.yml")


@dataclass(frozen=True)
class AgentModels:
    fast: str
    reasoning: str
    writing: str


@dataclass(frozen=True)
class AgentRouting:
    zero_data_retention: bool
    data_collection: str
    require_parameters: bool
    allow_fallbacks: bool
    providers: tuple[str, ...]


@dataclass(frozen=True)
class AgentLimits:
    max_requests: int
    max_tool_calls: int
    max_input_tokens: int
    max_output_tokens: int
    max_cost_per_turn_usd: Decimal


@dataclass(frozen=True)
class TelegramChannel:
    enabled: bool
    token_env: str
    allowed_user_ids: tuple[int, ...]
    allowed_chat_ids: tuple[int, ...]
    private_chats_only: bool
    history_max_turns: int


@dataclass(frozen=True)
class AgentChannels:
    telegram: TelegramChannel


@dataclass(frozen=True)
class AgentConfig:
    provider: str
    api_key_env: str
    models: AgentModels
    routing: AgentRouting
    limits: AgentLimits
    channels: AgentChannels


def _mapping(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a mapping")
    return value


def _strict_keys(payload: dict[str, Any], allowed: set[str], label: str) -> None:
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise ValueError(f"unknown {label} settings: {', '.join(unknown)}")


def _required_string(payload: dict[str, Any], key: str, label: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label}.{key} must be a non-empty string")
    return value.strip()


def _boolean(payload: dict[str, Any], key: str, default: bool) -> bool:
    value = payload.get(key, default)
    if not isinstance(value, bool):
        raise ValueError(f"{key} must be true or false")
    return value


def _positive_int(
    payload: dict[str, Any],
    key: str,
    default: int,
    maximum: int,
    *,
    section: str = "limits",
) -> int:
    value = payload.get(key, default)
    if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= maximum:
        raise ValueError(f"{section}.{key} must be an integer from 1 to {maximum}")
    return value


def _integer_list(value: object, label: str, *, positive: bool) -> tuple[int, ...]:
    if not isinstance(value, list) or not all(
        isinstance(item, int)
        and not isinstance(item, bool)
        and (item > 0 if positive else item != 0)
        for item in value
    ):
        qualifier = "positive " if positive else "non-zero "
        raise ValueError(f"{label} must be a list of {qualifier}integer IDs")
    return tuple(dict.fromkeys(value))


def load_agent_config(path: Path) -> AgentConfig:
    """Load an agent configuration without reading its API key."""
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(
            f"agent configuration not found: {path}; run `resume-builder agent init`"
        ) from exc
    except yaml.YAMLError as exc:
        raise ValueError(f"invalid agent YAML: {exc}") from exc
    payload = _mapping(raw, "agent configuration")
    _strict_keys(
        payload,
        {
            "schema_version",
            "provider",
            "api_key_env",
            "models",
            "routing",
            "limits",
            "channels",
        },
        "agent",
    )
    schema_version = payload.get("schema_version")
    if schema_version not in {1, 2}:
        raise ValueError("agent schema_version must be 1 or 2")
    provider = _required_string(payload, "provider", "agent")
    if provider != "openrouter":
        raise ValueError("agent.provider must currently be openrouter")
    api_key_env = _required_string(payload, "api_key_env", "agent")

    models = _mapping(payload.get("models"), "models")
    _strict_keys(models, {"fast", "reasoning", "writing"}, "models")
    parsed_models = AgentModels(
        fast=_required_string(models, "fast", "models"),
        reasoning=_required_string(models, "reasoning", "models"),
        writing=_required_string(models, "writing", "models"),
    )

    routing = _mapping(payload.get("routing", {}), "routing")
    _strict_keys(
        routing,
        {
            "zero_data_retention",
            "data_collection",
            "require_parameters",
            "allow_fallbacks",
            "providers",
        },
        "routing",
    )
    data_collection = routing.get("data_collection", "deny")
    if data_collection not in {"allow", "deny"}:
        raise ValueError("routing.data_collection must be allow or deny")
    raw_providers = routing.get("providers", [])
    if not isinstance(raw_providers, list) or not all(
        isinstance(item, str) and item for item in raw_providers
    ):
        raise ValueError("routing.providers must be a list of provider names")
    parsed_routing = AgentRouting(
        zero_data_retention=_boolean(routing, "zero_data_retention", True),
        data_collection=str(data_collection),
        require_parameters=_boolean(routing, "require_parameters", True),
        allow_fallbacks=_boolean(routing, "allow_fallbacks", True),
        providers=tuple(raw_providers),
    )

    limits = _mapping(payload.get("limits", {}), "limits")
    _strict_keys(
        limits,
        {
            "max_requests",
            "max_tool_calls",
            "max_input_tokens",
            "max_output_tokens",
            "max_cost_per_turn_usd",
        },
        "limits",
    )
    try:
        max_cost = Decimal(str(limits.get("max_cost_per_turn_usd", "0.25")))
    except InvalidOperation as exc:
        raise ValueError("limits.max_cost_per_turn_usd must be a decimal number") from exc
    if not Decimal("0") < max_cost <= Decimal("10"):
        raise ValueError("limits.max_cost_per_turn_usd must be greater than 0 and at most 10")
    parsed_limits = AgentLimits(
        max_requests=_positive_int(limits, "max_requests", 6, 25),
        max_tool_calls=_positive_int(limits, "max_tool_calls", 8, 50),
        max_input_tokens=_positive_int(limits, "max_input_tokens", 100_000, 2_000_000),
        max_output_tokens=_positive_int(limits, "max_output_tokens", 4_000, 100_000),
        max_cost_per_turn_usd=max_cost,
    )

    channels = _mapping(payload.get("channels", {}), "channels")
    _strict_keys(channels, {"telegram"}, "channels")
    telegram = _mapping(channels.get("telegram", {}), "channels.telegram")
    _strict_keys(
        telegram,
        {
            "enabled",
            "token_env",
            "allowed_user_ids",
            "allowed_chat_ids",
            "private_chats_only",
            "history_max_turns",
        },
        "channels.telegram",
    )
    parsed_telegram = TelegramChannel(
        enabled=_boolean(telegram, "enabled", False),
        token_env=str(telegram.get("token_env", "RESUME_BUILDER_TELEGRAM_BOT_TOKEN")).strip(),
        allowed_user_ids=_integer_list(
            telegram.get("allowed_user_ids", []),
            "channels.telegram.allowed_user_ids",
            positive=True,
        ),
        allowed_chat_ids=_integer_list(
            telegram.get("allowed_chat_ids", []),
            "channels.telegram.allowed_chat_ids",
            positive=False,
        ),
        private_chats_only=_boolean(telegram, "private_chats_only", True),
        history_max_turns=_positive_int(
            telegram,
            "history_max_turns",
            20,
            100,
            section="channels.telegram",
        ),
    )
    if not parsed_telegram.token_env:
        raise ValueError("channels.telegram.token_env must be a non-empty string")
    return AgentConfig(
        provider,
        api_key_env,
        parsed_models,
        parsed_routing,
        parsed_limits,
        AgentChannels(parsed_telegram),
    )


def render_default_agent_config() -> str:
    """Render conservative OpenRouter defaults without credentials."""
    return """\
schema_version: 2
provider: openrouter
api_key_env: OPENROUTER_API_KEY

models:
  fast: deepseek/deepseek-v4-flash
  reasoning: z-ai/glm-5.2
  writing: z-ai/glm-5.2

routing:
  zero_data_retention: true
  data_collection: deny
  require_parameters: true
  allow_fallbacks: true
  # Optionally pin OpenRouter serving providers after reviewing their policies.
  providers: []

limits:
  max_requests: 6
  max_tool_calls: 8
  max_input_tokens: 100000
  max_output_tokens: 4000
  max_cost_per_turn_usd: 0.25

channels:
  telegram:
    enabled: false
    token_env: RESUME_BUILDER_TELEGRAM_BOT_TOKEN
    allowed_user_ids: []
    allowed_chat_ids: []
    private_chats_only: true
    history_max_turns: 20
"""
