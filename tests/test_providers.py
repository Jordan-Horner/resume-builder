from datetime import UTC, datetime

import httpx

from job_puller.config import AtsBoard, CommercialProvider, SearchSettings
from job_puller.eligibility import family_keyword_queries
from job_puller.providers.ats import (
    AshbyProvider,
    GreenhouseProvider,
    LeverProvider,
    SmartRecruitersProvider,
    WorkdayProvider,
    _workday_posted_at,
)
from job_puller.providers.jobspy_provider import JobSpyProvider


def response(method, url, payload):
    return httpx.Response(200, json=payload, request=httpx.Request(method, url))


class FakeClient:
    def __init__(self, get_payloads=None, post_payloads=None):
        self.get_payloads = list(get_payloads or [])
        self.post_payloads = list(post_payloads or [])

    def get(self, url, params=None):
        return response("GET", url, self.get_payloads.pop(0))

    def post(self, url, json=None):
        return response("POST", url, self.post_payloads.pop(0))


SINCE = datetime(2026, 8, 20, tzinfo=UTC)


def test_greenhouse_normalizes_full_description():
    provider = GreenhouseProvider(AtsBoard(id="example", name="Example"))
    client = FakeClient(
        get_payloads=[
            {
                "jobs": [
                    {
                        "id": 1,
                        "title": "Cloud Engineer",
                        "absolute_url": "https://example/jobs/1",
                        "location": {"name": "Remote"},
                        "content": "<p>Build cloud systems</p>",
                        "updated_at": "2026-08-26T10:00:00Z",
                    }
                ]
            }
        ]
    )
    jobs = provider._fetch(client, SINCE)
    assert jobs[0].provider_job_id == "1"
    assert jobs[0].description_text == "Build cloud systems"


def test_lever_normalizes_apply_url():
    provider = LeverProvider(AtsBoard(id="example", name="Example"))
    client = FakeClient(
        get_payloads=[
            [
                {
                    "id": "1",
                    "text": "SRE",
                    "hostedUrl": "https://jobs.lever.co/example/1",
                    "applyUrl": "https://jobs.lever.co/example/1/apply",
                    "descriptionPlain": "Operate services",
                    "categories": {
                        "location": "Remote",
                        "commitment": "Full-time",
                        "workplaceType": "remote",
                    },
                    "createdAt": 1787738400000,
                }
            ]
        ]
    )
    job = provider._fetch(client, SINCE)[0]
    assert job.remote is True
    assert job.direct_apply_url.endswith("/apply")


def test_ashby_normalizes_job():
    provider = AshbyProvider(AtsBoard(id="Example", name="Example"))
    client = FakeClient(
        get_payloads=[
            {
                "jobs": [
                    {
                        "id": "1",
                        "title": "Backend Engineer",
                        "jobUrl": "https://jobs.ashbyhq.com/Example/1",
                        "applyUrl": "https://jobs.ashbyhq.com/Example/1/application",
                        "location": "Remote",
                        "descriptionHtml": "<p>Build APIs</p>",
                        "publishedAt": "2026-08-26T10:00:00Z",
                        "isRemote": True,
                    }
                ]
            }
        ]
    )
    job = provider._fetch(client, SINCE)[0]
    assert job.title == "Backend Engineer"
    assert job.remote is True


def test_smartrecruiters_fetches_detail():
    provider = SmartRecruitersProvider(AtsBoard(id="Example", name="Example"))
    list_payload = {"content": [{"id": "1", "name": "Support Engineer"}], "totalFound": 1}
    detail_payload = {
        "id": "1",
        "name": "Support Engineer",
        "postingUrl": "https://jobs.smartrecruiters.com/Example/1",
        "applyUrl": "https://jobs.smartrecruiters.com/Example/1/apply",
        "releasedDate": "2026-08-26T10:00:00Z",
        "location": {"city": "Remote", "country": "us"},
        "jobAd": {"sections": {"jobDescription": {"text": "<p>Support production APIs</p>"}}},
    }
    job = provider._fetch(FakeClient(get_payloads=[list_payload, detail_payload]), SINCE)[0]
    assert "Support production APIs" in job.description_text


def test_workday_uses_configured_cxs_endpoint():
    board = AtsBoard(
        id="example",
        name="Example",
        api_url="https://example.wd5.myworkdayjobs.com/wday/cxs/example/jobs/jobs",
        careers_url="https://example.wd5.myworkdayjobs.com/en-US/jobs",
    )
    provider = WorkdayProvider(board)
    payload = {
        "total": 1,
        "jobPostings": [
            {
                "title": "Production Support Engineer",
                "externalPath": "/job/remote/1",
                "locationsText": "United States - Remote",
                "bulletFields": ["REQ-1"],
            }
        ],
    }
    job = provider._fetch(FakeClient(post_payloads=[payload]), SINCE)[0]
    assert job.provider_job_id == "REQ-1"
    assert job.source_url == "https://example.wd5.myworkdayjobs.com/en-US/jobs/job/remote/1"


