from __future__ import annotations

import json
from pathlib import Path

from resume_builder import evidence
from resume_builder.synthesis import ClaimEvidence, ClaimSpec


def write_fact(vault: Path, *, status: str = "confirmed", body: str) -> None:
    facts = vault / "facts" / "profile"
    facts.mkdir(parents=True)
    (vault / "employment").mkdir(exist_ok=True)
    (vault / "vault.json").write_text(
        json.dumps(
            {
                "schema_version": 2,
                "facts_path": "facts",
                "employment_path": "employment",
                "sources_manifest": "sources/manifest.json",
            }
        ),
        encoding="utf-8",
    )
    (facts / "FACT-001.md").write_text(
        f"""---
schema_version: 2
id: FACT-001
title: Customer incident investigation
type: accomplishment
status: {status}
category: profile
sources:
  - SRC-0123456789ab
themes:
  - incident-response
---

{body}
""",
        encoding="utf-8",
    )


def test_grounding_audit_flags_lexically_unsupported_nonnumeric_claim(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    write_fact(
        vault,
        body="Resolved a customer incident and documented reproduction steps.",
    )
    payload = {
        "summary": "Global EKS transformation spanning regulated estates.",
        "summary_evidence": ["FACT-001"],
    }

    result = evidence.audit_claims(payload, vault)

    assert result["semantic_entailment_checked"] is False
    assert any("low lexical support" in warning for warning in result["warnings"])


def test_grounding_audit_rejects_unresolved_facts(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    write_fact(vault, status="needs-review", body="An older resume makes an unresolved claim.")
    payload = {
        "summary": "Improved customer incident investigations.",
        "summary_evidence": ["FACT-001"],
    }

    try:
        evidence.audit_claims(payload, vault)
    except ValueError as error:
        assert "relies on unresolved facts" in str(error)
    else:
        raise AssertionError("needs-review evidence must not compile into visible claims")


def test_grounding_audit_rejects_inflated_authorship_verb(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    write_fact(vault, body="Used the diagnostic workflow on real support tickets.")
    payload = {
        "experience": [
            {
                "company": "Example",
                "role": "Engineer",
                "dates": "",
                "location": "Remote",
                "evidence": ["FACT-001"],
                "bullets": [
                    {
                        "text": "Created a diagnostic workflow for support tickets.",
                        "evidence": ["FACT-001"],
                    }
                ],
            }
        ]
    }

    try:
        evidence.audit_claims(payload, vault)
    except ValueError as error:
        assert "authorship or authority" in str(error)
        assert "created" in str(error)
    else:
        raise AssertionError("unsupported authorship must not pass grounding")


def test_grounding_audit_accepts_explicit_authorship(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    write_fact(vault, body="Created a diagnostic workflow for support tickets.")
    payload = {
        "summary": "Created a diagnostic workflow for support tickets.",
        "summary_evidence": ["FACT-001"],
    }

    result = evidence.audit_claims(payload, vault)

    assert result["fact_ids_checked"] == 1


def test_grounding_audit_accepts_owned_when_fact_establishes_ownership(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    write_fact(
        vault,
        body="Held sole technical ownership and served as maintainer of the application.",
    )
    payload = {
        "summary": "Owned and maintained the application.",
        "summary_evidence": ["FACT-001"],
    }

    result = evidence.audit_claims(payload, vault)

    assert result["fact_ids_checked"] == 1


def test_grounding_audit_does_not_treat_system_behavior_as_candidate_authorship(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    write_fact(
        vault,
        body=("Built alert automation that responded with remediation steps or ticket creation."),
    )
    payload = {
        "summary": "Built alert automation that launched remediation or ticket workflows.",
        "summary_evidence": ["FACT-001"],
    }

    result = evidence.audit_claims(payload, vault)

    assert result["fact_ids_checked"] == 1


def test_grounding_audit_warns_on_low_information_leading_verb(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    write_fact(vault, body="Used a diagnostic workflow to resolve support tickets.")
    payload = {
        "experience": [
            {
                "company": "Example",
                "role": "Engineer",
                "dates": "",
                "location": "Remote",
                "evidence": ["FACT-001"],
                "bullets": [
                    {
                        "text": "Used a diagnostic workflow to resolve support tickets.",
                        "evidence": ["FACT-001"],
                    }
                ],
            }
        ]
    }

    result = evidence.audit_claims(payload, vault)

    assert any("low-information verb 'Used'" in warning for warning in result["warnings"])


def test_structured_claim_prevents_cross_fact_authorship_laundering(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    write_fact(vault, body="Built an unrelated reporting dashboard.")
    second = vault / "facts" / "profile" / "FACT-002.md"
    second.write_text(
        (vault / "facts" / "profile" / "FACT-001.md")
        .read_text(encoding="utf-8")
        .replace("FACT-001", "FACT-002")
        .replace(
            "Built an unrelated reporting dashboard.",
            "A diagnostic workflow was available for support tickets.",
        ),
        encoding="utf-8",
    )
    payload = {
        "experience": [
            {
                "company": "Example",
                "role": "Engineer",
                "dates": "Current",
                "evidence": ["FACT-001"],
                "bullets": [
                    {
                        "text": "Built a diagnostic workflow for support tickets.",
                        "evidence": ["FACT-001", "FACT-002"],
                        "story": "diagnostic-workflow",
                    }
                ],
            }
        ]
    }
    claim = ClaimSpec(
        subject="candidate",
        action="built",
        object="diagnostic-workflow",
        scope="support-tickets",
        outcome=None,
        composition="aggregate",
        relationship="The facts cover separate action and object evidence.",
        evidence=ClaimEvidence(
            action=("FACT-002",),
            object=("FACT-002",),
            scope=("FACT-002",),
            outcome=("FACT-001",),
        ),
    )

    try:
        evidence.audit_claims(
            payload,
            vault,
            claim_specs={"diagnostic-workflow": claim},
        )
    except ValueError as error:
        assert "authorship or authority" in str(error)
        assert "built" in str(error)
    else:
        raise AssertionError("an action from another cited fact must not support this claim")
