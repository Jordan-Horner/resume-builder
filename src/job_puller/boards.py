from __future__ import annotations

import ipaddress
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import httpx
import yaml

from .config import AtsBoard, BoardRegistry, BoardRegistryProviders, load_board_registry

SUPPORTED_PROVIDERS = ("greenhouse", "lever", "ashby", "smartrecruiters", "workday")
GREENHOUSE_HOSTS = {
    "boards.greenhouse.io",
    "job-boards.greenhouse.io",
    "job-boards.eu.greenhouse.io",
}
LOCALE_SEGMENT = re.compile(r"^[a-z]{2}-[A-Z]{2}$")


@dataclass(slots=True)
class DiscoveryReport:
    scanned_links: int = 0
    recognized_links: int = 0
    redirect_failures: list[str] = field(default_factory=list)
    verified_redirects: list[tuple[str, str]] = field(default_factory=list)
    host_counts: Counter[str] = field(default_factory=Counter)


@dataclass(slots=True)
class BoardCandidate:
    provider: str
    board: AtsBoard
    companies: Counter[str] = field(default_factory=Counter)
    observations: int = 0


def _segments(url: str) -> tuple[str, list[str]]:
    parsed = urlsplit(url)
    return parsed.hostname.casefold() if parsed.hostname else "", [
        segment for segment in parsed.path.split("/") if segment
    ]


def recognize_board(url: str, company: str = "") -> tuple[str, AtsBoard] | None:
    host, segments = _segments(url)
    if host in GREENHOUSE_HOSTS and segments:
        board_id = segments[0]
        return "greenhouse", AtsBoard(
            id=board_id,
            name=company or board_id,
            enabled=False,
            careers_url=f"https://job-boards.greenhouse.io/{board_id}",
        )
    if host == "jobs.lever.co" and segments:
        board_id = segments[0]
        return "lever", AtsBoard(
            id=board_id,
            name=company or board_id,
            enabled=False,
            careers_url=f"https://jobs.lever.co/{board_id}",
        )
    if host == "jobs.ashbyhq.com" and segments:
        board_id = segments[0]
        return "ashby", AtsBoard(
            id=board_id,
            name=company or board_id,
            enabled=False,
            careers_url=f"https://jobs.ashbyhq.com/{board_id}",
        )
    if host == "jobs.smartrecruiters.com" and segments:
        board_id = segments[0]
        return "smartrecruiters", AtsBoard(
            id=board_id,
            name=company or board_id,
            enabled=False,
            careers_url=f"https://jobs.smartrecruiters.com/{board_id}",
        )
    if host.endswith(".myworkdayjobs.com") and segments:
        tenant = host.split(".", 1)[0]
        site_index = 1 if LOCALE_SEGMENT.fullmatch(segments[0]) else 0
        if site_index >= len(segments):
            return None
        site = segments[site_index]
        careers_segments = segments[: site_index + 1]
        careers_path = "/".join(careers_segments)
        board_id = f"{tenant}-{site}".casefold()
        return "workday", AtsBoard(
            id=board_id,
            name=company or tenant,
            enabled=False,
            api_url=f"https://{host}/wday/cxs/{tenant}/{site}/jobs",
            careers_url=f"https://{host}/{careers_path}",
        )
    return None


def _greenhouse_redirect(url: str, client: httpx.Client) -> str:
    current = url
    allowed_hosts = {*GREENHOUSE_HOSTS, "grnh.se"}
    for _ in range(5):
        response = client.head(current)
        if response.status_code in {405, 501}:
            response = client.get(current)
        if response.is_redirect:
            location = response.headers.get("location", "")
            current = urljoin(current, location)
            host, _ = _segments(current)
            if host not in allowed_hosts:
                try:
                    ipaddress.ip_address(host)
                except ValueError:
                    if host and host != "localhost" and "." in host:
                        # Custom careers domains are valid terminal destinations.
                        # Return the Location header without requesting that host.
                        return current
                raise ValueError(f"unsafe Greenhouse redirect host: {host or 'missing'}")
            if host in GREENHOUSE_HOSTS:
                return current
            continue
        response.raise_for_status()
        host, _ = _segments(current)
        if host not in GREENHOUSE_HOSTS:
            raise ValueError(f"unexpected Greenhouse redirect host: {host or 'missing'}")
        return current
    raise ValueError("too many Greenhouse redirects")


def discover_boards(
    links: list[dict[str, object]],
    *,
    providers: set[str] | None = None,
    client: httpx.Client | None = None,
    timeout: float = 30,
) -> tuple[BoardRegistry, DiscoveryReport]:
    selected = providers or set(SUPPORTED_PROVIDERS)
    unknown = selected - set(SUPPORTED_PROVIDERS)
    if unknown:
        raise ValueError(f"unsupported ATS providers: {', '.join(sorted(unknown))}")
    report = DiscoveryReport(scanned_links=len(links))
    candidates: dict[tuple[str, str], BoardCandidate] = {}
    owns_client = client is None
    if client is None:
        client = httpx.Client(timeout=timeout, follow_redirects=False)
    try:
        for link in links:
            url = str(link.get("url") or "")
            company = str(link.get("company") or "").strip()
            observations = int(link.get("observations") or 1)
            host, _ = _segments(url)
            report.host_counts[host or "invalid"] += observations
            candidate_url = url
            if host == "grnh.se" and "greenhouse" in selected:
                try:
                    candidate_url = _greenhouse_redirect(url, client)
                    report.verified_redirects.append((url, candidate_url))
                except (httpx.HTTPError, ValueError) as exc:
                    report.redirect_failures.append(f"{url}: {type(exc).__name__}: {exc}")
                    continue
            recognized = recognize_board(candidate_url, company)
            if recognized is None or recognized[0] not in selected:
                continue
            provider, board = recognized
            key = (provider, board.id.casefold())
            existing = candidates.get(key)
            if existing is None:
                existing = BoardCandidate(provider, board)
                candidates[key] = existing
            if company:
                existing.companies[company] += observations
            existing.observations += observations
            report.recognized_links += observations
    finally:
        if owns_client:
            client.close()

    grouped: dict[str, list[AtsBoard]] = {name: [] for name in SUPPORTED_PROVIDERS}
    for candidate in candidates.values():
        name = candidate.companies.most_common(1)[0][0] if candidate.companies else candidate.board.name
        grouped[candidate.provider].append(candidate.board.model_copy(update={"name": name}))
    for boards in grouped.values():
        boards.sort(key=lambda board: (board.name.casefold(), board.id.casefold()))
    return BoardRegistry(providers=BoardRegistryProviders(**grouped)), report


def merge_registries(current: BoardRegistry, discovered: BoardRegistry) -> BoardRegistry:
    updates = {}
    for provider in SUPPORTED_PROVIDERS:
        existing = list(getattr(current.providers, provider))
        known = {board.id.casefold() for board in existing}
        additions = [
            board for board in getattr(discovered.providers, provider) if board.id.casefold() not in known
        ]
        updates[provider] = [*existing, *additions]
    return BoardRegistry(providers=BoardRegistryProviders(**updates))


def write_board_registry(path: Path, registry: BoardRegistry) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = registry.model_dump(mode="json", exclude_none=True, exclude_defaults=True)
    payload = {"schema_version": registry.schema_version, **payload}
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    temporary.replace(path)


def load_or_empty_registry(path: Path) -> BoardRegistry:
    return load_board_registry(path) if path.exists() else BoardRegistry()
