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
from .discovery_evidence import ResumeDocument, extract_query_expansion, extract_title_seed
from .discovery_portfolio import (
    TITLE_GENERATION_INSTRUCTIONS,
    build_cold_start_portfolio,
    generate_title_suggestions,
    load_cached_title_generation,
    title_generation_prompt,
)
from .job_screening import (
    SCREENING_INSTRUCTIONS,
    EligibilityStatus,
    ScreeningCache,
    ScreeningResult,
    deterministic_ineligible_result,
    screening_prompt,
)
from .jobs import DEFAULT_CONFIG as DEFAULT_JOBS_CONFIG
from .jobs import DEFAULT_PREFERENCES, get_job_screening_packet
from .screening_service import ScreeningService

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
    screen = commands.add_parser("screen", help="Run one structured, read-only job screen")
    screen.add_argument("job_id")
    screen.add_argument("--jobs-config", type=Path, default=DEFAULT_JOBS_CONFIG)
    screen.add_argument("--preferences", type=Path, default=DEFAULT_PREFERENCES)
    screen.add_argument("--model-tier", choices=("fast", "reasoning", "writing"), default="fast")
    screen.add_argument(
        "--preview-payload",
        action="store_true",
        help="Print exactly what would be sent without contacting the provider",
    )
    screen.add_argument(
        "--confirm-send-private-data",
        action="store_true",
        help="Explicitly allow this bounded packet to be sent to the configured provider",
    )
    screen.add_argument("--refresh", action="store_true", help="Ignore an unchanged cached screen")
    screen.add_argument("--json", action="store_true", help="Print the validated result as JSON")
    discovery = commands.add_parser(
        "discovery-plan",
        help="Create an editable cold-start search plan from one resume",
    )
    discovery.add_argument("--resume", type=Path, required=True)
    discovery.add_argument(
        "--output",
        type=Path,
        default=Path("build/job-search/cold-start-portfolio.json"),
    )
    discovery.add_argument("--model-tier", choices=("fast", "reasoning", "writing"), default="fast")
    mode = discovery.add_mutually_exclusive_group()
    mode.add_argument(
        "--preview-payload",
        action="store_true",
        help="Print exactly what would be sent without contacting the provider",
    )
    mode.add_argument(
        "--confirm-send-private-data",
        action="store_true",
        help="Explicitly allow the bounded resume packet to be sent to the provider",
    )
    mode.add_argument(
        "--local-only",
        action="store_true",
        help="Skip title generation and create a smaller historical/capability draft",
    )
    discovery.add_argument(
        "--generation-cache",
        type=Path,
        default=Path("build/job-search/title-generation-cache.json"),
    )
    discovery.add_argument(
        "--refresh",
        action="store_true",
        help="Ignore an unchanged generation cache and contact the provider again",
    )
    discovery.add_argument(
        "--force",
        action="store_true",
        help="Replace an existing editable portfolio",
    )
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


def _render_screen(result: ScreeningResult, *, cached: bool) -> str:
    lines = [
        f"{result.recommendation.value.replace('_', ' ').title()}: {result.job_id}",
        f"Eligibility: {result.eligibility.value}",
        f"Fit: {result.fit.value.replace('_', ' ')}",
        f"Confidence: {result.confidence.value}",
        f"Source: {'local cache' if cached else result.model}",
        "",
        result.reasoning_summary,
    ]
    if result.stretch_case:
        lines.extend(("", f"Why it may be worth the stretch: {result.stretch_case}"))
    violated = [item for item in result.constraints if item.state.value == "violated"]
    unknown = [item for item in result.constraints if item.state.value == "unknown"]
    if violated:
        lines.extend(("", "Confirmed conflicts:"))
        lines.extend(f"- {item.explanation}" for item in violated)
    if unknown:
        lines.extend(("", "Verify:"))
        lines.extend(f"- {item.explanation}" for item in unknown)
    if result.strengths:
        lines.extend(("", "Strengths:"))
        lines.extend(f"- {item}" for item in result.strengths)
    if result.gaps:
        lines.extend(("", "Gaps:"))
        lines.extend(f"- {item}" for item in result.gaps)
    return "\n".join(lines)


