"""Bounded, private retrieval of canonical evidence for quick job screens."""

from __future__ import annotations

from pathlib import Path

import resume_builder.jobs as jobs_module
from resume_builder.jobs import get_job_screening_packet
from resume_builder.posting_interpretation import (
    PostingCriterion,
    PostingInterpretation,
    SectionReview,
)
from resume_builder.screening_evidence import (
    MAX_CRITERION_EVIDENCE_CARDS,
    MAX_EVIDENCE_CARDS,
    MAX_EVIDENCE_CHARACTERS,
    CriterionEvidenceStatus,
    EvidenceCoverage,
    EvidenceStrategy,
    EvidenceStrength,
    select_criterion_screening_evidence,
    select_screening_evidence,
)
from resume_builder.workspace import initialize_workspace


def _fact(
    root: Path,
    fact_id: str,
    *,
    title: str,
    body: str,
    category: str = "employment",
    fact_type: str = "responsibility",
    status: str = "confirmed",
    organization: str | None = None,
    themes: tuple[str, ...] = ("production",),
) -> None:
    folder = root / "vault" / "facts" / category
    if organization:
        folder /= organization
    folder.mkdir(parents=True, exist_ok=True)
    organization_line = f"organization: {organization}\n" if organization else ""
    (folder / f"{fact_id}.md").write_text(
        "---\n"
        "schema_version: 2\n"
        f"id: {fact_id}\n"
        f'title: "{title}"\n'
        f"type: {fact_type}\n"
        f"status: {status}\n"
        f"category: {category}\n"
        f"{organization_line}"
        "sources:\n"
        "  - SRC-000000000001\n"
        "themes:\n" + "".join(f"  - {theme}\n" for theme in themes) + "---\n\n"
        f"# {title}\n\n{body}\n",
        encoding="utf-8",
    )


def _job(**overrides: object) -> dict[str, object]:
    return {
        "id": "job-1",
        "title": "Production Reliability Engineer",
        "company": "Example",
        "description_text": (
            "Operate production Kubernetes services, automate incident response in Python, "
            "and improve cloud reliability."
        ),
        **overrides,
    }


def _interpretation(*criteria: PostingCriterion) -> PostingInterpretation:
    return PostingInterpretation(
        criteria=list(criteria),
        section_reviews=[
            SectionReview(section_id="section-1", disposition="criteria", reason="Role criteria")
        ],
        criteria_complete=True,
    )


def _criterion(
    criterion_id: str,
    label: str,
    terms: list[str],
    *,
    importance: str = "required",
    resume_evaluable: bool = True,
) -> PostingCriterion:
    return PostingCriterion(
        id=criterion_id,
        label=label,
        description=f"Evidence for {label}.",
        importance=importance,
        basis="core_responsibility" if importance == "required" else "preference",
        requirement_type="mandatory-role-defining" if importance == "required" else "preferred",
        resume_evaluable=resume_evaluable,
        source_unit_ids=["section-1-unit-1"],
        source_section_id="section-1",
        source_excerpt=f"The role requires {label}.",
        retrieval_terms=terms,
        confidence="high",
    )


def test_criterion_retrieval_is_balanced_and_exposes_exact_fact_mappings(tmp_path: Path) -> None:
    initialize_workspace(tmp_path, git_name="Example", git_email="example@example.invalid")
    _fact(
        tmp_path,
        "KUBE-001",
        title="Kubernetes production operations",
        body="Operated Kubernetes services in production and restored failed workloads.",
        organization="example",
    )
    _fact(
        tmp_path,
        "PYTHON-001",
        title="Python incident automation",
        body="Built Python automation for incident response and recovery workflows.",
        organization="example",
    )
    _fact(
        tmp_path,
        "KUBE-002",
        title="Kubernetes deployment support",
        body="Supported Kubernetes deployment and production troubleshooting.",
        organization="example",
    )
    interpretation = _interpretation(
        _criterion("kubernetes", "Kubernetes operations", ["Kubernetes", "production"]),
        _criterion("automation", "Python automation", ["Python", "automation"]),
    )

    selection = select_criterion_screening_evidence(tmp_path / "vault", _job(), interpretation)

    assert selection.strategy == EvidenceStrategy.CRITERION_DRIVEN
    assert len(selection.cards) <= MAX_CRITERION_EVIDENCE_CARDS
    matches = {match.criterion_id: match for match in selection.criterion_matches}
    assert "KUBE-001" in matches["kubernetes"].fact_ids
    assert "PYTHON-001" in matches["automation"].fact_ids
    assert matches["kubernetes"].status == CriterionEvidenceStatus.DEMONSTRATED_CANDIDATE
    assert matches["automation"].status == CriterionEvidenceStatus.DEMONSTRATED_CANDIDATE
    assert selection.coverage == EvidenceCoverage.GOOD


