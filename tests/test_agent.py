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
from resume_builder.agent_contracts import InboundMessage, ModelReply, ModelRequest
from resume_builder.agent_openrouter import OpenRouterAdapter


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

    class FakeAgent:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def run_sync(self, *args: object, **kwargs: object) -> object:
            usage = types.SimpleNamespace(
                cost=Decimal("0.01"),
                requests=1,
                tool_calls=0,
                input_tokens=10,
                output_tokens=1,
            )
            return types.SimpleNamespace(output="READY", usage=usage)

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


def test_new_job_tool_exposes_only_sanitized_review_eligible_fields(
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
                            "category": "SCREEN NEXT",
                            "keyword_readiness": {"percent": 82},
                        },
                    },
                    {"id": "job-2", "prescreen": {"review_eligible": False}},
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
            "category": "SCREEN NEXT",
            "keyword_readiness_percent": 82,
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
