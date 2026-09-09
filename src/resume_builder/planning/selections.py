"""Parse synthesis-plan evidence selections outside individual stories."""

from __future__ import annotations

from collections.abc import Mapping

from .schema import exact_fields, nonempty_string, object_value, string_list


def parse_progression(
    raw_progression: object,
    facts: Mapping[str, Mapping[str, object]],
) -> list[str]:
    """Return a validated sequence of role fact IDs."""
    progression = string_list(raw_progression, "synthesis progression")
    unknown_progression = sorted(set(progression) - facts.keys())
    if unknown_progression:
        raise ValueError(f"synthesis progression cites unknown facts: {unknown_progression}")
    non_roles = sorted(fact_id for fact_id in progression if facts[fact_id].get("type") != "role")
    if non_roles:
        raise ValueError(f"synthesis progression must contain role facts: {non_roles}")
    return progression


def parse_summary_evidence(
    data: Mapping[str, object],
    *,
    version: int,
    facts: Mapping[str, Mapping[str, object]],
) -> tuple[str | None, list[str], list[str]]:
    """Return the summary job, all evidence, and role-scoped body evidence."""
    if version < 2:
        return None, [], []
    summary_job = nonempty_string(data["summary_job"], "synthesis summary_job")
    summary_fact_ids = string_list(data["summary_fact_ids"], "synthesis summary_fact_ids")
    unknown_summary = sorted(set(summary_fact_ids) - facts.keys())
    if unknown_summary:
        raise ValueError(f"synthesis summary cites unknown facts: {unknown_summary}")
    summary_body_fact_ids = [
        fact_id
        for fact_id in summary_fact_ids
        if facts[fact_id].get("category") == "employment" and facts[fact_id].get("scope") == "role"
    ]
    return summary_job, summary_fact_ids, summary_body_fact_ids


def parse_exclusions(
    raw_exclusions: object,
    *,
    facts: Mapping[str, Mapping[str, object]],
    selected_facts: set[str],
) -> list[tuple[str, str]]:
    """Return validated intentional fact exclusions."""
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
    return exclusions
