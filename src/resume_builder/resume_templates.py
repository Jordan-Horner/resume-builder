"""Load reusable resume content templates and visual themes."""

from __future__ import annotations

from pathlib import Path

import yaml

from .rendering import contained_project_path
from .synthesis_models import RESUME_SECTIONS, STORY_ID, ContentTemplate, RenderingTheme
from .synthesis_schema import exact_fields, nonempty_string, object_value, string_list

THEME_REQUIRED_PLACEHOLDERS = {
    "{{LANG}}",
    "{{TITLE}}",
    "{{HEADER_EVIDENCE}}",
    "{{NAME}}",
    "{{HEADLINE}}",
    "{{CONTACT}}",
    "{{PREVIEW_NOTICE}}",
    "{{REVIEW_ISSUES}}",
    "{{RESUME_SECTIONS}}",
}
THEME_STYLE_PLACEHOLDERS = {
    "{{PAGE_SIZE}}",
    "{{PAGE_WIDTH}}",
    "{{PAGE_MIN_HEIGHT}}",
}
LEGACY_SECTION_PLACEHOLDERS = {
    "{{SUMMARY_SECTION}}",
    "{{COMPETENCIES_SECTION}}",
    "{{EXPERIENCE_SECTION}}",
    "{{PROJECTS_SECTION}}",
    "{{EDUCATION_SECTION}}",
    "{{CERTIFICATIONS_SECTION}}",
    "{{SKILLS_SECTION}}",
}


def _registry_file(project_root: Path, directory: str, item_id: str, owner: str) -> Path:
    if not STORY_ID.fullmatch(item_id):
        raise ValueError(f"{owner} must be a lowercase hyphenated identifier")
    return contained_project_path(
        Path("templates") / directory / f"{item_id}.yaml",
        project_root,
        f"templates/{directory}",
        owner,
    )


def _yaml(path: Path, owner: str) -> dict[str, object]:
    try:
        return object_value(yaml.safe_load(path.read_text(encoding="utf-8")), owner)
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(f"invalid {owner} {path}: {exc}") from exc


def _unique(values: list[str], owner: str) -> None:
    duplicates = sorted({value for value in values if values.count(value) > 1})
    if duplicates:
        raise ValueError(f"{owner} must not contain duplicates: {duplicates}")


def _validate_theme_renderer(renderer: Path) -> None:
    if renderer.suffix.lower() != ".html":
        raise ValueError(f"resume theme renderer must be an HTML file: {renderer}")
    try:
        template = renderer.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"cannot read resume theme renderer {renderer}: {exc}") from exc
    missing = sorted(
        placeholder
        for placeholder in THEME_REQUIRED_PLACEHOLDERS
        if template.count(placeholder) != 1
    )
    if missing:
        raise ValueError(
            "resume theme renderer must contain each required placeholder exactly once: "
            f"invalid={missing}"
        )
    missing_style = sorted(
        placeholder for placeholder in THEME_STYLE_PLACEHOLDERS if placeholder not in template
    )
    if missing_style:
        raise ValueError(
            "resume theme renderer must contain every required style placeholder: "
            f"missing={missing_style}"
        )
    legacy = sorted(
        placeholder for placeholder in LEGACY_SECTION_PLACEHOLDERS if placeholder in template
    )
    if legacy:
        raise ValueError(
            "resume theme renderer must use {{RESUME_SECTIONS}} instead of legacy section "
            f"placeholders: {legacy}"
        )


def load_content_template(project_root: Path, template_id: str) -> ContentTemplate:
    """Load one named content template from the private workspace registry."""
    path = _registry_file(project_root, "resume-templates", template_id, "resume template")
    data = _yaml(path, "resume template")
    exact_fields(
        data,
        {
            "version",
            "id",
            "section_order",
            "required_sections",
            "optional_sections",
            "forbidden_sections",
        },
        "resume template",
    )
    if data["version"] != 1:
        raise ValueError("resume template must declare version 1")
    declared_id = nonempty_string(data["id"], "resume template id")
    if declared_id != template_id:
        raise ValueError(
            f"resume template filename and id disagree: file={template_id}, id={declared_id}"
        )
    section_order = string_list(data["section_order"], "resume template section_order")
    required = string_list(data["required_sections"], "resume template required_sections")
    optional = string_list(
        data["optional_sections"], "resume template optional_sections", required=False
    )
    forbidden = string_list(
        data["forbidden_sections"], "resume template forbidden_sections", required=False
    )
    for values, owner in (
        (section_order, "resume template section_order"),
        (required, "resume template required_sections"),
        (optional, "resume template optional_sections"),
        (forbidden, "resume template forbidden_sections"),
    ):
        _unique(values, owner)
    configured = set(required) | set(optional) | set(forbidden)
    unknown = sorted(configured - RESUME_SECTIONS)
    if unknown:
        raise ValueError(f"resume template contains unknown sections: {unknown}")
    if configured != RESUME_SECTIONS:
        raise ValueError(
            "resume template must classify every canonical section exactly once: "
            f"missing={sorted(RESUME_SECTIONS - configured)}"
        )
    overlap = sorted(
        (set(required) & set(optional))
        | (set(required) & set(forbidden))
        | (set(optional) & set(forbidden))
    )
    if overlap:
        raise ValueError(f"resume template section classifications overlap: {overlap}")
    allowed = set(required) | set(optional)
    if set(section_order) != allowed:
        raise ValueError(
            "resume template section_order must contain every required and optional section "
            f"exactly once: missing={sorted(allowed - set(section_order))}, "
            f"unexpected={sorted(set(section_order) - allowed)}"
        )
    if "summary" not in required:
        raise ValueError("resume template must require the summary section")
    return ContentTemplate(
        template_id=template_id,
        source=path,
        section_order=tuple(section_order),
        required_sections=tuple(required),
        optional_sections=tuple(optional),
        forbidden_sections=tuple(forbidden),
    )


def load_rendering_theme(project_root: Path, theme_id: str) -> RenderingTheme:
    """Load one named visual theme and its renderer path."""
    path = _registry_file(project_root, "themes", theme_id, "resume theme")
    data = _yaml(path, "resume theme")
    exact_fields(data, {"version", "id", "renderer"}, "resume theme")
    if data["version"] != 1:
        raise ValueError("resume theme must declare version 1")
    declared_id = nonempty_string(data["id"], "resume theme id")
    if declared_id != theme_id:
        raise ValueError(
            f"resume theme filename and id disagree: file={theme_id}, id={declared_id}"
        )
    renderer = contained_project_path(
        Path(nonempty_string(data["renderer"], "resume theme renderer")),
        project_root,
        "templates",
        "resume theme renderer",
    )
    if not renderer.is_file():
        raise ValueError(f"resume theme renderer does not exist: {renderer}")
    _validate_theme_renderer(renderer)
    return RenderingTheme(theme_id=theme_id, source=path, renderer=renderer)
