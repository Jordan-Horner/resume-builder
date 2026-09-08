from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

import job_puller.community_catalog as community_catalog
from job_puller.community_catalog import _board, audit_community_catalog
from job_puller.config import InventoryConfig, SearchFamily, SearchSettings
from job_puller.models import JobObservation, ProviderResult


def _config() -> InventoryConfig:
    search = SearchSettings(
        families=[SearchFamily(name="reliability", titles=["site reliability engineer"])]
    )
    return InventoryConfig.model_construct(search=search)


def test_catalog_audit_is_capped_read_only_and_resumes_from_cursor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    revision = "a" * 40

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.github.com":
            return httpx.Response(200, json={"sha": revision}, request=request)
        return httpx.Response(200, json=["alpha", "beta", "gamma"], request=request)

    class FakeProvider:
        def __init__(self, board, timeout, search):
            self.board = board

        def fetch(self, since):
            now = datetime.now(UTC)
            observation = JobObservation(
                provider="greenhouse",
                provider_job_id=f"{self.board.id}-1",
                title="Site Reliability Engineer",
                company=self.board.name,
                source_url=f"https://example.test/{self.board.id}",
            )
            return ProviderResult(
                f"greenhouse:{self.board.id}",
                "greenhouse",
                [observation],
                now,
                now,
                True,
                metrics={
                    "raw_results": 2,
                    "title_rejected": 1,
                    "accepted": 1,
                    "rejected_title.reliability analyst": 1,
                },
            )

    monkeypatch.setitem(community_catalog.ATS_PROVIDER_CLASSES, "greenhouse", FakeProvider)
    cursor = tmp_path / "cursor.json"
    output = tmp_path / "report.json"
    client = httpx.Client(transport=httpx.MockTransport(handler))

    first = audit_community_catalog(
        _config(),
        providers=["greenhouse"],
        limit_per_provider=2,
        cursor_path=cursor,
        output_path=output,
        client=client,
    )
    assert [board["identifier"] for board in first["providers"][0]["boards"]] == [
        "alpha",
        "beta",
    ]
    assert first["totals"]["promotion_ready"] == 2
    assert first["providers"][0]["boards"][0]["possible_false_negatives"] == [
        {"title": "reliability analyst", "count": 1, "shared_terms": ["reliability"]}
    ]
    assert first["providers"][0]["boards"][0]["board"]["enabled"] is False
    assert first["providers"][0]["boards"][0]["filter_accounting"]["valid"] is True
    assert first["totals"]["filter_accounting_errors"] == 0
    assert len(first["promotion_candidates"]) == 2
    assert first["possible_false_negatives"] == [{"title": "reliability analyst", "count": 2}]
    assert output.exists()

    second = audit_community_catalog(
        _config(),
        providers=["greenhouse"],
        limit_per_provider=2,
        cursor_path=cursor,
        output_path=output,
        client=client,
    )
    assert [board["identifier"] for board in second["providers"][0]["boards"]] == [
        "gamma",
        "alpha",
    ]


def test_catalog_board_identifiers_are_constrained_to_known_hosts():
    board = _board("workday", "acme|wd5|Careers")
    assert board.api_url == "https://acme.wd5.myworkdayjobs.com/wday/cxs/acme/Careers/jobs"
    assert board.enabled is False
    with pytest.raises(ValueError, match="invalid board identifier"):
        _board("greenhouse", "../private")


def test_catalog_audit_rejects_unbounded_runs(tmp_path: Path):
    with pytest.raises(ValueError, match="between 1 and 100"):
        audit_community_catalog(
            _config(),
            providers=["greenhouse"],
            limit_per_provider=101,
            cursor_path=tmp_path / "cursor.json",
            output_path=tmp_path / "report.json",
        )
