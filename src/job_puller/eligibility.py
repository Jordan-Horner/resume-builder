from __future__ import annotations

from datetime import datetime

from .config import SearchFamily, SearchSettings
from .models import JobObservation
from .normalize import normalized_key
from .work_modes import WorkMode

GENERIC_TITLE_TERMS = {
    "engineer",
    "developer",
    "senior",
    "sr",
    "lead",
    "staff",
    "principal",
}


def title_matches(
    title: str,
    titles: list[str],
    excluded_titles: list[str] | None = None,
) -> bool:
    normalized_title = f" {normalized_key(title)} "
    accepted = any(
        f" {normalized_key(candidate)} " in normalized_title
        for candidate in titles
        if normalized_key(candidate)
    )
    excluded = any(
        f" {normalized_key(candidate)} " in normalized_title
        for candidate in (excluded_titles or [])
        if normalized_key(candidate)
    )
    return accepted and not excluded


def matches_enabled_family(title: str, search: SearchSettings) -> bool:
    return any(
        family.enabled
        and not family.commercial_only
        and title_matches(title, family.accepted_titles, family.excluded_titles)
        for family in search.families
    )


def commercial_title_matches(title: str, family: SearchFamily) -> bool:
    """Apply the configured admission policy to one query-scoped commercial result."""
    return family.commercial_admission == "query_result" or title_matches(
        title, family.accepted_titles, family.excluded_titles
    )


def family_keyword_queries(search: SearchSettings) -> list[str]:
    queries = []
    for family in search.families:
        if not family.enabled or family.commercial_only:
            continue
        terms: list[str] = []
        for title in family.titles:
            for term in normalized_key(title).split():
                if term not in GENERIC_TITLE_TERMS and term not in terms:
                    terms.append(term)
        queries.append(" ".join(terms) or family.titles[0])
    return queries


def remote_matches(observation: JobObservation, search: SearchSettings) -> bool:
    accepted = search.accepted_work_modes or {WorkMode.REMOTE}
    return bool(observation.work_modes & accepted)


def recent_matches(observation: JobObservation, since: datetime) -> bool:
    return observation.posted_at is None or observation.posted_at >= since
