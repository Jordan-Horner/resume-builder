#!/usr/bin/env python3
"""Audit exact resume retrieval against one captured job posting."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from .atomic import atomic_write_json, atomic_write_text
from .compilation import compile_markdown, relative_output, sha256_file
from .directions import normalize_phrase, phrase_present, string_list
from .evidence import audit_claims, claim_blocks
from .job_report import markdown_report
from .job_target import (
    CRITERION_FIELDS,
    IMPORTANCE,
    SEARCH_FIELDS,
    SOURCE_FIELDS,
    SOURCE_KINDS,
    TARGET_FIELDS,
    body_sha256,
    parse_target,
    project_target_path,
    target_paths,
    validate_target,
)
from .rendering import contained_project_path, object_value

__all__ = [
    "CRITERION_FIELDS",
    "IMPORTANCE",
    "SEARCH_FIELDS",
    "SOURCE_FIELDS",
    "SOURCE_KINDS",
    "TARGET_FIELDS",
    "body_sha256",
    "compare_audits",
    "exact_retrieval",
    "main",
    "markdown_report",
    "match_job",
    "parse_target",
    "phrase_occurrences",
    "project_target_path",
    "resume_audit",
    "target_paths",
    "validate_main",
    "validate_target",
]


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
