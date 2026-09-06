from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import perf_counter
from typing import Any

import httpx

from .config import AtsBoard
from .database import InventoryDatabase
from .models import JobObservation
from .normalize import normalized_key
from .providers import AshbyProvider, GreenhouseProvider, LeverProvider
from .providers.ats import HttpProvider
from .work_modes import WorkMode, explicit_arrangement

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
    priority: int = 0


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
    board_requests_submitted: int = 0
    board_requests_deferred: int = 0
    probe_companies: int = 0
    boards_fetched: int = 0
    boards_failed: int = 0
    postings_scanned: int = 0
    local_candidates_scanned: int = 0
    local_matches: int = 0
    network_matches: int = 0
    matches: list[dict[str, Any]] = field(default_factory=list)
    applied: int = 0
    duration_ms: int = 0

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
            exact_matches = [entry for entry in catalog if entry.casefold() in variants]
            prefix_matches: list[str] = []
            if compact and len(compact) >= 5:
                prefix_matches.extend(
                    entry
                    for entry in catalog
                    if _compact_slug(entry).startswith(compact)
                    and len(_compact_slug(entry)) <= len(compact) + 15
                    and entry not in exact_matches
                )
            seen: set[str] = set()
            for board_id in [*exact_matches, *prefix_matches][:5]:
                if board_id.casefold() in seen:
                    continue
                seen.add(board_id.casefold())
                candidates.append(
                    BoardCandidate(
                        provider,
                        board_id,
                        company,
                        priority=0 if board_id in exact_matches else 1,
                    )
                )
        if include_probes and not candidates:
            candidates.extend(
                BoardCandidate(
                    provider,
                    board_id,
                    company,
                    origin="company-slug-probe",
                    priority=2,
                )
                for provider in ("greenhouse", "ashby", "lever")
                for board_id in variants[:2]
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


def linkedin_targets(
    database: InventoryDatabase,
    *,
    seen_since: datetime | None = None,
    limit: int | None = None,
) -> list[LinkedInTarget]:
    """Load the bounded target set before any catalog or ATS network work."""
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
        for item in database.unresolved_linkedin_targets(seen_since=seen_since)
    ]
    return targets[:limit] if limit is not None else targets


def _stored_observation(item: dict[str, object]) -> JobObservation:
    modes = item.get("work_modes")
    normalized_modes = (
        [WorkMode(str(mode)) for mode in modes]
        if isinstance(modes, list)
        else [WorkMode.UNKNOWN]
    )
    return JobObservation(
        provider=str(item["provider"]),
        provider_board_id=str(item["provider_board_id"]),
        provider_job_id=str(item["provider_job_id"]),
        title=str(item["title"]),
        company=str(item["company"]),
        source_url=str(item["source_url"]),
        direct_apply_url=str(item["direct_apply_url"]),
        location=str(item["location"]),
        description_html=str(item["description_html"]),
        description_text=str(item["description"]),
        posted_at=item["posted_at"] if isinstance(item["posted_at"], datetime) else None,
        salary_min=float(item["salary_min"])
        if isinstance(item["salary_min"], (int, float))
        else None,
        salary_max=float(item["salary_max"])
        if isinstance(item["salary_max"], (int, float))
        else None,
        salary_currency=str(item["salary_currency"]) if item["salary_currency"] else None,
        salary_interval=str(item["salary_interval"]) if item["salary_interval"] else None,
        employment_type=str(item["employment_type"]) if item["employment_type"] else None,
        remote=item["remote"] if isinstance(item["remote"], bool) else None,
        work_arrangement=explicit_arrangement(
            normalized_modes,
            source="stored_ats_observation",
            rule="persisted_work_mode",
        ),
        parser_version=str(item["parser_version"]),
    )


def _match_record(
    target: LinkedInTarget,
    match: PostingMatch,
    *,
    board_origin: str,
) -> dict[str, Any]:
    return {
        "job_id": target.job_id,
        "company": target.company,
        "title": target.title,
        "linkedin_observation_id": target.observation_id,
        "provider": match.observation.provider,
        "board_id": match.observation.provider_board_id,
        "source_url": match.observation.source_url,
        "work_modes": sorted(mode.value for mode in match.observation.work_modes),
        "confidence": round(match.confidence, 3),
        "reason": match.reason,
        "board_origin": board_origin,
    }


