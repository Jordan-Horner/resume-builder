"""Preview and apply safe, hash-pinned job preference changes."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, cast

import yaml
from pydantic import BaseModel, ConfigDict, Field

from job_puller.config import load_config, resolve_database_path

from .atomic import atomic_write_json, atomic_write_text
from .job_setup_defaults import PREFERENCES_PATH, SEARCH_CONFIG_PATH
from .jobs import (
    DEFAULT_OUTPUT,
    DEFAULT_REVIEW_OUTPUT,
    _database,
    _load_preferences,
    _prescreen,
    _shortlist,
    _terms,
)
from .workspace import discover_workspace

PROPOSAL_PATH = Path("build/job-search/preference-proposal.json")
BACKUP_PATH = Path("build/job-search/preferences-before-last-change.yml")
MUTABLE_FIELDS = {
    "accepted_work_modes",
    "desired_title_terms",
    "interest_terms",
    "excluded_title_terms",
    "senior_title_terms",
    "accepted_senior_role_terms",
    "unwanted_title_terms",
    "excluded_companies",
    "accepted_location_terms",
    "excluded_location_terms",
    "include_unknown_locations",
    "minimum_salary",
    "preferred_salary",
    "salary_currency",
    "salary_period",
    "screening_profile",
}
HIGH_RISK_FIELDS = {
    "accepted_work_modes",
    "excluded_title_terms",
    "senior_title_terms",
    "accepted_senior_role_terms",
    "excluded_companies",
    "accepted_location_terms",
    "excluded_location_terms",
    "include_unknown_locations",
    "minimum_salary",
    "screening_profile",
}


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PreferenceChangeRequest(StrictModel):
    """A deterministic edit request suitable for terminal or agent adapters."""

    schema_version: Literal[1] = 1
    set: dict[str, Any] = Field(default_factory=dict)
    add: dict[str, list[str]] = Field(default_factory=dict)
    remove: dict[str, list[str]] = Field(default_factory=dict)
    reason: str | None = Field(default=None, max_length=500)


class PreferenceProposal(StrictModel):
    schema_version: Literal[1] = 1
    kind: Literal["job_preference_proposal"] = "job_preference_proposal"
    created_at: str
    base_hash: str
    confirmation_hash: str
    risk: Literal["standard", "high"]
    changed_fields: list[str]
    request: PreferenceChangeRequest
    before: dict[str, Any]
    after: dict[str, Any]
    impact: dict[str, Any]


def _hash(value: object) -> str:
    rendered = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def _validate_fields(request: PreferenceChangeRequest) -> None:
    fields = set(request.set) | set(request.add) | set(request.remove)
    unknown = fields - MUTABLE_FIELDS
    if unknown:
        raise ValueError(f"preferences cannot change these fields: {', '.join(sorted(unknown))}")
    overlap = set(request.set) & (set(request.add) | set(request.remove))
    if overlap:
        raise ValueError(
            f"set cannot be combined with add/remove for: {', '.join(sorted(overlap))}"
        )
    if not fields:
        raise ValueError("preference proposal contains no changes")


def _apply_request(current: dict[str, Any], request: PreferenceChangeRequest) -> dict[str, Any]:
    _validate_fields(request)
    candidate = json.loads(json.dumps(current))
    for field, value in request.set.items():
        candidate[field] = value
    for field, additions in request.add.items():
        existing = candidate.get(field, [])
        if not isinstance(existing, list):
            raise ValueError(f"{field} is not a list preference")
        values = [str(value).strip() for value in additions if str(value).strip()]
        seen = {str(value).casefold() for value in existing}
        merged = list(existing)
        for value in values:
            if value.casefold() not in seen:
                merged.append(value)
                seen.add(value.casefold())
        candidate[field] = merged
    for field, removals in request.remove.items():
        existing = candidate.get(field, [])
        if not isinstance(existing, list):
            raise ValueError(f"{field} is not a list preference")
        rejected = {str(value).strip().casefold() for value in removals}
        candidate[field] = [value for value in existing if str(value).casefold() not in rejected]
    return _validated(candidate)


def _validated(candidate: dict[str, Any]) -> dict[str, Any]:
    """Reuse the authoritative preference validator without persisting a candidate."""
    descriptor, temporary_name = tempfile.mkstemp(
        prefix="resume-builder-preferences-", suffix=".yml"
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(yaml.safe_dump(candidate, sort_keys=False))
        return _load_preferences(temporary)
    finally:
        temporary.unlink(missing_ok=True)


def _resume_terms(root: Path, preferences: dict[str, Any]) -> set[str]:
    patterns = preferences.get("resume_globs") or [
        "resumes/baselines/*.md",
        "resumes/tailored/*.md",
    ]
    paths = sorted({path for pattern in patterns for path in root.glob(pattern) if path.is_file()})
    return _terms("\n".join(path.read_text(encoding="utf-8") for path in paths))


def _impact(root: Path, before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    config_path = root / SEARCH_CONFIG_PATH
    if not config_path.is_file():
        return {"inventory_jobs": 0, "changed_jobs": 0, "examples": [], "network_calls": 0}
    try:
        config = load_config(config_path)
        database_path = resolve_database_path(config_path, config.database_path)
        if not database_path.is_file():
            return {
                "inventory_jobs": 0,
                "changed_jobs": 0,
                "examples": [],
                "network_calls": 0,
            }
        jobs = _database(config_path).active_inventory()
    except (OSError, ValueError):
        return {"inventory_jobs": 0, "changed_jobs": 0, "examples": [], "network_calls": 0}
    before_terms = _resume_terms(root, before)
    after_terms = _resume_terms(root, after)
    changed: list[dict[str, Any]] = []
    for job in jobs:
        old = _prescreen(job, before, before_terms)
        new = _prescreen(job, after, after_terms)
        old_state = str(old["queue_state"])
        new_state = str(new["queue_state"])
        old_constraints = cast(dict[str, Any], old["constraints"])
        new_constraints = cast(dict[str, Any], new["constraints"])
        old_conflicts = old_constraints["hard_conflicts"]
        new_conflicts = new_constraints["hard_conflicts"]
        old_interest = old["interest"]
        new_interest = new["interest"]
        if (old_state, old_conflicts, old_interest) == (new_state, new_conflicts, new_interest):
            continue
        changed.append(
            {
                "id": str(job.get("id") or ""),
                "title": str(job.get("title") or ""),
                "company": str(job.get("company") or ""),
                "before": {"state": old_state, "hard_conflicts": old_conflicts},
                "after": {"state": new_state, "hard_conflicts": new_conflicts},
                "interest_changed": old_interest != new_interest,
            }
        )
    return {
        "inventory_jobs": len(jobs),
        "changed_jobs": len(changed),
        "examples": changed[:5],
        "jobs_deleted": 0,
        "network_calls": 0,
        "model_calls": 0,
    }


def propose(root: Path, request: PreferenceChangeRequest) -> PreferenceProposal:
    path = root / PREFERENCES_PATH
    before = _load_preferences(path)
    after = _apply_request(before, request)
    changed = sorted(field for field in MUTABLE_FIELDS if before.get(field) != after.get(field))
    if not changed:
        raise ValueError("the proposed preference change has no effect")
    base_hash = _hash(before)
    confirmation_hash = _hash({"base_hash": base_hash, "after": after})
    proposal = PreferenceProposal(
        created_at=datetime.now(UTC).isoformat(),
        base_hash=base_hash,
        confirmation_hash=confirmation_hash,
        risk="high" if HIGH_RISK_FIELDS & set(changed) else "standard",
        changed_fields=changed,
        request=request,
        before=before,
        after=after,
        impact=_impact(root, before, after),
    )
    atomic_write_json(root / PROPOSAL_PATH, proposal.model_dump(mode="json"))
    return proposal


def apply(root: Path, confirmation_hash: str) -> dict[str, Any]:
    proposal_path = root / PROPOSAL_PATH
    if not proposal_path.is_file():
        raise ValueError("no preference proposal is waiting for confirmation")
    proposal = PreferenceProposal.model_validate_json(proposal_path.read_text(encoding="utf-8"))
    if confirmation_hash != proposal.confirmation_hash:
        raise ValueError("confirmation hash does not match the proposed preference change")
    preferences_path = root / PREFERENCES_PATH
    current = _load_preferences(preferences_path)
    if _hash(current) != proposal.base_hash:
        raise ValueError("preferences changed after the preview; create a new proposal")
    _validated(proposal.after)
    atomic_write_text(root / BACKUP_PATH, yaml.safe_dump(current, sort_keys=False))
    atomic_write_text(preferences_path, yaml.safe_dump(proposal.after, sort_keys=False))
    proposal_path.unlink()
    refreshed = False
    refresh_error: str | None = None
    config_path = root / SEARCH_CONFIG_PATH
    if config_path.is_file():
        try:
            _shortlist(
                config_path,
                preferences_path,
                50,
                output_path=root / DEFAULT_OUTPUT,
                review_output_path=root / DEFAULT_REVIEW_OUTPUT,
            )
            refreshed = True
        except (OSError, ValueError) as exc:
            # The preference is still valid on a fresh workspace without an inventory.
            refresh_error = str(exc)
    return {
        "schema_version": 1,
        "kind": "job_preference_change_applied",
        "changed_fields": proposal.changed_fields,
        "local_shortlist_refreshed": refreshed,
        "provider_scan_started": False,
        "model_calls": 0,
        "backup": BACKUP_PATH.as_posix(),
        "local_shortlist_error": refresh_error,
    }


def _handoff_for_proposal(proposal: PreferenceProposal) -> dict[str, Any]:
    impact = proposal.impact
    examples = impact.get("examples", [])
    lines = [
        "### Review preference change",
        "",
        f"Changed settings: {', '.join(proposal.changed_fields)}",
        f"Local jobs affected: {impact.get('changed_jobs', 0)} of {impact.get('inventory_jobs', 0)}",
        "No jobs will be deleted. No provider scan or AI call was made.",
    ]
    if examples:
        lines.extend(["", "**Examples**", ""])
        for item in examples:
            transition = f"{item['before']['state']} → {item['after']['state']}"
            if item.get("interest_changed") and item["before"]["state"] == item["after"]["state"]:
                transition = "interest match changed"
            lines.append(f"- {item['title']} at {item['company']}: {transition}")
    lines.extend(
        [
            "",
            "Confirm with:",
            "",
            f"`resume-builder preferences apply --confirm {proposal.confirmation_hash}`",
        ]
    )
    return {
        **proposal.model_dump(mode="json"),
        "user_handoff": {
            "required": True,
            "action": "confirm-job-preference-change",
            "presentation_policy": {
                "mode": "exclusive-current-stage",
                "supersedes_prior_handoffs": True,
                "append_to_rendered_markdown": False,
            },
            "rendered_markdown": "\n".join(lines),
        },
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="resume-builder preferences",
        description="Review and safely change job-screening preferences.",
    )
    parser.add_argument("--workspace", type=Path)
    parser.add_argument("--json", action="store_true")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("show")
    preview = commands.add_parser("propose")
    preview.add_argument("request", help="JSON request or @path-to-json")
    confirm = commands.add_parser("apply")
    confirm.add_argument("--confirm", required=True)
    commands.add_parser("cancel")
    return parser


def _print(result: dict[str, Any], as_json: bool) -> None:
    if as_json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return
    handoff = result.get("user_handoff")
    if isinstance(handoff, dict) and isinstance(handoff.get("rendered_markdown"), str):
        print(handoff["rendered_markdown"])
    else:
        print(yaml.safe_dump(result, sort_keys=False).rstrip())


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    root = (args.workspace or discover_workspace() or Path.cwd()).expanduser().resolve()
    if args.command == "show":
        _print(_load_preferences(root / PREFERENCES_PATH), args.json)
        return 0
    if args.command == "cancel":
        (root / PROPOSAL_PATH).unlink(missing_ok=True)
        _print({"status": "canceled", "preferences_changed": False}, args.json)
        return 0
    if args.command == "propose":
        raw = (
            Path(args.request[1:]).read_text(encoding="utf-8")
            if args.request.startswith("@")
            else args.request
        )
        request = PreferenceChangeRequest.model_validate_json(raw)
        _print(_handoff_for_proposal(propose(root, request)), args.json)
        return 0
    result = apply(root, args.confirm)
    _print(result, args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
