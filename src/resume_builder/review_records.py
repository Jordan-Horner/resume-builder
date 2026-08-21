"""Prepare, repair, and validate hash-pinned editorial resume reviews."""

from __future__ import annotations

import json
import sys
from collections.abc import Sequence
from pathlib import Path

from .evidence_questions import question_plan, resolve_question
from .language_review import (
    finalize_language_review,
    language_review_freshness,
    prepare_language_review,
)
from .layout import contained_path
from .review_approval import require_editorial_approval, review_freshness
from .review_blocks import (
    BLOCK_ID,
    NarrativeReviewBlock,
    narrative_block_inventory,
    narrative_block_inventory_from_markdown,
    narrative_blocks,
)
from .review_decisions import finalize_review_record
from .review_packages import build_review_package
from .review_repairs import apply_review_repairs
from .review_schema import (
    EDITORIAL_DECISIONS,
    EDITORIAL_SCOPE,
    EDITORIAL_STATUSES,
    EVIDENCE_STATUSES,
    FEEDBACK_DECISIONS,
    FEEDBACK_STATUSES,
    HIRING_READS,
    REVIEW_METHODS,
    ROUTES,
    SHA256,
    VERDICTS,
    EditorialBlock,
    FeedbackRuleDecision,
    ReviewInput,
    ReviewRecord,
    load_review_record,
    sha256_file,
    sha256_text,
)
from .review_workflow_cli import (
    HYBRID_REVIEW_ACTIONS,
    add_hybrid_review_parsers,
    run_hybrid_review_action,
)
from .selection_guard import (
    approve_proposal,
)
from .selection_review import (
    finalize_selection_review,
    selection_review_freshness,
)

__all__ = [
    "BLOCK_ID",
    "EDITORIAL_DECISIONS",
    "EDITORIAL_SCOPE",
    "EDITORIAL_STATUSES",
    "EVIDENCE_STATUSES",
    "FEEDBACK_DECISIONS",
    "FEEDBACK_STATUSES",
    "HIRING_READS",
    "REVIEW_METHODS",
    "ROUTES",
    "SHA256",
    "VERDICTS",
    "EditorialBlock",
    "FeedbackRuleDecision",
    "NarrativeReviewBlock",
    "ReviewInput",
    "ReviewRecord",
    "apply_review_repairs",
    "build_review_package",
    "finalize_language_review",
    "finalize_review_record",
    "language_review_freshness",
    "load_review_record",
    "main",
    "narrative_block_inventory",
    "narrative_block_inventory_from_markdown",
    "narrative_blocks",
    "prepare_language_review",
    "require_editorial_approval",
    "review_freshness",
    "sha256_file",
    "sha256_text",
]


