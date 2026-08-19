#!/usr/bin/env python3
"""Validate direction profiles and audit resumes against their declared role shape."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from collections.abc import Sequence
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml

from .atomic import atomic_write_text
from .compilation import compile_markdown
from .evidence import audit_claims, claim_blocks
from .layout import VaultLayout
from .pdf_rendering import extraction_blocks
from .rendering import contained_project_path, object_value
from .synthesis import SynthesisPlan, load_synthesis_plan
from .validation import parse_frontmatter

SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
SOURCE_ID = re.compile(r"^DIRSRC-\d{3}$")
STATUSES = {"draft", "approved"}
MATURITIES = {"provisional", "researched", "outcome-validated"}
BASES = {"user-confirmed", "research-supported", "outcome-supported", "needs-review"}
SOURCE_KINDS = {"user", "research", "outcome"}
PAGE_FORMATS = {"letter", "a4"}
STYLE_TOKEN_EXCLUSIONS = {
    "across",
    "engineering",
    "management",
    "operations",
    "support",
    "technical",
    "through",
}
STYLE_MIN_TERM_OCCURRENCES = 12
STYLE_MIN_CLAIM_BLOCKS = 6
STYLE_MIN_WORD_SHARE = 0.025
COPIED_LABEL_MIN_COVERAGE = 0.8
ALLOWED_FIELDS = {
    "schema_version",
    "slug",
    "status",
    "maturity",
    "target_titles",
    "audiences",
    "positioning",
    "essential_terms",
    "priority_concepts",
    "de_emphasize",
    "avoid_terms",
    "defaults",
    "success_criteria",
    "sources",
}


def nonempty_string(value: object, owner: str) -> str:
    """Require one non-empty string."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{owner} must be a non-empty string")
    return value.strip()


def string_list(value: object, owner: str, *, required: bool = True) -> list[str]:
    """Require a list of unique non-empty strings."""
    if not isinstance(value, list) or (required and not value):
        raise ValueError(f"{owner} must be a{' non-empty' if required else ''} list of strings")
    if not all(isinstance(item, str) and item.strip() for item in value):
        raise ValueError(f"{owner} must contain only non-empty strings")
    normalized = [item.strip() for item in value]
    if len(set(normalized)) != len(normalized):
        raise ValueError(f"{owner} must not contain duplicates")
    return normalized


def iso_date(value: object, owner: str) -> str:
    """Accept YAML dates or strict ISO date strings."""
    if isinstance(value, date):
        return value.isoformat()
    text = nonempty_string(value, owner)
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError as exc:
        raise ValueError(f"{owner} must use YYYY-MM-DD") from exc