def resolve_linkedin_sources(
    database: InventoryDatabase,
    catalog: AtsCatalog,
    *,
    timeout: float = 30,
    apply: bool = False,
    limit: int | None = None,
    include_probes: bool = False,
    max_probe_companies: int = 20,
    max_board_requests: int | None = None,
    workers: int = 12,
    seen_since: datetime | None = None,
    targets: list[LinkedInTarget] | None = None,
) -> ResolutionReport:
    started = perf_counter()
    targets = targets if targets is not None else linkedin_targets(
        database, seen_since=seen_since, limit=limit
    )
    by_company: dict[str, list[LinkedInTarget]] = {}
    for target in targets:
        by_company.setdefault(normalized_key(target.company), []).append(target)
    report = ResolutionReport(targets=len(targets), companies=len(by_company))
    if not targets:
        report.duration_ms = round((perf_counter() - started) * 1000)
        return report

    matched_jobs: set[str] = set()
    stored = database.stored_direct_ats_observations(set(by_company))
    report.local_candidates_scanned = len(stored)
    stored_by_company: dict[str, list[tuple[dict[str, object], JobObservation]]] = {}
    for item in stored:
        stored_by_company.setdefault(str(item["normalized_company"]), []).append(
            (item, _stored_observation(item))
        )
    for company_key, company_targets in sorted(by_company.items()):
        stored_candidates = stored_by_company.get(company_key, [])
        observations = [observation for _, observation in stored_candidates]
        for target in company_targets:
            match = match_posting(target, observations)
            if match is None:
                continue
            item = next(
                item
                for item, observation in stored_candidates
                if observation is match.observation
            )
            report.matches.append(_match_record(target, match, board_origin="local-inventory"))
            report.local_matches += 1
            matched_jobs.add(target.job_id)
            if apply:
                database.attach_existing_source_resolution(
                    target.job_id,
                    target.observation_id,
                    str(item["observation_id"]),
                    confidence=match.confidence,
                    reason=match.reason,
                    seen_at=item["last_seen_at"]
                    if isinstance(item["last_seen_at"], datetime)
                    else datetime.now(UTC),
                )
                report.applied += 1

    unresolved_by_company = {
        company_key: [target for target in company_targets if target.job_id not in matched_jobs]
        for company_key, company_targets in by_company.items()
    }
    unresolved_by_company = {
        company_key: company_targets
        for company_key, company_targets in unresolved_by_company.items()
        if company_targets
    }
    board_tasks: dict[
        tuple[str, str], tuple[BoardCandidate, dict[str, LinkedInTarget]]
    ] = {}
    probe_companies = 0
    for _company_key, company_targets in sorted(unresolved_by_company.items()):
        company = company_targets[0].company
        board_candidates = catalog.boards_for(company)
        if include_probes and not board_candidates and probe_companies < max_probe_companies:
            board_candidates = catalog.boards_for(company, include_probes=True)
            if board_candidates:
                probe_companies += 1
        for candidate in board_candidates:
            board_key = (candidate.provider, candidate.board_id.casefold())
            if board_key not in board_tasks:
                board_tasks[board_key] = (candidate, {})
            board_tasks[board_key][1].update(
                (target.job_id, target) for target in company_targets
            )
    report.probe_companies = probe_companies
    report.boards_considered = len(board_tasks)
    prioritized_tasks = sorted(
        board_tasks.values(),
        key=lambda item: (item[0].priority, item[0].provider, item[0].board_id.casefold()),
    )
    if max_board_requests is not None:
        prioritized_tasks = prioritized_tasks[:max_board_requests]
    report.board_requests_submitted = len(prioritized_tasks)
    report.board_requests_deferred = report.boards_considered - len(prioritized_tasks)

    fetched: list[tuple[BoardCandidate, list[LinkedInTarget], Any]] = []
    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        futures = {
            executor.submit(
                _provider(candidate, timeout).fetch,
                datetime.now(UTC) - timedelta(days=3650),
            ): (candidate, list(company_targets.values()))
            for candidate, company_targets in prioritized_tasks
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

    for candidate, company_targets, result in sorted(
        fetched, key=lambda item: (item[0].provider, item[0].board_id.casefold())
    ):
        for target in company_targets:
            if target.job_id in matched_jobs:
                continue
            match = match_posting(target, result.observations)
            if match is None:
                continue
            report.matches.append(_match_record(target, match, board_origin=candidate.origin))
            report.network_matches += 1
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
    report.duration_ms = round((perf_counter() - started) * 1000)
    return report
