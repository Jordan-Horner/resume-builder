"""Compatibility facade for private career-assistant configuration."""

from .assistant.config import (
    DEFAULT_AGENT_CONFIG,
    DEFAULT_FAST_MODEL,
    LEGACY_GENERATED_FAST_MODELS,
    AgentChannels,
    AgentConfig,
    AgentLimits,
    AgentModels,
    AgentRouting,
    TelegramChannel,
    load_agent_config,
    render_default_agent_config,
)

__all__ = [
    "DEFAULT_AGENT_CONFIG",
    "DEFAULT_FAST_MODEL",
    "LEGACY_GENERATED_FAST_MODELS",
    "AgentChannels",
    "AgentConfig",
    "AgentLimits",
    "AgentModels",
    "AgentRouting",
    "TelegramChannel",
    "load_agent_config",
    "render_default_agent_config",
]
