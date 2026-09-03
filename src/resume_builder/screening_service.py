"""Application service for bounded, cached semantic job screening."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .agent_contracts import ModelAdapter, StructuredModelRequest
from .job_screening import (
    SCREENING_INSTRUCTIONS,
    EligibilityStatus,
    ScreeningCache,
    ScreeningPacket,
    ScreeningResult,
    SemanticScreen,
    deterministic_ineligible_result,
    finalize_screen,
    screening_prompt,
)


@dataclass(frozen=True)
class ScreeningOutcome:
    result: ScreeningResult
    cached: bool
    requests: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: Decimal = Decimal("0")


class ScreeningService:
    def __init__(self, adapter: ModelAdapter, cache: ScreeningCache):
        self.adapter = adapter
        self.cache = cache

    def screen(
        self,
        packet: ScreeningPacket,
        *,
        model: str,
        refresh: bool = False,
    ) -> tuple[ScreeningResult, bool]:
        """Return a validated result and whether it came from the local cache."""
        outcome = self.screen_detailed(packet, model=model, refresh=refresh)
        return outcome.result, outcome.cached

    def screen_detailed(
        self,
        packet: ScreeningPacket,
        *,
        model: str,
        refresh: bool = False,
    ) -> ScreeningOutcome:
        """Return a screen plus content-free usage data for bounded batch accounting."""
        if packet.eligibility == EligibilityStatus.INELIGIBLE:
            return ScreeningOutcome(deterministic_ineligible_result(packet), False)
        if not refresh:
            cached = self.cache.get(packet, model)
            if cached is not None:
                return ScreeningOutcome(cached, True)
        reply = self.adapter.run_structured(
            StructuredModelRequest(
                prompt=screening_prompt(packet),
                instructions=SCREENING_INSTRUCTIONS,
                model=model,
                output_type=SemanticScreen,
            )
        )
        semantic = SemanticScreen.model_validate(reply.output)
        result = finalize_screen(packet, semantic, model=reply.model)
        self.cache.put(packet, result)
        return ScreeningOutcome(
            result=result,
            cached=False,
            requests=reply.requests,
            input_tokens=reply.input_tokens,
            output_tokens=reply.output_tokens,
            cost_usd=Decimal(reply.cost_usd or "0"),
        )
