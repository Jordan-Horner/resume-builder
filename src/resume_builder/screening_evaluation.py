"""Offline, provider-free evaluation for the quick job-screening pipeline."""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .atomic import atomic_write_json
from .job_screening import CriterionAssessmentOutcome, FitOutcome, Recommendation


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CriterionEvaluationExpectation(StrictModel):
    """Human-reviewed truth for one stable interpreted criterion."""

    criterion_id: str = Field(min_length=1)
    relevant_fact_ids: list[str] = Field(default_factory=list)
    allowed_outcomes: list[CriterionAssessmentOutcome] = Field(min_length=1)

    @model_validator(mode="after")
    def reject_duplicates(self) -> CriterionEvaluationExpectation:
        if len(self.relevant_fact_ids) != len(set(self.relevant_fact_ids)):
            raise ValueError("relevant_fact_ids must not contain duplicates")
        if len(self.allowed_outcomes) != len(set(self.allowed_outcomes)):
            raise ValueError("allowed_outcomes must not contain duplicates")
        return self


class ScreeningEvaluationCase(StrictModel):
    """A human-reviewed expectation recorded after posting interpretation."""

    version: int = 1
    id: str = Field(min_length=1)
    job_id: str = Field(min_length=1)
    expected_fit: FitOutcome | None = None
    should_abstain: bool
    criteria: list[CriterionEvaluationExpectation]

    @model_validator(mode="after")
    def validate_case(self) -> ScreeningEvaluationCase:
        if self.version != 1:
            raise ValueError("screening evaluation case must declare version 1")
        criterion_ids = [criterion.criterion_id for criterion in self.criteria]
        if len(criterion_ids) != len(set(criterion_ids)):
            raise ValueError("screening evaluation criteria must be unique")
        return self


class ScreeningEvaluationCaseResult(StrictModel):
    case_id: str
    job_id: str
    issues: list[str]


class ScreeningEvaluationReport(StrictModel):
    total_cases: int
    missing_results: int
    assessment_coverage: float
    assessment_outcome_agreement: float
    retrieval_recall: float
    retrieval_precision: float
    abstention_accuracy: float
    fit_agreement: float | None
    cases: list[ScreeningEvaluationCaseResult]


def _provider_name(url: object) -> str:
    hostname = urlparse(str(url)).hostname or "unknown"
    hostname = hostname.removeprefix("www.")
    providers = {
        "linkedin.com": "linkedin",
        "greenhouse.io": "greenhouse",
        "ashbyhq.com": "ashby",
        "lever.co": "lever",
        "smartrecruiters.com": "smartrecruiters",
        "myworkdayjobs.com": "workday",
        "indeed.com": "indeed",
    }
    return next((name for suffix, name in providers.items() if hostname.endswith(suffix)), hostname)


def _current_review_candidate(item: object) -> dict[str, Any] | None:
    if not isinstance(item, Mapping):
        return None
    screening = item.get("screening")
    if not isinstance(screening, Mapping) or screening.get("status") != "complete":
        return None
    result = screening.get("result")
    if not isinstance(result, Mapping) or result.get("schema_version") != 4:
        return None
    evidence = result.get("criterion_evidence")
    assessments = result.get("criterion_assessments")
    if not isinstance(evidence, list) or not evidence or not isinstance(assessments, list):
        return None
    assessment_by_id = {
        str(value.get("criterion_id")): value
        for value in assessments
        if isinstance(value, Mapping) and isinstance(value.get("criterion_id"), str)
    }
    criteria: list[dict[str, Any]] = []
    for value in evidence:
        if not isinstance(value, Mapping) or not isinstance(value.get("criterion_id"), str):
            return None
        criterion_id = str(value["criterion_id"])
        assessment = assessment_by_id.get(criterion_id)
        if assessment is None:
            return None
        criteria.append(
            {
                "criterion_id": criterion_id,
                "label": str(value.get("label", criterion_id)),
                "description": str(value.get("description", "")),
                "importance": str(value.get("importance", "required")),
                "requirement_type": str(value.get("requirement_type", "supporting")),
                "relevant_fact_ids": [],
                "allowed_outcomes": [],
                "current_screen": {
                    "retrieval_status": value.get("status"),
                    "retrieved_fact_ids": list(value.get("fact_ids", [])),
                    "outcome": assessment.get("outcome"),
                    "confidence": assessment.get("confidence"),
                    "cited_fact_ids": list(assessment.get("fact_ids", [])),
                    "explanation": assessment.get("explanation"),
                },
            }
        )
    job_id = result.get("job_id")
    if not isinstance(job_id, str):
        return None
    return {
        "job_id": job_id,
        "title": str(item.get("title", "Untitled role")),
        "company": str(item.get("company", "Unknown company")),
        "provider": _provider_name(item.get("url")),
        "source_order": int(item.get("source_order", 0)),
        "fit": str(result.get("fit")),
        "evidence_coverage": str(result.get("evidence_coverage")),
        "posting_coverage": str(result.get("posting_coverage")),
        "current_screen": {
            "eligibility": result.get("eligibility"),
            "fit": result.get("fit"),
            "recommendation": result.get("recommendation"),
            "confidence": result.get("confidence"),
            "abstained": result.get("fit") == FitOutcome.INSUFFICIENT_INFORMATION.value
            or result.get("recommendation") == Recommendation.NEEDS_MORE_EVIDENCE.value,
        },
        "criteria": criteria,
    }


