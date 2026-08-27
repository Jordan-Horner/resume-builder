from __future__ import annotations

from datetime import datetime

from .config import SearchSettings
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


def title_matches(title: str, titles: list[str]) -> bool:
    normalized_title = f" {normalized_key(title)} "
    return any(
        f" {normalized_key(candidate)} " in normalized_title
        for candidate in titles
        if normalized_key(candidate)
    )


def enabled_titles(search: SearchSettings) -> list[str]:
    return [title for family in search.families if family.enabled for title in family.titles]


def family_keyword_queries(search: SearchSettings) -> list[str]:
    queries = []
    for family in search.families:
        if not family.enabled:
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
