#!/usr/bin/env python3
"""Validate direction profiles and audit resumes against their declared role shape."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from .atomic import atomic_write_text
from .compilation import compile_markdown
from .direction_diagnostics import direction_style_diagnostics, normalize_phrase, phrase_present
from .direction_schema import (
    ALLOWED_FIELDS,
    BASES,
    COPIED_LABEL_MIN_COVERAGE,
    MATURITIES,
    PAGE_FORMATS,
    SLUG,
    SOURCE_ID,
    SOURCE_KINDS,
    STATUSES,
    STYLE_MIN_CLAIM_BLOCKS,
    STYLE_MIN_TERM_OCCURRENCES,
    STYLE_MIN_WORD_SHARE,
    STYLE_TOKEN_EXCLUSIONS,
    iso_date,
    nonempty_string,
    parse_direction,
    string_list,
)
from .evidence import audit_claims, claim_blocks
from .layout import VaultLayout
from .pdf_rendering import extraction_blocks
from .rendering import contained_project_path, object_value
from .synthesis import SynthesisPlan, load_synthesis_plan
from .validation import parse_frontmatter

__all__ = [
    "ALLOWED_FIELDS",
    "BASES",
    "COPIED_LABEL_MIN_COVERAGE",
    "MATURITIES",
    "PAGE_FORMATS",
    "SLUG",
    "SOURCE_ID",
    "SOURCE_KINDS",
    "STATUSES",
    "STYLE_MIN_CLAIM_BLOCKS",
    "STYLE_MIN_TERM_OCCURRENCES",
    "STYLE_MIN_WORD_SHARE",
    "STYLE_TOKEN_EXCLUSIONS",
    "audit_direction",
    "direction_style_diagnostics",
    "fact_themes",
    "iso_date",
    "main",
    "nonempty_string",
    "normalize_phrase",
    "parse_direction",
    "phrase_present",
    "preview_direction_creation",
    "profile_paths",
    "project_direction_path",
    "string_list",
    "theme_reference_warnings",
]


def project_direction_path(path: Path, project_root: Path) -> Path:
    """Require a real direction profile under the project's directions folder."""
    resolved = contained_project_path(path, project_root, "directions", "direction profile")
    if resolved.name == "README.md" or resolved.name.endswith(".template.md"):
        raise ValueError("direction profile must not be README.md or a template")
    if resolved.suffix != ".md":
        raise ValueError("direction profile must use a .md extension")
    return resolved


def profile_paths(project_root: Path, requested: list[Path]) -> list[Path]:
    """Resolve requested profiles or discover all canonical profiles."""
    if requested:
        return [project_direction_path(path, project_root) for path in requested]
    directory = (project_root / "directions").resolve()
    return [
        path
        for path in sorted(directory.glob("*.md"))
        if path.name != "README.md" and not path.name.endswith(".template.md")
    ]


def preview_direction_creation(
    draft: Path,
    project_root: Path,
) -> tuple[Path, str, dict[str, Any]]:
    """Validate one initial private direction draft and resolve its canonical target."""
    source = contained_project_path(
        draft,
        project_root,
        "build/direction-drafts",
        "direction draft",
    )
    if source.suffix != ".md":
        raise ValueError("direction draft must use a .md extension")
    profile, _ = parse_direction(source)
    if profile["status"] != "draft" or profile["maturity"] != "provisional":
        raise ValueError("a new direction must begin as draft and provisional")
    target = project_root / "directions" / f"{profile['slug']}.md"
    if target.exists():
        raise ValueError(f"direction already exists: {target.relative_to(project_root)}")
    return target, source.read_text(encoding="utf-8"), profile


def fact_themes(vault_root: Path) -> dict[str, set[str]]:
    """Load fact-to-theme mappings from the configured vault."""
    layout = VaultLayout.load(vault_root)
    result: dict[str, set[str]] = {}
    for path in sorted(layout.facts.rglob("*.md")):
        metadata, _ = parse_frontmatter(path)
        fact_id = metadata.get("id")
        themes = metadata.get("themes")
        if isinstance(fact_id, str) and isinstance(themes, list):
            result[fact_id] = {item for item in themes if isinstance(item, str)}
    return result


