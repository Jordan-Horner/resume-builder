#!/usr/bin/env python3
"""Audit exact resume retrieval against one captured job posting."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import sys
import unicodedata
from collections.abc import Sequence
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml

from .atomic import atomic_write_json, atomic_write_text
from .compilation import compile_markdown, relative_output, sha256_file
from .directions import (
    SLUG,
    iso_date,
    nonempty_string,
    normalize_phrase,
    parse_direction,
    phrase_present,
    string_list,
)
from .evidence import audit_claims, claim_blocks
from .rendering import contained_project_path, object_value

TARGET_FIELDS = {
    "schema_version",
    "slug",
    "company",
    "role",
    "captured_at",
    "source",
    "direction",
    "criteria",
    "search_groups",
}
SOURCE_FIELDS = {"kind", "reference", "url", "published_at", "body_sha256"}
CRITERION_FIELDS = {
    "id",
    "importance",
    "label",
    "description",
    "resume_evaluable",
    "source_section",
}
SEARCH_FIELDS = {"id", "criterion_id", "any_of"}
SOURCE_KINDS = {"url", "pasted", "file"}
IMPORTANCE = {"required", "preferred"}


def body_sha256(body: str) -> str:
    """Hash the normalized posting snapshot independently from its metadata."""
    return hashlib.sha256(body.strip().encode("utf-8")).hexdigest()


def parse_target(path: Path) -> tuple[dict[str, Any], str]:
    """Load and validate a versioned, source-preserving target posting."""
    try:
        markdown = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"cannot read target posting: {exc}") from exc
    if not markdown.startswith("---\n"):
        raise ValueError("target posting must begin with YAML frontmatter")
    try:
        raw, body = markdown[4:].split("\n---\n", 1)
    except ValueError as exc:
        raise ValueError("target posting frontmatter is not closed with ---") from exc
    try:
        metadata = object_value(yaml.safe_load(raw), "target frontmatter")
    except yaml.YAMLError as exc:
        raise ValueError(f"invalid target frontmatter: {exc}") from exc

    if unexpected := sorted(set(metadata) - TARGET_FIELDS):
        raise ValueError(f"target posting contains unsupported fields: {unexpected}")
    if metadata.get("schema_version") != 1:
        raise ValueError("target posting must declare schema_version 1")
    slug = nonempty_string(metadata.get("slug"), "slug")
    if not SLUG.fullmatch(slug):
        raise ValueError("slug must use lowercase kebab-case")
    if path.stem != slug:
        raise ValueError(f"target filename must match slug: expected {slug}.md")
    nonempty_string(metadata.get("company"), "company")
    nonempty_string(metadata.get("role"), "role")
    iso_date(metadata.get("captured_at"), "captured_at")
    direction = nonempty_string(metadata.get("direction"), "direction")
    if not direction.startswith("directions/") or not direction.endswith(".md"):
        raise ValueError("direction must reference a Markdown file under directions/")

    source = object_value(metadata.get("source"), "source")
    if unexpected_source := sorted(set(source) - SOURCE_FIELDS):
        raise ValueError(f"source contains unsupported fields: {unexpected_source}")
    source_kind = nonempty_string(source.get("kind"), "source.kind")
    if source_kind not in SOURCE_KINDS:
        raise ValueError(f"source.kind must be one of {sorted(SOURCE_KINDS)}")
    nonempty_string(source.get("reference"), "source.reference")
    if "published_at" in source:
        iso_date(source.get("published_at"), "source.published_at")
    if source_kind == "url":
        url = nonempty_string(source.get("url"), "source.url")
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("source.url must be an http or https URL")
    elif "url" in source:
        raise ValueError("source.url is allowed only when source.kind is url")

    if not body.strip().startswith("# Job Posting Snapshot"):
        raise ValueError("target body must begin with '# Job Posting Snapshot'")
    expected_digest = nonempty_string(source.get("body_sha256"), "source.body_sha256")
    if not re.fullmatch(r"[a-f0-9]{64}", expected_digest):
        raise ValueError("source.body_sha256 must be a lowercase SHA-256 digest")
    actual_digest = body_sha256(body)
    if expected_digest != actual_digest:
        raise ValueError("target posting body does not match source.body_sha256")

    raw_criteria = metadata.get("criteria")
    if not isinstance(raw_criteria, list) or not raw_criteria:
        raise ValueError("criteria must be a non-empty list")
    if len(raw_criteria) > 12:
        raise ValueError("criteria must contain no more than 12 focused criteria")
    criteria: dict[str, dict[str, Any]] = {}
    for index, raw_criterion in enumerate(raw_criteria):
        criterion = object_value(raw_criterion, f"criteria[{index}]")
        if unexpected_criterion := sorted(set(criterion) - CRITERION_FIELDS):
            raise ValueError(
                f"criteria[{index}] contains unsupported fields: {unexpected_criterion}"
            )
        criterion_id = nonempty_string(criterion.get("id"), f"criteria[{index}].id")
        if not SLUG.fullmatch(criterion_id):
            raise ValueError(f"criteria[{index}].id must use lowercase kebab-case")
        if criterion_id in criteria:
            raise ValueError(f"duplicate criterion ID: {criterion_id}")
        importance = nonempty_string(criterion.get("importance"), f"criteria[{index}].importance")
        if importance not in IMPORTANCE:
            raise ValueError(f"criteria[{index}].importance must be one of {sorted(IMPORTANCE)}")
        nonempty_string(criterion.get("label"), f"criteria[{index}].label")
        nonempty_string(criterion.get("description"), f"criteria[{index}].description")
        nonempty_string(criterion.get("source_section"), f"criteria[{index}].source_section")
        if not isinstance(criterion.get("resume_evaluable"), bool):
            raise ValueError(f"criteria[{index}].resume_evaluable must be a boolean")
        criteria[criterion_id] = criterion
    if not any(criterion["importance"] == "required" for criterion in criteria.values()):
        raise ValueError("criteria must identify at least one required criterion")

    raw_groups = metadata.get("search_groups")
    if not isinstance(raw_groups, list) or not raw_groups:
        raise ValueError("search_groups must be a non-empty list")
    group_ids: set[str] = set()
    searchable_criteria: set[str] = set()
    for index, raw_group in enumerate(raw_groups):
        group = object_value(raw_group, f"search_groups[{index}]")
        if unexpected_group := sorted(set(group) - SEARCH_FIELDS):
            raise ValueError(
                f"search_groups[{index}] contains unsupported fields: {unexpected_group}"
            )
        group_id = nonempty_string(group.get("id"), f"search_groups[{index}].id")
        if not SLUG.fullmatch(group_id):
            raise ValueError(f"search_groups[{index}].id must use lowercase kebab-case")
        if group_id in group_ids:
            raise ValueError(f"duplicate search group ID: {group_id}")
        group_ids.add(group_id)
        criterion_id = nonempty_string(
            group.get("criterion_id"), f"search_groups[{index}].criterion_id"
        )
        if criterion_id not in criteria:
            raise ValueError(f"search_groups[{index}] cites unknown criterion: {criterion_id}")
        if not criteria[criterion_id]["resume_evaluable"]:
            raise ValueError(
                f"search_groups[{index}] cites a criterion that is not resume-evaluable"
            )
        terms = string_list(group.get("any_of"), f"search_groups[{index}].any_of")
        normalized = [normalize_phrase(term) for term in terms]
        if any(not term for term in normalized):
            raise ValueError(f"search_groups[{index}].any_of contains an empty search phrase")
        if len(set(normalized)) != len(normalized):
            raise ValueError(
                f"search_groups[{index}].any_of contains phrases that normalize to duplicates"
            )
        searchable_criteria.add(criterion_id)
    missing_groups = sorted(
        criterion_id
        for criterion_id, criterion in criteria.items()
        if criterion["resume_evaluable"] and criterion_id not in searchable_criteria
    )
    if missing_groups:
        raise ValueError(f"resume-evaluable criteria require search groups: {missing_groups}")
    return metadata, body.strip()


def project_target_path(path: Path, project_root: Path) -> Path:
    """Require a canonical target record under targets/."""
    resolved = contained_project_path(path, project_root, "targets", "target posting")
    if resolved.name == "README.md" or resolved.name.endswith(".template.md"):
        raise ValueError("target posting must not be README.md or a template")
    if resolved.suffix != ".md":
        raise ValueError("target posting must use a .md extension")
    return resolved


def target_paths(project_root: Path, requested: list[Path]) -> list[Path]:
    """Resolve requested target records or discover every canonical posting."""
    if requested:
        return [project_target_path(path, project_root) for path in requested]
    directory = (project_root / "targets").resolve()
    return [
        path
        for path in sorted(directory.glob("*.md"))
        if path.name != "README.md" and not path.name.endswith(".template.md")
    ]


def validate_target(path: Path, project_root: Path) -> tuple[dict[str, Any], Path]:
    """Validate one target and its referenced reusable direction."""
    target_path = project_target_path(path, project_root)
    target_data, _ = parse_target(target_path)
    direction_path = contained_project_path(
        Path(str(target_data["direction"])), project_root, "directions", "direction"
    )
    parse_direction(direction_path)
    return target_data, direction_path


def claim_kind(owner: str) -> str:
    """Separate demonstrated evidence from scan labels and contextual text."""
    if ".bullets[" in owner or owner.startswith("projects["):
        return "demonstrated"
    if owner == "candidate" or owner.startswith(("competencies[", "skills[")):
        return "listed"
    return "context"


def phrase_occurrences(term: str, text: str) -> int:
    """Count a normalized phrase on token boundaries."""
    normalized_term = normalize_phrase(term)
    normalized_text = normalize_phrase(text)
    if not normalized_term:
        return 0
    pattern = rf"(?<![a-z0-9+#.]){re.escape(normalized_term)}(?![a-z0-9+#.])"
    return len(re.findall(pattern, normalized_text))


def exact_retrieval(target: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    """Locate configured posting language without making a semantic-fit claim."""
    criteria = {
        str(item["id"]): item
        for item in target["criteria"]
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    blocks = claim_blocks(payload)
    group_results: list[dict[str, Any]] = []
    for raw_group in target["search_groups"]:
        group = object_value(raw_group, "search group")
        criterion_id = str(group["criterion_id"])
        matches: list[dict[str, Any]] = []
        for term in string_list(group["any_of"], "search group any_of"):
            locations: list[dict[str, Any]] = []
            for owner, claim, evidence_ids, _ in blocks:
                if not phrase_present(term, normalize_phrase(claim)):
                    continue
                locations.append(
                    {
                        "owner": owner,
                        "kind": claim_kind(owner),
                        "occurrences": phrase_occurrences(term, claim),
                        "evidence_fact_ids": evidence_ids,
                    }
                )
            if locations:
                matches.append({"term": term, "locations": locations})
        demonstrated = any(
            location["kind"] == "demonstrated"
            for match in matches
            for location in match["locations"]
        )
        group_results.append(
            {
                "id": group["id"],
                "criterion_id": criterion_id,
                "importance": criteria[criterion_id]["importance"],
                "any_of": group["any_of"],
                "found": bool(matches),
                "demonstrated": demonstrated,
                "matches": matches,
            }
        )
    found = [str(group["id"]) for group in group_results if group["found"]]
    missing = [str(group["id"]) for group in group_results if not group["found"]]
    required_missing = [
        str(group["id"])
        for group in group_results
        if group["importance"] == "required" and not group["found"]
    ]
    listed_only = [
        str(group["id"]) for group in group_results if group["found"] and not group["demonstrated"]
    ]
    return {
        "method": (
            "exact configured phrase retrieval with token boundaries; presence is not semantic "
            "evidence, an ATS score, or an employer decision prediction"
        ),
        "groups": group_results,
        "found_group_ids": found,
        "missing_group_ids": missing,
        "required_missing_group_ids": required_missing,
        "listed_without_demonstration_group_ids": listed_only,
    }


def resume_audit(
    payload: dict[str, Any], target: dict[str, Any], vault_root: Path
) -> dict[str, Any]:
    """Collect exact retrieval and grounding details for one resume."""
    blocks = claim_blocks(payload)
    return {
        "exact_retrieval": exact_retrieval(target, payload),
        "grounding": audit_claims(payload, vault_root),
        "fact_ids": sorted({fact_id for _, _, ids, _ in blocks for fact_id in ids}),
        "claim_blocks": len(blocks),
        "visible_words": sum(len(normalize_phrase(claim).split()) for _, claim, _, _ in blocks),
    }


def compare_audits(baseline: dict[str, Any], tailored: dict[str, Any]) -> dict[str, Any]:
    """Report preservation and retrieval deltas without declaring quality."""
    baseline_found = set(baseline["exact_retrieval"]["found_group_ids"])
    tailored_found = set(tailored["exact_retrieval"]["found_group_ids"])
    baseline_required_missing = set(baseline["exact_retrieval"]["required_missing_group_ids"])
    tailored_required_missing = set(tailored["exact_retrieval"]["required_missing_group_ids"])
    baseline_facts = set(baseline["fact_ids"])
    tailored_facts = set(tailored["fact_ids"])
    return {
        "method": (
            "deterministic baseline-to-tailored preservation and retrieval delta; editorial "
            "quality and semantic criterion satisfaction still require review"
        ),
        "retrieval": {
            "gained_group_ids": sorted(tailored_found - baseline_found),
            "lost_group_ids": sorted(baseline_found - tailored_found),
            "required_gaps_closed": sorted(baseline_required_missing - tailored_required_missing),
            "required_gaps_introduced": sorted(
                tailored_required_missing - baseline_required_missing
            ),
            "unchanged_found_group_ids": sorted(baseline_found & tailored_found),
        },
        "evidence": {
            "added_fact_ids": sorted(tailored_facts - baseline_facts),
            "removed_fact_ids": sorted(baseline_facts - tailored_facts),
        },
        "shape": {
            "claim_blocks_delta": tailored["claim_blocks"] - baseline["claim_blocks"],
            "visible_words_delta": tailored["visible_words"] - baseline["visible_words"],
        },
    }


def _markdown_source_text(value: object) -> str:
    """Normalize untrusted values so they cannot create new Markdown structure."""
    text = "".join(
        " " if character.isspace() or unicodedata.category(character) in {"Cc", "Cf"} else character
        for character in str(value)
    )
    return re.sub(r" +", " ", text).strip()


def _markdown_inline(value: object) -> str:
    """Render an untrusted value as inert inline Markdown text."""
    text = html.escape(_markdown_source_text(value), quote=False)
    return re.sub(r"([\\`*_\[\]!.:~])", r"\\\1", text)


def _markdown_table_cell(value: object) -> str:
    """Render an untrusted value without allowing table-row or cell injection."""
    return _markdown_inline(value).replace("|", "\\|")


def _markdown_code_span(value: object) -> str:
    """Render an untrusted path in a code span with a collision-free fence."""
    text = _markdown_source_text(value)
    longest_run = max((len(run) for run in re.findall(r"`+", text)), default=0)
    fence = "`" * (longest_run + 1)
    if "`" in text or text.startswith(" ") or text.endswith(" "):
        return f"{fence} {text} {fence}"
    return f"{fence}{text}{fence}"


def _markdown_list(values: Sequence[object]) -> str:
    """Render an untrusted sequence as a comma-separated inline list."""
    return ", ".join(_markdown_inline(value) for value in values) or "none"


def markdown_report(result: dict[str, Any]) -> str:
    """Render a concise, human-reviewable companion to the JSON audit."""
    lines = [
        (
            f"# Job Match: {_markdown_inline(result['target']['company'])} — "
            f"{_markdown_inline(result['target']['role'])}"
        ),
        "",
        "This is an exact-retrieval and preservation report, not an ATS score or hiring verdict.",
        "",
        f"- Target: {_markdown_code_span(result['target']['path'])}",
        f"- Resume: {_markdown_code_span(result['resume']['path'])}",
        f"- Direction: {_markdown_code_span(result['target']['direction'])}",
        "",
        "## Exact retrieval",
        "",
        "| Search group | Importance | Found | Demonstrated | Matched terms | Locations |",
        "|---|---|---:|---:|---|---|",
    ]
    for group in result["resume"]["audit"]["exact_retrieval"]["groups"]:
        terms = ", ".join(str(match["term"]) for match in group["matches"]) or "—"
        owners = sorted(
            {
                str(location["owner"])
                for match in group["matches"]
                for location in match["locations"]
            }
        )
        locations = ", ".join(owners) or "—"
        lines.append(
            "| {id} | {importance} | {found} | {demonstrated} | {terms} | {locations} |".format(
                id=_markdown_table_cell(group["id"]),
                importance=_markdown_table_cell(group["importance"]),
                found="yes" if group["found"] else "no",
                demonstrated="yes" if group["demonstrated"] else "no",
                terms=_markdown_table_cell(terms),
                locations=_markdown_table_cell(locations),
            )
        )
    retrieval = result["resume"]["audit"]["exact_retrieval"]
    lines.extend(
        [
            "",
            (
                "Required groups not retrieved: "
                f"{_markdown_list(retrieval['required_missing_group_ids'])}"
            ),
            (
                "Retrieved only outside experience/project proof: "
                f"{_markdown_list(retrieval['listed_without_demonstration_group_ids'])}"
            ),
        ]
    )
    if comparison := result.get("comparison"):
        delta = comparison["delta"]
        lines.extend(
            [
                "",
                "## Baseline comparison",
                "",
                f"- Baseline: {_markdown_code_span(comparison['baseline']['path'])}",
                (f"- Retrieval gained: {_markdown_list(delta['retrieval']['gained_group_ids'])}"),
                f"- Retrieval lost: {_markdown_list(delta['retrieval']['lost_group_ids'])}",
                (f"- Evidence IDs added: {_markdown_list(delta['evidence']['added_fact_ids'])}"),
                (
                    "- Evidence IDs removed: "
                    f"{_markdown_list(delta['evidence']['removed_fact_ids'])}"
                ),
            ]
        )
    lines.extend(
        [
            "",
            "## Required judgment",
            "",
            "Review each posting criterion against cited resume evidence. Use met, partial, not_met, "
            "or undecidable; do not convert this lexical report into a percentage or pass prediction.",
            "",
        ]
    )
    return "\n".join(lines)


def match_job(
    target: Path,
    resume: Path,
    *,
    baseline: Path | None = None,
    output_base: Path | None = None,
    vault_root: Path = Path("vault"),
) -> dict[str, Any]:
    """Create a reproducible target/resume audit and optional baseline delta."""
    resolved_vault = vault_root.expanduser().resolve()
    project_root = resolved_vault.parent
    target_path = project_target_path(target, project_root)
    resume_path = contained_project_path(resume, project_root, "resumes", "resume")
    target_data, direction_path = validate_target(target_path, project_root)
    payload = compile_markdown(resume_path.read_text(encoding="utf-8"))
    audit = resume_audit(payload, target_data, resolved_vault)

    result: dict[str, Any] = {
        "version": 1,
        "valid": True,
        "scope": "resume-only job match",
        "target": {
            "path": relative_output(target_path, project_root),
            "sha256": sha256_file(target_path),
            "body_sha256": target_data["source"]["body_sha256"],
            "company": target_data["company"],
            "role": target_data["role"],
            "direction": relative_output(direction_path, project_root),
            "direction_sha256": sha256_file(direction_path),
            "criteria": target_data["criteria"],
        },
        "resume": {
            "path": relative_output(resume_path, project_root),
            "sha256": sha256_file(resume_path),
            "audit": audit,
        },
        "limitations": [
            "Exact phrase presence does not prove that the resume satisfies a criterion.",
            "This report evaluates the resume only, not application answers or interviews.",
            "No universal ATS score or employer decision prediction is produced.",
        ],
    }

    if baseline is not None:
        baseline_path = contained_project_path(baseline, project_root, "resumes", "baseline")
        baseline_directory = (project_root / "resumes" / "baselines").resolve()
        if not baseline_path.is_relative_to(baseline_directory):
            raise ValueError("baseline comparison source must be under resumes/baselines/")
        tailored_directory = (project_root / "resumes" / "tailored").resolve()
        if not resume_path.is_relative_to(tailored_directory):
            raise ValueError("baseline comparison target must be under resumes/tailored/")
        if baseline_path == resume_path:
            raise ValueError("baseline and tailored resume must be different files")
        baseline_payload = compile_markdown(baseline_path.read_text(encoding="utf-8"))
        baseline_audit = resume_audit(baseline_payload, target_data, resolved_vault)
        result["comparison"] = {
            "baseline": {
                "path": relative_output(baseline_path, project_root),
                "sha256": sha256_file(baseline_path),
                "audit": baseline_audit,
            },
            "delta": compare_audits(baseline_audit, audit),
        }

    base_argument = output_base or (
        Path("build/matches") / f"{target_path.stem}--{resume_path.stem}"
    )
    resolved_base = contained_project_path(base_argument, project_root, "build", "output base")
    if resolved_base.suffix:
        raise ValueError("output base must not have a file extension")
    json_path = resolved_base.with_suffix(".json")
    markdown_path = resolved_base.with_suffix(".md")
    result["outputs"] = [
        relative_output(json_path, project_root),
        relative_output(markdown_path, project_root),
    ]
    atomic_write_json(json_path, result)
    atomic_write_text(markdown_path, markdown_report(result))
    return result


def validate_main(argv: Sequence[str]) -> int:
    """Validate canonical target postings without auditing a resume."""
    parser = argparse.ArgumentParser(description="Validate captured target postings")
    parser.add_argument("targets", nargs="*", type=Path)
    parser.add_argument("--vault-root", type=Path, default=Path("vault"))
    args = parser.parse_args(argv)
    try:
        project_root = args.vault_root.expanduser().resolve().parent
        validated = []
        for path in target_paths(project_root, args.targets):
            target, direction = validate_target(path, project_root)
            validated.append(
                {
                    "path": relative_output(path, project_root),
                    "slug": target["slug"],
                    "company": target["company"],
                    "role": target["role"],
                    "direction": relative_output(direction, project_root),
                    "body_sha256": target["source"]["body_sha256"],
                }
            )
        result = {"valid": True, "targets": validated, "count": len(validated)}
    except (OSError, ValueError) as exc:
        print(json.dumps({"error": str(exc)}, indent=2), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Validate targets or audit one resume against one captured posting."""
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments and arguments[0] == "validate":
        return validate_main(arguments[1:])
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", type=Path)
    parser.add_argument("resume", type=Path)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--output-base", type=Path)
    parser.add_argument("--vault-root", type=Path, default=Path("vault"))
    args = parser.parse_args(arguments)
    try:
        result = match_job(
            args.target,
            args.resume,
            baseline=args.baseline,
            output_base=args.output_base,
            vault_root=args.vault_root,
        )
    except (OSError, ValueError) as exc:
        print(json.dumps({"error": str(exc)}, indent=2), file=sys.stderr)
        return 2
    summary = {
        "valid": True,
        "scope": result["scope"],
        "target": result["target"]["path"],
        "resume": result["resume"]["path"],
        "required_missing_group_ids": result["resume"]["audit"]["exact_retrieval"][
            "required_missing_group_ids"
        ],
        "outputs": result["outputs"],
    }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
