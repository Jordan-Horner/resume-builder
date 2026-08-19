"""Validate versioned resume synthesis plans and their compiled output."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .layout import VaultLayout
from .rendering import contained_project_path
from .validation import parse_frontmatter

STORY_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
SECTIONS = {"experience", "projects"}
TARGET_MODES = {"direct", "adjacent", "exploratory"}
FIT_STATUSES = {"demonstrated", "transferable", "unsupported"}
RISK_STATUSES = {"resolved", "partial", "unresolved"}
COMPETENCY_DECISIONS = {"include", "omit"}
ROLE_ARC_EMPHASES = {"lead", "supporting", "compressed"}
CLAIM_COMPOSITIONS = {"single-fact", "same-system", "sequence", "aggregate"}
PAGE_BUDGET_SOURCES = {"direction-default", "user"}


@dataclass(frozen=True)
class ClaimEvidence:
    """Fact assignments for the semantic parts of one planned claim."""

    action: tuple[str, ...]
    object: tuple[str, ...]
    scope: tuple[str, ...]
    outcome: tuple[str, ...]

    @property
    def fact_ids(self) -> tuple[str, ...]:
        """Return every fact used by the visible claim in stable order."""
        return tuple(dict.fromkeys((*self.action, *self.object, *self.scope, *self.outcome)))


@dataclass(frozen=True)
class ClaimSpec:
    """Structured claim boundary used before natural-language drafting."""

    subject: str
    action: str
    object: str
    scope: str | None
    outcome: str | None
    composition: str
    relationship: str
    evidence: ClaimEvidence


@dataclass(frozen=True)
class PageBudget:
    """Resolved presentation budget shared by planning and minting."""

    max_pages: int
    source: str


@dataclass(frozen=True)
class SynthesisStory:
    """One planned resume claim with a distinct contribution."""

    story_id: str
    section: str
    role_ids: tuple[str, ...]
    fact_ids: tuple[str, ...]
    primary_job: str
    priority: int
    importance: str
    rationale: str
    claim_focus: str | None = None
    core_fact_ids: tuple[str, ...] = ()
    claim: ClaimSpec | None = None


@dataclass(frozen=True)
class ConceptFit:
    """Candidate-evidence relationship to one direction concept."""

    concept_id: str
    status: str
    fact_ids: tuple[str, ...]
    rationale: str


@dataclass(frozen=True)
class ReviewerRisk:
    """One material hiring-read objection considered during selection."""

    risk_id: str
    concern: str
    status: str
    fact_ids: tuple[str, ...]
    planning_action: str


@dataclass(frozen=True)
class PresentationStrategy:
    """Explicit section and compression choices for the resume draft."""

    competencies: str
    competencies_job: str
    compressed_role_ids: tuple[str, ...]


@dataclass(frozen=True)
class OmittedRoleSignal:
    """One supported role signal considered but intentionally left out."""

    signal: str
    fact_ids: tuple[str, ...]
    reason: str


@dataclass(frozen=True)
class RoleArc:
    """The planned story allocation for one experience placement."""

    role_ids: tuple[str, ...]
    emphasis: str
    arc_focus: str
    story_ids: tuple[str, ...]
    selection_rationale: str
    omitted_signals: tuple[OmittedRoleSignal, ...]
    required_dimensions: tuple[str, ...] = ()
    required_story_ids: tuple[str, ...] = ()
    optional_story_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class SynthesisPlan:
    """Validated strategy connecting vault evidence to one resume."""

    source: Path
    version: int
    resume: Path
    direction: Path
    target_argument: str
    summary_job: str | None
    summary_fact_ids: tuple[str, ...]
    summary_body_fact_ids: tuple[str, ...]
    progression: tuple[str, ...]
    stories: tuple[SynthesisStory, ...]
    exclusions: tuple[tuple[str, str], ...]
    gaps: tuple[str, ...]
    target_mode: str | None = None
    concept_fit: tuple[ConceptFit, ...] = ()
    reviewer_risks: tuple[ReviewerRisk, ...] = ()
    presentation: PresentationStrategy | None = None
    role_arcs: tuple[RoleArc, ...] = ()
    page_budget: PageBudget | None = None


def object_value(value: object, owner: str) -> dict[str, Any]:
    """Return a dictionary or raise a useful plan error."""
    if not isinstance(value, dict):
        raise ValueError(f"{owner} must be an object")
    return value


def exact_fields(value: dict[str, Any], allowed: set[str], owner: str) -> None:
    """Reject omitted and unexpected fields in a versioned synthesis object."""
    missing = sorted(allowed - value.keys())
    unexpected = sorted(value.keys() - allowed)
    if missing:
        raise ValueError(f"{owner} missing fields: {missing}")
    if unexpected:
        raise ValueError(f"{owner} contains unsupported fields: {unexpected}")


def nonempty_string(value: object, owner: str) -> str:
    """Return a stripped non-empty string."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{owner} must be a non-empty string")
    return value.strip()


def optional_string(value: object, owner: str) -> str | None:
    """Return a stripped optional string."""
    if value is None:
        return None
    return nonempty_string(value, owner)


def string_list(value: object, owner: str, *, required: bool = True) -> list[str]:
    """Return a unique list of non-empty strings."""
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise ValueError(f"{owner} must be a list of non-empty strings")
    if required and not value:
        raise ValueError(f"{owner} must not be empty")
    if len(set(value)) != len(value):
        raise ValueError(f"{owner} must not contain duplicates")
    return value


def fact_metadata(vault_root: Path) -> dict[str, dict[str, object]]:
    """Load canonical fact metadata for synthesis validation."""
    layout = VaultLayout.load(vault_root)
    result: dict[str, dict[str, object]] = {}
    for path in sorted(layout.facts.rglob("*.md")):
        metadata, _ = parse_frontmatter(path)
        fact_id = metadata.get("id")
        if isinstance(fact_id, str):
            result[fact_id] = metadata
    return result


