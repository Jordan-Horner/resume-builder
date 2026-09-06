"""Read-only career-library views and vault-backed job-search skill signals."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

import yaml

from .artifact_paths import resume_output_base
from .atomic import atomic_write_text
from .ats import normalize_payload
from .discovery_activation import (
    apply_portfolio_update,
    edit_portfolio,
    load_portfolio,
    save_portfolio,
)
from .discovery_portfolio import (
    MAX_CAPABILITY_QUERIES,
    ColdStartLane,
    ColdStartPortfolio,
    ColdStartQuery,
)
from .job_setup_defaults import PORTFOLIO_PATH, PREFERENCES_PATH, scaffold_job_search
from .layout import VaultLayout
from .project_report import project_report
from .rendering import known_fact_ids, render_payload
from .resume_parser import compile_markdown
from .resume_templates import load_rendering_theme, rendering_theme_text
from .role_policy import check_query_capacity
from .source_import import is_metadata_name
from .validation import parse_frontmatter

SEARCH_CONFIG_PATH = Path("job-search/config/search.yml")
VAULT_QUERY_PREFIX = "vault-skill-"
PORTFOLIO_BACKUP_PATH = Path("build/job-search/portfolio-before-last-portal-change.json")
CONFIG_BACKUP_PATH = Path("build/job-search/search-before-last-portal-change.yml")


def _preview_url(resume_id: str, version: int) -> str:
    return f"/api/resume-preview?resume_id={quote(resume_id, safe='')}&v={version}"


def _without_workflow_notice(template: str) -> str:
    """Remove the build-workflow banner from the portal's document reader."""
    start = template.find('<aside class="draft-notice"')
    if start == -1:
        return template
    end = template.find("</aside>", start)
    if end == -1:
        return template
    return template[:start] + template[end + len("</aside>") :]


def _render_portal_preview(root: Path, resume: Path) -> Path:
    """Render current Markdown for reading without changing workflow state."""
    payload, _ = normalize_payload(compile_markdown(resume.read_text(encoding="utf-8")))
    default_template = root / "templates" / "resume-template.html"
    plan_path = root / "resumes" / "plans" / f"{resume.stem}.yaml"
    if plan_path.is_file():
        raw_plan = yaml.safe_load(plan_path.read_text(encoding="utf-8"))
        resume_template = raw_plan.get("resume_template") if isinstance(raw_plan, dict) else None
        theme_id = resume_template.get("theme") if isinstance(resume_template, dict) else None
        if isinstance(theme_id, str) and theme_id:
            template = rendering_theme_text(load_rendering_theme(root, theme_id))
        else:
            template = default_template.read_text(encoding="utf-8").replace("{{THEME_CSS}}", "")
    else:
        template = default_template.read_text(encoding="utf-8").replace("{{THEME_CSS}}", "")
    rendered = render_payload(
        payload,
        _without_workflow_notice(template),
        known_fact_ids((root / "vault").resolve()),
        preview_notice="",
    )
    output = resume_output_base(root, resume).with_suffix(".portal.html")
    output.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(output, rendered)
    return output


def resolve_resume_preview(root: Path, resume_id: str) -> dict[str, Any]:
    """Resolve an existing generated HTML preview without accepting client paths."""
    candidate = (root / resume_id).resolve()
    allowed = (
        (root / "resumes" / "baselines").resolve(),
        (root / "resumes" / "tailored").resolve(),
    )
    if (
        candidate.suffix.casefold() != ".md"
        or not candidate.is_file()
        or not any(candidate.is_relative_to(base) for base in allowed)
    ):
        raise ValueError("generated resume was not found")
    rendered = _render_portal_preview(root, candidate)
    return {
        "path": rendered,
        "filename": f"{candidate.stem}.html",
        "media_type": "text/html; charset=utf-8",
    }


def _display_name(path: Path, payload: dict[str, Any] | None = None) -> str:
    candidate = payload.get("candidate") if isinstance(payload, dict) else None
    headline = candidate.get("headline") if isinstance(candidate, dict) else None
    return str(headline).strip() if headline else path.stem.replace("-", " ").title()