def test_workday_parses_relative_posting_age():
    now = datetime(2026, 8, 27, 18, tzinfo=UTC)
    assert _workday_posted_at("Posted Today", now) == now
    assert _workday_posted_at("Posted Yesterday", now) == datetime(2026, 8, 26, 18, tzinfo=UTC)
    assert _workday_posted_at("Posted 5 Days Ago", now) == datetime(2026, 8, 22, 18, tzinfo=UTC)


def test_workday_compiles_one_keyword_query_per_search_family():
    search = SearchSettings(
        families=[
            {
                "name": "reliability",
                "titles": ["site reliability engineer", "SRE", "cloud engineer"],
            },
            {"name": "development", "titles": ["backend engineer", "python developer"]},
        ]
    )
    assert family_keyword_queries(search) == ["site reliability sre cloud", "backend python"]


def test_workday_paginates_when_later_pages_report_zero_total():
    board = AtsBoard(
        id="example",
        name="Example",
        api_url="https://example.wd5.myworkdayjobs.com/wday/cxs/example/jobs/jobs",
        extra={"limit": 2},
    )
    pages = [
        {
            "total": 3 if page == 0 else 0,
            "jobPostings": [
                {
                    "title": "SRE",
                    "externalPath": f"/job/{job_id}",
                    "locationsText": "Remote",
                    "bulletFields": [job_id],
                }
                for job_id in job_ids
            ],
        }
        for page, job_ids in enumerate((("1", "2"), ("3",)))
    ]
    jobs = WorkdayProvider(board)._fetch(FakeClient(post_payloads=pages), SINCE)
    assert [job.provider_job_id for job in jobs] == ["1", "2", "3"]


def test_ats_filter_keeps_only_recent_remote_target_titles():
    search = SearchSettings(
        remote_only=True,
        families=[{"name": "reliability", "titles": ["site reliability engineer", "SRE"]}],
    )
    provider = GreenhouseProvider(AtsBoard(id="example", name="Example"), search=search)
    observations = [
        JobSpyProvider("indeed", CommercialProvider(), search)._normalize(
            {
                "id": job_id,
                "title": title,
                "company": "Example",
                "job_url": f"https://example/jobs/{job_id}",
                "is_remote": remote,
                "city": location,
                "date_posted": posted,
            },
            "reliability",
        )
        for job_id, title, remote, location, posted in [
            ("keep", "Senior Site Reliability Engineer", True, "Remote", "2026-08-26"),
            ("title", "Sales Engineer", True, "Remote", "2026-08-26"),
            ("remote", "Site Reliability Engineer", False, "New York", "2026-08-26"),
            ("old", "Site Reliability Engineer", True, "Remote", "2026-08-01"),
        ]
    ]
    accepted, metrics = provider._eligible([item for item in observations if item], SINCE)
    assert [item.provider_job_id for item in accepted] == ["keep"]
    assert metrics["title_rejected"] == 1
    assert metrics["remote_rejected"] == 1
    assert metrics["freshness_rejected"] == 1


def test_jobspy_adapter_normalizes_dataframe_row():
    provider = JobSpyProvider(
        "indeed",
        CommercialProvider(),
        SearchSettings(families=[{"name": "support", "titles": ["production support engineer"]}]),
    )
    job = provider._normalize(
        {
            "id": "in-1",
            "title": "Senior Production Support Engineer",
            "company": "Example",
            "job_url": "https://indeed.com/viewjob?jk=1",
            "job_url_direct": "https://example.com/jobs/1",
            "description": "<p>Operate production APIs and cloud services</p>",
            "is_remote": True,
            "city": "Remote",
            "state": "",
            "country": "US",
            "date_posted": "2026-08-26",
        },
        "support",
    )
    assert job is not None
    assert job.provider_job_id == "in-1"
    assert job.direct_apply_url == "https://example.com/jobs/1"


def test_jobspy_remote_filter_does_not_trust_description_mentions():
    provider = JobSpyProvider(
        "indeed",
        CommercialProvider(),
        SearchSettings(families=[{"name": "support", "titles": ["production support engineer"]}]),
    )
    job = provider._normalize(
        {
            "id": "in-2",
            "title": "Support Engineer",
            "company": "Example",
            "job_url": "https://indeed.com/viewjob?jk=2",
            "description": "Employees may occasionally work remotely.",
            "is_remote": False,
            "city": "New York",
            "state": "NY",
            "country": "US",
        },
        "support",
    )
    assert job is not None
    assert provider._remote_eligible(job) is False