def direction_concept_ids(path: Path) -> set[str]:
    """Return stable concept IDs declared by a direction profile."""
    try:
        markdown = path.read_text(encoding="utf-8")
        if not markdown.startswith("---\n"):
            raise ValueError("direction must begin with YAML frontmatter")
        raw_frontmatter, _ = markdown[4:].split("\n---\n", 1)
        metadata = object_value(yaml.safe_load(raw_frontmatter), "synthesis direction")
    except (OSError, ValueError, yaml.YAMLError) as exc:
        raise ValueError(f"invalid synthesis direction {path}: {exc}") from exc
    raw_concepts = metadata.get("priority_concepts")
    if not isinstance(raw_concepts, list) or not raw_concepts:
        raise ValueError("synthesis direction must declare priority_concepts")
    concept_ids: set[str] = set()
    for index, raw_concept in enumerate(raw_concepts):
        owner = f"synthesis direction priority_concepts[{index}]"
        concept = object_value(raw_concept, owner)
        concept_id = nonempty_string(concept.get("id"), f"{owner}.id")
        if not STORY_ID.fullmatch(concept_id):
            raise ValueError(f"{owner}.id must be a lowercase hyphenated identifier")
        if concept_id in concept_ids:
            raise ValueError(f"duplicate synthesis direction concept ID: {concept_id}")
        concept_ids.add(concept_id)
    return concept_ids


def direction_page_budget(path: Path) -> int:
    """Return the validated default page budget declared by a direction."""
    try:
        markdown = path.read_text(encoding="utf-8")
        raw_frontmatter, _ = markdown[4:].split("\n---\n", 1)
        metadata = object_value(yaml.safe_load(raw_frontmatter), "synthesis direction")
        defaults = object_value(metadata.get("defaults"), "synthesis direction defaults")
        max_pages = defaults.get("max_pages")
    except (OSError, ValueError, yaml.YAMLError) as exc:
        raise ValueError(f"invalid synthesis direction page budget {path}: {exc}") from exc
    if not isinstance(max_pages, int) or isinstance(max_pages, bool) or max_pages < 1:
        raise ValueError("synthesis direction defaults.max_pages must be a positive integer")
    return max_pages


