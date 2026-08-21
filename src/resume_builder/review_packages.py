"""Build frozen cold-read and evidence review packages."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from . import __version__
from .artifact_paths import resume_output_base
from .atomic import atomic_write_json
from .layout import contained_path
from .review_blocks import (
    NarrativeReviewBlock,
    narrative_block_inventory,
)
from .review_schema import (
    _object,
    sha256_file,
    sha256_text,
)
from .selection_guard import (
    build_selection,
    guard_selection,
    matching_repair_handoff,
    selection_digest,
)
from .selection_review import (
    require_approved_selection_review,
)
from .synthesis import load_synthesis_plan, role_arc_payloads


def build_review_package(
    resume: Path,
    project_root: Path,
    *,
    target: Path | None = None,
) -> Path:
    """Write the exact cold-read and selection appendix used by career review."""
    resolved_root = project_root.expanduser().resolve()
    resume_source = resume.expanduser()
    resume_path = (
        resume_source.resolve()
        if resume_source.is_absolute()
        else contained_path(resolved_root, resume_source.as_posix(), "resume")
    )
    resumes_root = (resolved_root / "resumes").resolve()
    if not resume_path.is_relative_to(resumes_root) or not resume_path.is_file():
        raise ValueError("resume must name an existing file under resumes/")
    require_approved_selection_review(resolved_root, resume_path)
    build_manifest_path = resume_output_base(resolved_root, resume_path).with_suffix(
        ".manifest.json"
    )
    try:
        build_manifest = json.loads(build_manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("review package requires a current compiled build manifest") from exc
    if not isinstance(build_manifest, dict) or build_manifest.get("phase") != "build":
        raise ValueError("review package requires a valid build manifest")
    if build_manifest.get("version") != 1 or build_manifest.get("valid") is not True:
        raise ValueError("review package requires a successful version 1 build")
    compiler = build_manifest.get("compiler")
    if not isinstance(compiler, dict) or compiler.get("version") != __version__:
        raise ValueError("review package build uses a different compiler version")
    source_record = build_manifest.get("source")
    if (
        not isinstance(source_record, dict)
        or source_record.get("path") != resume_path.relative_to(resolved_root).as_posix()
        or source_record.get("sha256") != sha256_file(resume_path)
    ):
        raise ValueError("review package build is stale for the current resume")
    synthesis_record = build_manifest.get("synthesis")
    if not isinstance(synthesis_record, dict) or not isinstance(synthesis_record.get("path"), str):
        raise ValueError("review package build has no synthesis plan")
    plan_path = contained_path(
        resolved_root, synthesis_record["path"], "review package synthesis plan"
    )
    plan = load_synthesis_plan(plan_path, resolved_root, resolved_root / "vault")
    if synthesis_record.get("sha256") != sha256_file(plan_path):
        raise ValueError("review package synthesis plan changed after compilation")
    template_record = build_manifest.get("template")
    if not isinstance(template_record, dict):
        raise ValueError("review package build has no template record")
    template_path_value = template_record.get("path")
    template_digest = template_record.get("sha256")
    if not isinstance(template_path_value, str) or not isinstance(template_digest, str):
        raise ValueError("review package build template record is invalid")
    template_path = contained_path(resolved_root, template_path_value, "review package template")
    if not template_path.is_file() or sha256_file(template_path) != template_digest:
        raise ValueError("review package template changed after compilation")
    output_records = build_manifest.get("outputs")
    if not isinstance(output_records, list) or not output_records:
        raise ValueError("review package build has no output inventory")
    for index, value in enumerate(output_records):
        if not isinstance(value, dict):
            raise ValueError(f"review package output[{index}] is invalid")
        path_value = value.get("path")
        digest = value.get("sha256")
        if not isinstance(path_value, str) or not isinstance(digest, str):
            raise ValueError(f"review package output[{index}] is invalid")
        output_path = contained_path(resolved_root, path_value, f"review package output[{index}]")
        if not output_path.is_file() or sha256_file(output_path) != digest:
            raise ValueError(f"review package output changed after compilation: {path_value}")

    target_record: dict[str, str] | None = None
    target_text: str | None = None
    if target is not None:
        target_source = target.expanduser()
        target_path = (
            target_source.resolve()
            if target_source.is_absolute()
            else contained_path(resolved_root, target_source.as_posix(), "review target")
        )
        targets_root = (resolved_root / "targets").resolve()
        if not target_path.is_relative_to(targets_root) or not target_path.is_file():
            raise ValueError("review target must name an existing file under targets/")
        target_record = {
            "path": target_path.relative_to(resolved_root).as_posix(),
            "sha256": sha256_file(target_path),
        }
        target_text = target_path.read_text(encoding="utf-8")

    cold_read_output = resolved_root / "build" / "reviews" / f"{resume_path.stem}.cold.json"
    output = resolved_root / "build" / "reviews" / f"{resume_path.stem}.package.json"
    decisions_output = resolved_root / "build" / "reviews" / f"{resume_path.stem}.decisions.json"
    if cold_read_output.is_file() and output.is_file() and decisions_output.is_file():
        try:
            existing_package = json.loads(output.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            existing_package = None
        expected_resume = {
            "path": resume_path.relative_to(resolved_root).as_posix(),
            "sha256": sha256_file(resume_path),
        }
        expected_build = {
            "path": build_manifest_path.relative_to(resolved_root).as_posix(),
            "sha256": sha256_file(build_manifest_path),
        }
        expected_plan = {
            "path": plan_path.relative_to(resolved_root).as_posix(),
            "sha256": sha256_file(plan_path),
        }
        expected_direction = {
            "path": plan.direction.relative_to(resolved_root).as_posix(),
            "sha256": sha256_file(plan.direction),
        }
        expected_cold = {
            "path": cold_read_output.relative_to(resolved_root).as_posix(),
            "sha256": sha256_file(cold_read_output),
        }
        if (
            isinstance(existing_package, dict)
            and existing_package.get("version") == 1
            and isinstance(existing_package.get("selection_appendix"), dict)
            and isinstance(existing_package["selection_appendix"].get("selection"), dict)
            and existing_package.get("resume") == expected_resume
            and existing_package.get("build_manifest") == expected_build
            and existing_package.get("plan") == expected_plan
            and existing_package.get("direction") == expected_direction
            and existing_package.get("target") == target_record
            and existing_package.get("cold_read") == expected_cold
        ):
            existing_appendix = _object(
                existing_package.get("selection_appendix"),
                "existing review package selection_appendix",
            )
            existing_selection = _object(
                existing_appendix.get("selection"), "existing review package selection"
            )
            guard_selection(resolved_root, resume_path, existing_selection)
            return output

    inventory = narrative_block_inventory(resume_path)
    evidence = build_manifest.get("evidence")
    fact_records = evidence.get("facts") if isinstance(evidence, dict) else None
    if not isinstance(fact_records, list):
        raise ValueError("review package build has no evidence inventory")
    fact_appendix: list[dict[str, str]] = []
    for index, value in enumerate(fact_records):
        if not isinstance(value, dict):
            raise ValueError(f"review package fact[{index}] is invalid")
        path_value = value.get("path")
        digest = value.get("sha256")
        fact_id = value.get("id")
        if (
            not isinstance(path_value, str)
            or not isinstance(digest, str)
            or not isinstance(fact_id, str)
        ):
            raise ValueError(f"review package fact[{index}] is invalid")
        fact_path = contained_path(resolved_root / "vault", path_value, "review package fact")
        if not fact_path.is_file() or sha256_file(fact_path) != digest:
            raise ValueError(f"review package fact changed after compilation: {fact_id}")
        fact_appendix.append(
            {
                "id": fact_id,
                "path": path_value,
                "sha256": digest,
                "content": fact_path.read_text(encoding="utf-8"),
            }
        )
    feedback_memory = build_manifest.get("feedback_memory")
    feedback_rules = feedback_memory.get("rules") if isinstance(feedback_memory, dict) else None
    if not isinstance(feedback_rules, list):
        raise ValueError("review package build has no feedback-memory inventory")

    generated_at = datetime.now().astimezone().isoformat()
    cold_read = {
        "version": 1,
        "generated_at": generated_at,
        "resume": {
            "path": resume_path.relative_to(resolved_root).as_posix(),
            "sha256": sha256_file(resume_path),
        },
        "target": target_record,
        "target_text": target_text,
        "blocks": [
            {
                "id": block.id,
                "sha256": sha256_text(block.text),
                "text": block.text,
                "context": block.context,
                "advisories": list(block.advisories),
            }
            for block in inventory
        ],
    }
    atomic_write_json(cold_read_output, cold_read)

    selection = build_selection(plan, synthesis_record, target=target_record)
    guard_selection(resolved_root, resume_path, selection)
    package = {
        "version": 1,
        "generated_at": generated_at,
        "resume": {
            "path": resume_path.relative_to(resolved_root).as_posix(),
            "sha256": sha256_file(resume_path),
        },
        "build_manifest": {
            "path": build_manifest_path.relative_to(resolved_root).as_posix(),
            "sha256": sha256_file(build_manifest_path),
        },
        "plan": {
            "path": plan_path.relative_to(resolved_root).as_posix(),
            "sha256": sha256_file(plan_path),
        },
        "direction": {
            "path": plan.direction.relative_to(resolved_root).as_posix(),
            "sha256": sha256_file(plan.direction),
        },
        "target": target_record,
        "cold_read": {
            "path": cold_read_output.relative_to(resolved_root).as_posix(),
            "sha256": sha256_file(cold_read_output),
        },
        "selection_appendix": {
            "selection": selection,
            "target_argument": plan.target_argument,
            "page_budget": (
                {
                    "max_pages": plan.page_budget.max_pages,
                    "source": plan.page_budget.source,
                }
                if plan.page_budget is not None
                else None
            ),
            "role_arcs": role_arc_payloads(plan, set(synthesis_record.get("used_story_ids", []))),
            "concept_fit": synthesis_record.get("concept_fit", []),
            "reviewer_risks": synthesis_record.get("reviewer_risks", []),
            "evidence_integrity": evidence,
            "feedback_memory": {
                "status": "applied" if feedback_rules else "not-applicable",
                "rules": feedback_rules,
            },
            "facts": fact_appendix,
        },
    }
    atomic_write_json(output, package)
    _write_review_decisions(
        resolved_root,
        resume_path,
        cold_read_output,
        output,
        inventory,
        generated_at,
        feedback_rules,
        selection,
    )
    return output


def _write_review_decisions(
    project_root: Path,
    resume: Path,
    cold_read: Path,
    review_package: Path,
    inventory: tuple[NarrativeReviewBlock, ...],
    generated_at: str,
    feedback_rules: list[object],
    selection: dict[str, Any],
) -> Path:
    """Create or refresh the small reviewer-owned decision file for one package."""
    output = project_root / "build" / "reviews" / f"{resume.stem}.decisions.json"
    review_inputs = {
        "cold_read": {
            "path": cold_read.relative_to(project_root).as_posix(),
            "sha256": sha256_file(cold_read),
        },
        "review_package": {
            "path": review_package.relative_to(project_root).as_posix(),
            "sha256": sha256_file(review_package),
        },
    }
    if output.is_file():
        try:
            existing = json.loads(output.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            existing = None
        if (
            isinstance(existing, dict)
            and existing.get("version") == (3 if feedback_rules else 2)
            and existing.get("review_inputs") == review_inputs
        ):
            return output
    handoff = matching_repair_handoff(
        project_root,
        resume,
        sha256_file(resume),
        selection_digest(selection),
    )
    handoff_blocks = handoff.get("carried_blocks", []) if handoff is not None else []
    carried = {
        str(item.get("id")): item
        for item in handoff_blocks
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    block_decisions = []
    for block in inventory:
        prior = carried.get(block.id)
        if prior is not None and prior.get("sha256") == sha256_text(block.text):
            block_decisions.append(
                {
                    "id": block.id,
                    "sha256": sha256_text(block.text),
                    "decision": "approved",
                    "note": str(prior.get("note", "")),
                    "repair": None,
                }
            )
        else:
            block_decisions.append(
                {
                    "id": block.id,
                    "sha256": sha256_text(block.text),
                    "decision": None,
                    "note": "",
                    "repair": None,
                }
            )
    template = {
        "version": 3 if feedback_rules else 2,
        "generated_at": generated_at,
        "review_inputs": review_inputs,
        "reviewer": {
            "method": "independent-cold-review",
            "context": "",
        },
        "verdict": None,
        "hiring_read": None,
        "findings": {"material": 0, "worthwhile": 0, "optional": 0},
        "next_action": {"route": None, "summary": ""},
        "language_review": {
            "status": None,
            "blocks": block_decisions,
        },
    }
    if feedback_rules:
        template["feedback_review"] = {
            "status": None,
            "rules": [
                {
                    "id": _object(rule, "feedback rule").get("id"),
                    "revision": _object(rule, "feedback rule").get("revision"),
                    "sha256": _object(rule, "feedback rule").get("sha256"),
                    "decision": None,
                    "note": "",
                }
                for rule in feedback_rules
            ],
        }
    atomic_write_json(output, template)
    return output