def main(argv: Sequence[str] | None = None) -> int:
    """Manage career-professional review inputs, repairs, and records."""
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="action", required=True)
    blocks_parser = subparsers.add_parser("blocks", help="List hash-pinned narrative blocks")
    blocks_parser.add_argument("resume", type=Path)
    blocks_parser.add_argument("--project-root", type=Path, default=Path("."))
    package_parser = subparsers.add_parser(
        "package", help="Create the exact cold-read and evidence appendix for review"
    )
    package_parser.add_argument("resume", type=Path)
    package_parser.add_argument("--target", type=Path)
    package_parser.add_argument("--project-root", type=Path, default=Path("."))
    add_hybrid_review_parsers(subparsers)
    validate_parser = subparsers.add_parser("validate", help="Validate a review record")
    validate_parser.add_argument("record", type=Path)
    validate_parser.add_argument("--project-root", type=Path, default=Path("."))
    finalize_parser = subparsers.add_parser(
        "finalize", help="Create a validated review record from reviewer decisions"
    )
    finalize_parser.add_argument("decisions", type=Path)
    finalize_parser.add_argument("--output", type=Path)
    finalize_parser.add_argument("--project-root", type=Path, default=Path("."))
    repair_parser = subparsers.add_parser(
        "apply-repairs", help="Apply exact wording-only repairs from reviewer decisions"
    )
    repair_parser.add_argument("decisions", type=Path)
    repair_parser.add_argument("--project-root", type=Path, default=Path("."))
    strategy_parser = subparsers.add_parser(
        "strategy-approve", help="Approve one grouped structural-selection change"
    )
    strategy_parser.add_argument("proposal", type=Path)
    strategy_parser.add_argument("--reason", required=True)
    strategy_parser.add_argument("--project-root", type=Path, default=Path("."))
    selection_finalize_parser = subparsers.add_parser(
        "selection-finalize", help="Finalize the independent pre-language selection review"
    )
    selection_finalize_parser.add_argument("decisions", type=Path)
    selection_finalize_parser.add_argument("--project-root", type=Path, default=Path("."))
    selection_validate_parser = subparsers.add_parser(
        "selection-validate", help="Validate a finalized selection review"
    )
    selection_validate_parser.add_argument("record", type=Path)
    selection_validate_parser.add_argument("--project-root", type=Path, default=Path("."))
    question_parser = subparsers.add_parser(
        "question-plan", help="Validate or record one focused evidence-question round"
    )
    question_parser.add_argument("plan", type=Path)
    question_parser.add_argument("--apply", action="store_true")
    question_parser.add_argument("--project-root", type=Path, default=Path("."))
    resolve_parser = subparsers.add_parser(
        "question-resolve", help="Resolve one previously recorded evidence gap"
    )
    resolve_parser.add_argument("resume", type=Path)
    resolve_parser.add_argument("gap_key")
    resolve_parser.add_argument(
        "--status", required=True, choices=("answered", "unknown", "declined", "accept-gap")
    )
    resolve_parser.add_argument("--source-id")
    resolve_parser.add_argument("--project-root", type=Path, default=Path("."))
    args = parser.parse_args(argv)
    project_root = args.project_root.expanduser().resolve()
    try:
        if args.action == "blocks":
            resume = contained_path(project_root, args.resume.as_posix(), "resume")
            resumes_root = (project_root / "resumes").resolve()
            if not resume.is_relative_to(resumes_root) or not resume.is_file():
                raise ValueError("resume must name an existing file under resumes/")
            blocks = narrative_block_inventory(resume)
            result = {
                "valid": True,
                "resume": {
                    "path": resume.relative_to(project_root).as_posix(),
                    "sha256": sha256_file(resume),
                },
                "scope": EDITORIAL_SCOPE,
                "blocks": [
                    {
                        "id": block.id,
                        "sha256": sha256_text(block.text),
                        "text": block.text,
                        "context": block.context,
                        "advisories": list(block.advisories),
                    }
                    for block in blocks
                ],
            }
        elif args.action in HYBRID_REVIEW_ACTIONS:
            result, exit_code = run_hybrid_review_action(args, project_root)
            if exit_code:
                print(json.dumps(result, indent=2), file=sys.stderr)
                return exit_code
        elif args.action == "package":
            output = build_review_package(args.resume, project_root, target=args.target)
            cold_read = output.with_name(f"{output.name.removesuffix('.package.json')}.cold.json")
            decisions = output.with_name(
                f"{output.name.removesuffix('.package.json')}.decisions.json"
            )
            result = {
                "valid": True,
                "cold_read": {
                    "path": cold_read.relative_to(project_root).as_posix(),
                    "sha256": sha256_file(cold_read),
                },
                "package": output.relative_to(project_root).as_posix(),
                "sha256": sha256_file(output),
                "decisions": decisions.relative_to(project_root).as_posix(),
            }
        elif args.action == "finalize":
            result = finalize_review_record(
                args.decisions,
                project_root,
                output=args.output,
            )
        elif args.action == "apply-repairs":
            result = apply_review_repairs(args.decisions, project_root)
        elif args.action == "strategy-approve":
            result = approve_proposal(args.proposal, project_root, args.reason)
        elif args.action == "selection-finalize":
            result = finalize_selection_review(args.decisions, project_root)
        elif args.action == "selection-validate":
            selection_record_path = contained_path(
                project_root, args.record.as_posix(), "selection review"
            )
            reasons = selection_review_freshness(selection_record_path, project_root)
            result = {"valid": not reasons, "reasons": reasons}
            if reasons:
                print(json.dumps(result, indent=2), file=sys.stderr)
                return 2
        elif args.action == "question-plan":
            result = question_plan(args.plan, project_root, apply=args.apply)
        elif args.action == "question-resolve":
            result = resolve_question(
                project_root,
                resume=args.resume,
                gap_key=args.gap_key,
                status=args.status,
                source_id=args.source_id,
            )
        else:
            record = load_review_record(args.record, project_root)
            reasons = review_freshness(record)
            result = {
                "valid": not reasons,
                "version": record.version,
                "evidence_status": record.evidence_status or "legacy-not-separated",
                "language_status": record.editorial_status,
                "verdict": record.verdict,
                "hiring_read": record.hiring_read,
                "reviewer_method": record.reviewer_method,
                "blocks": len(record.editorial_blocks),
                "feedback_status": record.feedback_status,
                "feedback_rules": len(record.feedback_rules),
                "reasons": reasons,
            }
            if reasons:
                print(json.dumps(result, indent=2), file=sys.stderr)
                return 2
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": str(exc)}, indent=2), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    return 0