def _balanced_candidates(candidates: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    """Round-robin provider/fit strata so common feeds cannot consume the review set."""
    strata: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for candidate in candidates:
        strata[(candidate["provider"], candidate["fit"])].append(candidate)
    for values in strata.values():
        values.sort(
            key=lambda value: (
                value["evidence_coverage"],
                value["posting_coverage"],
                value["source_order"],
                value["job_id"],
            )
        )
    ordered_keys = sorted(strata, key=lambda key: (-len(strata[key]), key))
    selected: list[dict[str, Any]] = []
    while ordered_keys and len(selected) < limit:
        remaining: list[tuple[str, str]] = []
        for key in ordered_keys:
            if len(selected) >= limit:
                break
            values = strata[key]
            if values:
                selected.append(values.pop(0))
            if values:
                remaining.append(key)
        ordered_keys = remaining
    return selected


def prepare_screening_review(queue: Mapping[str, Any], *, limit: int = 30) -> dict[str, Any]:
    """Create an explicitly unlabeled review worksheet from current structured screens."""
    if not 1 <= limit <= 100:
        raise ValueError("screening review limit must be from 1 to 100")
    jobs = queue.get("jobs")
    if not isinstance(jobs, list):
        raise ValueError("screening queue must contain a jobs list")
    candidates = [candidate for item in jobs if (candidate := _current_review_candidate(item))]
    if not candidates:
        raise ValueError(
            "no current criterion-level screens are available; regenerate screens before "
            "preparing calibration cases"
        )
    selected = _balanced_candidates(candidates, min(limit, len(candidates)))
    cases: list[dict[str, Any]] = []
    for index, candidate in enumerate(selected, start=1):
        cases.append(
            {
                "version": 1,
                "id": f"case-{index:03d}",
                "job_id": candidate["job_id"],
                "job_title": candidate["title"],
                "company": candidate["company"],
                "provider": candidate["provider"],
                "expected_fit": None,
                "should_abstain": None,
                "current_screen": candidate["current_screen"],
                "criteria": candidate["criteria"],
            }
        )
    return {
        "version": 1,
        "status": "needs-human-review",
        "instructions": [
            "Review the posting criterion and canonical facts, not the model explanation alone.",
            "Fill should_abstain, optional expected_fit, relevant_fact_ids, and allowed_outcomes.",
            "Use an empty relevant_fact_ids list only when no confirmed vault fact is relevant.",
            "Run screen-eval finalize before evaluating; current_screen fields are context, not truth.",
        ],
        "allowed_criterion_outcomes": [value.value for value in CriterionAssessmentOutcome],
        "summary": {
            "available_current_screens": len(candidates),
            "selected_cases": len(cases),
            "skipped_stale_or_incomplete": len(jobs) - len(candidates),
        },
        "selection": {
            "method": "round-robin-provider-and-fit",
            "dimensions": [
                "provider",
                "fit",
                "evidence_coverage",
                "posting_coverage",
                "source_order",
            ],
        },
        "cases": cases,
    }


def finalize_screening_review(review: Mapping[str, Any]) -> dict[str, Any]:
    """Strip model context only after every selected case has explicit human labels."""
    raw_cases = review.get("cases")
    if not isinstance(raw_cases, list) or not raw_cases:
        raise ValueError("screening review must contain at least one case")
    finalized: list[dict[str, Any]] = []
    for raw_case in raw_cases:
        if not isinstance(raw_case, Mapping):
            raise ValueError("screening review contains an invalid case")
        if not isinstance(raw_case.get("should_abstain"), bool):
            raise ValueError(f"{raw_case.get('id', 'case')} still needs human review")
        raw_criteria = raw_case.get("criteria")
        if not isinstance(raw_criteria, list):
            raise ValueError(f"{raw_case.get('id', 'case')} has invalid criteria")
        criteria: list[dict[str, Any]] = []
        for criterion in raw_criteria:
            if not isinstance(criterion, Mapping) or not criterion.get("allowed_outcomes"):
                raise ValueError(
                    f"{raw_case.get('id', 'case')} still needs human review for every criterion"
                )
            criteria.append(
                {
                    "criterion_id": criterion.get("criterion_id"),
                    "relevant_fact_ids": criterion.get("relevant_fact_ids", []),
                    "allowed_outcomes": criterion.get("allowed_outcomes"),
                }
            )
        case_payload = {
            "version": raw_case.get("version", 1),
            "id": raw_case.get("id"),
            "job_id": raw_case.get("job_id"),
            "expected_fit": raw_case.get("expected_fit"),
            "should_abstain": raw_case.get("should_abstain"),
            "criteria": criteria,
        }
        finalized.append(
            ScreeningEvaluationCase.model_validate(case_payload).model_dump(mode="json")
        )
    return {"cases": finalized}


def _ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 1.0


def evaluate_screening_results(
    cases: Sequence[ScreeningEvaluationCase],
    results: Mapping[str, Mapping[str, Any]],
) -> ScreeningEvaluationReport:
    """Compare saved screens with human-reviewed facts and outcomes without calling a model."""
    missing_results = 0
    expected_criteria = 0
    assessed_criteria = 0
    agreed_outcomes = 0
    expected_facts = 0
    retrieved_expected_facts = 0
    retrieved_facts = 0
    relevant_retrieved_facts = 0
    abstention_matches = 0
    fit_cases = 0
    fit_matches = 0
    case_results: list[ScreeningEvaluationCaseResult] = []

    for case in cases:
        issues: list[str] = []
        result = results.get(case.job_id)
        if result is None:
            missing_results += 1
            case_results.append(
                ScreeningEvaluationCaseResult(
                    case_id=case.id,
                    job_id=case.job_id,
                    issues=["screening result is missing"],
                )
            )
            continue

        retrieval = {
            str(item.get("criterion_id")): {
                str(fact_id) for fact_id in item.get("fact_ids", []) if isinstance(fact_id, str)
            }
            for item in result.get("criterion_evidence", [])
            if isinstance(item, Mapping)
        }
        assessments = {
            str(item.get("criterion_id")): item
            for item in result.get("criterion_assessments", [])
            if isinstance(item, Mapping)
        }
        for criterion in case.criteria:
            expected_criteria += 1
            assessment = assessments.get(criterion.criterion_id)
            if assessment is None:
                issues.append(f"{criterion.criterion_id}: assessment is missing")
            else:
                assessed_criteria += 1
                if assessment.get("outcome") in {
                    outcome.value for outcome in criterion.allowed_outcomes
                }:
                    agreed_outcomes += 1
                else:
                    issues.append(
                        f"{criterion.criterion_id}: unexpected outcome {assessment.get('outcome')}"
                    )

            expected = set(criterion.relevant_fact_ids)
            actual = retrieval.get(criterion.criterion_id, set())
            expected_facts += len(expected)
            retrieved_expected_facts += len(expected & actual)
            retrieved_facts += len(actual)
            relevant_retrieved_facts += len(expected & actual)
            missed = sorted(expected - actual)
            if missed:
                issues.append(
                    f"{criterion.criterion_id}: missed expected facts {', '.join(missed)}"
                )

        abstained = (
            result.get("fit") == FitOutcome.INSUFFICIENT_INFORMATION.value
            or result.get("recommendation") == Recommendation.NEEDS_MORE_EVIDENCE.value
        )
        if abstained == case.should_abstain:
            abstention_matches += 1
        else:
            issues.append("abstention behavior did not match the reviewed expectation")
        if case.expected_fit is not None:
            fit_cases += 1
            if result.get("fit") == case.expected_fit.value:
                fit_matches += 1
            else:
                issues.append(f"expected fit {case.expected_fit.value}, got {result.get('fit')}")
        case_results.append(
            ScreeningEvaluationCaseResult(case_id=case.id, job_id=case.job_id, issues=issues)
        )

    available_cases = len(cases) - missing_results
    return ScreeningEvaluationReport(
        total_cases=len(cases),
        missing_results=missing_results,
        assessment_coverage=_ratio(assessed_criteria, expected_criteria),
        assessment_outcome_agreement=_ratio(agreed_outcomes, expected_criteria),
        retrieval_recall=_ratio(retrieved_expected_facts, expected_facts),
        retrieval_precision=_ratio(relevant_retrieved_facts, retrieved_facts),
        abstention_accuracy=_ratio(abstention_matches, available_cases),
        fit_agreement=_ratio(fit_matches, fit_cases) if fit_cases else None,
        cases=case_results,
    )


def _load_cases(path: Path) -> list[ScreeningEvaluationCase]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    values = raw.get("cases") if isinstance(raw, dict) else raw
    if not isinstance(values, list):
        raise ValueError("screening evaluation cases must be a JSON list or a cases object")
    return [ScreeningEvaluationCase.model_validate(item) for item in values]


def _load_results(path: Path) -> dict[str, Mapping[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    values: object
    if isinstance(raw, dict) and isinstance(raw.get("jobs"), list):
        values = [
            screening["result"]
            for item in raw["jobs"]
            if isinstance(item, Mapping)
            and isinstance((screening := item.get("screening")), Mapping)
            and screening.get("status") == "complete"
            and isinstance(screening.get("result"), Mapping)
        ]
    else:
        values = raw.get("results") if isinstance(raw, dict) else raw
    if not isinstance(values, list):
        raise ValueError(
            "screening evaluation results must be a JSON list, a results object, or a screening queue"
        )
    results: dict[str, Mapping[str, Any]] = {}
    for item in values:
        if not isinstance(item, Mapping) or not isinstance(item.get("job_id"), str):
            raise ValueError("every screening evaluation result must contain a job_id")
        results[str(item["job_id"])] = item
    return results


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments and arguments[0] == "prepare":
        parser = argparse.ArgumentParser(prog="resume-builder screen-eval prepare")
        parser.add_argument("command")
        parser.add_argument("results", type=Path)
        parser.add_argument("output", type=Path)
        parser.add_argument("--limit", type=int, default=30)
        args = parser.parse_args(arguments)
        raw = json.loads(args.results.read_text(encoding="utf-8"))
        if not isinstance(raw, Mapping):
            raise ValueError("screening queue must be a JSON object")
        review = prepare_screening_review(raw, limit=args.limit)
        atomic_write_json(args.output, review)
        print(json.dumps(review["summary"], indent=2))
        return 0
    if arguments and arguments[0] == "finalize":
        parser = argparse.ArgumentParser(prog="resume-builder screen-eval finalize")
        parser.add_argument("command")
        parser.add_argument("review", type=Path)
        parser.add_argument("output", type=Path)
        args = parser.parse_args(arguments)
        raw = json.loads(args.review.read_text(encoding="utf-8"))
        if not isinstance(raw, Mapping):
            raise ValueError("screening review must be a JSON object")
        finalized = finalize_screening_review(raw)
        atomic_write_json(args.output, finalized)
        print(json.dumps({"finalized_cases": len(finalized["cases"])}, indent=2))
        return 0
    parser = argparse.ArgumentParser(prog="resume-builder screen-eval")
    parser.add_argument("cases", type=Path)
    parser.add_argument("results", type=Path)
    args = parser.parse_args(arguments)
    report = evaluate_screening_results(_load_cases(args.cases), _load_results(args.results))
    print(report.model_dump_json(indent=2))
    return 0
