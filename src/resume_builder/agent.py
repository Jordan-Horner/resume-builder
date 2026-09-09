"""Compatibility facade for the private career-assistant runtime."""

import sys

from .assistant import runtime as _runtime

AGENT_INSTRUCTIONS = _runtime.AGENT_INSTRUCTIONS
AgentService = _runtime.AgentService
ConsoleAdapter = _runtime.ConsoleAdapter
main = _runtime.main

__all__ = ["AGENT_INSTRUCTIONS", "AgentService", "ConsoleAdapter", "main"]
_runtime.__all__ = __all__  # type: ignore[attr-defined]
sys.modules[__name__] = _runtime
