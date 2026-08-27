from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

import httpx

from job_puller.config import AtsBoard, SearchSettings
from job_puller.eligibility import (
    enabled_titles,
    family_keyword_queries,
    recent_matches,
    remote_matches,
    title_matches,
)
from job_puller.models import JobObservation, ProviderResult
from job_puller.normalize import clean_text, html_to_text, parse_datetime


class HttpProvider:
    name = "http"

    def __init__(
        self, board: AtsBoard, timeout: float = 30, search: SearchSettings | None = None
    ):
        self.board = board
        self.timeout = timeout
        self.search = search
        self.source_key = f"{self.name}:{board.id}"

    def fetch(self, since: datetime) -> ProviderResult:
        started = datetime.now(UTC)
        try:
            with httpx.Client(timeout=self.timeout, follow_redirects=True) as client:
                raw_observations = self._fetch(client, since)
            observations, metrics = self._eligible(raw_observations, since)
            completed = datetime.now(UTC)
            return ProviderResult(
                self.source_key,
                self.name,
                observations,
                started,
                completed,
                True,
                suspicious_empty=not raw_observations,
                authoritative_complete=bool(raw_observations) and self.search is None,
                metrics=metrics,
            )
        except Exception as exc:
            return ProviderResult(
                self.source_key,
                self.name,
                [],
                started,
                datetime.now(UTC),
                False,
                f"{type(exc).__name__}: {exc}",
            )

    def _fetch(self, client: httpx.Client, since: datetime) -> list[JobObservation]:
        raise NotImplementedError

    def _eligible(
        self, observations: list[JobObservation], since: datetime
    ) -> tuple[list[JobObservation], dict[str, int]]:
        metrics = {
            "raw_results": len(observations),
            "invalid": 0,
            "title_rejected": 0,
            "remote_rejected": 0,
            "freshness_rejected": 0,
            "accepted": 0,
        }
        if self.search is None:
            metrics["accepted"] = len(observations)
            return observations, metrics
        titles = enabled_titles(self.search)
        accepted = []
        for observation in observations:
            if not observation.provider_job_id or not observation.title or not observation.source_url:
                metrics["invalid"] += 1
            elif not title_matches(observation.title, titles):
                metrics["title_rejected"] += 1
            elif not remote_matches(observation, self.search):
                metrics["remote_rejected"] += 1
            elif not recent_matches(observation, since):
                metrics["freshness_rejected"] += 1
            else:
                if self.search.remote_only:
                    observation.remote = True
                accepted.append(observation)
        metrics["accepted"] = len(accepted)
        return accepted, metrics

class GreenhouseProvider(HttpProvider):
    name = "greenhouse"

    def _fetch(self, client: httpx.Client, since: datetime) -> list[JobObservation]:
        url = (
            self.board.api_url
            or f"https://boards-api.greenhouse.io/v1/boards/{self.board.id}/jobs?content=true"
        )
        response = client.get(url)
        response.raise_for_status()
        items = response.json().get("jobs", [])
        result = []
        for item in items:
            description = str(item.get("content") or "")
            observation = JobObservation(
                provider=self.name,
                provider_board_id=self.board.id,
                provider_job_id=str(item.get("id") or ""),
                title=clean_text(item.get("title")),
                company=self.board.name,
                source_url=str(item.get("absolute_url") or ""),
                direct_apply_url=str(item.get("absolute_url") or ""),
                location=clean_text((item.get("location") or {}).get("name")),
                description_html=description,
                description_text=html_to_text(description),
                posted_at=parse_datetime(item.get("updated_at")),
                raw_payload=item,
                parser_version="greenhouse-v1",
            )
            if observation.source_url:
                result.append(observation)
        return result


class LeverProvider(HttpProvider):
    name = "lever"

    def _fetch(self, client: httpx.Client, since: datetime) -> list[JobObservation]:
        url = self.board.api_url or f"https://api.lever.co/v0/postings/{self.board.id}?mode=json"
        response = client.get(url)
        response.raise_for_status()
        result = []
        for item in response.json():
            description = str(item.get("description") or item.get("descriptionPlain") or "")
            categories = item.get("categories") or {}
            observation = JobObservation(
                provider=self.name,
                provider_board_id=self.board.id,
                provider_job_id=str(item.get("id") or ""),
                title=clean_text(item.get("text")),
                company=self.board.name,
                source_url=str(item.get("hostedUrl") or item.get("applyUrl") or ""),
                direct_apply_url=str(item.get("applyUrl") or item.get("hostedUrl") or ""),
                location=clean_text(categories.get("location")),
                description_html=description,
                description_text=html_to_text(description),
                posted_at=parse_datetime(item.get("createdAt")),
                employment_type=clean_text(categories.get("commitment")) or None,
                remote="remote" in clean_text(categories.get("workplaceType")).lower(),
                raw_payload=item,
                parser_version="lever-v1",
            )
            if observation.source_url:
                result.append(observation)
        return result


