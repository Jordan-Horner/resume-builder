"""Application service for bounded, cached semantic job screening."""

from __future__ import annotations

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
        if packet.eligibility == EligibilityStatus.INELIGIBLE:
            return deterministic_ineligible_result(packet), False
        if not refresh:
            cached = self.cache.get(packet, model)
            if cached is not None:
                return cached, True
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
        return result, False
