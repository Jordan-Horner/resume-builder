from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from . import __version__
from .config import load_config, resolve_database_path
from .database import InventoryDatabase
from .service import InventoryService


def _default_config_path() -> str:
    if configured := os.environ.get("JOB_PULLER_CONFIG"):
        return configured
    local = Path.cwd() / "config" / "search.yml"
    if local.exists():
        return str(local)
    editable_project = Path(__file__).resolve().parents[2] / "config" / "search.yml"
    return str(editable_project)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="job-puller", description="Collect jobs into a private local inventory."
    )
    parser.add_argument("--version", action="version", version=f"job-puller {__version__}")
    parser.add_argument("--config", default=_default_config_path(), help="Path to search configuration YAML")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("scrape", help="Run all enabled providers and update inventory")
    config = commands.add_parser("config", help="Configuration operations")
    config.add_argument("action", choices=["validate"])
    stats = commands.add_parser("stats", help="Show inventory counts")
    stats.add_argument("--json", action="store_true", dest="as_json")
    return parser


def _load(config_path: Path):
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
            name for name in type(config.providers).model_fields if getattr(config.providers, name).enabled
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

    service = InventoryService(config, database)
    providers = service.providers()
    if not providers:
        print(
            "No runnable providers: enable JobSpy providers or configure at least one ATS board.",
            file=sys.stderr,
        )
        return 2
    print(f"Updating inventory with {len(providers)} provider source(s)...")
    summaries = service.scrape()
    failed = 0
    for summary in summaries:
        state = "EMPTY" if summary.suspicious_empty else "OK" if summary.success else "FAILED"
        print(
            f"[{state}] {summary.source_key}: fetched={summary.fetched} "
            f"new={summary.inserted} updated={summary.updated}"
        )
        if summary.error:
            print(f"  {summary.error}", file=sys.stderr)
        failed += int(not summary.success or summary.suspicious_empty)
    stats = database.stats()
    print(f"Inventory: {stats['active_jobs']} active jobs, {stats['observations']} source observations")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
