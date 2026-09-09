"""Load and validate versioned synthesis plans against project evidence."""

from __future__ import annotations

from pathlib import Path

import yaml

from ..resume_documents.html import contained_project_path
from ..resume_templates import load_content_template, load_rendering_theme
from .models import (
    PAGE_BUDGET_SOURCES,
    PageBudget,
    ResumeTemplateSelection,
    SynthesisPlan,
)
from .presentation import parse_presentation
from .role_arcs import parse_role_arcs
from .schema import direction_concept_ids as direction_concept_ids
from .schema import (
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
from .targeting import parse_targeting


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

    target_mode, concept_fit, reviewer_risks = parse_targeting(
        data,
        version=version,
        direction=direction,
        facts=facts,
        planned_visible_facts=planned_visible_facts,
        selected_facts=selected_facts,
        summary_fact_ids=summary_fact_ids,
        exclusions=exclusions,
        gaps=gaps,
    )
    presentation = parse_presentation(
        data.get("presentation"),
        version=version,
        progression=progression,
        resume_template=resume_template,
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
