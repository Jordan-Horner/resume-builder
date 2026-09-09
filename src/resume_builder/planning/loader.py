"""Load and validate versioned synthesis plans against project evidence."""

from __future__ import annotations

from pathlib import Path

import yaml

from ..resume_documents.html import contained_project_path
from ..resume_templates import load_content_template, load_rendering_theme
from .models import (
    COMPETENCY_DECISIONS,
    FIT_STATUSES,
    PAGE_BUDGET_SOURCES,
    RISK_STATUSES,
    STORY_ID,
    TARGET_MODES,
    ConceptFit,
    PageBudget,
    PresentationStrategy,
    ResumeTemplateSelection,
    ReviewerRisk,
    SynthesisPlan,
)
from .role_arcs import parse_role_arcs
from .schema import (
    direction_concept_ids,
    direction_page_budget,
    exact_fields,
    fact_metadata,
    nonempty_string,
    object_value,
    string_list,
)
from .schema import optional_string as optional_string
from .stories import parse_stories
from .summary import parse_summary_strategy


def load_synthesis_plan(path: Path, project_root: Path, vault_root: Path) -> SynthesisPlan:
    """Load and validate one versioned synthesis plan."""
    source = contained_project_path(path, project_root, "resumes/plans", "synthesis plan")
    try:
        raw = yaml.safe_load(source.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(f"invalid synthesis plan {source}: {exc}") from exc
    data = object_value(raw, "synthesis plan")
    version = data.get("version")
    if not isinstance(version, int) or isinstance(version, bool) or version not in range(1, 12):
        raise ValueError("synthesis plan must declare version 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, or 11")
    fields = {
        "version",
        "resume",
        "direction",
        "target_argument",
        "progression",
        "stories",
        "exclusions",
        "gaps",
    }
    if version >= 2:
        fields.update({"summary_job", "summary_fact_ids"})
    if version >= 3:
        fields.update({"target_mode", "concept_fit", "reviewer_risks", "presentation"})
    if version >= 5:
        fields.add("role_arcs")
    if version >= 6:
        fields.add("page_budget")
    if version >= 7:
        fields.add("resume_template")
    if version >= 11:
        fields.add("summary_strategy")
    exact_fields(data, fields, "synthesis plan")

    resume = contained_project_path(
        Path(nonempty_string(data["resume"], "synthesis plan resume")),
        project_root,
        "resumes",
        "synthesis plan resume",
    )
    direction = contained_project_path(
        Path(nonempty_string(data["direction"], "synthesis plan direction")),
        project_root,
        "directions",
        "synthesis plan direction",
    )
    if source.stem != resume.stem:
        raise ValueError("synthesis plan filename must match its resume filename")
    if not direction.is_file():
        raise ValueError(f"synthesis direction does not exist: {direction}")

    page_budget: PageBudget | None = None
    if version >= 6:
        raw_page_budget = object_value(data["page_budget"], "synthesis page_budget")
        exact_fields(raw_page_budget, {"max_pages", "source"}, "synthesis page_budget")
        max_pages = raw_page_budget["max_pages"]
        if not isinstance(max_pages, int) or isinstance(max_pages, bool) or max_pages < 1:
            raise ValueError("synthesis page_budget.max_pages must be a positive integer")
        budget_source = nonempty_string(raw_page_budget["source"], "synthesis page_budget.source")
        if budget_source not in PAGE_BUDGET_SOURCES:
            raise ValueError("synthesis page_budget.source must be direction-default or user")
        if budget_source == "direction-default":
            direction_budget = direction_page_budget(direction)
            if max_pages != direction_budget:
                raise ValueError(
                    "synthesis page budget disagrees with direction default: "
                    f"plan={max_pages}, direction={direction_budget}"
                )
        page_budget = PageBudget(max_pages=max_pages, source=budget_source)

    resume_template: ResumeTemplateSelection | None = None
    if version >= 7:
        raw_template = object_value(data["resume_template"], "synthesis resume_template")
        exact_fields(raw_template, {"content", "theme"}, "synthesis resume_template")
        content_id = nonempty_string(raw_template["content"], "synthesis resume_template.content")
        theme_id = nonempty_string(raw_template["theme"], "synthesis resume_template.theme")
        resume_template = ResumeTemplateSelection(
            content=load_content_template(project_root, content_id),
            theme=load_rendering_theme(project_root, theme_id),
        )

    facts = fact_metadata(vault_root)
    progression = string_list(data["progression"], "synthesis progression")
    unknown_progression = sorted(set(progression) - facts.keys())
    if unknown_progression:
        raise ValueError(f"synthesis progression cites unknown facts: {unknown_progression}")
    non_roles = sorted(fact_id for fact_id in progression if facts[fact_id].get("type") != "role")
    if non_roles:
        raise ValueError(f"synthesis progression must contain role facts: {non_roles}")

    summary_job: str | None = None
    summary_fact_ids: list[str] = []
    summary_body_fact_ids: list[str] = []
    if version >= 2:
        summary_job = nonempty_string(data["summary_job"], "synthesis summary_job")
        summary_fact_ids = string_list(data["summary_fact_ids"], "synthesis summary_fact_ids")
        unknown_summary = sorted(set(summary_fact_ids) - facts.keys())
        if unknown_summary:
            raise ValueError(f"synthesis summary cites unknown facts: {unknown_summary}")
        summary_body_fact_ids = [
            fact_id
            for fact_id in summary_fact_ids
            if facts[fact_id].get("category") == "employment"
            and facts[fact_id].get("scope") == "role"
        ]

    stories, selected_facts, planned_visible_facts = parse_stories(
        data["stories"],
        version=version,
        facts=facts,
        progression=progression,
    )
    selected_facts.update(summary_fact_ids)
    summary_strategy = parse_summary_strategy(version, data, facts, stories, summary_fact_ids)

    raw_exclusions = data["exclusions"]
    if not isinstance(raw_exclusions, list):
        raise ValueError("synthesis exclusions must be a list")
    exclusions: list[tuple[str, str]] = []
    excluded_facts: set[str] = set()
    for index, raw_exclusion in enumerate(raw_exclusions):
        owner = f"synthesis exclusions[{index}]"
        exclusion = object_value(raw_exclusion, owner)
        exact_fields(exclusion, {"fact_id", "reason"}, owner)
        fact_id = nonempty_string(exclusion["fact_id"], f"{owner}.fact_id")
        if fact_id not in facts:
            raise ValueError(f"{owner} cites unknown fact: {fact_id}")
        if fact_id in selected_facts:
            raise ValueError(f"synthesis fact cannot be selected and excluded: {fact_id}")
        if fact_id in excluded_facts:
            raise ValueError(f"duplicate synthesis exclusion: {fact_id}")
        excluded_facts.add(fact_id)
        exclusions.append((fact_id, nonempty_string(exclusion["reason"], f"{owner}.reason")))

    gaps = tuple(string_list(data["gaps"], "synthesis gaps", required=False))

    target_mode: str | None = None
    concept_fit: tuple[ConceptFit, ...] = ()
    reviewer_risks: tuple[ReviewerRisk, ...] = ()
    presentation: PresentationStrategy | None = None
    if version >= 3:
        target_mode = nonempty_string(data["target_mode"], "synthesis target_mode")
        if target_mode not in TARGET_MODES:
            raise ValueError(f"synthesis target_mode must be one of {sorted(TARGET_MODES)}")

        expected_concepts = direction_concept_ids(direction)
        raw_fit = data["concept_fit"]
        if not isinstance(raw_fit, list) or not raw_fit:
            raise ValueError("synthesis concept_fit must be a non-empty list")
        fit_entries: list[ConceptFit] = []
        seen_concepts: set[str] = set()
        for index, raw_entry in enumerate(raw_fit):
            owner = f"synthesis concept_fit[{index}]"
            entry = object_value(raw_entry, owner)
            exact_fields(entry, {"concept_id", "status", "fact_ids", "rationale"}, owner)
            concept_id = nonempty_string(entry["concept_id"], f"{owner}.concept_id")
            if concept_id in seen_concepts:
                raise ValueError(f"duplicate synthesis concept fit: {concept_id}")
            seen_concepts.add(concept_id)
            status = nonempty_string(entry["status"], f"{owner}.status")
            if status not in FIT_STATUSES:
                raise ValueError(f"{owner}.status must be one of {sorted(FIT_STATUSES)}")
            fit_fact_ids = string_list(
                entry["fact_ids"], f"{owner}.fact_ids", required=status != "unsupported"
            )
            unknown_fit_facts = sorted(set(fit_fact_ids) - facts.keys())
            if unknown_fit_facts:
                raise ValueError(f"{owner} cites unknown facts: {unknown_fit_facts}")
            if status == "unsupported" and fit_fact_ids:
                raise ValueError(f"{owner}.fact_ids must be empty when status is unsupported")
            visible_plan_facts = planned_visible_facts if version >= 6 else selected_facts
            visible_plan_facts = set(visible_plan_facts) | set(summary_fact_ids)
            unselected_fit_facts = sorted(set(fit_fact_ids) - visible_plan_facts)
            if unselected_fit_facts:
                raise ValueError(
                    f"{owner} cites evidence absent from selected stories and summary: "
                    f"{unselected_fit_facts}"
                )
            fit_entries.append(
                ConceptFit(
                    concept_id=concept_id,
                    status=status,
                    fact_ids=tuple(fit_fact_ids),
                    rationale=nonempty_string(entry["rationale"], f"{owner}.rationale"),
                )
            )
        missing_concepts = sorted(expected_concepts - seen_concepts)
        unknown_concepts = sorted(seen_concepts - expected_concepts)
        if missing_concepts or unknown_concepts:
            raise ValueError(
                "synthesis concept_fit must classify every direction concept exactly once: "
                f"missing={missing_concepts}, unknown={unknown_concepts}"
            )
        concept_fit = tuple(fit_entries)

        raw_risks = data["reviewer_risks"]
        if not isinstance(raw_risks, list) or len(raw_risks) > 3:
            raise ValueError("synthesis reviewer_risks must be a list of at most three items")
        risk_entries: list[ReviewerRisk] = []
        seen_risks: set[str] = set()
        unresolved_risk = False
        for index, raw_risk in enumerate(raw_risks):
            owner = f"synthesis reviewer_risks[{index}]"
            risk = object_value(raw_risk, owner)
            exact_fields(
                risk,
                {"id", "concern", "status", "fact_ids", "planning_action"},
                owner,
            )
            risk_id = nonempty_string(risk["id"], f"{owner}.id")
            if not STORY_ID.fullmatch(risk_id):
                raise ValueError(f"{owner}.id must be a lowercase hyphenated identifier")
            if risk_id in seen_risks:
                raise ValueError(f"duplicate synthesis reviewer risk: {risk_id}")
            seen_risks.add(risk_id)
            risk_status = nonempty_string(risk["status"], f"{owner}.status")
            if risk_status not in RISK_STATUSES:
                raise ValueError(f"{owner}.status must be one of {sorted(RISK_STATUSES)}")
            risk_fact_ids = string_list(
                risk["fact_ids"], f"{owner}.fact_ids", required=risk_status != "unresolved"
            )
            unknown_risk_facts = sorted(set(risk_fact_ids) - facts.keys())
            if unknown_risk_facts:
                raise ValueError(f"{owner} cites unknown facts: {unknown_risk_facts}")
            visible_plan_facts = planned_visible_facts if version >= 6 else selected_facts
            visible_plan_facts = set(visible_plan_facts) | set(summary_fact_ids)
            excluded_fact_ids = {fact_id for fact_id, _reason in exclusions}
            unaccounted_risk_facts = sorted(
                set(risk_fact_ids) - visible_plan_facts - excluded_fact_ids
            )
            if unaccounted_risk_facts:
                raise ValueError(
                    f"{owner} cites evidence absent from selected stories, summary, and "
                    f"intentional exclusions: {unaccounted_risk_facts}"
                )
            unresolved_risk = unresolved_risk or risk_status == "unresolved"
            risk_entries.append(
                ReviewerRisk(
                    risk_id=risk_id,
                    concern=nonempty_string(risk["concern"], f"{owner}.concern"),
                    status=risk_status,
                    fact_ids=tuple(risk_fact_ids),
                    planning_action=nonempty_string(
                        risk["planning_action"], f"{owner}.planning_action"
                    ),
                )
            )
        if unresolved_risk and not gaps:
            raise ValueError("unresolved synthesis reviewer risks require at least one gap")
        reviewer_risks = tuple(risk_entries)

        raw_presentation = object_value(data["presentation"], "synthesis presentation")
        exact_fields(
            raw_presentation,
            {"competencies", "competencies_job", "compressed_role_ids"},
            "synthesis presentation",
        )
        competencies = nonempty_string(
            raw_presentation["competencies"], "synthesis presentation.competencies"
        )
        if competencies not in COMPETENCY_DECISIONS:
            raise ValueError("synthesis presentation.competencies must be include or omit")
        compressed_role_ids = string_list(
            raw_presentation["compressed_role_ids"],
            "synthesis presentation.compressed_role_ids",
            required=False,
        )
        unknown_compressed_roles = sorted(set(compressed_role_ids) - set(progression))
        if unknown_compressed_roles:
            raise ValueError(
                "synthesis presentation compresses roles absent from progression: "
                f"{unknown_compressed_roles}"
            )
        presentation = PresentationStrategy(
            competencies=competencies,
            competencies_job=nonempty_string(
                raw_presentation["competencies_job"],
                "synthesis presentation.competencies_job",
            ),
            compressed_role_ids=tuple(compressed_role_ids),
        )
        if resume_template is not None:
            competency_required = "competencies" in resume_template.content.required_sections
            competency_forbidden = "competencies" in resume_template.content.forbidden_sections
            if competency_required and competencies != "include":
                raise ValueError(
                    "synthesis competencies decision disagrees with resume template: "
                    "the selected template requires competencies"
                )
            if competency_forbidden and competencies != "omit":
                raise ValueError(
                    "synthesis competencies decision disagrees with resume template: "
                    "the selected template forbids competencies"
                )

    role_arcs = parse_role_arcs(
        data.get("role_arcs"),
        version=version,
        presentation=presentation,
        progression=progression,
        stories=stories,
        facts=facts,
    )

    return SynthesisPlan(
        source=source,
        version=version,
        resume=resume,
        direction=direction,
        target_argument=nonempty_string(data["target_argument"], "synthesis target_argument"),
        summary_job=summary_job,
        summary_fact_ids=tuple(summary_fact_ids),
        summary_body_fact_ids=tuple(summary_body_fact_ids),
        summary_strategy=summary_strategy,
        progression=tuple(progression),
        stories=tuple(stories),
        exclusions=tuple(exclusions),
        gaps=gaps,
        target_mode=target_mode,
        concept_fit=concept_fit,
        reviewer_risks=reviewer_risks,
        presentation=presentation,
        role_arcs=role_arcs,
        page_budget=page_budget,
        resume_template=resume_template,
    )
