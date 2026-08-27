from datetime import UTC, datetime

import httpx

from job_puller.config import AtsBoard, CommercialProvider, SearchSettings
from job_puller.providers.ats import (
    AshbyProvider,
    GreenhouseProvider,
    LeverProvider,
    SmartRecruitersProvider,
    WorkdayProvider,
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
    assert job.source_url == "https://example.wd5.myworkdayjobs.com/job/remote/1"


def test_jobspy_adapter_normalizes_dataframe_row():
    provider = JobSpyProvider(
        "indeed",
        CommercialProvider(),
        SearchSettings(families=[{"name": "support", "terms": ["production support engineer"]}]),
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
