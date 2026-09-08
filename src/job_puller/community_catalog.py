from __future__ import annotations

import hashlib
import json
import re
from bisect import bisect_right
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

from .config import AtsBoard, InventoryConfig
from .eligibility import GENERIC_TITLE_TERMS
from .normalize import normalized_key
from .service import ATS_PROVIDER_CLASSES

CATALOG_REPOSITORY = "Feashliaa/job-board-aggregator"
CATALOG_LICENSE = "CC-BY-NC-4.0"
CATALOG_FILES = {
    "greenhouse": "greenhouse_companies.json",
    "lever": "lever_companies.json",
    "ashby": "ashby_companies.json",
    "workday": "workday_companies.json",
}
SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$")


def _atomic_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def _catalog_revision(client: httpx.Client, ref: str) -> str:
    response = client.get(
        f"https://api.github.com/repos/{CATALOG_REPOSITORY}/commits/{ref}",
        headers={"Accept": "application/vnd.github+json"},
    )
    response.raise_for_status()
    revision = str(response.json().get("sha") or "")
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("catalog source did not return a valid commit revision")
    return revision


def _catalog_entries(client: httpx.Client, provider: str, revision: str) -> tuple[list[str], str]:
    filename = CATALOG_FILES[provider]
    response = client.get(
        f"https://raw.githubusercontent.com/{CATALOG_REPOSITORY}/{revision}/data/{filename}"
    )
    response.raise_for_status()
    try:
        payload = response.json()
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid {provider} catalog JSON") from exc
    if not isinstance(payload, list) or any(not isinstance(item, str) for item in payload):
        raise ValueError(f"invalid {provider} catalog: expected a list of strings")
    entries = sorted(set(payload), key=str.casefold)
    return entries, hashlib.sha256(response.content).hexdigest()


def _next_batch(entries: list[str], last_id: str, limit: int) -> list[str]:
    if not entries:
        return []
    folded = [entry.casefold() for entry in entries]
    start = bisect_right(folded, last_id.casefold()) if last_id else 0
    return (entries[start:] + entries[:start])[:limit]


def _board(provider: str, identifier: str) -> AtsBoard:
    if provider == "workday":
        parts = identifier.split("|")
        if len(parts) != 3 or not all(SAFE_ID.fullmatch(part) for part in parts):
            raise ValueError("expected tenant|datacenter|site")
        tenant, datacenter, site = parts
        if not re.fullmatch(r"wd\d+", datacenter, re.IGNORECASE):
            raise ValueError("invalid Workday datacenter")
        host = f"{tenant}.{datacenter}.myworkdayjobs.com"
        return AtsBoard(
            id=f"{tenant}-{datacenter}-{site}".casefold(),
            name=tenant,
            enabled=False,
            api_url=f"https://{host}/wday/cxs/{tenant}/{site}/jobs",
            careers_url=f"https://{host}/{site}",
        )
    if not SAFE_ID.fullmatch(identifier):
        raise ValueError("invalid board identifier")
    urls = {
        "greenhouse": f"https://job-boards.greenhouse.io/{identifier}",
        "lever": f"https://jobs.lever.co/{identifier}",
        "ashby": f"https://jobs.ashbyhq.com/{identifier}",
    }
    return AtsBoard(id=identifier, name=identifier, enabled=False, careers_url=urls[provider])


def _possible_misses(metrics: dict[str, int], config: InventoryConfig) -> list[dict[str, object]]:
    search_terms = {
        token
        for family in config.search.families
        if family.enabled and not family.commercial_only
        for title in family.accepted_titles
        for token in normalized_key(title).split()
        if len(token) >= 3 and token not in GENERIC_TITLE_TERMS
    }
    candidates = []
    for key, count in metrics.items():
        if not key.startswith("rejected_title."):
            continue
        title = key.removeprefix("rejected_title.")
        shared = sorted(set(normalized_key(title).split()) & search_terms)
        if shared:
            candidates.append({"title": title, "count": count, "shared_terms": shared})
    return sorted(candidates, key=lambda item: (-int(str(item["count"])), str(item["title"])))


