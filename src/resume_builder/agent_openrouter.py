"""PydanticAI implementation of the model-adapter boundary."""

from __future__ import annotations

import os
from typing import Any, cast

from .agent_config import AgentConfig
from .agent_contracts import (
    ModelAdapter,
    ModelProviderError,
    ModelReply,
    ModelRequest,
    StructuredModelReply,
    StructuredModelRequest,
)


class AgentProviderError(ModelProviderError):
    """Report a provider failure without retaining provider content."""


class OpenRouterAdapter(ModelAdapter):
    """Run one bounded PydanticAI turn through OpenRouter."""

    def __init__(self, config: AgentConfig):
        self.config = config

    def run(self, request: ModelRequest) -> ModelReply:
        api_key = os.environ.get(self.config.api_key_env, "").strip()
        if not api_key:
            raise AgentProviderError(f"{self.config.api_key_env} is not configured")
        try:
            from pydantic_ai import Agent, Tool
            from pydantic_ai.models.openrouter import OpenRouterModel, OpenRouterModelSettings
            from pydantic_ai.providers.openrouter import OpenRouterProvider
            from pydantic_ai.usage import UsageLimits
        except ImportError as exc:
            raise AgentProviderError(
                'agent dependencies are missing; install with `pip install -e ".[agent]"`'
            ) from exc

        provider_options: dict[str, Any] = {
            "allow_fallbacks": self.config.routing.allow_fallbacks,
            "require_parameters": self.config.routing.require_parameters,
            "data_collection": self.config.routing.data_collection,
            "zdr": self.config.routing.zero_data_retention,
        }
        if self.config.routing.providers:
            provider_options["only"] = list(self.config.routing.providers)
        settings = OpenRouterModelSettings(
            max_tokens=self.config.limits.max_output_tokens,
            openrouter_provider=cast(Any, provider_options),
        )
        model = OpenRouterModel(
            request.model,
            provider=OpenRouterProvider(api_key=api_key, app_title="Resume Builder"),
        )
        tools = [
            Tool(
                item.handler,
                name=item.name,
                description=item.description,
                requires_approval=item.requires_approval,
                sequential=True,
            )
            for item in request.tools
        ]
        agent = Agent(
            model,
            instructions=request.instructions,
            tools=tools,
            retries=2,
            name="resume_builder_agent",
        )
        limits = UsageLimits(
            cost_limit=self.config.limits.max_cost_per_turn_usd,
            request_limit=self.config.limits.max_requests,
            tool_calls_limit=self.config.limits.max_tool_calls,
            input_tokens_limit=self.config.limits.max_input_tokens,
            output_tokens_limit=self.config.limits.max_output_tokens,
        )
        try:
            result = agent.run_sync(request.prompt, model_settings=settings, usage_limits=limits)
        except Exception as exc:
            raise AgentProviderError(
                f"OpenRouter turn failed safely ({exc.__class__.__name__})"
            ) from exc
        usage = result.usage
        cost = str(usage.cost) if usage.cost is not None else None
        return ModelReply(
            text=str(result.output),
            model=request.model,
            requests=usage.requests,
            tool_calls=usage.tool_calls,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cost_usd=cost,
        )

    def run_structured(self, request: StructuredModelRequest) -> StructuredModelReply:
        """Run one schema-validated task without exposing provider response types."""
        api_key = os.environ.get(self.config.api_key_env, "").strip()
        if not api_key:
            raise AgentProviderError(f"{self.config.api_key_env} is not configured")
        try:
            from pydantic_ai import Agent
            from pydantic_ai.models.openrouter import OpenRouterModel, OpenRouterModelSettings
            from pydantic_ai.providers.openrouter import OpenRouterProvider
            from pydantic_ai.usage import UsageLimits
        except ImportError as exc:
            raise AgentProviderError(
                'agent dependencies are missing; install with `pip install -e ".[agent]"`'
            ) from exc

        provider_options: dict[str, Any] = {
            "allow_fallbacks": self.config.routing.allow_fallbacks,
            "require_parameters": self.config.routing.require_parameters,
            "data_collection": self.config.routing.data_collection,
            "zdr": self.config.routing.zero_data_retention,
        }
        if self.config.routing.providers:
            provider_options["only"] = list(self.config.routing.providers)
        settings = OpenRouterModelSettings(
            max_tokens=self.config.limits.max_output_tokens,
            openrouter_provider=cast(Any, provider_options),
        )
        model = OpenRouterModel(
            request.model,
            provider=OpenRouterProvider(api_key=api_key, app_title="Resume Builder"),
        )
        agent = Agent(
            model,
            output_type=request.output_type,
            instructions=request.instructions,
            retries=2,
            name="resume_builder_screening_agent",
        )
        limits = UsageLimits(
            cost_limit=self.config.limits.max_cost_per_turn_usd,
            request_limit=self.config.limits.max_requests,
            input_tokens_limit=self.config.limits.max_input_tokens,
            output_tokens_limit=self.config.limits.max_output_tokens,
        )
        try:
            result = agent.run_sync(request.prompt, model_settings=settings, usage_limits=limits)
        except Exception as exc:
            raise AgentProviderError(
                f"OpenRouter structured turn failed safely ({exc.__class__.__name__})"
            ) from exc
        output = result.output
        if not isinstance(output, request.output_type):
            raise AgentProviderError("OpenRouter structured turn returned an invalid result type")
        usage = result.usage
        return StructuredModelReply(
            output=output,
            model=request.model,
            requests=usage.requests,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cost_usd=str(usage.cost) if usage.cost is not None else None,
        )
