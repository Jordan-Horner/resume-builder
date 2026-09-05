"""Resumable, non-scanning job-search setup inside the existing onboarding journey."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .atomic import atomic_write_text
from .discovery_activation import activate_portfolio, preview_activation
from .discovery_evidence import (
    DiscoveryEvidenceSet,
    HistoricalTitleState,
    ResumeDocument,
    evidence_set,
    extract_query_expansion_set,
    extract_title_seed,
)
from .discovery_portfolio import (
    MAX_TOTAL_QUERIES,
    ColdStartLane,
    ColdStartPortfolio,
    ColdStartQuery,
)
from .integrations import (
    integration_setup_guide,
    interactive_integration_setup,
    parse_integration_choices,
)
from .job_setup_defaults import (
    ACTIVATION_BACKUP_PATH,
    ACTIVATION_RECORD_PATH,
    PORTFOLIO_PATH,
    PREFERENCES_PATH,
    SEARCH_CONFIG_PATH,
    SETUP_PATH,
    scaffold_job_search,
)
from .jobs import _load_preferences
from .layout import VaultLayout
from .source_import import load_manifest
from .validation import validate_vault
from .workspace_state import WorkspaceError, discover_workspace

PRESENTATION_POLICY = {
    "mode": "exclusive-current-stage",
    "supersedes_prior_handoffs": True,
    "append_to_rendered_markdown": False,
}


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SetupStatus(StrEnum):
    IN_PROGRESS = "in_progress"
    READY_TO_ACTIVATE = "ready_to_activate"
    ACTIVE = "active"
    SKIPPED = "skipped"


class SetupStep(StrEnum):
    ROLES = "roles"
    ELIGIBILITY = "eligibility"
    LOCATION = "location"
    COMPENSATION = "compensation"
    REVIEW = "review"
    COMPLETE = "complete"


class RoleGroup(StrEnum):
    CURRENT_RECENT = "current_recent"
    RELATED = "related"
    EARLIER = "earlier"


class RoleIntent(StrEnum):
    SEARCH = "search"
    EXPLORE = "explore"
    DONT_SEED = "dont_seed"


class RoleProposal(StrictModel):
    role_id: str
    title: str = Field(min_length=2, max_length=150)
    group: RoleGroup
    intent: RoleIntent
    lane: ColdStartLane
    source_ids: list[str] = Field(min_length=1)
    evidence_role: str | None = None
    evidence_terms: list[str] = Field(default_factory=list)
    reason: str


class EligibilityAnswers(StrictModel):
    intended_country: str = Field(min_length=2, max_length=100)
    authorized_to_work: bool | None = None
    requires_sponsorship: bool | None = None
    held_clearances: list[str] = Field(default_factory=list, max_length=10)
    holds_clearance_or_public_trust: bool | None = None
    willing_to_obtain_clearance: bool | None = None

    @field_validator("intended_country")
    @classmethod
    def clean_country(cls, value: str) -> str:
        return value.strip()


class LocationAnswers(StrictModel):
    search_country: str | None = Field(default=None, min_length=2, max_length=100)
    accepted_work_modes: list[Literal["remote", "hybrid", "onsite"]] = Field(min_length=1)
    accepted_onsite_locations: list[str] = Field(default_factory=list, max_length=20)
    remote_location_terms: list[str] | None = Field(default=None, max_length=20)

    @model_validator(mode="after")
    def require_places_for_place_bound_work(self) -> LocationAnswers:
        if {"hybrid", "onsite"} & set(self.accepted_work_modes):
            if not any(item.strip() for item in self.accepted_onsite_locations):
                raise ValueError("hybrid or onsite work requires at least one acceptable location")
        return self


class CompensationAnswers(StrictModel):
    skipped: bool = False
    minimum: float | None = Field(default=None, ge=0)
    target: float | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    period: Literal["hour", "year"] | None = None

    @model_validator(mode="after")
    def validate_compensation(self) -> CompensationAnswers:
        if self.skipped:
            if any(
                value is not None
                for value in (self.minimum, self.target, self.currency, self.period)
            ):
                raise ValueError("skipped compensation cannot include compensation values")
            return self
        if self.minimum is None and self.target is None:
            raise ValueError("provide a minimum or target, or set skipped to true")
        if self.currency is None or self.period is None:
            raise ValueError("currency and period are required with compensation values")
        if self.minimum is not None and self.target is not None and self.target < self.minimum:
            raise ValueError("target compensation cannot be lower than minimum compensation")
        self.currency = self.currency.upper()
        return self


class JobSearchSetupState(StrictModel):
    schema_version: Literal[1] = 1
    kind: Literal["job_search_setup"] = "job_search_setup"
    session_id: str
    status: SetupStatus
    step: SetupStep
    created_at: str
    updated_at: str
    evidence_hash: str
    source_ids: list[str]
    roles: list[RoleProposal]
    eligibility: EligibilityAnswers | None = None
    location: LocationAnswers | None = None
    compensation: CompensationAnswers | None = None
    portfolio_path: str | None = None
    activation_record_path: str | None = None


class JobSearchSetupAnswer(StrictModel):
    schema_version: Literal[1] = 1
    kind: Literal["job_search_setup_answer"] = "job_search_setup_answer"
    session_id: str
    step: SetupStep
    answer: dict[str, Any]


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _count(report: dict[str, object], key: str) -> int:
    value = report.get(key, 0)
    return value if isinstance(value, int) else 0


def _workspace_root(root: Path | None = None) -> Path:
    if root is not None:
        return root.expanduser().resolve()
    discovered = discover_workspace()
    if discovered is None:
        raise WorkspaceError("no Resume Builder workspace is configured")
    return discovered


def _load_evidence(root: Path) -> DiscoveryEvidenceSet:
    layout = VaultLayout.load(root / "vault")
    report = validate_vault(layout.root, strict=False)
    if _count(report, "registered_sources") == 0:
        raise ValueError("add one or more resumes or career sources before job-search setup")
    manifest = load_manifest(layout)
    documents: list[ResumeDocument] = []
    for item in manifest["sources"]:
        snapshot = layout.snapshot_path(item["snapshot"])
        documents.append(
            ResumeDocument(source_id=str(item["id"]), content=snapshot.read_text(encoding="utf-8"))
        )
    return evidence_set(documents)


def _role_id(title: str, lane: ColdStartLane) -> str:
    identity = f"{lane.value}\n{title.casefold().strip()}"
    return f"role-{_hash_text(identity)[:12]}"


def _role_proposals(evidence: DiscoveryEvidenceSet) -> list[RoleProposal]:
    try:
        titles = extract_title_seed(evidence.documents)
    except ValueError:
        titles = None
    expansion = extract_query_expansion_set(evidence.documents)
    proposals: list[RoleProposal] = []
    for title in (titles.historical_titles if titles else [])[: MAX_TOTAL_QUERIES - 6]:
        current = title.state == HistoricalTitleState.ACTIVE
        proposals.append(
            RoleProposal(
                role_id=_role_id(title.query_title, ColdStartLane.HISTORICAL_TITLE),
                title=title.query_title,
                group=RoleGroup.CURRENT_RECENT if current else RoleGroup.EARLIER,
                intent=RoleIntent.SEARCH if current else RoleIntent.DONT_SEED,
                lane=ColdStartLane.HISTORICAL_TITLE,
                source_ids=title.source_ids,
                evidence_role=title.exact_title,
                reason=title.reason,
            )
        )
    for seed in expansion.capability_combinations:
        proposals.append(
            RoleProposal(
                role_id=_role_id(seed.query, ColdStartLane.CAPABILITY_COMBINATION),
                title=seed.query,
                group=RoleGroup.RELATED,
                intent=RoleIntent.EXPLORE,
                lane=ColdStartLane.CAPABILITY_COMBINATION,
                source_ids=[seed.source_id],
                evidence_role=seed.evidence_role,
                evidence_terms=seed.evidence_terms,
                reason="These capabilities appear together in one source evidence block.",
            )
        )
    return proposals


def load_state(root: Path) -> JobSearchSetupState | None:
    path = root / SETUP_PATH
    if not path.is_file():
        return None
    return JobSearchSetupState.model_validate_json(path.read_text(encoding="utf-8"))


def save_state(root: Path, state: JobSearchSetupState) -> None:
    atomic_write_text(root / SETUP_PATH, state.model_dump_json(indent=2) + "\n")


def start_setup(
    root: Path,
    *,
    restart: bool = False,
    additional_roles: Sequence[RoleProposal] = (),
) -> JobSearchSetupState:
    scaffold_job_search(root)
    existing = load_state(root)
    if existing is not None and existing.status == SetupStatus.ACTIVE and restart:
        raise ValueError("active job discovery cannot be restarted through onboarding")
    if existing is not None and existing.status != SetupStatus.SKIPPED and not restart:
        return existing
    config_path = root / SEARCH_CONFIG_PATH
    if config_path.is_file():
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        if isinstance(raw, dict) and raw.get("enabled", True):
            raise ValueError(
                "job discovery is already configured; onboarding will not replace it automatically"
            )
    evidence = _load_evidence(root)
    roles = _role_proposals(evidence)
    existing_titles = {item.title.casefold().strip() for item in roles}
    for role in additional_roles:
        if role.title.casefold().strip() not in existing_titles:
            roles.append(role)
            existing_titles.add(role.title.casefold().strip())
    timestamp = _now()
    state = JobSearchSetupState(
        session_id=str(uuid.uuid4()),
        status=SetupStatus.IN_PROGRESS,
        step=SetupStep.ROLES,
        created_at=timestamp,
        updated_at=timestamp,
        evidence_hash=evidence.corpus_hash,
        source_ids=[item.source_id for item in evidence.documents],
        roles=roles,
    )
    save_state(root, state)
    return state


def _update_roles(state: JobSearchSetupState, answer: dict[str, Any]) -> None:
    decisions = answer.get("decisions", {})
    additions = answer.get("add", [])
    if not isinstance(decisions, dict):
        raise ValueError(
            "roles answer decisions must map role IDs to search, explore, or dont_seed"
        )
    known = {item.role_id for item in state.roles}
    unknown = set(decisions) - known
    if unknown:
        raise ValueError(f"unknown role IDs: {', '.join(sorted(unknown))}")
    state.roles = [
        item.model_copy(
            update={"intent": RoleIntent(decisions.get(item.role_id, item.intent.value))}
        )
        for item in state.roles
    ]
    if not isinstance(additions, list):
        raise ValueError("roles answer add must be a list of titles")
    existing = {item.title.casefold().strip() for item in state.roles}
    for value in additions:
        if isinstance(value, str):
            title, intent = value.strip(), RoleIntent.SEARCH
        elif isinstance(value, dict) and isinstance(value.get("title"), str):
            title = value["title"].strip()
            intent = RoleIntent(value.get("intent", "search"))
        else:
            raise ValueError("each added role must contain a title")
        if len(title) < 2 or title.casefold() in existing:
            continue
        state.roles.append(
            RoleProposal(
                role_id=_role_id(title, ColdStartLane.ADJACENT_TITLE),
                title=title,
                group=RoleGroup.RELATED,
                intent=intent,
                lane=ColdStartLane.ADJACENT_TITLE,
                source_ids=["user-confirmed-setup"],
                reason="Added explicitly during job-search setup.",
            )
        )
        existing.add(title.casefold())
    if not any(item.intent in {RoleIntent.SEARCH, RoleIntent.EXPLORE} for item in state.roles):
        raise ValueError("keep at least one role as search or explore")
    selected_count = sum(
        item.intent in {RoleIntent.SEARCH, RoleIntent.EXPLORE} for item in state.roles
    )
    if selected_count > MAX_TOTAL_QUERIES:
        raise ValueError(f"search and explore can contain at most {MAX_TOTAL_QUERIES} roles")


def _next_step(step: SetupStep) -> SetupStep:
    order = [
        SetupStep.ROLES,
        SetupStep.ELIGIBILITY,
        SetupStep.LOCATION,
        SetupStep.COMPENSATION,
        SetupStep.REVIEW,
    ]
    return order[min(order.index(step) + 1, len(order) - 1)]


def apply_answer(root: Path, payload: JobSearchSetupAnswer) -> JobSearchSetupState:
    state = load_state(root)
    if state is None:
        raise ValueError("job-search setup has not started")
    if state.status != SetupStatus.IN_PROGRESS:
        raise ValueError(f"job-search setup is {state.status.value}, not accepting answers")
    if payload.session_id != state.session_id:
        raise ValueError("answer session ID does not match the current setup")
    if (
        payload.step == SetupStep.LOCATION
        and state.step == SetupStep.ELIGIBILITY
        and payload.answer.get("search_country")
    ):
        # The portal combines search country and location; the CLI retains eligibility.
        state.step = SetupStep.LOCATION
    if payload.step != state.step:
        raise ValueError(f"answer is for {payload.step.value}; current step is {state.step.value}")

    if state.step == SetupStep.ROLES:
        _update_roles(state, payload.answer)
    elif state.step == SetupStep.ELIGIBILITY:
        state.eligibility = EligibilityAnswers.model_validate(payload.answer)
    elif state.step == SetupStep.LOCATION:
        state.location = LocationAnswers.model_validate(payload.answer)
        if state.location.search_country is not None:
            country = EligibilityAnswers(intended_country=state.location.search_country)
            state.eligibility = (
                state.eligibility.model_copy(update={"intended_country": country.intended_country})
                if state.eligibility
                else country
            )
    elif state.step == SetupStep.COMPENSATION:
        state.compensation = CompensationAnswers.model_validate(payload.answer)
    elif state.step == SetupStep.REVIEW:
        action = payload.answer.get("action")
        if action == "skip":
            state.status = SetupStatus.SKIPPED
            state.step = SetupStep.COMPLETE
        elif action == "save":
            _compile_setup(root, state)
            state.status = SetupStatus.READY_TO_ACTIVATE
            state.step = SetupStep.COMPLETE
            state.portfolio_path = PORTFOLIO_PATH.as_posix()
        elif action == "change":
            section = payload.answer.get("section")
            try:
                state.step = SetupStep(str(section))
            except ValueError as exc:
                raise ValueError(
                    "change section must be roles, eligibility, location, or compensation"
                ) from exc
            if state.step in {SetupStep.REVIEW, SetupStep.COMPLETE}:
                raise ValueError(
                    "change section must be roles, eligibility, location, or compensation"
                )
        else:
            raise ValueError("review action must be save, change, or skip")
        state.updated_at = _now()
        save_state(root, state)
        return state
    else:  # pragma: no cover - exhaustive enum guard
        raise ValueError("setup is complete")

    state.step = _next_step(state.step)
    state.updated_at = _now()
    save_state(root, state)
    return state


def skip_setup(root: Path) -> JobSearchSetupState:
    state = load_state(root)
    if state is None:
        timestamp = _now()
        state = JobSearchSetupState(
            session_id=str(uuid.uuid4()),
            status=SetupStatus.SKIPPED,
            step=SetupStep.COMPLETE,
            created_at=timestamp,
            updated_at=timestamp,
            evidence_hash="not-started",
            source_ids=[],
            roles=[],
        )
    elif state.status != SetupStatus.ACTIVE:
        state.status = SetupStatus.SKIPPED
        state.step = SetupStep.COMPLETE
        state.updated_at = _now()
    else:
        raise ValueError(
            "active job discovery must be disabled through configuration, not onboarding"
        )
    save_state(root, state)
    return state


def _portfolio_from_state(state: JobSearchSetupState) -> ColdStartPortfolio:
    queries = [
        ColdStartQuery(
            query_id=item.role_id.replace("role-", f"{item.lane.value}-", 1),
            lane=item.lane,
            query=item.title,
            enabled=True,
            source_ids=item.source_ids,
            evidence_role=item.evidence_role,
            evidence_terms=item.evidence_terms,
            reason=item.reason,
        )
        for item in state.roles
        if item.intent in {RoleIntent.SEARCH, RoleIntent.EXPLORE}
    ]
    return ColdStartPortfolio(
        generated_at=_now(),
        resume_hash=state.evidence_hash,
        queries=queries,
    )


def _compile_setup(root: Path, state: JobSearchSetupState) -> None:
    if state.eligibility is None or state.location is None or state.compensation is None:
        raise ValueError("complete eligibility, location, and compensation before saving")
    if _load_evidence(root).corpus_hash != state.evidence_hash:
        raise ValueError(
            "career sources changed during setup; run `resume-builder onboard restart` to review updated roles"
        )
    scaffold_job_search(root)
    preferences_path = root / PREFERENCES_PATH
    preferences = _load_preferences(preferences_path)
    selected = [item.title for item in state.roles if item.intent == RoleIntent.SEARCH]
    explored = [item.title for item in state.roles if item.intent == RoleIntent.EXPLORE]
    preferences["desired_title_terms"] = selected
    preferences["interest_terms"] = explored
    preferences["accepted_work_modes"] = state.location.accepted_work_modes
    preferences["accepted_location_terms"] = [
        item.strip() for item in state.location.accepted_onsite_locations if item.strip()
    ]
    compensation = state.compensation
    preferences["minimum_salary"] = compensation.minimum
    preferences["preferred_salary"] = compensation.target
    preferences["salary_currency"] = compensation.currency
    preferences["salary_period"] = compensation.period
    profile = dict(preferences.get("screening_profile") or {})
    profile.update(
        {
            "intended_work_country": state.eligibility.intended_country,
            "authorized_to_work": state.eligibility.authorized_to_work,
            "requires_sponsorship": state.eligibility.requires_sponsorship,
            "held_clearances": state.eligibility.held_clearances,
            "holds_clearance_or_public_trust": state.eligibility.holds_clearance_or_public_trust,
            "willing_to_obtain_clearance": state.eligibility.willing_to_obtain_clearance,
            "remote_location_terms": state.location.remote_location_terms,
        }
    )
    preferences["screening_profile"] = profile
    _load_preferences_from_mapping(root, preferences)
    config_path = root / SEARCH_CONFIG_PATH
    search_config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(search_config, dict) or search_config.get("enabled", True):
        raise ValueError("refusing to replace an active job-search configuration")
    search = search_config.setdefault("search", {})
    if not isinstance(search, dict):
        raise ValueError("search configuration search section must be a mapping")
    search["location"] = state.eligibility.intended_country
    search["accepted_work_modes"] = state.location.accepted_work_modes
    search.pop("remote_only", None)
    portfolio = _portfolio_from_state(state)
    atomic_write_text(preferences_path, yaml.safe_dump(preferences, sort_keys=False))
    atomic_write_text(config_path, yaml.safe_dump(search_config, sort_keys=False))
    atomic_write_text(root / PORTFOLIO_PATH, portfolio.model_dump_json(indent=2) + "\n")


def _load_preferences_from_mapping(root: Path, preferences: dict[str, Any]) -> None:
    """Validate a prospective preference mapping through the canonical loader."""
    # The loader is intentionally file-based; use a private temporary sibling and remove it.
    target = root / "build" / "job-search" / ".preferences-validation.yml"
    atomic_write_text(target, yaml.safe_dump(preferences, sort_keys=False))
    try:
        _load_preferences(target)
    finally:
        target.unlink(missing_ok=True)


def _setup_summary(state: JobSearchSetupState) -> dict[str, Any]:
    return {
        "search": [item.title for item in state.roles if item.intent == RoleIntent.SEARCH],
        "explore": [item.title for item in state.roles if item.intent == RoleIntent.EXPLORE],
        "not_seeded": [item.title for item in state.roles if item.intent == RoleIntent.DONT_SEED],
        "eligibility": state.eligibility.model_dump(mode="json") if state.eligibility else None,
        "location": state.location.model_dump(mode="json") if state.location else None,
        "compensation": state.compensation.model_dump(mode="json") if state.compensation else None,
    }


def _markdown_for_state(
    state: JobSearchSetupState, *, evidence_update_available: bool = False
) -> str:
    if state.status == SetupStatus.SKIPPED:
        return "Job-search setup is skipped for now. Resume building remains available."
    if state.status == SetupStatus.READY_TO_ACTIVATE:
        message = (
            "### Job discovery is ready\n\n"
            "Your preferences and search suggestions are saved, but scanning is still off. "
            "Preview activation when you are ready."
        )
        if evidence_update_available:
            message += "\n\nYour career sources changed after this setup was created. Review the role-direction update before activation."
        return message
    if state.status == SetupStatus.ACTIVE:
        message = "### Job discovery is active\n\nYour confirmed search portfolio is configured."
        if evidence_update_available:
            message += "\n\nNew career evidence is available to review. Your active searches have not changed."
        return message
    if state.step == SetupStep.ROLES:
        groups = {
            RoleGroup.CURRENT_RECENT: "Current and recent",
            RoleGroup.RELATED: "Related possibilities",
            RoleGroup.EARLIER: "Earlier experience",
        }
        lines = [
            "### Choose what to search",
            "",
            "These suggestions come from your imported career sources. Earlier roles are not searched unless you choose them.",
        ]
        for group, label in groups.items():
            items = [item for item in state.roles if item.group == group]
            if not items:
                continue
            lines.extend(["", f"**{label}**", ""])
            labels = {
                RoleIntent.SEARCH: "search",
                RoleIntent.EXPLORE: "explore",
                RoleIntent.DONT_SEED: "not searched",
            }
            lines.extend(
                f"- `{item.role_id}` — {item.title} ({labels[item.intent]})" for item in items
            )
        lines.extend(["", "Reply with any changes and any additional roles you want to include."])
        return "\n".join(lines)
    if state.step == SetupStep.ELIGIBILITY:
        return (
            "### Eligibility\n\n"
            "Which country are you targeting, are you authorized to work there, will you need sponsorship, "
            "and do you hold or want to obtain a security clearance?"
        )
    if state.step == SetupStep.LOCATION:
        return (
            "### Work location\n\n"
            "Choose remote, hybrid, onsite, or a combination. Add locations only for hybrid or onsite work."
        )
    if state.step == SetupStep.COMPENSATION:
        return (
            "### Compensation (optional)\n\n"
            "Provide a minimum and/or target with currency and hourly or yearly period, or skip this step. "
            "Jobs with unknown pay will remain visible."
        )
    summary = _setup_summary(state)
    lines = ["### Review job-search setup", ""]
    lines.append(f"**Search:** {', '.join(summary['search']) or 'None'}")
    lines.append(f"**Explore:** {', '.join(summary['explore']) or 'None'}")
    if state.eligibility:
        lines.append(
            f"**Eligibility:** {state.eligibility.intended_country}; "
            f"sponsorship required: {state.eligibility.requires_sponsorship}"
        )
    if state.location:
        locations = ", ".join(state.location.accepted_onsite_locations) or "no onsite locations"
        lines.append(f"**Location:** {', '.join(state.location.accepted_work_modes)}; {locations}")
    if state.compensation:
        if state.compensation.skipped:
            lines.append("**Compensation:** Not specified")
        else:
            lines.append(
                f"**Compensation:** minimum {state.compensation.minimum or 'not set'}, "
                f"target {state.compensation.target or 'not set'} "
                f"{state.compensation.currency}/{state.compensation.period}"
            )
    lines.extend(["", "Save these settings, change a section, or skip job discovery."])
    return "\n".join(lines)


def _expected_answer(state: JobSearchSetupState) -> dict[str, Any] | None:
    if state.status != SetupStatus.IN_PROGRESS:
        return None
    examples: dict[SetupStep, dict[str, Any]] = {
        SetupStep.ROLES: {"decisions": {"role-id": "search|explore|dont_seed"}, "add": []},
        SetupStep.ELIGIBILITY: {
            "intended_country": "country",
            "authorized_to_work": None,
            "requires_sponsorship": None,
            "held_clearances": [],
            "willing_to_obtain_clearance": None,
        },
        SetupStep.LOCATION: {
            "accepted_work_modes": ["remote"],
            "accepted_onsite_locations": [],
            "remote_location_terms": None,
        },
        SetupStep.COMPENSATION: {"skipped": True},
        SetupStep.REVIEW: {"action": "save|change|skip", "section": None},
    }
    return {
        "schema_version": 1,
        "kind": "job_search_setup_answer",
        "session_id": state.session_id,
        "step": state.step.value,
        "answer": examples[state.step],
    }


def structured_output(
    state: JobSearchSetupState, *, evidence_update_available: bool = False
) -> dict[str, Any]:
    steps = 5
    completed = {
        SetupStep.ROLES: 0,
        SetupStep.ELIGIBILITY: 1,
        SetupStep.LOCATION: 2,
        SetupStep.COMPENSATION: 3,
        SetupStep.REVIEW: 4,
        SetupStep.COMPLETE: 5,
    }[state.step]
    markdown = _markdown_for_state(state, evidence_update_available=evidence_update_available)
    return {
        "schema_version": 1,
        "kind": "job_search_setup",
        "session_id": state.session_id,
        "status": state.status.value,
        "progress": {"completed": completed, "total": steps},
        "step": state.step.value,
        "draft": _setup_summary(state),
        "evidence_update_available": evidence_update_available,
        "expected_answer": _expected_answer(state),
        "actions": (
            (
                ["preview_activation", "skip", "review_evidence_update"]
                if evidence_update_available
                else ["preview_activation", "skip"]
            )
            if state.status == SetupStatus.READY_TO_ACTIVATE
            else (["review_evidence_update"] if evidence_update_available else [])
            if state.status == SetupStatus.ACTIVE
            else ["answer", "skip"]
            if state.status == SetupStatus.IN_PROGRESS
            else ["start"]
            if state.status == SetupStatus.SKIPPED
            else []
        ),
        "user_handoff": {
            "required": True,
            "action": "present-job-search-setup",
            "presentation_policy": PRESENTATION_POLICY,
            "rendered_markdown": markdown,
        },
    }


def onboarding_status(root: Path) -> dict[str, Any]:
    state = load_state(root)
    if state is not None:
        evidence_changed = False
        if state.status in {SetupStatus.READY_TO_ACTIVATE, SetupStatus.ACTIVE}:
            try:
                evidence_changed = _load_evidence(root).corpus_hash != state.evidence_hash
            except (OSError, ValueError):
                evidence_changed = False
        return structured_output(state, evidence_update_available=evidence_changed)
    config_path = root / SEARCH_CONFIG_PATH
    if config_path.is_file():
        existing_config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        if isinstance(existing_config, dict) and existing_config.get("enabled", True):
            markdown = (
                "### Job discovery is already configured\n\n"
                "The existing search configuration was preserved. Onboarding will not replace it automatically."
            )
            return {
                "schema_version": 1,
                "kind": "unified_onboarding",
                "status": "job_search_active",
                "actions": [],
                "user_handoff": {
                    "required": True,
                    "action": "present-onboarding",
                    "presentation_policy": PRESENTATION_POLICY,
                    "rendered_markdown": markdown,
                },
            }
    report = validate_vault(root / "vault", strict=False)
    if _count(report, "registered_sources") == 0:
        markdown = (
            "### Add your career information\n\n"
            "Attach one or more resumes, provide a folder, a LinkedIn export, or career notes. "
            "Job-search setup will use the combined evidence after hydration."
        )
        stage = "needs_sources"
    elif _count(report, "facts") == 0:
        markdown = (
            "### Finish career-vault hydration\n\n"
            "Your sources are registered. Review and save the canonical career facts before setting up job discovery."
        )
        stage = "needs_hydration"
    else:
        markdown = (
            "### Resume Builder is ready\n\n"
            "You can build resumes now, or optionally set up job discovery from all hydrated career sources."
        )
        stage = "job_search_optional"
    return {
        "schema_version": 1,
        "kind": "unified_onboarding",
        "status": stage,
        "actions": ["start_job_search", "skip_job_search"]
        if stage == "job_search_optional"
        else [],
        "user_handoff": {
            "required": True,
            "action": "present-onboarding",
            "presentation_policy": PRESENTATION_POLICY,
            "rendered_markdown": markdown,
        },
    }


def activation_preview(root: Path) -> dict[str, Any]:
    state = load_state(root)
    if state is None or state.status != SetupStatus.READY_TO_ACTIVATE:
        raise ValueError("finish and save job-search setup before activation")
    preview = preview_activation(
        ColdStartPortfolio.model_validate_json((root / PORTFOLIO_PATH).read_text(encoding="utf-8")),
        (root / SEARCH_CONFIG_PATH).read_text(encoding="utf-8"),
    )
    return {
        "schema_version": 1,
        "kind": "job_search_activation_preview",
        "confirmation_hash": preview.confirmation_hash,
        "enabled_queries": len(preview.enabled_query_ids),
        "diff": preview.unified_diff,
        "scan_started": False,
        "user_handoff": {
            "required": True,
            "action": "confirm-job-search-activation",
            "presentation_policy": PRESENTATION_POLICY,
            "rendered_markdown": (
                f"### Ready to activate {len(preview.enabled_query_ids)} searches\n\n"
                "No scan has started. Confirm the activation hash to enable these searches on the next scheduled run.\n\n"
                f"`{preview.confirmation_hash}`"
            ),
        },
    }


def evidence_update_preview(root: Path) -> dict[str, Any]:
    state = load_state(root)
    if state is None or state.status not in {
        SetupStatus.READY_TO_ACTIVATE,
        SetupStatus.ACTIVE,
    }:
        raise ValueError("save job-search setup before reviewing source updates")
    evidence = _load_evidence(root)
    proposed = _role_proposals(evidence)
    prior = {item.title.casefold(): item for item in state.roles}
    current = {item.title.casefold(): item for item in proposed}
    added = [item for key, item in current.items() if key not in prior]
    removed = [
        item
        for key, item in prior.items()
        if key not in current and "user-confirmed-setup" not in item.source_ids
    ]
    if evidence.corpus_hash == state.evidence_hash:
        summary = "Your registered career evidence has not changed since job-search setup."
    elif not added and not removed:
        summary = "Your source snapshot changed, but it did not add or remove any proposed search directions."
    else:
        lines = ["### Career-source update", "", "Your active searches have not changed."]
        if added:
            lines.extend(["", "**New suggestions**", ""])
            lines.extend(f"- {item.title}" for item in added)
        if removed:
            lines.extend(["", "**No longer found in current sources**", ""])
            lines.extend(f"- {item.title}" for item in removed)
        summary = "\n".join(lines)
    return {
        "schema_version": 1,
        "kind": "job_search_evidence_update",
        "evidence_changed": evidence.corpus_hash != state.evidence_hash,
        "added": [item.model_dump(mode="json") for item in added],
        "removed": [item.model_dump(mode="json") for item in removed],
        "active_searches_changed": False,
        "user_handoff": {
            "required": True,
            "action": "present-job-search-evidence-update",
            "presentation_policy": PRESENTATION_POLICY,
            "rendered_markdown": summary,
        },
    }


def activate(root: Path, confirmation_hash: str) -> JobSearchSetupState:
    state = load_state(root)
    if state is None or state.status != SetupStatus.READY_TO_ACTIVATE:
        raise ValueError("job-search setup is not ready to activate")
    activate_portfolio(
        root / PORTFOLIO_PATH,
        root / SEARCH_CONFIG_PATH,
        root / ACTIVATION_BACKUP_PATH,
        root / ACTIVATION_RECORD_PATH,
        confirmation_hash,
    )
    state.status = SetupStatus.ACTIVE
    state.activation_record_path = ACTIVATION_RECORD_PATH.as_posix()
    state.updated_at = _now()
    save_state(root, state)
    return state


def _print_output(result: dict[str, Any], as_json: bool) -> None:
    if as_json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        handoff = result.get("user_handoff", {})
        print(handoff.get("rendered_markdown", json.dumps(result, indent=2)))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="resume-builder onboard",
        description="Continue unified onboarding or configure optional job discovery.",
    )
    parser.add_argument("--workspace", type=Path)
    parser.add_argument("--json", action="store_true", help="Print the structured handoff")
    actions = parser.add_subparsers(dest="action")
    actions.add_parser("status")
    actions.add_parser("run", help="Walk through setup interactively in a terminal")
    integrations = actions.add_parser(
        "integrations", help="Choose and review optional integration setup"
    )
    integrations.add_argument(
        "--select",
        help="Noninteractive comma-separated selection: telegram, gmail, discord, all, or none",
    )
    actions.add_parser("start")
    actions.add_parser("restart", help="Rebuild an unfinished setup from current career sources")
    answer = actions.add_parser("answer")
    answer.add_argument("payload", help="JSON answer object or @path-to-json")
    actions.add_parser("skip")
    actions.add_parser("preview-activation")
    actions.add_parser(
        "review-update", help="Compare newer career evidence without changing searches"
    )
    activation = actions.add_parser("activate")
    activation.add_argument("--confirm", required=True)
    return parser


def _answer_payload(value: str) -> JobSearchSetupAnswer:
    raw = Path(value[1:]).read_text(encoding="utf-8") if value.startswith("@") else value
    return JobSearchSetupAnswer.model_validate_json(raw)


def _ask_optional_bool(prompt: str) -> bool | None:
    while True:
        value = input(f"{prompt} [y/n/unknown]: ").strip().casefold()
        if value in {"y", "yes"}:
            return True
        if value in {"n", "no"}:
            return False
        if value in {"", "unknown", "u", "skip"}:
            return None
        print("Enter y, n, or unknown.")


def _interactive_answer(state: JobSearchSetupState) -> JobSearchSetupAnswer:
    print(_markdown_for_state(state))
    if state.step == SetupStep.ROLES:
        decisions: dict[str, str] = {}
        if input("\nKeep these suggestions? [Y/n]: ").strip().casefold() in {"n", "no"}:
            print("Enter s to search, e to explore, n to leave unsearched, or press Enter to keep.")
            choices = {"s": "search", "e": "explore", "n": "dont_seed"}
            for item in state.roles:
                choice = input(f"{item.title} [{item.intent.value}]: ").strip().casefold()
                if choice in choices:
                    decisions[item.role_id] = choices[choice]
        additions = [
            item.strip()
            for item in input("Additional roles, separated by commas [none]: ").split(",")
            if item.strip()
        ]
        answer: dict[str, Any] = {"decisions": decisions, "add": additions}
    elif state.step == SetupStep.ELIGIBILITY:
        country = input("Target country [United States]: ").strip() or "United States"
        answer = {
            "intended_country": country,
            "authorized_to_work": _ask_optional_bool(f"Authorized to work in {country}?"),
            "requires_sponsorship": _ask_optional_bool("Need employer sponsorship?"),
            "held_clearances": [
                item.strip()
                for item in input("Active clearances, separated by commas [none]: ").split(",")
                if item.strip()
            ],
            "willing_to_obtain_clearance": _ask_optional_bool("Willing to obtain a clearance?"),
        }
    elif state.step == SetupStep.LOCATION:
        modes = [
            item.strip().casefold()
            for item in (input("Work modes [remote]: ").strip() or "remote").split(",")
            if item.strip()
        ]
        places = []
        if {"hybrid", "onsite"} & set(modes):
            places = [
                item.strip()
                for item in input("Acceptable hybrid/onsite locations: ").split(",")
                if item.strip()
            ]
        remote_terms = [
            item.strip()
            for item in input(
                "Remote geographic restrictions, separated by commas [no restriction]: "
            ).split(",")
            if item.strip()
        ]
        answer = {
            "accepted_work_modes": modes,
            "accepted_onsite_locations": places,
            "remote_location_terms": remote_terms,
        }
    elif state.step == SetupStep.COMPENSATION:
        if input("Add compensation preferences? [y/N]: ").strip().casefold() not in {"y", "yes"}:
            answer = {"skipped": True}
        else:
            minimum = input("Minimum compensation [none]: ").strip()
            target = input("Target compensation [none]: ").strip()
            answer = {
                "skipped": False,
                "minimum": float(minimum) if minimum else None,
                "target": float(target) if target else None,
                "currency": input("Currency [USD]: ").strip() or "USD",
                "period": input("Period [year]: ").strip().casefold() or "year",
            }
    else:
        action = input("Save, change, or skip? [save]: ").strip().casefold() or "save"
        answer = {"action": action}
        if action == "change":
            answer["section"] = (
                input("Section (roles, eligibility, location, compensation): ").strip().casefold()
            )
    return JobSearchSetupAnswer(
        session_id=state.session_id,
        step=state.step,
        answer=answer,
    )


def interactive_run(root: Path) -> dict[str, Any]:
    state = load_state(root)
    if state is None or state.status == SetupStatus.SKIPPED:
        status = onboarding_status(root)
        if status.get("status") != "job_search_optional" and state is None:
            return status
        print(status["user_handoff"]["rendered_markdown"])
        if input("\nSet up job discovery now? [Y/n]: ").strip().casefold() in {"n", "no"}:
            return structured_output(skip_setup(root))
        state = start_setup(root)
    while state.status == SetupStatus.IN_PROGRESS:
        state = apply_answer(root, _interactive_answer(state))
        print()
    return structured_output(state)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        root = _workspace_root(args.workspace)
        action = args.action or ("run" if sys.stdin.isatty() and sys.stdout.isatty() else "status")
        if action == "status":
            result = onboarding_status(root)
        elif action == "run":
            result = interactive_run(root)
        elif action == "integrations":
            if args.json and args.select is None:
                raise ValueError("--json requires integrations --select")
            guide = (
                integration_setup_guide(parse_integration_choices(args.select), root)
                if args.select is not None
                else interactive_integration_setup(root)
            )
            result = {
                "schema_version": 1,
                "kind": "integration_setup",
                "user_handoff": {
                    "required": True,
                    "action": "present-integration-setup",
                    "presentation_policy": PRESENTATION_POLICY,
                    "rendered_markdown": guide,
                },
            }
        elif action == "start":
            result = structured_output(start_setup(root))
        elif action == "restart":
            result = structured_output(start_setup(root, restart=True))
        elif action == "answer":
            result = structured_output(apply_answer(root, _answer_payload(args.payload)))
        elif action == "skip":
            result = structured_output(skip_setup(root))
        elif action == "preview-activation":
            result = activation_preview(root)
        elif action == "review-update":
            result = evidence_update_preview(root)
        else:
            result = structured_output(activate(root, args.confirm))
    except (OSError, ValueError, WorkspaceError) as exc:
        print(json.dumps({"error": str(exc)}, indent=2), file=sys.stderr)
        return 2
    _print_output(result, args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
