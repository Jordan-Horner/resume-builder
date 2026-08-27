from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest

from job_puller.config import LinkedInProviderSettings, SearchSettings
from job_puller.database import InventoryDatabase
from job_puller.models import JobObservation, ProviderResult
from job_puller.providers.linkedin import (
    LinkedInBlockedError,
    LinkedInError,
    LinkedInGuestClient,
    LinkedInGuestProvider,
    parse_job_detail,
    parse_search_cards,
)
from job_puller.work_modes import WorkMode

SINCE = datetime(2026, 8, 20, 12, tzinfo=UTC)


def card(job_id: int, title: str, *, location: str = "United States") -> str:
    return f"""
    <div class="base-search-card" data-entity-urn="urn:li:jobPosting:{job_id}">
      <a class="base-card__full-link"
         href="https://www.linkedin.com/jobs/view/{title.lower().replace(' ', '-')}-{job_id}?trackingId=x">
      </a>
      <h3 class="base-search-card__title">{title}</h3>
      <h4 class="base-search-card__subtitle">Example Corp</h4>
      <span class="job-search-card__location">{location}</span>
      <time datetime="2026-08-26">1 day ago</time>
    </div>
    """


def detail(description: str = "This is a fully remote role building reliable cloud services.") -> str:
    return f"""
    <section>
      <div class="show-more-less-html__markup"><p>{description}</p></div>
      <ul class="description__job-criteria-list">
        <li class="description__job-criteria-item">
          <h3 class="description__job-criteria-subheader">Employment type</h3>
          <span class="description__job-criteria-text">Full-time</span>
        </li>
      </ul>
    </section>
    """


class FakeLinkedInClient:
    def __init__(self, pages=None, details=None, search_error=None, detail_error=None):
        self.pages = pages or {}
        self.details = details or {}
        self.search_error = search_error
        self.detail_error = detail_error
        self.search_calls: list[dict] = []
        self.detail_calls: list[str] = []

    def search(self, params):
        self.search_calls.append(dict(params))
        if self.search_error:
            raise self.search_error
        return self.pages.get(params["start"], "")

    def detail(self, job_id):
        self.detail_calls.append(job_id)
        if self.detail_error:
            raise self.detail_error
        return self.details.get(job_id)


def provider(
    client,
    *,
    results_wanted=20,
    max_cards_scanned=100,
    remote_policy="strict",
    detail_cache=None,
):
    return LinkedInGuestProvider(
        LinkedInProviderSettings(
            results_wanted=results_wanted,
            fetch_descriptions=True,
            request_delay_seconds=0,
            max_cards_scanned=max_cards_scanned,
            remote_policy=remote_policy,
        ),
        SearchSettings(
            location="United States",
            remote_only=True,
            families=[{"name": "reliability", "titles": ["SRE"]}],
        ),
        client=client,
        detail_cache=detail_cache,
    )


def test_search_parser_extracts_stable_id_and_strips_tracking():
    cards, invalid = parse_search_cards(card(123456789, "Senior SRE"))
    assert invalid == 0
    assert len(cards) == 1
    assert cards[0].job_id == "123456789"
    assert cards[0].source_url == "https://www.linkedin.com/jobs/view/123456789"
    assert cards[0].posted_at == datetime(2026, 8, 26, tzinfo=UTC)


def test_detail_parser_extracts_description_and_criteria():
    parsed = parse_job_detail(detail())
    assert parsed is not None
    assert parsed.description_text == "This is a fully remote role building reliable cloud services."
    assert parsed.employment_type == "Full-time"
    assert parsed.criteria == {"Employment type": "Full-time"}


def test_detail_parser_extracts_external_apply_url():
    parsed = parse_job_detail(
        detail()
        + """
        <code id="applyUrl">https://www.linkedin.com/jobs/view/externalApply/123?
        url=https%3A%2F%2Fcareers.example.com%2Fapply%3Fjob%3D123&amp;urlHash=abc</code>
        """
    )
    assert parsed is not None
    assert parsed.direct_apply_url == "https://careers.example.com/apply?job=123"


def test_provider_uses_fixed_offsets_and_filters_before_details():
    first_page = card(1, "Senior SRE") + "".join(
        card(job_id, "Sales Representative") for job_id in range(2, 11)
    )
    second_page = card(11, "Cloud SRE") + card(1, "Senior SRE")
    client = FakeLinkedInClient(
        pages={0: first_page, 10: second_page},
        details={
            "1": detail(),
            "11": detail("This remote position operates a distributed production platform."),
        },
    )

    result = provider(client, results_wanted=2).fetch(SINCE)

    assert result.success
    assert [call["start"] for call in client.search_calls] == [0, 10]
    assert client.detail_calls == ["1", "11"]
    assert {item.provider_job_id for item in result.observations} == {"1", "11"}
    assert all(item.provider == "linkedin" for item in result.observations)
    assert all(item.remote is True for item in result.observations)
    assert all(item.parser_version == "linkedin-guest-v2" for item in result.observations)
    assert result.metrics["raw_results"] == 12
    assert result.metrics["title_rejected"] == 9
    assert result.metrics["card_duplicates"] == 1
    assert result.metrics["detail_requests"] == 2
    assert result.metrics["candidate_target_reached"] == 1


