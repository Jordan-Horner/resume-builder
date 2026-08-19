"""Run reproducible regression evaluations for completed and sealed resume lanes."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import yaml

from .compilation import build_resume
from .layout import VaultLayout, contained_path, load_json_object
from .synthesis import SynthesisPlan, load_synthesis_plan
from .validation import parse_frontmatter

DIMENSIONS = {
    "relevance",
    "evidence_strength",
    "distinctiveness",
    "story_coherence",
    "seniority_alignment",
    "clarity",
    "ats_readability",
}


def _strings(value: object, owner: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise ValueError(f"{owner} must be a list of non-empty strings")
    if len(value) != len(set(value)):
        raise ValueError(f"{owner} must not contain duplicates")
    return value


def load_case(path: Path, project_root: Path) -> dict[str, Any]:
    """Load one exact-field evaluation case from the canonical case directory."""
    cases_root = (project_root / "evals" / "cases").resolve()
    source = path.expanduser()
    source = (project_root / source).resolve() if not source.is_absolute() else source.resolve()
    if source.parent != cases_root or source.suffix not in {".yaml", ".yml"}:
        raise ValueError("evaluation case must be a YAML file directly under evals/cases")
    raw = yaml.safe_load(source.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("evaluation case must be an object")
    expected = {
        "version",
        "id",
        "lane",
        "resume",
        "original_source_id",
        "original_sha256",
        "snapshot_sha256",
        "sealed",
        "required_role_ids",
        "material_fact_ids",
    }
    missing = sorted(expected - raw.keys())
    unexpected = sorted(raw.keys() - expected)
    if missing or unexpected:
        raise ValueError(
            f"evaluation case fields mismatch; missing={missing}, unexpected={unexpected}"
        )
    if raw["version"] != 1:
        raise ValueError("evaluation case must declare version 1")
    for field in (
        "id",
        "lane",
        "resume",
        "original_source_id",
        "original_sha256",
        "snapshot_sha256",
    ):
        if not isinstance(raw[field], str) or not raw[field].strip():
            raise ValueError(f"evaluation case {field} must be a non-empty string")
    if not re.fullmatch(r"SRC-[0-9a-f]{12}", raw["original_source_id"]):
        raise ValueError("evaluation original_source_id must use SRC-<12 lowercase hex>")
    for field in ("original_sha256", "snapshot_sha256"):
        if not re.fullmatch(r"[0-9a-f]{64}", raw[field]):
            raise ValueError(f"evaluation case {field} must be a lowercase SHA-256 digest")
    if not isinstance(raw["sealed"], bool):
        raise ValueError("evaluation case sealed must be a boolean")
    raw["required_role_ids"] = _strings(raw["required_role_ids"], "required_role_ids")
    raw["material_fact_ids"] = _strings(raw["material_fact_ids"], "material_fact_ids")
    resume = (project_root / raw["resume"]).resolve()
    resumes_root = (project_root / "resumes").resolve()
    if resume != resumes_root and resumes_root not in resume.parents:
        raise ValueError("evaluation resume must remain under resumes")
    raw["source"] = source
    raw["resume_path"] = resume
    return raw


def _fact_sources(vault_root: Path) -> dict[str, set[str]]:
    layout = VaultLayout.load(vault_root)
    result: dict[str, set[str]] = {}
    for path in sorted(layout.facts.rglob("*.md")):
        metadata, _ = parse_frontmatter(path)
        fact_id = metadata.get("id")
        sources = metadata.get("sources")
        if isinstance(fact_id, str) and isinstance(sources, list):
            result[fact_id] = {source for source in sources if isinstance(source, str)}
    return result


def _source_entry(vault_root: Path, source_id: str) -> dict[str, Any]:
    layout = VaultLayout.load(vault_root)
    manifest = json.loads(layout.manifest.read_text(encoding="utf-8"))
    for entry in manifest.get("sources", []):
        if isinstance(entry, dict) and entry.get("id") == source_id:
            return entry
    raise ValueError(f"evaluation source is not registered: {source_id}")


def _review(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or set(raw) != {"dimensions", "verdict"}:
        raise ValueError("editorial review requires dimensions and verdict")
    dimensions = raw["dimensions"]
    if not isinstance(dimensions, dict) or set(dimensions) != DIMENSIONS:
        raise ValueError(f"editorial review dimensions must be {sorted(DIMENSIONS)}")
    for name, scores in dimensions.items():
        if not isinstance(scores, dict) or set(scores) != {"original", "new", "notes"}:
            raise ValueError(f"editorial review dimension {name} has invalid fields")
        for key in ("original", "new"):
            score = scores[key]
            if (
                not isinstance(score, (int, float))
                or isinstance(score, bool)
                or not 1 <= score <= 5
            ):
                raise ValueError(f"editorial review {name}.{key} must be 1 through 5")
        if not isinstance(scores["notes"], str):
            raise ValueError(f"editorial review {name}.notes must be a string")
    if raw["verdict"] not in {"regressed", "on-par", "improved"}:
        raise ValueError("editorial review verdict must be regressed, on-par, or improved")
    return raw


def _generated_output(outputs: object, filename: str, project_root: Path) -> Path:
    """Resolve one expected build artifact from a compiler result."""
    if not isinstance(outputs, list):
        raise ValueError("evaluation build outputs must be a list")
    matches = [
        contained_path(project_root, value, "evaluation build output")
        for value in outputs
        if isinstance(value, str) and Path(value).name == filename
    ]
    if len(matches) != 1:
        raise ValueError(f"evaluation build must produce exactly one {filename} artifact")
    return matches[0]


def _compiled_selection(
    plan: SynthesisPlan,
    payload: dict[str, Any],
    synthesis_audit: dict[str, Any],
) -> tuple[set[str], set[str]]:
    """Return facts and progression roles actually present in compiled content."""
    used_story_ids = set(_strings(synthesis_audit.get("used_story_ids"), "compiled used_story_ids"))
    stories = {story.story_id: story for story in plan.stories}
    unknown_story_ids = sorted(used_story_ids - stories.keys())
    if unknown_story_ids:
        raise ValueError(f"compiled resume cites unknown synthesis stories: {unknown_story_ids}")

    raw_selected = synthesis_audit.get("selected_fact_ids")
    if raw_selected is None:
        # Compatibility for stored manifests created before actual used evidence
        # was included in the synthesis audit.
        selected = {
            fact_id for story_id in used_story_ids for fact_id in stories[story_id].fact_ids
        }
        selected.update(_strings(payload.get("summary_evidence"), "compiled summary_evidence"))
    else:
        selected = set(_strings(raw_selected, "compiled selected_fact_ids"))

    progression = set(plan.progression)
    present_roles: set[str] = set()
    experience = payload.get("experience")
    if not isinstance(experience, list):
        raise ValueError("compiled experience must be a list")
    for index, entry in enumerate(experience):
        if not isinstance(entry, dict):
            raise ValueError(f"compiled experience[{index}] must be an object")
        evidence = _strings(entry.get("evidence"), f"compiled experience[{index}].evidence")
        present_roles.update(set(evidence) & progression)
    return selected, present_roles


def grade_case(
    case_path: Path,
    *,
    project_root: Path,
    vault_root: Path,
    review_path: Path | None = None,
) -> dict[str, Any]:
    """Build a resume, then grade preservation and cross-source synthesis."""
    case = load_case(case_path, project_root)
    resume = case["resume_path"]
    if not resume.is_file():
        raise ValueError("evaluation resume must exist before the original source is opened")

    output_base = Path("build/evals") / case["id"]
    build_result = build_resume(resume, output_base=output_base, vault_root=vault_root)
    plan = load_synthesis_plan(
        Path("resumes/plans") / f"{resume.stem}.yaml", project_root, vault_root
    )
    outputs = build_result.get("outputs")
    payload = load_json_object(_generated_output(outputs, f"{case['id']}.json", project_root))
    manifest = load_json_object(
        _generated_output(outputs, f"{case['id']}.manifest.json", project_root)
    )
    raw_synthesis = manifest.get("synthesis")
    if not isinstance(raw_synthesis, dict):
        raise ValueError("evaluation build manifest requires a synthesis audit")
    selected, present_roles = _compiled_selection(plan, payload, raw_synthesis)
    excluded = set(dict(plan.exclusions))
    material = set(case["material_fact_ids"])
    missing = sorted(material - selected - excluded)
    intentional = sorted(material & excluded)
    retained = sorted(material & selected)
    missing_roles = sorted(set(case["required_role_ids"]) - present_roles)

    entry = _source_entry(vault_root, case["original_source_id"])
    if entry.get("sha256") != case["original_sha256"]:
        raise ValueError("registered original source hash does not match evaluation case")
    snapshot = contained_path(vault_root, entry.get("snapshot"), "evaluation source snapshot")
    snapshot_hash = hashlib.sha256(snapshot.read_bytes()).hexdigest()
    if snapshot_hash != case["snapshot_sha256"]:
        raise ValueError("normalized original snapshot hash does not match evaluation case")

    sources = _fact_sources(vault_root)
    unknown_material = sorted(material - sources.keys())
    if unknown_material:
        raise ValueError(f"evaluation case cites unknown material facts: {unknown_material}")
    unrelated_material = sorted(
        fact_id for fact_id in material if case["original_source_id"] not in sources[fact_id]
    )
    if unrelated_material:
        raise ValueError(
            "evaluation material facts are not grounded in its original source: "
            f"{unrelated_material}"
        )
    cross_source = sorted(
        fact_id
        for fact_id in selected
        if case["original_source_id"] not in sources.get(fact_id, set())
    )
    editorial = _review(review_path)
    deterministic_pass = bool(retained) and not missing and not missing_roles and bool(cross_source)
    return {
        "valid": deterministic_pass,
        "case": case["id"],
        "lane": case["lane"],
        "sealed": case["sealed"],
        "resume": case["resume"],
        "preservation": {
            "retained": retained,
            "intentionally_excluded": intentional,
            "missing": missing,
        },
        "required_roles_missing": missing_roles,
        "cross_source_gains": cross_source,
        "editorial": editorial or {"status": "not-scored"},
    }


def main(argv: Sequence[str] | None = None) -> int:
    """Validate cases or grade one built resume lane."""
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="action", required=True)
    validate = subparsers.add_parser("validate")
    validate.add_argument("cases", nargs="*", type=Path)
    validate.add_argument("--vault-root", type=Path, default=Path("vault"))
    grade = subparsers.add_parser("grade")
    grade.add_argument("case", type=Path)
    grade.add_argument("--review", type=Path)
    grade.add_argument("--vault-root", type=Path, default=Path("vault"))
    args = parser.parse_args(argv)
    try:
        vault_root = args.vault_root.expanduser().resolve()
        project_root = vault_root.parent
        if args.action == "validate":
            paths = args.cases or sorted((project_root / "evals" / "cases").glob("*.yaml"))
            cases = [load_case(path, project_root) for path in paths]
            result = {"valid": True, "cases": [case["id"] for case in cases]}
        else:
            result = grade_case(
                args.case,
                project_root=project_root,
                vault_root=vault_root,
                review_path=args.review,
            )
    except (OSError, ValueError, json.JSONDecodeError, yaml.YAMLError) as exc:
        print(json.dumps({"error": str(exc)}, indent=2), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
