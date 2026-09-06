"""Career-library views and résumé lifecycle actions."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

import yaml

from .applications import (
    RESUME_SNAPSHOT_ROOT,
    iter_records,
    load_record,
    preserve_application_resume_snapshots,
)
from .artifact_paths import resume_output_base
from .atomic import atomic_write_text
from .ats import normalize_payload
from .project_report import project_report
from .rendering import known_fact_ids, render_payload
from .resume_parser import compile_markdown
from .resume_templates import load_rendering_theme, rendering_theme_text
from .source_import import is_metadata_name


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
        (root / "resumes" / "archived").resolve(),
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


def directional_resume_removal_impact(root: Path, resume_id: str) -> dict[str, Any]:
    """Describe a recoverable removal without changing resume or vault state."""
    candidate = (root / resume_id).resolve()
    baseline_root = (root / "resumes" / "baselines").resolve()
    if (
        candidate.suffix.casefold() != ".md"
        or not candidate.is_file()
        or not candidate.is_relative_to(baseline_root)
    ):
        raise ValueError("directional resume was not found")
    relative = candidate.relative_to(root.resolve()).as_posix()
    applications = []
    for _, record in iter_records(root / "applications"):
        resume = record["application"].get("resume")
        if isinstance(resume, dict) and resume.get("path") == relative:
            applications.append(
                {
                    "id": record["application"]["id"],
                    "company": record["application"]["company"],
                    "role": record["application"]["role"],
                }
            )
    return {
        "kind": "resume_removal",
        "action": "retire" if applications else "archive",
        "resume_id": relative,
        "name": candidate.stem.replace("-", " ").title(),
        "revision": hashlib.sha256(candidate.read_bytes()).hexdigest(),
        "application_references": applications,
        "vault_unchanged": True,
        "tailored_resumes_unchanged": True,
    }


def archive_directional_resume(root: Path, impact: dict[str, Any]) -> dict[str, Any]:
    """Archive a directional resume after rechecking the proposed impact."""
    current = directional_resume_removal_impact(root, str(impact.get("resume_id") or ""))
    if current["revision"] != impact.get("revision"):
        raise ValueError("The resume changed after removal was proposed. Review it again.")
    source = root / current["resume_id"]
    destination = root / "resumes" / "archived" / source.name
    if destination.exists():
        raise ValueError("An archived resume with this name already exists.")
    preservation = preserve_application_resume_snapshots(
        root / "applications", root, current["resume_id"]
    )
    if preservation["blocked"]:
        raise ValueError(
            "The original application résumé could not be preserved, so this résumé was not retired."
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    source.replace(destination)
    return {
        "archived": True,
        "retired": bool(current["application_references"]),
        "message": (
            "Directional résumé retired. Application copies and vault evidence were preserved."
            if current["application_references"]
            else "Directional résumé removed. Vault evidence and tailored résumés were unchanged."
        ),
        "archive_path": destination.relative_to(root).as_posix(),
    }


def restore_directional_resume(
    root: Path, resume_id: str, *, expected_revision: str | None = None
) -> dict[str, Any]:
    """Restore one archived directional résumé to the active library."""
    candidate = (root / resume_id).resolve()
    archived_root = (root / "resumes" / "archived").resolve()
    if (
        candidate.suffix.casefold() != ".md"
        or not candidate.is_file()
        or not candidate.is_relative_to(archived_root)
    ):
        raise ValueError("retired résumé was not found")
    if (
        expected_revision is not None
        and hashlib.sha256(candidate.read_bytes()).hexdigest() != expected_revision
    ):
        raise ValueError(
            "The retired résumé changed after restoration was proposed. Review it again."
        )
    destination = root / "resumes" / "baselines" / candidate.name
    if destination.exists():
        raise ValueError("An active résumé with this name already exists")
    destination.parent.mkdir(parents=True, exist_ok=True)
    candidate.replace(destination)
    return {
        "restored": True,
        "resume_id": destination.relative_to(root).as_posix(),
        "message": "Directional résumé restored for future matching.",
    }


def resolve_application_resume_preview(root: Path, application_id: str) -> dict[str, Any]:
    """Resolve the exact immutable résumé copy attached to one application."""
    if not application_id.startswith("APP-") or any(
        character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-"
        for character in application_id
    ):
        raise ValueError("application was not found")
    record = load_record(root / "applications" / f"{application_id}.json")
    artifact = record["application"].get("resume")
    if not isinstance(artifact, dict):
        raise ValueError("this application does not have a recorded résumé")
    snapshot_value = artifact.get("snapshot_path")
    if not isinstance(snapshot_value, str):
        raise ValueError("this older application does not have a preserved résumé copy")
    snapshot = (root / snapshot_value).resolve()
    allowed = (root / "applications" / RESUME_SNAPSHOT_ROOT).resolve()
    if not snapshot.is_relative_to(allowed) or not snapshot.is_file():
        raise ValueError("the preserved application résumé is unavailable")
    if hashlib.sha256(snapshot.read_bytes()).hexdigest() != artifact.get("sha256"):
        raise ValueError("the preserved application résumé failed its integrity check")
    if snapshot.suffix.casefold() == ".md":
        rendered = _render_portal_preview(root, snapshot)
        return {
            "path": rendered,
            "filename": f"{record['application']['company']}-{record['application']['role']}.html",
            "media_type": "text/html; charset=utf-8",
        }
    if snapshot.suffix.casefold() == ".pdf":
        return {
            "path": snapshot,
            "filename": f"{record['application']['company']}-{record['application']['role']}.pdf",
            "media_type": "application/pdf",
        }
    raise ValueError("this preserved résumé format cannot be previewed")


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
    retired: list[dict[str, Any]] = []
    for path in sorted((root / "resumes" / "archived").glob("*.md")):
        if is_metadata_name(path.name):
            continue
        try:
            payload = compile_markdown(path.read_text(encoding="utf-8"))
            error = None
        except (OSError, ValueError) as exc:
            payload = None
            error = str(exc)
        relative = path.relative_to(root).as_posix()
        references = sum(
            1
            for _, record in iter_records(root / "applications")
            if isinstance(record["application"].get("resume"), dict)
            and record["application"]["resume"].get("path") == f"resumes/baselines/{path.name}"
        )
        retired.append(
            {
                "id": relative,
                "name": _display_name(path, payload),
                "kind": "directional",
                "status": "retired",
                "updated_at": datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat(),
                "detail": (
                    f"Retired · preserved for {references} application"
                    f"{'s' if references != 1 else ''}"
                    if references
                    else "Retired direction"
                ),
                "skill_fact_ids": sorted(_all_evidence_ids(payload or {})),
                "error": error,
                "preview_url": _preview_url(relative, path.stat().st_mtime_ns)
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
            {
                "id": "retired",
                "title": "Retired resumes",
                "description": "Hidden from future matching; preserved when applications used them.",
                "items": retired,
            },
        ]
    }


def resolve_directional_resume_reference(root: Path, reference: str) -> str:
    """Resolve a portal-visible name or stable ID without accepting arbitrary paths."""
    requested = reference.strip().casefold()
    if not requested:
        raise ValueError("Choose a directional resume")
    directional = next(
        section for section in list_resumes(root)["sections"] if section["id"] == "directional"
    )
    exact_ids = [item for item in directional["items"] if item["id"].casefold() == requested]
    matches = exact_ids or [
        item for item in directional["items"] if item["name"].casefold() == requested
    ]
    if not matches:
        raise ValueError("No directional resume matches that name")
    if len(matches) > 1:
        raise ValueError("More than one directional resume has that name; open the one to remove")
    return str(matches[0]["id"])


def resolve_retired_resume_reference(root: Path, reference: str) -> str:
    """Resolve one portal-visible retired résumé without accepting arbitrary paths."""
    requested = reference.strip().casefold()
    if not requested:
        raise ValueError("Choose a retired résumé")
    retired = next(
        section for section in list_resumes(root)["sections"] if section["id"] == "retired"
    )
    exact_ids = [item for item in retired["items"] if item["id"].casefold() == requested]
    matches = exact_ids or [
        item for item in retired["items"] if item["name"].casefold() == requested
    ]
    if not matches:
        raise ValueError("No retired résumé matches that name")
    if len(matches) > 1:
        raise ValueError("More than one retired résumé has that name")
    return str(matches[0]["id"])
