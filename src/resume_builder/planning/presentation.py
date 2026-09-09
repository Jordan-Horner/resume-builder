"""Parse synthesis-plan presentation decisions."""

from __future__ import annotations

from collections.abc import Sequence

from .models import COMPETENCY_DECISIONS, PresentationStrategy, ResumeTemplateSelection
from .schema import exact_fields, nonempty_string, object_value, string_list


def parse_presentation(
    raw_presentation: object,
    *,
    version: int,
    progression: Sequence[str],
    resume_template: ResumeTemplateSelection | None,
) -> PresentationStrategy | None:
    """Return validated presentation choices for one synthesis plan."""
    if version < 3:
        return None

    presentation_data = object_value(raw_presentation, "synthesis presentation")
    exact_fields(
        presentation_data,
        {"competencies", "competencies_job", "compressed_role_ids"},
        "synthesis presentation",
    )
    competencies = nonempty_string(
        presentation_data["competencies"], "synthesis presentation.competencies"
    )
    if competencies not in COMPETENCY_DECISIONS:
        raise ValueError("synthesis presentation.competencies must be include or omit")
    compressed_role_ids = string_list(
        presentation_data["compressed_role_ids"],
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
            presentation_data["competencies_job"],
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
    return presentation