def test_criterion_retrieval_does_not_pad_with_unrelated_foundation_facts(tmp_path: Path) -> None:
    initialize_workspace(tmp_path, git_name="Example", git_email="example@example.invalid")
    _fact(
        tmp_path,
        "UNRELATED-001",
        title="Production operations support",
        body="Supported production scheduling for restaurant menus and kitchen inventory.",
        organization="example",
    )
    interpretation = _interpretation(
        _criterion("kubernetes", "Kubernetes operations", ["Kubernetes"])
    )

    selection = select_criterion_screening_evidence(tmp_path / "vault", _job(), interpretation)

    assert selection.cards == []
    assert selection.coverage == EvidenceCoverage.LOW
    assert selection.criterion_matches[0].status == CriterionEvidenceStatus.NO_CANDIDATE_EVIDENCE
    assert selection.criterion_matches[0].fact_ids == []


def test_single_term_retrieval_uses_token_boundaries(tmp_path: Path) -> None:
    initialize_workspace(tmp_path, git_name="Example", git_email="example@example.invalid")
    _fact(
        tmp_path,
        "CAPITAL-001",
        title="Capital planning",
        body="Prepared capital forecasts and annual budgets.",
        organization="example",
    )
    interpretation = _interpretation(_criterion("apis", "API development", ["API"]))

    selection = select_criterion_screening_evidence(tmp_path / "vault", _job(), interpretation)

    assert selection.cards == []
    assert selection.coverage == EvidenceCoverage.LOW


def test_non_resume_evaluable_criteria_are_acknowledged_but_never_retrieve_facts(
    tmp_path: Path,
) -> None:
    initialize_workspace(tmp_path, git_name="Example", git_email="example@example.invalid")
    _fact(
        tmp_path,
        "TRAVEL-001",
        title="Travel support",
        body="Traveled to customer sites for implementation support.",
        organization="example",
    )
    lifestyle = _criterion(
        "travel", "Travel up to 25 percent", ["travel"], resume_evaluable=False
    ).model_copy(update={"basis": "lifestyle", "requirement_type": "lifestyle"})
    interpretation = _interpretation(lifestyle)

    selection = select_criterion_screening_evidence(tmp_path / "vault", _job(), interpretation)

    assert selection.cards == []
    assert selection.criterion_matches[0].status == CriterionEvidenceStatus.NOT_RESUME_EVALUABLE


def test_career_stage_criteria_retrieve_oldest_and_newest_confirmed_roles(
    tmp_path: Path,
) -> None:
    initialize_workspace(tmp_path, git_name="Example", git_email="example@example.invalid")
    _fact(
        tmp_path,
        "ROLE-OLD",
        title="Support Associate",
        body="Support Associate from 2013 through 2015.",
        fact_type="role",
        organization="first-company",
    )
    _fact(
        tmp_path,
        "ROLE-NEW",
        title="Production Engineering Lead",
        body="Production Engineering Lead from 2024 through 2026.",
        fact_type="role",
        organization="current-company",
    )
    interpretation = _interpretation(
        _criterion(
            "career-stage",
            "1\u20133 years of relevant experience for a campus hire",
            ["campus hire", "relevant experience"],
        )
    )

    selection = select_criterion_screening_evidence(tmp_path / "vault", _job(), interpretation)

    match = selection.criterion_matches[0]
    assert match.fact_ids == ["ROLE-NEW", "ROLE-OLD"]
    assert match.status == CriterionEvidenceStatus.DEMONSTRATED_CANDIDATE


def test_selection_uses_confirmed_vault_evidence_without_private_profile_data(
    tmp_path: Path,
) -> None:
    initialize_workspace(tmp_path, git_name="Example", git_email="example@example.invalid")
    _fact(
        tmp_path,
        "OPS-001",
        title="Production incident automation",
        body="Built Python workflows for production incident response and Kubernetes recovery.",
        organization="example",
    )
    _fact(
        tmp_path,
        "SKILL-001",
        title="Systems and cloud",
        body="AWS, Kubernetes, Linux, networking, and production operations.",
        category="skills",
    )
    _fact(
        tmp_path,
        "OPS-002",
        title="Unverified AI claim",
        body="Used every frontier model in production.",
        status="needs-review",
        organization="example",
    )
    _fact(
        tmp_path,
        "PROFILE-001",
        title="Contact details",
        body="example@example.com and 561-555-0100",
        category="profile",
    )

    selection = select_screening_evidence(tmp_path / "vault", _job())

    assert {card.fact_id for card in selection.cards} == {"OPS-001", "SKILL-001"}
    assert selection.cards[0].fact_id == "OPS-001"
    assert selection.cards[0].strength == EvidenceStrength.DEMONSTRATED
    assert selection.coverage in {EvidenceCoverage.PARTIAL, EvidenceCoverage.GOOD}
    rendered = selection.model_dump_json()
    assert "example@example.com" not in rendered
    assert "561-555-0100" not in rendered
    assert "Unverified AI claim" not in rendered


