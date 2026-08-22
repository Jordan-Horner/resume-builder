"""Load, compose, catalog, and scaffold resume templates and visual themes."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .atomic import atomic_write_text
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
THEME_CSS_PLACEHOLDER = "{{THEME_CSS}}"
THEME_KINDS = {"content", "theme"}


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


def _validate_theme_renderer(renderer: Path, *, require_theme_css: bool = False) -> None:
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
    css_placeholders = template.count(THEME_CSS_PLACEHOLDER)
    if require_theme_css and css_placeholders != 1:
        raise ValueError(
            "version 2 resume theme renderer must contain {{THEME_CSS}} exactly once"
        )
    if css_placeholders > 1:
        raise ValueError("resume theme renderer contains {{THEME_CSS}} more than once")
    if css_placeholders == 1:
        css_index = template.index(THEME_CSS_PLACEHOLDER)
        lowered = template.lower()
        style_start = lowered.rfind("<style", 0, css_index)
        style_open_end = lowered.find(">", style_start, css_index) if style_start >= 0 else -1
        style_end = lowered.find("</style>", css_index)
        if style_open_end < 0 or style_end < 0:
            raise ValueError("resume theme {{THEME_CSS}} placeholder must be inside a style block")


def _validate_stylesheet(stylesheet: Path) -> str:
    if stylesheet.suffix.lower() != ".css":
        raise ValueError(f"resume theme stylesheet must be a CSS file: {stylesheet}")
    try:
        content = stylesheet.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"cannot read resume theme stylesheet {stylesheet}: {exc}") from exc
    if not content.strip():
        raise ValueError(f"resume theme stylesheet must not be empty: {stylesheet}")
    lowered = content.lower()
    forbidden = [token for token in ("@import", "url(", "</style") if token in lowered]
    if forbidden:
        raise ValueError(
            "resume theme stylesheet must be self-contained and must not close its style tag: "
            f"forbidden={forbidden}"
        )
    return content


def load_content_template(project_root: Path, template_id: str) -> ContentTemplate:
    """Load one named content template from the private workspace registry."""
    path = _registry_file(project_root, "resume-templates", template_id, "resume template")
    data = _yaml(path, "resume template")
    version = data.get("version")
    common_fields = {
        "version",
        "id",
        "section_order",
        "required_sections",
        "optional_sections",
        "forbidden_sections",
    }
    if version == 1:
        exact_fields(data, common_fields, "resume template")
        display_name = None
        description = None
    elif version == 2:
        exact_fields(data, common_fields | {"display_name", "description"}, "resume template")
        display_name = nonempty_string(data["display_name"], "resume template display_name")
        description = nonempty_string(data["description"], "resume template description")
    else:
        raise ValueError("resume template must declare version 1 or 2")
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
        version=int(version),
        display_name=display_name,
        description=description,
    )


def load_rendering_theme(project_root: Path, theme_id: str) -> RenderingTheme:
    """Load one named visual theme and its renderer path."""
    path = _registry_file(project_root, "themes", theme_id, "resume theme")
    data = _yaml(path, "resume theme")
    version = data.get("version")
    if version == 1:
        exact_fields(data, {"version", "id", "renderer"}, "resume theme")
        display_name = None
        description = None
        category = None
        stylesheet = None
    elif version == 2:
        exact_fields(
            data,
            {
                "version",
                "id",
                "display_name",
                "description",
                "category",
                "renderer",
                "stylesheet",
            },
            "resume theme",
        )
        display_name = nonempty_string(data["display_name"], "resume theme display_name")
        description = nonempty_string(data["description"], "resume theme description")
        category = nonempty_string(data["category"], "resume theme category")
        stylesheet = contained_project_path(
            Path(nonempty_string(data["stylesheet"], "resume theme stylesheet")),
            project_root,
            "templates",
            "resume theme stylesheet",
        )
        if not stylesheet.is_file():
            raise ValueError(f"resume theme stylesheet does not exist: {stylesheet}")
        _validate_stylesheet(stylesheet)
    else:
        raise ValueError("resume theme must declare version 1 or 2")
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
    _validate_theme_renderer(renderer, require_theme_css=version == 2)
    return RenderingTheme(
        theme_id=theme_id,
        source=path,
        renderer=renderer,
        version=int(version),
        display_name=display_name,
        description=description,
        category=category,
        stylesheet=stylesheet,
    )


def rendering_theme_text(theme: RenderingTheme) -> str:
    """Return the validated renderer with any version-2 stylesheet composed inline."""
    template = theme.renderer.read_text(encoding="utf-8")
    stylesheet = _validate_stylesheet(theme.stylesheet) if theme.stylesheet is not None else ""
    if theme.version == 2 and template.count(THEME_CSS_PLACEHOLDER) != 1:
        raise ValueError("version 2 resume theme renderer is missing {{THEME_CSS}}")
    return template.replace(THEME_CSS_PLACEHOLDER, stylesheet)


def _catalog_files(project_root: Path, directory: str) -> list[Path]:
    root = project_root / "templates" / directory
    return sorted(root.glob("*.yaml")) if root.is_dir() else []


def template_catalog(project_root: Path) -> dict[str, object]:
    """Return every workspace template with validation and display metadata."""
    from .workspace_templates import template_resources

    built_ins = {
        (Path("templates") / relative).as_posix(): content
        for relative, content in template_resources()
    }
    items: list[dict[str, object]] = []
    errors: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for kind, directory in (("content", "resume-templates"), ("theme", "themes")):
        for path in _catalog_files(project_root, directory):
            item_id = path.stem
            key = (kind, item_id)
            if key in seen:
                errors.append({"kind": kind, "id": item_id, "error": "duplicate template id"})
                continue
            seen.add(key)
            try:
                loaded: Any = (
                    load_content_template(project_root, item_id)
                    if kind == "content"
                    else load_rendering_theme(project_root, item_id)
                )
            except ValueError as exc:
                errors.append({"kind": kind, "id": item_id, "error": str(exc)})
                continue
            items.append(
                {
                    "kind": kind,
                    "id": item_id,
                    "version": loaded.version,
                    "display_name": loaded.display_name or item_id.replace("-", " ").title(),
                    "description": loaded.description or "Legacy version 1 template",
                    "category": loaded.category if kind == "theme" else None,
                    "path": path.relative_to(project_root).as_posix(),
                    "origin": (
                        "built-in"
                        if built_ins.get(path.relative_to(project_root).as_posix())
                        == path.read_text(encoding="utf-8")
                        else "workspace-owned"
                    ),
                }
            )
    return {"valid": not errors, "templates": items, "errors": errors}


def select_catalog_item(
    catalog: dict[str, object], template_id: str | None
) -> dict[str, object]:
    """Filter a template catalog to one content or theme ID when requested."""
    if template_id is None:
        return catalog
    templates_value = catalog.get("templates")
    errors_value = catalog.get("errors")
    templates = templates_value if isinstance(templates_value, list) else []
    errors = errors_value if isinstance(errors_value, list) else []
    matches = [
        item for item in templates if isinstance(item, dict) and item.get("id") == template_id
    ]
    matching_errors = [
        item for item in errors if isinstance(item, dict) and item.get("id") == template_id
    ]
    return {
        "valid": bool(matches) and not matching_errors,
        "templates": matches,
        "errors": matching_errors
        or ([] if matches else [{"id": template_id, "error": "not found"}]),
    }


def scaffold_template(project_root: Path, kind: str, item_id: str) -> dict[str, object]:
    """Create one safe workspace-owned version-2 template without overwriting files."""
    if kind not in THEME_KINDS:
        raise ValueError(f"template kind must be one of {sorted(THEME_KINDS)}")
    if not STORY_ID.fullmatch(item_id):
        raise ValueError("template id must be a lowercase hyphenated identifier")
    created: list[str] = []
    if kind == "theme":
        descriptor = project_root / "templates" / "themes" / f"{item_id}.yaml"
        stylesheet = project_root / "templates" / "themes" / f"{item_id}.css"
        targets = (descriptor, stylesheet)
        if any(path.exists() for path in targets):
            raise ValueError(f"template scaffold target already exists: {item_id}")
        atomic_write_text(
            stylesheet,
            ":root {\n  --accent: #222222;\n  --accent-dark: #222222;\n  --secondary: #444444;\n}\n",
        )
        atomic_write_text(
            descriptor,
            "\n".join(
                [
                    "version: 2",
                    f"id: {item_id}",
                    f'display_name: "{item_id.replace("-", " ").title()}"',
                    'description: "Workspace-owned ATS-safe visual theme"',
                    'category: "custom"',
                    "renderer: templates/renderers/ats-single-column.html",
                    f"stylesheet: templates/themes/{item_id}.css",
                    "",
                ]
            ),
        )
        created.extend(path.relative_to(project_root).as_posix() for path in targets)
    else:
        descriptor = project_root / "templates" / "resume-templates" / f"{item_id}.yaml"
        if descriptor.exists():
            raise ValueError(f"template scaffold target already exists: {item_id}")
        atomic_write_text(
            descriptor,
            "\n".join(
                [
                    "version: 2",
                    f"id: {item_id}",
                    f'display_name: "{item_id.replace("-", " ").title()}"',
                    'description: "Workspace-owned resume content architecture"',
                    "section_order: [summary, experience, projects, education, certifications, skills]",
                    "required_sections: [summary, experience, skills]",
                    "optional_sections: [projects, education, certifications]",
                    "forbidden_sections: [competencies]",
                    "",
                ]
            ),
        )
        created.append(descriptor.relative_to(project_root).as_posix())
    return {"valid": True, "kind": kind, "id": item_id, "created": created}
