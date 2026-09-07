"""Optional Bright Data enrichment for unresolved LinkedIn observations."""

from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import monotonic, sleep
from typing import Any
from urllib.parse import urlsplit

import httpx

from job_puller.database import InventoryDatabase
from job_puller.models import JobObservation
from job_puller.normalize import html_to_text, normalized_key
from job_puller.source_resolution import LinkedInTarget

from .atomic import atomic_write_json

BRIGHT_DATA_DATASET_ID = "gd_lpfll7v5hcqtkxl6l"
BRIGHT_DATA_ENDPOINT = "https://api.brightdata.com/datasets/v3/scrape"
BRIGHT_DATA_PARSER_VERSION = "linkedin-bright-data-v2"
BRIGHT_DATA_SECRET_PATH = Path("build/secrets/bright-data-key")
BRIGHT_DATA_SETTINGS_PATH = Path("job-search/bright-data.json")


@dataclass(frozen=True, slots=True)
class BrightDataSettings:
    enabled: bool = False
    max_records_per_refresh: int = 100


def load_bright_data_settings(workspace: Path) -> BrightDataSettings:
    path = workspace / BRIGHT_DATA_SETTINGS_PATH
    if not path.is_file():
        return BrightDataSettings()
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Bright Data settings must be an object")
    maximum = payload.get("max_records_per_refresh", 100)
    if not isinstance(maximum, int) or isinstance(maximum, bool) or not 1 <= maximum <= 1000:
        raise ValueError("Bright Data record limit must be from 1 to 1000")
    return BrightDataSettings(
        enabled=payload.get("enabled") is True,
        max_records_per_refresh=maximum,
    )


def save_bright_data_settings(workspace: Path, settings: BrightDataSettings) -> None:
    atomic_write_json(
        workspace / BRIGHT_DATA_SETTINGS_PATH,
        {
            "schema_version": 1,
            "enabled": settings.enabled,
            "max_records_per_refresh": settings.max_records_per_refresh,
        },
    )


def bright_data_secret_path(workspace: Path) -> Path:
    override = os.environ.get("RESUME_BUILDER_BRIGHT_DATA_KEY_FILE", "").strip()
    return (
        Path(override).expanduser().resolve() if override else workspace / BRIGHT_DATA_SECRET_PATH
    )


def bright_data_key(workspace: Path) -> str:
    path = bright_data_secret_path(workspace)
    if path.is_file():
        return path.read_text(encoding="utf-8").strip()
    return os.environ.get("BRIGHT_DATA_API_TOKEN", "").strip()


def _linkedin_id(url: str) -> str:
    for segment in reversed(urlsplit(url).path.rstrip("/").split("/")):
        if segment.isdigit():
            return segment
        match = segment.rsplit("-", 1)[-1]
        if match.isdigit():
            return match
    return ""


def _number(value: object) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _currency(value: object) -> str | None:
    normalized = str(value or "").strip().upper()
    return {"$": "USD", "US$": "USD", "C$": "CAD", "CA$": "CAD"}.get(normalized, normalized or None)


def _interval(value: object) -> str | None:
    normalized = str(value or "").strip().casefold().replace("per ", "").lstrip("/")
    if normalized in {"year", "yr", "annual", "annually", "yearly"}:
        return "yearly"
    if normalized in {"hour", "hr", "hourly"}:
        return "hourly"
    return normalized or None


def _observation(payload: dict[str, Any], target: LinkedInTarget) -> JobObservation:
    salary = payload.get("base_salary")
    salary = salary if isinstance(salary, dict) else {}
    description_html = str(
        payload.get("job_description_formatted") or payload.get("job_summary") or ""
    )
    return JobObservation(
        provider="linkedin",
        provider_job_id=str(payload.get("job_posting_id") or _linkedin_id(target.source_url)),
        title=str(payload.get("job_title") or target.title),
        company=str(payload.get("company_name") or target.company),
        source_url=str(payload.get("url") or target.source_url),
        direct_apply_url=str(payload.get("apply_link") or ""),
        location=str(payload.get("job_location") or target.location),
        description_html=description_html,
        description_text=html_to_text(description_html),
        salary_min=_number(salary.get("min_amount")),
        salary_max=_number(salary.get("max_amount")),
        salary_currency=_currency(salary.get("currency")),
        salary_interval=_interval(salary.get("payment_period")),
        employment_type=str(payload.get("job_employment_type") or "") or None,
        raw_payload={},
        parser_version=BRIGHT_DATA_PARSER_VERSION,
    )


