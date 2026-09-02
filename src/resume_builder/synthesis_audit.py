"""Audit compiled resumes against validated synthesis plans."""

from __future__ import annotations

import hashlib
from collections import Counter
from pathlib import Path
from typing import Any

from .role_balance import role_balance_diagnostic
from .synthesis_models import SynthesisPlan, SynthesisStory, summary_strategy_payload


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def body_evidence_ids(payload: dict[str, Any]) -> set[str]:
    """Collect canonical evidence cited after the summary."""
    result: set[str] = set()

    def collect(value: object) -> None:
        if isinstance(value, dict):
            raw_evidence = value.get("evidence")
            if isinstance(raw_evidence, list):
                result.update(item for item in raw_evidence if isinstance(item, str))
            for nested in value.values():
                collect(nested)
        elif isinstance(value, list):
            for nested in value:
                collect(nested)

    for section in (
        "competencies",
        "experience",
        "projects",
        "education",
        "certifications",
        "skills",
    ):
        collect(payload.get(section, []))
    return result


def role_arc_payloads(
    plan: SynthesisPlan,
    used_story_ids: set[str] | None = None,
) -> list[dict[str, object]]:
    """Return inspectable role-level story allocations for reports and manifests."""
    story_by_id = {story.story_id: story for story in plan.stories}
    result: list[dict[str, object]] = []
    for arc in plan.role_arcs:
        payload: dict[str, object] = {
            "role_ids": list(arc.role_ids),
            "emphasis": arc.emphasis,
            "arc_focus": arc.arc_focus,
            "story_ids": list(arc.story_ids),
            "primary_jobs": [story_by_id[story_id].primary_job for story_id in arc.story_ids],
            "planned_story_count": len(arc.story_ids),
            "selection_rationale": arc.selection_rationale,
            "omitted_signals": [
                {
                    "signal": signal.signal,
                    "fact_ids": list(signal.fact_ids),
                    "reason": signal.reason,
                }
                for signal in arc.omitted_signals
            ],
        }
        if plan.version >= 6:
            payload.update(
                {
                    "required_dimensions": list(arc.required_dimensions),
                    "required_story_ids": list(arc.required_story_ids),
                    "optional_story_ids": list(arc.optional_story_ids),
                }
            )
        if plan.version >= 8:
            payload["role_anchor_story_ids"] = list(arc.role_anchor_story_ids)
        if plan.version >= 9:
            payload["role_selling_story_ids"] = list(arc.role_selling_story_ids)
        if plan.version >= 10:
            payload["core_job"] = {
                "selected_id": arc.selected_core_job_id,
                "decision": arc.core_job_decision,
                "candidates": [
                    {
                        "id": candidate.candidate_id,
                        "description": candidate.description,
                        "confidence": candidate.confidence,
                    }
                    for candidate in arc.core_job_candidates
                ],
            }
        if used_story_ids is not None:
            used = [story_id for story_id in arc.story_ids if story_id in used_story_ids]
            payload.update(
                {
                    "used_story_ids": used,
                    "used_story_count": len(used),
                    "omitted_story_ids": [
                        story_id for story_id in arc.story_ids if story_id not in used_story_ids
                    ],
                }
            )
        result.append(payload)
    return result


