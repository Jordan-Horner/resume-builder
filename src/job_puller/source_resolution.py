from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

from .config import AtsBoard
from .database import InventoryDatabase
from .models import JobObservation
from .normalize import normalized_key
from .providers import AshbyProvider, GreenhouseProvider, LeverProvider
from .providers.ats import HttpProvider
from .work_modes import WorkMode

DATASET_REVISION = "ecb67960f3e3f87b832efab823a479d4d64a2c07"
DATASET_BASE = (
    f"https://raw.githubusercontent.com/Feashliaa/job-board-aggregator/{DATASET_REVISION}/data"
)
DATASETS = {
    "greenhouse": f"{DATASET_BASE}/greenhouse_companies.json",
    "lever": f"{DATASET_BASE}/lever_companies.json",
    "ashby": f"{DATASET_BASE}/ashby_companies.json",
}
SLUG = re.compile(r"^[A-Za-z0-9._-]+$")
LEGAL_SUFFIXES = {
    "co",
    "company",
    "corp",
    "corporation",
    "inc",
    "incorporated",
    "limited",
    "llc",
    "llp",
    "ltd",
    "plc",
}
PROVIDER_CLASSES: dict[str, type[HttpProvider]] = {
    "greenhouse": GreenhouseProvider,
    "ashby": AshbyProvider,
    "lever": LeverProvider,
}


@dataclass(frozen=True, slots=True)
class LinkedInTarget:
    job_id: str
    observation_id: str
    title: str
    company: str
    location: str
    description: str
    posted_at: datetime | None


@dataclass(frozen=True, slots=True)
class BoardCandidate:
    provider: str
    board_id: str
    company: str
    api_url: str | None = None
    origin: str = "catalog"


@dataclass(frozen=True, slots=True)
class PostingMatch:
    target: LinkedInTarget
    observation: JobObservation
    confidence: float
    reason: str


@dataclass(slots=True)
class ResolutionReport:
    targets: int = 0
    companies: int = 0
    boards_considered: int = 0
    boards_fetched: int = 0
    boards_failed: int = 0
    postings_scanned: int = 0
    matches: list[dict[str, Any]] = field(default_factory=list)
    applied: int = 0

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class CatalogError(ValueError):
    pass


class AtsCatalog:
    """Validated, cached index of public ATS board identifiers."""

    def __init__(self, entries: dict[str, tuple[str, ...]]):
        self.entries = entries

    @classmethod
    def load(
        cls,
        cache_dir: Path,
        *,
        timeout: float = 30,
        max_age: timedelta = timedelta(hours=24),
        client: httpx.Client | None = None,
    ) -> AtsCatalog:
        cache_dir.mkdir(parents=True, exist_ok=True)
        owns_client = client is None
        client = client or httpx.Client(timeout=timeout, follow_redirects=True)
        loaded: dict[str, tuple[str, ...]] = {}
        try:
            for provider, url in DATASETS.items():
                path = cache_dir / f"{provider}.json"
                fresh = path.exists() and (
                    datetime.now(UTC).timestamp() - path.stat().st_mtime <= max_age.total_seconds()
                )
                if fresh:
                    payload = json.loads(path.read_text(encoding="utf-8"))
                else:
                    try:
                        response = client.get(url)
                        response.raise_for_status()
                        payload = response.json()
                    except (httpx.HTTPError, json.JSONDecodeError):
                        if not path.exists():
                            raise
                        payload = json.loads(path.read_text(encoding="utf-8"))
                    else:
                        _validate_catalog(provider, payload)
                        path.write_text(
                            json.dumps(payload, separators=(",", ":")), encoding="utf-8"
                        )
                loaded[provider] = _validate_catalog(provider, payload)
        finally:
            if owns_client:
                client.close()
        return cls(loaded)

    def boards_for(self, company: str, *, include_probes: bool = False) -> list[BoardCandidate]:
        variants = company_slug_candidates(company)
        compact = variants[-1] if variants else ""
        candidates: list[BoardCandidate] = []
        for provider in ("greenhouse", "ashby", "lever"):
            catalog = self.entries.get(provider, ())
            catalog_matches = [entry for entry in catalog if entry.casefold() in variants]
            if compact and len(compact) >= 5:
                catalog_matches.extend(
                    entry
                    for entry in catalog
                    if _compact_slug(entry).startswith(compact)
                    and len(_compact_slug(entry)) <= len(compact) + 15
                )
            seen: set[str] = set()
            for board_id in catalog_matches[:5]:
                if board_id.casefold() in seen:
                    continue
                seen.add(board_id.casefold())
                candidates.append(BoardCandidate(provider, board_id, company))
            if include_probes:
                for board_id in variants[:2]:
                    if board_id.casefold() not in seen:
                        candidates.append(
                            BoardCandidate(provider, board_id, company, origin="company-slug-probe")
                        )
        unique: dict[tuple[str, str], BoardCandidate] = {}
        for candidate in candidates:
            unique.setdefault((candidate.provider, candidate.board_id.casefold()), candidate)
        return list(unique.values())


def _validate_catalog(provider: str, payload: Any) -> tuple[str, ...]:
    if not isinstance(payload, list):
        raise CatalogError(f"{provider} catalog must be a JSON list")
    result: list[str] = []
    for value in payload:
        if not isinstance(value, str):
            raise CatalogError(f"{provider} catalog contains a non-string entry")
        if not SLUG.fullmatch(value):
            raise CatalogError(f"invalid {provider} board identifier: {value!r}")
        result.append(value)
    return tuple(dict.fromkeys(result))


def _compact_slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.casefold())


