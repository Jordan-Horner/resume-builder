"""Run the private career agent through provider and communication adapters."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Literal

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
    ModelReply,
    ModelRequest,
    OutboundMessage,
    StructuredModelReply,
    StructuredModelRequest,
)
from .agent_openrouter import AgentProviderError, OpenRouterAdapter
from .agent_tools import build_read_only_tools
from .atomic import atomic_write_text
from .automation import default_state_path
from .discovery_activation import (
    DiscoveryActivationRecord,
    activate_portfolio,
    edit_portfolio,
    load_portfolio,
    preview_activation,
    rollback_activation,
    rollback_confirmation,
    save_portfolio,
)
from .discovery_evidence import ResumeDocument, extract_query_expansion, extract_title_seed
from .discovery_portfolio import (
    TITLE_GENERATION_INSTRUCTIONS,
    ColdStartLane,
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
from .job_screening_queue import (
    DEFAULT_SCREENING_OUTPUT,
    build_screening_queue,
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


class _LocalOnlyModelAdapter(ModelAdapter):
    """Satisfy the batch boundary when provider use is deliberately disabled."""

    def run(self, request: ModelRequest) -> ModelReply:
        raise AssertionError("local-only screening must not make a model request")

    def run_structured(self, request: StructuredModelRequest) -> StructuredModelReply:
        raise AssertionError("local-only screening must not make a structured model request")


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
    screen_new = commands.add_parser(
        "screen-new", help="Build a complete, non-hiding screening queue for new jobs"
    )
    screen_new.add_argument("--input", type=Path, default=Path("job-search/new-jobs.json"))
    screen_new.add_argument("--output", type=Path, default=DEFAULT_SCREENING_OUTPUT)
    screen_new.add_argument("--jobs-config", type=Path, default=DEFAULT_JOBS_CONFIG)
    screen_new.add_argument("--preferences", type=Path, default=DEFAULT_PREFERENCES)
    screen_new.add_argument("--model-tier", choices=("fast", "reasoning"), default="fast")
    screen_new.add_argument("--max-provider-jobs", type=int)
    screen_new.add_argument(
        "--confirm-send-private-data",
        action="store_true",
        help="Allow bounded job and profile packets to be sent to the configured provider",
    )
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
    show = commands.add_parser("discovery-show", help="Validate and list a discovery portfolio")
    show.add_argument("--portfolio", type=Path, required=True)
    edit = commands.add_parser("discovery-edit", help="Edit one discovery query")
    edit.add_argument("--portfolio", type=Path, required=True)
    action = edit.add_mutually_exclusive_group(required=True)
    action.add_argument("--enable", metavar="QUERY_ID")
    action.add_argument("--disable", metavar="QUERY_ID")
    action.add_argument("--remove", metavar="QUERY_ID")
    action.add_argument("--add", metavar="QUERY")
    edit.add_argument("--lane", choices=tuple(item.value for item in ColdStartLane))
    activate = commands.add_parser(
        "discovery-activate", help="Preview or explicitly activate a reviewed portfolio"
    )
    activate.add_argument("--portfolio", type=Path, required=True)
    activate.add_argument("--search-config", type=Path, default=DEFAULT_JOBS_CONFIG)
    activate.add_argument("--backup", type=Path, required=True)
    activate.add_argument("--record", type=Path, required=True)
    activate.add_argument("--confirm", metavar="CONFIRMATION_HASH")
    rollback = commands.add_parser(
        "discovery-rollback", help="Preview or explicitly restore an activation backup"
    )
    rollback.add_argument("--record", type=Path, required=True)
    rollback.add_argument("--confirm", metavar="CONFIRMATION_HASH")
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


def _run_discovery_show(args: argparse.Namespace) -> int:
    portfolio = load_portfolio(args.portfolio.expanduser())
    for item in portfolio.queries:
        state = "enabled" if item.enabled else "disabled"
        print(f"{item.query_id}\t{state}\t{item.lane.value}\t{item.query}")
    print(f"Enabled: {sum(item.enabled for item in portfolio.queries)}")
    return 0


def _run_discovery_edit(args: argparse.Namespace) -> int:
    path = args.portfolio.expanduser()
    portfolio = load_portfolio(path)
    if args.add is not None:
        if args.lane is None:
            raise ValueError("--add requires --lane")
        operation: Literal["enable", "disable", "remove", "add"] = "add"
        query_id, query = None, args.add
        lane = ColdStartLane(args.lane)
    else:
        operation = "enable" if args.enable else "disable" if args.disable else "remove"
        query_id = args.enable or args.disable or args.remove
        query, lane = None, None
    updated = edit_portfolio(
        portfolio,
        operation=operation,
        query_id=query_id,
        query=query,
        lane=lane,
    )
    save_portfolio(path, updated)
    print(f"Updated discovery portfolio: {path}")
    return _run_discovery_show(args)


def _run_discovery_activate(args: argparse.Namespace) -> int:
    portfolio_path = args.portfolio.expanduser()
    config_path = args.search_config.expanduser()
    if args.confirm:
        record = activate_portfolio(
            portfolio_path,
            config_path,
            args.backup.expanduser(),
            args.record.expanduser(),
            args.confirm,
        )
        print(f"Activated {len(record.enabled_query_ids)} discovery queries.")
        print("No job scan was started. Container restart behavior was not changed.")
        return 0
    preview = preview_activation(
        load_portfolio(portfolio_path), config_path.read_text(encoding="utf-8")
    )
    print(preview.unified_diff or "No configuration changes.")
    print(f"Confirmation hash: {preview.confirmation_hash}")
    print("Rerun with --confirm <hash> to activate; no scan has been started.")
    return 0


def _run_discovery_rollback(args: argparse.Namespace) -> int:
    record_path = args.record.expanduser()
    record = DiscoveryActivationRecord.model_validate_json(record_path.read_text(encoding="utf-8"))
    expected = rollback_confirmation(record)
    if not args.confirm:
        print(f"Rollback confirmation hash: {expected}")
        print("Rerun with --confirm <hash> to restore the prior search configuration.")
        return 0
    rollback_activation(record_path, args.confirm)
    print(f"Restored search configuration: {record.config_path}")
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
        if args.command == "discovery-show":
            return _run_discovery_show(args)
        if args.command == "discovery-edit":
            return _run_discovery_edit(args)
        if args.command == "discovery-activate":
            return _run_discovery_activate(args)
        if args.command == "discovery-rollback":
            return _run_discovery_rollback(args)
        if args.command == "screen-new" and not args.confirm_send_private_data:
            try:
                local_config = load_agent_config(args.config)
            except ValueError:
                local_config = None
            maximum = args.max_provider_jobs or (
                local_config.limits.max_requests if local_config is not None else 6
            )
            if local_config is not None and maximum > local_config.limits.max_requests:
                raise ValueError(
                    "--max-provider-jobs cannot exceed agent limits.max_requests "
                    f"({local_config.limits.max_requests})"
                )
            model = (
                getattr(local_config.models, args.model_tier)
                if local_config is not None
                else "unconfigured"
            )
            summary = build_screening_queue(
                adapter=_LocalOnlyModelAdapter(),
                model=model,
                cache_path=args.state.with_name("screening-cache.sqlite"),
                input_path=args.input.expanduser(),
                output_path=args.output.expanduser(),
                config_path=args.jobs_config.expanduser(),
                preferences_path=args.preferences.expanduser(),
                max_provider_jobs=maximum,
                allow_provider=False,
            )
            print(
                json.dumps(
                    {
                        **summary.__dict__,
                        "cost_usd": str(summary.cost_usd),
                        "output": str(args.output.expanduser()),
                        "provider_authorized": False,
                        "agent_configured": local_config is not None,
                    },
                    indent=2,
                )
            )
            return 0
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
        if args.command == "screen-new":
            maximum = args.max_provider_jobs or config.limits.max_requests
            if maximum > config.limits.max_requests:
                raise ValueError(
                    "--max-provider-jobs cannot exceed agent limits.max_requests "
                    f"({config.limits.max_requests})"
                )
            summary = build_screening_queue(
                adapter=OpenRouterAdapter(config),
                model=getattr(config.models, args.model_tier),
                cache_path=args.state.with_name("screening-cache.sqlite"),
                input_path=args.input.expanduser(),
                output_path=args.output.expanduser(),
                config_path=args.jobs_config.expanduser(),
                preferences_path=args.preferences.expanduser(),
                max_provider_jobs=maximum,
                allow_provider=args.confirm_send_private_data,
            )
            print(
                json.dumps(
                    {
                        **summary.__dict__,
                        "cost_usd": str(summary.cost_usd),
                        "output": str(args.output.expanduser()),
                        "provider_authorized": args.confirm_send_private_data,
                    },
                    indent=2,
                )
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