def theme_reference_warnings(profile: dict[str, Any], vault_root: Path) -> list[str]:
    """Report concepts that currently have no matching vault evidence theme."""
    known = set().union(*fact_themes(vault_root).values())
    warnings: list[str] = []
    concepts = profile.get("priority_concepts")
    assert isinstance(concepts, list)
    for index, raw_concept in enumerate(concepts):
        concept = object_value(raw_concept, f"priority_concepts[{index}]")
        referenced = set(
            string_list(
                concept.get("evidence_themes"), f"priority_concepts[{index}].evidence_themes"
            )
        )
        unknown = sorted(referenced - known)
        if unknown:
            warnings.append(
                f"priority_concepts[{index}] has themes absent from the vault (candidate gap): "
                f"{unknown}"
            )
    return warnings


def audit_direction(
    profile: dict[str, Any],
    payload: dict[str, Any],
    vault_root: Path,
    *,
    plan: SynthesisPlan | None = None,
) -> dict[str, Any]:
    """Score evidence coverage and report terminology as a separate retrieval signal."""
    visible = normalize_phrase(" ".join(value for _, value in extraction_blocks(payload)))
    blocks = claim_blocks(payload)
    selected_ids = {fact_id for _, _, ids, _ in blocks for fact_id in ids}
    experience_ids = {
        fact_id
        for owner, _, ids, _ in blocks
        if owner.startswith(("experience[", "projects["))
        for fact_id in ids
    }
    summary_ids = {fact_id for owner, _, ids, _ in blocks if owner == "summary" for fact_id in ids}
    listed_only_ids = selected_ids - experience_ids - summary_ids
    fit_by_concept = (
        {item.concept_id: item for item in plan.concept_fit} if plan is not None else {}
    )
    themes = fact_themes(vault_root)
    total_weight = 0
    evidence_earned = 0
    experience_evidence_earned = 0
    vocabulary_earned = 0
    concept_results: list[dict[str, Any]] = []
    concepts = profile["priority_concepts"]
    assert isinstance(concepts, list)
    for raw_concept in concepts:
        concept = object_value(raw_concept, "priority concept")
        weight = concept["weight"]
        assert isinstance(weight, int)
        terms = string_list(concept["terms"], "terms")
        expected_themes = set(string_list(concept["evidence_themes"], "evidence_themes"))
        matched_terms = [term for term in terms if phrase_present(term, visible)]
        matched_facts = sorted(
            fact_id for fact_id in selected_ids if themes.get(fact_id, set()) & expected_themes
        )
        matched_experience_facts = sorted(set(matched_facts) & experience_ids)
        matched_summary_only_facts = sorted((set(matched_facts) & summary_ids) - experience_ids)
        matched_listed_only_facts = sorted(set(matched_facts) & listed_only_ids)
        matched_claims: list[dict[str, Any]] = []
        for owner, claim, ids, _ in blocks:
            claim_text = normalize_phrase(claim)
            claim_terms = [term for term in terms if phrase_present(term, claim_text)]
            claim_facts = sorted(
                fact_id for fact_id in ids if themes.get(fact_id, set()) & expected_themes
            )
            if claim_terms and claim_facts:
                matched_claims.append(
                    {"owner": owner, "terms": claim_terms, "evidence_fact_ids": claim_facts}
                )
        evidence_fraction = 1 if matched_facts else 0
        experience_evidence_fraction = 1 if matched_experience_facts else 0
        vocabulary_fraction = 1 if matched_terms else 0
        alignment_fraction = (
            1.0 if matched_claims else 0.5 if matched_terms or matched_facts else 0.0
        )
        total_weight += weight
        evidence_earned += weight * evidence_fraction
        experience_evidence_earned += weight * experience_evidence_fraction
        vocabulary_earned += weight * vocabulary_fraction
        concept_id = str(concept["id"])
        planned_fit = fit_by_concept.get(concept_id)
        concept_results.append(
            {
                "id": concept_id,
                "label": concept["label"],
                "weight": weight,
                "coverage": "full" if evidence_fraction else "missing",
                "evidence_coverage": "full" if evidence_fraction else "missing",
                "vocabulary_coverage": "full" if vocabulary_fraction else "missing",
                "alignment_coverage": (
                    "full"
                    if alignment_fraction == 1
                    else "partial"
                    if alignment_fraction
                    else "missing"
                ),
                "matched_terms": matched_terms,
                "evidence_fact_ids": matched_facts,
                "experience_evidence_fact_ids": matched_experience_facts,
                "summary_only_fact_ids": matched_summary_only_facts,
                "listed_only_fact_ids": matched_listed_only_facts,
                "planned_fit": planned_fit.status if planned_fit is not None else "not-recorded",
                "matched_claims": matched_claims,
            }
        )
    evidence_score = round((evidence_earned / total_weight) * 100) if total_weight else 0
    experience_evidence_score = (
        round((experience_evidence_earned / total_weight) * 100) if total_weight else 0
    )
    vocabulary_score = round((vocabulary_earned / total_weight) * 100) if total_weight else 0
    avoid_terms = string_list(profile.get("avoid_terms", []), "avoid_terms", required=False)
    avoid_found = [term for term in avoid_terms if phrase_present(term, visible)]
    de_emphasize = string_list(profile.get("de_emphasize", []), "de_emphasize", required=False)
    de_emphasized_found = [term for term in de_emphasize if phrase_present(term, visible)]
    defaults = object_value(profile["defaults"], "defaults")
    minimum = defaults["minimum_coverage"]
    assert isinstance(minimum, int)
    expected_format = defaults["page_format"]
    actual_format = payload.get("page_format", "letter")
    page_format_matches = actual_format == expected_format
    essential_terms = string_list(
        profile.get("essential_terms", []), "essential_terms", required=False
    )
    essential_found = [term for term in essential_terms if phrase_present(term, visible)]
    essential_missing = [term for term in essential_terms if term not in essential_found]
    style_diagnostics = direction_style_diagnostics(profile, blocks)
    style_warnings = [
        *(
            [
                "configured direction vocabulary is unusually concentrated; review repeated "
                "target terms instead of changing the direction profile to improve the audit"
            ]
            if style_diagnostics["target_term_concentration"]
            else []
        ),
        *(
            [
                "competencies closely repeat direction concept labels; keep only labels that "
                "improve scanning and are supported by the experience story"
            ]
            if style_diagnostics["copied_concept_labels"]
            else []
        ),
    ]
    evidence_passes = (
        evidence_score >= minimum
        and not essential_missing
        and not avoid_found
        and page_format_matches
    )
    fit_breakdown = {
        status: sorted(item.concept_id for item in fit_by_concept.values() if item.status == status)
        for status in ("demonstrated", "transferable", "unsupported")
    }
    return {
        "score": evidence_score,
        "evidence_score": evidence_score,
        "experience_evidence_score": experience_evidence_score,
        "vocabulary_score": vocabulary_score,
        "minimum_coverage": minimum,
        "passes": evidence_passes,
        "evidence_passes": evidence_passes,
        "editorial_status": "not-reviewed",
        "target_mode": plan.target_mode if plan is not None else None,
        "fit_breakdown": fit_breakdown,
        "concepts": concept_results,
        "essential_terminology": {
            "terms": essential_terms,
            "found": essential_found,
            "missing": essential_missing,
            "passes": not essential_missing,
        },
        "vocabulary_advisory": {
            "score": vocabulary_score,
            "missing_concept_ids": [
                str(concept["id"])
                for concept in concept_results
                if concept["vocabulary_coverage"] == "missing"
            ],
            "changes_pass_fail": False,
        },
        "style_diagnostics": style_diagnostics,
        "avoid_terms_found": avoid_found,
        "de_emphasized_terms_found": de_emphasized_found,
        "selected_fact_ids": sorted(selected_ids),
        "experience_fact_ids": sorted(experience_ids),
        "summary_fact_ids": sorted(summary_ids),
        "listed_only_fact_ids": sorted(listed_only_ids),
        "page_defaults": {
            "expected_format": expected_format,
            "actual_format": actual_format,
            "format_matches": page_format_matches,
            "max_pages": defaults["max_pages"],
        },
        "warnings": [
            *theme_reference_warnings(profile, vault_root),
            *(["direction profile is still draft"] if profile.get("status") == "draft" else []),
            *(
                ["direction role shape is provisional and may improve with research"]
                if profile.get("maturity") == "provisional"
                else []
            ),
            *style_warnings,
        ],
    }