class AshbyProvider(HttpProvider):
    name = "ashby"

    def _fetch(self, client: httpx.Client, since: datetime) -> list[JobObservation]:
        url = self.board.api_url or f"https://api.ashbyhq.com/posting-api/job-board/{self.board.id}"
        response = client.get(url)
        response.raise_for_status()
        result = []
        for item in response.json().get("jobs", []):
            description = str(item.get("descriptionHtml") or item.get("descriptionPlain") or "")
            observation = JobObservation(
                provider=self.name,
                provider_board_id=self.board.id,
                provider_job_id=str(item.get("id") or item.get("jobUrl") or ""),
                title=clean_text(item.get("title")),
                company=self.board.name,
                source_url=str(item.get("jobUrl") or item.get("applyUrl") or ""),
                direct_apply_url=str(item.get("applyUrl") or item.get("jobUrl") or ""),
                location=clean_text(item.get("location")),
                description_html=description,
                description_text=html_to_text(description),
                posted_at=parse_datetime(item.get("publishedAt")),
                employment_type=clean_text(item.get("employmentType")) or None,
                remote=bool(item.get("isRemote")) if item.get("isRemote") is not None else None,
                raw_payload=item,
                parser_version="ashby-v1",
            )
            if observation.source_url:
                result.append(observation)
        return result


class SmartRecruitersProvider(HttpProvider):
    name = "smartrecruiters"

    def _fetch(self, client: httpx.Client, since: datetime) -> list[JobObservation]:
        base = self.board.api_url or f"https://api.smartrecruiters.com/v1/companies/{self.board.id}/postings"
        result = []
        offset = 0
        while True:
            response = client.get(base, params={"limit": 100, "offset": offset})
            response.raise_for_status()
            payload = response.json()
            items = payload.get("content", [])
            for item in items:
                job_id = str(item.get("id") or "")
                detail = item
                if job_id:
                    detail_response = client.get(f"{base}/{job_id}")
                    if detail_response.is_success:
                        detail = detail_response.json()
                sections = detail.get("jobAd", {}).get("sections", {})
                description = "\n".join(
                    str(section.get("text") or "")
                    for section in sections.values()
                    if isinstance(section, dict)
                )
                location_data = detail.get("location") or item.get("location") or {}
                location = ", ".join(
                    str(location_data.get(key))
                    for key in ("city", "region", "country")
                    if location_data.get(key)
                )
                observation = JobObservation(
                    provider=self.name,
                    provider_board_id=self.board.id,
                    provider_job_id=job_id,
                    title=clean_text(detail.get("name") or item.get("name")),
                    company=self.board.name,
                    source_url=str(detail.get("postingUrl") or item.get("ref") or f"{base}/{job_id}"),
                    direct_apply_url=str(detail.get("applyUrl") or detail.get("postingUrl") or ""),
                    location=location,
                    description_html=description,
                    description_text=html_to_text(description),
                    posted_at=parse_datetime(detail.get("releasedDate") or item.get("releasedDate")),
                    employment_type=clean_text((detail.get("typeOfEmployment") or {}).get("label")) or None,
                    raw_payload=detail,
                    parser_version="smartrecruiters-v1",
                )
                if observation.source_url:
                    result.append(observation)
            if not items or offset + len(items) >= int(payload.get("totalFound") or len(items)):
                break
            offset += len(items)
        return result


class WorkdayProvider(HttpProvider):
    name = "workday"

    def _fetch(self, client: httpx.Client, since: datetime) -> list[JobObservation]:
        if not self.board.api_url:
            raise ValueError(f"Workday board {self.board.id!r} requires api_url")
        limit = int(self.board.extra.get("limit", 20))
        max_results = int(self.board.extra.get("max_results_per_query", 1000))
        # Workday search is token-oriented rather than exact-title matching. One
        # keyword query per configured family covers its aliases without issuing a
        # separate paginated crawl for every title; the strict local title gate
        # below still decides what enters inventory.
        queries = family_keyword_queries(self.search) if self.search else [""]
        result: dict[str, JobObservation] = {}
        origin = self.board.careers_url or self.board.api_url.split("/wday/cxs/")[0]
        fetched_at = datetime.now(UTC)
        for query in queries:
            offset = 0
            seen_pages: set[tuple[str, ...]] = set()
            while offset < max_results:
                payload = {
                    "appliedFacets": {},
                    "limit": limit,
                    "offset": offset,
                    "searchText": query,
                }
                payload.update(self.board.extra.get("payload", {}))
                payload["limit"] = limit
                payload["offset"] = offset
                payload["searchText"] = query
                response = client.post(self.board.api_url, json=payload)
                response.raise_for_status()
                items = response.json().get("jobPostings") or []
                signature = tuple(str(item.get("externalPath") or "") for item in items)
                if not items or signature in seen_pages:
                    break
                seen_pages.add(signature)
                for item in items:
                    external = str(item.get("externalPath") or "")
                    source_url = f"{origin}{external}" if external.startswith("/") else external
                    observation = JobObservation(
                        provider=self.name,
                        provider_board_id=self.board.id,
                        provider_job_id=str(
                            item.get("bulletFields", [""])[0]
                            if item.get("bulletFields")
                            else external
                        ),
                        title=clean_text(item.get("title")),
                        company=self.board.name,
                        source_url=source_url,
                        direct_apply_url=source_url,
                        location=clean_text(item.get("locationsText")),
                        description_text="",
                        posted_at=_workday_posted_at(item.get("postedOn"), fetched_at),
                        raw_payload=item,
                        parser_version="workday-v2",
                    )
                    if source_url:
                        result[observation.provider_job_id or source_url] = observation
                if len(items) < limit:
                    break
                offset += len(items)
        return list(result.values())


def _workday_posted_at(value: object, now: datetime | None = None) -> datetime | None:
    parsed = parse_datetime(value)
    if parsed is not None:
        return parsed
    current = now or datetime.now(UTC)
    text = clean_text(str(value or "")).casefold()
    if text == "posted today":
        return current
    if text == "posted yesterday":
        return current - timedelta(days=1)
    match = re.fullmatch(r"posted (\d+)\+? days? ago", text)
    return current - timedelta(days=int(match.group(1))) if match else None
