from __future__ import annotations

import math
import random
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from html import unescape
from typing import Any
from urllib.parse import unquote, urlsplit, urlunsplit

import httpx
from bs4 import BeautifulSoup, Tag

from job_puller.config import LinkedInProviderSettings, SearchSettings
from job_puller.detail_cache import ProviderDetailCache
from job_puller.models import JobObservation, ProviderResult
from job_puller.normalize import html_to_text, normalized_key, parse_datetime
from job_puller.work_modes import WorkMode, explicit_arrangement

_BASE_URL = "https://www.linkedin.com"
_SEARCH_URL = f"{_BASE_URL}/jobs-guest/jobs/api/seeMoreJobPostings/search"
_DETAIL_URL = f"{_BASE_URL}/jobs-guest/jobs/api/jobPosting"
_PAGE_SIZE = 10
_MAX_START = 999
_JOB_ID_RE = re.compile(r"(?:urn:li:jobPosting:|/jobs/view/(?:[^/?#]*-)?)(\d+)")
_PARSER_VERSION = "linkedin-guest-v2"


class LinkedInError(RuntimeError):
    pass


class LinkedInBlockedError(LinkedInError):
    pass


class LinkedInUnavailableError(LinkedInError):
    pass


@dataclass(slots=True)
class LinkedInCard:
    job_id: str
    title: str
    company: str
    location: str
    posted_at: datetime | None
    posted_label: str
    source_url: str
    raw_html: str


@dataclass(slots=True)
class LinkedInDetail:
    description_html: str
    description_text: str
    employment_type: str | None
    direct_apply_url: str
    criteria: dict[str, str]
    raw_html: str


@dataclass(frozen=True, slots=True)
class RemoteEvidence:
    status: str
    rule: str
    source: str
    matched_text: str = ""


@dataclass(slots=True)
class _Candidate:
    card: LinkedInCard
    families: set[str] = field(default_factory=set)
    metric_keys: set[str] = field(default_factory=set)


class LinkedInGuestClient:
    def __init__(
        self,
        client: httpx.Client,
        request_delay_seconds: float,
        *,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ):
        self.client = client
        self.request_delay_seconds = request_delay_seconds
        self.sleep = sleep
        self.monotonic = monotonic
        self._last_request_at: float | None = None

    def search(self, params: dict[str, Any]) -> str:
        response = self._get(_SEARCH_URL, params=params)
        if response.status_code == 400:
            if int(params.get("start", 0)) >= 990:
                return ""
            raise LinkedInError(f"LinkedIn search returned HTTP 400 at offset {params.get('start', 0)}")
        self._raise_for_status(response)
        self._raise_for_challenge(response)
        return response.text

    def detail(self, job_id: str) -> str | None:
        response = self._get(f"{_DETAIL_URL}/{job_id}")
        if response.status_code == 404:
            return None
        self._raise_for_status(response)
        self._raise_for_challenge(response)
        return response.text

    def _get(self, url: str, params: dict[str, Any] | None = None) -> httpx.Response:
        if self._last_request_at is not None and self.request_delay_seconds:
            elapsed = self.monotonic() - self._last_request_at
            remaining = self.request_delay_seconds - elapsed
            if remaining > 0:
                self.sleep(remaining + random.uniform(0, min(0.2, self.request_delay_seconds / 10)))
        try:
            response = self.client.get(url, params=params)
        except httpx.HTTPError as exc:
            raise LinkedInUnavailableError(f"LinkedIn request failed: {exc}") from exc
        finally:
            self._last_request_at = self.monotonic()
        return response

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        if response.status_code in {401, 403, 429}:
            raise LinkedInBlockedError(f"LinkedIn returned HTTP {response.status_code}")
        if response.status_code >= 500:
            raise LinkedInUnavailableError(f"LinkedIn returned HTTP {response.status_code}")
        if not 200 <= response.status_code < 300:
            raise LinkedInError(f"LinkedIn returned HTTP {response.status_code}")

    @staticmethod
    def _raise_for_challenge(response: httpx.Response) -> None:
        body = response.text.casefold()
        final_url = str(response.url).casefold()
        redirected_to_auth = any(marker in final_url for marker in ("/signup", "/login", "authwall"))
        challenge_body = any(marker in body for marker in ("checkpoint/challenge", "captcha"))
        if redirected_to_auth or challenge_body:
            raise LinkedInBlockedError("LinkedIn returned a login or challenge page")


