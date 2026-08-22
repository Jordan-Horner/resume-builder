"""Immutable models and constants for versioned synthesis plans."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

STORY_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
SECTIONS = {"experience", "projects"}
TARGET_MODES = {"direct", "adjacent", "exploratory"}
FIT_STATUSES = {"demonstrated", "transferable", "unsupported"}
RISK_STATUSES = {"resolved", "partial", "unresolved"}
COMPETENCY_DECISIONS = {"include", "omit"}
ROLE_ARC_EMPHASES = {"lead", "supporting", "compressed"}
CLAIM_COMPOSITIONS = {"single-fact", "same-system", "sequence", "aggregate"}
PAGE_BUDGET_SOURCES = {"direction-default", "user"}
RESUME_SECTIONS = {
    "summary",
    "competencies",
    "experience",
    "projects",
    "education",
    "certifications",
    "skills",
}


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
class ContentTemplate:
    """Reusable section architecture selected by a synthesis plan."""

    template_id: str
    source: Path
    section_order: tuple[str, ...]
    required_sections: tuple[str, ...]
    optional_sections: tuple[str, ...]
    forbidden_sections: tuple[str, ...]
    version: int = 1
    display_name: str | None = None
    description: str | None = None


@dataclass(frozen=True)
class RenderingTheme:
    """Reusable visual theme kept separate from content architecture."""

    theme_id: str
    source: Path
    renderer: Path
    version: int = 1
    display_name: str | None = None
    description: str | None = None
    category: str | None = None
    stylesheet: Path | None = None


@dataclass(frozen=True)
class ResumeTemplateSelection:
    """Named content-template and visual-theme choice for one resume."""

    content: ContentTemplate
    theme: RenderingTheme


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
class CoreJobCandidate:
    """One evidence-based interpretation of a role's core job."""

    candidate_id: str
    description: str
    confidence: int


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
    role_anchor_story_ids: tuple[str, ...] = ()
    role_selling_story_ids: tuple[str, ...] = ()
    core_job_candidates: tuple[CoreJobCandidate, ...] = ()
    selected_core_job_id: str | None = None
    core_job_decision: str | None = None


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
    resume_template: ResumeTemplateSelection | None = None
