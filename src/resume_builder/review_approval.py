"""Evaluate review freshness and enforce release authorization."""

from __future__ import annotations

import json
from pathlib import Path

from .feedback_resolution import manifest_guidance_freshness
from .layout import contained_path
from .review_blocks import narrative_block_inventory
from .review_schema import ReviewRecord, load_review_record, sha256_file, sha256_text
from .selection_guard import load_seal, selection_digest
from .selection_review import require_approved_selection_review


def review_freshness(record: ReviewRecord) -> list[str]:
    """Return every review input whose current digest differs from the record."""
    inputs = [record.resume, record.plan, record.direction]
    if record.target is not None:
        inputs.append(record.target)
    if record.build_manifest is not None:
        inputs.append(record.build_manifest)
    if record.cold_read is not None:
        inputs.append(record.cold_read)
    if record.review_package is not None:
        inputs.append(record.review_package)
    reasons = [
        f"{item.path.name} changed after review"
        for item in inputs
        if sha256_file(item.path) != item.sha256
    ]
    resume_changed = any(
        item.path == record.resume.path and sha256_file(item.path) != item.sha256 for item in inputs
    )
    if resume_changed:
        return reasons
    if record.build_manifest is not None and record.build_manifest.path.is_file():
        try:
            build = json.loads(record.build_manifest.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            reasons.append(f"build manifest is invalid: {exc}")
        else:
            if not isinstance(build, dict):
                reasons.append("build manifest is not an object")
            else:
                project_root = record.resume.path.parents[2]
                for owner, value in (
                    ("source", build.get("source")),
                    ("template", build.get("template")),
                    ("synthesis", build.get("synthesis")),
                ):
                    if not isinstance(value, dict):
                        reasons.append(f"build {owner} record is missing")
                        continue
                    path_value = value.get("path")
                    digest = value.get("sha256")
                    if not isinstance(path_value, str) or not isinstance(digest, str):
                        reasons.append(f"build {owner} record is invalid")
                        continue
                    try:
                        current_path = contained_path(
                            project_root, path_value, f"build {owner} path"
                        )
                    except ValueError as exc:
                        reasons.append(str(exc))
                        continue
                    if not current_path.is_file() or sha256_file(current_path) != digest:
                        reasons.append(f"build {owner} changed after evidence review")
                outputs = build.get("outputs")
                if not isinstance(outputs, list) or not outputs:
                    reasons.append("build output records are missing")
                else:
                    for index, output in enumerate(outputs):
                        if not isinstance(output, dict):
                            reasons.append(f"build output[{index}] record is invalid")
                            continue
                        path_value = output.get("path")
                        digest = output.get("sha256")
                        if not isinstance(path_value, str) or not isinstance(digest, str):
                            reasons.append(f"build output[{index}] record is invalid")
                            continue
                        try:
                            output_path = contained_path(
                                project_root, path_value, f"build output[{index}] path"
                            )
                        except ValueError as exc:
                            reasons.append(str(exc))
                            continue
                        if not output_path.is_file() or sha256_file(output_path) != digest:
                            reasons.append(f"{output_path.name} changed after evidence review")
                evidence = build.get("evidence")
                facts = evidence.get("facts") if isinstance(evidence, dict) else None
                vault_root = project_root / "vault"
                if not isinstance(facts, list):
                    reasons.append("build manifest evidence facts are missing")
                else:
                    for index, fact in enumerate(facts):
                        if not isinstance(fact, dict):
                            reasons.append(f"build fact[{index}] record is invalid")
                            continue
                        path_value = fact.get("path")
                        digest = fact.get("sha256")
                        if not isinstance(path_value, str) or not isinstance(digest, str):
                            reasons.append(f"build fact[{index}] record is invalid")
                            continue
                        try:
                            fact_path = contained_path(
                                vault_root, path_value, f"build fact[{index}] path"
                            )
                        except ValueError as exc:
                            reasons.append(str(exc))
                            continue
                        if not fact_path.is_file() or sha256_file(fact_path) != digest:
                            reasons.append(f"{fact_path.name} changed after evidence review")
                if record.version >= 4 and isinstance(evidence, dict):
                    checked = evidence.get("structured_claims_checked")
                    if checked != record.structured_claims:
                        reasons.append(
                            "review structured-claim count disagrees with build evidence audit"
                        )
                reasons.extend(
                    manifest_guidance_freshness(
                        build,
                        project_root,
                        project_root / "vault",
                    )
                )
    inventory = narrative_block_inventory(record.resume.path)
    expected = {block.id: block.text for block in inventory}
    expected_inventory = {block.id: block for block in inventory}
    reviewed = {block.id: block for block in record.editorial_blocks}
    missing = sorted(expected.keys() - reviewed.keys())
    unexpected = sorted(reviewed.keys() - expected.keys())
    changed = sorted(
        block_id
        for block_id, text in expected.items()
        if block_id in reviewed and reviewed[block_id].sha256 != sha256_text(text)
    )
    if missing:
        reasons.append(f"editorial review is missing narrative blocks: {missing}")
    if unexpected:
        reasons.append(f"editorial review contains unknown narrative blocks: {unexpected}")
    if changed:
        reasons.append(f"narrative block hashes do not match: {changed}")
    unaddressed_advisories = sorted(
        block_id
        for block_id, editorial_block in reviewed.items()
        if block_id in expected_inventory
        and expected_inventory[block_id].advisories
        and editorial_block.decision == "approved"
        and not editorial_block.note
    )
    if unaddressed_advisories:
        reasons.append(
            "approved narrative blocks with advisories require a reviewer note: "
            f"{unaddressed_advisories}"
        )
    return reasons


def require_editorial_approval(
    resume: Path,
    project_root: Path,
    *,
    accept_review_risk: bool = False,
) -> ReviewRecord:
    """Return a fresh approved record for a route-required or requested deep critique."""
    review_path = project_root / "build" / "reviews" / f"{resume.stem}.json"
    if not review_path.is_file():
        raise ValueError("critique finalization requires a fresh career-professional review record")
    record = load_review_record(review_path, project_root)
    if record.resume.path != resume.resolve():
        raise ValueError("review record names a different resume")
    if record.version < 4:
        raise ValueError(
            "critique finalization requires a version 4 or 5 review record; "
            "legacy review records remain readable but cannot authorize approval"
        )
    if record.version == 4 and record.build_manifest is not None:
        try:
            build = json.loads(record.build_manifest.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            build = None
        memory = build.get("feedback_memory") if isinstance(build, dict) else None
        rules = memory.get("rules") if isinstance(memory, dict) else None
        if isinstance(rules, list) and rules:
            raise ValueError(
                "critique finalization requires a version 5 review record when the build "
                "applied feedback guidance"
            )
    require_approved_selection_review(project_root, record.resume.path)
    reasons = review_freshness(record)
    if reasons:
        raise ValueError(f"career-professional review is stale or incomplete: {reasons}")
    if record.editorial_status != "approved":
        rejected = [block.id for block in record.editorial_blocks if block.decision == "revise"]
        raise ValueError(f"career-professional language review requires changes: {rejected}")
    if record.evidence_status != "claim-checked":
        raise ValueError("resume evidence integrity requires changes")
    if record.version >= 5 and record.feedback_status != "approved":
        rejected = [rule.id for rule in record.feedback_rules if rule.decision == "revise"]
        raise ValueError(f"accepted feedback compliance requires changes: {rejected}")
    if record.verdict == "needs-revision" and not accept_review_risk:
        raise ValueError(
            "career-professional verdict is needs-revision; resolve it or explicitly pass "
            "--accept-review-risk after the user accepts the documented non-language tradeoff"
        )
    return record


def carried_career_review(
    resume: Path,
    project_root: Path,
    selection: dict[str, object],
    strategy_sha256: str,
) -> dict[str, str | bool] | None:
    """Reuse a sealed hiring judgment when only independently reviewed prose changed."""
    try:
        require_approved_selection_review(
            project_root,
            resume,
            strategy_sha256=strategy_sha256,
        )
        seal = load_seal(project_root, resume)
    except ValueError:
        return None
    if seal is None or seal.get("selection_sha256") != selection_digest(selection):
        return None
    review_ref = seal.get("review")
    if not isinstance(review_ref, dict) or not isinstance(review_ref.get("path"), str):
        return None
    try:
        review_path = contained_path(project_root, review_ref["path"], "sealed career review")
    except ValueError:
        return None
    if (
        review_path.parent != (project_root / "build" / "reviews").resolve()
        or not review_path.is_file()
        or review_ref.get("sha256") != sha256_file(review_path)
    ):
        return None
    try:
        raw = json.loads(review_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict) or raw.get("version") not in {4, 5}:
        return None
    reviewer = raw.get("reviewer")
    resume_ref = raw.get("resume")
    evidence = raw.get("evidence_integrity")
    language = raw.get("language_review")
    next_action = raw.get("next_action")
    if (
        not isinstance(reviewer, dict)
        or reviewer.get("method") != "independent-cold-review"
        or not isinstance(resume_ref, dict)
        or resume_ref.get("path") != resume.relative_to(project_root).as_posix()
        or not isinstance(evidence, dict)
        or evidence.get("status") != "claim-checked"
        or not isinstance(language, dict)
        or language.get("status") != "approved"
        or not isinstance(next_action, dict)
        or not isinstance(next_action.get("summary"), str)
    ):
        return None
    if raw.get("version") == 5:
        feedback = raw.get("feedback_review")
        if not isinstance(feedback, dict) or feedback.get("status") != "approved":
            return None
    verdict = raw.get("verdict")
    hiring_read = raw.get("hiring_read")
    if not isinstance(verdict, str) or not isinstance(hiring_read, str):
        return None
    return {
        "path": review_path.relative_to(project_root).as_posix(),
        "sha256": sha256_file(review_path),
        "verdict": verdict,
        "hiring_read": hiring_read,
        "next_action": next_action["summary"],
        "carried_forward": True,
    }