def main(argv: Sequence[str] | None = None) -> int:
    """Validate direction profiles or audit one canonical resume."""
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="action", required=True)
    validate_parser = subparsers.add_parser("validate", help="Validate direction profiles")
    validate_parser.add_argument("profiles", nargs="*", type=Path)
    validate_parser.add_argument("--vault-root", type=Path, default=Path("vault"))
    audit_parser = subparsers.add_parser("audit", help="Audit a resume against a direction")
    audit_parser.add_argument("profile", type=Path)
    audit_parser.add_argument("resume", type=Path)
    audit_parser.add_argument("--vault-root", type=Path, default=Path("vault"))
    create_parser = subparsers.add_parser(
        "create",
        help="Preview or apply a validated initial direction draft",
    )
    create_parser.add_argument("draft", type=Path)
    create_parser.add_argument("--vault-root", type=Path, default=Path("vault"))
    create_parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    try:
        vault_root = args.vault_root.expanduser().resolve()
        project_root = vault_root.parent
        if args.action == "validate":
            paths = profile_paths(project_root, args.profiles)
            validated = []
            warnings: list[str] = []
            for path in paths:
                metadata, _ = parse_direction(path)
                warnings.extend(
                    f"{path.relative_to(project_root).as_posix()}: {warning}"
                    for warning in theme_reference_warnings(metadata, vault_root)
                )
                validated.append(
                    {
                        "path": path.relative_to(project_root).as_posix(),
                        "slug": metadata["slug"],
                        "status": metadata["status"],
                        "maturity": metadata["maturity"],
                    }
                )
            result = {
                "valid": True,
                "profiles": validated,
                "count": len(validated),
                "warnings": warnings,
            }
        elif args.action == "audit":
            profile_path = project_direction_path(args.profile, project_root)
            resume_path = contained_project_path(args.resume, project_root, "resumes", "resume")
            profile, _ = parse_direction(profile_path)
            payload = compile_markdown(resume_path.read_text(encoding="utf-8"))
            grounding = audit_claims(payload, vault_root)
            plan_path = project_root / "resumes" / "plans" / f"{resume_path.stem}.yaml"
            plan = None
            if plan_path.is_file():
                candidate_plan = load_synthesis_plan(plan_path, project_root, vault_root)
                if (
                    candidate_plan.resume == resume_path
                    and candidate_plan.direction == profile_path
                ):
                    plan = candidate_plan
            audit = audit_direction(profile, payload, vault_root, plan=plan)
            result = {
                "valid": True,
                "direction": profile_path.relative_to(project_root).as_posix(),
                "resume": resume_path.relative_to(project_root).as_posix(),
                "grounding": grounding,
                **audit,
            }
        else:
            target, content, profile = preview_direction_creation(
                args.draft,
                project_root,
            )
            if args.apply:
                atomic_write_text(target, content)
            result = {
                "valid": True,
                "applied": args.apply,
                "draft": args.draft.resolve().relative_to(project_root).as_posix(),
                "target": target.relative_to(project_root).as_posix(),
                "slug": profile["slug"],
                "status": profile["status"],
                "maturity": profile["maturity"],
            }
    except (OSError, ValueError) as exc:
        print(json.dumps({"error": str(exc)}, indent=2), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    return 0 if result.get("passes", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
