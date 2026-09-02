"""Parse and validate structured summary strategy for synthesis plans."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .synthesis_models import (
    STORY_ID,
    SUMMARY_FIT_POSTURES,
    TARGET_MODES,
    SummaryFitPosture,
    SummaryStrategy,
    SynthesisStory,
)
from .synthesis_schema import exact_fields, nonempty_string, object_value, string_list


def parse_summary_strategy(
    version: int,
    data: dict[str, Any],
    facts: Mapping[str, object],
    stories: Sequence[SynthesisStory],
    summary_fact_ids: Sequence[str],
) -> SummaryStrategy | None:
    """Return the version-11 strategy after checking its evidence boundaries."""
    if version < 11:
        return None
    raw_strategy = object_value(data["summary_strategy"], "synthesis summary_strategy")
    exact_fields(
        raw_strategy,
        {
            "reader_conclusion",
            "professional_frame",
            "fit_posture",
            "operating_scope_fact_ids",
            "proof_anchor_story_id",
            "delegated_to_body",
        },
        "synthesis summary_strategy",
    )
    raw_posture = object_value(
        raw_strategy["fit_posture"], "synthesis summary_strategy.fit_posture"
    )
    exact_fields(
        raw_posture,
        {"classification", "controlling_criterion_ids", "bounded_criterion_ids"},
        "synthesis summary_strategy.fit_posture",
    )
    classification = nonempty_string(
        raw_posture["classification"],
        "synthesis summary_strategy.fit_posture.classification",
    )
    if classification not in SUMMARY_FIT_POSTURES:
        raise ValueError(
            "synthesis summary_strategy.fit_posture.classification must be one of "
            f"{sorted(SUMMARY_FIT_POSTURES)}"
        )
    expected_postures = {
        "direct": {"direct", "direct-with-bounded-gaps"},
        "adjacent": {"adjacent"},
        "exploratory": {"exploratory"},
    }
    target_mode = nonempty_string(data["target_mode"], "synthesis target_mode")
    if target_mode not in TARGET_MODES or classification not in expected_postures[target_mode]:
        raise ValueError(
            "synthesis summary_strategy fit posture disagrees with target_mode: "
            f"target_mode={target_mode}, classification={classification}"
        )
    controlling_ids = string_list(
        raw_posture["controlling_criterion_ids"],
        "synthesis summary_strategy.fit_posture.controlling_criterion_ids",
        required=False,
    )
    bounded_ids = string_list(
        raw_posture["bounded_criterion_ids"],
        "synthesis summary_strategy.fit_posture.bounded_criterion_ids",
        required=False,
    )
    invalid_ids = sorted(
        item for item in {*controlling_ids, *bounded_ids} if not STORY_ID.fullmatch(item)
    )
    if invalid_ids:
        raise ValueError(
            "synthesis summary_strategy criterion ids must use lowercase hyphenated "
            f"identifiers: {invalid_ids}"
        )
    overlap = sorted(set(controlling_ids) & set(bounded_ids))
    if overlap:
        raise ValueError(
            f"synthesis summary_strategy criteria cannot be both controlling and bounded: {overlap}"
        )
    if classification == "direct" and (controlling_ids or bounded_ids):
        raise ValueError(
            "synthesis direct summary fit posture cannot declare controlling or bounded gaps"
        )
    if classification == "direct-with-bounded-gaps" and (controlling_ids or not bounded_ids):
        raise ValueError(
            "synthesis direct-with-bounded-gaps posture requires bounded criteria and "
            "forbids controlling criteria"
        )

    operating_scope_fact_ids = string_list(
        raw_strategy["operating_scope_fact_ids"],
        "synthesis summary_strategy.operating_scope_fact_ids",
    )
    unknown_scope_facts = sorted(set(operating_scope_fact_ids) - facts.keys())
    if unknown_scope_facts:
        raise ValueError(
            f"synthesis summary_strategy operating scope cites unknown facts: {unknown_scope_facts}"
        )
    non_summary_scope = sorted(set(operating_scope_fact_ids) - set(summary_fact_ids))
    if non_summary_scope:
        raise ValueError(
            "synthesis summary_strategy operating scope must be included in "
            f"summary_fact_ids: {non_summary_scope}"
        )

    proof_anchor_story_id = nonempty_string(
        raw_strategy["proof_anchor_story_id"],
        "synthesis summary_strategy.proof_anchor_story_id",
    )
    proof_story = {story.story_id: story for story in stories}.get(proof_anchor_story_id)
    if proof_story is None:
        raise ValueError(
            "synthesis summary_strategy.proof_anchor_story_id must reference a planned "
            f"story: {proof_anchor_story_id}"
        )
    missing_proof_facts = sorted(set(proof_story.core_fact_ids) - set(summary_fact_ids))
    if missing_proof_facts:
        raise ValueError(
            "synthesis summary_strategy proof anchor core facts must be included in "
            f"summary_fact_ids: {missing_proof_facts}"
        )

    return SummaryStrategy(
        reader_conclusion=nonempty_string(
            raw_strategy["reader_conclusion"], "synthesis summary_strategy.reader_conclusion"
        ),
        professional_frame=nonempty_string(
            raw_strategy["professional_frame"], "synthesis summary_strategy.professional_frame"
        ),
        fit_posture=SummaryFitPosture(
            classification=classification,
            controlling_criterion_ids=tuple(controlling_ids),
            bounded_criterion_ids=tuple(bounded_ids),
        ),
        operating_scope_fact_ids=tuple(operating_scope_fact_ids),
        proof_anchor_story_id=proof_anchor_story_id,
        delegated_to_body=tuple(
            string_list(
                raw_strategy["delegated_to_body"],
                "synthesis summary_strategy.delegated_to_body",
                required=False,
            )
        ),
    )
