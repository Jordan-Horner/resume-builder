"""Parse and validate synthesis-plan role-arc allocations."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from .models import (
    ROLE_ARC_EMPHASES,
    STORY_ID,
    OmittedRoleSignal,
    PresentationStrategy,
    RoleArc,
    SynthesisStory,
)
from .schema import (
    core_job_assessment,
    exact_fields,
    nonempty_string,
    object_value,
    role_arc_fields,
    role_story_classes,
    string_list,
)


def parse_role_arcs(
    raw_role_arcs: object,
    *,
    version: int,
    presentation: PresentationStrategy | None,
    progression: Sequence[str],
    stories: Sequence[SynthesisStory],
    facts: Mapping[str, Mapping[str, object]],
) -> tuple[RoleArc, ...]:
    """Return validated role-arc allocations for one synthesis plan."""
    if version < 5:
        return ()
    assert presentation is not None
    if not isinstance(raw_role_arcs, list) or not raw_role_arcs:
        raise ValueError("synthesis role_arcs must be a non-empty list")
    story_by_id = {story.story_id: story for story in stories}
    experience_story_ids = {story.story_id for story in stories if story.section == "experience"}
    arc_entries: list[RoleArc] = []
    seen_placements: set[tuple[str, ...]] = set()
    allocated_story_ids: set[str] = set()
    roles_in_arcs: set[str] = set()
    compressed_arc_roles: set[str] = set()
    lead_arc_found = False
    for index, raw_arc in enumerate(raw_role_arcs):
        owner = f"synthesis role_arcs[{index}]"
        arc = object_value(raw_arc, owner)
        exact_fields(arc, role_arc_fields(version), owner)
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
        role_anchor_story_ids, role_selling_story_ids = role_story_classes(
            arc, owner, required_story_ids, version
        )
        core_job_candidates, selected_core_job_id, core_job_decision = core_job_assessment(
            arc, owner, version
        )
        unknown_arc_stories = sorted(set(arc_story_ids) - experience_story_ids)
        if unknown_arc_stories:
            raise ValueError(
                f"{owner}.story_ids must reference experience stories: {unknown_arc_stories}"
            )
        if version < 6:
            required_story_ids = [
                story_id for story_id in arc_story_ids if story_by_id[story_id].importance == "core"
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
            required_jobs = {story_by_id[story_id].primary_job for story_id in required_story_ids}
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
                role_anchor_story_ids=tuple(role_anchor_story_ids),
                role_selling_story_ids=tuple(role_selling_story_ids),
                core_job_candidates=tuple(core_job_candidates),
                selected_core_job_id=selected_core_job_id,
                core_job_decision=core_job_decision,
            )
        )

    missing_allocations = sorted(experience_story_ids - allocated_story_ids)
    if missing_allocations:
        raise ValueError(
            f"synthesis experience stories missing from role_arcs: {missing_allocations}"
        )
    missing_arc_roles = sorted(set(progression) - roles_in_arcs)
    if missing_arc_roles:
        raise ValueError(f"synthesis progression roles missing from role_arcs: {missing_arc_roles}")
    if not lead_arc_found:
        raise ValueError("synthesis role_arcs must identify at least one lead arc")
    planned_compressed_roles = set(presentation.compressed_role_ids)
    if compressed_arc_roles != planned_compressed_roles:
        raise ValueError(
            "synthesis role_arcs compressed emphasis disagrees with presentation: "
            f"role_arcs={sorted(compressed_arc_roles)}, "
            f"presentation={sorted(planned_compressed_roles)}"
        )
    return tuple(arc_entries)
