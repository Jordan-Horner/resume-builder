"""Posting-only interpretation remains grounded, bounded, and candidate-independent."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from resume_builder.agent_contracts import StructuredModelReply, StructuredModelRequest
from resume_builder.job_screening import (
    CitedFinding,
    Confidence,
    CriterionAssessment,
    CriterionAssessmentOutcome,
    FitOutcome,
    ScreeningCache,
    ScreeningJob,
    SemanticScreen,
    build_screening_packet,
    screening_prompt,
)
from resume_builder.posting_interpretation import (
    MAX_INTERPRETATION_CHARS,
    PostingInterpretationCache,
    PostingInterpretationService,
    ProposedPostingCriterion,
    ProposedPostingInterpretation,
    SectionReview,
    bound_posting_description,
    build_interpretation_packet,
    section_posting,
    validate_interpretation,
)
from resume_builder.screening_service import (
    ScreeningService,
    enrich_packet_from_cached_interpretation,
)
from resume_builder.workspace import initialize_workspace


def _job(description: str, *, truncated: bool = False, digest: str = "a" * 64) -> ScreeningJob:
    return ScreeningJob(
        id="fictional-role",
        title="Platform Engineer",
        company="Fictional Systems",
        location="United States",
        work_modes=["remote"],
        url="https://example.invalid/jobs/platform",
        description=description,
        description_truncated=truncated,
        description_hash=digest,
    )


def test_packet_exposes_stable_source_units_instead_of_free_form_section_text() -> None:
    description = (
        "Requirements\n"
        "- Operate production systems.\n"
        "- 3.5 years of U.S. support experience. Work on-call rotations."
    )

    first = build_interpretation_packet(_job(description))
    second = build_interpretation_packet(_job(description))

    units = first.sections[0].source_units
    assert [unit.id for unit in units] == [
        "section-1-unit-1",
        "section-1-unit-2",
        "section-1-unit-3",
    ]
    assert [unit.text for unit in units] == [
        "Operate production systems.",
        "3.5 years of U.S. support experience.",
        "Work on-call rotations.",
    ]
    assert all(unit.text in description for unit in units)
    assert max(len(unit.text) for unit in section_posting("word " * 4_000)[0].source_units) <= 900
    assert first.sections == second.sections
    serialized_section = json.loads(first.model_dump_json())["sections"][0]
    assert set(serialized_section) == {"id", "kind", "heading", "source_units"}


def test_server_derives_exact_excerpt_and_section_from_source_unit_ids() -> None:
    packet = build_interpretation_packet(
        _job("Requirements\nOperate Kubernetes. Maintain Terraform modules.")
    )
    unit_ids = [unit.id for unit in packet.sections[0].source_units]
    proposed = ProposedPostingInterpretation(
        criteria=[
            ProposedPostingCriterion(
                id="platform-tooling",
                label="Kubernetes and Terraform",
                description="Operate Kubernetes and maintain Terraform modules.",
                importance="required",
                basis="core_responsibility",
                requirement_type="mandatory-role-defining",
                resume_evaluable=True,
                source_unit_ids=unit_ids,
                retrieval_terms=["Kubernetes", "Terraform"],
                confidence="high",
            )
        ],
        section_reviews=[
            SectionReview(section_id="section-1", disposition="criteria", reason="Core work")
        ],
        criteria_complete=True,
    )

    criterion = validate_interpretation(packet, proposed).criteria[0]

    assert criterion.source_section_id == "section-1"
    assert criterion.source_excerpt == "Operate Kubernetes.\nMaintain Terraform modules."


def test_validation_rejects_unknown_or_cross_section_source_units() -> None:
    packet = build_interpretation_packet(
        _job("Responsibilities\nOperate Kubernetes.\nRequirements\nMaintain Terraform modules.")
    )
    interpretation = ProposedPostingInterpretation(
        criteria=[
            ProposedPostingCriterion(
                id="platform-tooling",
                label="Kubernetes and Terraform",
                description="Operate Kubernetes and maintain Terraform modules.",
                importance="required",
                basis="core_responsibility",
                requirement_type="mandatory-role-defining",
                resume_evaluable=True,
                source_unit_ids=[
                    packet.sections[0].source_units[0].id,
                    packet.sections[1].source_units[0].id,
                ],
                retrieval_terms=["Kubernetes", "Terraform"],
                confidence="high",
            )
        ],
        section_reviews=[
            SectionReview(section_id=section.id, disposition="criteria", reason="Relevant")
            for section in packet.sections
        ],
        criteria_complete=True,
    )

    with pytest.raises(ValueError, match="one section"):
        validate_interpretation(packet, interpretation)

    unknown = interpretation.model_copy(deep=True)
    unknown.criteria[0].source_unit_ids = ["section-1-unit-99"]
    with pytest.raises(ValueError, match="unknown source unit"):
        validate_interpretation(packet, unknown)

    repeated = interpretation.model_copy(deep=True)
    repeated.criteria[0].source_unit_ids = [
        packet.sections[0].source_units[0].id,
        packet.sections[0].source_units[0].id,
    ]
    with pytest.raises(ValueError, match="repeats a source unit"):
        validate_interpretation(packet, repeated)


def test_provider_output_schema_cannot_supply_derived_source_text() -> None:
    schema = ProposedPostingInterpretation.model_json_schema()
    criterion = schema["$defs"]["ProposedPostingCriterion"]["properties"]

    assert "source_unit_ids" in criterion
    assert "source_excerpt" not in criterion
    assert "source_section_id" not in criterion


def _interpretation(packet: object) -> ProposedPostingInterpretation:
    sections = packet.sections  # type: ignore[attr-defined]
    required = next(
        (section for section in sections if section.kind.value == "required_qualifications"),
        sections[0],
    )
    unit = required.source_units[0]
    return ProposedPostingInterpretation(
        criteria=[
            ProposedPostingCriterion(
                id="platform-operations",
                label="Platform operations",
                description="Operate a production platform.",
                importance="required",
                basis="core_responsibility",
                requirement_type="mandatory-role-defining",
                resume_evaluable=True,
                source_unit_ids=[unit.id],
                retrieval_terms=[unit.text],
                confidence="high",
            )
        ],
        section_reviews=[
            SectionReview(
                section_id=section.id,
                disposition="criteria" if section.id == required.id else "non_evaluative",
                reason=(
                    "Contains the central work."
                    if section.id == required.id
                    else "No additional material criterion."
                ),
            )
            for section in sections
        ],
        criteria_complete=packet.posting_coverage == "complete",  # type: ignore[attr-defined]
    )


def test_sectioner_preserves_job_structure_without_candidate_data() -> None:
    description = """About us
