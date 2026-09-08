"""Build bundled ATS board seeds from a curated employer list and Feashliaa jobs.

This is a maintainer tool, not a runtime job source. It streams the public job
feed, retains only matching employers long enough to recognize their ATS board,
verifies each board endpoint, and optionally updates the bundled registry.
"""

from __future__ import annotations

import argparse
import gzip
import json
import re
import unicodedata
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from job_puller.boards import load_or_empty_registry, merge_registries, recognize_board
from job_puller.config import AtsBoard, BoardRegistry, BoardRegistryProviders

FEED_ROOT = "https://feashliaa.github.io/job-board-data/data/chunks"
MANIFEST_URL = f"{FEED_ROOT}/jobs_manifest.json"
SUPPORTED_FEED_PROVIDERS = {"greenhouse", "lever", "ashby", "workday"}
LEGAL_SUFFIXES = {
    "ag",
    "co",
    "company",
    "corp",
    "corporation",
    "group",
    "holdings",
    "inc",
    "incorporated",
    "llc",
    "llp",
    "ltd",
    "limited",
    "plc",
}


@dataclass(slots=True)
class Candidate:
    provider: str
    board: AtsBoard
    company: str
    tags: set[str] = field(default_factory=set)
    observations: int = 0


def normalized_company(value: str) -> str:
    ascii_value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    tokens = re.findall(r"[a-z0-9]+", ascii_value.casefold())
    while tokens and tokens[-1] in LEGAL_SUFFIXES:
        tokens.pop()
    return "".join(tokens)