def test_selection_ranks_full_fact_but_sends_only_a_bounded_excerpt(tmp_path: Path) -> None:
    initialize_workspace(tmp_path, git_name="Example", git_email="example@example.invalid")
    _fact(
        tmp_path,
        "OPS-LATE",
        title="Maintenance practice",
        body=("General context without matching terminology. " * 30)
        + "Implemented Kubernetes recovery automation for production incidents.",
    )

    selection = select_screening_evidence(tmp_path / "vault", _job())

    selected = next(card for card in selection.cards if card.fact_id == "OPS-LATE")
    assert "Kubernetes" not in selected.excerpt
    assert len(selected.excerpt) <= 350


def test_selection_is_bounded_and_diverse(tmp_path: Path) -> None:
    initialize_workspace(tmp_path, git_name="Example", git_email="example@example.invalid")
    for index in range(30):
        _fact(
            tmp_path,
            f"OPS-{index + 1:03d}",
            title=f"Production Kubernetes incident response {index}",
            body=("Operated Kubernetes production services and automated incident response. " * 20),
            organization="example",
        )
    _fact(
        tmp_path,
        "PROJ-001",
        title="Python reliability service",
        body="Built a Python API for production reliability workflows.",
        category="projects",
        fact_type="project",
    )
    _fact(
        tmp_path,
        "SKILL-001",
        title="Cloud platforms",
        body="AWS, Kubernetes, Python, and Linux.",
        category="skills",
    )

    selection = select_screening_evidence(tmp_path / "vault", _job())

    assert len(selection.cards) <= MAX_EVIDENCE_CARDS
    assert selection.candidate_characters <= MAX_EVIDENCE_CHARACTERS
    assert {card.category for card in selection.cards} >= {"employment", "projects", "skills"}
    assert sum(card.category == "employment" for card in selection.cards) <= 10


def test_unrelated_fact_does_not_change_selected_evidence_revision(tmp_path: Path) -> None:
    initialize_workspace(tmp_path, git_name="Example", git_email="example@example.invalid")
    _fact(
        tmp_path,
        "OPS-001",
        title="Production incident response",
        body="Handled Kubernetes production incidents and automated recovery in Python.",
        organization="example",
    )
    first = select_screening_evidence(tmp_path / "vault", _job())

    _fact(
        tmp_path,
        "CERT-001",
        title="Unrelated culinary certificate",
        body="Completed a culinary fundamentals course.",
        category="certifications",
        fact_type="accomplishment",
        themes=("culinary",),
    )
    second = select_screening_evidence(tmp_path / "vault", _job())

    assert second.evidence_revision == first.evidence_revision
    assert [card.fact_id for card in second.cards] == [card.fact_id for card in first.cards]


def test_empty_vault_returns_low_coverage_without_inventing_evidence(tmp_path: Path) -> None:
    initialize_workspace(tmp_path, git_name="Example", git_email="example@example.invalid")

    selection = select_screening_evidence(tmp_path / "vault", _job())

    assert selection.cards == []
    assert selection.coverage == EvidenceCoverage.LOW
    assert selection.evidence_revision


def test_shared_screening_packet_retrieves_evidence_from_the_workspace_vault(
    tmp_path: Path, monkeypatch
) -> None:
    initialize_workspace(tmp_path, git_name="Example", git_email="example@example.invalid")
    _fact(
        tmp_path,
        "OPS-001",
        title="Production incident automation",
        body="Built Python workflows for production incident response.",
        organization="example",
    )
    preferences = tmp_path / "preferences.yml"
    preferences.write_text(
        "schema_version: 1\naccepted_work_modes: [remote]\n",
        encoding="utf-8",
    )

    class Inventory:
        def active_inventory(self):
            return [
                {
                    **_job(),
                    "location": "USA - Remote",
                    "work_modes": ["remote"],
                    "description_quality": "complete",
                    "url": "https://example.invalid/job-1",
                }
            ]

    monkeypatch.setattr(jobs_module, "_database", lambda _path: Inventory())

    packet = get_job_screening_packet(
        "job-1",
        config_path=tmp_path / "search.yml",
        preferences_path=preferences,
        workspace=tmp_path,
    )

    assert packet.schema_version == 5
    assert packet.candidate_evidence[0].fact_id == "OPS-001"
    assert packet.evidence_coverage == EvidenceCoverage.PARTIAL
    assert packet.profile.supported_capabilities == []