Fictional Systems makes software.

Responsibilities
Operate the production platform.

Required qualifications
Five years of platform operations experience.

Preferred qualifications
Kubernetes experience is preferred.

Benefits
Medical and dental coverage.
"""

    packet = build_interpretation_packet(_job(description))

    assert [section.kind.value for section in packet.sections] == [
        "company",
        "responsibilities",
        "required_qualifications",
        "preferred_qualifications",
        "benefits",
    ]
    serialized = packet.model_dump_json().casefold()
    assert "candidate" not in serialized
    assert packet.privacy == "public-job-data"


def test_long_posting_keeps_late_qualifications_before_company_boilerplate() -> None:
    description = (
        "About the company\n"
        + ("Company history and marketing. " * 900)
        + "\nRequired qualifications\nOperate Kubernetes in production.\n"
        + "Preferred qualifications\nTerraform experience is preferred."
    )

    bounded, truncated = bound_posting_description(description)

    assert truncated is True
    assert len(bounded) <= MAX_INTERPRETATION_CHARS
    assert "Operate Kubernetes in production" in bounded
    assert "Terraform experience is preferred" in bounded


def test_shadow_section_budget_does_not_change_current_screen_payload() -> None:
    description = (
        "About the company\n"
        + ("Company history and marketing. " * 900)
        + "\nRequired qualifications\nOperate Kubernetes in production."
    )
    packet = build_screening_packet(
        {
            "id": "fictional-long",
            "title": "Platform Engineer",
            "company": "Fictional Systems",
            "location": "Remote",
            "work_modes": ["remote"],
            "description_text": description,
            "url": "https://example.invalid/jobs/long",
        },
        {
            "accepted_work_modes": ["remote"],
            "include_unknown_locations": True,
            "screening_profile": {"supported_capabilities": ["platform operations"]},
        },
        {},
    )

    assert "Operate Kubernetes in production" not in packet.job.description
    assert "Operate Kubernetes in production" in packet.interpretation_description
    assert "interpretation_description" not in screening_prompt(packet)


def test_validation_requires_exact_section_coverage_and_lexically_grounded_excerpt() -> None:
    packet = build_interpretation_packet(
        _job("Responsibilities\nOperate the production platform.\nBenefits\nMedical coverage.")
    )
    valid = _interpretation(packet)

    validated = validate_interpretation(packet, valid)
    assert validated.criteria[0].source_excerpt == "Operate the production platform."

    invalid = valid.model_copy(deep=True)
    invalid.criteria[0].source_unit_ids = ["section-1-unit-99"]
    with pytest.raises(ValueError, match="unknown source unit"):
        validate_interpretation(packet, invalid)

    missing_review = valid.model_copy(update={"section_reviews": valid.section_reviews[:-1]})
    with pytest.raises(ValueError, match="cover the packet exactly"):
        validate_interpretation(packet, missing_review)


def test_validation_rejects_a_criterion_bound_to_the_wrong_source_sentence() -> None:
    packet = build_interpretation_packet(
        _job("Requirements\nBachelor's degree with two years of experience.")
    )
    interpretation = _interpretation(packet)
    interpretation.criteria[0] = interpretation.criteria[0].model_copy(
        update={
            "label": "Production support experience",
            "description": "Provide production support.",
            "retrieval_terms": ["production support"],
        }
    )

    with pytest.raises(ValueError, match="does not support its label or retrieval terms"):
        validate_interpretation(packet, interpretation)


def test_partial_posting_is_normalized_to_incomplete_criteria() -> None:
    packet = build_interpretation_packet(_job("Operate production systems.", truncated=True))
    interpretation = _interpretation(packet).model_copy(update={"criteria_complete": True})

    validated = validate_interpretation(packet, interpretation)

    assert validated.criteria_complete is False


def test_section_disposition_is_derived_from_validated_citations() -> None:
    packet = build_interpretation_packet(
        _job("Responsibilities\nOperate the production platform.\nBenefits\nMedical coverage.")
    )
    interpretation = _interpretation(packet)
    interpretation.section_reviews[0].disposition = "non_evaluative"
    interpretation.section_reviews[1].disposition = "criteria"

    validated = validate_interpretation(packet, interpretation)

    assert [review.disposition.value for review in validated.section_reviews] == [
        "criteria",
        "non_evaluative",
    ]


def test_preferred_and_substitution_contracts_are_normalized_safely() -> None:
    packet = build_interpretation_packet(
        _job("Requirements\nKubernetes experience is preferred.\nA bachelor's degree is required.")
    )
    preferred = ProposedPostingCriterion(
        id="kubernetes",
        label="Kubernetes",
        description="Kubernetes experience is preferred.",
        importance="required",
        basis="preference",
        requirement_type="mandatory-role-defining",
        resume_evaluable=True,
        source_unit_ids=[packet.sections[0].source_units[0].id],
        retrieval_terms=["Kubernetes"],
        confidence="high",
    )
    unsupported_substitution = ProposedPostingCriterion(
        id="degree",
        label="Bachelor's degree",
        description="A bachelor's degree is required.",
        importance="required",
        basis="explicit_minimum",
        requirement_type="mandatory-substitutable",
        resume_evaluable=True,
        source_unit_ids=[packet.sections[0].source_units[1].id],
        retrieval_terms=["bachelor's degree"],
        confidence="high",
    )
    interpretation = ProposedPostingInterpretation(
        criteria=[preferred, unsupported_substitution],
        section_reviews=[
            SectionReview(section_id="section-1", disposition="criteria", reason="Requirements")
        ],
        criteria_complete=True,
    )

    validated = validate_interpretation(packet, interpretation)

    assert validated.criteria[0].importance.value == "preferred"
    assert validated.criteria[0].requirement_type.value == "preferred"
    assert validated.criteria[1].requirement_type.value == "mandatory-role-defining"


def test_resume_evaluable_work_and_lifestyle_fields_are_normalized() -> None:
    packet = build_interpretation_packet(
        _job("Requirements: Provide L2 production support. Must hold a security clearance.")
    )
    work = ProposedPostingCriterion(
        id="production-support",
        label="L2 production support",
        description="Provide L2 production support.",
        importance="required",
        basis="core_responsibility",
        requirement_type="mandatory-role-defining",
        resume_evaluable=False,
        source_unit_ids=[packet.sections[0].source_units[0].id],
        retrieval_terms=["production support"],
        confidence="high",
    )
    clearance = ProposedPostingCriterion(
        id="clearance",
        label="Security clearance",
        description="Must hold a security clearance.",
        importance="required",
        basis="explicit_minimum",
        requirement_type="mandatory-role-defining",
        resume_evaluable=True,
        source_unit_ids=[packet.sections[0].source_units[1].id],
        retrieval_terms=["security clearance"],
        confidence="high",
    )
    interpretation = ProposedPostingInterpretation(
        criteria=[work, clearance],
        section_reviews=[
            SectionReview(section_id="section-1", disposition="criteria", reason="Requirements")
        ],
        criteria_complete=True,
    )

    validated = validate_interpretation(packet, interpretation)

    assert validated.criteria[0].resume_evaluable is True
    assert validated.criteria[1].basis.value == "lifestyle"
    assert validated.criteria[1].requirement_type.value == "lifestyle"
    assert validated.criteria[1].resume_evaluable is False


class InterpretationAdapter:
    def __init__(self) -> None:
        self.requests: list[StructuredModelRequest] = []

    def run(self, request: object) -> object:
        raise AssertionError("free-form calls are not allowed")

    def run_structured(self, request: StructuredModelRequest) -> StructuredModelReply:
        self.requests.append(request)
        payload = json.loads(request.prompt.split("\n", 1)[1])
        first = payload["sections"][0]
        unit = first["source_units"][0]
        return StructuredModelReply(
            output=ProposedPostingInterpretation(
                criteria=[
                    ProposedPostingCriterion(
                        id="platform-operations",
                        label="Platform operations",
                        description="Operate a production platform.",
                        importance="required",
                        basis="core_responsibility",
                        requirement_type="mandatory-role-defining",
                        resume_evaluable=True,
                        source_unit_ids=[unit["id"]],
                        retrieval_terms=[unit["text"]],
                        confidence="high",
                    )
                ],
                section_reviews=[
                    SectionReview(
                        section_id=section["id"],
                        disposition=(
                            "criteria" if section["id"] == first["id"] else "non_evaluative"
                        ),
                        reason=(
                            "Contains the core work."
                            if section["id"] == first["id"]
                            else "No additional criterion."
                        ),
                    )
                    for section in payload["sections"]
                ],
                criteria_complete=payload["posting_coverage"] == "complete",
            ),
            model=request.model,
            requests=1,
            input_tokens=80,
            output_tokens=20,
            cost_usd="0.001",
        )


def test_interpretation_service_caches_by_posting_hash_model_and_rubric(tmp_path: Path) -> None:
    packet = build_interpretation_packet(_job("Responsibilities\nOperate production systems."))
    adapter = InterpretationAdapter()
    service = PostingInterpretationService(
        adapter, PostingInterpretationCache(tmp_path / "screens.sqlite")
    )

    first = service.interpret(packet, model="fictional/fast")
    second = service.interpret(packet, model="fictional/fast")
    different_model = service.interpret(packet, model="fictional/other")

    assert first.cached is False
    assert second.cached is True
    assert different_model.cached is False
    assert len(adapter.requests) == 2
    assert all(request.output_type is ProposedPostingInterpretation for request in adapter.requests)
    assert all("candidate_evidence" not in request.prompt for request in adapter.requests)


def test_changed_posting_hash_invalidates_interpretation_cache(tmp_path: Path) -> None:
    adapter = InterpretationAdapter()
    service = PostingInterpretationService(
        adapter, PostingInterpretationCache(tmp_path / "screens.sqlite")
    )
    first = build_interpretation_packet(
        _job("Responsibilities\nOperate production systems.", digest="a" * 64)
    )
    changed = build_interpretation_packet(
        _job("Responsibilities\nOperate cloud systems.", digest="b" * 64)
    )

    service.interpret(first, model="fictional/fast")
    service.interpret(changed, model="fictional/fast")

    assert len(adapter.requests) == 2


def test_cached_interpretation_is_revalidated_before_reuse(tmp_path: Path) -> None:
    packet = build_interpretation_packet(_job("Responsibilities\nOperate production systems."))
    adapter = InterpretationAdapter()
    cache = PostingInterpretationCache(tmp_path / "screens.sqlite")
    valid = validate_interpretation(packet, _interpretation(packet))
    invalid = valid.model_copy(deep=True)
    invalid.criteria[0].source_unit_ids = ["section-1-unit-99"]
    cache.put(packet, "fictional/fast", invalid)

    result = PostingInterpretationService(adapter, cache).interpret(packet, model="fictional/fast")

    assert result.cached is False
    assert len(adapter.requests) == 1


def test_section_ids_and_packet_hash_are_stable() -> None:
    description = "Responsibilities\nOperate systems.\nRequirements\nPython experience."

    first = build_interpretation_packet(_job(description))
    second = build_interpretation_packet(_job(description))

    assert [section.id for section in first.sections] == ["section-1", "section-2"]
    assert first.packet_hash == second.packet_hash
    assert section_posting(description) == section_posting(description)


class InvalidShadowAdapter(InterpretationAdapter):
    def run_structured(self, request: StructuredModelRequest) -> StructuredModelReply:
        if request.output_type is ProposedPostingInterpretation:
            reply = super().run_structured(request)
            invalid = ProposedPostingInterpretation.model_validate(reply.output).model_copy(
                deep=True
            )
            invalid.criteria[0].source_unit_ids = ["section-1-unit-99"]
            return StructuredModelReply(output=invalid, model=request.model, requests=1)
        self.requests.append(request)
        packet = json.loads(request.prompt.split("\n", 1)[1])
        return StructuredModelReply(
            output=SemanticScreen(
                fit=FitOutcome.GOOD_MATCH,
                confidence=Confidence.MEDIUM,
                strengths=[
                    CitedFinding(
                        statement="Production operations evidence aligns.",
                        fact_ids=[packet["candidate_evidence"][0]["fact_id"]],
                    )
                ],
                gaps=[],
                unknowns=[],
                reasoning_summary="The current quick screen remains independently validated.",
            ),
            model=request.model,
            requests=1,
        )


def test_invalid_shadow_interpretation_cannot_change_current_screen(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    packet = build_screening_packet(
        {
            "id": "fictional-shadow",
            "title": "Platform Engineer",
            "company": "Fictional Systems",
            "location": "Remote",
            "work_modes": ["remote"],
            "description_text": "Responsibilities\nOperate production systems.",
            "url": "https://example.invalid/jobs/shadow",
        },
        {
            "accepted_work_modes": ["remote"],
            "include_unknown_locations": True,
            "screening_profile": {"supported_capabilities": ["production operations"]},
        },
        {},
    )
    adapter = InvalidShadowAdapter()
    cache_path = tmp_path / "screens.sqlite"
    service = ScreeningService(
        adapter,
        ScreeningCache(cache_path),
        interpretation_service=PostingInterpretationService(
            adapter, PostingInterpretationCache(cache_path)
        ),
    )

    outcome = service.screen_detailed(packet, model="fictional/fast")

    assert outcome.result.fit == FitOutcome.GOOD_MATCH
    assert outcome.posting_interpretation is None
    assert outcome.posting_interpretation_error == "ValueError"
    assert outcome.requests == 2
    assert len(adapter.requests) == 2
    assert "posting_interpretation_failed" in caplog.text


class CriterionScreenAdapter:
    def __init__(self) -> None:
        self.requests: list[StructuredModelRequest] = []

    def run(self, request: object) -> object:
        raise AssertionError("free-form model path must not be used")

    def run_structured(self, request: StructuredModelRequest) -> StructuredModelReply:
        self.requests.append(request)
        payload = json.loads(request.prompt.split("\n", 1)[1])
        if request.output_type is ProposedPostingInterpretation:
            unit = payload["sections"][0]["source_units"][0]
            return StructuredModelReply(
                output=ProposedPostingInterpretation(
                    criteria=[
                        ProposedPostingCriterion(
                            id="kubernetes-operations",
                            label="Kubernetes operations",
                            description="Operate Kubernetes in production.",
                            importance="required",
                            basis="core_responsibility",
                            requirement_type="mandatory-role-defining",
                            resume_evaluable=True,
                            source_unit_ids=[unit["id"]],
                            retrieval_terms=["Kubernetes"],
                            confidence="high",
                        )
                    ],
                    section_reviews=[
                        SectionReview(
                            section_id=section["id"],
                            disposition=(
                                "criteria"
                                if section["id"] == payload["sections"][0]["id"]
                                else "non_evaluative"
                            ),
                            reason="Core responsibility",
                        )
                        for section in payload["sections"]
                    ],
                    criteria_complete=True,
                ),
                model=request.model,
                requests=1,
            )
        criterion = payload["criterion_evidence"][0]
        assert payload["evidence_strategy"] == "criterion-driven"
        assert criterion["criterion_id"] == "kubernetes-operations"
        assert criterion["fact_ids"] == ["OPS-001"]
        assert [card["fact_id"] for card in payload["candidate_evidence"]] == ["OPS-001"]
        return StructuredModelReply(
            output=SemanticScreen(
                fit=FitOutcome.GOOD_MATCH,
                confidence=Confidence.MEDIUM,
                criterion_assessments=[
                    CriterionAssessment(
                        criterion_id="kubernetes-operations",
                        outcome=CriterionAssessmentOutcome.SUPPORTED,
                        confidence=Confidence.HIGH,
                        fact_ids=["OPS-001"],
                        explanation="Confirmed production Kubernetes evidence directly supports the criterion.",
                        materially_affects_recommendation=True,
                    )
                ],
                strengths=[
                    CitedFinding(
                        statement="Production Kubernetes evidence aligns.",
                        fact_ids=["OPS-001"],
                        criterion_id="kubernetes-operations",
                    )
                ],
                gaps=[],
                unknowns=[],
                reasoning_summary="The central criterion has demonstrated evidence.",
            ),
            model=request.model,
            requests=1,
        )


def _canonical_fact(root: Path, fact_id: str, title: str, body: str) -> None:
    folder = root / "vault" / "facts" / "employment" / "example"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{fact_id}.md").write_text(
        "---\n"
        "schema_version: 2\n"
        f"id: {fact_id}\n"
        f'title: "{title}"\n'
        "type: responsibility\n"
        "status: confirmed\n"
        "category: employment\n"
        "organization: example\n"
        "sources:\n  - SRC-000000000001\n"
        "themes:\n  - production\n"
        "---\n\n"
        f"# {title}\n\n{body}\n",
        encoding="utf-8",
    )


def test_valid_interpretation_replaces_broad_evidence_with_criterion_mapped_evidence(
    tmp_path: Path,
) -> None:
    initialize_workspace(tmp_path, git_name="Example", git_email="example@example.invalid")
    _canonical_fact(
        tmp_path,
        "OPS-001",
        "Production Kubernetes operations",
        "Operated Kubernetes workloads in production.",
    )
    _canonical_fact(
        tmp_path,
        "UNRELATED-001",
        "Customer billing support",
        "Resolved invoice disputes and processed billing adjustments.",
    )
    packet = build_screening_packet(
        {
            "id": "fictional-criterion-screen",
            "title": "Platform Engineer",
            "company": "Fictional Systems",
            "location": "Remote",
            "work_modes": ["remote"],
            "description_text": "Operate Kubernetes in production.",
            "url": "https://example.invalid/jobs/criterion-screen",
        },
        {
            "accepted_work_modes": ["remote"],
            "include_unknown_locations": True,
            "screening_profile": {"supported_capabilities": ["broad platform support"]},
        },
        {},
    )
    adapter = CriterionScreenAdapter()
    service = ScreeningService(
        adapter,
        ScreeningCache(tmp_path / "screens.sqlite"),
        interpretation_service=PostingInterpretationService(
            adapter, PostingInterpretationCache(tmp_path / "screens.sqlite")
        ),
        vault_root=tmp_path / "vault",
    )

    outcome = service.screen_detailed(packet, model="fictional/fast")

    assert outcome.result.fit == FitOutcome.GOOD_MATCH
    assert outcome.result.evidence_strategy == "criterion-driven"
    assert [card.fact_id for card in outcome.result.evidence_used] == ["OPS-001"]
    assert outcome.requests == 2
    cached_packet = enrich_packet_from_cached_interpretation(
        packet,
        model="fictional/fast",
        interpretation_cache=PostingInterpretationCache(tmp_path / "screens.sqlite"),
        vault_root=tmp_path / "vault",
    )
    cached_result = ScreeningCache(tmp_path / "screens.sqlite").get(cached_packet, "fictional/fast")
    assert cached_result is not None
    assert cached_result.packet_hash == outcome.result.packet_hash


def test_criterion_retrieval_abstains_without_paying_for_the_private_fit_screen(
    tmp_path: Path,
) -> None:
    initialize_workspace(tmp_path, git_name="Example", git_email="example@example.invalid")
    _canonical_fact(
        tmp_path,
        "UNRELATED-001",
        "Culinary operations",
        "Prepared menus and managed kitchen inventory.",
    )
    packet = build_screening_packet(
        {
            "id": "fictional-no-evidence",
            "title": "Platform Engineer",
            "company": "Fictional Systems",
            "location": "Remote",
            "work_modes": ["remote"],
            "description_text": "Operate Kubernetes in production.",
            "url": "https://example.invalid/jobs/no-evidence",
        },
        {"accepted_work_modes": ["remote"], "include_unknown_locations": True},
        {},
    )
    adapter = CriterionScreenAdapter()
    service = ScreeningService(
        adapter,
        ScreeningCache(tmp_path / "screens.sqlite"),
        interpretation_service=PostingInterpretationService(
            adapter, PostingInterpretationCache(tmp_path / "screens.sqlite")
        ),
        vault_root=tmp_path / "vault",
    )

    outcome = service.screen_detailed(packet, model="fictional/fast")

    assert outcome.result.fit == FitOutcome.INSUFFICIENT_INFORMATION
    assert outcome.result.evidence_strategy == "criterion-driven"
    assert outcome.result.recommendation.value == "needs_more_evidence"
    assert outcome.requests == 1
    assert len(adapter.requests) == 1
