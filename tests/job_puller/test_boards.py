from pathlib import Path

import httpx

from job_puller.boards import (
    discover_boards,
    merge_registries,
    recognize_board,
    write_board_registry,
)
from job_puller.config import AtsBoard, BoardRegistry, BoardRegistryProviders, load_board_registry


def test_recognizes_supported_board_urls():
    cases = {
        "https://acme.applytojob.com/apply/abc/cloud-engineer": ("jazzhr", "acme"),
        "https://ats.rippling.com/acme/jobs/abc": ("rippling", "acme"),
        "https://job-boards.greenhouse.io/acme/jobs/1": ("greenhouse", "acme"),
        "https://jobs.lever.co/acme/1": ("lever", "acme"),
        "https://jobs.ashbyhq.com/Acme/1": ("ashby", "Acme"),
        "https://jobs.smartrecruiters.com/Acme/1": ("smartrecruiters", "Acme"),
        "https://acme.wd5.myworkdayjobs.com/en-US/Careers/job/Remote/1": (
            "workday",
            "acme-careers",
        ),
    }
    for url, expected in cases.items():
        provider, board = recognize_board(url, "Acme")
        assert (provider, board.id) == expected
        assert board.enabled is False
    workday = recognize_board(next(url for url in cases if "workday" in url), "Acme")[1]
    assert workday.api_url == "https://acme.wd5.myworkdayjobs.com/wday/cxs/acme/Careers/jobs"
    assert workday.careers_url == "https://acme.wd5.myworkdayjobs.com/en-US/Careers"


def test_discovery_follows_only_known_greenhouse_redirects():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "grnh.se":
            return httpx.Response(
                301,
                headers={"location": "https://boards.greenhouse.io/acme/jobs/42"},
                request=request,
            )
        return httpx.Response(200, request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)
    registry, report = discover_boards(
        [{"url": "https://grnh.se/example", "company": "Acme", "observations": 2}],
        client=client,
    )
    assert report.recognized_links == 2
    assert report.verified_redirects == [
        ("https://grnh.se/example", "https://boards.greenhouse.io/acme/jobs/42")
    ]
    assert registry.providers.greenhouse[0].id == "acme"
    assert registry.providers.greenhouse[0].name == "Acme"


def test_discovery_accepts_european_greenhouse_host():
    recognized = recognize_board("https://job-boards.eu.greenhouse.io/acme/jobs/42", "Acme")
    assert recognized is not None
    assert recognized[0] == "greenhouse"
    assert recognized[1].id == "acme"


def test_discovery_rejects_untrusted_greenhouse_redirect_host():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            301,
            headers={"location": "http://127.0.0.1/private"},
            request=request,
        )

    client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)
    registry, report = discover_boards(
        [{"url": "https://grnh.se/example", "company": "Acme", "observations": 1}],
        client=client,
    )
    assert not registry.providers.greenhouse
    assert len(report.redirect_failures) == 1


def test_discovery_does_not_request_custom_greenhouse_careers_host():
    requested_hosts = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_hosts.append(request.url.host)
        return httpx.Response(
            301,
            headers={"location": "https://careers.example.com/job/42?gh_jid=42"},
            request=request,
        )

    client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)
    registry, report = discover_boards(
        [{"url": "https://grnh.se/example", "company": "Acme", "observations": 1}],
        client=client,
    )
    assert not registry.providers.greenhouse
    assert not report.redirect_failures
    assert report.verified_redirects == [
        ("https://grnh.se/example", "https://careers.example.com/job/42?gh_jid=42")
    ]
    assert requested_hosts == ["grnh.se"]


def test_registry_merge_preserves_reviewed_settings(tmp_path: Path):
    current = BoardRegistry(
        providers=BoardRegistryProviders(
            greenhouse=[AtsBoard(id="acme", name="Acme", enabled=True, tags=["faang-plus"])]
        )
    )
    discovered = BoardRegistry(
        providers=BoardRegistryProviders(
            greenhouse=[
                AtsBoard(id="acme", name="Changed", enabled=False),
                AtsBoard(id="new", name="New", enabled=False),
            ]
        )
    )
    merged = merge_registries(current, discovered)
    path = tmp_path / "boards.yml"
    write_board_registry(path, merged)
    loaded = load_board_registry(path)
    assert [board.id for board in loaded.providers.greenhouse] == ["acme", "new"]
    assert loaded.providers.greenhouse[0].enabled is True
    assert loaded.providers.greenhouse[0].tags == ["faang-plus"]