def parse_search_cards(html: str) -> tuple[list[LinkedInCard], int]:
    soup = BeautifulSoup(html, "html.parser")
    cards: list[LinkedInCard] = []
    invalid = 0
    for node in soup.select("div.base-search-card"):
        card = _parse_card(node)
        if card is None:
            invalid += 1
        else:
            cards.append(card)
    return cards, invalid


def _parse_card(node: Tag) -> LinkedInCard | None:
    link = node.select_one("a.base-card__full-link")
    href = str(link.get("href") or "") if link else ""
    urn = str(node.get("data-entity-urn") or "")
    match = _JOB_ID_RE.search(urn) or _JOB_ID_RE.search(href)
    title_node = node.select_one("h3.base-search-card__title") or node.select_one("span.sr-only")
    title = _node_text(title_node)
    if not match or not title:
        return None
    job_id = match.group(1)
    time_node = node.select_one("time")
    posted_value = str(time_node.get("datetime") or "") if time_node else ""
    return LinkedInCard(
        job_id=job_id,
        title=title,
        company=_node_text(node.select_one("h4.base-search-card__subtitle")),
        location=_node_text(node.select_one("span.job-search-card__location")),
        posted_at=parse_datetime(posted_value),
        posted_label=_node_text(time_node),
        source_url=f"{_BASE_URL}/jobs/view/{job_id}",
        raw_html=str(node),
    )


def parse_job_detail(html: str) -> LinkedInDetail | None:
    soup = BeautifulSoup(html, "html.parser")
    description_node = soup.select_one("div.show-more-less-html__markup")
    if description_node is None:
        return None
    description_html = str(description_node)
    criteria: dict[str, str] = {}
    for item in soup.select("li.description__job-criteria-item"):
        label = _node_text(item.select_one("h3.description__job-criteria-subheader"))
        value = _node_text(item.select_one("span.description__job-criteria-text"))
        if label and value:
            criteria[label] = value
    employment_type = next(
        (value for label, value in criteria.items() if label.casefold() == "employment type"),
        None,
    )
    direct_apply_url = ""
    apply_node = soup.select_one("code#applyUrl")
    if apply_node:
        encoded = unescape(apply_node.decode_contents()).replace("\\u0026", "&")
        encoded = re.sub(r"\s+", "", encoded)
        match = re.search(r"[?&]url=([^\"&<]+)", encoded)
        if match:
            candidate = unquote(match.group(1)).strip()
            try:
                parts = urlsplit(candidate)
            except ValueError:
                parts = None
            if parts and parts.scheme in {"http", "https"} and parts.netloc:
                direct_apply_url = candidate
    return LinkedInDetail(
        description_html=description_html,
        description_text=html_to_text(description_html),
        employment_type=employment_type,
        direct_apply_url=direct_apply_url,
        criteria=criteria,
        raw_html=html,
    )


def _node_text(node: Tag | None) -> str:
    return " ".join(node.get_text(" ", strip=True).split()) if node else ""


def _strip_tracking(url: str) -> str:
    try:
        parts = urlsplit(url)
    except ValueError:
        return ""
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


