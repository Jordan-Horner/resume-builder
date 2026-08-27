from __future__ import annotations

from datetime import UTC, datetime

import httpx

from job_puller.config import AtsBoard
from job_puller.models import JobObservation, ProviderResult
from job_puller.normalize import clean_text, html_to_text, parse_datetime


class HttpProvider:
    name = "http"

    def __init__(self, board: AtsBoard, timeout: float = 30):
        self.board = board
        self.timeout = timeout
        self.source_key = f"{self.name}:{board.id}"

    def fetch(self, since: datetime) -> ProviderResult:
        started = datetime.now(UTC)
        try:
            with httpx.Client(timeout=self.timeout, follow_redirects=True) as client:
                observations = self._fetch(client, since)
            completed = datetime.now(UTC)
            return ProviderResult(
                self.source_key,
                self.name,
                observations,
                started,
                completed,
                True,
                suspicious_empty=not observations,
                authoritative_complete=bool(observations),
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

    @staticmethod
    def _recent(observation: JobObservation, since: datetime) -> bool:
        return observation.posted_at is None or observation.posted_at >= since


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
        offset = 0
        result = []
        while True:
            payload = {"appliedFacets": {}, "limit": limit, "offset": offset, "searchText": ""}
            payload.update(self.board.extra.get("payload", {}))
            payload["limit"] = limit
            payload["offset"] = offset
            response = client.post(self.board.api_url, json=payload)
            response.raise_for_status()
            data = response.json()
            items = data.get("jobPostings") or []
            origin = self.board.api_url.split("/wday/cxs/")[0]
            for item in items:
                external = str(item.get("externalPath") or "")
                source_url = f"{origin}{external}" if external.startswith("/") else external
                observation = JobObservation(
                    provider=self.name,
                    provider_board_id=self.board.id,
                    provider_job_id=str(
                        item.get("bulletFields", [""])[0] if item.get("bulletFields") else external
                    ),
                    title=clean_text(item.get("title")),
                    company=self.board.name,
                    source_url=source_url,
                    direct_apply_url=source_url,
                    location=clean_text(item.get("locationsText")),
                    description_text="",
                    posted_at=parse_datetime(item.get("postedOn")),
                    raw_payload=item,
                    parser_version="workday-v1",
                )
                if source_url:
                    result.append(observation)
            total = int(data.get("total") or len(items))
            if not items or offset + len(items) >= total:
                break
            offset += len(items)
        return result