def _all_evidence_ids(value: object) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        for key, child in value.items():
            if key == "evidence" and isinstance(child, list):
                found.update(item for item in child if isinstance(item, str))
            else:
                found.update(_all_evidence_ids(child))
    elif isinstance(value, list):
        for child in value:
            found.update(_all_evidence_ids(child))
    return found


def list_resumes(root: Path) -> dict[str, Any]:
    """Adapt generated resume artifacts into a presentation-ready library."""
    report = project_report(root / "vault", strict=False)
    generated: dict[str, list[dict[str, Any]]] = {"directional": [], "tailored": []}
    for record in report["resumes"]:
        if record["kind"] == "tailored" and record.get("mint", {}).get("status") != "current":
            continue
        path = root / record["path"]
        try:
            payload = compile_markdown(path.read_text(encoding="utf-8"))
            error = None
        except (OSError, ValueError) as exc:
            payload = None
            error = str(exc)
        kind = "directional" if record["kind"] == "baseline" else "tailored"
        direction = record.get("direction")
        detail = (
            f"Direction · {Path(direction).stem.replace('-', ' ').title()}"
            if kind == "directional" and direction
            else "Reusable role direction"
            if kind == "directional"
            else "Minted application resume"
        )
        generated[kind].append(
            {
                "id": record["path"],
                "name": _display_name(path, payload),
                "kind": kind,
                "updated_at": datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat(),
                "detail": detail,
                "skill_fact_ids": sorted(_all_evidence_ids(payload or {})),
                "error": error,
                "preview_url": _preview_url(record["path"], path.stat().st_mtime_ns)
                if payload is not None
                else None,
                "preview_message": None,
            }
        )
    return {
        "sections": [
            {
                "id": "directional",
                "title": "Directional resumes",
                "description": "Reusable resumes built for a role direction.",
                "items": generated["directional"],
            },
            {
                "id": "tailored",
                "title": "Tailored resumes",
                "description": "Minted job-specific resumes used with applications.",
                "items": generated["tailored"],
            },
        ]
    }


def _description(body: str) -> str:
    paragraphs = [
        " ".join(
            line.strip() for line in paragraph.splitlines() if not line.lstrip().startswith("#")
        )
        for paragraph in body.split("\n\n")
    ]
    return next((paragraph for paragraph in paragraphs if paragraph), "")


def _strings(value: object) -> list[str]:
    return [str(item) for item in value] if isinstance(value, list) else []


def _selected_skill_ids(root: Path) -> set[str]:
    path = root / PORTFOLIO_PATH
    if not path.is_file():
        return set()
    portfolio = load_portfolio(path)
    return {
        source.removeprefix("vault:")
        for query in portfolio.queries
        if query.enabled
        for source in query.source_ids
        if source.startswith("vault:")
    }


def list_skills(root: Path) -> list[dict[str, Any]]:
    """Build the portal skill inventory directly from canonical vault facts."""
    layout = VaultLayout.load(root / "vault")
    selected = _selected_skill_ids(root)
    resume_names: dict[str, list[str]] = {}
    for section in list_resumes(root)["sections"]:
        for resume in section["items"]:
            for fact_id in resume.get("skill_fact_ids", []):
                resume_names.setdefault(fact_id, []).append(resume["name"])
    records: list[dict[str, Any]] = []
    skill_root = layout.facts / "skills"
    for path in sorted(skill_root.rglob("*.md")) if skill_root.is_dir() else []:
        if is_metadata_name(path.relative_to(skill_root).as_posix()):
            continue
        metadata, body = parse_frontmatter(path)
        fact_id = metadata.get("id")
        title = metadata.get("title")
        if not isinstance(fact_id, str) or not isinstance(title, str):
            raise ValueError(f"skill fact has no valid id or title: {path}")
        records.append(
            {
                "id": fact_id,
                "title": title,
                "description": _description(body),
                "status_label": "Confirmed"
                if metadata.get("status") == "confirmed"
                else "Review needed",
                "status_tone": "positive" if metadata.get("status") == "confirmed" else "attention",
                "themes": _strings(metadata.get("themes")),
                "sources": _strings(metadata.get("sources")),
                "resumes": resume_names.get(fact_id, []),
                "search": {
                    "enabled": fact_id in selected,
                    "can_change": metadata.get("status") == "confirmed",
                    "disabled_reason": None
                    if metadata.get("status") == "confirmed"
                    else "Confirm this evidence before using it for search.",
                },
            }
        )
    return records


