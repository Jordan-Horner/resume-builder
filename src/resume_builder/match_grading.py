"""Validate semantic job-match judgments and classify screening fit."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .directions import nonempty_string, string_list
from .rendering import object_value

CASE_FIELDS = {"version", "evidence_complete", "criteria"}
JUDGMENT_FIELDS = {
    "criterion_id",
    "importance",
    "requirement_type",
    "status",
    "evidence_sufficiency",
    "confidence",
    "evidence_blocks",
    "evidence_fact_ids",
    "substitution_basis",
    "gap",
}
IMPORTANCE = {"required", "preferred"}
REQUIREMENT_TYPES = {
    "mandatory-role-defining",
    "mandatory-substitutable",
    "supporting",
    "preferred",
    "lifestyle",
}
STATUSES = {"met", "partial", "not_met", "undecidable"}
SUFFICIENCY = {"high", "medium", "low"}
MATCH_LABELS = {"Strong match", "Partial match", "Weak match", "Unknown match"}


def load_classification_case(path: Path) -> dict[str, Any]:
    """Read one transient or persisted semantic classification case."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"cannot read match classification case: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid match classification JSON: {exc}") from exc
    return object_value(data, "match classification case")


def _string_items(value: object, field: str) -> list[str]:
    if value == []:
        return []
    return string_list(value, field)


def validate_classification_case(case: dict[str, Any]) -> list[dict[str, Any]]:
    """Validate a complete criterion matrix without assigning a score."""
    if unexpected := sorted(set(case) - CASE_FIELDS):
        raise ValueError(f"match classification case contains unsupported fields: {unexpected}")
    if case.get("version") != 1:
        raise ValueError("match classification case must declare version 1")
    if not isinstance(case.get("evidence_complete"), bool):
        raise ValueError("match classification evidence_complete must be a boolean")
    raw_criteria = case.get("criteria")
    if not isinstance(raw_criteria, list) or not raw_criteria:
        raise ValueError("match classification criteria must be a non-empty list")

    criteria: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_criteria):
        item = object_value(raw, f"criteria[{index}]")
        if unexpected := sorted(set(item) - JUDGMENT_FIELDS):
            raise ValueError(f"criteria[{index}] contains unsupported fields: {unexpected}")
        missing = sorted(JUDGMENT_FIELDS - set(item))
        if missing:
            raise ValueError(f"criteria[{index}] missing fields: {missing}")
        criterion_id = nonempty_string(item.get("criterion_id"), f"criteria[{index}].criterion_id")
        if criterion_id in seen:
            raise ValueError(f"duplicate classification criterion: {criterion_id}")
        seen.add(criterion_id)

        importance = nonempty_string(item.get("importance"), f"criteria[{index}].importance")
        if importance not in IMPORTANCE:
            raise ValueError(f"criteria[{index}].importance must be one of {sorted(IMPORTANCE)}")
        requirement_type = nonempty_string(
            item.get("requirement_type"), f"criteria[{index}].requirement_type"
        )
        if requirement_type not in REQUIREMENT_TYPES:
            raise ValueError(
                f"criteria[{index}].requirement_type must be one of {sorted(REQUIREMENT_TYPES)}"
            )
        if importance == "preferred" and requirement_type not in {"preferred", "lifestyle"}:
            raise ValueError(
                f"criteria[{index}] preferred importance requires preferred or lifestyle type"
            )
        if importance == "required" and requirement_type == "preferred":
            raise ValueError(f"criteria[{index}] required importance cannot use preferred type")

        status = nonempty_string(item.get("status"), f"criteria[{index}].status")
        if status not in STATUSES:
            raise ValueError(f"criteria[{index}].status must be one of {sorted(STATUSES)}")
        sufficiency = nonempty_string(
            item.get("evidence_sufficiency"), f"criteria[{index}].evidence_sufficiency"
        )
        if sufficiency not in SUFFICIENCY:
            raise ValueError(
                f"criteria[{index}].evidence_sufficiency must be one of {sorted(SUFFICIENCY)}"
            )
        confidence = nonempty_string(item.get("confidence"), f"criteria[{index}].confidence")
        if confidence not in SUFFICIENCY:
            raise ValueError(f"criteria[{index}].confidence must be one of {sorted(SUFFICIENCY)}")
        blocks = _string_items(item.get("evidence_blocks"), f"criteria[{index}].evidence_blocks")
        fact_ids = _string_items(
            item.get("evidence_fact_ids"), f"criteria[{index}].evidence_fact_ids"
        )
        gap = item.get("gap")
        if not isinstance(gap, str):
            raise ValueError(f"criteria[{index}].gap must be a string")
        substitution_basis = item.get("substitution_basis")
        if not isinstance(substitution_basis, str):
            raise ValueError(f"criteria[{index}].substitution_basis must be a string")
        if requirement_type == "mandatory-substitutable" and not substitution_basis.strip():
            raise ValueError(
                f"criteria[{index}] mandatory-substitutable type requires the posting's explicit substitution basis"
            )
        if requirement_type != "mandatory-substitutable" and substitution_basis.strip():
            raise ValueError(
                f"criteria[{index}] substitution_basis is allowed only for mandatory-substitutable requirements"
            )
        if status in {"met", "partial"} and (not blocks or not fact_ids):
            raise ValueError(
                f"criteria[{index}] {status} status requires evidence blocks and fact IDs"
            )
        if status != "met" and not gap.strip():
            raise ValueError(f"criteria[{index}] {status} status requires a concrete gap")
        if status == "met" and gap.strip():
            raise ValueError(f"criteria[{index}] met status must not declare a gap")
        criteria.append(
            {
                **item,
                "evidence_blocks": blocks,
                "evidence_fact_ids": fact_ids,
                "substitution_basis": substitution_basis.strip(),
                "gap": gap.strip(),
            }
        )

    if not any(item["importance"] == "required" for item in criteria):
        raise ValueError("match classification must include at least one required criterion")
    return criteria


