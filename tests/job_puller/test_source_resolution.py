import json
from datetime import UTC, datetime, timedelta

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
    assert company_slug_candidates("Core Specialty Insurance Holdings, Inc.") == (
        "core-specialty-insurance",
        "corespecialtyinsurance",
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


def test_catalog_prefers_private_registered_board_for_exact_company():
    from types import SimpleNamespace

    board = SimpleNamespace(
        id="riot-platforms-careers",
        name="Riot Platforms, Inc.",
        api_url=None,
        careers_url="https://ats.rippling.com/riot-platforms-careers/jobs",
    )
    providers = SimpleNamespace(
        rippling=SimpleNamespace(boards=[board]),
        greenhouse=SimpleNamespace(boards=[]),
        ashby=SimpleNamespace(boards=[]),
        lever=SimpleNamespace(boards=[]),
        workday=SimpleNamespace(boards=[]),
    )
    catalog = AtsCatalog({}).add_configured_boards(SimpleNamespace(providers=providers))

    candidates = catalog.boards_for("Riot Platforms, Inc.")

    assert [(item.provider, item.board_id, item.origin) for item in candidates] == [
        ("rippling", "riot-platforms-careers", "private-registry")
    ]


def test_catalog_adds_bounded_probes_only_when_company_is_missing():
    catalog = AtsCatalog({"greenhouse": (), "ashby": (), "lever": ()})

    boards = catalog.boards_for("Missing Example, Inc.", include_probes=True)

    assert len(boards) == 6
    assert all(board.origin == "company-slug-probe" for board in boards)


def test_catalog_allows_delimited_prefix_for_short_company_name():
    catalog = AtsCatalog(
        {
            "greenhouse": (),
            "ashby": ("luma-ai", "lumana", "lumilens"),
            "lever": (),
        }
    )

    boards = catalog.boards_for("Luma")

    assert [(board.provider, board.board_id) for board in boards] == [("ashby", "luma-ai")]


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


def test_catalog_keeps_distinct_workday_datacenters_for_same_site():
    catalog = AtsCatalog(
        {
            "workday": (
                "salesforce|wd1|external_career_site",
                "salesforce|wd12|external_career_site",
            )
        }
    )

    boards = catalog.boards_for("Salesforce")

    assert [board.api_url for board in boards] == [
        "https://salesforce.wd1.myworkdayjobs.com/wday/cxs/salesforce/external_career_site/jobs",
        "https://salesforce.wd12.myworkdayjobs.com/wday/cxs/salesforce/external_career_site/jobs",
    ]


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


def test_catalog_loader_uses_private_snapshots_and_defaults_missing_providers(tmp_path):
    for provider in ("greenhouse", "lever", "ashby", "workday"):
        value = ["example|wd5|jobs"] if provider == "workday" else ["example"]
        (tmp_path / f"{provider}.json").write_text(json.dumps(value))

    catalog = AtsCatalog.load(tmp_path)

    assert catalog.entries["greenhouse"] == ("example",)

    (tmp_path / "lever.json").unlink()
    assert AtsCatalog.load(tmp_path).entries["lever"] == ()


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


def test_ashby_fetch_retries_compact_catalog_slug(monkeypatch):
    requested = []
    now = datetime.now(UTC)

    class Provider:
        def __init__(self, candidate):
            self.candidate = candidate

        def fetch(self, _cutoff):
            requested.append(self.candidate.board_id)
            success = self.candidate.board_id == "lumaai"
            return ProviderResult(
                f"ashby:{self.candidate.board_id}",
                "ashby",
                [],
                now,
                now,
                success,
                None if success else "HTTPStatusError: 404 Not Found",
            )

    monkeypatch.setattr(
        resolution_module,
        "_provider",
        lambda candidate, _timeout: Provider(candidate),
    )

    result = resolution_module._fetch_candidate(
        resolution_module.BoardCandidate("ashby", "luma-ai", "Luma"),
        [target(" ".join(f"requirement-{index}" for index in range(120)))],
        30,
    )

    assert result.success is True
    assert result.source_key == "ashby:lumaai"
    assert requested == ["luma-ai", "lumaai"]


def test_ashby_fetch_does_not_retry_compact_slug_after_network_failure(monkeypatch):
    requested = []
    now = datetime.now(UTC)

    class Provider:
        def __init__(self, candidate):
            self.candidate = candidate

        def fetch(self, _cutoff):
            requested.append(self.candidate.board_id)
            return ProviderResult(
                f"ashby:{self.candidate.board_id}",
                "ashby",
                [],
                now,
                now,
                False,
                "ConnectTimeout: timed out",
            )

    monkeypatch.setattr(
        resolution_module,
        "_provider",
        lambda candidate, _timeout: Provider(candidate),
    )

    result = resolution_module._fetch_candidate(
        resolution_module.BoardCandidate("ashby", "luma-ai", "Luma"),
        [target(" ".join(f"requirement-{index}" for index in range(120)))],
        30,
    )

    assert result.success is False
    assert requested == ["luma-ai"]


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


def test_resolver_prefers_board_from_captured_apply_url(monkeypatch):
    requested = []

    class Database:
        def stored_direct_ats_observations(self, _companies):
            return []

    def fetch(candidate, _targets, _timeout):
        requested.append((candidate.provider, candidate.board_id, candidate.origin))
        now = datetime.now(UTC)
        return ProviderResult(
            f"{candidate.provider}:{candidate.board_id}",
            candidate.provider,
            [],
            now,
            now,
            True,
        )

    monkeypatch.setattr(resolution_module, "_fetch_candidate", fetch)
    captured_target = resolution_module.replace(
        target(" ".join(f"requirement-{index}" for index in range(120))),
        company="Riot Platforms, Inc.",
        direct_apply_url=(
            "https://ats.rippling.com/riot-platforms-careers/jobs/"
            "19611d4b-3a3f-452a-9ea4-d2cd914f7716?src=LinkedIn"
        ),
    )

    resolve_linkedin_sources(Database(), AtsCatalog({}), targets=[captured_target])

    assert requested == [("rippling", "riot-platforms-careers", "captured-apply-url")]


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