def audit_synthesis(payload: dict[str, Any], plan: SynthesisPlan) -> dict[str, object]:
    """Require core stories and report intentionally omitted supporting stories."""
    planned = {story.story_id: story for story in plan.stories}
    used: list[str] = []
    selected_fact_ids: set[str] = set()
    present_roles: set[str] = set()
    story_evidence: dict[str, dict[str, object]] = {}
    unused_optional_facts: set[str] = set()

    def validate_story_evidence(
        evidence_value: object,
        story: SynthesisStory,
        owner: str,
    ) -> set[str]:
        evidence = (
            {item for item in evidence_value if isinstance(item, str)}
            if isinstance(evidence_value, list)
            else set()
        )
        planned_evidence = set(story.fact_ids)
        if plan.version >= 6:
            assert story.claim is not None
            expected_claim_evidence = set(story.claim.evidence.fact_ids)
            if evidence != expected_claim_evidence:
                raise ValueError(
                    f"{owner} evidence disagrees with structured claim {story.story_id}: "
                    f"missing={sorted(expected_claim_evidence - evidence)}, "
                    f"unexpected={sorted(evidence - expected_claim_evidence)}"
                )
        elif plan.version < 4:
            if evidence != planned_evidence:
                raise ValueError(f"{owner} evidence disagrees with story {story.story_id}")
        else:
            unexpected = sorted(evidence - planned_evidence)
            missing_core = sorted(set(story.core_fact_ids) - evidence)
            if not evidence or unexpected or missing_core:
                raise ValueError(
                    f"{owner} evidence disagrees with story {story.story_id}: "
                    f"missing_core={missing_core}, unexpected={unexpected}"
                )
        unused_optional = sorted(planned_evidence - set(story.core_fact_ids) - evidence)
        unused_optional_facts.update(unused_optional)
        story_evidence_item: dict[str, object] = {
            "claim_focus": story.claim_focus,
            "core_fact_ids": list(story.core_fact_ids),
            "available_fact_ids": list(story.fact_ids),
            "used_fact_ids": sorted(evidence),
            "unused_optional_fact_ids": unused_optional,
        }
        if story.claim is not None:
            story_evidence_item["claim"] = {
                "subject": story.claim.subject,
                "action": story.claim.action,
                "object": story.claim.object,
                "scope": story.claim.scope,
                "outcome": story.claim.outcome,
                "composition": story.claim.composition,
                "relationship": story.claim.relationship,
                "evidence": {
                    "action": list(story.claim.evidence.action),
                    "object": list(story.claim.evidence.object),
                    "scope": list(story.claim.evidence.scope),
                    "outcome": list(story.claim.evidence.outcome),
                },
            }
        story_evidence[story.story_id] = story_evidence_item
        return evidence

    for index, item in enumerate(payload.get("experience", [])):
        if not isinstance(item, dict):
            continue
        entry_roles = set(item.get("evidence", [])) & set(plan.progression)
        present_roles.update(entry_roles)
        for bullet_index, bullet in enumerate(item.get("bullets", [])):
            if not isinstance(bullet, dict):
                continue
            owner = f"experience[{index}].bullets[{bullet_index}]"
            story_id = bullet.get("story")
            if not isinstance(story_id, str) or story_id not in planned:
                raise ValueError(f"{owner} requires a planned story ID")
            story = planned[story_id]
            if story.section != "experience":
                raise ValueError(f"{owner} uses a non-experience story: {story_id}")
            if set(story.role_ids) != entry_roles:
                raise ValueError(f"{owner} role placement disagrees with story {story_id}")
            evidence = validate_story_evidence(bullet.get("evidence", []), story, owner)
            used.append(story_id)
            selected_fact_ids.update(evidence)

    for index, item in enumerate(payload.get("projects", [])):
        if not isinstance(item, dict):
            continue
        owner = f"projects[{index}]"
        story_id = item.get("story")
        if not isinstance(story_id, str) or story_id not in planned:
            raise ValueError(f"{owner} requires a planned story ID")
        story = planned[story_id]
        if story.section != "projects":
            raise ValueError(f"{owner} uses a non-project story: {story_id}")
        evidence = validate_story_evidence(item.get("evidence", []), story, owner)
        used.append(story_id)
        selected_fact_ids.update(evidence)

    counts = Counter(used)
    duplicate = sorted(story_id for story_id, count in counts.items() if count > 1)
    missing = sorted(set(planned) - counts.keys())
    missing_core = sorted(
        story_id for story_id in missing if planned[story_id].importance == "core"
    )
    omitted_supporting = sorted(
        story_id for story_id in missing if planned[story_id].importance == "supporting"
    )
    if duplicate:
        raise ValueError(f"synthesis stories used more than once: {duplicate}")
    if missing_core:
        raise ValueError(f"core synthesis stories absent from resume: {missing_core}")
    if plan.version >= 6:
        required_story_ids = {
            story_id for arc in plan.role_arcs for story_id in arc.required_story_ids
        }
        missing_required = sorted(required_story_ids - counts.keys())
        if missing_required:
            raise ValueError(f"required role-arc stories absent from resume: {missing_required}")
    missing_roles = sorted(set(plan.progression) - present_roles)
    if missing_roles:
        raise ValueError(f"planned progression roles absent from resume: {missing_roles}")
    used_exclusions = sorted(set(dict(plan.exclusions)) & selected_fact_ids)
    if used_exclusions:
        raise ValueError(f"excluded synthesis facts appear in resume: {used_exclusions}")
    summary_evidence = payload.get("summary_evidence", [])
    if not isinstance(summary_evidence, list):
        summary_evidence = []
    if plan.version >= 2:
        planned_summary_facts = set(plan.summary_fact_ids)
        actual_summary_facts = {item for item in summary_evidence if isinstance(item, str)}
        if actual_summary_facts != planned_summary_facts:
            missing_summary_facts = sorted(planned_summary_facts - actual_summary_facts)
            unexpected_summary_facts = sorted(actual_summary_facts - planned_summary_facts)
            raise ValueError(
                "resume summary evidence disagrees with synthesis plan: "
                f"missing={missing_summary_facts}, unexpected={unexpected_summary_facts}"
            )
        missing_body_support = sorted(set(plan.summary_body_fact_ids) - body_evidence_ids(payload))
        if missing_body_support:
            raise ValueError(
                "planned role-scoped summary facts are not demonstrated later in the resume: "
                f"{missing_body_support}"
            )
    if plan.version >= 3:
        assert plan.presentation is not None
        has_competencies = bool(payload.get("competencies"))
        should_include = plan.presentation.competencies == "include"
        if has_competencies != should_include:
            raise ValueError(
                "resume competencies section disagrees with synthesis presentation strategy: "
                f"planned={plan.presentation.competencies}, present={has_competencies}"
            )
    if plan.resume_template is not None:
        template = plan.resume_template.content
        actual_order_value = payload.get("section_order")
        if not isinstance(actual_order_value, list) or not all(
            isinstance(item, str) for item in actual_order_value
        ):
            raise ValueError("compiled resume must record its section_order")
        actual_order = list(actual_order_value)
        actual_sections = set(actual_order)
        missing_required = sorted(set(template.required_sections) - actual_sections)
        forbidden_present = sorted(set(template.forbidden_sections) & actual_sections)
        expected_order = [
            section for section in template.section_order if section in actual_sections
        ]
        if missing_required or forbidden_present or actual_order != expected_order:
            raise ValueError(
                "resume section architecture disagrees with selected template: "
                f"template={template.template_id}, missing_required={missing_required}, "
                f"forbidden_present={forbidden_present}, expected_order={expected_order}, "
                f"actual_order={actual_order}"
            )
    core_story_ids = sorted(story.story_id for story in plan.stories if story.importance == "core")
    supporting_story_ids = sorted(
        story.story_id for story in plan.stories if story.importance == "supporting"
    )
    actual_summary_facts = {item for item in summary_evidence if isinstance(item, str)}
    unused_optional_fact_ids = sorted(unused_optional_facts)
    return {
        "valid": True,
        "version": plan.version,
        "stories": len(plan.stories),
        "story_ids": sorted(planned),
        "planned_story_ids": sorted(planned),
        "used_story_ids": sorted(counts),
        "omitted_story_ids": omitted_supporting,
        "core_story_ids": core_story_ids,
        "supporting_story_ids": supporting_story_ids,
        "body_fact_ids": sorted(selected_fact_ids),
        "selected_fact_ids": sorted(selected_fact_ids | actual_summary_facts),
        "unused_optional_fact_ids": unused_optional_fact_ids,
        "story_evidence": [
            story_evidence[story_id] | {"story_id": story_id} for story_id in sorted(story_evidence)
        ],
        "summary_job": plan.summary_job,
        "summary_fact_ids": list(plan.summary_fact_ids),
        "summary_body_fact_ids": list(plan.summary_body_fact_ids),
        **(
            {"summary_strategy": summary_strategy_payload(plan.summary_strategy)}
            if plan.version >= 11
            else {}
        ),
        "progression_role_ids": list(plan.progression),
        "exclusions": len(plan.exclusions),
        "gaps": list(plan.gaps),
        "target_mode": plan.target_mode,
        "concept_fit": [
            {
                "concept_id": item.concept_id,
                "status": item.status,
                "fact_ids": list(item.fact_ids),
                "rationale": item.rationale,
            }
            for item in plan.concept_fit
        ],
        "reviewer_risks": [
            {
                "id": item.risk_id,
                "concern": item.concern,
                "status": item.status,
                "fact_ids": list(item.fact_ids),
                "planning_action": item.planning_action,
            }
            for item in plan.reviewer_risks
        ],
        "presentation": (
            {
                "competencies": plan.presentation.competencies,
                "competencies_job": plan.presentation.competencies_job,
                "compressed_role_ids": list(plan.presentation.compressed_role_ids),
            }
            if plan.presentation is not None
            else None
        ),
        "role_arcs": role_arc_payloads(plan, set(counts)),
        "role_balance": role_balance_diagnostic(payload, plan),
        "page_budget": (
            {"max_pages": plan.page_budget.max_pages, "source": plan.page_budget.source}
            if plan.page_budget is not None
            else None
        ),
        "resume_template": (
            {
                "content": {
                    "id": plan.resume_template.content.template_id,
                    "version": plan.resume_template.content.version,
                    "path": plan.resume_template.content.source.relative_to(
                        plan.source.parents[2]
                    ).as_posix(),
                    "sha256": _sha256(plan.resume_template.content.source),
                },
                "theme": {
                    "id": plan.resume_template.theme.theme_id,
                    "version": plan.resume_template.theme.version,
                    "path": plan.resume_template.theme.source.relative_to(
                        plan.source.parents[2]
                    ).as_posix(),
                    "sha256": _sha256(plan.resume_template.theme.source),
                },
                "renderer": {
                    "path": plan.resume_template.theme.renderer.relative_to(
                        plan.source.parents[2]
                    ).as_posix(),
                    "sha256": _sha256(plan.resume_template.theme.renderer),
                },
                "stylesheet": (
                    {
                        "path": plan.resume_template.theme.stylesheet.relative_to(
                            plan.source.parents[2]
                        ).as_posix(),
                        "sha256": _sha256(plan.resume_template.theme.stylesheet),
                    }
                    if plan.resume_template.theme.stylesheet is not None
                    else None
                ),
            }
            if plan.resume_template is not None
            else None
        ),
    }