def classify_match(case: dict[str, Any]) -> dict[str, Any]:
    """Apply the shared gate-first screen and detailed-match policy."""
    criteria = validate_classification_case(case)
    required = [item for item in criteria if item["importance"] == "required"]
    incomplete = [item["criterion_id"] for item in required if item["status"] == "undecidable"]
    gate_failures = [
        item["criterion_id"]
        for item in required
        if item["requirement_type"] in {"mandatory-role-defining", "mandatory-substitutable"}
        and item["status"] in {"not_met", "undecidable"}
    ]
    required_gaps = [
        item["criterion_id"]
        for item in required
        if item["requirement_type"] != "lifestyle" and item["status"] != "met"
    ]
    lifestyle_risks = [
        item["criterion_id"]
        for item in criteria
        if item["requirement_type"] == "lifestyle" and item["status"] != "met"
    ]
    preferred_gaps = [
        item["criterion_id"]
        for item in criteria
        if item["importance"] == "preferred" and item["status"] != "met"
    ]

    if not case["evidence_complete"] and incomplete:
        label = "Unknown match"
        controlling = incomplete
        reason = "Required evidence is incomplete, so the match cannot be classified defensibly."
    elif gate_failures:
        label = "Weak match"
        controlling = gate_failures
        reason = "A mandatory role-defining or accepted-substitute requirement is unsupported."
    elif required_gaps:
        label = "Partial match"
        controlling = required_gaps
        reason = "Required work is only partially demonstrated or has a supporting evidence gap."
    else:
        label = "Strong match"
        controlling = []
        reason = "Every resume-evaluable required criterion is directly demonstrated."

    return {
        "version": 1,
        "method": (
            "shared gate-first semantic classification; this is not an ATS score, interview "
            "probability, or employer decision prediction"
        ),
        "label": label,
        "reason": reason,
        "evidence_complete": case["evidence_complete"],
        "controlling_criterion_ids": controlling,
        "gate_failure_ids": gate_failures,
        "required_gap_ids": required_gaps,
        "lifestyle_risk_ids": lifestyle_risks,
        "preferred_gap_ids": preferred_gaps,
        "criteria": criteria,
    }


def validate_against_match(classification: dict[str, Any], match_result: dict[str, Any]) -> None:
    """Pin a classification to the complete target criteria and cited resume evidence."""
    expected = {
        str(item["id"]): str(item["importance"])
        for item in match_result["target"]["criteria"]
        if item.get("resume_evaluable") is True
    }
    actual = {
        str(item["criterion_id"]): str(item["importance"]) for item in classification["criteria"]
    }
    if actual != expected:
        missing = sorted(set(expected) - set(actual))
        unknown = sorted(set(actual) - set(expected))
        mismatched = sorted(
            criterion_id
            for criterion_id in set(actual) & set(expected)
            if actual[criterion_id] != expected[criterion_id]
        )
        raise ValueError(
            "classification must cover every resume-evaluable target criterion exactly once: "
            f"missing={missing}, unknown={unknown}, importance_mismatch={mismatched}"
        )
    resume_fact_ids = set(match_result["resume"]["audit"]["fact_ids"])
    cited = {
        fact_id for item in classification["criteria"] for fact_id in item["evidence_fact_ids"]
    }
    if unknown_facts := sorted(cited - resume_fact_ids):
        raise ValueError(
            f"classification cites fact IDs not present in the matched resume: {unknown_facts}"
        )
