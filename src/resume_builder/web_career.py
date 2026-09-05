"""Read-only career-library views and vault-backed job-search skill signals."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import quote

import yaml

from .artifact_paths import resume_output_base
from .discovery_activation import (
    apply_portfolio_update,
    edit_portfolio,
    load_portfolio,
    save_portfolio,
)
from .discovery_portfolio import (
    MAX_CAPABILITY_QUERIES,
    MAX_TOTAL_QUERIES,
    ColdStartLane,
    ColdStartPortfolio,
    ColdStartQuery,
)
from .job_setup_defaults import PORTFOLIO_PATH, PREFERENCES_PATH, scaffold_job_search
from .layout import VaultLayout
from .project_report import project_report
from .resume_parser import compile_markdown
from .source_import import is_metadata_name, load_manifest, resume_manifest_sources
from .validation import parse_frontmatter

SEARCH_CONFIG_PATH = Path("job-search/config/search.yml")
VAULT_QUERY_PREFIX = "vault-skill-"
PORTFOLIO_BACKUP_PATH = Path("build/job-search/portfolio-before-last-portal-change.json")
CONFIG_BACKUP_PATH = Path("build/job-search/search-before-last-portal-change.yml")


def _preview_url(resume_id: str) -> str:
    return f"/api/resume-preview?resume_id={quote(resume_id, safe='')}"


def _generated_preview(root: Path, resume: Path) -> Path | None:
    candidate = resume_output_base(root, resume).with_suffix(".html")
    return candidate if candidate.is_file() else None


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
    rendered = _generated_preview(root, candidate)
    if rendered is None:
        raise ValueError("this resume does not have an HTML preview yet")
    return {
        "path": rendered,
        "filename": f"{candidate.stem}.html",
        "media_type": "text/html; charset=utf-8",
    }


def _display_name(path: Path, payload: dict[str, Any] | None = None) -> str:
    candidate = payload.get("candidate") if isinstance(payload, dict) else None
    headline = candidate.get("headline") if isinstance(candidate, dict) else None
    return str(headline).strip() if headline else path.stem.replace("-", " ").title()


def _generated_status(record: dict[str, Any]) -> tuple[str, str]:
    if record.get("mint", {}).get("status") == "current":
        return "Ready", "positive"
    if record.get("preview", {}).get("status") == "current":
        return "In review", "attention"
    if record.get("build", {}).get("status") == "current":
        return "Built", "neutral"
    statuses = [
        record.get(owner, {}).get("status") for owner in ("build", "critique", "preview", "mint")
    ]
    if "invalid" in statuses:
        return "Needs attention", "negative"
    return "Draft", "neutral"


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
    """Adapt canonical sources and project status into a presentation-ready library."""
    layout = VaultLayout.load(root / "vault", allow_missing=True)
    grouped_originals: dict[str, dict[str, Any]] = {}
    for source in resume_manifest_sources(load_manifest(layout)):
        names = [name for name in source.get("filenames", []) if not is_metadata_name(name)]
        if not names:
            continue
        source_name = str(names[0])
        source_path = PurePosixPath(source_name)
        group_id = source_path.with_suffix("").as_posix().casefold()
        item = grouped_originals.get(group_id)
        if item is None:
            item = {
                "id": source["id"],
                "name": source_path.with_suffix("").as_posix(),
                "kind": "original",
                "status_label": "Imported",
                "status_tone": "neutral",
                "updated_at": source.get("refreshed_at") or source.get("imported_at"),
                "formats": set(),
                "has_empty_source": False,
                "preview_url": None,
                "preview_message": "Directional resumes include a formatted HTML preview.",
            }
            grouped_originals[group_id] = item
        item["formats"].add(str(source.get("format") or "source").upper())
        item["has_empty_source"] = (
            item["has_empty_source"] or source.get("extraction_status") != "ok"
        )
        updated_at = source.get("refreshed_at") or source.get("imported_at")
        if updated_at and str(updated_at) > str(item.get("updated_at") or ""):
            item["updated_at"] = updated_at

    originals = []
    for item in grouped_originals.values():
        formats = ", ".join(sorted(item.pop("formats")))
        has_empty_source = bool(item.pop("has_empty_source"))
        item.update(
            {
                "detail": f"{formats} · Base resume",
                "error": "No readable text was extracted from one format."
                if has_empty_source
                else None,
            }
        )
        originals.append(item)
    originals.sort(key=lambda item: str(item["name"]).casefold())

    report = project_report(root / "vault", strict=False)
    generated: dict[str, list[dict[str, Any]]] = {"directional": [], "tailored": []}
    for record in report["resumes"]:
        path = root / record["path"]
        try:
            payload = compile_markdown(path.read_text(encoding="utf-8"))
            error = None
        except (OSError, ValueError) as exc:
            payload = None
            error = str(exc)
        status_label, status_tone = _generated_status(record)
        kind = "directional" if record["kind"] == "baseline" else "tailored"
        rendered = _generated_preview(root, path)
        direction = record.get("direction")
        detail = (
            f"Direction · {Path(direction).stem.replace('-', ' ').title()}"
            if kind == "directional" and direction
            else "Reusable role direction"
            if kind == "directional"
            else "Job-specific resume"
        )
        generated[kind].append(
            {
                "id": record["path"],
                "name": _display_name(path, payload),
                "kind": kind,
                "status_label": "Needs attention" if error else status_label,
                "status_tone": "negative" if error else status_tone,
                "updated_at": datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat(),
                "detail": detail,
                "skill_fact_ids": sorted(_all_evidence_ids(payload or {})),
                "error": error,
                "preview_url": _preview_url(record["path"]) if rendered else None,
                "preview_message": (
                    None if rendered else "This resume does not have an HTML preview yet."
                ),
            }
        )
    return {
        "sections": [
            {
                "id": "originals",
                "title": "Base resumes",
                "description": "Resume sources used to build role-specific versions.",
                "items": originals,
            },
            {
                "id": "directional",
                "title": "Directional resumes",
                "description": "Reusable resumes built for a role direction.",
                "items": generated["directional"],
            },
            {
                "id": "tailored",
                "title": "Tailored resumes",
                "description": "Job-specific versions kept with application history.",
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
    if len(portfolio.queries) > MAX_TOTAL_QUERIES:
        raise ValueError("remove a role or skill before adding another search signal")
    apply_portfolio_update(
        root / PORTFOLIO_PATH,
        root / SEARCH_CONFIG_PATH,
        root / PORTFOLIO_BACKUP_PATH,
        root / CONFIG_BACKUP_PATH,
        portfolio,
    )
    return next(item for item in list_skills(root) if item["id"] == fact_id)
