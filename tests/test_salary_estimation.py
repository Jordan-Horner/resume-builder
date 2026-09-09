"""Fictional estimates exercise explicit requests and advisory screening boundaries."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from resume_builder.agent_config import render_default_agent_config
from resume_builder.agent_contracts import ModelAdapter, ModelProviderError, StructuredModelReply
from resume_builder.opportunities.salary import (
    SALARY_CACHE_PATH,
    SalaryEstimate,
    SalaryEstimationService,
    build_salary_packet,
    validate_salary_estimate,
)
from resume_builder.web import create_app
from resume_builder.web_service import DashboardService


def posting(**changes: object) -> dict:
    return {
        "id": "fictional-job",
        "title": "Support Engineer",
        "company": "Fictional Cloud",
        "location": "New York, NY",
        "description_text": "Resolve customer incidents.",
        "url": "https://example.invalid/jobs/one",
        **changes,
    }


def estimate(**changes: object) -> SalaryEstimate:
    return SalaryEstimate.model_validate(
        {
            "status": "estimated",
            "minimum": 80_000,
            "maximum": 110_000,
            "currency": "USD",
            "period": "year",
            "confidence": "low",
            "reasoning": "An inferred support engineering range for this location.",
            "company_basis": "Company size and pay policy are unknown.",
            "assumptions": ["US base pay, excluding equity and bonus."],
            **changes,
        }
    )


def adapter_for(output: object) -> Mock:
    adapter = Mock(spec=ModelAdapter)
    adapter.run_structured.return_value = StructuredModelReply(
        output=output,
        model="fictional/model",
        requests=1,
        input_tokens=100,
        output_tokens=50,
    )
    return adapter


@pytest.mark.parametrize(
    "changes",
    [
        {"minimum": -1},
        {"minimum": True},
        {"minimum": float("nan")},
        {"maximum": float("inf")},
        {"maximum": 100},
        {"currency": "US"},
        {"period": None},
        {"confidence": "none"},
        {"assumptions": []},
        {"status": "unavailable"},
    ],
)
def test_invalid_estimate_is_rejected(changes: dict) -> None:
    with pytest.raises(ValidationError):
        estimate(**changes)


def test_packet_uses_only_bounded_posting_data_and_related_company_pay() -> None:
    inventory = [
        posting(id="other", salary_min=90_000),
        posting(id="same-title", company="Fictional Hosting", salary_min=80_000),
        posting(id="other-company-role", company="Elsewhere", title="Accountant", salary_min=1),
        posting(id="missing-pay"),
    ]
    packet = build_salary_packet(
        posting(description_text="x" * 10_000, resume="SECRET", minimum_salary=900_000),
        inventory,
    )
    assert len(packet.job["description"]) == 8_000
    assert [item["id"] for item in packet.related_postings] == ["other", "same-title"]
    assert "SECRET" not in packet.model_dump_json()
    assert "900000" not in packet.model_dump_json()
    assert all("description" not in item for item in packet.related_postings)
    assert build_salary_packet(posting(), list(reversed(inventory))) == build_salary_packet(
        posting(),
        inventory,
    )


@pytest.mark.parametrize(
    "pay",
    [
        {"salary_min": 90_000},
        {"salary_max": 120_000},
        {"description_text": "Base salary $90,000\u2013$120,000 per year."},
    ],
)
def test_posted_pay_skips_estimation_even_without_provider(tmp_path: Path, pay: dict) -> None:
    result, cached = SalaryEstimationService(tmp_path).estimate(
        build_salary_packet(posting(**pay)),
        adapter=None,
        model="",
    )
    assert result.status == "posted"
    assert result.estimate is None
    assert not cached
    assert not list(tmp_path.iterdir())


def test_estimate_cache_refresh_expiry_and_changed_inputs(tmp_path: Path) -> None:
    service = SalaryEstimationService(tmp_path)
    adapter = adapter_for(estimate())
    packet = build_salary_packet(posting())
    first, cached = service.estimate(packet, adapter=adapter, model="fictional/model")
    assert not cached
    second, cached = service.estimate(packet, adapter=None, model="fictional/model")
    assert cached and second == first
    assert adapter.run_structured.call_count == 1
    assert service.get(packet, model="different/model") is None
    assert (
        service.get(
            build_salary_packet(posting(title="Senior Support Engineer")), model="fictional/model"
        )
        is None
    )
    service.estimate(packet, adapter=adapter, model="fictional/model", refresh=True)
    assert adapter.run_structured.call_count == 2
    path = next(tmp_path.glob("*.json"))
    expired = first.model_copy(update={"generated_at": datetime.now(UTC) - timedelta(days=31)})
    path.write_text(expired.model_dump_json())
    assert service.get(packet, model="fictional/model") is None
    assert packet.job.get("salary_min") is None


def test_unknown_references_fail_and_model_only_confidence_is_capped() -> None:
    packet = build_salary_packet(posting())
    with pytest.raises(ValueError, match="outside"):
        validate_salary_estimate(packet, estimate(related_job_ids=["invented"]))
    assert validate_salary_estimate(packet, estimate(confidence="medium")).confidence == "low"


def test_unavailable_is_explicit_and_cached(tmp_path: Path) -> None:
    unavailable = SalaryEstimate(
        status="unavailable",
        confidence="none",
        reasoning="Remote location does not identify a pay market.",
        company_basis="Company pay policy is unknown.",
    )
    service = SalaryEstimationService(tmp_path)
    packet = build_salary_packet(posting(location="Remote"))
    result, _ = service.estimate(packet, adapter=adapter_for(unavailable), model="model")
    assert result.status == "unavailable" and result.estimate.minimum is None
    assert service.estimate(packet, adapter=None, model="model")[1]


def test_posted_endpoint_does_not_require_valid_agent_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "agent/config.yml"
    path.parent.mkdir()
    path.write_text("invalid agent config")
    monkeypatch.setattr(
        DashboardService, "_load_inventory", lambda self: [posting(salary_min=90_000)]
    )
    client = TestClient(create_app(tmp_path))
    assert client.post("/api/jobs/fictional-job/estimate-salary").json()["status"] == "posted"


def test_provider_failures_are_not_saved_as_estimates(tmp_path: Path) -> None:
    adapter = adapter_for(estimate())
    adapter.run_structured.side_effect = ModelProviderError("failed")
    with pytest.raises(ModelProviderError):
        SalaryEstimationService(tmp_path).estimate(
            build_salary_packet(posting()),
            adapter=adapter,
            model="fictional/model",
        )
    assert not list(tmp_path.iterdir())


def test_endpoint_is_explicit_cached_and_leaves_browsing_unchanged(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = tmp_path / "agent/config.yml"
    config.parent.mkdir()
    config.write_text(render_default_agent_config())
    monkeypatch.setenv("OPENROUTER_API_KEY", "fictional-test-key")
    monkeypatch.setattr(DashboardService, "_load_inventory", lambda self: [posting()])
    adapter = adapter_for(estimate())
    monkeypatch.setattr("resume_builder.web_service.OpenRouterAdapter", lambda *a, **kw: adapter)
    client = TestClient(create_app(tmp_path))
    assert client.get("/api/jobs").status_code == 200
    assert client.get("/api/jobs/fictional-job").json()["salary_min"] is None
    adapter.run_structured.assert_not_called()
    url = "/api/jobs/fictional-job/estimate-salary"
    saved_url = "/api/jobs/fictional-job/salary-estimate"
    assert client.get(saved_url).status_code == 204
    adapter.run_structured.assert_not_called()
    response = client.post(url)
    assert response.status_code == 200
    assert response.json()["status"] == "estimated"
    assert not response.json()["cached"]
    assert client.post(url).json()["cached"]
    assert adapter.run_structured.call_count == 1
    saved = client.get(saved_url)
    assert saved.status_code == 200
    assert saved.json()["status"] == "estimated"
    assert saved.json()["cached"] is True
    assert adapter.run_structured.call_count == 1
    assert client.get("/api/jobs/fictional-job").json()["salary_min"] is None
    assert client.get(url).status_code == 405
    assert client.post("/api/jobs/absent/estimate-salary").status_code == 404
    assert len(list((tmp_path / SALARY_CACHE_PATH).glob("*.json"))) == 1
    assert "fictional-test-key" not in json.dumps(response.json())
    adapter.run_structured.side_effect = ModelProviderError("provider details must stay private")
    failed = client.post(url + "?refresh=true")
    assert failed.status_code == 502
    assert "provider details" not in failed.text


def test_endpoint_without_provider_explains_setup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(DashboardService, "_load_inventory", lambda self: [posting()])
    client = TestClient(create_app(tmp_path))
    response = client.post("/api/jobs/fictional-job/estimate-salary")
    assert response.status_code == 400
    assert "Configure an AI provider" in response.json()["detail"]