def _record_attempt(
    database: InventoryDatabase,
    posting_id: str,
    outcome: str,
    *,
    fields_added: frozenset[str] = frozenset(),
) -> None:
    now = datetime.now(UTC)
    database.put_provider_detail(
        "bright-data",
        posting_id,
        BRIGHT_DATA_PARSER_VERSION,
        json.dumps({"outcome": outcome, "fields_added": sorted(fields_added)}),
        now,
        now + timedelta(days=1 if outcome == "failed" else 30),
    )


def _response_items(
    client: httpx.Client,
    response: httpx.Response,
    *,
    api_token: str,
    timeout: float,
) -> list[object]:
    """Return immediate results or finish Bright Data's documented 202 fallback."""
    response.raise_for_status()
    payload = response.json()
    if response.status_code != 202:
        return payload if isinstance(payload, list) else [payload]
    snapshot_id = str(payload.get("snapshot_id") or "") if isinstance(payload, dict) else ""
    if not snapshot_id:
        raise ValueError("Bright Data returned 202 without a snapshot ID")
    headers = {"Authorization": f"Bearer {api_token}"}
    deadline = monotonic() + max(timeout, 300)
    while monotonic() < deadline:
        progress = client.get(
            f"https://api.brightdata.com/datasets/v3/progress/{snapshot_id}",
            headers=headers,
        )
        progress.raise_for_status()
        status = str(progress.json().get("status") or "")
        if status == "ready":
            completed = client.get(
                f"https://api.brightdata.com/datasets/v3/snapshot/{snapshot_id}",
                params={"format": "json"},
                headers=headers,
            )
            completed.raise_for_status()
            result = completed.json()
            return result if isinstance(result, list) else [result]
        if status == "failed":
            raise ValueError("Bright Data snapshot failed")
        sleep(5)
    raise ValueError("Bright Data snapshot did not finish in time")


def save_captured_boards(
    database: InventoryDatabase, config_path: Path, *, timeout: float
) -> dict[str, object]:
    """Persist recognized Apply-link boards so later jobs use the free ATS path."""
    from job_puller.boards import (
        SUPPORTED_PROVIDERS,
        discover_boards,
        load_or_empty_registry,
        merge_registries,
        write_board_registry,
    )
    from job_puller.config import (
        BoardRegistry,
        BoardRegistryProviders,
        load_config,
        resolve_project_path,
    )

    config = load_config(config_path)
    if not config.board_registry_path:
        return {"added": 0, "boards": []}
    path = resolve_project_path(config_path, config.board_registry_path)
    current = load_or_empty_registry(path)
    discovered, _ = discover_boards(database.active_application_links(), timeout=timeout)
    additions: list[dict[str, object]] = []
    new_boards = {}
    for provider in SUPPORTED_PROVIDERS:
        known = {board.id.casefold() for board in getattr(config.providers, provider).boards}
        new_boards[provider] = [
            board
            for board in getattr(discovered.providers, provider)
            if board.id.casefold() not in known
        ]
        additions.extend(
            {
                "provider": provider,
                "id": board.id,
                "name": board.name,
                "api_url": board.api_url,
                "careers_url": board.careers_url,
            }
            for board in new_boards[provider]
        )
    if additions:
        newly_discovered = BoardRegistry(providers=BoardRegistryProviders(**new_boards))
        write_board_registry(path, merge_registries(current, newly_discovered))
    return {"added": len(additions), "boards": additions}


