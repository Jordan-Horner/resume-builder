"""Offline evaluation of quick-screen retrieval and judgments."""

import json

import pytest

from resume_builder.screening_evaluation import (
    ScreeningEvaluationCase,
    _load_results,
    evaluate_screening_results,
    finalize_screening_review,
    prepare_screening_review,
)


def test_screening_evaluation_measures_retrieval_assessment_fit_and_abstention() -> None:
    cases = [
        ScreeningEvaluationCase.model_validate(
            {
                "id": "case-1",
                "job_id": "job-1",
                "expected_fit": "good_match",
                "should_abstain": False,
                "criteria": [
                    {
                        "criterion_id": "kubernetes",
                        "relevant_fact_ids": ["FACT-1", "FACT-2"],
                        "allowed_outcomes": ["supported", "partially_supported"],
                    }
                ],
            }
        ),
        ScreeningEvaluationCase.model_validate(
            {
                "id": "case-2",
                "job_id": "job-2",
                "should_abstain": True,
                "criteria": [
                    {
                        "criterion_id": "leadership",
                        "relevant_fact_ids": [],
                        "allowed_outcomes": ["unknown"],
                    }
                ],
            }
        ),
    ]
    results = {
        "job-1": {
            "fit": "good_match",
            "recommendation": "pursue",
            "criterion_evidence": [
                {"criterion_id": "kubernetes", "fact_ids": ["FACT-1", "FACT-X"]}
            ],
            "criterion_assessments": [
                {"criterion_id": "kubernetes", "outcome": "supported", "fact_ids": ["FACT-1"]}
            ],
        },
        "job-2": {
            "fit": "insufficient_information",
            "recommendation": "needs_more_evidence",
            "criterion_evidence": [{"criterion_id": "leadership", "fact_ids": []}],
            "criterion_assessments": [
                {"criterion_id": "leadership", "outcome": "unknown", "fact_ids": []}
            ],
        },
    }

    report = evaluate_screening_results(cases, results)

    assert report.total_cases == 2
    assert report.assessment_coverage == 1.0
    assert report.assessment_outcome_agreement == 1.0
    assert report.retrieval_recall == 0.5
    assert report.retrieval_precision == 0.5
    assert report.abstention_accuracy == 1.0
    assert report.fit_agreement == 1.0
    assert report.cases[0].issues == ["kubernetes: missed expected facts FACT-2"]


def test_screening_evaluation_reports_missing_results_and_assessments() -> None:
    cases = [
        ScreeningEvaluationCase.model_validate(
            {
                "id": "missing-result",
                "job_id": "job-missing",
                "should_abstain": False,
                "criteria": [],
            }
        ),
        ScreeningEvaluationCase.model_validate(
            {
                "id": "missing-assessment",
                "job_id": "job-2",
                "should_abstain": False,
                "criteria": [
                    {
                        "criterion_id": "python",
                        "relevant_fact_ids": ["FACT-1"],
                        "allowed_outcomes": ["supported"],
                    }
                ],
            }
        ),
    ]

    report = evaluate_screening_results(
        cases,
        {
            "job-2": {
                "fit": "weak_fit",
                "recommendation": "deprioritize",
                "criterion_evidence": [],
                "criterion_assessments": [],
            }
        },
    )

    assert report.missing_results == 1
    assert report.assessment_coverage == 0.0
    assert report.cases[0].issues == ["screening result is missing"]
    assert "python: assessment is missing" in report.cases[1].issues
    assert "python: missed expected facts FACT-1" in report.cases[1].issues


def test_screening_evaluation_loads_existing_screening_queue_output(tmp_path) -> None:
    path = tmp_path / "new-job-screens.json"
    path.write_text(
        json.dumps(
            {
                "jobs": [
                    {
                        "id": "job-1",
                        "screening": {
                            "status": "complete",
                            "result": {"job_id": "job-1", "fit": "good_match"},
                        },
                    },
                    {"id": "job-2", "screening": {"status": "unscreened"}},
                ]
            }
        ),
        encoding="utf-8",
    )

    assert _load_results(path) == {"job-1": {"job_id": "job-1", "fit": "good_match"}}