def audit_community_catalog(
    config: InventoryConfig,
    *,
    providers: list[str],
    limit_per_provider: int,
    cursor_path: Path,
    output_path: Path,
    ref: str = "main",
    client: httpx.Client | None = None,
) -> dict[str, object]:
    if limit_per_provider < 1 or limit_per_provider > 100:
        raise ValueError("limit per provider must be between 1 and 100")
    unknown = set(providers) - set(CATALOG_FILES)
    if unknown:
        raise ValueError(f"unsupported community catalog providers: {', '.join(sorted(unknown))}")
    try:
        cursor = json.loads(cursor_path.read_text(encoding="utf-8")) if cursor_path.exists() else {}
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid catalog audit cursor: {exc}") from exc
    last_ids = cursor.get("last_ids", {})
    if not isinstance(last_ids, dict):
        raise ValueError("invalid catalog audit cursor: last_ids must be a mapping")

    owns_client = client is None
    if client is None:
        client = httpx.Client(timeout=config.request_timeout_seconds, follow_redirects=True)
    try:
        revision = _catalog_revision(client, ref)
        provider_reports = []
        totals: Counter[str] = Counter()
        possible_miss_counts: Counter[str] = Counter()
        promotion_candidates: list[dict[str, object]] = []
        next_last_ids = dict(last_ids)
        since = datetime.now(UTC) - timedelta(days=config.initial_lookback_days)
        for provider_name in providers:
            entries, file_sha256 = _catalog_entries(client, provider_name, revision)
            selected = _next_batch(
                entries, str(last_ids.get(provider_name) or ""), limit_per_provider
            )
            board_reports: list[dict[str, object]] = []
            for identifier in selected:
                try:
                    board = _board(provider_name, identifier)
                except ValueError as exc:
                    board_reports.append(
                        {"identifier": identifier, "outcome": "invalid", "error": str(exc)}
                    )
                    totals["invalid_boards"] += 1
                    continue
                provider = ATS_PROVIDER_CLASSES[provider_name](
                    board, config.request_timeout_seconds, config.search
                )
                result = provider.fetch(since)
                metrics = dict(result.metrics)
                accepted = len(result.observations)
                outcome = result.outcome.value
                accounted_jobs = sum(
                    metrics.get(key, 0)
                    for key in (
                        "invalid",
                        "duplicates",
                        "title_rejected",
                        "freshness_rejected",
                        "detail_errors",
                        "accepted",
                    )
                )
                accounting_valid = metrics.get("raw_results", 0) == accounted_jobs
                possible_misses = _possible_misses(metrics, config)
                promotion_ready = outcome in {"healthy", "capped"} and accepted > 0
                report = {
                    "identifier": identifier,
                    "board": board.model_dump(mode="json", exclude_none=True),
                    "outcome": outcome,
                    "raw_jobs": metrics.get("raw_results", 0),
                    "accepted_jobs": accepted,
                    "filters": metrics,
                    "filter_accounting": {
                        "raw_jobs": metrics.get("raw_results", 0),
                        "accounted_jobs": accounted_jobs,
                        "valid": accounting_valid,
                    },
                    "possible_false_negatives": possible_misses,
                    "promotion_ready": promotion_ready,
                    "duration_seconds": round(
                        (result.completed_at - result.started_at).total_seconds(), 3
                    ),
                }
                if result.error:
                    report["error"] = result.error
                board_reports.append(report)
                for candidate in possible_misses:
                    possible_miss_counts[str(candidate["title"])] += int(str(candidate["count"]))
                if promotion_ready:
                    promotion_candidates.append(
                        {
                            "provider": provider_name,
                            "identifier": identifier,
                            "accepted_jobs": accepted,
                            "board": report["board"],
                        }
                    )
                totals["boards_tested"] += 1
                totals[f"outcome.{outcome}"] += 1
                for key in (
                    "raw_results",
                    "invalid",
                    "title_rejected",
                    "freshness_rejected",
                    "work_mode_mismatch",
                    "accepted",
                ):
                    totals[key] += metrics.get(key, 0)
                totals["promotion_ready"] += int(promotion_ready)
                totals["filter_accounting_errors"] += int(not accounting_valid)
            if selected:
                next_last_ids[provider_name] = selected[-1]
            provider_reports.append(
                {
                    "provider": provider_name,
                    "catalog_entries": len(entries),
                    "file_sha256": file_sha256,
                    "selected": len(selected),
                    "boards": board_reports,
                }
            )
        report = {
            "schema_version": 1,
            "mode": "read-only",
            "source": {
                "repository": CATALOG_REPOSITORY,
                "repository_url": f"https://github.com/{CATALOG_REPOSITORY}",
                "revision": revision,
                "license": CATALOG_LICENSE,
                "license_url": "https://creativecommons.org/licenses/by-nc/4.0/",
            },
            "created_at": datetime.now(UTC).isoformat(),
            "limit_per_provider": limit_per_provider,
            "totals": dict(sorted(totals.items())),
            "promotion_candidates": promotion_candidates,
            "possible_false_negatives": [
                {"title": title, "count": count}
                for title, count in possible_miss_counts.most_common(50)
            ],
            "providers": provider_reports,
        }
        _atomic_json(output_path, report)
        _atomic_json(
            cursor_path,
            {
                "schema_version": 1,
                "source_repository": CATALOG_REPOSITORY,
                "last_revision": revision,
                "last_ids": next_last_ids,
            },
        )
        return report
    finally:
        if owns_client:
            client.close()