def test_provider_stops_on_a_repeated_page():
    page = "".join(card(job_id, "SRE") for job_id in range(1, 11))
    client = FakeLinkedInClient(
        pages={0: page, 10: page},
        details={str(job_id): detail() for job_id in range(1, 11)},
    )
    result = provider(client, results_wanted=20).fetch(SINCE)
    assert result.success
    assert [call["start"] for call in client.search_calls] == [0, 10]
    assert result.metrics["repeated_pages"] == 1
    assert len(result.observations) == 10


def test_provider_reports_scan_limit_before_candidate_target():
    page = card(1, "SRE") + "".join(
        card(job_id, "Sales Representative") for job_id in range(2, 11)
    )
    client = FakeLinkedInClient(pages={0: page}, details={"1": detail()})
    result = provider(client, results_wanted=2, max_cards_scanned=10).fetch(SINCE)
    assert result.success
    assert len(result.observations) == 1
    assert result.metrics["qualified_cards"] == 1
    assert result.metrics["scan_limit_reached"] == 1
    assert result.metrics["saturated_queries"] == 1


def test_provider_enforces_minimum_incremental_lookback():
    client = FakeLinkedInClient()
    provider(client).fetch(datetime.now(UTC) - timedelta(hours=6))
    seconds = int(client.search_calls[0]["f_TPR"].removeprefix("r"))
    assert 48 * 3600 <= seconds < 49 * 3600


@pytest.mark.parametrize(
    "description",
    [
        "Hybrid schedule with one remote day each week.",
        "Provide remote hands for physical systems.",
        "Work Type: On-Site in Huntsville.",
        "Employees are required to work in the office.",
    ],
)
def test_provider_keeps_explicit_remote_contradictions(description):
    client = FakeLinkedInClient(
        pages={0: card(1, "SRE")},
        details={"1": detail(description)},
    )
    result = provider(client).fetch(SINCE)
    assert result.success
    assert len(result.observations) == 1
    assert result.metrics["work_mode_mismatch"] == 1
    assert result.metrics["remote_contradiction_observed"] == 1


def test_provider_keeps_remote_filter_result_without_positive_evidence():
    client = FakeLinkedInClient(
        pages={0: card(1, "SRE", location="Austin, TX")},
        details={"1": detail("Build and operate reliable cloud services.")},
    )
    result = provider(client).fetch(SINCE)
    assert result.success
    assert len(result.observations) == 1
    assert result.observations[0].work_modes == {WorkMode.UNKNOWN}
    assert result.metrics["work_mode_mismatch"] == 1
    assert result.metrics["remote_unverified_observed"] == 1


def test_remote_evidence_does_not_treat_hybrid_cloud_as_a_work_arrangement():
    assert (
        LinkedInGuestProvider._remote_evidence(
            "Cloud SRE",
            "United States",
            "This is a fully remote role supporting hybrid cloud infrastructure.",
        )
        .status
        == "verified"
    )


def test_remote_location_is_positive_evidence():
    assert (
        LinkedInGuestProvider._remote_evidence("SRE", "Remote, United States", "").status
        == "verified"
    )


def test_remote_policy_distinguishes_employer_and_source_evidence():
    strict = LinkedInGuestProvider._remote_evidence(
        "SRE", "Austin, TX", "We are a remote-first workplace.", "strict"
    )
    balanced = LinkedInGuestProvider._remote_evidence(
        "SRE", "Austin, TX", "We are a remote-first workplace.", "balanced"
    )
    source = LinkedInGuestProvider._remote_evidence(
        "SRE", "Austin, TX", "Build reliable services.", "source"
    )
    contradicted = LinkedInGuestProvider._remote_evidence(
        "SRE", "Austin, TX", "This is a hybrid work schedule.", "source"
    )
    assert strict.status == "unverified"
    assert strict.rule == "balanced_evidence_not_allowed"
    assert balanced.status == "verified"
    assert balanced.rule == "remote_first_employer"
    assert source.status == "verified"
    assert source.rule == "linkedin_source_filter"
    assert contradicted.status == "contradiction"


def test_provider_surfaces_block_and_does_not_report_healthy_empty():
    client = FakeLinkedInClient(search_error=LinkedInBlockedError("LinkedIn returned HTTP 429"))
    result = provider(client).fetch(SINCE)
    assert not result.success
    assert not result.suspicious_empty
    assert result.error == "LinkedIn returned HTTP 429"


def test_transport_maps_429_to_blocked_error():
    class RateLimitedClient:
        def get(self, url, params=None):
            return httpx.Response(429, request=httpx.Request("GET", url))

    client = LinkedInGuestClient(RateLimitedClient(), 0)
    with pytest.raises(LinkedInBlockedError, match="429"):
        client.search({"keywords": "SRE", "start": 0})