def _review_job(
    job_id: str,
    *,
    provider_url: str,
    fit: str,
    criterion_id: str,
    source_order: int,
) -> dict[str, object]:
    return {
        "id": job_id,
        "title": f"Role {job_id}",
        "company": f"Company {job_id}",
        "url": provider_url,
        "source_order": source_order,
        "screening": {
            "status": "complete",
            "result": {
                "schema_version": 4,
                "job_id": job_id,
                "fit": fit,
                "recommendation": "pursue",
                "confidence": "medium",
                "eligibility": "eligible",
                "evidence_coverage": "partial",
                "posting_coverage": "complete",
                "criterion_evidence": [
                    {
                        "criterion_id": criterion_id,
                        "label": f"Criterion {criterion_id}",
                        "description": "Evidence needed for this role criterion.",
                        "importance": "required",
                        "requirement_type": "mandatory-substitutable",
                        "status": "demonstrated-candidate",
                        "fact_ids": [f"FACT-{job_id}"],
                    }
                ],
                "criterion_assessments": [
                    {
                        "criterion_id": criterion_id,
                        "outcome": "supported",
                        "confidence": "medium",
                        "fact_ids": [f"FACT-{job_id}"],
                        "explanation": "Current model judgment.",
                        "materially_affects_recommendation": True,
                    }
                ],
            },
        },
    }


def test_prepare_screening_review_balances_provider_and_fit_without_inventing_truth() -> None:
    queue = {
        "jobs": [
            _review_job(
                "linkedin-good",
                provider_url="https://www.linkedin.com/jobs/view/1",
                fit="good_match",
                criterion_id="python",
                source_order=0,
            ),
            _review_job(
                "linkedin-weak",
                provider_url="https://www.linkedin.com/jobs/view/2",
                fit="weak_fit",
                criterion_id="linux",
                source_order=1,
            ),
            _review_job(
                "greenhouse-good",
                provider_url="https://boards.greenhouse.io/acme/jobs/3",
                fit="good_match",
                criterion_id="aws",
                source_order=2,
            ),
        ]
    }

    review = prepare_screening_review(queue, limit=3)

    assert review["summary"] == {
        "available_current_screens": 3,
        "selected_cases": 3,
        "skipped_stale_or_incomplete": 0,
    }
    assert {case["job_id"] for case in review["cases"]} == {
        "linkedin-good",
        "linkedin-weak",
        "greenhouse-good",
    }
    first = review["cases"][0]
    assert first["should_abstain"] is None
    assert first["expected_fit"] is None
    assert first["criteria"][0]["allowed_outcomes"] == []
    assert first["criteria"][0]["relevant_fact_ids"] == []
    assert first["criteria"][0]["current_screen"]["retrieved_fact_ids"]


def test_prepare_screening_review_rejects_queue_with_only_stale_screens() -> None:
    with pytest.raises(ValueError, match="current criterion-level screens"):
        prepare_screening_review(
            {
                "jobs": [
                    {
                        "id": "old-job",
                        "screening": {
                            "status": "complete",
                            "result": {"schema_version": 1, "job_id": "old-job"},
                        },
                    }
                ]
            },
            limit=30,
        )


def test_finalize_screening_review_requires_human_labels() -> None:
    review = prepare_screening_review(
        {
            "jobs": [
                _review_job(
                    "job-1",
                    provider_url="https://jobs.ashbyhq.com/acme/1",
                    fit="good_match",
                    criterion_id="incident-response",
                    source_order=0,
                )
            ]
        },
        limit=1,
    )

    with pytest.raises(ValueError, match="still needs human review"):
        finalize_screening_review(review)

    case = review["cases"][0]
    case["should_abstain"] = False
    case["expected_fit"] = "good_match"
    case["criteria"][0]["allowed_outcomes"] = ["supported", "partially_supported"]
    case["criteria"][0]["relevant_fact_ids"] = ["FACT-job-1"]

    finalized = finalize_screening_review(review)

    assert finalized == {
        "cases": [
            {
                "version": 1,
                "id": "case-001",
                "job_id": "job-1",
                "expected_fit": "good_match",
                "should_abstain": False,
                "criteria": [
                    {
                        "criterion_id": "incident-response",
                        "relevant_fact_ids": ["FACT-job-1"],
                        "allowed_outcomes": ["supported", "partially_supported"],
                    }
                ],
            }
        ]
    }
