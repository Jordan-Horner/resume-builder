from __future__ import annotations

import re
import time
from collections import Counter
from datetime import UTC, datetime
from typing import Any

from job_puller.config import CommercialProvider, SearchSettings
from job_puller.eligibility import commercial_title_matches, remote_matches, title_matches
from job_puller.models import JobObservation, ProviderResult
from job_puller.normalize import html_to_text, normalized_key, parse_datetime
from job_puller.work_modes import WorkMode, explicit_arrangement

_ONTARIO_CALIFORNIA = re.compile(
    r"^\s*Ontario\s*,\s*CA\s*,\s*(?:US|USA|United States)\s*$", re.IGNORECASE
)
_BASED_IN_ONTARIO = re.compile(
    r"\b(?:based|located|residing)\s+in\s+(?:the\s+)?Ontario\b", re.IGNORECASE
)
_CANADIAN_CURRENCY = re.compile(r"(?<![A-Za-z])(?:CA\$|CAD\b)", re.IGNORECASE)


class JobSpyProvider:
    def __init__(self, site: str, settings: CommercialProvider, search: SearchSettings):
        if site != "indeed":
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
            return ProviderResult(
                self.source_key, self.name, [], started, datetime.now(UTC), False, str(exc)
            )

        hours_old = max(1, int((started - since).total_seconds() / 3600) + 1)
        metrics = {
            "queries": 0,
            "raw_results": 0,
            "invalid": 0,
            "title_rejected": 0,
            "work_mode_mismatch": 0,
            "freshness_rejected": 0,
            "accepted_before_dedupe": 0,
            "duplicates": 0,
            "accepted": 0,
            "saturated_queries": 0,
        }
        rejected_titles: Counter[str] = Counter()
        query_number = 0
        for family in self.search.families:
            if not family.enabled:
                continue
            family_prefix = f"family.{family.name}."
            queries = (
                [family.provider_query]
                if family.provider_query
                else self._provider_queries(family.titles)
            )
            for query in queries:
                query_prefix = family_prefix + f"query.{normalized_key(query)}."
                result_limit = self.settings.family_results_wanted.get(
                    family.name, self.settings.results_wanted
                )
                if query_number and self.settings.request_delay_seconds:
                    time.sleep(self.settings.request_delay_seconds)
                query_number += 1
                metrics["queries"] += 1
                try:
                    kwargs: dict[str, Any] = {
                        "site_name": [self.name],
                        "search_term": query,
                        "location": self.search.location,
                        "results_wanted": result_limit,
                        "country_indeed": "USA",
                        "description_format": "html",
                        "verbose": 0,
                    }
                    if self.search.remote_only:
                        # Indeed treats freshness and remote as mutually exclusive server filters.
                        # Ask Indeed for remote jobs, then apply freshness locally below.
                        kwargs["is_remote"] = True
                    else:
                        kwargs["hours_old"] = hours_old
                        if self.search.remote_only:
                            kwargs["is_remote"] = True
                    frame = scrape_jobs(**kwargs)
                    rows = frame.to_dict(orient="records")
                    metrics["raw_results"] += len(rows)
                    if len(rows) >= result_limit:
                        metrics["saturated_queries"] += 1
                    metrics[family_prefix + "raw_results"] = metrics.get(
                        family_prefix + "raw_results", 0
                    ) + len(rows)
                    metrics[query_prefix + "raw_results"] = len(rows)
                    family_accepted = 0
                    for row in rows:
                        observation = self._normalize(row, family.name)
                        if observation is None:
                            metrics["invalid"] += 1
                        elif not commercial_title_matches(observation.title, family):
                            metrics["title_rejected"] += 1
                            rejected_titles[normalized_key(observation.title)] += 1
                        elif not self._recent_enough(observation, since):
                            metrics["freshness_rejected"] += 1
                        else:
                            if not self._remote_eligible(observation):
                                metrics["work_mode_mismatch"] += 1
                            observations.append(observation)
                            family_accepted += 1
                    metrics[family_prefix + "accepted_before_dedupe"] = (
                        metrics.get(family_prefix + "accepted_before_dedupe", 0) + family_accepted
                    )
                    metrics[query_prefix + "accepted_before_dedupe"] = family_accepted
                except Exception as exc:
                    errors.append(f"{family.name}/{query}: {type(exc).__name__}: {exc}")

        deduped = {
            f"{item.provider}:{item.provider_job_id or item.source_url}": item
            for item in observations
        }
        completed = datetime.now(UTC)
        metrics["accepted_before_dedupe"] = len(observations)
        metrics["accepted"] = len(deduped)
        metrics["duplicates"] = len(observations) - len(deduped)
        metrics.update(
            {f"rejected_title.{title}": count for title, count in rejected_titles.most_common(10)}
        )
        success = not errors
        return ProviderResult(
            self.source_key,
            self.name,
            list(deduped.values()),
            started,
            completed,
            success,
            "; ".join(errors)[:4000] or None,
            suspicious_empty=success and metrics["raw_results"] == 0,
            metrics=metrics,
        )

    def _remote_eligible(self, observation: JobObservation) -> bool:
        return remote_matches(observation, self.search)

    def _recent_enough(self, observation: JobObservation, since: datetime) -> bool:
        if observation.posted_at is None:
            return False
        # JobSpy exposes Indeed's publication value as a calendar date. Comparing its
        # midnight timestamp to an intra-day checkpoint would lose same-day postings.
        return observation.posted_at.date() >= since.date()

    def _provider_queries(self, titles: list[str]) -> list[str]:
        # Indeed's website supports Boolean/title syntax, but the GraphQL route used by
        # JobSpy can return a generic fallback page for those expressions. Plain title
        # searches plus a strict local title gate have proven reliable in live tests.
        return titles

    @staticmethod
    def _title_matches(
        title: str,
        titles: list[str],
        excluded_titles: list[str] | None = None,
    ) -> bool:
        return title_matches(title, titles, excluded_titles)

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
        if not url or not title or not company:
            return None
        raw_description = str(value("description"))
        job_id = str(value("id")) or url.rstrip("/").split("/")[-1].split("?")[0]
        location_parts = [str(value(key)) for key in ("city", "state", "country") if value(key)]
        location = ", ".join(location_parts) or str(value("location"))
        salary_currency = str(value("currency")) or None
        location, salary_currency = self._correct_indeed_geography(
            location, raw_description, salary_currency
        )
        remote_value = value("is_remote", None)
        remote = bool(remote_value) if remote_value is not None else None
        work_arrangement = (
            explicit_arrangement(
                [WorkMode.REMOTE],
                source="jobspy_structured_field",
                rule="is_remote_true",
            )
            if remote is True
            else None
        )
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
            salary_currency=salary_currency,
            salary_interval=str(value("interval")) or None,
            employment_type=str(value("job_type")) or None,
            remote=remote,
            work_arrangement=work_arrangement,
            raw_payload=raw_payload,
            parser_version="jobspy-v2",
        )

    @staticmethod
    def _correct_indeed_geography(
        location: str, description_html: str, salary_currency: str | None
    ) -> tuple[str, str | None]:
        """Repair a corroborated Indeed country/currency geocoding conflict.

        Indeed can geocode Ontario, Canada as the city of Ontario, California
        when a USA-scoped search returns a Canadian remote posting. Correct the
        structured fields only when the posting independently says candidates
        should be based in Ontario and publishes Canadian-dollar compensation.
        The untouched provider row remains available in ``raw_payload``.
        """
        canadian_compensation = bool(_CANADIAN_CURRENCY.search(description_html))
        if (
            canadian_compensation
            and _ONTARIO_CALIFORNIA.fullmatch(location)
            and _BASED_IN_ONTARIO.search(description_html)
        ):
            location = "Ontario, Canada"
            salary_currency = "CAD"
        return location, salary_currency

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
