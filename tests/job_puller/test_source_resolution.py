import json
from datetime import UTC, datetime, timedelta

import httpx

from job_puller.models import JobObservation
from job_puller.source_resolution import (
    AtsCatalog,
    CatalogError,
    LinkedInTarget,
    company_slug_candidates,
    match_posting,
)
from job_puller.work_modes import WorkMode, explicit_arrangement


def posting(job_id: str, description: str, mode: WorkMode) -> JobObservation:
    return JobObservation(
        provider="ashby",
        provider_board_id="example",
        provider_job_id=job_id,
        title="AI Engineer",
        company="Example, Inc.",
        source_url=f"https://jobs.ashbyhq.com/example/{job_id}",
        location="Phoenix, AZ",
        description_text=description,
        work_arrangement=explicit_arrangement(
            [mode], source="ashby_structured_field", rule="workplace_type"
        ),
    )


def target(description: str) -> LinkedInTarget:
    return LinkedInTarget(
        job_id="job-1",
        observation_id="linkedin-1",
        title="AI Engineer",
        company="Example, Inc.",
        location="Phoenix, AZ",
        description=description,
        posted_at=datetime(2026, 9, 1, tzinfo=UTC),
    )


def test_company_slug_candidates_are_bounded_and_strip_legal_suffixes():
    assert company_slug_candidates("Obsidian Security, Inc.") == (
        "obsidian-security",
        "obsidiansecurity",
    )


def test_catalog_uses_exact_or_compact_company_board_and_adds_probes():
    catalog = AtsCatalog(
        {
            "greenhouse": ("obsidiansecurity",),
            "ashby": (),
            "lever": (),
        }
    )

    boards = catalog.boards_for("Obsidian Security", include_probes=True)

    assert boards[0].provider == "greenhouse"
    assert boards[0].board_id == "obsidiansecurity"
    assert boards[0].origin == "catalog"
    assert any(board.origin == "company-slug-probe" for board in boards)


def test_catalog_rejects_unsafe_identifiers():
    try:
        from job_puller.source_resolution import _validate_catalog

        _validate_catalog("greenhouse", ["../../internal"])
    except CatalogError:
        pass
    else:
        raise AssertionError("unsafe catalog identifier was accepted")


def test_match_requires_exact_title_strong_description_overlap_and_known_mode():
    description = " ".join(f"requirement-{index}" for index in range(120))
    matched = match_posting(target(description), [posting("ats-1", description, WorkMode.ONSITE)])

    assert matched is not None
    assert matched.observation.work_modes == frozenset({WorkMode.ONSITE})
    assert matched.confidence >= 0.92

    wrong_title = posting("ats-2", description, WorkMode.REMOTE)
    wrong_title.title = "Data Engineer"
    unknown = posting("ats-3", description, WorkMode.UNKNOWN)
    unrelated = posting(
        "ats-4",
        " ".join(f"different-{index}" for index in range(120)),
        WorkMode.REMOTE,
    )
    assert match_posting(target(description), [wrong_title, unknown, unrelated]) is None


def test_catalog_loader_uses_validated_cached_copy_when_refresh_fails(tmp_path):
    for provider in ("greenhouse", "lever", "ashby"):
        value = ["example"]
        (tmp_path / f"{provider}.json").write_text(json.dumps(value))

    def fail(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline", request=_request)

    with httpx.Client(transport=httpx.MockTransport(fail)) as client:
        catalog = AtsCatalog.load(
            tmp_path,
            max_age=timedelta(0),
            client=client,
        )

    assert catalog.entries["greenhouse"] == ("example",)
