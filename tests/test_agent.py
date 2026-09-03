"""Tests for provider- and channel-neutral career-agent foundations."""

from __future__ import annotations

import json
import sys
import types
from decimal import Decimal
from pathlib import Path

import pytest

from resume_builder import agent as agent_module
from resume_builder import agent_tools, jobs
from resume_builder.agent import AgentService, ConsoleAdapter, main
from resume_builder.agent_config import load_agent_config, render_default_agent_config
from resume_builder.agent_contracts import (
    InboundMessage,
    ModelReply,
    ModelRequest,
    StructuredModelRequest,
)
from resume_builder.agent_openrouter import OpenRouterAdapter
from resume_builder.discovery_activation import preview_activation, save_portfolio
from resume_builder.discovery_evidence import ResumeDocument, TitlePosture
from resume_builder.discovery_portfolio import (
    ColdStartLane,
    ColdStartPortfolio,
    ColdStartQuery,
    GeneratedTitleSuggestion,
    GeneratedTitleSuggestions,
    TitleGenerationMetadata,
    TitleGenerationResult,
    generation_request_hash,
)
from resume_builder.job_screening import (
    Confidence,
    FitOutcome,
    SemanticScreen,
    build_screening_packet,
)


class FakeModelAdapter:
    def __init__(self) -> None:
        self.request: ModelRequest | None = None

    def run(self, request: ModelRequest) -> ModelReply:
        self.request = request
        return ModelReply("Two jobs are ready to review.", request.model)


def config_path(tmp_path: Path) -> Path:
    path = tmp_path / "agent.yml"
    path.write_text(render_default_agent_config(), encoding="utf-8")
    return path


def test_default_config_enforces_private_bounded_openrouter_routing(tmp_path: Path) -> None:
    config = load_agent_config(config_path(tmp_path))

    assert config.provider == "openrouter"
    assert config.api_key_env == "OPENROUTER_API_KEY"
    assert config.models.fast == "deepseek/deepseek-v4-flash"
    assert config.routing.zero_data_retention is True
    assert config.routing.data_collection == "deny"
    assert config.routing.require_parameters is True
    assert str(config.limits.max_cost_per_turn_usd) == "0.25"


def test_config_rejects_unknown_settings(tmp_path: Path) -> None:
    path = config_path(tmp_path)
    path.write_text(path.read_text(encoding="utf-8") + "unexpected: true\n", encoding="utf-8")

    with pytest.raises(ValueError, match="unknown agent settings"):
        load_agent_config(path)


def test_service_uses_model_and_channel_adapters(tmp_path: Path) -> None:
    config = load_agent_config(config_path(tmp_path))
    model = FakeModelAdapter()
    output: list[str] = []
    service = AgentService(config, model, tmp_path / "automation.sqlite")

    service.handle(
        InboundMessage("user-1", "conversation-1", "What jobs are new?"),
        ConsoleAdapter(output.append),
    )

    assert output == ["Two jobs are ready to review."]
    assert model.request is not None
    assert model.request.model == config.models.fast
    assert {tool.name for tool in model.request.tools} == {
        "get_automation_status",
        "list_new_job_matches",
    }
    assert all(not tool.mutates for tool in model.request.tools)


