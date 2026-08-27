from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from job_puller.config import CommercialProvider, SearchSettings
from job_puller.models import JobObservation, ProviderResult
from job_puller.normalize import html_to_text, normalized_key, parse_datetime


class JobSpyProvider:
    def __init__(self, site: str, settings: CommercialProvider, search: SearchSettings):
        if site not in {"linkedin", "indeed"}:
            raise ValueError(f"unsupported JobSpy site: {site}")
        self.name = site
        self.source_key = f"jobspy:{site}"
        self.settings = settings
        self.search = search

    def fetch(self, since: datetime) -> ProviderResult:
        started = datetime.now(UTC)
        observations: list[JobObservation] = []
        errors: list[str] = []
        try:
            from jobspy import scrape_jobs
        except ImportError as exc:
            return ProviderResult(self.source_key, self.name, [], started, datetime.now(UTC), False, str(exc))

        hours_old = max(1, int((started - since).total_seconds() / 3600) + 1)
        for family in self.search.families:
            for configured_term in family.terms:
                for query in self._provider_queries(configured_term):
                    try:
                        kwargs: dict[str, Any] = {
                            "site_name": [self.name],
                            "search_term": query,
                            "location": self.search.location,
                            "results_wanted": self.settings.results_wanted,
                            "country_indeed": "USA",
                            "description_format": "html",
                            "verbose": 0,
                        }
                        if self.name == "indeed" and self.search.remote_only:
                            # Indeed treats freshness and remote as mutually exclusive server filters.
                            # Ask Indeed for remote jobs, then apply freshness locally below.
                            kwargs["is_remote"] = True
                        else:
                            kwargs["hours_old"] = hours_old
                            if self.search.remote_only:
                                kwargs["is_remote"] = True
                        if self.name == "linkedin":
                            kwargs["linkedin_fetch_description"] = self.settings.fetch_descriptions
                        frame = scrape_jobs(**kwargs)
                        for row in frame.to_dict(orient="records"):
                            observation = self._normalize(row, family.name)
                            if (
                                observation
                                and self._title_matches(observation.title, configured_term)
                                and self._remote_eligible(observation)
                                and self._recent_enough(observation, since)
                            ):
                                observations.append(observation)
                    except Exception as exc:
                        errors.append(f"{family.name}/{query}: {type(exc).__name__}: {exc}")

        deduped = {
            f"{item.provider}:{item.provider_job_id or item.source_url}": item for item in observations
        }
        completed = datetime.now(UTC)
        success = not errors or bool(deduped)
        return ProviderResult(
            self.source_key,
            self.name,
            list(deduped.values()),
            started,
            completed,
            success,
            "; ".join(errors)[:4000] or None,
            suspicious_empty=success and not deduped,
        )

    def _remote_eligible(self, observation: JobObservation) -> bool:
        if not self.search.remote_only:
            return True
        location = observation.location.lower()
        return observation.remote is True or "remote" in location

    @staticmethod
    def _recent_enough(observation: JobObservation, since: datetime) -> bool:
        return observation.posted_at is None or observation.posted_at >= since

    def _provider_queries(self, configured_term: str) -> list[str]:
        if self.name != "indeed":
            return [configured_term]
        phrases = re.findall(r'"([^"]+)"', configured_term)
        if phrases:
            return phrases
        return [part.strip() for part in re.split(r"\s+OR\s+", configured_term) if part.strip()]

    @staticmethod
    def _title_matches(title: str, query: str) -> bool:
        phrases = re.findall(r'"([^"]+)"', query)
        if not phrases:
            phrases = [part.strip() for part in re.split(r"\s+OR\s+", query, flags=re.IGNORECASE)]
        normalized_title = normalized_key(title)
        return any(normalized_key(phrase) in normalized_title for phrase in phrases if normalized_key(phrase))

    def _normalize(self, row: dict[str, Any], family: str) -> JobObservation | None:
        def value(name: str, default: Any = "") -> Any:
            item = row.get(name, default)
            try:
                if item != item:  # NaN
                    return default
            except Exception:
                pass
            return item if item is not None else default

        url = str(value("job_url"))
        title = str(value("title"))
        company = str(value("company"))
        if not url or not title:
            return None
        raw_description = str(value("description"))
        job_id = str(value("id")) or url.rstrip("/").split("/")[-1].split("?")[0]
        location_parts = [str(value(key)) for key in ("city", "state", "country") if value(key)]
        location = ", ".join(location_parts) or str(value("location"))
        remote_value = value("is_remote", None)
        remote = bool(remote_value) if remote_value is not None else None
        raw_payload = {key: (None if self._is_nan(item) else item) for key, item in row.items()}
        raw_payload["search_family"] = family
        return JobObservation(
            provider=self.name,
            provider_job_id=job_id,
            title=title,
            company=company,
            source_url=url,
            direct_apply_url=str(value("job_url_direct")),
            location=location,
            description_html=raw_description,
            description_text=html_to_text(raw_description),
            posted_at=parse_datetime(value("date_posted", None)),
            salary_min=self._number(value("min_amount", None)),
            salary_max=self._number(value("max_amount", None)),
            salary_currency=str(value("currency")) or None,
            salary_interval=str(value("interval")) or None,
            employment_type=str(value("job_type")) or None,
            remote=remote,
            raw_payload=raw_payload,
            parser_version="jobspy-v1",
        )

    @staticmethod
    def _is_nan(value: Any) -> bool:
        try:
            return value != value
        except Exception:
            return False

    @staticmethod
    def _number(value: Any) -> float | None:
        try:
            result = float(value)
            return None if result != result else result
        except (TypeError, ValueError):
            return None
