"""PydanticAI implementation of the model-adapter boundary."""

from __future__ import annotations

import asyncio
import os
from typing import Any, cast

from .agent_config import AgentConfig
from .agent_contracts import (
    ModelAdapter,
    ModelProviderError,
    ModelProviderTimeoutError,
    ModelReply,
    ModelRequest,
    StructuredModelReply,
    StructuredModelRequest,
)


class AgentProviderError(ModelProviderError):
    """Report a provider failure without retaining provider content."""


OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


class OpenRouterAdapter(ModelAdapter):
    """Run one bounded PydanticAI turn through OpenRouter."""

    def __init__(
        self,
        config: AgentConfig,
        *,
        api_key: str | None = None,
        timeout_seconds: float | None = None,
        retries: int = 2,
    ):
        self.config = config
        self._api_key = api_key.strip() if api_key else None
        self._timeout_seconds = timeout_seconds
        self._retries = retries

    def _model_settings(
        self,
        settings_type: type,
        provider_options: dict[str, Any],
        *,
        max_output_tokens: int | None = None,
    ) -> Any:
        values: dict[str, Any] = {
            "max_tokens": max_output_tokens or self.config.limits.max_output_tokens,
            "openrouter_provider": cast(Any, provider_options),
        }
        if self._timeout_seconds is not None:
            values["timeout"] = self._timeout_seconds
        return settings_type(**values)

    def _provider(self, provider_type: Any, client_type: type, api_key: str) -> Any:
        client_options: dict[str, Any] = {
            "api_key": api_key,
            "base_url": OPENROUTER_BASE_URL,
            "default_headers": {"X-Title": "Resume Builder"},
            "max_retries": self._retries,
        }
        if self._timeout_seconds is not None:
            client_options["timeout"] = self._timeout_seconds
        try:
            return provider_type(openai_client=client_type(**client_options))
        except Exception as exc:
            raise AgentProviderError(
                f"OpenRouter client initialization failed safely ({exc.__class__.__name__})"
            ) from exc

    def _configured_api_key(self) -> str:
        api_key = self._api_key or os.environ.get(self.config.api_key_env, "").strip()
        if not api_key:
            raise AgentProviderError(f"{self.config.api_key_env} is not configured")
        return api_key

    def _run_agent(self, agent: Any, prompt: str, **kwargs: Any) -> Any:
        if self._timeout_seconds is None:
            return agent.run_sync(prompt, **kwargs)

        async def run_with_deadline() -> Any:
            return await asyncio.wait_for(
                agent.run(prompt, **kwargs), timeout=self._timeout_seconds
            )

        return asyncio.run(run_with_deadline())

    def run(self, request: ModelRequest) -> ModelReply:
        api_key = self._configured_api_key()
        try:
            from openai import AsyncOpenAI
            from pydantic_ai import Agent, Tool
            from pydantic_ai.messages import (
                ModelRequest as PydanticModelRequest,
            )
            from pydantic_ai.messages import (
                ModelResponse as PydanticModelResponse,
            )
            from pydantic_ai.messages import (
                TextPart,
                UserPromptPart,
            )
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
        settings = self._model_settings(OpenRouterModelSettings, provider_options)
        model = OpenRouterModel(
            request.model,
            provider=self._provider(OpenRouterProvider, AsyncOpenAI, api_key),
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
            retries=self._retries,
            name="resume_builder_agent",
        )
        limits = UsageLimits(
            cost_limit=self.config.limits.max_cost_per_turn_usd,
            request_limit=self.config.limits.max_requests,
            tool_calls_limit=self.config.limits.max_tool_calls,
            input_tokens_limit=self.config.limits.max_input_tokens,
            output_tokens_limit=self.config.limits.max_output_tokens,
        )
        message_history: list[Any] = []
        for turn in request.history:
            if turn.role == "user":
                message_history.append(PydanticModelRequest(parts=[UserPromptPart(turn.text)]))
            else:
                message_history.append(PydanticModelResponse(parts=[TextPart(turn.text)]))
        try:
            result = self._run_agent(
                agent,
                request.prompt,
                message_history=message_history or None,
                conversation_id=request.conversation_id,
                model_settings=settings,
                usage_limits=limits,
            )
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
        api_key = self._configured_api_key()
        try:
            from openai import AsyncOpenAI
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
        settings = self._model_settings(
            OpenRouterModelSettings,
            provider_options,
            max_output_tokens=request.max_output_tokens,
        )
        model = OpenRouterModel(
            request.model,
            provider=self._provider(OpenRouterProvider, AsyncOpenAI, api_key),
        )
        agent = Agent(
            model,
            output_type=request.output_type,
            instructions=request.instructions,
            retries=self._retries,
            name="resume_builder_screening_agent",
        )
        limits = UsageLimits(
            cost_limit=self.config.limits.max_cost_per_turn_usd,
            request_limit=self.config.limits.max_requests,
            input_tokens_limit=self.config.limits.max_input_tokens,
            output_tokens_limit=self.config.limits.max_output_tokens,
        )
        try:
            result = self._run_agent(
                agent,
                request.prompt,
                model_settings=settings,
                usage_limits=limits,
            )
        except TimeoutError as exc:
            raise ModelProviderTimeoutError(
                "OpenRouter structured turn exceeded its deadline"
            ) from exc
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
