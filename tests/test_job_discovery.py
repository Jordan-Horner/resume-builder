import pytest

from resume_builder.agent_contracts import StructuredModelReply
from resume_builder.discovery_evidence import (
    HistoricalTitleState,
    ResumeDocument,
    TitlePosture,
    extract_query_expansion,
    extract_title_seed,
)
from resume_builder.discovery_portfolio import (
    MAX_TOTAL_QUERIES,
    ColdStartLane,
    GeneratedTitleSuggestion,
    GeneratedTitleSuggestions,
    RejectionReason,
    TitleGenerationMetadata,
    TitleGenerationResult,
    build_cold_start_portfolio,
    generate_title_suggestions,
    generation_request_hash,
    title_generation_prompt,
)


def fictional_resume() -> ResumeDocument:
    return ResumeDocument(
        source_id="fictional-progressing-career.md",
        content="""\
# Professional Summary
Operations engineer who enjoys reliable systems.

# Work Experience

## Example Cloud | Production Services Lead | 2024 - 2026
- Led production incident response across AWS and Kubernetes services.
- Built a FastAPI and Postgres troubleshooting service using Python.

## Example Data | Technical Support Engineer | 2021 - 2024
- Reproduced distributed software failures with Docker and Kubernetes.
- Automated Terraform deployments through GitLab CI/CD.

## Example Hosting | Linux Systems Administrator | 2016 - 2020
- Supported Linux infrastructure and automated operational work with Bash.

## Example School | Help Desk Agent | 2012 - 2014
- Resolved workstation requests.

# Technical Skills
- AWS, Linux, Docker, Kubernetes, Terraform, Python, Bash, FastAPI, Postgres
""",
    )


def fictional_generation(
    document: ResumeDocument, suggestions: list[GeneratedTitleSuggestion]
) -> TitleGenerationResult:
    model = "fictional/model"
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
        suggestions=GeneratedTitleSuggestions(suggestions=suggestions),
    )


def test_old_titles_are_history_not_automatic_queries() -> None:
    seed = extract_title_seed([fictional_resume()])
    states = {item.query_title: item.state for item in seed.historical_titles}

    assert states["Production Services Lead"] == HistoricalTitleState.ACTIVE
    assert states["Technical Support Engineer"] == HistoricalTitleState.ACTIVE
    assert states["Linux Systems Administrator"] == HistoricalTitleState.HISTORICAL_CONTEXT
    assert states["Help Desk Agent"] == HistoricalTitleState.HISTORICAL_CONTEXT


def test_summary_role_label_does_not_become_a_historical_title() -> None:
    titles = {
        item.query_title for item in extract_title_seed([fictional_resume()]).historical_titles
    }

    assert "Operations Engineer" not in titles
    assert "Example Cloud" not in titles


def test_normalized_snapshot_role_layout_is_supported() -> None:
    document = ResumeDocument(
        source_id="fictional-normalized-source.md",
        content="""\
# Normalized source snapshot
## Technical Skills
**Cloud:** AWS, Kubernetes
## Experience
### Example Company
**Production Services Engineer**
2024 - 2026
- Supported production systems and incident response in AWS.
""",
    )

    seed = extract_title_seed([document])

    assert [item.query_title for item in seed.historical_titles] == ["Production Services Engineer"]


def test_query_expansion_keeps_capabilities_role_coherent() -> None:
    expansion = extract_query_expansion(fictional_resume())
    queries = {item.query for item in expansion.capability_combinations}

    assert "AWS Kubernetes" in queries
    assert "FastAPI Terraform" not in queries


def test_query_expansion_does_not_invent_missing_terms() -> None:
    document = ResumeDocument(
        source_id="fictional-minimal.md",
        content="""\
# Work Experience
## Example | Support Specialist | 2024 - 2026
- Resolved account questions.
# Technical Skills
- Ticketing
""",
    )

    assert extract_query_expansion(document).capability_combinations == []


def test_cold_start_portfolio_combines_grounded_lanes() -> None:
    document = fictional_resume()
    generation = fictional_generation(
        document,
        [
            GeneratedTitleSuggestion(
                title="Reliability Automation Engineer",
                posture=TitlePosture.ADJACENT,
                evidence_role="Production Services Lead",
                evidence_terms=["AWS", "Kubernetes"],
                reason="Production response and container evidence support this adjacent title.",
            ),
            GeneratedTitleSuggestion(
                title="Developer Productivity Engineer",
                posture=TitlePosture.EXPLORATORY,
                evidence_role="Technical Support Engineer",
                evidence_terms=["Terraform", "GitLab CI/CD"],
                reason="Automation and delivery-system evidence support this exploratory title.",
            ),
        ],
    )

    portfolio = build_cold_start_portfolio(
        document,
        extract_title_seed([document]),
        extract_query_expansion(document),
        generation,
    )
    lanes = {query.lane for query in portfolio.queries}

    assert portfolio.activation == "draft-review-required"
    assert lanes >= {
        ColdStartLane.HISTORICAL_TITLE,
        ColdStartLane.ADJACENT_TITLE,
        ColdStartLane.EXPLORATION,
        ColdStartLane.CAPABILITY_COMBINATION,
    }
    assert len(portfolio.queries) <= MAX_TOTAL_QUERIES
    assert portfolio.title_generation == generation.metadata


