from datetime import UTC, datetime, timedelta

from job_puller.database import InventoryDatabase
from job_puller.models import JobObservation, ProviderResult
from job_puller.source_resolution import linkedin_targets
from job_puller.work_modes import WorkMode, explicit_arrangement
from resume_builder import bright_data


def test_bright_data_enriches_exact_linkedin_job(monkeypatch, tmp_path):
    database = InventoryDatabase(tmp_path / "inventory.db")
    database.migrate()
    observation = JobObservation(
        provider="linkedin",
        provider_job_id="4462886742",
        title="Technical Support Engineer",
        company="Example",
        source_url="https://www.linkedin.com/jobs/view/4462886742",
        location="Austin, TX",
        description_text="Support customer systems. " * 20,
        work_arrangement=explicit_arrangement(
            [WorkMode.UNKNOWN], source="linkedin", rule="not_listed"
        ),
    )
    now = datetime.now(UTC)
    database.record_result(
        ProviderResult(
            "linkedin:test",
            "linkedin",
            [observation],
            now - timedelta(seconds=1),
            now,
            True,
        )
    )

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "url": "https://www.linkedin.com/jobs/view/4462886742",
                "job_posting_id": "4462886742",
                "job_title": "Technical Support Engineer",
                "company_name": "Example",
                "job_location": "San Francisco, CA",
                "job_summary": "This role is hybrid. Support customer systems from our office.",
                "job_employment_type": "Full-time",
                "apply_link": "https://example.com/jobs/REQ-1",
                "base_salary": {
                    "min_amount": 100000,
                    "max_amount": 125000,
                    "currency": "$",
                    "payment_period": "yr",
                },
            }

    calls = []

    class Client:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def post(self, url, **kwargs):
            calls.append(kwargs["json"])
            assert url == bright_data.BRIGHT_DATA_ENDPOINT
            assert kwargs["headers"] == {"Authorization": "Bearer fixture-token"}
            assert kwargs["json"]["input"] == [
                {"url": "https://www.linkedin.com/jobs/view/4462886742"}
            ]
            return Response()

    monkeypatch.setattr(bright_data.httpx, "Client", lambda **_kwargs: Client())

    targets = linkedin_targets(database)
    report = bright_data.enrich_linkedin_targets(
        database,
        targets,
        api_token="fixture-token",
        limit=10,
    )

    assert report == {
        "status": "complete",
        "eligible": 1,
        "requested": 1,
        "received": 1,
        "applied": 1,
        "improved": 1,
        "no_change": 0,
        "not_found": 0,
        "failed": 0,
        "skipped_cached": 0,
        "deferred_same_company": 0,
        "salary_added": 1,
        "location_added": 0,
        "work_mode_added": 1,
        "apply_links_added": 1,
    }
    job = database.active_inventory()[0]
    assert job["location"] == "San Francisco, CA"
    assert job["work_modes"] == ["hybrid"]
    assert job["salary_min"] == 100000
    assert job["salary_max"] == 125000
    assert job["url"] == "https://example.com/jobs/REQ-1"
    cached_report = bright_data.enrich_linkedin_targets(
        database,
        targets,
        api_token="fixture-token",
        limit=10,
    )
    assert cached_report["requested"] == 0
    assert cached_report["skipped_cached"] == 1
    assert len(calls) == 1


def test_bright_data_checks_only_one_job_per_company(monkeypatch):
    from job_puller.source_resolution import LinkedInTarget

    targets = [
        LinkedInTarget(
            job_id=f"job-{number}",
            observation_id=f"observation-{number}",
            title=f"Engineer {number}",
            company="Example",
            location="",
            description="",
            posted_at=None,
            source_url=f"https://www.linkedin.com/jobs/view/{number}234567890",
        )
        for number in (1, 2)
    ]
    calls = []

    class Database:
        def get_provider_detail(self, *_args):
            return None

        def put_provider_detail(self, *_args):
            return None

        def apply_linkedin_enrichment(self, *_args):
            return frozenset()

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"job_posting_id": "1234567890", "job_title": "Engineer 1"}

    class Client:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def post(self, *_args, **_kwargs):
            calls.append(1)
            return Response()

    monkeypatch.setattr(bright_data.httpx, "Client", lambda **_kwargs: Client())

    report = bright_data.enrich_linkedin_targets(
        Database(), targets, api_token="fixture-token", limit=25
    )

    assert report["requested"] == 1
    assert report["deferred_same_company"] == 1
    assert len(calls) == 1