class LinkedInGuestProvider:
    name = "linkedin"
    source_key = "linkedin:guest"

    def __init__(
        self,
        settings: LinkedInProviderSettings,
        search: SearchSettings,
        request_timeout_seconds: float = 30,
        client: LinkedInGuestClient | None = None,
        detail_cache: ProviderDetailCache | None = None,
    ):
        self.settings = settings
        self.search = search
        self.request_timeout_seconds = request_timeout_seconds
        self.client = client
        self.detail_cache = detail_cache

    def fetch(self, since: datetime) -> ProviderResult:
        if self.client is not None:
            return self._fetch(since, self.client)
        headers = {
            "Accept-Language": "en-US,en;q=0.9",
            "User-Agent": "JobPuller/0.1 (+local personal inventory)",
        }
        try:
            with httpx.Client(
                timeout=self.request_timeout_seconds,
                follow_redirects=True,
                headers=headers,
            ) as http_client:
                client = LinkedInGuestClient(http_client, self.settings.request_delay_seconds)
                return self._fetch(since, client)
        except (httpx.HTTPError, ValueError) as exc:
            now = datetime.now(UTC)
            return ProviderResult(
                self.source_key,
                self.name,
                [],
                now,
                now,
                False,
                f"{type(exc).__name__}: {exc}",
            )

    def _fetch(self, since: datetime, client: LinkedInGuestClient) -> ProviderResult:
        started = datetime.now(UTC)
        metrics: dict[str, int] = {
            "queries": 0,
            "search_pages": 0,
            "raw_results": 0,
            "cards_scanned": 0,
            "qualified_cards": 0,
            "candidate_target_reached": 0,
            "scan_limit_reached": 0,
            "invalid": 0,
            "card_duplicates": 0,
            "repeated_pages": 0,
            "title_rejected": 0,
            "freshness_rejected": 0,
            "detail_requests": 0,
            "detail_fetched": 0,
            "detail_unavailable": 0,
            "detail_parse_failed": 0,
            "detail_cache_hits": 0,
            "detail_cache_misses": 0,
            "detail_cache_expired": 0,
            "detail_cache_errors": 0,
            "detail_requests_saved": 0,
            "remote_rejected": 0,
            "remote_contradiction_rejected": 0,
            "remote_unverified_rejected": 0,
            "accepted_before_dedupe": 0,
            "duplicates": 0,
            "accepted": 0,
            "saturated_queries": 0,
        }
        candidates: dict[str, _Candidate] = {}
        fatal_errors: list[str] = []
        partial_errors: list[str] = []
        rolling_since = started - timedelta(hours=self.settings.incremental_lookback_hours)
        effective_since = min(since, rolling_since)
        seconds_old = max(1, math.ceil((started - effective_since).total_seconds()))
        metrics["effective_lookback_seconds"] = seconds_old

        try:
            for family in self.search.families:
                if not family.enabled:
                    continue
                query = self._provider_query(family.titles)
                query_key = f"family.{family.name}.query.{normalized_key(query)}."
                family_key = f"family.{family.name}."
                target = self.settings.family_results_wanted.get(
                    family.name, self.settings.results_wanted
                )
                metrics["queries"] += 1
                scanned_for_query = 0
                qualified_for_query = 0
                seen_for_query: set[str] = set()
                offset = 0
                while (
                    qualified_for_query < target
                    and scanned_for_query < self.settings.max_cards_scanned
                    and offset <= _MAX_START
                ):
                    params: dict[str, Any] = {
                        "keywords": query,
                        "location": self.search.location,
                        "f_TPR": f"r{seconds_old}",
                        "start": offset,
                    }
                    if self.search.remote_only:
                        params["f_WT"] = 2
                    html = client.search(params)
                    metrics["search_pages"] += 1
                    cards, invalid = parse_search_cards(html)
                    metrics["invalid"] += invalid
                    if not cards:
                        if html.strip():
                            raise LinkedInError(
                                f"LinkedIn search-card markup was not recognized at offset {offset}"
                            )
                        break
                    page_ids = {card.job_id for card in cards}
                    if page_ids and page_ids <= seen_for_query:
                        metrics["repeated_pages"] += 1
                        break
                    remaining = self.settings.max_cards_scanned - scanned_for_query
                    selected = cards[:remaining]
                    scanned_for_query += len(selected)
                    metrics["raw_results"] += len(selected)
                    metrics["cards_scanned"] += len(selected)
                    metrics[family_key + "raw_results"] = (
                        metrics.get(family_key + "raw_results", 0) + len(selected)
                    )
                    metrics[query_key + "raw_results"] = (
                        metrics.get(query_key + "raw_results", 0) + len(selected)
                    )
                    for card in selected:
                        if card.job_id in seen_for_query:
                            metrics["card_duplicates"] += 1
                            continue
                        seen_for_query.add(card.job_id)
                        if not self._title_matches(card.title, family.titles):
                            metrics["title_rejected"] += 1
                            continue
                        if not self._recent_enough(card.posted_at, effective_since):
                            metrics["freshness_rejected"] += 1
                            continue
                        if qualified_for_query >= target:
                            continue
                        qualified_for_query += 1
                        metrics["qualified_cards"] += 1
                        candidate = candidates.setdefault(card.job_id, _Candidate(card))
                        candidate.families.add(family.name)
                        candidate.metric_keys.update({family_key, query_key})
                    if len(cards) < _PAGE_SIZE:
                        break
                    offset += _PAGE_SIZE
                metrics[family_key + "qualified_cards"] = qualified_for_query
                metrics[query_key + "qualified_cards"] = qualified_for_query
                if qualified_for_query >= target:
                    metrics["candidate_target_reached"] += 1
                elif scanned_for_query >= self.settings.max_cards_scanned:
                    metrics["scan_limit_reached"] += 1
                    metrics["saturated_queries"] += 1
        except LinkedInError as exc:
            fatal_errors.append(str(exc))

        observations: list[JobObservation] = []
        if not fatal_errors:
            for candidate in candidates.values():
                detail: LinkedInDetail | None = None
                if self.settings.fetch_descriptions:
                    detail_html: str | None = None
                    cache_entry = None
                    if self.detail_cache is not None:
                        try:
                            cache_entry = self.detail_cache.get_provider_detail(
                                self.name, candidate.card.job_id, _PARSER_VERSION
                            )
                        except Exception as exc:  # cache failure must surface without hiding jobs
                            metrics["detail_cache_errors"] += 1
                            partial_errors.append(
                                f"LinkedIn detail cache read failed for {candidate.card.job_id}: "
                                f"{type(exc).__name__}: {exc}"
                            )
                    now = datetime.now(UTC)
                    if cache_entry is not None and cache_entry.expires_at > now:
                        detail_html = cache_entry.response_body
                        metrics["detail_cache_hits"] += 1
                        metrics["detail_requests_saved"] += 1
                    else:
                        if self.detail_cache is not None:
                            metrics["detail_cache_misses"] += 1
                            if cache_entry is not None:
                                metrics["detail_cache_expired"] += 1
                        metrics["detail_requests"] += 1
                        try:
                            detail_html = client.detail(candidate.card.job_id)
                        except LinkedInError as exc:
                            fatal_errors.append(str(exc))
                            break
                    if detail_html is None:
                        metrics["detail_unavailable"] += 1
                        continue
                    detail = parse_job_detail(detail_html)
                    if detail is None:
                        metrics["detail_parse_failed"] += 1
                        partial_errors.append(
                            f"LinkedIn detail {candidate.card.job_id} could not be parsed"
                        )
                        continue
                    metrics["detail_fetched"] += 1
                    if (
                        self.detail_cache is not None
                        and (cache_entry is None or cache_entry.expires_at <= now)
                    ):
                        try:
                            fetched_at = datetime.now(UTC)
                            self.detail_cache.put_provider_detail(
                                self.name,
                                candidate.card.job_id,
                                _PARSER_VERSION,
                                detail_html,
                                fetched_at,
                                fetched_at + timedelta(hours=self.settings.detail_cache_hours),
                            )
                        except Exception as exc:  # cache failure must surface without hiding jobs
                            metrics["detail_cache_errors"] += 1
                            partial_errors.append(
                                f"LinkedIn detail cache write failed for {candidate.card.job_id}: "
                                f"{type(exc).__name__}: {exc}"
                            )
                if self.search.remote_only:
                    remote_evidence = self._remote_evidence(
                        candidate.card.title,
                        candidate.card.location,
                        detail.description_text if detail else "",
                        self.settings.remote_policy,
                    )
                    if remote_evidence.status != "verified":
                        metrics["remote_rejected"] += 1
                        metrics[f"remote_{remote_evidence.status}_rejected"] += 1
                        continue
                else:
                    remote_evidence = RemoteEvidence("not_filtered", "not_filtered", "none")
                observation = self._normalize(candidate, detail, remote_evidence)
                observations.append(observation)
                metrics["accepted_before_dedupe"] += len(candidate.families)
                for key in candidate.metric_keys:
                    metrics[key + "accepted_before_dedupe"] = (
                        metrics.get(key + "accepted_before_dedupe", 0) + 1
                    )

        metrics["accepted"] = len(observations)
        metrics["duplicates"] = metrics["accepted_before_dedupe"] - metrics["accepted"]
        completed = datetime.now(UTC)
        errors = fatal_errors + partial_errors
        success = not errors
        return ProviderResult(
            self.source_key,
            self.name,
            observations,
            started,
            completed,
            success,
            "; ".join(errors)[:4000] or None,
            suspicious_empty=success and metrics["raw_results"] == 0,
            metrics=metrics,
        )

    def _normalize(
        self,
        candidate: _Candidate,
        detail: LinkedInDetail | None,
        remote_evidence: RemoteEvidence,
    ) -> JobObservation:
        card = candidate.card
        description_html = detail.description_html if detail else ""
        description_text = detail.description_text if detail else ""
        raw_payload: dict[str, Any] = {
            "search_families": sorted(candidate.families),
            "remote_filter_requested": self.search.remote_only,
            "remote_policy": self.settings.remote_policy,
            "remote_evidence": {
                "status": remote_evidence.status,
                "rule": remote_evidence.rule,
                "source": remote_evidence.source,
                "matched_text": remote_evidence.matched_text,
            },
            "posted_label": card.posted_label,
            "search_card_html": card.raw_html,
        }
        if detail:
            raw_payload["criteria"] = detail.criteria
            raw_payload["detail_html"] = detail.raw_html
        work_arrangement = None
        if remote_evidence.status == "verified":
            work_arrangement = explicit_arrangement(
                [WorkMode.REMOTE],
                source=f"linkedin_{remote_evidence.source}",
                rule=remote_evidence.rule,
                matched_text=remote_evidence.matched_text,
            )
        return JobObservation(
            provider=self.name,
            provider_job_id=card.job_id,
            title=card.title,
            company=card.company,
            source_url=_strip_tracking(card.source_url),
            direct_apply_url=detail.direct_apply_url if detail else "",
            location=card.location,
            description_html=description_html,
            description_text=description_text,
            posted_at=card.posted_at,
            employment_type=detail.employment_type if detail else None,
            remote=True if self.search.remote_only else "remote" in card.location.casefold(),
            work_arrangement=work_arrangement,
            raw_payload=raw_payload,
            parser_version=_PARSER_VERSION,
        )

    @staticmethod
    def _provider_query(titles: list[str]) -> str:
        clauses = [f'"{title}"' if " " in title else title for title in titles]
        return f"({' OR '.join(clauses)})"

    @staticmethod
    def _title_matches(title: str, titles: list[str]) -> bool:
        normalized_title = f" {normalized_key(title)} "
        return any(
            f" {normalized_key(candidate)} " in normalized_title
            for candidate in titles
            if normalized_key(candidate)
        )

    @staticmethod
    def _recent_enough(posted_at: datetime | None, since: datetime) -> bool:
        if posted_at is None:
            return False
        return posted_at.date() >= since.date()

    @staticmethod
    def _remote_evidence(
        title: str,
        location: str,
        description: str,
        policy: str = "strict",
    ) -> RemoteEvidence:
        normalized_title = " ".join(title.casefold().split())
        normalized_location = " ".join(location.casefold().split())
        text = " ".join(description.casefold().split())
        title_location_exclusions = (
            ("hybrid_workplace", r"\bhybrid\b"),
            ("onsite_workplace", r"\bon-?site\b"),
            ("onsite_workplace", r"\bonsite\b"),
            ("office_workplace", r"\bin[- ]office\b"),
        )
        description_exclusions = (
            ("remote_hands", r"\bremote hands\b"),
            (
                "hybrid_schedule",
                r"\bhybrid (?:work|working|schedule|role|position|arrangement|model|policy)\b",
            ),
            (
                "hybrid_schedule",
                r"\b(?:role|position|schedule|workplace|work arrangement) "
                r"(?:is|will be|operates as) (?:a )?hybrid\b",
            ),
            ("onsite_workplace", r"\bon-?site\b"),
            ("onsite_workplace", r"\bonsite\b"),
            ("office_workplace", r"\bin[- ]office\b"),
            ("office_workplace", r"\bin the office\b"),
            ("office_workplace", r"\bfrom (?:the )?office\b"),
            ("required_office_presence", r"\brequired to have (?:a )?weekly presence\b"),
            ("required_office_presence", r"\brequired to work in (?:the )?office\b"),
            (
                "limited_remote_days",
                r"\b(?:one|two|three|four|five|\d+) remote days? (?:each|per) week\b",
            ),
            ("hybrid_schedule", r"\bremote and hybrid flexibility varies\b"),
        )
        for source, value in (("title", normalized_title), ("location", normalized_location)):
            for rule, pattern in title_location_exclusions:
                if match := re.search(pattern, value):
                    return RemoteEvidence("contradiction", rule, source, match.group(0))
        for rule, pattern in description_exclusions:
            if match := re.search(pattern, text):
                return RemoteEvidence("contradiction", rule, "description", match.group(0))

        for source, value in (("title", normalized_title), ("location", normalized_location)):
            if match := re.search(r"\bremote\b", value):
                return RemoteEvidence("verified", f"remote_{source}", source, match.group(0))

        strict_evidence = (
            ("fully_remote", r"\b(?:fully|entirely|100%) remote\b"),
            ("remote_role", r"\bremote (?:position|role|job|opportunity)\b"),
            (
                "remote_role",
                r"\b(?:position|role|job|opportunity) (?:is|will be|can be) "
                r"(?:a )?(?:fully )?remote\b",
            ),
            ("work_remotely", r"\bwork(?:ing)? remotely\b"),
            ("work_from_home", r"\bwork from home\b"),
            ("remote_candidates", r"\bopen to remote candidates\b"),
            ("remote_candidates", r"\bremote candidates\b"),
            (
                "remote_location_statement",
                r"\b(?:location|work location|workplace):? "
                r"(?:us |u\.s\. |united states )?remote\b",
            ),
            (
                "remote_us_statement",
                r"\bremote (?:within|from|anywhere in|across) "
                r"(?:the )?(?:us|u\.s\.|united states)\b",
            ),
            ("remote_us_statement", r"\b(?:us|u\.s\.|united states)[ -]+remote\b"),
        )
        for rule, pattern in strict_evidence:
            if match := re.search(pattern, text):
                return RemoteEvidence("verified", rule, "description", match.group(0))

        balanced_evidence = (
            ("remote_first_employer", r"\bremote[- ]first\b"),
            ("remote_team", r"\b(?:completely )?remote (?:workplace|team|employee|worker)\b"),
        )
        for rule, pattern in balanced_evidence:
            if match := re.search(pattern, text):
                if policy == "balanced":
                    return RemoteEvidence("verified", rule, "description", match.group(0))
                if policy == "strict":
                    return RemoteEvidence(
                        "unverified", "balanced_evidence_not_allowed", "description", match.group(0)
                    )

        if policy == "source":
            return RemoteEvidence("verified", "linkedin_source_filter", "source")
        return RemoteEvidence("unverified", "no_positive_remote_evidence", "none")