def test_cold_start_rejects_unsupported_and_historical_suggestions() -> None:
    document = fictional_resume()
    suggestions = [
        GeneratedTitleSuggestion(
            title="Technical Support Engineer",
            posture=TitlePosture.ADJACENT,
            evidence_role="Technical Support Engineer",
            evidence_terms=["Docker", "Kubernetes"],
            reason="This deliberately duplicates a historical title for validation.",
        ),
        GeneratedTitleSuggestion(
            title="Machine Learning Engineer",
            posture=TitlePosture.EXPLORATORY,
            evidence_role="Production Services Lead",
            evidence_terms=["TensorFlow", "model training"],
            reason="This deliberately cites evidence absent from the fictional resume.",
        ),
        GeneratedTitleSuggestion(
            title="Cloud Architect",
            posture=TitlePosture.EXPLORATORY,
            evidence_role="Help Desk Agent",
            evidence_terms=["AWS", "Kubernetes"],
            reason="This deliberately relies only on unrelated global skill evidence.",
        ),
    ]

    portfolio = build_cold_start_portfolio(
        document,
        extract_title_seed([document]),
        extract_query_expansion(document),
        fictional_generation(document, suggestions),
    )

    assert {item.reason_code for item in portfolio.rejected_suggestions} == {
        RejectionReason.HISTORICAL_DUPLICATE,
        RejectionReason.NO_ROLE_EVIDENCE,
        RejectionReason.UNSUPPORTED_EVIDENCE,
    }


def test_local_only_portfolio_has_no_inferred_titles() -> None:
    document = fictional_resume()
    portfolio = build_cold_start_portfolio(
        document,
        extract_title_seed([document]),
        extract_query_expansion(document),
    )

    assert not any(query.lane == ColdStartLane.ADJACENT_TITLE for query in portfolio.queries)
    assert any(query.lane == ColdStartLane.CAPABILITY_COMBINATION for query in portfolio.queries)


def test_title_generation_packet_excludes_summary_and_source_name() -> None:
    document = fictional_resume().model_copy(update={"source_id": "Private Person Resume.md"})
    prompt = title_generation_prompt(document)

    assert "Private Person" not in prompt
    assert "Operations engineer who enjoys reliable systems" not in prompt
    assert "Production Services Lead" in prompt


def test_generated_title_validation_rejects_provider_syntax() -> None:
    with pytest.raises(ValueError, match="double quotes"):
        GeneratedTitleSuggestion(
            title='Cloud "Expert"',
            posture=TitlePosture.ADJACENT,
            evidence_role="Production Services Lead",
            evidence_terms=["AWS", "Kubernetes"],
            reason="Quoted provider syntax must not enter a draft portfolio.",
        )


def test_cold_start_enforces_generated_lane_budgets() -> None:
    document = fictional_resume()
    suggestions = [
        GeneratedTitleSuggestion(
            title=f"Reliability Specialist {index}",
            posture=TitlePosture.ADJACENT,
            evidence_role="Production Services Lead",
            evidence_terms=["AWS", "Kubernetes"],
            reason="Production response and container evidence support this adjacent title.",
        )
        for index in range(12)
    ]
    suggestions.extend(
        GeneratedTitleSuggestion(
            title=f"Exploratory Operations Specialist {index}",
            posture=TitlePosture.EXPLORATORY,
            evidence_role="Production Services Lead",
            evidence_terms=["AWS", "Kubernetes"],
            reason="Production response and cloud evidence support this exploratory title.",
        )
        for index in range(6)
    )

    portfolio = build_cold_start_portfolio(
        document,
        extract_title_seed([document]),
        extract_query_expansion(document),
        fictional_generation(document, suggestions),
    )

    assert sum(query.lane == ColdStartLane.ADJACENT_TITLE for query in portfolio.queries) == 10
    assert sum(query.lane == ColdStartLane.EXPLORATION for query in portfolio.queries) == 4
    assert (
        sum(
            item.reason_code == RejectionReason.LANE_BUDGET_EXCEEDED
            for item in portfolio.rejected_suggestions
        )
        == 4
    )


def test_title_generation_uses_provider_neutral_structured_contract() -> None:
    class FakeStructuredAdapter:
        def __init__(self) -> None:
            self.request = None

        def run_structured(self, request):
            self.request = request
            return StructuredModelReply(
                output=GeneratedTitleSuggestions(
                    suggestions=[
                        GeneratedTitleSuggestion(
                            title="Reliability Engineer",
                            posture=TitlePosture.ADJACENT,
                            evidence_role="Production Services Lead",
                            evidence_terms=["AWS", "Kubernetes"],
                            reason="Production and container evidence support this title.",
                        )
                    ]
                ),
                model=request.model,
            )

    adapter = FakeStructuredAdapter()
    result = generate_title_suggestions(fictional_resume(), adapter, model="fictional/model")

    assert result.suggestions.suggestions[0].title == "Reliability Engineer"
    assert result.metadata.model == "fictional/model"
    assert adapter.request.output_type is GeneratedTitleSuggestions


def test_generation_hash_changes_with_resume() -> None:
    document = fictional_resume()
    model = "fictional/model"
    first = generation_request_hash(document, model)
    changed = document.model_copy(update={"content": document.content + "\n- Added evidence."})

    assert first != generation_request_hash(changed, model)
