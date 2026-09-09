"""Parse and validate synthesis-plan story selections and claim evidence."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from .models import (
    CLAIM_COMPOSITIONS,
    SECTIONS,
    STORY_ID,
    ClaimEvidence,
    ClaimSpec,
    SynthesisStory,
)
from .schema import exact_fields, nonempty_string, object_value, optional_string, string_list


def parse_stories(
    raw_stories: object,
    *,
    version: int,
    facts: Mapping[str, Mapping[str, object]],
    progression: Sequence[str],
) -> tuple[list[SynthesisStory], set[str], set[str]]:
    """Return validated stories, selected facts, and planned visible facts."""
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
    return stories, selected_facts, planned_visible_facts
