#!/usr/bin/env python3
"""Fetch one Greenhouse, Ashby, or Workday posting through its public job-board API."""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
from collections.abc import Callable
from html.parser import HTMLParser
from typing import Any, ClassVar
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

from job_puller.boards import LOCALE_SEGMENT as _WORKDAY_LOCALE_SEGMENT

JsonObject = dict[str, Any]
JsonFetcher = Callable[[str], JsonObject]


class _TextExtractor(HTMLParser):
    BLOCKS: ClassVar[set[str]] = {"br", "div", "h1", "h2", "h3", "h4", "li", "p", "ul"}

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self.BLOCKS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self.BLOCKS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def _plain_text(value: object) -> str:
    if not isinstance(value, str):
        return ""
    parser = _TextExtractor()
    parser.feed(html.unescape(value))
    lines = [" ".join(line.split()) for line in "".join(parser.parts).splitlines()]
    return "\n".join(line for line in lines if line)


def _fetch_json(url: str) -> JsonObject:
    request = Request(url, headers={"User-Agent": "resume-builder-job-screen/1.0"})
    with urlopen(request, timeout=20) as response:
        payload = json.load(response)
    if not isinstance(payload, dict):
        raise ValueError("job-board API returned a non-object response")
    return payload


def _posting_identity(url: str) -> tuple[str, str, str, str]:
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise ValueError("job posting URL must use HTTPS")
    parts = [part for part in parsed.path.split("/") if part]
    host = parsed.hostname or ""

    if host in {"boards.greenhouse.io", "job-boards.greenhouse.io"}:
        if len(parts) < 3 or parts[1] != "jobs" or not re.fullmatch(r"\d+", parts[2]):
            raise ValueError("unrecognized Greenhouse job posting URL")
        board, job_id = parts[0], parts[2]
        api_url = (
            "https://boards-api.greenhouse.io/v1/boards/"
            f"{quote(board, safe='')}/jobs/{quote(job_id, safe='')}"
        )
        return "greenhouse", board, job_id, api_url

    if host == "jobs.ashbyhq.com":
        if len(parts) < 2 or parts[1] == "application":
            raise ValueError("unrecognized Ashby job posting URL")
        board, job_id = parts[0], parts[1]
        api_url = (
            "https://api.ashbyhq.com/posting-api/job-board/"
            f"{quote(board, safe='')}?includeCompensation=true"
        )
        return "ashby", board, job_id, api_url

    if host.endswith(".myworkdayjobs.com"):
        if not parts:
            raise ValueError("unrecognized Workday job posting URL")
        tenant = host.split(".", 1)[0]
        site_index = 1 if _WORKDAY_LOCALE_SEGMENT.fullmatch(parts[0]) else 0
        if site_index >= len(parts):
            raise ValueError("unrecognized Workday job posting URL")
        site = parts[site_index]
        job_index = parsed.path.find("/job/")
        if job_index < 0:
            raise ValueError("Workday posting URL has no job path")
        external_path = parsed.path[job_index:]
        board = f"{tenant}-{site}".casefold()
        job_id = parts[-1]
        api_url = f"https://{host}/wday/cxs/{quote(tenant, safe='')}/{quote(site, safe='')}{external_path}"
        return "workday", board, job_id, api_url

    raise ValueError("supported posting providers are Greenhouse, Ashby, and Workday")


def _greenhouse_result(
    source_url: str,
    board: str,
    job_id: str,
    api_url: str,
    payload: JsonObject,
) -> JsonObject:
    metadata = payload.get("metadata")
    employment_type = None
    if isinstance(metadata, list):
        employment_type = next(
            (
                item.get("value")
                for item in metadata
                if isinstance(item, dict)
                and item.get("name") == "Workforce Classification"
                and isinstance(item.get("value"), str)
            ),
            None,
        )
    location = payload.get("location")
    return {
        "provider": "greenhouse",
        "board": board,
        "id": job_id,
        "source_url": source_url,
        "api_url": api_url,
        "canonical_url": payload.get("absolute_url"),
        "title": payload.get("title"),
        "location": location.get("name") if isinstance(location, dict) else None,
        "employment_type": employment_type,
        "workplace_type": None,
        "compensation": None,
        "published_at": payload.get("first_published"),
        "updated_at": payload.get("updated_at"),
        "description": _plain_text(payload.get("content")),
    }


def _ashby_result(
    source_url: str,
    board: str,
    job_id: str,
    api_url: str,
    payload: JsonObject,
) -> JsonObject:
    jobs = payload.get("jobs")
    if not isinstance(jobs, list):
        raise ValueError("Ashby job-board API response has no jobs list")
    matches = [job for job in jobs if isinstance(job, dict) and job.get("id") == job_id]
    if len(matches) != 1:
        raise ValueError(f"Ashby posting {job_id} was not found on board {board}")
    job = matches[0]
    description = job.get("descriptionPlain")
    if not isinstance(description, str):
        description = _plain_text(job.get("descriptionHtml"))
    return {
        "provider": "ashby",
        "board": board,
        "id": job_id,
        "source_url": source_url,
        "api_url": api_url,
        "canonical_url": job.get("jobUrl"),
        "title": job.get("title"),
        "location": job.get("location"),
        "employment_type": job.get("employmentType"),
        "workplace_type": job.get("workplaceType"),
        "compensation": job.get("compensation"),
        "published_at": job.get("publishedAt"),
        "updated_at": None,
        "description": description,
    }


def _workday_result(
    source_url: str,
    board: str,
    job_id: str,
    api_url: str,
    payload: JsonObject,
) -> JsonObject:
    info = payload.get("jobPostingInfo")
    if not isinstance(info, dict):
        raise ValueError("Workday job-board API response has no jobPostingInfo")
    locations = [
        value
        for value in [info.get("location"), *(info.get("additionalLocations") or [])]
        if isinstance(value, str) and value
    ]
    locations = list(dict.fromkeys(locations))
    canonical_url = info.get("externalUrl")
    if not isinstance(canonical_url, str) or not canonical_url:
        parsed = urlparse(api_url)
        external_index = parsed.path.find("/job/")
        canonical_url = f"{parsed.scheme}://{parsed.hostname}{parsed.path[external_index:]}"
    return {
        "provider": "workday",
        "board": board,
        "id": job_id,
        "source_url": source_url,
        "api_url": api_url,
        "canonical_url": canonical_url,
        "title": info.get("title"),
        "location": " / ".join(locations) or None,
        "employment_type": info.get("timeType"),
        "workplace_type": info.get("remoteType"),
        "compensation": None,
        "published_at": info.get("postedOn"),
        "updated_at": None,
        "description": _plain_text(info.get("jobDescription")),
    }


def fetch_posting(url: str, fetch_json: JsonFetcher = _fetch_json) -> JsonObject:
    """Return one normalized posting from a supported public job-board API."""
    provider, board, job_id, api_url = _posting_identity(url)
    payload = fetch_json(api_url)
    if provider == "greenhouse":
        return _greenhouse_result(url, board, job_id, api_url, payload)
    if provider == "workday":
        return _workday_result(url, board, job_id, api_url, payload)
    return _ashby_result(url, board, job_id, api_url, payload)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", help="Greenhouse, Ashby, or Workday job posting URL")
    args = parser.parse_args(argv)
    try:
        result = fetch_posting(args.url)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": str(exc)}, indent=2), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
