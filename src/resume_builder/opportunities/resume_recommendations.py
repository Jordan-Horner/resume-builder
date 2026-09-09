"""Match active directional resumes to an existing criterion-driven job screen."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from ..matching.grading import classify_match
from ..resume_documents.markdown import compile_markdown
from ..vault.evidence import claim_blocks

ResumeMatchLabel = Literal["Strong match", "Partial match", "Weak match", "Unknown match"]
ResumeText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DirectionalResumeCandidate(_StrictModel):
    """The minimum local resume identity needed for deterministic matching."""

    resume_id: ResumeText
    name: ResumeText
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    fact_ids: list[ResumeText] = Field(default_factory=list, max_length=500)


class ResumeMatchAlternative(_StrictModel):
    resume_id: ResumeText
    name: ResumeText
    label: ResumeMatchLabel


class ResumeMatchSummary(_StrictModel):
    """Presentation-safe result from the shared CLI classifier."""

    resume_id: ResumeText
    name: ResumeText
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    label: ResumeMatchLabel
    strongest_overlap: list[ResumeText] = Field(default_factory=list, max_length=3)
    primary_gap: ResumeText | None = None
    alternative: ResumeMatchAlternative | None = None


class ResumeMatchGuidance(_StrictModel):
    """Actionable explanation when no single directional resume can be selected."""

    status: Literal["multiple-matches", "needs-tailoring", "no-resumes", "not-enough-evidence"]
    label: ResumeText
    detail: ResumeText


def load_directional_resume_candidates(workspace: Path) -> list[DirectionalResumeCandidate]:
    """Load valid, active directional resumes; archived and tailored files stay out."""
    candidates: list[DirectionalResumeCandidate] = []
    root = workspace.expanduser().resolve()
    for path in sorted((root / "resumes" / "baselines").glob("*.md")):
        if path.name.casefold() == "readme.md":
            continue
        try:
            content = path.read_text(encoding="utf-8")
            payload = compile_markdown(content)
        except (OSError, ValueError):
            continue
        candidate = payload.get("candidate")
        headline = candidate.get("headline") if isinstance(candidate, dict) else None
        facts = sorted(
            {fact_id for _, _, evidence_ids, _ in claim_blocks(payload) for fact_id in evidence_ids}
        )
        candidates.append(
            DirectionalResumeCandidate(
                resume_id=path.relative_to(root).as_posix(),
                name=(
                    str(headline).strip()
                    if isinstance(headline, str) and headline.strip()
                    else path.stem.replace("-", " ").title()
                ),
                sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(),
                fact_ids=facts,
            )
        )
    return candidates


def resume_revision(candidates: Sequence[DirectionalResumeCandidate]) -> str:
    """Hash the complete active directional set for screen-cache invalidation."""
    digest = hashlib.sha256()
    for candidate in candidates:
        digest.update(candidate.resume_id.encode("utf-8"))
        digest.update(candidate.sha256.encode("ascii"))
    return digest.hexdigest()


def _classification_for_candidate(
    candidate: DirectionalResumeCandidate,
    criteria: Sequence[Any],
    assessments: dict[str, Any],
    *,
    posting_complete: bool,
) -> dict[str, Any]:
    resume_facts = set(candidate.fact_ids)
    judgments: list[dict[str, Any]] = []
    for criterion in criteria:
        assessment = assessments.get(str(criterion.criterion_id))
        cited_facts = set(assessment.fact_ids) if assessment is not None else set()
        visible_facts = sorted(cited_facts & resume_facts)
        outcome = str(assessment.outcome) if assessment is not None else "unknown"
        if outcome == "supported" and visible_facts:
            status = "met"
        elif outcome in {"partially_supported", "transferable"} and visible_facts:
            status = "partial"
        elif outcome == "unknown":
            status = "undecidable"
        elif outcome == "apparent_gap" and visible_facts:
            status = "not_met"
        else:
            # The shared screen retrieves only a bounded candidate set. A cited fact that
            # is absent from this resume is not proof that the resume lacks all support.
            status = "undecidable"
        judgments.append(
            {
                "criterion_id": str(criterion.criterion_id),
                "importance": str(criterion.importance),
                "requirement_type": str(criterion.requirement_type),
                "status": status,
                "evidence_sufficiency": (
                    "high" if status == "met" else "medium" if status == "partial" else "low"
                ),
                "confidence": str(assessment.confidence) if assessment is not None else "low",
                "evidence_blocks": [candidate.resume_id] if visible_facts else [],
                "evidence_fact_ids": visible_facts,
                "substitution_basis": (
                    str(criterion.description)
                    if str(criterion.requirement_type) == "mandatory-substitutable"
                    else ""
                ),
                "gap": "" if status == "met" else str(criterion.label),
            }
        )
    evidence_complete = posting_complete and all(
        item["status"] != "undecidable" for item in judgments if item["importance"] == "required"
    )
    return classify_match(
        {
            "version": 1,
            "evidence_complete": evidence_complete,
            "criteria": judgments,
        }
    )


def classify_directional_resumes(
    candidates: Sequence[DirectionalResumeCandidate],
    criteria: Sequence[Any],
    assessments: Sequence[Any],
    *,
    posting_complete: bool,
) -> ResumeMatchSummary | None:
    """Select the closest active direction using the CLI's gate-first labels."""
    evaluable = [item for item in criteria if str(item.status) != "not-resume-evaluable"]
    if not candidates or not evaluable:
        return None
    by_criterion = {str(item.criterion_id): item for item in assessments}
    labels = {"Strong match": 3, "Partial match": 2, "Weak match": 1, "Unknown match": 0}
    ranked: list[tuple[tuple[int, int, int, str], DirectionalResumeCandidate, dict[str, Any]]] = []
    for candidate in candidates:
        classification = _classification_for_candidate(
            candidate,
            evaluable,
            by_criterion,
            posting_complete=posting_complete,
        )
        met = sum(item["status"] == "met" for item in classification["criteria"])
        partial = sum(item["status"] == "partial" for item in classification["criteria"])
        rank = (labels[classification["label"]], met, partial, candidate.resume_id)
        ranked.append((rank, candidate, classification))
    ranked.sort(key=lambda item: item[0], reverse=True)
    _, winner, classification = ranked[0]
    criterion_labels = {str(item.criterion_id): str(item.label) for item in evaluable}
    strongest = [
        criterion_labels[item["criterion_id"]]
        for item in classification["criteria"]
        if item["status"] in {"met", "partial"}
    ][:3]
    controlling = classification["controlling_criterion_ids"]
    primary_gap = criterion_labels.get(controlling[0]) if controlling else None
    alternative = None
    if len(ranked) > 1:
        _, runner_up, runner_classification = ranked[1]
        alternative = ResumeMatchAlternative(
            resume_id=runner_up.resume_id,
            name=runner_up.name,
            label=runner_classification["label"],
        )
    return ResumeMatchSummary(
        resume_id=winner.resume_id,
        name=winner.name,
        sha256=winner.sha256,
        label=classification["label"],
        strongest_overlap=strongest,
        primary_gap=primary_gap,
        alternative=alternative,
    )