def _skill_query(skill: dict[str, Any]) -> ColdStartQuery:
    digest = hashlib.sha256(skill["id"].encode()).hexdigest()[:12]
    return ColdStartQuery(
        query_id=f"{VAULT_QUERY_PREFIX}{digest}",
        lane=ColdStartLane.CAPABILITY_COMBINATION,
        query=skill["title"],
        source_ids=[f"vault:{skill['id']}"],
        evidence_terms=[skill["title"]],
        reason="Confirmed career-vault skill selected for job-search expansion.",
    )


def _base_queries(root: Path, preferences: dict[str, Any]) -> tuple[list[ColdStartQuery], str]:
    path = root / PORTFOLIO_PATH
    if path.is_file():
        portfolio = ColdStartPortfolio.model_validate_json(path.read_text(encoding="utf-8"))
        return (
            [
                item
                for item in portfolio.queries
                if not item.query_id.startswith(VAULT_QUERY_PREFIX)
            ],
            portfolio.resume_hash,
        )
    queries = [
        ColdStartQuery(
            query_id=f"user-{hashlib.sha256(title.casefold().encode()).hexdigest()[:12]}",
            lane=ColdStartLane.ADJACENT_TITLE,
            query=title,
            source_ids=["user-confirmed-settings"],
            reason="Explicitly included in Search preferences.",
        )
        for title in preferences.get("desired_title_terms", [])
    ]
    return queries, "vault-skill-search"


def _portfolio(root: Path) -> ColdStartPortfolio:
    scaffold_job_search(root)
    path = root / PORTFOLIO_PATH
    if path.is_file():
        return load_portfolio(path)
    preferences = yaml.safe_load((root / PREFERENCES_PATH).read_text(encoding="utf-8"))
    queries, resume_hash = _base_queries(root, preferences)
    portfolio = ColdStartPortfolio(
        generated_at=datetime.now(UTC).isoformat(), resume_hash=resume_hash, queries=queries
    )
    save_portfolio(path, portfolio)
    return portfolio


def set_skill_search_enabled(root: Path, fact_id: str, enabled: bool) -> dict[str, Any]:
    """Select one canonical skill fact for managed capability searching."""
    skills = list_skills(root)
    by_id = {item["id"]: item for item in skills}
    skill = by_id.get(fact_id)
    if skill is None:
        raise ValueError("skill fact was not found")
    if enabled and not skill["search"]["can_change"]:
        raise ValueError("only confirmed vault skills can be used for search")
    portfolio = _portfolio(root)
    matching = [item for item in portfolio.queries if f"vault:{fact_id}" in item.source_ids]
    if enabled and not matching:
        portfolio = edit_portfolio(
            portfolio,
            operation="add",
            query_id=_skill_query(skill).query_id,
            query=skill["title"],
            lane=ColdStartLane.CAPABILITY_COMBINATION,
            source_ids=[f"vault:{fact_id}"],
            evidence_terms=[skill["title"]],
            reason="Confirmed career-vault skill selected for job-search expansion.",
        )
    elif not enabled:
        for item in matching:
            portfolio = edit_portfolio(portfolio, operation="remove", query_id=item.query_id)
    selected_count = sum(
        item.lane == ColdStartLane.CAPABILITY_COMBINATION and item.enabled
        for item in portfolio.queries
    )
    if selected_count > MAX_CAPABILITY_QUERIES:
        raise ValueError(f"choose at most {MAX_CAPABILITY_QUERIES} skills for search")
    check_query_capacity(item.query for item in portfolio.queries)
    apply_portfolio_update(
        root / PORTFOLIO_PATH,
        root / SEARCH_CONFIG_PATH,
        root / PORTFOLIO_BACKUP_PATH,
        root / CONFIG_BACKUP_PATH,
        portfolio,
    )
    return next(item for item in list_skills(root) if item["id"] == fact_id)