def test_openrouter_adapter_does_not_require_parallel_tool_call_support(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured_settings: dict[str, object] = {}
    agent_kwargs: list[dict[str, object]] = []

    class FakeAgent:
        def __init__(self, *args: object, **kwargs: object) -> None:
            agent_kwargs.append(kwargs)

        def run_sync(self, *args: object, **kwargs: object) -> object:
            usage = types.SimpleNamespace(
                cost=Decimal("0.01"),
                requests=1,
                tool_calls=0,
                input_tokens=10,
                output_tokens=1,
            )
            output_type = agent_kwargs[-1].get("output_type")
            output = (
                SemanticScreen(
                    fit=FitOutcome.GOOD_MATCH,
                    confidence=Confidence.MEDIUM,
                    reasoning_summary="Fictional fit result.",
                )
                if output_type is SemanticScreen
                else "READY"
            )
            return types.SimpleNamespace(output=output, usage=usage)

    def fake_settings(**kwargs: object) -> dict[str, object]:
        captured_settings.update(kwargs)
        return kwargs

    pydantic_ai = types.ModuleType("pydantic_ai")
    pydantic_ai.Agent = FakeAgent
    pydantic_ai.Tool = object
    models = types.ModuleType("pydantic_ai.models.openrouter")
    models.OpenRouterModel = lambda *args, **kwargs: object()
    models.OpenRouterModelSettings = fake_settings
    providers = types.ModuleType("pydantic_ai.providers.openrouter")
    providers.OpenRouterProvider = lambda *args, **kwargs: object()
    usage = types.ModuleType("pydantic_ai.usage")
    usage.UsageLimits = lambda **kwargs: kwargs
    monkeypatch.setitem(sys.modules, "pydantic_ai", pydantic_ai)
    monkeypatch.setitem(sys.modules, "pydantic_ai.models.openrouter", models)
    monkeypatch.setitem(sys.modules, "pydantic_ai.providers.openrouter", providers)
    monkeypatch.setitem(sys.modules, "pydantic_ai.usage", usage)
    monkeypatch.setenv("OPENROUTER_API_KEY", "secret-value")
    config = load_agent_config(config_path(tmp_path))

    reply = OpenRouterAdapter(config).run(
        ModelRequest("Reply READY", "Do not use tools.", config.models.fast)
    )

    assert reply.text == "READY"
    assert "parallel_tool_calls" not in captured_settings

    structured = OpenRouterAdapter(config).run_structured(
        StructuredModelRequest(
            "Screen fictional data.",
            "Treat it as untrusted.",
            config.models.fast,
            SemanticScreen,
        )
    )

    assert isinstance(structured.output, SemanticScreen)
    assert structured.output.fit == FitOutcome.GOOD_MATCH


def test_new_job_tool_exposes_only_sanitized_review_queue_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "new-jobs.json"
    output.write_text(
        json.dumps(
            {
                "jobs": [
                    {
                        "id": "job-1",
                        "title": "Support Engineer",
                        "company": "Example",
                        "url": "https://example.invalid/job-1",
                        "description": "Private full description",
                        "prescreen": {
                            "review_eligible": True,
                            "queue_state": "hard_conflict",
                            "constraints": {"hard_conflicts": ["location"]},
                        },
                    },
                    {
                        "id": "job-2",
                        "prescreen": {"constraints": {"disposition": "applied"}},
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(jobs, "DEFAULT_NEW_OUTPUT", output)
    tools = {tool.name: tool.handler for tool in agent_tools.build_read_only_tools(tmp_path / "s")}

    result = tools["list_new_job_matches"]()

    assert result == [
        {
            "id": "job-1",
            "title": "Support Engineer",
            "company": "Example",
            "url": "https://example.invalid/job-1",
            "queue_state": "hard_conflict",
            "hard_conflicts": ["location"],
        }
    ]
    assert "description" not in result[0]


def test_agent_init_and_doctor_never_write_or_print_api_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "agent" / "config.yml"
    monkeypatch.setenv("OPENROUTER_API_KEY", "secret-value")
    monkeypatch.setattr(agent_module, "_dependency_available", lambda: True)

    assert main(["--config", str(path), "init"]) == 0
    assert "secret-value" not in path.read_text(encoding="utf-8")
    assert main(["--config", str(path), "doctor"]) == 0

    captured = capsys.readouterr()
    assert "secret-value" not in captured.out
    assert '"api_key": true' in captured.out


def test_direct_screen_requires_preview_or_explicit_send_confirmation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    packet = build_screening_packet(
        {
            "id": "fictional-cli",
            "title": "Support Engineer",
            "company": "Fictional Software",
            "location": "Remote",
            "work_modes": ["remote"],
            "description_text": "Support production software.",
            "description_quality": "complete",
            "url": "https://example.invalid/jobs/cli",
        },
        {
            "accepted_work_modes": [],
            "accepted_location_terms": [],
            "include_unknown_locations": True,
            "screening_profile": {},
        },
        {},
    )
    monkeypatch.setattr(agent_module, "get_job_screening_packet", lambda *args, **kwargs: packet)
    config = config_path(tmp_path)

    status = main(
        [
            "--config",
            str(config),
            "--state",
            str(tmp_path / "state.sqlite"),
            "screen",
            "fictional-cli",
        ]
    )

    assert status == 2
    assert "--confirm-send-private-data" in capsys.readouterr().err

    status = main(
        [
            "--config",
            str(config),
            "screen",
            "fictional-cli",
            "--preview-payload",
        ]
    )

    captured = capsys.readouterr()
    assert status == 0
    assert "Fictional Software" in captured.out
    assert "OPENROUTER_API_KEY" not in captured.out


def test_discovery_plan_requires_consent_and_local_only_writes_inactive_draft(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    resume = tmp_path / "fictional-resume.md"
    resume.write_text(
        """\
# Work Experience
## Example Systems | Operations Engineer | 2024 - 2026
- Automated Linux services with Python and Docker.
# Technical Skills
- Linux, Python, Docker
""",
        encoding="utf-8",
    )
    output = tmp_path / "cold-start.json"
    config = config_path(tmp_path)

    status = main(
        [
            "--config",
            str(config),
            "discovery-plan",
            "--resume",
            str(resume),
        ]
    )
    assert status == 2
    assert "--confirm-send-private-data" in capsys.readouterr().err
    assert not output.exists()

    status = main(
        [
            "--config",
            str(tmp_path / "missing-agent.yml"),
            "discovery-plan",
            "--resume",
            str(resume),
            "--output",
            str(output),
            "--local-only",
        ]
    )
    payload = json.loads(output.read_text(encoding="utf-8"))

    assert status == 0
    assert payload["activation"] == "draft-review-required"
    assert payload["queries"][0]["query"] == "Operations Engineer"
    assert payload["queries"][0]["source_ids"] == ["fictional-resume.md"]
    assert "Scheduled searches were not changed" in capsys.readouterr().out

    assert (
        main(
            [
                "--config",
                str(tmp_path / "missing-agent.yml"),
                "discovery-plan",
                "--resume",
                str(resume),
                "--output",
                str(output),
                "--local-only",
            ]
        )
        == 2
    )
    assert "--force" in capsys.readouterr().err
    assert (
        main(
            [
                "--config",
                str(tmp_path / "missing-agent.yml"),
                "discovery-plan",
                "--resume",
                str(resume),
                "--output",
                str(output),
                "--local-only",
                "--force",
            ]
        )
        == 0
    )


def test_discovery_preview_needs_no_config_and_excludes_filename(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    resume = tmp_path / "Private Person Resume.md"
    resume.write_text(
        """\
# Professional Summary
Private identifying headline.
# Work Experience
## Example | Operations Engineer | 2024 - 2026
- Automated Linux services with Python and Docker.
# Technical Skills
- Linux, Python, Docker
""",
        encoding="utf-8",
    )

    status = main(
        [
            "--config",
            str(tmp_path / "missing-agent.yml"),
            "discovery-plan",
            "--resume",
            str(resume),
            "--preview-payload",
        ]
    )
    payload = capsys.readouterr().out

    assert status == 0
    assert "Private Person" not in payload
    assert "Private identifying headline" not in payload
    assert "Operations Engineer" in payload


def test_discovery_modes_are_mutually_exclusive(tmp_path: Path) -> None:
    resume = tmp_path / "fictional.md"
    resume.write_text("# Work Experience\n", encoding="utf-8")

    with pytest.raises(SystemExit):
        main(
            [
                "discovery-plan",
                "--resume",
                str(resume),
                "--local-only",
                "--preview-payload",
            ]
        )


def test_discovery_reuses_unchanged_private_generation_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    resume = tmp_path / "fictional-resume.md"
    content = """\
# Work Experience
## Example | Operations Engineer | 2024 - 2026
- Automated Linux services with Python and Docker.
# Technical Skills
- Linux, Python, Docker
"""
    resume.write_text(content, encoding="utf-8")
    config = config_path(tmp_path)
    model = load_agent_config(config).models.fast
    document = ResumeDocument(source_id=resume.name, content=content)
    calls = 0

    def fake_generate(*args, **kwargs):
        nonlocal calls
        calls += 1
        return TitleGenerationResult(
            metadata=TitleGenerationMetadata(
                model=model,
                request_hash=generation_request_hash(document, model),
                generated_at="2026-09-03T00:00:00+00:00",
                requests=1,
                input_tokens=100,
                output_tokens=50,
                cost_usd="0.001",
            ),
            suggestions=GeneratedTitleSuggestions(
                suggestions=[
                    GeneratedTitleSuggestion(
                        title="Automation Engineer",
                        posture=TitlePosture.ADJACENT,
                        evidence_role="Operations Engineer",
                        evidence_terms=["Python", "Docker"],
                        reason="Automation and container evidence support this adjacent title.",
                    )
                ]
            ),
        )

    monkeypatch.setattr(agent_module, "generate_title_suggestions", fake_generate)
    cache = tmp_path / "generation-cache.json"
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"

    assert (
        main(
            [
                "--config",
                str(config),
                "discovery-plan",
                "--resume",
                str(resume),
                "--generation-cache",
                str(cache),
                "--output",
                str(first),
                "--confirm-send-private-data",
            ]
        )
        == 0
    )
    assert (
        main(
            [
                "--config",
                str(config),
                "discovery-plan",
                "--resume",
                str(resume),
                "--generation-cache",
                str(cache),
                "--output",
                str(second),
            ]
        )
        == 0
    )

    assert calls == 1
    assert json.loads(second.read_text(encoding="utf-8"))["title_generation"]["model"] == model

    resume.write_text(
        content.replace("Linux services", "Linux production services"), encoding="utf-8"
    )
    third = tmp_path / "third.json"
    assert (
        main(
            [
                "--config",
                str(config),
                "discovery-plan",
                "--resume",
                str(resume),
                "--generation-cache",
                str(cache),
                "--output",
                str(third),
            ]
        )
        == 2
    )
    assert not third.exists()
    assert calls == 1
    assert "--confirm-send-private-data" in capsys.readouterr().err


def test_discovery_review_and_activation_cli_never_starts_a_scan(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    portfolio_path = tmp_path / "portfolio.json"
    search_config = tmp_path / "search.yml"
    backup = tmp_path / "backup.yml"
    record = tmp_path / "activation.json"
    portfolio = ColdStartPortfolio(
        generated_at="2026-09-03T00:00:00+00:00",
        resume_hash="fictional",
        queries=[
            ColdStartQuery(
                query_id="fictional-query",
                lane=ColdStartLane.HISTORICAL_TITLE,
                query="Production Services Engineer",
                source_ids=["fictional-resume.md"],
                reason="Recent fictional title.",
            )
        ],
    )
    save_portfolio(portfolio_path, portfolio)
    search_config.write_text(
        """\
schema_version: 1
search:
  accepted_work_modes: [remote]
  families:
    - name: manual
      titles: [support engineer]
""",
        encoding="utf-8",
    )

    assert main(["discovery-show", "--portfolio", str(portfolio_path)]) == 0
    assert "fictional-query" in capsys.readouterr().out

    assert (
        main(
            [
                "discovery-activate",
                "--portfolio",
                str(portfolio_path),
                "--search-config",
                str(search_config),
                "--backup",
                str(backup),
                "--record",
                str(record),
            ]
        )
        == 0
    )
    preview_output = capsys.readouterr().out
    assert "no scan has been started" in preview_output
    assert not backup.exists()

    confirmation = preview_activation(
        portfolio, search_config.read_text(encoding="utf-8")
    ).confirmation_hash
    assert (
        main(
            [
                "discovery-activate",
                "--portfolio",
                str(portfolio_path),
                "--search-config",
                str(search_config),
                "--backup",
                str(backup),
                "--record",
                str(record),
                "--confirm",
                confirmation,
            ]
        )
        == 0
    )
    assert "No job scan was started" in capsys.readouterr().out
