"""Application service for bounded, cached semantic job screening."""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from .agent_contracts import (
    ModelAdapter,
    ModelProviderError,
    ModelProviderTimeoutError,
    StructuredModelRequest,
)
from .job_screening import (
    SCREENING_INSTRUCTIONS,
    EligibilityStatus,
    PostingWideSemanticScreen,
    ScreeningCache,
    ScreeningPacket,
    ScreeningResult,
    SemanticScreen,
    deterministic_ineligible_result,
    deterministic_insufficient_evidence_result,
    finalize_screen,
    screening_prompt,
    with_directional_resumes,
    with_screening_evidence,
)
from .posting_interpretation import (
    PostingInterpretation,
    PostingInterpretationCache,
    PostingInterpretationService,
    build_interpretation_packet,
)
from .resume_screening import load_directional_resume_candidates
from .screening_evidence import select_criterion_screening_evidence

LOGGER = logging.getLogger(__name__)
INTERACTIVE_SCREEN_TIMEOUT_SECONDS = 15
BACKGROUND_SCREEN_TIMEOUT_SECONDS = 25
QUICK_SCREEN_PROVIDER_RETRIES = 0


class ScreeningProviderError(ModelProviderError):
    """Retain only content-free request-count telemetry across a failed screen."""

    def __init__(self, message: str, *, requests: int, category: str):
        super().__init__(message)
        self.requests = requests
        self.category = category


def provider_error_category(error: BaseException) -> str:
    """Classify a provider failure from exception types without retaining its text."""
    current: BaseException | None = error
    while current is not None:
        name = current.__class__.__name__.casefold()
        if isinstance(current, (ModelProviderTimeoutError, TimeoutError)) or "timeout" in name:
            return "timeout"
        if "ratelimit" in name or "too many requests" in name:
            return "rate_limited"
        if "authentication" in name or "permission" in name:
            return "authentication"
        if "connection" in name or "network" in name:
            return "connection"
        if "validation" in name or "unexpectedmodelbehavior" in name:
            return "invalid_response"
        current = current.__cause__
    return "provider_error"


def _telemetry_job_id(job_id: object) -> str:
    """Return a stable opaque identifier without putting source data in logs."""
    return hashlib.sha256(str(job_id or "").encode("utf-8")).hexdigest()[:12]


@dataclass(frozen=True)
class ScreeningOutcome:
    result: ScreeningResult
    cached: bool
    requests: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: Decimal = Decimal("0")
    posting_interpretation: PostingInterpretation | None = None
    posting_interpretation_cached: bool = False
    posting_interpretation_error: str | None = None


def enrich_packet_from_cached_interpretation(
    packet: ScreeningPacket,
    *,
    model: str,
    interpretation_cache: PostingInterpretationCache,
    vault_root: Path,
) -> ScreeningPacket:
    """Recreate a criterion-driven packet locally so its screen cache remains addressable."""
    resolved_vault = vault_root.expanduser().resolve()
    if not (resolved_vault / "vault.json").is_file():
        return packet
    try:
        description = packet.interpretation_description or None
        interpretation_packet = build_interpretation_packet(
            packet.job,
            description=description,
            description_truncated=(
                packet.interpretation_description_truncated
                if description is not None
                else packet.job.description_truncated
            ),
        )
        interpretation = interpretation_cache.get(interpretation_packet, model)
        if interpretation is None:
            return packet
        evidence = select_criterion_screening_evidence(
            resolved_vault,
            packet.job.model_dump(mode="python"),
            interpretation,
        )
        packet = with_screening_evidence(packet, evidence)
        return with_directional_resumes(
            packet, load_directional_resume_candidates(resolved_vault.parent)
        )
    except (OSError, ValueError) as exc:
        LOGGER.warning(
            "cached_criterion_evidence_retrieval_failed job_id=%s error_category=%s",
            packet.job.id,
            exc.__class__.__name__,
        )
        return packet


