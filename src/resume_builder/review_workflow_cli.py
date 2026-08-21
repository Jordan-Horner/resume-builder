"""CLI registration and dispatch for the hybrid resume-review workflow."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from .language_review import (
    finalize_language_review,
    language_review_freshness,
    prepare_language_review,
)
from .layout import contained_path
from .review_policy import hybrid_review_route
from .synthesis import load_synthesis_plan

HYBRID_REVIEW_ACTIONS = frozenset(
    {"language-package", "language-finalize", "language-validate", "route"}
)


def add_hybrid_review_parsers(subparsers: Any) -> None:
    """Register the standalone language-review and fit-routing commands."""
    package = subparsers.add_parser(
        "language-package",
        help="Prepare only new or changed narrative blocks for independent language review",
    )
    package.add_argument("resume", type=Path)
    package.add_argument("--target", type=Path)
    package.add_argument("--project-root", type=Path, default=Path("."))

    finalize = subparsers.add_parser(
        "language-finalize",
        help="Finalize the standalone independent language review",
    )
    finalize.add_argument("decisions", type=Path)
    finalize.add_argument("--output", type=Path)
    finalize.add_argument("--project-root", type=Path, default=Path("."))

    validate = subparsers.add_parser(
        "language-validate",
        help="Validate freshness of a standalone language review",
    )
    validate.add_argument("record", type=Path)
    validate.add_argument("--resume", type=Path)
    validate.add_argument("--project-root", type=Path, default=Path("."))

    route = subparsers.add_parser(
        "route", help="Choose the hybrid language-only or deeper career-review path"
    )
    route.add_argument("resume", type=Path)
    route.add_argument("--synthesis-plan", type=Path)
    route.add_argument("--project-root", type=Path, default=Path("."))


def run_hybrid_review_action(
    args: argparse.Namespace, project_root: Path
) -> tuple[dict[str, Any], int]:
    """Run one registered hybrid-review command and return its result and exit code."""
    if args.action == "language-package":
        return prepare_language_review(args.resume, project_root, target=args.target), 0
    if args.action == "language-finalize":
        return finalize_language_review(args.decisions, project_root, output=args.output), 0
    if args.action == "language-validate":
        resume = (
            contained_path(project_root, args.resume.as_posix(), "language review resume")
            if args.resume is not None
            else None
        )
        record = contained_path(project_root, args.record.as_posix(), "language review record")
        reasons = language_review_freshness(record, project_root, resume)
        return {"valid": not reasons, "reasons": reasons}, 2 if reasons else 0
    if args.action == "route":
        resume = contained_path(project_root, args.resume.as_posix(), "review route resume")
        plan_argument = args.synthesis_plan or Path("resumes/plans") / f"{resume.stem}.yaml"
        plan = load_synthesis_plan(plan_argument, project_root, project_root / "vault")
        if plan.resume != resume:
            raise ValueError("review route synthesis plan targets a different resume")
        return {
            "valid": True,
            "resume": resume.relative_to(project_root).as_posix(),
            **hybrid_review_route(plan),
        }, 0
    raise ValueError(f"unsupported hybrid review action: {args.action}")
