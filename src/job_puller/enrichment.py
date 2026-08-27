from __future__ import annotations

import json
from typing import Any

import httpx
from bs4 import BeautifulSoup

from .models import JobObservation
from .normalize import clean_text, html_to_text


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


def enrich_observation(observation: JobObservation, timeout: float = 30) -> JobObservation:
    if len(observation.description_text.strip()) >= 200:
        return observation
    url = observation.direct_apply_url or observation.source_url
    if not url.startswith(("http://", "https://")):
        return observation
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            response = client.get(
                url, headers={"User-Agent": "JobPuller/0.1 (+local personal inventory)"}
            )
            response.raise_for_status()
    except (httpx.HTTPError, ValueError):
        return observation
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
    if posting:
        description_html = str(posting.get("description") or "")
        observation.direct_apply_url = str(posting.get("url") or observation.direct_apply_url)
        if not observation.title:
            observation.title = clean_text(posting.get("title"))
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
    if len(text) > len(observation.description_text):
        observation.description_html = description_html
        observation.description_text = text
        observation.raw_payload["enriched_from"] = str(response.url)
    return observation