def load_synthesis_plan(path: Path, project_root: Path, vault_root: Path) -> SynthesisPlan:
    """Load and validate one versioned synthesis plan."""
    source = contained_project_path(path, project_root, "resumes/plans", "synthesis plan")
    try:
        raw = yaml.safe_load(source.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(f"invalid synthesis plan {source}: {exc}") from exc
    data = object_value(raw, "synthesis plan")
    version = data.get("version")
    if (
        not isinstance(version, int)
        or isinstance(version, bool)
        or version not in {1, 2, 3, 4, 5, 6}
    ):
        raise ValueError("synthesis plan must declare version 1, 2, 3, 4, 5, or 6")
    fields = {
        "version",
        "resume",
        "direction",
        "target_argument",
        "progression",
        "stories",
        "exclusions",
        "gaps",
    }
    if version >= 2:
        fields.update({"summary_job", "summary_fact_ids"})
    if version >= 3:
        fields.update({"target_mode", "concept_fit", "reviewer_risks", "presentation"})
    if version >= 5:
        fields.add("role_arcs")
    if version >= 6:
        fields.add("page_budget")
    exact_fields(data, fields, "synthesis plan")

    resume = contained_project_path(
        Path(nonempty_string(data["resume"], "synthesis plan resume")),
        project_root,
        "resumes",
        "synthesis plan resume",
    )
    direction = contained_project_path(
        Path(nonempty_string(data["direction"], "synthesis plan direction")),
        project_root,
        "directions",
        "synthesis plan direction",
    )
    if source.stem != resume.stem:
        raise ValueError("synthesis plan filename must match its resume filename")
    if not direction.is_file():
        raise ValueError(f"synthesis direction does not exist: {direction}")

    page_budget: PageBudget | None = None
    if version >= 6:
        raw_page_budget = object_value(data["page_budget"], "synthesis page_budget")
        exact_fields(raw_page_budget, {"max_pages", "source"}, "synthesis page_budget")
        max_pages = raw_page_budget["max_pages"]
        if not isinstance(max_pages, int) or isinstance(max_pages, bool) or max_pages < 1:
            raise ValueError("synthesis page_budget.max_pages must be a positive integer")
        budget_source = nonempty_string(raw_page_budget["source"], "synthesis page_budget.source")
        if budget_source not in PAGE_BUDGET_SOURCES:
            raise ValueError("synthesis page_budget.source must be direction-default or user")
        if budget_source == "direction-default":
            direction_budget = direction_page_budget(direction)
            if max_pages != direction_budget:
                raise ValueError(
                    "synthesis page budget disagrees with direction default: "
                    f"plan={max_pages}, direction={direction_budget}"
                )
        page_budget = PageBudget(max_pages=max_pages, source=budget_source)

    facts = fact_metadata(vault_root)
    progression = string_list(data["progression"], "synthesis progression")
    unknown_progression = sorted(set(progression) - facts.keys())
    if unknown_progression:
        raise ValueError(f"synthesis progression cites unknown facts: {unknown_progression}")
    non_roles = sorted(fact_id for fact_id in progression if facts[fact_id].get("type") != "role")
    if non_roles:
        raise ValueError(f"synthesis progression must contain role facts: {non_roles}")

    summary_job: str | None = None
    summary_fact_ids: list[str] = []
    summary_body_fact_ids: list[str] = []
    if version >= 2:
        summary_job = nonempty_string(data["summary_job"], "synthesis summary_job")
        summary_fact_ids = string_list(data["summary_fact_ids"], "synthesis summary_fact_ids")
        unknown_summary = sorted(set(summary_fact_ids) - facts.keys())
        if unknown_summary:
            raise ValueError(f"synthesis summary cites unknown facts: {unknown_summary}")
        summary_body_fact_ids = [
            fact_id
            for fact_id in summary_fact_ids
            if facts[fact_id].get("category") == "employment"
            and facts[fact_id].get("scope") == "role"
        ]

    raw_stories = data["stories"]
    if not isinstance(raw_stories, list) or not raw_stories:
        raise ValueError("synthesis stories must be a non-empty list")
    stories: list[SynthesisStory] = []
    seen_story_ids: set[str] = set()
    seen_jobs: set[tuple[str, tuple[str, ...], str]] = set()
    selected_facts: set[str] = set()
    story_fields = {
        "id",
        "section",
        "role_ids",
        "fact_ids",
        "primary_job",
        "priority",
        "rationale",
    }
    if version >= 2:
        story_fields.add("importance")
    if version >= 4:
        story_fields.update({"claim_focus", "core_fact_ids"})
    if version >= 6:
        story_fields.add("claim")
    planned_visible_facts: set[str] = set()
    for index, raw_story in enumerate(raw_stories):
        owner = f"synthesis stories[{index}]"
        story = object_value(raw_story, owner)
        exact_fields(story, story_fields, owner)
        story_id = nonempty_string(story["id"], f"{owner}.id")
        if not STORY_ID.fullmatch(story_id):
            raise ValueError(f"{owner}.id must be a lowercase hyphenated identifier")
        if story_id in seen_story_ids:
            raise ValueError(f"duplicate synthesis story ID: {story_id}")
        seen_story_ids.add(story_id)
        section = nonempty_string(story["section"], f"{owner}.section")
        if section not in SECTIONS:
            raise ValueError(f"{owner}.section must be experience or projects")
        role_ids = string_list(
            story["role_ids"], f"{owner}.role_ids", required=section == "experience"
        )
        if set(role_ids) - set(progression):
            raise ValueError(f"{owner}.role_ids must be declared in progression")
        fact_ids = string_list(story["fact_ids"], f"{owner}.fact_ids")
        unknown = sorted(set(fact_ids) - facts.keys())
        if unknown:
            raise ValueError(f"{owner} cites unknown facts: {unknown}")
        for fact_id in fact_ids:
            fact = facts[fact_id]
            if fact.get("category") != "employment" or fact.get("type") == "role":
                continue
            if fact.get("scope") != "role":
                continue
            raw_allowed_roles = fact.get("role_ids")
            if not isinstance(raw_allowed_roles, list):
                raise ValueError(f"role-scoped fact {fact_id} has invalid role_ids")
            allowed_roles = {item for item in raw_allowed_roles if isinstance(item, str)}
            placed_roles = set(role_ids)
            if section != "experience" or not placed_roles.issubset(allowed_roles):
                raise ValueError(
                    f"{owner} places role-scoped fact {fact_id} outside its roles: "
                    f"{sorted(allowed_roles)}"
                )
        primary_job = nonempty_string(story["primary_job"], f"{owner}.primary_job")
        if not STORY_ID.fullmatch(primary_job):
            raise ValueError(f"{owner}.primary_job must be a lowercase hyphenated identifier")
        job_key = (section, tuple(sorted(role_ids)), primary_job)
        if job_key in seen_jobs:
            raise ValueError(f"duplicate primary job for the same placement: {primary_job}")
        seen_jobs.add(job_key)
        priority = story["priority"]
        if not isinstance(priority, int) or isinstance(priority, bool) or not 1 <= priority <= 5:
            raise ValueError(f"{owner}.priority must be an integer from 1 to 5")
        importance = (
            nonempty_string(story["importance"], f"{owner}.importance") if version >= 2 else "core"
        )
        if importance not in {"core", "supporting"}:
            raise ValueError(f"{owner}.importance must be core or supporting")
        rationale = nonempty_string(story["rationale"], f"{owner}.rationale")
        claim_focus = (
            nonempty_string(story["claim_focus"], f"{owner}.claim_focus") if version >= 4 else None
        )
        core_fact_ids = (
            string_list(story["core_fact_ids"], f"{owner}.core_fact_ids")
            if version >= 4
            else fact_ids
        )
        facts_outside_story = sorted(set(core_fact_ids) - set(fact_ids))
        if facts_outside_story:
            raise ValueError(
                f"{owner}.core_fact_ids must be a subset of fact_ids: {facts_outside_story}"
            )
        claim: ClaimSpec | None = None
        if version >= 6:
            raw_claim = object_value(story["claim"], f"{owner}.claim")
            exact_fields(
                raw_claim,
                {
                    "subject",
                    "action",
                    "object",
                    "scope",
                    "outcome",
                    "composition",
                    "relationship",
                    "evidence",
                },
                f"{owner}.claim",
            )
            subject = nonempty_string(raw_claim["subject"], f"{owner}.claim.subject")
            if subject != "candidate":
                raise ValueError(f"{owner}.claim.subject must be candidate")
            composition = nonempty_string(raw_claim["composition"], f"{owner}.claim.composition")
            if composition not in CLAIM_COMPOSITIONS:
                raise ValueError(
                    f"{owner}.claim.composition must be one of {sorted(CLAIM_COMPOSITIONS)}"
                )
            raw_claim_evidence = object_value(raw_claim["evidence"], f"{owner}.claim.evidence")
            exact_fields(
                raw_claim_evidence,
                {"action", "object", "scope", "outcome"},
                f"{owner}.claim.evidence",
            )
            scope = optional_string(raw_claim["scope"], f"{owner}.claim.scope")
            outcome = optional_string(raw_claim["outcome"], f"{owner}.claim.outcome")
            claim_evidence = ClaimEvidence(
                action=tuple(
                    string_list(raw_claim_evidence["action"], f"{owner}.claim.evidence.action")
                ),
                object=tuple(
                    string_list(raw_claim_evidence["object"], f"{owner}.claim.evidence.object")
                ),
                scope=tuple(
                    string_list(
                        raw_claim_evidence["scope"],
                        f"{owner}.claim.evidence.scope",
                        required=scope is not None,
                    )
                ),
                outcome=tuple(
                    string_list(
                        raw_claim_evidence["outcome"],
                        f"{owner}.claim.evidence.outcome",
                        required=outcome is not None,
                    )
                ),
            )
            if scope is None and claim_evidence.scope:
                raise ValueError(f"{owner}.claim scope evidence requires visible scope")
            if outcome is None and claim_evidence.outcome:
                raise ValueError(f"{owner}.claim outcome evidence requires visible outcome")
            claim_fact_ids = set(claim_evidence.fact_ids)
            unknown_claim_facts = sorted(claim_fact_ids - set(fact_ids))
            missing_claim_core = sorted(set(core_fact_ids) - claim_fact_ids)
            if unknown_claim_facts or missing_claim_core:
                raise ValueError(
                    f"{owner}.claim evidence disagrees with story facts: "
                    f"missing_core={missing_claim_core}, unexpected={unknown_claim_facts}"
                )
            if composition == "single-fact" and len(claim_fact_ids) != 1:
                raise ValueError(f"{owner}.claim single-fact composition requires exactly one fact")
            relationship = nonempty_string(raw_claim["relationship"], f"{owner}.claim.relationship")
            claim = ClaimSpec(
                subject=subject,
                action=nonempty_string(raw_claim["action"], f"{owner}.claim.action"),
                object=nonempty_string(raw_claim["object"], f"{owner}.claim.object"),
                scope=scope,
                outcome=outcome,
                composition=composition,
                relationship=relationship,
                evidence=claim_evidence,
            )
            planned_visible_facts.update(claim_evidence.fact_ids)
        else:
            planned_visible_facts.update(fact_ids)
        selected_facts.update(fact_ids)
        stories.append(
            SynthesisStory(
                story_id=story_id,
                section=section,
                role_ids=tuple(role_ids),
                fact_ids=tuple(fact_ids),
                primary_job=primary_job,
                priority=priority,
                importance=importance,
                rationale=rationale,
                claim_focus=claim_focus,
                core_fact_ids=tuple(core_fact_ids),
                claim=claim,
            )
        )

    selected_facts.update(summary_fact_ids)
    raw_exclusions = data["exclusions"]
    if not isinstance(raw_exclusions, list):
        raise ValueError("synthesis exclusions must be a list")
    exclusions: list[tuple[str, str]] = []
    excluded_facts: set[str] = set()
    for index, raw_exclusion in enumerate(raw_exclusions):
        owner = f"synthesis exclusions[{index}]"
        exclusion = object_value(raw_exclusion, owner)
        exact_fields(exclusion, {"fact_id", "reason"}, owner)
        fact_id = nonempty_string(exclusion["fact_id"], f"{owner}.fact_id")
        if fact_id not in facts:
            raise ValueError(f"{owner} cites unknown fact: {fact_id}")
        if fact_id in selected_facts:
            raise ValueError(f"synthesis fact cannot be selected and excluded: {fact_id}")
        if fact_id in excluded_facts:
            raise ValueError(f"duplicate synthesis exclusion: {fact_id}")
        excluded_facts.add(fact_id)
        exclusions.append((fact_id, nonempty_string(exclusion["reason"], f"{owner}.reason")))

    gaps = tuple(string_list(data["gaps"], "synthesis gaps", required=False))

    target_mode: str | None = None
    concept_fit: tuple[ConceptFit, ...] = ()
    reviewer_risks: tuple[ReviewerRisk, ...] = ()
    presentation: PresentationStrategy | None = None
    role_arcs: tuple[RoleArc, ...] = ()
    if version >= 3:
        target_mode = nonempty_string(data["target_mode"], "synthesis target_mode")
        if target_mode not in TARGET_MODES:
            raise ValueError(f"synthesis target_mode must be one of {sorted(TARGET_MODES)}")

        expected_concepts = direction_concept_ids(direction)
        raw_fit = data["concept_fit"]
        if not isinstance(raw_fit, list) or not raw_fit:
            raise ValueError("synthesis concept_fit must be a non-empty list")
        fit_entries: list[ConceptFit] = []
        seen_concepts: set[str] = set()
        for index, raw_entry in enumerate(raw_fit):
            owner = f"synthesis concept_fit[{index}]"
            entry = object_value(raw_entry, owner)
            exact_fields(entry, {"concept_id", "status", "fact_ids", "rationale"}, owner)
            concept_id = nonempty_string(entry["concept_id"], f"{owner}.concept_id")
            if concept_id in seen_concepts:
                raise ValueError(f"duplicate synthesis concept fit: {concept_id}")
            seen_concepts.add(concept_id)
            status = nonempty_string(entry["status"], f"{owner}.status")
            if status not in FIT_STATUSES:
                raise ValueError(f"{owner}.status must be one of {sorted(FIT_STATUSES)}")
            fit_fact_ids = string_list(
                entry["fact_ids"], f"{owner}.fact_ids", required=status != "unsupported"
            )
            unknown_fit_facts = sorted(set(fit_fact_ids) - facts.keys())
            if unknown_fit_facts:
                raise ValueError(f"{owner} cites unknown facts: {unknown_fit_facts}")
            if status == "unsupported" and fit_fact_ids:
                raise ValueError(f"{owner}.fact_ids must be empty when status is unsupported")
            visible_plan_facts = planned_visible_facts if version >= 6 else selected_facts
            visible_plan_facts = set(visible_plan_facts) | set(summary_fact_ids)
            unselected_fit_facts = sorted(set(fit_fact_ids) - visible_plan_facts)
            if unselected_fit_facts:
                raise ValueError(
                    f"{owner} cites evidence absent from selected stories and summary: "
                    f"{unselected_fit_facts}"
                )
            fit_entries.append(
                ConceptFit(
                    concept_id=concept_id,
                    status=status,
                    fact_ids=tuple(fit_fact_ids),
                    rationale=nonempty_string(entry["rationale"], f"{owner}.rationale"),
                )
            )
        missing_concepts = sorted(expected_concepts - seen_concepts)
        unknown_concepts = sorted(seen_concepts - expected_concepts)
        if missing_concepts or unknown_concepts:
            raise ValueError(
                "synthesis concept_fit must classify every direction concept exactly once: "
                f"missing={missing_concepts}, unknown={unknown_concepts}"
            )
        concept_fit = tuple(fit_entries)

        raw_risks = data["reviewer_risks"]
        if not isinstance(raw_risks, list) or len(raw_risks) > 3:
            raise ValueError("synthesis reviewer_risks must be a list of at most three items")
        risk_entries: list[ReviewerRisk] = []
        seen_risks: set[str] = set()
        unresolved_risk = False
        for index, raw_risk in enumerate(raw_risks):
            owner = f"synthesis reviewer_risks[{index}]"
            risk = object_value(raw_risk, owner)
            exact_fields(
                risk,
                {"id", "concern", "status", "fact_ids", "planning_action"},
                owner,
            )
            risk_id = nonempty_string(risk["id"], f"{owner}.id")
            if not STORY_ID.fullmatch(risk_id):
                raise ValueError(f"{owner}.id must be a lowercase hyphenated identifier")
            if risk_id in seen_risks:
                raise ValueError(f"duplicate synthesis reviewer risk: {risk_id}")
            seen_risks.add(risk_id)
            risk_status = nonempty_string(risk["status"], f"{owner}.status")
            if risk_status not in RISK_STATUSES:
                raise ValueError(f"{owner}.status must be one of {sorted(RISK_STATUSES)}")
            risk_fact_ids = string_list(
                risk["fact_ids"], f"{owner}.fact_ids", required=risk_status != "unresolved"
            )
            unknown_risk_facts = sorted(set(risk_fact_ids) - facts.keys())
            if unknown_risk_facts:
                raise ValueError(f"{owner} cites unknown facts: {unknown_risk_facts}")
            visible_plan_facts = planned_visible_facts if version >= 6 else selected_facts
            visible_plan_facts = set(visible_plan_facts) | set(summary_fact_ids)
            unselected_risk_facts = sorted(set(risk_fact_ids) - visible_plan_facts)
            if unselected_risk_facts:
                raise ValueError(
                    f"{owner} cites evidence absent from selected stories and summary: "
                    f"{unselected_risk_facts}"
                )
            unresolved_risk = unresolved_risk or risk_status == "unresolved"
            risk_entries.append(
                ReviewerRisk(
                    risk_id=risk_id,
                    concern=nonempty_string(risk["concern"], f"{owner}.concern"),
                    status=risk_status,
                    fact_ids=tuple(risk_fact_ids),
                    planning_action=nonempty_string(
                        risk["planning_action"], f"{owner}.planning_action"
                    ),
                )
            )
        if unresolved_risk and not gaps:
            raise ValueError("unresolved synthesis reviewer risks require at least one gap")
        reviewer_risks = tuple(risk_entries)

        raw_presentation = object_value(data["presentation"], "synthesis presentation")
        exact_fields(
            raw_presentation,
            {"competencies", "competencies_job", "compressed_role_ids"},
            "synthesis presentation",
        )
        competencies = nonempty_string(
            raw_presentation["competencies"], "synthesis presentation.competencies"
        )
        if competencies not in COMPETENCY_DECISIONS:
            raise ValueError("synthesis presentation.competencies must be include or omit")
        compressed_role_ids = string_list(
            raw_presentation["compressed_role_ids"],
            "synthesis presentation.compressed_role_ids",
            required=False,
        )
        unknown_compressed_roles = sorted(set(compressed_role_ids) - set(progression))
        if unknown_compressed_roles:
            raise ValueError(
                "synthesis presentation compresses roles absent from progression: "
                f"{unknown_compressed_roles}"
            )
        presentation = PresentationStrategy(
            competencies=competencies,
            competencies_job=nonempty_string(
                raw_presentation["competencies_job"],
                "synthesis presentation.competencies_job",
            ),
            compressed_role_ids=tuple(compressed_role_ids),
        )

    if version >= 5:
        assert presentation is not None
        raw_role_arcs = data["role_arcs"]
        if not isinstance(raw_role_arcs, list) or not raw_role_arcs:
            raise ValueError("synthesis role_arcs must be a non-empty list")
        story_by_id = {story.story_id: story for story in stories}
        experience_story_ids = {
            story.story_id for story in stories if story.section == "experience"
        }
        arc_entries: list[RoleArc] = []
        seen_placements: set[tuple[str, ...]] = set()
        allocated_story_ids: set[str] = set()
        roles_in_arcs: set[str] = set()
        compressed_arc_roles: set[str] = set()
        lead_arc_found = False
        for index, raw_arc in enumerate(raw_role_arcs):
            owner = f"synthesis role_arcs[{index}]"
            arc = object_value(raw_arc, owner)
            arc_fields = {
                "role_ids",
                "emphasis",
                "arc_focus",
                "selection_rationale",
                "omitted_signals",
            }
            if version >= 6:
                arc_fields.update(
                    {"required_dimensions", "required_story_ids", "optional_story_ids"}
                )
            else:
                arc_fields.add("story_ids")
            exact_fields(arc, arc_fields, owner)
            arc_role_ids = string_list(arc["role_ids"], f"{owner}.role_ids")
            unknown_arc_roles = sorted(set(arc_role_ids) - set(progression))
            if unknown_arc_roles:
                raise ValueError(
                    f"{owner}.role_ids must be declared in progression: {unknown_arc_roles}"
                )
            placement = tuple(sorted(arc_role_ids))
            if placement in seen_placements:
                raise ValueError(f"duplicate synthesis role arc placement: {list(placement)}")
            seen_placements.add(placement)
            roles_in_arcs.update(arc_role_ids)

            emphasis = nonempty_string(arc["emphasis"], f"{owner}.emphasis")
            if emphasis not in ROLE_ARC_EMPHASES:
                raise ValueError(f"{owner}.emphasis must be one of {sorted(ROLE_ARC_EMPHASES)}")
            lead_arc_found = lead_arc_found or emphasis == "lead"
            if emphasis == "compressed":
                compressed_arc_roles.update(arc_role_ids)

            required_dimensions: list[str] = []
            required_story_ids: list[str] = []
            optional_story_ids: list[str] = []
            if version >= 6:
                required_dimensions = string_list(
                    arc["required_dimensions"], f"{owner}.required_dimensions"
                )
                if any(not STORY_ID.fullmatch(item) for item in required_dimensions):
                    raise ValueError(
                        f"{owner}.required_dimensions must use lowercase hyphenated identifiers"
                    )
                required_story_ids = string_list(
                    arc["required_story_ids"], f"{owner}.required_story_ids"
                )
                optional_story_ids = string_list(
                    arc["optional_story_ids"],
                    f"{owner}.optional_story_ids",
                    required=False,
                )
                overlap = sorted(set(required_story_ids) & set(optional_story_ids))
                if overlap:
                    raise ValueError(
                        f"{owner} assigns stories as both required and optional: {overlap}"
                    )
                arc_story_ids = [*required_story_ids, *optional_story_ids]
            else:
                arc_story_ids = string_list(arc["story_ids"], f"{owner}.story_ids")
            unknown_arc_stories = sorted(set(arc_story_ids) - experience_story_ids)
            if unknown_arc_stories:
                raise ValueError(
                    f"{owner}.story_ids must reference experience stories: {unknown_arc_stories}"
                )
            if version < 6:
                required_story_ids = [
                    story_id
                    for story_id in arc_story_ids
                    if story_by_id[story_id].importance == "core"
                ]
                optional_story_ids = [
                    story_id
                    for story_id in arc_story_ids
                    if story_by_id[story_id].importance == "supporting"
                ]
            duplicate_allocations = sorted(set(arc_story_ids) & allocated_story_ids)
            if duplicate_allocations:
                raise ValueError(
                    "synthesis experience stories allocated to more than one role arc: "
                    f"{duplicate_allocations}"
                )
            mismatched_placements = sorted(
                story_id
                for story_id in arc_story_ids
                if tuple(sorted(story_by_id[story_id].role_ids)) != placement
            )
            if mismatched_placements:
                raise ValueError(
                    f"{owner}.story_ids disagree with role placement: {mismatched_placements}"
                )
            if version >= 6:
                non_core_required = sorted(
                    story_id
                    for story_id in required_story_ids
                    if story_by_id[story_id].importance != "core"
                )
                non_supporting_optional = sorted(
                    story_id
                    for story_id in optional_story_ids
                    if story_by_id[story_id].importance != "supporting"
                )
                if non_core_required or non_supporting_optional:
                    raise ValueError(
                        f"{owner} story importance disagrees with allocation: "
                        f"required_not_core={non_core_required}, "
                        f"optional_not_supporting={non_supporting_optional}"
                    )
                required_jobs = {
                    story_by_id[story_id].primary_job for story_id in required_story_ids
                }
                missing_dimensions = sorted(set(required_dimensions) - required_jobs)
                if missing_dimensions:
                    raise ValueError(
                        f"{owner}.required_dimensions lack required stories: {missing_dimensions}"
                    )
            allocated_story_ids.update(arc_story_ids)

            raw_omitted_signals = arc["omitted_signals"]
            if not isinstance(raw_omitted_signals, list):
                raise ValueError(f"{owner}.omitted_signals must be a list")
            omitted_signals: list[OmittedRoleSignal] = []
            seen_signals: set[str] = set()
            for signal_index, raw_signal in enumerate(raw_omitted_signals):
                signal_owner = f"{owner}.omitted_signals[{signal_index}]"
                signal = object_value(raw_signal, signal_owner)
                exact_fields(signal, {"signal", "fact_ids", "reason"}, signal_owner)
                signal_name = nonempty_string(signal["signal"], f"{signal_owner}.signal")
                if signal_name in seen_signals:
                    raise ValueError(f"duplicate omitted role signal in {owner}: {signal_name}")
                seen_signals.add(signal_name)
                signal_fact_ids = string_list(signal["fact_ids"], f"{signal_owner}.fact_ids")
                unknown_signal_facts = sorted(set(signal_fact_ids) - facts.keys())
                if unknown_signal_facts:
                    raise ValueError(f"{signal_owner} cites unknown facts: {unknown_signal_facts}")
                omitted_signals.append(
                    OmittedRoleSignal(
                        signal=signal_name,
                        fact_ids=tuple(signal_fact_ids),
                        reason=nonempty_string(signal["reason"], f"{signal_owner}.reason"),
                    )
                )

            arc_entries.append(
                RoleArc(
                    role_ids=tuple(arc_role_ids),
                    emphasis=emphasis,
                    arc_focus=nonempty_string(arc["arc_focus"], f"{owner}.arc_focus"),
                    story_ids=tuple(arc_story_ids),
                    selection_rationale=nonempty_string(
                        arc["selection_rationale"], f"{owner}.selection_rationale"
                    ),
                    omitted_signals=tuple(omitted_signals),
                    required_dimensions=tuple(required_dimensions),
                    required_story_ids=tuple(required_story_ids),
                    optional_story_ids=tuple(optional_story_ids),
                )
            )

        missing_allocations = sorted(experience_story_ids - allocated_story_ids)
        if missing_allocations:
            raise ValueError(
                f"synthesis experience stories missing from role_arcs: {missing_allocations}"
            )
        missing_arc_roles = sorted(set(progression) - roles_in_arcs)
        if missing_arc_roles:
            raise ValueError(
                f"synthesis progression roles missing from role_arcs: {missing_arc_roles}"
            )
        if not lead_arc_found:
            raise ValueError("synthesis role_arcs must identify at least one lead arc")
        planned_compressed_roles = set(presentation.compressed_role_ids)
        if compressed_arc_roles != planned_compressed_roles:
            raise ValueError(
                "synthesis role_arcs compressed emphasis disagrees with presentation: "
                f"role_arcs={sorted(compressed_arc_roles)}, "
                f"presentation={sorted(planned_compressed_roles)}"
            )
        role_arcs = tuple(arc_entries)

    return SynthesisPlan(
        source=source,
        version=version,
        resume=resume,
        direction=direction,
        target_argument=nonempty_string(data["target_argument"], "synthesis target_argument"),
        summary_job=summary_job,
        summary_fact_ids=tuple(summary_fact_ids),
        summary_body_fact_ids=tuple(summary_body_fact_ids),
        progression=tuple(progression),
        stories=tuple(stories),
        exclusions=tuple(exclusions),
        gaps=gaps,
        target_mode=target_mode,
        concept_fit=concept_fit,
        reviewer_risks=reviewer_risks,
        presentation=presentation,
        role_arcs=role_arcs,
        page_budget=page_budget,
    )


def body_evidence_ids(payload: dict[str, Any]) -> set[str]:
    """Collect canonical evidence cited after the summary."""
    result: set[str] = set()

    def collect(value: object) -> None:
        if isinstance(value, dict):
            raw_evidence = value.get("evidence")
            if isinstance(raw_evidence, list):
                result.update(item for item in raw_evidence if isinstance(item, str))
            for nested in value.values():
                collect(nested)
        elif isinstance(value, list):
            for nested in value:
                collect(nested)

    for section in (
        "competencies",
        "experience",
        "projects",
        "education",
        "certifications",
        "skills",
    ):
        collect(payload.get(section, []))
    return result


def role_arc_payloads(
    plan: SynthesisPlan,
    used_story_ids: set[str] | None = None,
) -> list[dict[str, object]]:
    """Return inspectable role-level story allocations for reports and manifests."""
    story_by_id = {story.story_id: story for story in plan.stories}
    result: list[dict[str, object]] = []
    for arc in plan.role_arcs:
        payload: dict[str, object] = {
            "role_ids": list(arc.role_ids),
            "emphasis": arc.emphasis,
            "arc_focus": arc.arc_focus,
            "story_ids": list(arc.story_ids),
            "primary_jobs": [story_by_id[story_id].primary_job for story_id in arc.story_ids],
            "planned_story_count": len(arc.story_ids),
            "selection_rationale": arc.selection_rationale,
            "omitted_signals": [
                {
                    "signal": signal.signal,
                    "fact_ids": list(signal.fact_ids),
                    "reason": signal.reason,
                }
                for signal in arc.omitted_signals
            ],
        }
        if plan.version >= 6:
            payload.update(
                {
                    "required_dimensions": list(arc.required_dimensions),
                    "required_story_ids": list(arc.required_story_ids),
                    "optional_story_ids": list(arc.optional_story_ids),
                }
            )
        if used_story_ids is not None:
            used = [story_id for story_id in arc.story_ids if story_id in used_story_ids]
            payload.update(
                {
                    "used_story_ids": used,
                    "used_story_count": len(used),
                    "omitted_story_ids": [
                        story_id for story_id in arc.story_ids if story_id not in used_story_ids
                    ],
                }
            )
        result.append(payload)
    return result


def audit_synthesis(payload: dict[str, Any], plan: SynthesisPlan) -> dict[str, object]:
    """Require core stories and report intentionally omitted supporting stories."""
    planned = {story.story_id: story for story in plan.stories}
    used: list[str] = []
    selected_fact_ids: set[str] = set()
    present_roles: set[str] = set()
    story_evidence: dict[str, dict[str, object]] = {}
    unused_optional_facts: set[str] = set()

    def validate_story_evidence(
        evidence_value: object,
        story: SynthesisStory,
        owner: str,
    ) -> set[str]:
        evidence = (
            {item for item in evidence_value if isinstance(item, str)}
            if isinstance(evidence_value, list)
            else set()
        )
        planned_evidence = set(story.fact_ids)
        if plan.version >= 6:
            assert story.claim is not None
            expected_claim_evidence = set(story.claim.evidence.fact_ids)
            if evidence != expected_claim_evidence:
                raise ValueError(
                    f"{owner} evidence disagrees with structured claim {story.story_id}: "
                    f"missing={sorted(expected_claim_evidence - evidence)}, "
                    f"unexpected={sorted(evidence - expected_claim_evidence)}"
                )
        elif plan.version < 4:
            if evidence != planned_evidence:
                raise ValueError(f"{owner} evidence disagrees with story {story.story_id}")
        else:
            unexpected = sorted(evidence - planned_evidence)
            missing_core = sorted(set(story.core_fact_ids) - evidence)
            if not evidence or unexpected or missing_core:
                raise ValueError(
                    f"{owner} evidence disagrees with story {story.story_id}: "
                    f"missing_core={missing_core}, unexpected={unexpected}"
                )
        unused_optional = sorted(planned_evidence - set(story.core_fact_ids) - evidence)
        unused_optional_facts.update(unused_optional)
        story_evidence_item: dict[str, object] = {
            "claim_focus": story.claim_focus,
            "core_fact_ids": list(story.core_fact_ids),
            "available_fact_ids": list(story.fact_ids),
            "used_fact_ids": sorted(evidence),
            "unused_optional_fact_ids": unused_optional,
        }
        if story.claim is not None:
            story_evidence_item["claim"] = {
                "subject": story.claim.subject,
                "action": story.claim.action,
                "object": story.claim.object,
                "scope": story.claim.scope,
                "outcome": story.claim.outcome,
                "composition": story.claim.composition,
                "relationship": story.claim.relationship,
                "evidence": {
                    "action": list(story.claim.evidence.action),
                    "object": list(story.claim.evidence.object),
                    "scope": list(story.claim.evidence.scope),
                    "outcome": list(story.claim.evidence.outcome),
                },
            }
        story_evidence[story.story_id] = story_evidence_item
        return evidence

    for index, item in enumerate(payload.get("experience", [])):
        if not isinstance(item, dict):
            continue
        entry_roles = set(item.get("evidence", [])) & set(plan.progression)
        present_roles.update(entry_roles)
        for bullet_index, bullet in enumerate(item.get("bullets", [])):
            if not isinstance(bullet, dict):
                continue
            owner = f"experience[{index}].bullets[{bullet_index}]"
            story_id = bullet.get("story")
            if not isinstance(story_id, str) or story_id not in planned:
                raise ValueError(f"{owner} requires a planned story ID")
            story = planned[story_id]
            if story.section != "experience":
                raise ValueError(f"{owner} uses a non-experience story: {story_id}")
            if set(story.role_ids) != entry_roles:
                raise ValueError(f"{owner} role placement disagrees with story {story_id}")
            evidence = validate_story_evidence(bullet.get("evidence", []), story, owner)
            used.append(story_id)
            selected_fact_ids.update(evidence)

    for index, item in enumerate(payload.get("projects", [])):
        if not isinstance(item, dict):
            continue
        owner = f"projects[{index}]"
        story_id = item.get("story")
        if not isinstance(story_id, str) or story_id not in planned:
            raise ValueError(f"{owner} requires a planned story ID")
        story = planned[story_id]
        if story.section != "projects":
            raise ValueError(f"{owner} uses a non-project story: {story_id}")
        evidence = validate_story_evidence(item.get("evidence", []), story, owner)
        used.append(story_id)
        selected_fact_ids.update(evidence)

    counts = Counter(used)
    duplicate = sorted(story_id for story_id, count in counts.items() if count > 1)
    missing = sorted(set(planned) - counts.keys())
    missing_core = sorted(
        story_id for story_id in missing if planned[story_id].importance == "core"
    )
    omitted_supporting = sorted(
        story_id for story_id in missing if planned[story_id].importance == "supporting"
    )
    if duplicate:
        raise ValueError(f"synthesis stories used more than once: {duplicate}")
    if missing_core:
        raise ValueError(f"core synthesis stories absent from resume: {missing_core}")
    if plan.version >= 6:
        required_story_ids = {
            story_id for arc in plan.role_arcs for story_id in arc.required_story_ids
        }
        missing_required = sorted(required_story_ids - counts.keys())
        if missing_required:
            raise ValueError(f"required role-arc stories absent from resume: {missing_required}")
    missing_roles = sorted(set(plan.progression) - present_roles)
    if missing_roles:
        raise ValueError(f"planned progression roles absent from resume: {missing_roles}")
    used_exclusions = sorted(set(dict(plan.exclusions)) & selected_fact_ids)
    if used_exclusions:
        raise ValueError(f"excluded synthesis facts appear in resume: {used_exclusions}")
    summary_evidence = payload.get("summary_evidence", [])
    if not isinstance(summary_evidence, list):
        summary_evidence = []
    if plan.version >= 2:
        planned_summary_facts = set(plan.summary_fact_ids)
        actual_summary_facts = {item for item in summary_evidence if isinstance(item, str)}
        if actual_summary_facts != planned_summary_facts:
            missing_summary_facts = sorted(planned_summary_facts - actual_summary_facts)
            unexpected_summary_facts = sorted(actual_summary_facts - planned_summary_facts)
            raise ValueError(
                "resume summary evidence disagrees with synthesis plan: "
                f"missing={missing_summary_facts}, unexpected={unexpected_summary_facts}"
            )
        missing_body_support = sorted(set(plan.summary_body_fact_ids) - body_evidence_ids(payload))
        if missing_body_support:
            raise ValueError(
                "planned role-scoped summary facts are not demonstrated later in the resume: "
                f"{missing_body_support}"
            )
    if plan.version >= 3:
        assert plan.presentation is not None
        has_competencies = bool(payload.get("competencies"))
        should_include = plan.presentation.competencies == "include"
        if has_competencies != should_include:
            raise ValueError(
                "resume competencies section disagrees with synthesis presentation strategy: "
                f"planned={plan.presentation.competencies}, present={has_competencies}"
            )
    core_story_ids = sorted(story.story_id for story in plan.stories if story.importance == "core")
    supporting_story_ids = sorted(
        story.story_id for story in plan.stories if story.importance == "supporting"
    )
    actual_summary_facts = {item for item in summary_evidence if isinstance(item, str)}
    unused_optional_fact_ids = sorted(unused_optional_facts)
    return {
        "valid": True,
        "version": plan.version,
        "stories": len(plan.stories),
        "story_ids": sorted(planned),
        "planned_story_ids": sorted(planned),
        "used_story_ids": sorted(counts),
        "omitted_story_ids": omitted_supporting,
        "core_story_ids": core_story_ids,
        "supporting_story_ids": supporting_story_ids,
        "body_fact_ids": sorted(selected_fact_ids),
        "selected_fact_ids": sorted(selected_fact_ids | actual_summary_facts),
        "unused_optional_fact_ids": unused_optional_fact_ids,
        "story_evidence": [
            story_evidence[story_id] | {"story_id": story_id} for story_id in sorted(story_evidence)
        ],
        "summary_job": plan.summary_job,
        "summary_fact_ids": list(plan.summary_fact_ids),
        "summary_body_fact_ids": list(plan.summary_body_fact_ids),
        "progression_role_ids": list(plan.progression),
        "exclusions": len(plan.exclusions),
        "gaps": list(plan.gaps),
        "target_mode": plan.target_mode,
        "concept_fit": [
            {
                "concept_id": item.concept_id,
                "status": item.status,
                "fact_ids": list(item.fact_ids),
                "rationale": item.rationale,
            }
            for item in plan.concept_fit
        ],
        "reviewer_risks": [
            {
                "id": item.risk_id,
                "concern": item.concern,
                "status": item.status,
                "fact_ids": list(item.fact_ids),
                "planning_action": item.planning_action,
            }
            for item in plan.reviewer_risks
        ],
        "presentation": (
            {
                "competencies": plan.presentation.competencies,
                "competencies_job": plan.presentation.competencies_job,
                "compressed_role_ids": list(plan.presentation.compressed_role_ids),
            }
            if plan.presentation is not None
            else None
        ),
        "role_arcs": role_arc_payloads(plan, set(counts)),
        "page_budget": (
            {"max_pages": plan.page_budget.max_pages, "source": plan.page_budget.source}
            if plan.page_budget is not None
            else None
        ),
    }


def sha256_file(path: Path) -> str:
    """Hash a synthesis plan for the build manifest."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(argv: Sequence[str] | None = None) -> int:
    """Validate a synthesis plan independently of resume compilation."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan", type=Path)
    parser.add_argument("--vault-root", type=Path, default=Path("vault"))
    args = parser.parse_args(argv)
    try:
        vault_root = args.vault_root.expanduser().resolve()
        project_root = vault_root.parent
        plan = load_synthesis_plan(args.plan, project_root, vault_root)
        result = {
            "valid": True,
            "version": plan.version,
            "plan": plan.source.relative_to(project_root).as_posix(),
            "resume": plan.resume.relative_to(project_root).as_posix(),
            "direction": plan.direction.relative_to(project_root).as_posix(),
            "stories": len(plan.stories),
            "core_stories": sum(story.importance == "core" for story in plan.stories),
            "supporting_stories": sum(story.importance == "supporting" for story in plan.stories),
            "summary_job": plan.summary_job,
            "summary_fact_ids": list(plan.summary_fact_ids),
            "summary_body_fact_ids": list(plan.summary_body_fact_ids),
            "progression_role_ids": list(plan.progression),
            "exclusions": len(plan.exclusions),
            "gaps": list(plan.gaps),
            "target_mode": plan.target_mode,
            "concept_fit": [
                {
                    "concept_id": item.concept_id,
                    "status": item.status,
                    "fact_ids": list(item.fact_ids),
                    "rationale": item.rationale,
                }
                for item in plan.concept_fit
            ],
            "reviewer_risks": [
                {
                    "id": item.risk_id,
                    "concern": item.concern,
                    "status": item.status,
                    "fact_ids": list(item.fact_ids),
                    "planning_action": item.planning_action,
                }
                for item in plan.reviewer_risks
            ],
            "presentation": (
                {
                    "competencies": plan.presentation.competencies,
                    "competencies_job": plan.presentation.competencies_job,
                    "compressed_role_ids": list(plan.presentation.compressed_role_ids),
                }
                if plan.presentation is not None
                else None
            ),
            "role_arcs": role_arc_payloads(plan),
            "page_budget": (
                {
                    "max_pages": plan.page_budget.max_pages,
                    "source": plan.page_budget.source,
                }
                if plan.page_budget is not None
                else None
            ),
            "sha256": sha256_file(plan.source),
        }
    except (OSError, ValueError) as exc:
        print(json.dumps({"error": str(exc)}, indent=2), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
