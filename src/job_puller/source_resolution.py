from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import perf_counter
from typing import Any

from .boards import recognize_board
from .config import AtsBoard, InventoryConfig
from .database import InventoryDatabase
from .models import JobObservation, ProviderResult
from .normalize import canonical_url, normalized_key
from .providers import (
    AshbyProvider,
    GreenhouseProvider,
    LeverProvider,
    RipplingProvider,
    WorkdayProvider,
)
from .providers.ats import HttpProvider
from .work_modes import WorkMode, explicit_arrangement

DATASET_REVISION = "first-party-board-registry-v1"
CATALOG_PROVIDERS = ("greenhouse", "lever", "ashby", "workday")
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
    "holding",
    "holdings",
}
PROVIDER_CLASSES: dict[str, type[HttpProvider]] = {
    "rippling": RipplingProvider,
    "greenhouse": GreenhouseProvider,
    "ashby": AshbyProvider,
    "lever": LeverProvider,
    "workday": WorkdayProvider,
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
    direct_apply_url: str = ""
    source_url: str = ""


@dataclass(frozen=True, slots=True)
class BoardCandidate:
    provider: str
    board_id: str
    company: str
    api_url: str | None = None
    careers_url: str | None = None
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
    """Validated index of private ATS board identifiers."""

    def __init__(self, entries: dict[str, tuple[str, ...]]):
        self.entries = entries
        self.registered: tuple[BoardCandidate, ...] = ()

    def add_configured_boards(self, config: InventoryConfig | Any) -> AtsCatalog:
        """Prefer private, observed board routes over public catalog guesses."""
        candidates: list[BoardCandidate] = []
        for provider in PROVIDER_CLASSES:
            for board in getattr(config.providers, provider).boards:
                candidates.append(
                    BoardCandidate(
                        provider=provider,
                        board_id=board.id,
                        company=board.name,
                        api_url=board.api_url,
                        careers_url=board.careers_url,
                        origin="private-registry",
                        priority=-1,
                    )
                )
        self.registered = tuple(candidates)
        return self

    @classmethod
    def load(
        cls,
        cache_dir: Path,
    ) -> AtsCatalog:
        """Load optional private catalog snapshots without downloading third-party seeds."""
        cache_dir.mkdir(parents=True, exist_ok=True)
        loaded: dict[str, tuple[str, ...]] = {}
        for provider in CATALOG_PROVIDERS:
            path = cache_dir / f"{provider}.json"
            payload = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
            loaded[provider] = _validate_catalog(provider, payload)
        return cls(loaded)

    def boards_for(self, company: str, *, include_probes: bool = False) -> list[BoardCandidate]:
        variants = company_slug_candidates(company)
        compact = variants[-1] if variants else ""
        company_key = normalized_key(company)
        candidates: list[BoardCandidate] = [
            candidate
            for candidate in self.registered
            if normalized_key(candidate.company) == company_key
        ]
        for provider in ("greenhouse", "ashby", "lever"):
            catalog = self.entries.get(provider, ())
            exact_matches = [entry for entry in catalog if entry.casefold() in variants]
            prefix_matches: list[str] = []
            if compact:
                delimited_prefix = f"{variants[0]}-"
                prefix_matches.extend(
                    entry
                    for entry in catalog
                    if (
                        (len(compact) >= 5 and _compact_slug(entry).startswith(compact))
                        or entry.casefold().startswith(delimited_prefix)
                    )
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
        workday_matches = []
        for entry in self.entries.get("workday", ()):
            tenant, datacenter, site = entry.split("|")
            if tenant.casefold() not in variants:
                continue
            site_key = site.casefold()
            specialized = any(
                marker in site_key
                for marker in (
                    "private",
                    "internal",
                    "hardware",
                    "subsidiary",
                    "contingent",
                    "university",
                    "event",
                )
            ) or site_key in {"intern", "graduate", "newgrad"}
            public = any(marker in site_key for marker in ("career", "jobs", "external"))
            workday_matches.append(
                (specialized, not public, len(site_key), site_key, tenant, datacenter, site)
            )
        for *_sort_key, tenant, datacenter, site in sorted(workday_matches)[:3]:
            host = f"https://{tenant}.{datacenter}.myworkdayjobs.com"
            candidates.append(
                BoardCandidate(
                    "workday",
                    f"{tenant}-{site}".casefold(),
                    company,
                    api_url=f"{host}/wday/cxs/{tenant}/{site}/jobs",
                    careers_url=f"{host}/en-US/{site}",
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
        unique: dict[tuple[str, str, str], BoardCandidate] = {}
        for candidate in candidates:
            # One Workday tenant/site can exist in more than one datacenter. Keep
            # each endpoint until it has been tried instead of allowing a stale
            # catalog row to hide the live endpoint.
            endpoint = candidate.api_url.casefold() if candidate.api_url else ""
            unique.setdefault(
                (candidate.provider, candidate.board_id.casefold(), endpoint), candidate
            )
        return list(unique.values())


def _validate_catalog(provider: str, payload: Any) -> tuple[str, ...]:
    if not isinstance(payload, list):
        raise CatalogError(f"{provider} catalog must be a JSON list")
    result: list[str] = []
    for value in payload:
        if not isinstance(value, str):
            raise CatalogError(f"{provider} catalog contains a non-string entry")
        parts = value.split("|") if provider == "workday" else [value]
        if (provider == "workday" and len(parts) != 3) or any(
            not SLUG.fullmatch(part) for part in parts
        ):
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


def _match_captured_posting(
    target: LinkedInTarget, observations: list[JobObservation]
) -> PostingMatch | None:
    """Trust a browser-captured 1:1 Apply URL after an exact title check."""
    captured_url = canonical_url(target.direct_apply_url)
    if not captured_url:
        return None
    captured_path = re.sub(r"[^a-z0-9]", "", target.direct_apply_url.casefold())
    matches = [
        observation
        for observation in observations
        if (
            canonical_url(observation.source_url) == captured_url
            or (
                len(observation.provider_job_id) >= 5
                and re.sub(r"[^a-z0-9]", "", observation.provider_job_id.casefold())
                in captured_path
            )
        )
        and normalized_key(observation.title) == normalized_key(target.title)
    ]
    if len(matches) != 1:
        return None
    return PostingMatch(target, matches[0], 0.99, "exact_captured_apply_url_and_title")


def _provider(candidate: BoardCandidate, timeout: float) -> HttpProvider:
    board = AtsBoard(
        id=candidate.board_id,
        name=candidate.company,
        api_url=candidate.api_url,
        careers_url=candidate.careers_url,
    )
    return PROVIDER_CLASSES[candidate.provider](board, timeout, None)


def _fetch_candidate(
    candidate: BoardCandidate, targets: list[LinkedInTarget], timeout: float
) -> ProviderResult:
    provider = _provider(candidate, timeout)
    if isinstance(provider, WorkdayProvider):
        direct_urls = []
        for target in targets:
            recognized = recognize_board(target.direct_apply_url, target.company)
            if (
                recognized is not None
                and recognized[0] == "workday"
                and recognized[1].id.casefold() == candidate.board_id.casefold()
            ):
                direct_urls.append(target.direct_apply_url)
        if direct_urls:
            direct_result = provider.fetch_direct_urls(direct_urls)
            if direct_result.success and direct_result.observations:
                return direct_result
        return provider.fetch_exact_titles([target.title for target in targets])
    cutoff = datetime.now(UTC) - timedelta(days=3650)
    result = provider.fetch(cutoff)
    compact_id = _compact_slug(candidate.board_id)
    if (
        result.success
        or candidate.provider != "ashby"
        or compact_id == candidate.board_id.casefold()
        or "404" not in (result.error or "")
    ):
        return result
    return _provider(replace(candidate, board_id=compact_id), timeout).fetch(cutoff)


def linkedin_targets(
    database: InventoryDatabase,
    *,
    seen_since: datetime | None = None,
    limit: int | None = None,
    include_possibly_closed: bool = False,
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
            direct_apply_url=str(item.get("direct_apply_url") or ""),
            source_url=str(item.get("source_url") or ""),
        )
        for item in database.unresolved_linkedin_targets(
            **(
                {"seen_since": seen_since, "include_possibly_closed": True}
                if include_possibly_closed
                else {"seen_since": seen_since}
            )
        )
    ]
    return targets[:limit] if limit is not None else targets


def _stored_observation(item: dict[str, object]) -> JobObservation:
    modes = item.get("work_modes")
    normalized_modes = (
        [WorkMode(str(mode)) for mode in modes] if isinstance(modes, list) else [WorkMode.UNKNOWN]
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
        "linkedin_location": target.location,
        "resolved_location": match.observation.location,
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
    providers: set[str] | None = None,
) -> ResolutionReport:
    started = perf_counter()
    targets = (
        targets
        if targets is not None
        else linkedin_targets(database, seen_since=seen_since, limit=limit)
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
                item for item, observation in stored_candidates if observation is match.observation
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
        tuple[str, str, str, str], tuple[BoardCandidate, dict[str, LinkedInTarget]]
    ] = {}
    probe_companies = 0
    for _company_key, company_targets in sorted(unresolved_by_company.items()):
        company = company_targets[0].company
        board_candidates: list[BoardCandidate] = []
        for target in company_targets:
            recognized = recognize_board(target.direct_apply_url, target.company)
            if recognized is None or recognized[0] not in PROVIDER_CLASSES:
                continue
            provider, board = recognized
            board_candidates.append(
                BoardCandidate(
                    provider=provider,
                    board_id=board.id,
                    company=target.company,
                    api_url=board.api_url,
                    careers_url=board.careers_url,
                    origin="captured-apply-url",
                    priority=-2,
                )
            )
        board_candidates.extend(catalog.boards_for(company))
        if providers is not None:
            board_candidates = [
                candidate for candidate in board_candidates if candidate.provider in providers
            ]
        if include_probes and not board_candidates and probe_companies < max_probe_companies:
            board_candidates = catalog.boards_for(company, include_probes=True)
            if providers is not None:
                board_candidates = [
                    candidate for candidate in board_candidates if candidate.provider in providers
                ]
            if board_candidates:
                probe_companies += 1
        for candidate in board_candidates:
            if candidate.provider == "workday":
                for target in company_targets:
                    board_key = (
                        candidate.provider,
                        candidate.board_id.casefold(),
                        (candidate.api_url or "").casefold(),
                        normalized_key(target.title),
                    )
                    if board_key not in board_tasks:
                        board_tasks[board_key] = (candidate, {})
                    board_tasks[board_key][1][target.job_id] = target
            else:
                board_key = (candidate.provider, candidate.board_id.casefold(), "", "")
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

    fetched: list[tuple[BoardCandidate, list[LinkedInTarget], ProviderResult]] = []
    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        futures = {
            executor.submit(
                _fetch_candidate,
                candidate,
                list(company_targets.values()),
                timeout,
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
            match = (
                _match_captured_posting(target, result.observations)
                if candidate.origin == "captured-apply-url"
                else None
            ) or match_posting(target, result.observations)
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
