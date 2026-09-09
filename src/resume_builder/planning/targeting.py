"""Parse target fit and reviewer-risk evidence from synthesis plans."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

from .models import (
    FIT_STATUSES,
    RISK_STATUSES,
    STORY_ID,
    TARGET_MODES,
    ConceptFit,
    ReviewerRisk,
)
from .schema import direction_concept_ids, exact_fields, nonempty_string, object_value, string_list


def parse_targeting(
    data: Mapping[str, object],
    *,
    version: int,
    direction: Path,
    facts: Mapping[str, Mapping[str, object]],
    planned_visible_facts: set[str],
    selected_facts: set[str],
    summary_fact_ids: Sequence[str],
    exclusions: Sequence[tuple[str, str]],
    gaps: Sequence[str],
) -> tuple[str | None, tuple[ConceptFit, ...], tuple[ReviewerRisk, ...]]:
    """Return the validated targeting mode, concept fit, and reviewer risks."""
    if version < 3:
        return None, (), ()

    target_mode = nonempty_string(data["target_mode"], "synthesis target_mode")
    if target_mode not in TARGET_MODES:
        raise ValueError(f"synthesis target_mode must be one of {sorted(TARGET_MODES)}")

    visible_plan_facts = planned_visible_facts if version >= 6 else selected_facts
    visible_plan_facts = set(visible_plan_facts) | set(summary_fact_ids)
    concept_fit = _parse_concept_fit(data["concept_fit"], direction, facts, visible_plan_facts)
    reviewer_risks = _parse_reviewer_risks(
        data["reviewer_risks"],
        facts,
        visible_plan_facts,
        exclusions,
        gaps,
    )
    return target_mode, concept_fit, reviewer_risks


def _parse_concept_fit(
    raw_fit: object,
    direction: Path,
    facts: Mapping[str, Mapping[str, object]],
    visible_plan_facts: set[str],
) -> tuple[ConceptFit, ...]:
    expected_concepts = direction_concept_ids(direction)
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
    return tuple(fit_entries)


def _parse_reviewer_risks(
    raw_risks: object,
    facts: Mapping[str, Mapping[str, object]],
    visible_plan_facts: set[str],
    exclusions: Sequence[tuple[str, str]],
    gaps: Sequence[str],
) -> tuple[ReviewerRisk, ...]:
    if not isinstance(raw_risks, list) or len(raw_risks) > 3:
        raise ValueError("synthesis reviewer_risks must be a list of at most three items")
    risk_entries: list[ReviewerRisk] = []
    seen_risks: set[str] = set()
    unresolved_risk = False
    excluded_fact_ids = {fact_id for fact_id, _reason in exclusions}
    for index, raw_risk in enumerate(raw_risks):
        owner = f"synthesis reviewer_risks[{index}]"
        risk = object_value(raw_risk, owner)
        exact_fields(risk, {"id", "concern", "status", "fact_ids", "planning_action"}, owner)
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
        unaccounted_risk_facts = sorted(set(risk_fact_ids) - visible_plan_facts - excluded_fact_ids)
        if unaccounted_risk_facts:
            raise ValueError(
                f"{owner} cites evidence absent from selected stories, summary, and "
                f"intentional exclusions: {unaccounted_risk_facts}"
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
    return tuple(risk_entries)
