"""Diagnose materially backward-weighted experience allocations."""

from __future__ import annotations

import re
from typing import Any, TypedDict

from .synthesis_models import RoleArc, SynthesisPlan, SynthesisStory

WORD = re.compile(r"\b[\w'-]+\b")
EMPHASIS_RANK = {"compressed": 0, "supporting": 1, "lead": 2}


class Placement(TypedDict):
    """Visible story allocation for one experience entry."""

    experience_index: int
    role_ids: list[str]
    emphasis: str
    story_ids: list[str]
    story_count: int
    word_count: int
    story_word_counts: dict[str, int]


def _word_count(value: object) -> int:
    return len(WORD.findall(value)) if isinstance(value, str) else 0


def _placement(
    index: int,
    item: dict[str, Any],
    arcs_by_story: dict[str, RoleArc],
) -> Placement | None:
    bullets = item.get("bullets")
    if not isinstance(bullets, list):
        return None
    story_ids: list[str] = []
    word_count = 0
    story_word_counts: dict[str, int] = {}
    arcs: list[RoleArc] = []
    for bullet in bullets:
        if not isinstance(bullet, dict):
            continue
        story_id = bullet.get("story")
        if not isinstance(story_id, str) or story_id not in arcs_by_story:
            continue
        story_ids.append(story_id)
        bullet_words = _word_count(bullet.get("text"))
        word_count += bullet_words
        story_word_counts[story_id] = bullet_words
        arc = arcs_by_story[story_id]
        if arc not in arcs:
            arcs.append(arc)
    if not story_ids:
        return None
    emphasis = max((arc.emphasis for arc in arcs), key=EMPHASIS_RANK.__getitem__)
    role_ids = list(dict.fromkeys(role_id for arc in arcs for role_id in arc.role_ids))
    return {
        "experience_index": index,
        "role_ids": role_ids,
        "emphasis": emphasis,
        "story_ids": story_ids,
        "story_count": len(story_ids),
        "word_count": word_count,
        "story_word_counts": story_word_counts,
    }


def role_balance_diagnostic(
    payload: dict[str, Any],
    plan: SynthesisPlan,
) -> dict[str, object]:
    """Return an advisory allocation diagnosis without changing selected content."""
    method = {
        "comparison": "older visible experience placements against the largest lead allocation",
        "material_inversion": ("story_surplus >= 2, or story_surplus >= 1 with word_ratio >= 1.75"),
        "automatic_scope": "selected supporting stories declared optional by the role arc",
    }
    if plan.version < 5 or not plan.role_arcs:
        return {
            "status": "not-applicable",
            "advisory_only": True,
            "reason": "role-balance diagnosis requires role arcs from synthesis version 5 or later",
            "method": method,
            "placements": [],
            "inversions": [],
        }

    arcs_by_story = {story_id: arc for arc in plan.role_arcs for story_id in arc.story_ids}
    experience = payload.get("experience")
    placements: list[Placement] = [
        placement
        for index, item in enumerate(experience if isinstance(experience, list) else [])
        if isinstance(item, dict)
        if (placement := _placement(index, item, arcs_by_story)) is not None
    ]
    lead_placements = [item for item in placements if item["emphasis"] == "lead"]
    if not lead_placements:
        return {
            "status": "not-applicable",
            "advisory_only": True,
            "reason": "no visible lead experience allocation was found",
            "method": method,
            "placements": placements,
            "inversions": [],
        }
    reference = max(
        lead_placements,
        key=lambda item: (item["story_count"], item["word_count"]),
    )
    story_by_id: dict[str, SynthesisStory] = {story.story_id: story for story in plan.stories}
    inversions: list[dict[str, object]] = []
    for older in placements:
        if older["experience_index"] <= reference["experience_index"]:
            continue
        story_surplus = older["story_count"] - reference["story_count"]
        word_ratio = older["word_count"] / max(reference["word_count"], 1)
        if not (story_surplus >= 2 or (story_surplus >= 1 and word_ratio >= 1.75)):
            continue
        older_story_ids = older["story_ids"]
        matching_arcs = {
            arcs_by_story[story_id] for story_id in older_story_ids if story_id in arcs_by_story
        }
        optional_ids = {story_id for arc in matching_arcs for story_id in arc.optional_story_ids}
        required_ids = {story_id for arc in matching_arcs for story_id in arc.required_story_ids}
        auto_candidates = [
            story_id
            for story_id in older_story_ids
            if story_id in optional_ids
            and story_id not in required_ids
            and story_by_id[story_id].importance == "supporting"
        ]
        auto_candidates.sort(
            key=lambda story_id: (story_by_id[story_id].priority, older_story_ids.index(story_id))
        )
        protected_ids = [
            story_id for story_id in older_story_ids if story_id not in auto_candidates
        ]
        protected_ids.sort(
            key=lambda story_id: (story_by_id[story_id].priority, older_story_ids.index(story_id))
        )
        ordered_candidates = [*auto_candidates, *protected_ids]
        remaining_count = older["story_count"]
        remaining_words = older["word_count"]
        required_reduction = len(ordered_candidates)
        story_word_counts = older["story_word_counts"]
        for candidate_index, story_id in enumerate(ordered_candidates, start=1):
            remaining_count -= 1
            remaining_words -= story_word_counts.get(story_id, 0)
            remaining_surplus = remaining_count - reference["story_count"]
            remaining_ratio = remaining_words / max(reference["word_count"], 1)
            if not (remaining_surplus >= 2 or (remaining_surplus >= 1 and remaining_ratio >= 1.75)):
                required_reduction = candidate_index
                break
        resolution = (
            "reviewer-decision" if len(auto_candidates) >= required_reduction else "user-decision"
        )
        inversions.append(
            {
                "reference_role_ids": reference["role_ids"],
                "older_role_ids": older["role_ids"],
                "reference_story_count": reference["story_count"],
                "older_story_count": older["story_count"],
                "reference_word_count": reference["word_count"],
                "older_word_count": older["word_count"],
                "story_surplus": story_surplus,
                "word_ratio": round(word_ratio, 2),
                "required_reduction": required_reduction,
                "automatic_candidate_story_ids": auto_candidates,
                "protected_story_ids": protected_ids,
                "candidate_stories": [
                    {
                        "id": story_id,
                        "primary_job": story_by_id[story_id].primary_job,
                        "claim_focus": story_by_id[story_id].claim_focus,
                        "priority": story_by_id[story_id].priority,
                    }
                    for story_id in ordered_candidates
                ],
                "resolution": resolution,
            }
        )
    status = (
        "user-decision"
        if any(item["resolution"] == "user-decision" for item in inversions)
        else "reviewer-decision"
        if inversions
        else "no-inversion-detected"
    )
    return {
        "status": status,
        "advisory_only": True,
        "method": method,
        "reference": reference,
        "placements": placements,
        "inversions": inversions,
    }
