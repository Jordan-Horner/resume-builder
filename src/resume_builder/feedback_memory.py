"""Capture conversational resume feedback and promote accepted guidance."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from .feedback_acceptance import (
    _acceptance_result,
    retire_feedback_rule,
)
from .feedback_acceptance import (
    accept_feedback as _accept_feedback,
)
from .feedback_recording import record_feedback
from .feedback_resolution import (
    KINDS,
    PROMOTIONS,
    RULE_ID,
    RULE_STATUSES,
    SCOPE_LEVELS,
    SESSION_ID,
    SESSION_STATUSES,
    STRENGTHS,
    SUBJECT_KEY,
    _read_json,
    _validate_rule,
    _validate_session,
    guidance_snapshot,
    manifest_guidance_freshness,
    resolve_for_plan,
)
from .synthesis import load_synthesis_plan

__all__ = [
    "KINDS",
    "PROMOTIONS",
    "RULE_ID",
    "RULE_STATUSES",
    "SCOPE_LEVELS",
    "SESSION_ID",
    "SESSION_STATUSES",
    "STRENGTHS",
    "SUBJECT_KEY",
    "accept_feedback",
    "guidance_snapshot",
    "main",
    "manifest_guidance_freshness",
    "record_feedback",
    "resolve_feedback",
    "resolve_for_plan",
    "retire_feedback_rule",
    "validate_feedback_memory",
]


def accept_feedback(
    project_root: Path,
    *,
    session_id: str | None = None,
    resume: Path | None = None,
    preview: Path | None = None,
) -> dict[str, object]:
    """Accept feedback through the compatibility facade's preview validator."""
    return _accept_feedback(
        project_root,
        session_id=session_id,
        resume=resume,
        preview=preview,
        acceptance_result_fn=_acceptance_result,
    )


def resolve_feedback(
    plan_path: Path,
    project_root: Path,
    vault_root: Path,
    *,
    include_open: bool = False,
) -> dict[str, object]:
    root = project_root.expanduser().resolve()
    plan = load_synthesis_plan(plan_path, root, vault_root.expanduser().resolve())
    rules = resolve_for_plan(plan, root, include_open=include_open)
    return {
        "valid": True,
        "plan": plan.source.relative_to(root).as_posix(),
        "resume": plan.resume.relative_to(root).as_posix(),
        "rules": rules,
        "count": len(rules),
    }


def validate_feedback_memory(project_root: Path) -> dict[str, object]:
    """Validate existing memory while treating missing directories as an empty install."""
    root = project_root.expanduser().resolve()
    errors: list[str] = []
    sessions = 0
    open_sessions = 0
    rules = 0
    active_rules = 0
    for path in sorted((root / "build" / "feedback").glob("*.json")):
        try:
            value = _read_json(path, "feedback session")
            _validate_session(value, path, root)
            sessions += 1
            open_sessions += value["status"] == "open"
        except ValueError as exc:
            errors.append(str(exc))
    for path in sorted((root / "editorial" / "rules").glob("*.json")):
        try:
            value = _read_json(path, "feedback rule")
            _validate_rule(value, path, root)
            rules += 1
            active_rules += value["status"] == "active"
        except ValueError as exc:
            errors.append(str(exc))
    return {
        "valid": not errors,
        "sessions": sessions,
        "open_sessions": open_sessions,
        "rules": rules,
        "active_rules": active_rules,
        "errors": errors,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="action", required=True)
    record_parser = subparsers.add_parser("record", help="Record or revise one feedback session")
    record_parser.add_argument("plan", type=Path)
    record_parser.add_argument("--session")
    accept_parser = subparsers.add_parser("accept", help="Promote accepted feedback")
    accept_parser.add_argument("session_id", nargs="?")
    accept_parser.add_argument("--resume", type=Path)
    accept_parser.add_argument("--preview", type=Path)
    resolve_parser = subparsers.add_parser("resolve", help="Resolve guidance for one plan")
    resolve_parser.add_argument("plan", type=Path)
    resolve_parser.add_argument("--vault-root", type=Path, default=Path("vault"))
    resolve_parser.add_argument("--include-open", action="store_true")
    retire_parser = subparsers.add_parser("retire", help="Retire one accepted feedback rule")
    retire_parser.add_argument("rule_id")
    retire_parser.add_argument("--reason", required=True)
    validate_parser = subparsers.add_parser(
        "validate", help="Validate sessions and accepted memory"
    )
    status_parser = subparsers.add_parser("status", help="Summarize sessions and accepted memory")
    for subparser in (
        record_parser,
        accept_parser,
        resolve_parser,
        retire_parser,
        validate_parser,
        status_parser,
    ):
        subparser.add_argument("--project-root", type=Path, default=Path("."))
    args = parser.parse_args(argv)
    root = args.project_root.expanduser().resolve()
    try:
        if args.action == "record":
            result = record_feedback(args.plan, root, session_id=args.session)
        elif args.action == "accept":
            result = accept_feedback(
                root,
                session_id=args.session_id,
                resume=args.resume,
                preview=args.preview,
            )
        elif args.action == "resolve":
            vault_root = args.vault_root
            if not vault_root.is_absolute():
                vault_root = root / vault_root
            result = resolve_feedback(
                args.plan,
                root,
                vault_root,
                include_open=args.include_open,
            )
        elif args.action == "retire":
            result = retire_feedback_rule(args.rule_id, args.reason, root)
        else:
            result = validate_feedback_memory(root)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": str(exc)}, indent=2), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    return 0 if result.get("valid") is True else 2


if __name__ == "__main__":
    raise SystemExit(main())
