"""Run the private career agent through provider and communication adapters."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from .agent_config import (
    DEFAULT_AGENT_CONFIG,
    AgentConfig,
    load_agent_config,
    render_default_agent_config,
)
from .agent_contracts import (
    CommunicationAdapter,
    InboundMessage,
    ModelAdapter,
    ModelRequest,
    OutboundMessage,
)
from .agent_openrouter import AgentProviderError, OpenRouterAdapter
from .agent_tools import build_read_only_tools
from .atomic import atomic_write_text
from .automation import default_state_path

AGENT_INSTRUCTIONS = """\
You are the private Resume Builder career agent. Be concise and candid.
Use tools for current local state instead of guessing. The available tools are read-only.
Never claim that you applied for a job, changed application state, sent email, or modified a
resume. Do not invent candidate facts. Explain when a requested action is not available yet.
Do not repeat private data unless it is necessary to answer the user's immediate request.
"""


class ConsoleAdapter(CommunicationAdapter):
    name = "console"

    def __init__(self, write: Callable[[str], None] = print):
        self.write = write

    def send(self, message: OutboundMessage) -> None:
        self.write(message.text)


class AgentService:
    """Coordinate one channel-neutral turn with a bounded model adapter."""

    def __init__(self, config: AgentConfig, model_adapter: ModelAdapter, state_path: Path):
        self.config = config
        self.model_adapter = model_adapter
        self.tools = build_read_only_tools(state_path)

    def handle(
        self,
        inbound: InboundMessage,
        channel: CommunicationAdapter,
        *,
        model_tier: str = "fast",
    ) -> None:
        model = getattr(self.config.models, model_tier)
        reply = self.model_adapter.run(
            ModelRequest(
                prompt=inbound.text,
                instructions=AGENT_INSTRUCTIONS,
                model=model,
                tools=self.tools,
            )
        )
        channel.send(OutboundMessage(inbound.conversation_id, reply.text))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="resume-builder agent")
    parser.add_argument("--config", type=Path, default=DEFAULT_AGENT_CONFIG)
    parser.add_argument("--state", type=Path, default=default_state_path())
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init", help="Create a private, secret-free agent configuration")
    commands.add_parser("doctor", help="Check dependencies, privacy settings, and credentials")
    ask = commands.add_parser("ask", help="Run one bounded console conversation turn")
    ask.add_argument("message")
    ask.add_argument("--model-tier", choices=("fast", "reasoning", "writing"), default="fast")
    return parser


def _dependency_available() -> bool:
    try:
        import pydantic_ai  # noqa: F401
    except ImportError:
        return False
    return True


def _doctor(config: AgentConfig) -> dict[str, object]:
    checks = {
        "provider_supported": config.provider == "openrouter",
        "agent_dependency": _dependency_available(),
        "api_key": bool(os.environ.get(config.api_key_env, "").strip()),
        "zero_data_retention": config.routing.zero_data_retention,
        "data_collection_denied": config.routing.data_collection == "deny",
        "bounded_requests": config.limits.max_requests <= 25,
        "bounded_turn_cost": config.limits.max_cost_per_turn_usd <= 10,
    }
    return {
        "healthy": all(checks.values()),
        "checks": checks,
        "models": {
            "fast": config.models.fast,
            "reasoning": config.models.reasoning,
            "writing": config.models.writing,
        },
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "init":
        if args.config.exists():
            print(f"Agent configuration already exists: {args.config}")
            return 0
        atomic_write_text(args.config, render_default_agent_config())
        print(f"Created {args.config}")
        print(
            f"Set {load_agent_config(args.config).api_key_env}, then run `resume-builder agent doctor`."
        )
        return 0
    try:
        config = load_agent_config(args.config)
        if args.command == "doctor":
            result = _doctor(config)
            print(json.dumps(result, indent=2, default=str))
            return 0 if result["healthy"] else 2
        service = AgentService(config, OpenRouterAdapter(config), args.state)
        service.handle(
            InboundMessage("local-user", "console", args.message),
            ConsoleAdapter(),
            model_tier=args.model_tier,
        )
        return 0
    except (AgentProviderError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
