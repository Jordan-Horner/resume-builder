from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from . import __version__
from .boards import (
    SUPPORTED_PROVIDERS,
    discover_boards,
    load_or_empty_registry,
    merge_registries,
    write_board_registry,
)
from .config import InventoryConfig, load_config, resolve_database_path, resolve_project_path
from .database import InventoryDatabase
from .service import InventoryService


def _default_config_path() -> str:
    if configured := os.environ.get("JOB_PULLER_CONFIG"):
        return configured
    candidates = (
        Path.cwd() / "job-search" / "config" / "search.yml",
        Path.cwd() / "config" / "search.yml",
    )
    return str(next((path for path in candidates if path.exists()), candidates[0]))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="job-puller", description="Collect jobs into a private local inventory."
    )
    parser.add_argument("--version", action="version", version=f"job-puller {__version__}")
    parser.add_argument(
        "--config", default=_default_config_path(), help="Path to search configuration YAML"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    scrape = commands.add_parser("scrape", help="Run enabled providers and update inventory")
    scrape.add_argument(
        "--provider",
        action="append",
        choices=("linkedin", "indeed", *SUPPORTED_PROVIDERS),
        dest="scrape_providers",
        help="Run one provider type; repeat to select more than one",
    )
    config = commands.add_parser("config", help="Configuration operations")
    config.add_argument("action", choices=["validate"])
    stats = commands.add_parser("stats", help="Show inventory counts")
    stats.add_argument("--json", action="store_true", dest="as_json")
    commands.add_parser(
        "reconcile", help="Consolidate exact provider identities while retaining observations"
    )
    boards = commands.add_parser("boards", help="Discover and manage direct ATS boards")
    board_commands = boards.add_subparsers(dest="boards_action", required=True)
    discover = board_commands.add_parser(
        "discover", help="Find supported ATS boards in stored direct application links"
    )
    discover.add_argument("--output", default="config/boards.yml", help="Board registry YAML path")
    discover.add_argument(
        "--provider",
        action="append",
        choices=SUPPORTED_PROVIDERS,
        dest="board_providers",
        help="Limit discovery to one provider; repeat to select more than one",
    )
    check = board_commands.add_parser(
        "check", help="Test one ATS vendor's configured boards without updating inventory"
    )
    check.add_argument("--provider", required=True, choices=SUPPORTED_PROVIDERS)
    return parser


def _load(config_path: Path) -> tuple[InventoryConfig, InventoryDatabase]:
    config = load_config(config_path)
    database_path = resolve_database_path(config_path, config.database_path)
    database = InventoryDatabase(database_path, config.raw_payload_retention_days)
    database.migrate()
    return config, database


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    config_path = Path(args.config).expanduser()
    try:
        config, database = _load(config_path)
    except ValueError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"Startup error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    if args.command == "config":
        enabled = [
            name
            for name in type(config.providers).model_fields
            if getattr(config.providers, name).enabled
        ]
        print(f"Configuration valid: {config_path}")
        print(f"Enabled providers: {', '.join(enabled)}")
        print(f"Database: {database.path}")
        return 0

    if args.command == "stats":
        stats = database.stats()
        if args.as_json:
            print(json.dumps(stats, indent=2, sort_keys=True))
        else:
            for key, value in stats.items():
                print(f"{key.replace('_', ' ').title()}: {value}")
        return 0

    if args.command == "reconcile":
        merged = database.reconcile_provider_identities()
        print(f"Reconciled canonical jobs: {merged}")
        print(f"Observations retained: {database.stats()['observations']}")
        return 0

    if args.command == "scrape" and not config.enabled:
        print(
            "Job discovery setup is not active. Finish onboarding and activate a search plan.",
            file=sys.stderr,
        )
        return 2

    if args.command == "boards":
        if args.boards_action == "check":
            service = InventoryService(config, database)
            providers = service.ats_providers(args.provider, include_disabled=True)
            if not providers:
                print(f"No {args.provider} boards are configured.", file=sys.stderr)
                return 2
            failed = 0
            print(f"Checking {len(providers)} {args.provider} board(s)...")
            for provider in providers:
                result = provider.fetch(service.cutoff(provider.source_key))
                state = result.outcome.value.upper()
                print(
                    f"[{state}] {provider.source_key}: "
                    f"raw={result.metrics.get('raw_results', 0)} "
                    f"eligible={len(result.observations)}"
                )
                if result.error:
                    print(f"  {result.error}", file=sys.stderr)
                failed += int(result.outcome.value in {"failed", "blocked", "partial"})
            return 1 if failed else 0
        output_path = resolve_project_path(config_path, args.output)
        discovered, report = discover_boards(
            database.active_application_links(),
            providers=set(args.board_providers or SUPPORTED_PROVIDERS),
            timeout=config.request_timeout_seconds,
        )
        registry = merge_registries(load_or_empty_registry(output_path), discovered)
        write_board_registry(output_path, registry)
        aliases, canonicalized, merged = database.record_verified_redirects(
            report.verified_redirects
        )
        provider_counts = {
            name: len(getattr(discovered.providers, name)) for name in SUPPORTED_PROVIDERS
        }
        print(f"Board registry updated: {output_path}")
        print(
            f"Scanned {report.scanned_links} application links; "
            f"recognized {report.recognized_links} observations."
        )
        print(
            "Discovered boards: "
            + ", ".join(f"{name}={count}" for name, count in provider_counts.items())
        )
        print("New boards are disabled until reviewed and enabled in the registry.")
        print(
            f"Verified redirects: {aliases}; canonicalized={canonicalized}; merged_jobs={merged}."
        )
        if report.redirect_failures:
            print(f"Greenhouse redirect failures: {len(report.redirect_failures)}", file=sys.stderr)
            for failure in report.redirect_failures[:10]:
                print(f"  {failure}", file=sys.stderr)
        return 1 if report.redirect_failures else 0

    service = InventoryService(config, database)
    selected = set(args.scrape_providers) if args.scrape_providers else None
    providers = service.providers(selected)
    if not providers:
        print(
            "No runnable providers: enable JobSpy providers or configure at least one ATS board.",
            file=sys.stderr,
        )
        return 2
    print(f"Updating inventory with {len(providers)} provider source(s)...", flush=True)

    def report_provider_start(index: int, total: int, source_key: str) -> None:
        print(f"[{index}/{total}] Fetching {source_key}...", flush=True)

    summaries = service.scrape(selected, on_provider_start=report_provider_start)
    failed = 0
    for summary in summaries:
        state = summary.outcome.upper()
        print(
            f"[{state}] {summary.source_key}: fetched={summary.fetched} "
            f"new_observations={summary.inserted} updated_observations={summary.updated}"
        )
        if summary.metrics:
            print(
                "  filters: "
                f"raw={summary.metrics.get('raw_results', 0)} "
                f"invalid={summary.metrics.get('invalid', 0)} "
                f"title={summary.metrics.get('title_rejected', 0)} "
                f"mode_mismatch={summary.metrics.get('work_mode_mismatch', 0)} "
                f"stale={summary.metrics.get('freshness_rejected', 0)} "
                f"duplicates={summary.metrics.get('duplicates', 0)} "
                f"capped={summary.metrics.get('saturated_queries', 0)} "
                f"accepted={summary.metrics.get('accepted', 0)}"
            )
            if "qualified_cards" in summary.metrics:
                print(
                    "  linkedin: "
                    f"pages={summary.metrics.get('search_pages', 0)} "
                    f"scanned={summary.metrics.get('cards_scanned', 0)} "
                    f"qualified={summary.metrics.get('qualified_cards', 0)} "
                    f"targets={summary.metrics.get('candidate_target_reached', 0)} "
                    f"scan_limits={summary.metrics.get('scan_limit_reached', 0)} "
                    f"details={summary.metrics.get('detail_requests', 0)} "
                    f"cache_hits={summary.metrics.get('detail_cache_hits', 0)}"
                )
            rejected_titles = sorted(
                (
                    (key.removeprefix("rejected_title."), count)
                    for key, count in summary.metrics.items()
                    if key.startswith("rejected_title.")
                ),
                key=lambda item: (-item[1], item[0]),
            )
            if rejected_titles:
                print(
                    "  top rejected titles: "
                    + ", ".join(f"{title}={count}" for title, count in rejected_titles[:10])
                )
        if summary.error:
            print(f"  {summary.error}", file=sys.stderr)
        failed += int(summary.outcome in {"failed", "blocked", "partial"})
    stats = database.stats()
    print(
        f"Inventory: {stats['active_jobs']} active jobs, {stats['observations']} source observations"
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