def company_slug_candidates(company: str) -> tuple[str, ...]:
    tokens = normalized_key(company).split()
    while tokens and tokens[-1] in LEGAL_SUFFIXES:
        tokens.pop()
    if not tokens:
        return ()
    hyphenated = "-".join(tokens)
    compact = "".join(tokens)
    candidates = [hyphenated]
    if compact != hyphenated:
        candidates.append(compact)
    return tuple(candidate for candidate in dict.fromkeys(candidates) if SLUG.fullmatch(candidate))


def _description_similarity(left: str, right: str) -> float:
    def shingles(value: str) -> set[tuple[str, str, str]]:
        tokens = normalized_key(value).split()
        return set(zip(tokens, tokens[1:], tokens[2:], strict=False))

    left_shingles = shingles(left)
    right_shingles = shingles(right)
    if len(left_shingles) < 25 or len(right_shingles) < 25:
        return 0.0
    overlap = len(left_shingles & right_shingles)
    return overlap / min(len(left_shingles), len(right_shingles))


def match_posting(
    target: LinkedInTarget, observations: list[JobObservation]
) -> PostingMatch | None:
    title = normalized_key(target.title)
    ranked = []
    for observation in observations:
        if normalized_key(observation.title) != title:
            continue
        similarity = _description_similarity(target.description, observation.description_text)
        if similarity >= 0.85:
            ranked.append((similarity, observation))
    ranked.sort(key=lambda item: item[0], reverse=True)
    if not ranked:
        return None
    if len(ranked) > 1 and ranked[0][0] - ranked[1][0] < 0.08:
        return None
    similarity, observation = ranked[0]
    modes = observation.work_modes
    if not modes or modes == frozenset({WorkMode.UNKNOWN}):
        return None
    confidence = min(0.99, 0.92 + (similarity - 0.85) * 0.5)
    return PostingMatch(
        target,
        observation,
        confidence,
        "exact_company_board_and_title_with_description_overlap",
    )


def _provider(candidate: BoardCandidate, timeout: float) -> HttpProvider:
    board = AtsBoard(
        id=candidate.board_id,
        name=candidate.company,
        api_url=candidate.api_url,
    )
    return PROVIDER_CLASSES[candidate.provider](board, timeout, None)


def resolve_linkedin_sources(
    database: InventoryDatabase,
    catalog: AtsCatalog,
    *,
    timeout: float = 30,
    apply: bool = False,
    limit: int | None = None,
    include_probes: bool = False,
    workers: int = 12,
) -> ResolutionReport:
    targets = [
        LinkedInTarget(
            job_id=str(item["job_id"]),
            observation_id=str(item["observation_id"]),
            title=str(item["title"]),
            company=str(item["company"]),
            location=str(item["location"]),
            description=str(item["description"]),
            posted_at=item["posted_at"] if isinstance(item["posted_at"], datetime) else None,
        )
        for item in database.unresolved_linkedin_targets()
    ]
    if limit is not None:
        targets = targets[:limit]
    by_company: dict[str, list[LinkedInTarget]] = {}
    for target in targets:
        by_company.setdefault(normalized_key(target.company), []).append(target)
    report = ResolutionReport(targets=len(targets), companies=len(by_company))
    board_tasks: list[tuple[BoardCandidate, list[LinkedInTarget]]] = []
    seen_boards: set[tuple[str, str, str]] = set()
    for company_key, company_targets in by_company.items():
        company = company_targets[0].company
        for candidate in catalog.boards_for(company, include_probes=include_probes):
            board_key = (candidate.provider, candidate.board_id.casefold(), company_key)
            if board_key in seen_boards:
                continue
            seen_boards.add(board_key)
            board_tasks.append((candidate, company_targets))
    report.boards_considered = len(board_tasks)

    fetched: list[tuple[BoardCandidate, list[LinkedInTarget], Any]] = []
    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        futures = {
            executor.submit(
                _provider(candidate, timeout).fetch,
                datetime.now(UTC) - timedelta(days=3650),
            ): (candidate, company_targets)
            for candidate, company_targets in board_tasks
        }
        for future in as_completed(futures):
            candidate, company_targets = futures[future]
            try:
                result = future.result()
            except Exception:
                report.boards_failed += 1
                continue
            if not result.success:
                report.boards_failed += 1
                continue
            report.boards_fetched += 1
            report.postings_scanned += len(result.observations)
            fetched.append((candidate, company_targets, result))

    matched_jobs: set[str] = set()
    for candidate, company_targets, result in sorted(
        fetched, key=lambda item: (item[0].provider, item[0].board_id.casefold())
    ):
        for target in company_targets:
            if target.job_id in matched_jobs:
                continue
            match = match_posting(target, result.observations)
            if match is None:
                continue
            modes = sorted(mode.value for mode in match.observation.work_modes)
            record = {
                "job_id": target.job_id,
                "company": target.company,
                "title": target.title,
                "linkedin_observation_id": target.observation_id,
                "provider": match.observation.provider,
                "board_id": match.observation.provider_board_id,
                "source_url": match.observation.source_url,
                "work_modes": modes,
                "confidence": round(match.confidence, 3),
                "reason": match.reason,
                "board_origin": candidate.origin,
            }
            report.matches.append(record)
            matched_jobs.add(target.job_id)
            if apply:
                database.record_source_resolution(
                    target.job_id,
                    target.observation_id,
                    match.observation,
                    result.source_key,
                    confidence=match.confidence,
                    reason=match.reason,
                    seen_at=result.completed_at,
                )
                report.applied += 1
    report.matches.sort(key=lambda item: (str(item["company"]), str(item["title"])))
    return report
