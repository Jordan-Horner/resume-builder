import json
from datetime import UTC, datetime, timedelta

import httpx

import job_puller.source_resolution as resolution_module
from job_puller.database import InventoryDatabase
from job_puller.models import JobObservation, ProviderResult
from job_puller.source_resolution import (
    AtsCatalog,
    CatalogError,
    LinkedInTarget,
    company_slug_candidates,
    match_posting,
    resolve_linkedin_sources,
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


def test_catalog_uses_exact_or_compact_company_board_without_extra_probes():
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
    assert all(board.origin == "catalog" for board in boards)


def test_catalog_adds_bounded_probes_only_when_company_is_missing():
    catalog = AtsCatalog({"greenhouse": (), "ashby": (), "lever": ()})

    boards = catalog.boards_for("Missing Example, Inc.", include_probes=True)

    assert len(boards) == 6
    assert all(board.origin == "company-slug-probe" for board in boards)


def test_catalog_rejects_unsafe_identifiers():
    try:
        from job_puller.source_resolution import _validate_catalog

        _validate_catalog("greenhouse", ["../../internal"])
    except CatalogError:
        pass
    else:
        raise AssertionError("unsafe catalog identifier was accepted")


def test_catalog_builds_bounded_workday_boards_from_exact_tenant_match():
    catalog = AtsCatalog(
        {
            "greenhouse": (),
            "ashby": (),
            "lever": (),
            "workday": (
                "generalmotors|wd5|Careers",
                "generalmotors|wd5|GM_Careers",
                "unrelated|wd1|jobs",
            ),
        }
    )

    boards = catalog.boards_for("General Motors")

    assert [board.provider for board in boards] == ["workday", "workday"]
    assert boards[0].api_url == (
        "https://generalmotors.wd5.myworkdayjobs.com/wday/cxs/generalmotors/Careers/jobs"
    )
    assert boards[0].careers_url == ("https://generalmotors.wd5.myworkdayjobs.com/en-US/Careers")


def test_catalog_prefers_public_workday_site_within_three_request_cap():
    catalog = AtsCatalog(
        {
            "workday": (
                "boeing|wd1|aaeoy",
                "boeing|wd1|alpfa",
                "boeing|wd1|clear",
                "boeing|wd1|external_careers",
                "boeing|wd1|external_subsidiary",
            )
        }
    )

    boards = catalog.boards_for("Boeing")

    assert len(boards) == 3
    assert boards[0].board_id == "boeing-external_careers"
    assert all("subsidiary" not in board.board_id for board in boards)


def test_catalog_rejects_malformed_workday_entries():
    from job_puller.source_resolution import _validate_catalog

    for value in ("tenant|wd5", "tenant|wd5|jobs|extra", "tenant|wd5|../jobs"):
        try:
            _validate_catalog("workday", [value])
        except CatalogError:
            continue
        raise AssertionError(f"unsafe Workday catalog identifier was accepted: {value}")


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
    for provider in ("greenhouse", "lever", "ashby", "workday"):
        value = ["example|wd5|jobs"] if provider == "workday" else ["example"]
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


def test_resolver_caps_company_slug_fallback_across_the_whole_run(monkeypatch):
    description = " ".join(f"requirement-{index}" for index in range(120))

    class Database:
        def unresolved_linkedin_targets(self, *, seen_since=None):
            assert seen_since is not None
            return [
                {
                    "job_id": f"job-{index}",
                    "observation_id": f"linkedin-{index}",
                    "title": "AI Engineer",
                    "company": company,
                    "location": "Phoenix, AZ",
                    "description": description,
                    "posted_at": None,
                }
                for index, company in enumerate(("Alpha Inc.", "Beta Inc."), start=1)
            ]

        def stored_direct_ats_observations(self, _companies):
            return []

    class FailedProvider:
        def fetch(self, _cutoff):
            return type("Result", (), {"success": False})()

    monkeypatch.setattr(
        resolution_module, "_provider", lambda _candidate, _timeout: FailedProvider()
    )
    report = resolve_linkedin_sources(
        Database(),
        AtsCatalog({"greenhouse": (), "ashby": (), "lever": ()}),
        include_probes=True,
        max_probe_companies=1,
        seen_since=datetime.now(UTC),
    )

    assert report.companies == 2
    assert report.probe_companies == 1
    assert report.boards_considered == 3
    assert report.board_requests_submitted == 3


def test_resolver_reuses_stored_ats_observation_before_network(tmp_path):
    description = " ".join(f"requirement-{index}" for index in range(120))
    now = datetime.now(UTC)
    linkedin = JobObservation(
        provider="linkedin",
        provider_job_id="linkedin-1",
        title="AI Engineer",
        company="Example, Inc.",
        source_url="https://linkedin.com/jobs/view/linkedin-1",
        location="Phoenix, AZ",
        description_text=description,
        work_arrangement=explicit_arrangement(
            [WorkMode.UNKNOWN], source="linkedin", rule="not_listed"
        ),
    )
    ats = posting("ats-1", f"{description} additional detail", WorkMode.ONSITE)
    database = InventoryDatabase(tmp_path / "inventory.db")
    database.migrate()
    for source_key, observation_item in (("linkedin:test", linkedin), ("ashby:example", ats)):
        database.record_result(
            ProviderResult(
                source_key=source_key,
                provider=observation_item.provider,
                observations=[observation_item],
                started_at=now - timedelta(seconds=1),
                completed_at=now,
                success=True,
            )
        )

    report = resolve_linkedin_sources(
        database,
        AtsCatalog({"greenhouse": (), "ashby": (), "lever": ()}),
        apply=True,
    )

    assert report.local_candidates_scanned == 1
    assert report.local_matches == 1
    assert report.network_matches == 0
    assert report.board_requests_submitted == 0
    assert report.applied == 1
    assert database.unresolved_linkedin_targets() == []


def test_resolver_deduplicates_boards_and_enforces_request_budget(monkeypatch):
    description = " ".join(f"requirement-{index}" for index in range(120))

    class Database:
        def unresolved_linkedin_targets(self, *, seen_since=None):
            return [
                {
                    "job_id": f"job-{index}",
                    "observation_id": f"linkedin-{index}",
                    "title": "AI Engineer",
                    "company": company,
                    "location": "Phoenix, AZ",
                    "description": description,
                    "posted_at": None,
                }
                for index, company in enumerate(("Acme", "Acme Inc.", "Beta"), start=1)
            ]

        def stored_direct_ats_observations(self, _companies):
            return []

    class FailedProvider:
        def fetch(self, _cutoff):
            return type("Result", (), {"success": False})()

    monkeypatch.setattr(
        resolution_module, "_provider", lambda _candidate, _timeout: FailedProvider()
    )
    report = resolve_linkedin_sources(
        Database(),
        AtsCatalog({"greenhouse": ("acme", "beta"), "ashby": (), "lever": ()}),
        max_board_requests=1,
    )

    assert report.boards_considered == 2
    assert report.board_requests_submitted == 1
    assert report.board_requests_deferred == 1


def test_resolver_can_limit_network_queries_to_workday(monkeypatch):
    requested = []

    class Database:
        def stored_direct_ats_observations(self, _companies):
            return []

    class FailedProvider:
        def fetch(self, _cutoff):
            return type("Result", (), {"success": False})()

    def provider(candidate, _timeout):
        requested.append(candidate.provider)
        return FailedProvider()

    monkeypatch.setattr(resolution_module, "_provider", provider)
    resolve_linkedin_sources(
        Database(),
        AtsCatalog(
            {
                "greenhouse": ("example",),
                "workday": ("example|wd5|jobs",),
            }
        ),
        targets=[target(" ".join(f"requirement-{index}" for index in range(120)))],
        providers={"workday"},
    )

    assert requested == ["workday"]


def test_resolver_rejects_partial_board_results_before_unique_matching(monkeypatch):
    description = " ".join(f"requirement-{index}" for index in range(120))

    class Database:
        def stored_direct_ats_observations(self, _companies):
            return []

    class PartialProvider:
        def fetch(self, _cutoff):
            now = datetime.now(UTC)
            return ProviderResult(
                "ashby:example",
                "ashby",
                [posting("ats-1", description, WorkMode.ONSITE)],
                now,
                now,
                False,
                "another same-title detail failed",
            )

    monkeypatch.setattr(
        resolution_module, "_provider", lambda _candidate, _timeout: PartialProvider()
    )
    report = resolve_linkedin_sources(
        Database(),
        AtsCatalog({"ashby": ("example",)}),
        targets=[target(description)],
    )

    assert report.boards_failed == 1
    assert report.network_matches == 0
