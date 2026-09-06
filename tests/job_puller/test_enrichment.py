import json

import httpx

from job_puller.enrichment import enrich_observation
from job_puller.models import JobObservation
from job_puller.work_modes import WorkMode


def test_json_ld_enrichment(monkeypatch):
    payload = {
        "@context": "https://schema.org",
        "@type": "JobPosting",
        "title": "Backend Engineer",
        "description": "<p>" + "Build reliable Python APIs and cloud services. " * 8 + "</p>",
        "url": "https://example.com/apply/1",
    }
    html = f'<script type="application/ld+json">{json.dumps(payload)}</script>'

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def get(self, url, headers):
            return httpx.Response(200, text=html, request=httpx.Request("GET", url))

    monkeypatch.setattr("job_puller.enrichment.httpx.Client", FakeClient)
    item = JobObservation(
        "linkedin", "1", "Backend Engineer", "Example", "https://example.com/job/1"
    )
    enriched = enrich_observation(
        item,
        address_lookup=lambda _host, _port: ["93.184.216.34"],
    )
    assert len(enriched.description_text) >= 200
    assert enriched.direct_apply_url == "https://example.com/apply/1"


def test_direct_apply_redirect_enriches_from_exact_ats_posting():
    ats_payload = {
        "@context": "https://schema.org",
        "@type": "JobPosting",
        "title": "AI Engineer",
        "description": (
            "<p>This is an on-site position working from our Phoenix office. "
            + "Build and deliver AI-enabled solutions for business teams. " * 4
            + "</p>"
        ),
        "employmentType": "FULL_TIME",
        "jobLocationType": "ON_SITE",
        "jobLocation": {
            "@type": "Place",
            "address": {
                "addressLocality": "Phoenix",
                "addressRegion": "AZ",
                "addressCountry": "US",
            },
        },
    }
    ats_html = f'<script type="application/ld+json">{json.dumps(ats_payload)}</script>'

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "apply.example.com":
            return httpx.Response(
                302,
                headers={"location": "https://jobs.ashbyhq.com/Example/job-123"},
                request=request,
            )
        return httpx.Response(200, text=ats_html, request=request)

    observation = JobObservation(
        "linkedin",
        "123",
        "AI Engineer",
        "Example",
        "https://www.linkedin.com/jobs/view/123",
        direct_apply_url="https://apply.example.com/link/123",
        location="Phoenix, AZ",
        description_text="LinkedIn description without a stated work arrangement. " * 8,
    )
    with httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False) as client:
        enriched = enrich_observation(
            observation,
            client=client,
            address_lookup=lambda _host, _port: ["93.184.216.34"],
        )

    assert enriched.direct_apply_url == "https://jobs.ashbyhq.com/Example/job-123"
    assert enriched.work_modes == {WorkMode.ONSITE}
    assert enriched.employment_type == "FULL_TIME"
    assert enriched.raw_payload["direct_apply_resolution"]["status"] == "resolved"
    assert enriched.raw_payload["ats_job_posting"]["location"] == "Phoenix, AZ, US"


def test_direct_apply_redirect_rejects_private_destination():
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        return httpx.Response(
            302, headers={"location": "http://127.0.0.1/private"}, request=request
        )

    observation = JobObservation(
        "linkedin",
        "123",
        "AI Engineer",
        "Example",
        "https://www.linkedin.com/jobs/view/123",
        direct_apply_url="https://apply.example.com/link/123",
        description_text="LinkedIn description without a stated work arrangement. " * 8,
    )
    with httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False) as client:
        enriched = enrich_observation(
            observation,
            client=client,
            address_lookup=lambda _host, _port: ["93.184.216.34"],
        )

    assert requests == ["https://apply.example.com/link/123"]
    assert enriched.direct_apply_url == "https://apply.example.com/link/123"
    assert enriched.raw_payload["direct_apply_resolution"]["status"] == "failed"
    assert "non-public" in enriched.raw_payload["direct_apply_resolution"]["error"]


def test_complete_direct_ats_observation_does_not_refetch_its_own_page():
    class NoRequestClient:
        def get(self, *_args, **_kwargs):
            raise AssertionError("complete direct ATS observation was refetched")

    observation = JobObservation(
        "greenhouse",
        "123",
        "AI Engineer",
        "Example",
        "https://job-boards.greenhouse.io/example/jobs/123",
        direct_apply_url="https://job-boards.greenhouse.io/example/jobs/123",
        description_text="Complete first-party ATS description. " * 10,
    )

    assert enrich_observation(observation, client=NoRequestClient()) is observation


def test_structured_workday_detail_never_falls_back_to_page_json_ld():
    class NoRequestClient:
        def get(self, *_args, **_kwargs):
            raise AssertionError("authoritative Workday detail was refetched")

    observation = JobObservation(
        "workday",
        "REQ-1",
        "AI Engineer",
        "Example",
        "https://example.wd5.myworkdayjobs.com/job/REQ-1",
        description_text="Short but authoritative description.",
        parser_version="workday-cxs-v3",
    )

    assert enrich_observation(observation, client=NoRequestClient()) is observation