def test_transport_rejects_challenge_page_with_http_200():
    class ChallengeClient:
        def get(self, url, params=None):
            return httpx.Response(
                200,
                text="<html>checkpoint/challenge captcha</html>",
                request=httpx.Request("GET", url),
            )

    client = LinkedInGuestClient(ChallengeClient(), 0)
    with pytest.raises(LinkedInBlockedError, match="challenge"):
        client.search({"keywords": "SRE", "start": 0})


def test_transport_surfaces_unexpected_initial_400():
    class BadRequestClient:
        def get(self, url, params=None):
            return httpx.Response(400, request=httpx.Request("GET", url))

    client = LinkedInGuestClient(BadRequestClient(), 0)
    with pytest.raises(LinkedInError, match="offset 0"):
        client.search({"keywords": "SRE", "start": 0})


def test_detail_cache_avoids_repeat_network_request(tmp_path):
    database = InventoryDatabase(tmp_path / "inventory.db")
    database.migrate()
    first_client = FakeLinkedInClient(pages={0: card(1, "SRE")}, details={"1": detail()})
    first = provider(first_client, detail_cache=database).fetch(SINCE)
    assert first.success
    assert first.metrics["detail_cache_misses"] == 1
    assert first_client.detail_calls == ["1"]

    second_client = FakeLinkedInClient(pages={0: card(1, "SRE")})
    second = provider(second_client, detail_cache=database).fetch(SINCE)
    assert second.success
    assert second.metrics["detail_cache_hits"] == 1
    assert second.metrics["detail_requests_saved"] == 1
    assert second_client.detail_calls == []
    assert len(second.observations) == 1


def test_expired_detail_cache_is_refreshed(tmp_path):
    database = InventoryDatabase(tmp_path / "inventory.db")
    database.migrate()
    old = datetime.now(UTC) - timedelta(days=2)
    database.put_provider_detail(
        "linkedin",
        "1",
        "linkedin-guest-v2",
        detail("Old remote description."),
        old,
        old + timedelta(hours=1),
    )
    client = FakeLinkedInClient(pages={0: card(1, "SRE")}, details={"1": detail()})
    result = provider(client, detail_cache=database).fetch(SINCE)
    assert result.success
    assert result.metrics["detail_cache_expired"] == 1
    assert result.metrics["detail_cache_misses"] == 1
    assert client.detail_calls == ["1"]


def test_cache_failure_surfaces_but_keeps_observation():
    class BrokenCache:
        def get_provider_detail(self, provider, provider_job_id, parser_version):
            raise OSError("cache unavailable")

        def put_provider_detail(self, *args):
            raise OSError("cache unavailable")

    client = FakeLinkedInClient(pages={0: card(1, "SRE")}, details={"1": detail()})
    result = provider(client, detail_cache=BrokenCache()).fetch(SINCE)
    assert not result.success
    assert len(result.observations) == 1
    assert result.metrics["detail_cache_errors"] == 2
    assert "cache unavailable" in (result.error or "")


def test_malformed_detail_does_not_hide_later_jobs(tmp_path):
    client = FakeLinkedInClient(
        pages={0: card(1, "SRE") + card(2, "SRE")},
        details={"1": "<html>changed markup</html>", "2": detail()},
    )
    result = provider(client, results_wanted=2).fetch(SINCE)
    assert not result.success
    assert result.metrics["detail_parse_failed"] == 1
    assert [item.provider_job_id for item in result.observations] == ["2"]
    assert client.detail_calls == ["1", "2"]
    database = InventoryDatabase(tmp_path / "inventory.db")
    database.migrate()
    database.record_result(result)
    assert database.checkpoint("linkedin:guest") is None


def test_unrecognized_search_markup_is_an_explicit_failure():
    client = FakeLinkedInClient(pages={0: "<html><main>new markup</main></html>"})
    result = provider(client).fetch(SINCE)
    assert not result.success
    assert not result.suspicious_empty
    assert "markup was not recognized" in (result.error or "")


def test_new_source_updates_existing_linkedin_observation_without_duplicate(tmp_path):
    database = InventoryDatabase(tmp_path / "inventory.db")
    database.migrate()
    old = JobObservation(
        provider="linkedin",
        provider_job_id="123",
        title="SRE",
        company="Example",
        source_url="https://www.linkedin.com/jobs/view/123",
    )
    first = ProviderResult(
        "jobspy:linkedin",
        "linkedin",
        [old],
        SINCE,
        SINCE,
        True,
    )
    assert database.record_result(first) == (1, 0)

    replacement = JobObservation(
        provider="linkedin",
        provider_job_id="123",
        title="Senior SRE",
        company="Example",
        source_url="https://www.linkedin.com/jobs/view/123",
        parser_version="linkedin-guest-v1",
    )
    second = ProviderResult(
        "linkedin:guest",
        "linkedin",
        [replacement],
        SINCE,
        SINCE,
        True,
    )
    assert database.record_result(second) == (0, 1)
    with database.connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS count, source_key, parser_version FROM observations"
        ).fetchone()
    assert row["count"] == 1
    assert row["source_key"] == "linkedin:guest"
    assert row["parser_version"] == "linkedin-guest-v1"