def load_employers(path: Path) -> tuple[dict[str, tuple[str, set[str]]], dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    sources = payload.get("sources")
    if not isinstance(sources, list):
        raise ValueError("employer input must contain a sources list")
    indexed: dict[str, tuple[str, set[str]]] = {}
    for source in sources:
        source_id = str(source.get("id") or "").strip()
        companies = source.get("companies")
        if not source_id or not isinstance(companies, list):
            raise ValueError("each employer source requires an id and companies list")
        for company in companies:
            canonical = str(company).strip()
            key = normalized_company(canonical)
            if not key:
                continue
            prior = indexed.get(key)
            if prior is None:
                indexed[key] = (canonical, {source_id})
            else:
                prior[1].add(source_id)
    aliases = payload.get("aliases", {})
    if not isinstance(aliases, dict):
        raise ValueError("aliases must be a mapping of canonical names to alternate names")
    for canonical, values in aliases.items():
        canonical_key = normalized_company(str(canonical))
        if canonical_key not in indexed or not isinstance(values, list):
            continue
        company, tags = indexed[canonical_key]
        for alias in values:
            alias_key = normalized_company(str(alias))
            if alias_key:
                indexed[alias_key] = (company, tags)
    return indexed, payload


def _candidate_from_job(
    job: dict[str, Any], employers: dict[str, tuple[str, set[str]]]
) -> Candidate | None:
    raw_company = str(job.get("company") or "").strip()
    employer = employers.get(normalized_company(raw_company))
    if employer is None:
        return None
    url = str(job.get("url") or "")
    recognized = recognize_board(url, employer[0])
    if recognized is None:
        return None
    provider, board = recognized
    return Candidate(provider, board, employer[0], set(employer[1]), 1)


def _verify(candidate: Candidate, timeout: float) -> tuple[bool, str | None]:
    board = candidate.board
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            if candidate.provider == "greenhouse":
                response = client.get(
                    board.api_url or f"https://boards-api.greenhouse.io/v1/boards/{board.id}/jobs",
                    params={"content": "false"},
                )
            elif candidate.provider == "lever":
                response = client.get(
                    board.api_url or f"https://api.lever.co/v0/postings/{board.id}",
                    params={"mode": "json"},
                )
            elif candidate.provider == "ashby":
                response = client.get(
                    board.api_url or f"https://api.ashbyhq.com/posting-api/job-board/{board.id}"
                )
            elif candidate.provider == "workday" and board.api_url:
                response = client.post(
                    board.api_url,
                    json={"appliedFacets": {}, "limit": 1, "offset": 0, "searchText": ""},
                )
            else:
                return False, "unsupported board route"
            response.raise_for_status()
            return True, None
    except (httpx.HTTPError, ValueError) as exc:
        return False, f"{type(exc).__name__}: {exc}"


def _merge_curated(current: BoardRegistry, discovered: BoardRegistry) -> BoardRegistry:
    merged = merge_registries(current, discovered)
    updates: dict[str, list[AtsBoard]] = {}
    for provider in SUPPORTED_FEED_PROVIDERS:
        curated = {board.id.casefold(): board for board in getattr(discovered.providers, provider)}
        updates[provider] = [
            board.model_copy(
                update={"tags": sorted({*board.tags, *curated[board.id.casefold()].tags})}
            )
            if board.id.casefold() in curated
            else board
            for board in getattr(merged.providers, provider)
        ]
    return merged.model_copy(update={"providers": merged.providers.model_copy(update=updates)})


def curate(
    employer_path: Path,
    *,
    output_path: Path,
    registry_path: Path | None = None,
    timeout: float = 30,
    workers: int = 8,
) -> dict[str, Any]:
    employers, employer_payload = load_employers(employer_path)
    candidates: dict[tuple[str, str], Candidate] = {}
    metrics: Counter[str] = Counter()
    unsupported: Counter[str] = Counter()
    headers = {"User-Agent": "Resume-Builder board curation"}
    with httpx.Client(timeout=timeout, follow_redirects=True, headers=headers) as client:
        manifest_response = client.get(MANIFEST_URL)
        manifest_response.raise_for_status()
        manifest = manifest_response.json()
        for chunk_name in manifest["chunks"]:
            response = client.get(f"{FEED_ROOT}/{chunk_name}")
            response.raise_for_status()
            jobs = json.loads(gzip.decompress(response.content))
            metrics["feed_jobs"] += len(jobs)
            for job in jobs:
                employer = employers.get(normalized_company(str(job.get("company") or "")))
                if employer is None:
                    continue
                metrics["matched_jobs"] += 1
                ats = str(job.get("ats") or "unknown").casefold()
                if ats not in SUPPORTED_FEED_PROVIDERS:
                    unsupported[ats] += 1
                    continue
                found = _candidate_from_job(job, employers)
                if found is None:
                    metrics["unrecognized_matched_urls"] += 1
                    continue
                key = (found.provider, found.board.id.casefold())
                current = candidates.get(key)
                if current is None:
                    candidates[key] = found
                else:
                    current.tags.update(found.tags)
                    current.observations += 1

    ordered = sorted(
        candidates.values(), key=lambda item: (item.provider, item.board.id.casefold())
    )
    with ThreadPoolExecutor(max_workers=workers) as executor:
        results = list(executor.map(lambda item: _verify(item, timeout), ordered))

    verified: list[Candidate] = []
    failures = []
    for candidate, (valid, error) in zip(ordered, results, strict=True):
        if valid:
            verified.append(candidate)
        else:
            failures.append(
                {
                    "provider": candidate.provider,
                    "board_id": candidate.board.id,
                    "company": candidate.company,
                    "error": error,
                }
            )

    grouped: dict[str, list[AtsBoard]] = defaultdict(list)
    for candidate in verified:
        grouped[candidate.provider].append(
            candidate.board.model_copy(
                update={
                    "name": candidate.company,
                    "enabled": True,
                    "tags": sorted({"recognized-employer", *candidate.tags}),
                }
            )
        )
    discovered = BoardRegistry(providers=BoardRegistryProviders(**grouped))
    imported = 0
    if registry_path is not None:
        current = load_or_empty_registry(registry_path)
        before = sum(len(getattr(current.providers, name)) for name in grouped)
        merged = _merge_curated(current, discovered)
        after = sum(len(getattr(merged.providers, name)) for name in grouped)
        imported = after - before
        temporary = registry_path.with_suffix(f"{registry_path.suffix}.tmp")
        temporary.write_text(
            json.dumps(
                merged.model_dump(mode="json", exclude_none=True, exclude_defaults=True), indent=2
            )
            + "\n",
            encoding="utf-8",
        )
        temporary.replace(registry_path)

    report = {
        "schema_version": 1,
        "employer_sources": [
            {"id": source["id"], "url": source["url"], "companies": len(source["companies"])}
            for source in employer_payload["sources"]
        ],
        "unique_employer_keys": len(employers),
        "feed": {
            "manifest_url": MANIFEST_URL,
            "last_updated": manifest.get("last_updated"),
            "jobs_declared": manifest.get("totalJobs"),
            "jobs_scanned": metrics["feed_jobs"],
        },
        "matched_jobs": metrics["matched_jobs"],
        "unrecognized_matched_urls": metrics["unrecognized_matched_urls"],
        "unsupported_ats_jobs": dict(sorted(unsupported.items())),
        "candidate_boards": len(ordered),
        "verified_boards": len(verified),
        "imported_boards": imported,
        "verified_by_provider": dict(Counter(item.provider for item in verified)),
        "verification_failures": failures,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("employers", type=Path, help="JSON file containing sourced company lists")
    parser.add_argument("--output", type=Path, required=True, help="Write the curation report here")
    parser.add_argument("--apply", type=Path, help="Merge verified boards into this registry")
    parser.add_argument("--timeout", type=float, default=30)
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()
    report = curate(
        args.employers,
        output_path=args.output,
        registry_path=args.apply,
        timeout=args.timeout,
        workers=args.workers,
    )
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
