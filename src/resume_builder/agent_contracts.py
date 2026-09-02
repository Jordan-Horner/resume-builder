"""Provider- and channel-neutral contracts for the private career agent."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class AgentTool:
    """One explicitly exposed application capability."""

    name: str
    description: str
    handler: Callable[..., object]
    mutates: bool = False
    requires_approval: bool = False


@dataclass(frozen=True)
class ModelRequest:
    """One model turn independent of a specific inference provider."""

    prompt: str
    instructions: str
    model: str
    tools: Sequence[AgentTool] = field(default_factory=tuple)


@dataclass(frozen=True)
class ModelReply:
    """Normalized model output and content-free usage metadata."""

    text: str
    model: str
    requests: int = 0
    tool_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: str | None = None


class ModelAdapter(Protocol):
    """Run model turns without exposing provider types to application code."""

    def run(self, request: ModelRequest) -> ModelReply: ...


@dataclass(frozen=True)
class InboundMessage:
    """Channel-neutral user input."""

    sender_id: str
    conversation_id: str
    text: str


@dataclass(frozen=True)
class OutboundMessage:
    """Channel-neutral agent response."""

    conversation_id: str
    text: str


class CommunicationAdapter(Protocol):
    """Deliver a response without coupling the agent to Telegram or WhatsApp."""

    name: str

    def send(self, message: OutboundMessage) -> None: ...
