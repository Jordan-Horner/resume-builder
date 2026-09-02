from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "evals" / "summary-positioning.yaml"


def test_summary_positioning_evaluation_matrix_is_complete_and_public_safe() -> None:
    value = yaml.safe_load(CASES.read_text(encoding="utf-8"))

    assert value["version"] == 1
    assert value["kind"] == "summary-positioning"
    assert value["method"] == "independent-cold-review"
    assert "fresh reviewer" in value["pass_condition"]

    cases = value["cases"]
    assert len(cases) >= 10
    assert len({case["id"] for case in cases}) == len(cases)
    assert {case["target_mode"] for case in cases} == {"direct", "adjacent", "exploratory"}
    assert {case["expected_decision"] for case in cases} == {"approved", "revise"}

    required_scenarios = {
        "direct-adjacent-title",
        "single-substantial-project",
        "adjacent-bridge",
        "adjacent-unsupported-title",
        "exploratory-proof-led",
        "broad-role-false-positive",
        "qualifying-education",
        "unsupported-target-identity",
        "summary-inventory",
    }
    assert required_scenarios <= {case["scenario"] for case in cases}

    serialized = CASES.read_text(encoding="utf-8").casefold()
    assert "http://" not in serialized
    assert "https://" not in serialized
    assert "/users/" not in serialized
    assert "file://" not in serialized
    assert "@" not in serialized

    for case in cases:
        assert case["target"].strip()
        assert case["formal_title"].strip()
        assert case["opening"].strip()
        assert case["review_reason"].strip()
        assert case["evidence_profile"]
        assert all(item.strip() for item in case["evidence_profile"])


def test_single_substantial_project_does_not_require_repetition() -> None:
    value = yaml.safe_load(CASES.read_text(encoding="utf-8"))
    case = next(item for item in value["cases"] if item["scenario"] == "single-substantial-project")

    assert len(case["evidence_profile"]) == 1
    assert case["expected_decision"] == "approved"
    assert "without repeated projects" in case["review_reason"]