def enrich_linkedin_targets(
    database: InventoryDatabase,
    targets: list[LinkedInTarget],
    *,
    api_token: str,
    limit: int,
    timeout: float = 60,
) -> dict[str, object]:
    candidates = [target for target in targets if _linkedin_id(target.source_url)]
    now = datetime.now(UTC)
    eligible = []
    skipped_cached = 0
    for target in candidates:
        cached = database.get_provider_detail(
            "bright-data",
            _linkedin_id(target.source_url),
            BRIGHT_DATA_PARSER_VERSION,
        )
        if cached is not None and cached.expires_at > now:
            skipped_cached += 1
        else:
            eligible.append(target)
    selected: list[LinkedInTarget] = []
    selected_companies = set()
    deferred_same_company = 0
    for target in eligible:
        company = normalized_key(target.company)
        if company in selected_companies:
            deferred_same_company += 1
        elif len(selected) < limit:
            selected.append(target)
            selected_companies.add(company)
    report: dict[str, object] = {
        "status": "complete",
        "eligible": len(eligible),
        "requested": len(selected),
        "received": 0,
        "applied": 0,
        "improved": 0,
        "no_change": 0,
        "not_found": 0,
        "failed": 0,
        "skipped_cached": skipped_cached,
        "deferred_same_company": deferred_same_company,
        "salary_added": 0,
        "location_added": 0,
        "work_mode_added": 0,
        "apply_links_added": 0,
    }
    if not selected:
        return report
    received = 0
    applied = 0
    improved = 0
    no_change = 0
    not_found = 0
    failed = 0
    field_counts = {field: 0 for field in ("salary", "location", "work_mode", "apply_url")}
    with (
        httpx.Client(timeout=max(timeout, 120), follow_redirects=False, trust_env=False) as client,
        ThreadPoolExecutor(max_workers=min(5, len(selected))) as executor,
    ):
        futures = {}
        for request_target in selected:
            futures[
                executor.submit(
                    client.post,
                    BRIGHT_DATA_ENDPOINT,
                    params={
                        "dataset_id": BRIGHT_DATA_DATASET_ID,
                        "notify": "false",
                        "include_errors": "true",
                        "format": "json",
                    },
                    headers={"Authorization": f"Bearer {api_token}"},
                    json={"input": [{"url": request_target.source_url}]},
                )
            ] = request_target
        for future in as_completed(futures):
            request_target = futures[future]
            posting_id = _linkedin_id(request_target.source_url)
            try:
                response = future.result()
                items = _response_items(client, response, api_token=api_token, timeout=timeout)
            except (httpx.HTTPError, ValueError):
                failed += 1
                _record_attempt(database, posting_id, "failed")
                continue
            matched_item = None
            for item in items:
                if not isinstance(item, dict):
                    continue
                if str(item.get("job_posting_id") or "") != posting_id or normalized_key(
                    str(item.get("job_title") or "")
                ) != normalized_key(request_target.title):
                    continue
                matched_item = item
                break
            if matched_item is None:
                not_found += 1
                _record_attempt(database, posting_id, "not_found")
                continue
            received += 1
            fields_added = database.apply_linkedin_enrichment(
                request_target.job_id,
                request_target.observation_id,
                _observation(matched_item, request_target),
            )
            applied += 1
            if fields_added:
                improved += 1
                for field in fields_added:
                    field_counts[field] += 1
                _record_attempt(database, posting_id, "improved", fields_added=fields_added)
            else:
                no_change += 1
                _record_attempt(database, posting_id, "no_change")
    report["received"] = received
    report["applied"] = applied
    report["improved"] = improved
    report["no_change"] = no_change
    report["not_found"] = not_found
    report["failed"] = failed
    report["salary_added"] = field_counts["salary"]
    report["location_added"] = field_counts["location"]
    report["work_mode_added"] = field_counts["work_mode"]
    report["apply_links_added"] = field_counts["apply_url"]
    return report
