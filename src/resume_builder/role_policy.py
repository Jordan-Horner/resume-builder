"""Shared role identity, title validation, and discovery query capacity."""

from collections.abc import Iterable

from job_puller.normalize import normalized_key

from .discovery_portfolio import MAX_TOTAL_QUERIES

MIN_TITLE_LENGTH = 2
MAX_TITLE_LENGTH = 150


def clean_titles(values: object, *, allow_empty: bool = False) -> list[str]:
    if not isinstance(values, list):
        raise ValueError("job titles must be a list")
    titles: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, str):
            raise ValueError("job titles must be text")
        title = " ".join(value.split())
        if not MIN_TITLE_LENGTH <= len(title) <= MAX_TITLE_LENGTH or not normalized_key(title):
            raise ValueError(
                "job titles must be between 2 and 150 characters and contain letters or numbers"
            )
        key = normalized_key(title)
        if key not in seen:
            titles.append(title)
            seen.add(key)
    if not titles and not allow_empty:
        raise ValueError("add at least one job title")
    check_query_capacity(titles)
    return titles


def check_query_capacity(queries: Iterable[str]) -> int:
    count = len({normalized_key(query) for query in queries})
    if count > MAX_TOTAL_QUERIES:
        raise ValueError(
            f"you can search at most {MAX_TOTAL_QUERIES} unique roles and skills; remove one before adding another"
        )
    return MAX_TOTAL_QUERIES - count
