"""Validate, preview, and atomically apply agent-authored vault change plans."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from .atomic import atomic_write_bytes, atomic_write_text
from .layout import LayoutError, VaultLayout, contained_path
from .validation import SHA256, validate_vault


@dataclass(frozen=True)
class PlannedWrite:
    """One optimistic, non-deleting canonical file replacement."""

    path: Path
    relative_path: str
    content: str
    expected_sha256: str | None


@dataclass(frozen=True)
class VaultChangePlan:
    """A validated collection of canonical writes."""

    source: Path
    writes: tuple[PlannedWrite, ...]
    rationale: str


def file_sha256(path: Path) -> str:
    """Hash one existing canonical file."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_plan(path: Path, layout: VaultLayout) -> VaultChangePlan:
    """Load a versioned plan and validate every target and optimistic hash."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise ValueError(f"invalid plan JSON {path}: {exc}") from exc
    if not isinstance(data, dict) or data.get("version") != 1:
        raise ValueError("vault plan must be a version 1 JSON object")
    rationale = data.get("rationale")
    if not isinstance(rationale, str) or not rationale.strip():
        raise ValueError("vault plan requires a non-empty rationale")
    raw_writes = data.get("writes")
    if not isinstance(raw_writes, list) or not raw_writes:
        raise ValueError("vault plan writes must be a non-empty list")

    writes: list[PlannedWrite] = []
    seen: set[Path] = set()
    for index, raw in enumerate(raw_writes):
        owner = f"plan write {index}"
        if not isinstance(raw, dict):
            raise ValueError(f"{owner} must be an object")
        target = contained_path(layout.root, raw.get("path"), f"{owner} path")
        is_canonical = (
            target == layout.hydration_report
            or target.is_relative_to(layout.facts)
            or target.is_relative_to(layout.employment)
        )
        if not is_canonical or (target != layout.hydration_report and target.suffix != ".md"):
            raise ValueError(f"{owner} targets a non-canonical path")
        if target in seen:
            raise ValueError(f"duplicate plan target: {layout.relative(target)}")
        seen.add(target)
        content = raw.get("content")
        if not isinstance(content, str) or not content.strip():
            raise ValueError(f"{owner} content must be a non-empty string")
        expected = raw.get("expected_sha256")
        if expected is not None and (
            not isinstance(expected, str) or not SHA256.fullmatch(expected)
        ):
            raise ValueError(f"{owner} expected_sha256 must be null or a full digest")
        if target.exists():
            if expected is None:
                raise ValueError(
                    f"{owner} would overwrite an existing file without expected_sha256"
                )
            actual = file_sha256(target)
            if actual != expected:
                raise ValueError(
                    f"{owner} stale file hash for {layout.relative(target)}: "
                    f"expected {expected}, found {actual}"
                )
        elif expected is not None:
            raise ValueError(f"{owner} expects a file that does not exist")
        writes.append(
            PlannedWrite(
                path=target,
                relative_path=layout.relative(target),
                content=content,
                expected_sha256=expected,
            )
        )
    return VaultChangePlan(source=path, writes=tuple(writes), rationale=rationale)


def validate_staged_plan(
    layout: VaultLayout,
    plan: VaultChangePlan,
) -> dict[str, object]:
    """Apply a plan to a temporary vault copy and run strict validation there."""
    with tempfile.TemporaryDirectory(prefix="vault-plan-", dir=layout.root.parent) as raw:
        staged_root = Path(raw) / "vault"
        shutil.copytree(layout.root, staged_root)
        staged_layout = VaultLayout.load(staged_root)
        for write in plan.writes:
            staged_target = staged_root / write.path.relative_to(layout.root)
            atomic_write_text(staged_target, write.content)
        return validate_vault(staged_layout.root, strict=True)


def affected_references(layout: VaultLayout, plan: VaultChangePlan) -> dict[str, object]:
    """List project artifacts that mention facts updated by this plan."""
    changed_fact_ids = sorted(
        write.path.stem
        for write in plan.writes
        if write.expected_sha256 is not None and write.path.is_relative_to(layout.facts)
    )
    result: dict[str, object] = {
        "fact_ids": changed_fact_ids,
        "resumes": [],
        "synthesis_plans": [],
        "build_manifests": [],
    }
    if not changed_fact_ids:
        return result

    project_root = layout.root.parent
    pattern = re.compile(
        r"(?<![A-Za-z0-9-])(?:"
        + "|".join(re.escape(item) for item in changed_fact_ids)
        + r")(?![A-Za-z0-9-])"
    )

    def matching_files(paths: list[Path]) -> list[str]:
        matches: list[str] = []
        for path in paths:
            try:
                content = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            if pattern.search(content):
                matches.append(path.relative_to(project_root).as_posix())
        return sorted(matches)

    resumes_root = project_root / "resumes"
    plan_root = resumes_root / "plans"
    resume_paths = (
        [path for path in resumes_root.rglob("*.md") if plan_root not in path.parents]
        if resumes_root.exists()
        else []
    )
    synthesis_paths = (
        [*plan_root.rglob("*.yaml"), *plan_root.rglob("*.yml")] if plan_root.exists() else []
    )
    build_root = project_root / "build"
    manifest_paths = list(build_root.rglob("*.manifest.json")) if build_root.exists() else []
    result["resumes"] = matching_files(resume_paths)
    result["synthesis_plans"] = matching_files(synthesis_paths)
    result["build_manifests"] = matching_files(manifest_paths)
    return result


def plan_summary(
    layout: VaultLayout,
    plan: VaultChangePlan,
    validation: dict[str, object],
    *,
    applied: bool,
) -> dict[str, object]:
    """Render a stable, reviewable plan result."""
    return {
        "valid": validation.get("valid", False),
        "applied": applied,
        "rationale": plan.rationale,
        "writes": [
            {
                "path": write.relative_path,
                "operation": "update" if write.expected_sha256 else "add",
            }
            for write in plan.writes
        ],
        "validation_errors": validation.get("errors", []),
        "validation_warnings": validation.get("warnings", []),
        "affected_references": affected_references(layout, plan),
        "vault_root": str(layout.root),
    }


def apply_plan(layout: VaultLayout, plan: VaultChangePlan) -> dict[str, object]:
    """Apply all writes with optimistic concurrency and rollback on failure."""
    staged_validation = validate_staged_plan(layout, plan)
    if not staged_validation.get("valid"):
        raise ValueError("plan does not produce a valid strict vault")

    originals: dict[Path, bytes | None] = {}
    for write in plan.writes:
        if write.path.exists():
            actual = file_sha256(write.path)
            if actual != write.expected_sha256:
                raise ValueError(f"file changed after preview: {write.relative_path}")
            originals[write.path] = write.path.read_bytes()
        else:
            if write.expected_sha256 is not None:
                raise ValueError(f"expected file disappeared: {write.relative_path}")
            originals[write.path] = None

    try:
        for write in plan.writes:
            atomic_write_text(write.path, write.content)
        final_validation = validate_vault(layout.root, strict=True)
        if not final_validation.get("valid"):
            raise ValueError("applied plan failed final strict validation")
    except BaseException:
        rollback_errors: list[str] = []
        for path, original in originals.items():
            try:
                if original is None:
                    path.unlink(missing_ok=True)
                else:
                    atomic_write_bytes(path, original)
            except OSError as exc:
                rollback_errors.append(f"{path}: {exc}")
        if rollback_errors:
            raise RuntimeError(
                "plan failed and rollback was incomplete: " + "; ".join(rollback_errors)
            ) from None
        raise
    return final_validation


def main(argv: Sequence[str] | None = None) -> int:
    """Validate, preview, or apply a versioned vault change plan."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("validate", "preview", "apply"))
    parser.add_argument("plan", type=Path)
    parser.add_argument("--vault-root", type=Path, default=Path("vault"))
    args = parser.parse_args(argv)
    try:
        layout = VaultLayout.load(args.vault_root)
        plan = load_plan(args.plan, layout)
        validation = validate_staged_plan(layout, plan)
        if args.mode == "apply":
            if not validation.get("valid"):
                raise ValueError("plan does not produce a valid strict vault")
            validation = apply_plan(layout, plan)
        result = plan_summary(
            layout,
            plan,
            validation,
            applied=args.mode == "apply",
        )
    except (LayoutError, OSError, RuntimeError, ValueError) as exc:
        print(json.dumps({"error": str(exc)}, indent=2), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["valid"] else 1
