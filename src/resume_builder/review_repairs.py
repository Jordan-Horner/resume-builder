"""Apply one guarded wording-only repair pass."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .atomic import atomic_write_text
from .layout import contained_path
from .review_blocks import (
    narrative_block_inventory_from_markdown,
)
from .review_schema import (
    _exact_fields,
    _object,
    _source_input,
    sha256_file,
)
from .selection_guard import (
    record_repair_attempts,
    selection_digest,
    write_repair_handoff,
)


def apply_review_repairs(decisions: Path, project_root: Path) -> dict[str, Any]:
    """Apply reviewer-proposed wording-only repairs to exact pinned resume blocks."""
    resolved_root = project_root.expanduser().resolve()
    decisions_path = decisions.expanduser()
    decisions_path = (
        decisions_path.resolve()
        if decisions_path.is_absolute()
        else contained_path(resolved_root, decisions_path.as_posix(), "review decisions")
    )
    reviews_root = (resolved_root / "build" / "reviews").resolve()
    if decisions_path.parent != reviews_root or not decisions_path.name.endswith(".decisions.json"):
        raise ValueError("review decisions must be a *.decisions.json file under build/reviews/")
    try:
        raw = json.loads(decisions_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid review decisions {decisions_path}: {exc}") from exc
    data = _object(raw, "review decisions")
    if data.get("version") not in {2, 3}:
        raise ValueError("automatic repairs require review decisions version 2 or 3")
    review_inputs = _object(data.get("review_inputs"), "review decisions.review_inputs")
    cold_read = _source_input(
        review_inputs.get("cold_read"),
        "review decisions cold_read",
        resolved_root,
        "build/reviews",
    )
    if sha256_file(cold_read.path) != cold_read.sha256:
        raise ValueError("cold-read package changed after reviewer decisions were prepared")
    review_package = _source_input(
        review_inputs.get("review_package"),
        "review decisions review_package",
        resolved_root,
        "build/reviews",
    )
    if sha256_file(review_package.path) != review_package.sha256:
        raise ValueError("review package changed after reviewer decisions were prepared")
    try:
        cold_raw = json.loads(cold_read.path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid cold-read package: {exc}") from exc
    cold = _object(cold_raw, "cold-read package")
    resume = _source_input(cold.get("resume"), "cold-read resume", resolved_root, "resumes")
    if sha256_file(resume.path) != resume.sha256:
        raise ValueError("resume changed after the cold-read package was created")
    cold_blocks_value = cold.get("blocks")
    if not isinstance(cold_blocks_value, list) or not cold_blocks_value:
        raise ValueError("cold-read package has no narrative blocks")
    cold_blocks = {
        str(_object(value, "cold-read block").get("id")): _object(value, "cold-read block")
        for value in cold_blocks_value
    }
    language_review = _object(data.get("language_review"), "review decisions.language_review")
    decision_blocks = language_review.get("blocks")
    if not isinstance(decision_blocks, list) or not decision_blocks:
        raise ValueError("review decisions have no narrative blocks")

    replacements: dict[str, tuple[str, str]] = {}
    for index, value in enumerate(decision_blocks):
        owner = f"review decisions.language_review.blocks[{index}]"
        block = _object(value, owner)
        _exact_fields(block, {"id", "sha256", "decision", "note", "repair"}, owner)
        if block.get("decision") != "revise" or block.get("repair") is None:
            continue
        block_id = block.get("id")
        if not isinstance(block_id, str) or block_id not in cold_blocks:
            raise ValueError(f"{owner}.id does not identify a pinned cold-read block")
        cold_block = cold_blocks[block_id]
        if block.get("sha256") != cold_block.get("sha256"):
            raise ValueError(f"{owner} does not match the pinned cold-read block")
        repair = _object(block.get("repair"), f"{owner}.repair")
        _exact_fields(repair, {"kind", "replacement"}, f"{owner}.repair")
        if repair.get("kind") != "wording-only":
            raise ValueError(f"{owner}.repair.kind must be 'wording-only'")
        replacement = repair.get("replacement")
        if not isinstance(replacement, str) or not replacement.strip():
            raise ValueError(f"{owner}.repair.replacement must be non-empty prose")
        replacement = replacement.strip()
        if "\n" in replacement or "<!--" in replacement or "-->" in replacement:
            raise ValueError(f"{owner}.repair.replacement must be one visible prose block")
        original = cold_block.get("text")
        if not isinstance(original, str) or not original:
            raise ValueError(f"cold-read block {block_id} has no prose")
        if replacement == original:
            raise ValueError(f"{owner}.repair.replacement does not change the block")
        replacements[block_id] = (original, replacement)
    if not replacements:
        raise ValueError("review decisions contain no wording-only repairs to apply")

    source = resume.path.read_text(encoding="utf-8")
    repaired = source
    for block_id, (original, replacement) in replacements.items():
        if repaired.count(original) != 1:
            raise ValueError(
                f"pinned block {block_id} is not uniquely replaceable in the resume source"
            )
        repaired = repaired.replace(original, replacement, 1)
    repaired_inventory = {
        block.id: block for block in narrative_block_inventory_from_markdown(repaired)
    }
    if set(repaired_inventory) != set(cold_blocks):
        raise ValueError("wording repair changed the narrative block structure")
    for block_id, cold_block in cold_blocks.items():
        expected_text = replacements.get(block_id, (str(cold_block.get("text")), ""))[1]
        if block_id not in replacements:
            expected_text = str(cold_block.get("text"))
        if repaired_inventory[block_id].text != expected_text:
            raise ValueError(f"wording repair changed an unexpected block: {block_id}")
    try:
        package_raw = json.loads(review_package.path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid review package: {exc}") from exc
    package = _object(package_raw, "review package")
    appendix = _object(package.get("selection_appendix"), "review package selection_appendix")
    selection = _object(appendix.get("selection"), "review package selection")
    record_repair_attempts(
        resolved_root,
        resume.path,
        selection_digest(selection),
        sorted(replacements),
    )
    atomic_write_text(resume.path, repaired)
    carried_blocks: list[dict[str, object]] = [
        {
            "id": str(block.get("id")),
            "sha256": str(block.get("sha256")),
            "decision": "approved",
            "note": str(block.get("note", "")),
        }
        for block in decision_blocks
        if isinstance(block, dict)
        and block.get("decision") == "approved"
        and block.get("id") not in replacements
    ]
    write_repair_handoff(
        resolved_root,
        resume.path,
        sha256_file(resume.path),
        selection_digest(selection),
        sorted(replacements),
        carried_blocks,
    )
    return {
        "valid": True,
        "resume": resume.path.relative_to(resolved_root).as_posix(),
        "repairs_applied": sorted(replacements),
        "next_action": "Run verify and submit every changed block to a fresh independent review.",
    }