def test_jobspy_title_gate_accepts_seniority_variants():
    titles = ["production support engineer", "site reliability engineer", "SRE"]
    assert JobSpyProvider._title_matches("Senior Production Support Engineer", titles)
    assert JobSpyProvider._title_matches("Cloud Site Reliability Engineer II", titles)
    assert JobSpyProvider._title_matches("Director of Cloud SRE", titles)
    assert not JobSpyProvider._title_matches("Inbound Sales Account Executive", titles)
    assert not JobSpyProvider._title_matches("SREcruiting Coordinator", titles)


def test_indeed_uses_plain_individual_title_queries():
    provider = JobSpyProvider(
        "indeed",
        CommercialProvider(),
        SearchSettings(families=[{"name": "reliability", "titles": ["site reliability engineer"]}]),
    )
    assert provider._provider_queries(["site reliability engineer", "SRE"]) == [
        "site reliability engineer",
        "SRE",
    ]


def test_indeed_freshness_uses_calendar_date():
    provider = JobSpyProvider(
        "indeed",
        CommercialProvider(),
        SearchSettings(families=[{"name": "reliability", "titles": ["SRE"]}]),
    )
    job = provider._normalize(
        {
            "id": "same-day",
            "title": "SRE",
            "company": "Example",
            "job_url": "https://example/same-day",
            "date_posted": "2026-08-27",
        },
        "reliability",
    )
    assert job is not None
    assert provider._recent_enough(job, datetime(2026, 8, 27, 18, tzinfo=UTC))


def test_indeed_fetch_reports_filter_waterfall(monkeypatch):
    captured = []

    class Frame:
        def to_dict(self, orient):
            assert orient == "records"
            base = {
                "company": "Example",
                "description": "A complete description",
                "is_remote": True,
                "location": "Remote, US",
            }
            return [
                {
                    **base,
                    "id": "1",
                    "title": "Senior Site Reliability Engineer",
                    "job_url": "https://example/1",
                    "date_posted": "2026-08-26",
                },
                {
                    **base,
                    "id": "1",
                    "title": "Senior Site Reliability Engineer",
                    "job_url": "https://example/1",
                    "date_posted": "2026-08-26",
                },
                {
                    **base,
                    "id": "2",
                    "title": "Old Site Reliability Engineer",
                    "job_url": "https://example/2",
                    "date_posted": "2026-08-19",
                },
                {
                    **base,
                    "id": "3",
                    "title": "Sales Engineer",
                    "job_url": "https://example/3",
                    "date_posted": "2026-08-26",
                },
                {
                    **base,
                    "id": "4",
                    "title": "Platform Site Reliability Engineer",
                    "job_url": "https://example/4",
                    "date_posted": "2026-08-26",
                    "is_remote": False,
                    "location": "New York, NY",
                },
            ]

    def fake_scrape_jobs(**kwargs):
        captured.append(kwargs)
        return Frame()

    monkeypatch.setattr("jobspy.scrape_jobs", fake_scrape_jobs)
    provider = JobSpyProvider(
        "indeed",
        CommercialProvider(
            results_wanted=100,
            family_results_wanted={"reliability": 200},
        ),
        SearchSettings(families=[{"name": "reliability", "titles": ["site reliability engineer"]}]),
    )
    result = provider.fetch(SINCE)

    assert captured[0]["search_term"] == "site reliability engineer"
    assert captured[0]["results_wanted"] == 200
    assert captured[0]["is_remote"] is True
    assert "hours_old" not in captured[0]
    assert len(result.observations) == 1
    assert result.metrics == {
        "queries": 1,
        "raw_results": 5,
        "invalid": 0,
        "title_rejected": 1,
        "remote_rejected": 1,
        "freshness_rejected": 1,
        "accepted_before_dedupe": 2,
        "duplicates": 1,
        "accepted": 1,
        "saturated_queries": 0,
        "family.reliability.raw_results": 5,
        "family.reliability.accepted_before_dedupe": 2,
        "family.reliability.query.site reliability engineer.raw_results": 5,
        "family.reliability.query.site reliability engineer.accepted_before_dedupe": 2,
    }


def test_jobspy_partial_query_failure_does_not_advance_as_success(monkeypatch):
    calls = 0

    class EmptyFrame:
        def to_dict(self, orient):
            assert orient == "records"
            return []

    def partly_failing_scrape(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("blocked")
        return EmptyFrame()

    monkeypatch.setattr("jobspy.scrape_jobs", partly_failing_scrape)
    provider = JobSpyProvider(
        "indeed",
        CommercialProvider(),
        SearchSettings(families=[{"name": "reliability", "titles": ["SRE", "cloud engineer"]}]),
    )
    result = provider.fetch(SINCE)

    assert result.success is False
    assert result.suspicious_empty is False
    assert "blocked" in (result.error or "")