def _run_discovery_plan(args: argparse.Namespace) -> int:
    resume_path = args.resume.expanduser()
    document = ResumeDocument(
        source_id=resume_path.name,
        content=resume_path.read_text(encoding="utf-8"),
    )
    if args.refresh and (args.preview_payload or args.local_only):
        raise ValueError("--refresh can only be used with provider-backed title generation")
    if args.preview_payload:
        print(
            json.dumps(
                {
                    "instructions": TITLE_GENERATION_INSTRUCTIONS,
                    "prompt": title_generation_prompt(document),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    output_path = args.output.expanduser()
    if output_path.exists() and not args.force:
        raise ValueError(
            f"discovery portfolio already exists: {output_path}; use --force to replace it"
        )

    generation = None
    generation_source = "local only"
    if not args.local_only:
        config = load_agent_config(args.config)
        model = getattr(config.models, args.model_tier)
        cache_path = args.generation_cache.expanduser()
        generation = (
            None if args.refresh else load_cached_title_generation(cache_path, document, model)
        )
        if generation is None:
            if not args.confirm_send_private_data:
                raise ValueError(
                    "No unchanged title-generation cache exists. Preview with "
                    "--preview-payload, use --local-only, or rerun with "
                    "--confirm-send-private-data to contact the provider."
                )
            generation = generate_title_suggestions(
                document,
                OpenRouterAdapter(config),
                model=model,
            )
            atomic_write_text(cache_path, generation.model_dump_json(indent=2) + "\n")
            generation_source = "configured provider"
        else:
            generation_source = "unchanged local cache"

    portfolio = build_cold_start_portfolio(
        document,
        extract_title_seed([document]),
        extract_query_expansion(document),
        generation,
    )
    atomic_write_text(output_path, portfolio.model_dump_json(indent=2) + "\n")
    print(f"Created draft discovery portfolio: {output_path}")
    print(f"Queries: {len(portfolio.queries)} of {portfolio.query_budget}")
    print(f"Title generation: {generation_source}")
    print("Scheduled searches were not changed.")
    return 0


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
        if args.command == "discovery-plan":
            return _run_discovery_plan(args)
        config = load_agent_config(args.config)
        if args.command == "doctor":
            doctor_result = _doctor(config)
            print(json.dumps(doctor_result, indent=2, default=str))
            return 0 if doctor_result["healthy"] else 2
        if args.command == "screen":
            packet = get_job_screening_packet(
                args.job_id,
                config_path=args.jobs_config.expanduser(),
                preferences_path=args.preferences.expanduser(),
            )
            if args.preview_payload:
                print(
                    json.dumps(
                        {
                            "instructions": SCREENING_INSTRUCTIONS,
                            "prompt": screening_prompt(packet),
                        },
                        indent=2,
                        sort_keys=True,
                    )
                )
                return 0
            model = getattr(config.models, args.model_tier)
            cache = ScreeningCache(args.state.with_name("screening-cache.sqlite"))
            cached_result = None if args.refresh else cache.get(packet, model)
            if packet.eligibility == EligibilityStatus.INELIGIBLE:
                screen_result, cached = deterministic_ineligible_result(packet), False
            elif cached_result is not None:
                screen_result, cached = cached_result, True
            else:
                if not args.confirm_send_private_data:
                    raise ValueError(
                        "No unchanged cached screen exists. Preview with --preview-payload, then "
                        "rerun with --confirm-send-private-data to contact the provider."
                    )
                screen_result, cached = ScreeningService(OpenRouterAdapter(config), cache).screen(
                    packet, model=model, refresh=args.refresh
                )
            print(
                screen_result.model_dump_json(indent=2)
                if args.json
                else _render_screen(screen_result, cached=cached)
            )
            return 0
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
