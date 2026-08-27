import json

import httpx

from job_puller.enrichment import enrich_observation
from job_puller.models import JobObservation


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
    item = JobObservation("linkedin", "1", "Backend Engineer", "Example", "https://example.com/job/1")
    enriched = enrich_observation(item)
    assert len(enriched.description_text) >= 200
    assert enriched.direct_apply_url == "https://example.com/apply/1"