def parse_direction(path: Path) -> tuple[dict[str, Any], str]:
    """Load and validate a direction profile's versioned frontmatter."""
    try:
        markdown = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"cannot read direction profile: {exc}") from exc
    if not markdown.startswith("---\n"):
        raise ValueError("direction profile must begin with YAML frontmatter")
    try:
        raw, body = markdown[4:].split("\n---\n", 1)
    except ValueError as exc:
        raise ValueError("direction profile frontmatter is not closed with ---") from exc
    try:
        metadata = object_value(yaml.safe_load(raw), "direction frontmatter")
    except yaml.YAMLError as exc:
        raise ValueError(f"invalid direction frontmatter: {exc}") from exc
    unexpected = sorted(set(metadata) - ALLOWED_FIELDS)
    if unexpected:
        raise ValueError(f"direction profile contains unsupported fields: {unexpected}")
    if metadata.get("schema_version") != 1:
        raise ValueError("direction profile must declare schema_version 1")
    slug = nonempty_string(metadata.get("slug"), "slug")
    if not SLUG.fullmatch(slug):
        raise ValueError("slug must use lowercase kebab-case")
    if path.stem != slug:
        raise ValueError(f"direction filename must match slug: expected {slug}.md")
    status = nonempty_string(metadata.get("status"), "status")
    if status not in STATUSES:
        raise ValueError(f"status must be one of {sorted(STATUSES)}")
    maturity = nonempty_string(metadata.get("maturity"), "maturity")
    if maturity not in MATURITIES:
        raise ValueError(f"maturity must be one of {sorted(MATURITIES)}")
    string_list(metadata.get("target_titles"), "target_titles")
    string_list(metadata.get("audiences"), "audiences")
    nonempty_string(metadata.get("positioning"), "positioning")
    essential_terms = string_list(
        metadata.get("essential_terms", []), "essential_terms", required=False
    )
    if len(essential_terms) > 5:
        raise ValueError("essential_terms must contain no more than 5 terms")
    string_list(metadata.get("de_emphasize", []), "de_emphasize", required=False)
    string_list(metadata.get("avoid_terms", []), "avoid_terms", required=False)
    string_list(metadata.get("success_criteria"), "success_criteria")

    sources = metadata.get("sources")
    if not isinstance(sources, list) or not sources:
        raise ValueError("sources must be a non-empty list")
    source_ids: set[str] = set()
    source_kind_by_id: dict[str, str] = {}
    source_kinds: set[str] = set()
    for index, raw_source in enumerate(sources):
        source = object_value(raw_source, f"sources[{index}]")
        allowed = {"id", "kind", "reference", "as_of", "url"}
        if unexpected_source := sorted(set(source) - allowed):
            raise ValueError(f"sources[{index}] contains unsupported fields: {unexpected_source}")
        source_id = nonempty_string(source.get("id"), f"sources[{index}].id")
        if not SOURCE_ID.fullmatch(source_id):
            raise ValueError(f"sources[{index}].id must use DIRSRC-NNN")
        if source_id in source_ids:
            raise ValueError(f"duplicate direction source ID: {source_id}")
        source_ids.add(source_id)
        kind = nonempty_string(source.get("kind"), f"sources[{index}].kind")
        if kind not in SOURCE_KINDS:
            raise ValueError(f"sources[{index}].kind must be one of {sorted(SOURCE_KINDS)}")
        source_kinds.add(kind)
        source_kind_by_id[source_id] = kind
        nonempty_string(source.get("reference"), f"sources[{index}].reference")
        iso_date(source.get("as_of"), f"sources[{index}].as_of")
        if "url" in source:
            url = nonempty_string(source.get("url"), f"sources[{index}].url")
            parsed = urlparse(url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ValueError(f"sources[{index}].url must be an http or https URL")

    if maturity == "researched" and "research" not in source_kinds:
        raise ValueError("researched directions require at least one research source")
    if maturity == "outcome-validated" and "outcome" not in source_kinds:
        raise ValueError("outcome-validated directions require at least one outcome source")

    concepts = metadata.get("priority_concepts")
    if not isinstance(concepts, list) or not concepts:
        raise ValueError("priority_concepts must be a non-empty list")
    concept_ids: set[str] = set()
    concept_bases: set[str] = set()
    for index, raw_concept in enumerate(concepts):
        concept = object_value(raw_concept, f"priority_concepts[{index}]")
        allowed = {"id", "label", "weight", "terms", "evidence_themes", "basis", "source_ids"}
        if unexpected_concept := sorted(set(concept) - allowed):
            raise ValueError(
                f"priority_concepts[{index}] contains unsupported fields: {unexpected_concept}"
            )
        concept_id = nonempty_string(concept.get("id"), f"priority_concepts[{index}].id")
        if not SLUG.fullmatch(concept_id):
            raise ValueError(f"priority_concepts[{index}].id must use lowercase kebab-case")
        if concept_id in concept_ids:
            raise ValueError(f"duplicate priority concept ID: {concept_id}")
        concept_ids.add(concept_id)
        nonempty_string(concept.get("label"), f"priority_concepts[{index}].label")
        weight = concept.get("weight")
        if not isinstance(weight, int) or isinstance(weight, bool) or not 1 <= weight <= 5:
            raise ValueError(f"priority_concepts[{index}].weight must be an integer from 1 to 5")
        string_list(concept.get("terms"), f"priority_concepts[{index}].terms")
        string_list(concept.get("evidence_themes"), f"priority_concepts[{index}].evidence_themes")
        basis = nonempty_string(concept.get("basis"), f"priority_concepts[{index}].basis")
        if basis not in BASES:
            raise ValueError(f"priority_concepts[{index}].basis must be one of {sorted(BASES)}")
        concept_bases.add(basis)
        linked_sources = string_list(
            concept.get("source_ids", []),
            f"priority_concepts[{index}].source_ids",
            required=basis != "needs-review",
        )
        unknown_sources = sorted(set(linked_sources) - source_ids)
        if unknown_sources:
            raise ValueError(
                f"priority_concepts[{index}] cites unknown direction sources: {unknown_sources}"
            )
        expected_kind = {
            "user-confirmed": "user",
            "research-supported": "research",
            "outcome-supported": "outcome",
        }.get(basis)
        if expected_kind and not any(
            source_kind_by_id[source_id] == expected_kind for source_id in linked_sources
        ):
            raise ValueError(
                f"priority_concepts[{index}] basis {basis} requires a {expected_kind} source"
            )
        if status == "approved" and basis == "needs-review":
            raise ValueError("approved directions cannot contain needs-review concepts")
    if maturity == "researched" and "research-supported" not in concept_bases:
        raise ValueError("researched directions require at least one research-supported concept")
    if maturity == "outcome-validated" and "outcome-supported" not in concept_bases:
        raise ValueError(
            "outcome-validated directions require at least one outcome-supported concept"
        )

    defaults = object_value(metadata.get("defaults"), "defaults")
    if unexpected_defaults := sorted(
        set(defaults) - {"max_pages", "page_format", "minimum_coverage"}
    ):
        raise ValueError(f"defaults contains unsupported fields: {unexpected_defaults}")
    max_pages = defaults.get("max_pages")
    if not isinstance(max_pages, int) or isinstance(max_pages, bool) or max_pages < 1:
        raise ValueError("defaults.max_pages must be a positive integer")
    if defaults.get("page_format") not in PAGE_FORMATS:
        raise ValueError(f"defaults.page_format must be one of {sorted(PAGE_FORMATS)}")
    minimum = defaults.get("minimum_coverage")
    if not isinstance(minimum, int) or isinstance(minimum, bool) or not 0 <= minimum <= 100:
        raise ValueError("defaults.minimum_coverage must be an integer from 0 to 100")
    if not body.strip().startswith("# "):
        raise ValueError("direction profile body must begin with a level-one heading")
    return metadata, body.strip()


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


def normalize_phrase(value: str) -> str:
    """Normalize prose for deterministic multi-word terminology matching."""
    tokens = (token.strip(".") for token in re.findall(r"[a-z0-9+#.]+", value.casefold()))
    return " ".join(token for token in tokens if token)


def phrase_present(term: str, normalized_text: str) -> bool:
    """Match a normalized term on token boundaries rather than substrings."""
    normalized_term = normalize_phrase(term)
    return bool(normalized_term) and f" {normalized_term} " in f" {normalized_text} "


def direction_style_diagnostics(
    profile: dict[str, Any], blocks: list[tuple[str, str, list[str], str | None]]
) -> dict[str, Any]:
    """Report role-profile echo as editorial advice without rejecting the resume."""
    block_tokens = {owner: normalize_phrase(claim).split() for owner, claim, _, _ in blocks}
    all_tokens = [token for tokens in block_tokens.values() for token in tokens]
    token_counts = Counter(all_tokens)
    configured_tokens: set[str] = set()
    concepts = profile["priority_concepts"]
    assert isinstance(concepts, list)
    for raw_concept in concepts:
        concept = object_value(raw_concept, "priority concept")
        for term in string_list(concept["terms"], "terms"):
            configured_tokens.update(normalize_phrase(term).split())

    concentrated: list[dict[str, Any]] = []
    token_total = len(all_tokens)
    for token in sorted(configured_tokens):
        if len(token) < 5 or token in STYLE_TOKEN_EXCLUSIONS:
            continue
        count = token_counts[token]
        owners = sorted(owner for owner, tokens in block_tokens.items() if token in tokens)
        share = count / token_total if token_total else 0.0
        if (
            count >= STYLE_MIN_TERM_OCCURRENCES
            and len(owners) >= STYLE_MIN_CLAIM_BLOCKS
            and share >= STYLE_MIN_WORD_SHARE
        ):
            concentrated.append(
                {
                    "term": token,
                    "occurrences": count,
                    "claim_blocks": len(owners),
                    "word_share": round(share, 3),
                }
            )

    competency_blocks = [
        (owner, claim) for owner, claim, _, _ in blocks if owner.startswith("competencies[")
    ]
    copied_labels: list[dict[str, str]] = []
    for raw_concept in concepts:
        concept = object_value(raw_concept, "priority concept")
        label = nonempty_string(concept["label"], "concept label")
        label_tokens = {
            token for token in normalize_phrase(label).split() if token not in {"and", "or", "the"}
        }
        if not label_tokens:
            continue
        for owner, claim in competency_blocks:
            claim_tokens = {
                token
                for token in normalize_phrase(claim).split()
                if token not in {"and", "or", "the"}
            }
            overlap = len(label_tokens & claim_tokens) / len(label_tokens)
            if overlap >= COPIED_LABEL_MIN_COVERAGE:
                copied_labels.append(
                    {
                        "concept_id": str(concept["id"]),
                        "concept_label": label,
                        "owner": owner,
                    }
                )

    return {
        "advisory_only": True,
        "target_term_concentration": concentrated,
        "copied_concept_labels": copied_labels,
    }


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
