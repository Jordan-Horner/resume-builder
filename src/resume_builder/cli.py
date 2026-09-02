"""Command-line entry point for Resume Builder."""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Callable, Sequence

from . import (
    agent,
    applications,
    automation,
    compilation,
    directions,
    evaluations,
    feedback_memory,
    gmail_automation,
    job_matching,
    jobs,
    migration,
    minting,
    plans,
    previewing,
    project_report,
    rendering,
    review_records,
    schema_upgrade,
    source_import,
    synthesis,
    validation,
    verification,
    workspace,
)

Command = tuple[Callable[[Sequence[str] | None], int], str]
COMMANDS: dict[str, Command] = {
    "agent": (agent.main, "Talk to the private career agent through an adapter"),
    "init": (
        workspace.main,
        "Create a private Git workspace with an optional private GitHub backup",
    ),
    "workspace": (workspace.status_main, "Show the active private workspace and backup state"),
    "hydrate": (
        source_import.main,
        "Preview or apply source-document registration",
    ),
    "validate": (validation.main, "Validate vault structure and provenance"),
    "report": (project_report.main, "Show project readiness and the next action"),
    "migrate": (migration.main, "Migrate a legacy aggregate vault to the current schema"),
    "plan": (plans.main, "Validate, preview, or apply canonical vault writes"),
    "compile": (
        compilation.main,
        "Build canonical resume Markdown as validated review input",
    ),
    "verify": (
        verification.main,
        "Run cached resume checks and prepare frozen review inputs",
    ),
    "preview": (previewing.main, "Publish reviewed resume HTML for final approval"),
    "mint": (minting.main, "Mint a validated resume as an audited PDF"),
    "direction": (
        directions.main,
        "Validate role-shape profiles or audit directional resume coverage",
    ),
    "eval": (evaluations.main, "Validate or grade reproducible resume regression cases"),
    "feedback": (
        feedback_memory.main,
        "Capture conversational revisions and accepted editorial memory",
    ),
    "match": (job_matching.main, "Audit a resume against one captured job posting"),
    "jobs": (jobs.main, "Update, inspect, and prescreen the local job inventory"),
    "application": (
        applications.main,
        "Record applications, outcomes, and submitted answers",
    ),
    "automation": (
        automation.main,
        "Schedule job discovery, Gmail updates, and notifications",
    ),
    "gmail": (
        gmail_automation.main,
        "Detect application confirmations without retaining email content",
    ),
    "review": (review_records.main, "Manage career-professional prose review"),
    "render": (rendering.main, "Render an evidence-grounded resume as ATS-safe HTML"),
    "synthesis": (synthesis.main, "Validate a versioned resume synthesis plan"),
    "upgrade": (schema_upgrade.main, "Preview or apply a vault schema upgrade"),
}


def parser() -> argparse.ArgumentParser:
    """Build the top-level command parser."""
    command_parser = argparse.ArgumentParser(
        prog="resume-builder",
        description="Build and maintain a source-grounded, Git-first career vault.",
    )
    command_parser.add_argument("command", nargs="?", choices=COMMANDS)
    return command_parser


def main(argv: Sequence[str] | None = None) -> int:
    """Dispatch a subcommand without mutating process-global arguments."""
    arguments = list(sys.argv[1:] if argv is None else argv)
    if not arguments and sys.stdin.isatty() and sys.stdout.isatty():
        try:
            return workspace.main([])
        except KeyboardInterrupt:
            print("\nSetup canceled. No workspace changes were applied.", file=sys.stderr)
            return 130
    if not arguments or arguments[0] in {"-h", "--help"}:
        command_parser = parser()
        command_parser.print_help()
        print("\ncommands:")
        for name, (_, description) in COMMANDS.items():
            print(f"  {name:<10} {description}")
        return 0

    command = arguments[0]
    if command not in COMMANDS:
        parser().error(f"invalid command: {command}")

    handler, _ = COMMANDS[command]
    forwarded = arguments[1:]
    if command != "init":
        active_workspace = workspace.discover_workspace()
        if active_workspace is not None:
            os.chdir(active_workspace)
    if command == "report" and "--summary" not in forwarded:
        forwarded = [*forwarded, "--summary"]
    try:
        return handler(forwarded)
    except KeyboardInterrupt:
        print("\nCanceled.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
