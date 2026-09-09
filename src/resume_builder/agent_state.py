"""Compatibility facade for external assistant conversation state."""

from .assistant.state import AgentState, StoredUpdate, default_agent_state_path

__all__ = ["AgentState", "StoredUpdate", "default_agent_state_path"]
