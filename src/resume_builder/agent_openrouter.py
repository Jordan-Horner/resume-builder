"""Compatibility facade for the assistant's OpenRouter adapter."""

from .assistant.openrouter import OPENROUTER_BASE_URL, AgentProviderError, OpenRouterAdapter

__all__ = ["OPENROUTER_BASE_URL", "AgentProviderError", "OpenRouterAdapter"]