def match_directional_resumes_by_cited_facts(
    candidates: Sequence[DirectionalResumeCandidate],
    supporting_fact_ids: Sequence[str],
) -> ResumeMatchSummary | None:
    """Name a posting-wide closest resume only when cited evidence has one clear winner."""
    cited = set(supporting_fact_ids)
    if not candidates or not cited:
        return None
    ranked = sorted(
        ((len(cited & set(candidate.fact_ids)), candidate) for candidate in candidates),
        key=lambda item: (-item[0], item[1].resume_id),
    )
    top_overlap, winner = ranked[0]
    if top_overlap == 0 or (len(ranked) > 1 and ranked[1][0] == top_overlap):
        return None

    def label(overlap: int) -> ResumeMatchLabel:
        return "Strong match" if overlap == len(cited) and len(cited) >= 2 else "Partial match"

    alternative = None
    if len(ranked) > 1 and ranked[1][0] > 0:
        runner_overlap, runner_up = ranked[1]
        if len(ranked) == 2 or ranked[2][0] != runner_overlap:
            alternative = ResumeMatchAlternative(
                resume_id=runner_up.resume_id,
                name=runner_up.name,
                label=label(runner_overlap),
            )
    return ResumeMatchSummary(
        resume_id=winner.resume_id,
        name=winner.name,
        sha256=winner.sha256,
        label=label(top_overlap),
        alternative=alternative,
    )


def resume_match_guidance(
    candidates: Sequence[DirectionalResumeCandidate],
    supporting_fact_ids: Sequence[str],
    match: ResumeMatchSummary | None,
) -> ResumeMatchGuidance | None:
    """Explain the vault-backed resume decision when the matcher cannot name a winner."""
    if match is not None:
        return None
    cited = set(supporting_fact_ids)
    if not candidates:
        return ResumeMatchGuidance(
            status="no-resumes",
            label="Build a resume",
            detail="The vault has relevant evidence, but there are no active directional resumes to compare.",
        )
    if not cited:
        return ResumeMatchGuidance(
            status="not-enough-evidence",
            label="Not enough evidence",
            detail="The screen did not cite enough verified vault evidence to assess resume coverage.",
        )
    overlaps = [len(cited & set(candidate.fact_ids)) for candidate in candidates]
    top_overlap = max(overlaps)
    fact_label = "fact" if len(cited) == 1 else "facts"
    if top_overlap == 0:
        return ResumeMatchGuidance(
            status="needs-tailoring",
            label="Needs tailoring",
            detail=(
                f"{len(cited)} verified vault {fact_label} support this job, but none appears in "
                "a current resume. Tailor one from the vault before applying."
            ),
        )
    tied_count = sum(overlap == top_overlap for overlap in overlaps)
    if tied_count > 1:
        return ResumeMatchGuidance(
            status="multiple-matches",
            label="Multiple matches",
            detail=(
                f"{tied_count} current resumes cover the same share of {len(cited)} verified "
                f"vault {fact_label}, so there is no single best choice. Compare or tailor them "
                "before applying."
            ),
        )
    return ResumeMatchGuidance(
        status="needs-tailoring",
        label="Needs tailoring",
        detail=(
            f"{len(cited)} verified vault {fact_label} support this job, but no current resume "
            "represents them clearly enough. Tailor one from the vault before applying."
        ),
    )
