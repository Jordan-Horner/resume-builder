from __future__ import annotations

import json
import re
from collections.abc import Iterable
from typing import Any

import httpx
from bs4 import BeautifulSoup

from .models import JobObservation
from .normalize import canonical_url, clean_text, html_to_text
from .url_resolution import AddressLookup, ExternalUrlError, fetch_external_page
from .work_modes import WorkArrangement, WorkMode, WorkModeEvidence, classify_work_arrangement


def _job_posting_json(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        kind = value.get("@type")
        if kind == "JobPosting" or (isinstance(kind, list) and "JobPosting" in kind):
            return value
        for child in value.values():
            found = _job_posting_json(child)
            if found:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _job_posting_json(child)
            if found:
                return found
    return None


def _schema_text(value: Any) -> str:
    if isinstance(value, dict):
        value = value.get("name") or value.get("value") or ""
    if isinstance(value, list):
        return ", ".join(filter(None, (_schema_text(item) for item in value)))
    return clean_text(str(value)) if value is not None else ""


def _location_text(value: Any) -> str:
    locations = value if isinstance(value, list) else [value]
    rendered: list[str] = []
    for location in locations:
        if not isinstance(location, dict):
            continue
        address = location.get("address", location)
        if not isinstance(address, dict):
            continue
        parts = [
            _schema_text(address.get("addressLocality")),
            _schema_text(address.get("addressRegion")),
            _schema_text(address.get("addressCountry")),
        ]
        text = ", ".join(part for part in parts if part)
        if text and text not in rendered:
            rendered.append(text)
    return " / ".join(rendered)


def _ats_work_arrangement(
    posting: dict[str, Any], location: str, description: str
) -> WorkArrangement:
    location_types = posting.get("jobLocationType")
    values: Iterable[Any] = location_types if isinstance(location_types, list) else [location_types]
    explicit_modes: dict[WorkMode, str] = {}
    for value in values:
        text = _schema_text(value)
        normalized = re.sub(r"[^a-z]", "", text.casefold())
        mode = {
            "telecommute": WorkMode.REMOTE,
            "remote": WorkMode.REMOTE,
            "hybrid": WorkMode.HYBRID,
            "onsite": WorkMode.ONSITE,
        }.get(normalized)
        if mode is not None:
            explicit_modes.setdefault(mode, text)
    if explicit_modes:
        return WorkArrangement(
            frozenset(explicit_modes),
            tuple(
                WorkModeEvidence(mode, "ats_json_ld", "jobLocationType", matched)
                for mode, matched in explicit_modes.items()
            ),
        )
    classified = classify_work_arrangement(location=location, description=description)
    if classified.available_modes == frozenset({WorkMode.UNKNOWN}):
        return classified
    return WorkArrangement(
        classified.available_modes,
        tuple(
            WorkModeEvidence(item.mode, "ats_posting", item.rule, item.matched_text)
            for item in classified.evidence
        ),
    )


def enrich_observation(
    observation: JobObservation,
    timeout: float = 30,
    *,
    address_lookup: AddressLookup | None = None,
    client: httpx.Client | None = None,
) -> JobObservation:
    if observation.provider == "workday" and observation.parser_version == "workday-cxs-v3":
        return observation
    has_description = len(observation.description_text.strip()) >= 200
    should_resolve_direct = observation.provider in {"linkedin", "indeed"} and bool(
        observation.direct_apply_url
    )
    if has_description and not should_resolve_direct:
        return observation
    url = observation.direct_apply_url or observation.source_url
    if not url.startswith(("http://", "https://")):
        return observation
    try:
        page = fetch_external_page(
            url,
            timeout=timeout,
            client=client,
            address_lookup=address_lookup,
        )
    except (ExternalUrlError, ValueError) as exc:
        if observation.direct_apply_url:
            observation.raw_payload["direct_apply_resolution"] = {
                "status": "failed",
                "url": url,
                "error": f"{type(exc).__name__}: {exc}",
            }
        return observation
    response = page.response
    if observation.direct_apply_url:
        observation.raw_payload["direct_apply_resolution"] = {
            "status": "resolved" if page.final_url != page.requested_url else "verified",
            "requested_url": page.requested_url,
            "final_url": page.final_url,
            "redirect_chain": list(page.redirect_chain),
        }
        observation.direct_apply_url = page.final_url
    soup = BeautifulSoup(response.text, "html.parser")
    posting = None
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            posting = _job_posting_json(json.loads(script.string or "null"))
        except (json.JSONDecodeError, TypeError):
            continue
        if posting:
            break
    description_html = ""
    ats_location = ""
    if posting:
        description_html = str(posting.get("description") or "")
        ats_location = _location_text(posting.get("jobLocation"))
        if not observation.direct_apply_url:
            posting_url = clean_text(posting.get("url"))
            if canonical_url(posting_url):
                observation.direct_apply_url = posting_url
        if not observation.title:
            observation.title = clean_text(posting.get("title"))
        if not observation.employment_type:
            employment_type = posting.get("employmentType")
            observation.employment_type = _schema_text(employment_type) or None
    if not description_html:
        selectors = [
            "[data-automation-id='jobPostingDescription']",
            "#content",
            ".job-description",
            ".posting-page",
            "main",
        ]
        for selector in selectors:
            node = soup.select_one(selector)
            if node and len(node.get_text(" ", strip=True)) >= 200:
                description_html = str(node)
                break
    text = html_to_text(description_html)
    if len(text) >= 100 and (posting or len(text) > len(observation.description_text)):
        observation.description_html = description_html
        observation.description_text = text
        observation.raw_payload["enriched_from"] = page.final_url
    if posting:
        arrangement = _ats_work_arrangement(posting, ats_location, text)
        if arrangement.available_modes != frozenset({WorkMode.UNKNOWN}):
            observation.work_arrangement = arrangement
            observation.remote = arrangement.available_modes == frozenset({WorkMode.REMOTE})
        observation.raw_payload["ats_job_posting"] = {
            "url": page.final_url,
            "location": ats_location,
            "work_modes": sorted(mode.value for mode in arrangement.available_modes),
        }
    return observation
