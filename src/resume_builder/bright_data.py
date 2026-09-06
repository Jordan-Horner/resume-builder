"""Optional Bright Data enrichment for unresolved LinkedIn observations."""

from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
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
        parser_version="linkedin-bright-data-v1",
    )


def enrich_linkedin_targets(
    database: InventoryDatabase,
    targets: list[LinkedInTarget],
    *,
    api_token: str,
    limit: int,
    timeout: float = 60,
) -> dict[str, object]:
    selected = [target for target in targets if _linkedin_id(target.source_url)][:limit]
    report: dict[str, object] = {
        "status": "complete",
        "requested": len(selected),
        "received": 0,
        "applied": 0,
        "failed": 0,
    }
    if not selected:
        return report
    by_id = {_linkedin_id(target.source_url): target for target in selected}
    received = 0
    applied = 0
    failed = 0
    with (
        httpx.Client(timeout=timeout, follow_redirects=False, trust_env=False) as client,
        ThreadPoolExecutor(max_workers=min(5, len(selected))) as executor,
    ):
        futures = {}
        for request_target in selected:
            futures[
                executor.submit(
                    client.post,
                    BRIGHT_DATA_ENDPOINT,
                    params={"dataset_id": BRIGHT_DATA_DATASET_ID, "include_errors": "true"},
                    headers={"Authorization": f"Bearer {api_token}"},
                    json={"input": [{"url": request_target.source_url}]},
                )
            ] = request_target
        for future in as_completed(futures):
            try:
                response = future.result()
                response.raise_for_status()
                payload = response.json()
                items = payload if isinstance(payload, list) else [payload]
            except (httpx.HTTPError, ValueError):
                failed += 1
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                posting_id = str(item.get("job_posting_id") or "")
                matched_target = by_id.get(posting_id)
                if matched_target is None or normalized_key(
                    str(item.get("job_title") or "")
                ) != normalized_key(matched_target.title):
                    continue
                received += 1
                database.apply_linkedin_enrichment(
                    matched_target.job_id,
                    matched_target.observation_id,
                    _observation(item, matched_target),
                )
                applied += 1
    report["received"] = received
    report["applied"] = applied
    report["failed"] = failed
    return report