class ScreeningService:
    def __init__(
        self,
        adapter: ModelAdapter,
        cache: ScreeningCache,
        *,
        interpretation_service: PostingInterpretationService | None = None,
        interpretation_model: str | None = None,
        vault_root: Path | None = None,
    ):
        self.adapter = adapter
        self.cache = cache
        self.interpretation_service = interpretation_service
        self.interpretation_model = interpretation_model
        self.vault_root = vault_root

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
        interpretation = None
        interpretation_cached = False
        interpretation_error = None
        interpretation_requests = 0
        interpretation_input_tokens = 0
        interpretation_output_tokens = 0
        interpretation_cost = Decimal("0")
        if self.interpretation_service is not None:
            try:
                interpretation_description = packet.interpretation_description or None
                interpretation_packet = build_interpretation_packet(
                    packet.job,
                    description=interpretation_description,
                    description_truncated=(
                        packet.interpretation_description_truncated
                        if interpretation_description is not None
                        else packet.job.description_truncated
                    ),
                )
            except ValueError as exc:
                interpretation_error = exc.__class__.__name__
                LOGGER.warning(
                    "posting_interpretation_failed job_id=%s error_category=%s",
                    packet.job.id,
                    interpretation_error,
                )
            else:
                try:
                    shadow = self.interpretation_service.interpret(
                        interpretation_packet,
                        model=self.interpretation_model or model,
                        refresh=refresh,
                    )
                except (ModelProviderError, ValueError) as exc:
                    interpretation_error = exc.__class__.__name__
                    interpretation_requests = 1
                    LOGGER.warning(
                        "posting_interpretation_failed job_id=%s error_category=%s",
                        packet.job.id,
                        interpretation_error,
                    )
                else:
                    interpretation = shadow.interpretation
                    interpretation_cached = shadow.cached
                    interpretation_requests = shadow.requests
                    interpretation_input_tokens = shadow.input_tokens
                    interpretation_output_tokens = shadow.output_tokens
                    interpretation_cost = Decimal(shadow.cost_usd or "0")
                    if (
                        self.vault_root is not None
                        and (self.vault_root.expanduser().resolve() / "vault.json").is_file()
                    ):
                        try:
                            evidence = select_criterion_screening_evidence(
                                self.vault_root,
                                packet.job.model_dump(mode="python"),
                                interpretation,
                            )
                            packet = with_screening_evidence(packet, evidence)
                            packet = with_directional_resumes(
                                packet,
                                load_directional_resume_candidates(
                                    self.vault_root.expanduser().resolve().parent
                                ),
                            )
                        except (OSError, ValueError) as exc:
                            interpretation_error = exc.__class__.__name__
                            LOGGER.warning(
                                "criterion_evidence_retrieval_failed job_id=%s error_category=%s",
                                packet.job.id,
                                interpretation_error,
                            )
        if not packet.candidate_evidence:
            return ScreeningOutcome(
                deterministic_insufficient_evidence_result(packet),
                False,
                requests=interpretation_requests,
                input_tokens=interpretation_input_tokens,
                output_tokens=interpretation_output_tokens,
                cost_usd=interpretation_cost,
                posting_interpretation=interpretation,
                posting_interpretation_cached=interpretation_cached,
                posting_interpretation_error=interpretation_error,
            )
        if not refresh:
            cached = self.cache.get(packet, model)
            if cached is not None:
                return ScreeningOutcome(
                    cached,
                    True,
                    requests=interpretation_requests,
                    input_tokens=interpretation_input_tokens,
                    output_tokens=interpretation_output_tokens,
                    cost_usd=interpretation_cost,
                    posting_interpretation=interpretation,
                    posting_interpretation_cached=interpretation_cached,
                    posting_interpretation_error=interpretation_error,
                )
        request_started = time.monotonic()
        telemetry_id = _telemetry_job_id(packet.job.id)
        LOGGER.info(
            "screening_provider_request_started job=%s model=%s",
            telemetry_id,
            model,
        )
        try:
            reply = self.adapter.run_structured(
                StructuredModelRequest(
                    prompt=screening_prompt(packet),
                    instructions=SCREENING_INSTRUCTIONS,
                    model=model,
                    output_type=(
                        SemanticScreen if packet.criterion_evidence else PostingWideSemanticScreen
                    ),
                    max_output_tokens=800,
                )
            )
        except ModelProviderError as exc:
            category = provider_error_category(exc)
            LOGGER.warning(
                "screening_provider_request_failed job=%s model=%s duration_ms=%d category=%s",
                telemetry_id,
                model,
                round((time.monotonic() - request_started) * 1000),
                category,
            )
            raise ScreeningProviderError(
                "candidate screening provider failed",
                requests=interpretation_requests + 1,
                category=category,
            ) from exc
        LOGGER.info(
            "screening_provider_request_completed job=%s model=%s duration_ms=%d requests=%d "
            "input_tokens=%d output_tokens=%d cost_usd=%s",
            telemetry_id,
            model,
            round((time.monotonic() - request_started) * 1000),
            reply.requests,
            reply.input_tokens,
            reply.output_tokens,
            reply.cost_usd or "0",
        )
        semantic = SemanticScreen.model_validate(reply.output)
        result = finalize_screen(packet, semantic, model=reply.model)
        self.cache.put(packet, result)
        return ScreeningOutcome(
            result=result,
            cached=False,
            requests=interpretation_requests + reply.requests,
            input_tokens=interpretation_input_tokens + reply.input_tokens,
            output_tokens=interpretation_output_tokens + reply.output_tokens,
            cost_usd=interpretation_cost + Decimal(reply.cost_usd or "0"),
            posting_interpretation=interpretation,
            posting_interpretation_cached=interpretation_cached,
            posting_interpretation_error=interpretation_error,
        )
