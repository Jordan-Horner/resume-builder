"""Load, validate, and enforce hash-pinned editorial review records."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .feedback_resolution import RULE_ID, SESSION_ID
from .layout import contained_path
from .review_blocks import BLOCK_ID

SHA256 = re.compile(r"^[0-9a-f]{64}$")
VERDICTS = {
    "ready-to-mint",
    "ready-with-optional-improvements",
    "needs-revision",
}
HIRING_READS = {
    "compelling",
    "credible-but-not-yet-differentiated",
    "weak-or-misaligned",
}
ROUTES = {"rebuild", "hydrate", "direction", "mint"}
EDITORIAL_SCOPE = "all-narrative-prose"
EDITORIAL_STATUSES = {"approved", "changes-required"}
EDITORIAL_DECISIONS = {"approved", "revise"}
REVIEW_METHODS = {"independent-cold-review", "single-context-review"}
EVIDENCE_STATUSES = {"claim-checked", "changes-required"}
FEEDBACK_STATUSES = {"approved", "changes-required", "not-applicable"}
FEEDBACK_DECISIONS = {"complies", "revise"}


@dataclass(frozen=True)
class ReviewInput:
    """One source file and the digest used during editorial review."""

    path: Path
    sha256: str


@dataclass(frozen=True)
class EditorialBlock:
    """One hash-pinned narrative block and its editorial decision."""

    id: str
    sha256: str
    decision: str
    note: str


@dataclass(frozen=True)
class FeedbackRuleDecision:
    """One accepted rule or open revision and its compliance decision."""

    id: str
    revision: int
    source: ReviewInput
    decision: str
    note: str


@dataclass(frozen=True)
class ReviewRecord:
    """Validated metadata for one editorial review."""

    source: Path
    version: int
    reviewed_at: str
    resume: ReviewInput
    plan: ReviewInput
    direction: ReviewInput
    target: ReviewInput | None
    verdict: str
    hiring_read: str
    findings: dict[str, int]
    next_route: str
    next_summary: str
    editorial_status: str
    editorial_blocks: tuple[EditorialBlock, ...]
    reviewer_method: str | None = None
    reviewer_context: str | None = None
    build_manifest: ReviewInput | None = None
    cold_read: ReviewInput | None = None
    review_package: ReviewInput | None = None
    evidence_status: str | None = None
    structured_claims: int = 0
    feedback_status: str = "not-applicable"
    feedback_rules: tuple[FeedbackRuleDecision, ...] = ()


def sha256_file(path: Path) -> str:
    """Return a lowercase SHA-256 digest for one file."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sha256_text(value: str) -> str:
    """Return the digest used to pin one normalized visible prose block."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _object(value: object, owner: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{owner} must be an object")
    return value


def _exact_fields(value: dict[str, Any], expected: set[str], owner: str) -> None:
    missing = sorted(expected - value.keys())
    unexpected = sorted(value.keys() - expected)
    if missing or unexpected:
        raise ValueError(f"{owner} fields mismatch; missing={missing}, unexpected={unexpected}")


def _source_input(
    value: object,
    owner: str,
    project_root: Path,
    allowed_directory: str,
) -> ReviewInput:
    data = _object(value, owner)
    _exact_fields(data, {"path", "sha256"}, owner)
    digest = data["sha256"]
    if not isinstance(digest, str) or not SHA256.fullmatch(digest):
        raise ValueError(f"{owner}.sha256 must be a lowercase SHA-256 digest")
    path = contained_path(project_root, data["path"], f"{owner}.path")
    allowed = (project_root / allowed_directory).resolve()
    if not path.is_relative_to(allowed) or not path.is_file():
        raise ValueError(f"{owner}.path must name an existing file under {allowed_directory}/")
    return ReviewInput(path=path, sha256=digest)


def load_review_record(path: Path, project_root: Path) -> ReviewRecord:
    """Load one strict review record from ``build/reviews``."""
    resolved_root = project_root.expanduser().resolve()
    source = path.expanduser()
    source = (resolved_root / source).resolve() if not source.is_absolute() else source.resolve()
    reviews_root = (resolved_root / "build" / "reviews").resolve()
    if source.parent != reviews_root or source.suffix != ".json":
        raise ValueError("review record must be a JSON file directly under build/reviews")
    try:
        raw = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid review record {source}: {exc}") from exc
    data = _object(raw, "review record")
    version = data.get("version")
    if version not in {2, 3, 4, 5}:
        raise ValueError("review record must declare version 2, 3, 4, or 5")
    expected_fields = {
        "version",
        "reviewed_at",
        "resume",
        "plan",
        "direction",
        "target",
        "verdict",
        "hiring_read",
        "findings",
        "next_action",
    }
    expected_fields.add("language_review" if version >= 4 else "editorial_review")
    if version >= 3:
        expected_fields.add("reviewer")
    if version >= 4:
        expected_fields.update(
            {"build_manifest", "cold_read", "review_package", "evidence_integrity"}
        )
    if version >= 5:
        expected_fields.add("feedback_review")
    _exact_fields(data, expected_fields, "review record")

    reviewer_method: str | None = None
    reviewer_context: str | None = None
    if version >= 3:
        reviewer = _object(data["reviewer"], "reviewer")
        _exact_fields(reviewer, {"method", "context"}, "reviewer")
        reviewer_method = reviewer["method"]
        reviewer_context = reviewer["context"]
        if reviewer_method not in REVIEW_METHODS:
            raise ValueError(f"reviewer.method must be one of {sorted(REVIEW_METHODS)}")
        if not isinstance(reviewer_context, str) or not reviewer_context.strip():
            raise ValueError("reviewer.context must be a non-empty string")
        reviewer_context = reviewer_context.strip()
    reviewed_at = data["reviewed_at"]
    if not isinstance(reviewed_at, str):
        raise ValueError("reviewed_at must be an ISO-8601 timestamp")
    try:
        parsed_at = datetime.fromisoformat(reviewed_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("reviewed_at must be an ISO-8601 timestamp") from exc
    if parsed_at.tzinfo is None:
        raise ValueError("reviewed_at must include a timezone")

    verdict = data["verdict"]
    if verdict not in VERDICTS:
        raise ValueError(f"review verdict must be one of {sorted(VERDICTS)}")
    hiring_read = data["hiring_read"]
    if hiring_read not in HIRING_READS:
        raise ValueError(f"review hiring_read must be one of {sorted(HIRING_READS)}")
    findings = _object(data["findings"], "review findings")
    _exact_fields(findings, {"material", "worthwhile", "optional"}, "review findings")
    if any(
        not isinstance(value, int) or isinstance(value, bool) or value < 0
        for value in findings.values()
    ):
        raise ValueError("review finding counts must be non-negative integers")
    next_action = _object(data["next_action"], "review next_action")
    _exact_fields(next_action, {"route", "summary"}, "review next_action")
    next_route = next_action["route"]
    next_summary = next_action["summary"]
    if next_route not in ROUTES:
        raise ValueError(f"review next_action.route must be one of {sorted(ROUTES)}")
    if not isinstance(next_summary, str) or not next_summary.strip():
        raise ValueError("review next_action.summary must be a non-empty string")

    build_manifest: ReviewInput | None = None
    cold_read: ReviewInput | None = None
    review_package: ReviewInput | None = None
    evidence_status: str | None = None
    structured_claims = 0
    feedback_status = "not-applicable"
    feedback_rules: list[FeedbackRuleDecision] = []
    if version >= 4:
        build_manifest = _source_input(
            data["build_manifest"], "review build_manifest", resolved_root, "build"
        )
        cold_read = _source_input(
            data["cold_read"], "review cold_read", resolved_root, "build/reviews"
        )
        review_package = _source_input(
            data["review_package"], "review package", resolved_root, "build/reviews"
        )
        evidence_integrity = _object(data["evidence_integrity"], "evidence integrity")
        _exact_fields(
            evidence_integrity,
            {"status", "method", "structured_claims"},
            "evidence integrity",
        )
        evidence_status = evidence_integrity["status"]
        if evidence_status not in EVIDENCE_STATUSES:
            raise ValueError(
                f"evidence integrity.status must be one of {sorted(EVIDENCE_STATUSES)}"
            )
        if evidence_integrity["method"] != "deterministic-structured-claims":
            raise ValueError("evidence integrity.method must be deterministic-structured-claims")
        structured_claims = evidence_integrity["structured_claims"]
        if (
            not isinstance(structured_claims, int)
            or isinstance(structured_claims, bool)
            or structured_claims < 1
        ):
            raise ValueError("evidence integrity.structured_claims must be a positive integer")
    if version >= 5:
        feedback = _object(data["feedback_review"], "feedback review")
        _exact_fields(feedback, {"status", "rules"}, "feedback review")
        raw_feedback_status = feedback.get("status")
        if not isinstance(
            raw_feedback_status, str
        ) or raw_feedback_status not in FEEDBACK_STATUSES - {"not-applicable"}:
            raise ValueError("feedback review.status must be approved or changes-required")
        feedback_status = raw_feedback_status
        raw_feedback_rules = feedback.get("rules")
        if not isinstance(raw_feedback_rules, list) or not raw_feedback_rules:
            raise ValueError("feedback review.rules must be a non-empty list")
        seen_feedback_rules: set[tuple[str, int]] = set()
        for index, value in enumerate(raw_feedback_rules):
            owner = f"feedback review.rules[{index}]"
            rule = _object(value, owner)
            _exact_fields(
                rule,
                {"id", "revision", "path", "sha256", "decision", "note"},
                owner,
            )
            rule_id = rule.get("id")
            revision = rule.get("revision")
            if not isinstance(rule_id, str) or not (
                RULE_ID.fullmatch(rule_id) or SESSION_ID.fullmatch(rule_id)
            ):
                raise ValueError(f"{owner}.id must be a feedback rule or session ID")
            if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
                raise ValueError(f"{owner}.revision must be a positive integer")
            key = (rule_id, revision)
            if key in seen_feedback_rules:
                raise ValueError(f"duplicate feedback rule decision: {rule_id} revision {revision}")
            seen_feedback_rules.add(key)
            decision = rule.get("decision")
            note = rule.get("note")
            if decision not in FEEDBACK_DECISIONS:
                raise ValueError(f"{owner}.decision must be complies or revise")
            if not isinstance(note, str):
                raise ValueError(f"{owner}.note must be a string")
            if decision == "revise" and not note.strip():
                raise ValueError(f"{owner}.note must explain a revise decision")
            source_directory = (
                "build/feedback" if SESSION_ID.fullmatch(rule_id) else "editorial/rules"
            )
            source_input = _source_input(
                {"path": rule.get("path"), "sha256": rule.get("sha256")},
                owner,
                resolved_root,
                source_directory,
            )
            feedback_rules.append(
                FeedbackRuleDecision(
                    id=rule_id,
                    revision=revision,
                    source=source_input,
                    decision=str(decision),
                    note=note.strip(),
                )
            )
        has_feedback_revisions = any(rule.decision == "revise" for rule in feedback_rules)
        if feedback_status == "approved" and has_feedback_revisions:
            raise ValueError("approved feedback review cannot contain revise decisions")
        if feedback_status == "changes-required" and not has_feedback_revisions:
            raise ValueError("changes-required feedback review requires a revise decision")
        if feedback_status == "changes-required" and verdict != "needs-revision":
            raise ValueError("feedback changes-required requires a needs-revision verdict")
        if verdict != "needs-revision" and feedback_status != "approved":
            raise ValueError("a ready verdict requires approved feedback compliance")

    review_field = "language_review" if version >= 4 else "editorial_review"
    editorial = _object(data[review_field], "language review")
    _exact_fields(editorial, {"scope", "status", "blocks"}, "language review")
    if editorial["scope"] != EDITORIAL_SCOPE:
        raise ValueError(f"editorial review.scope must be {EDITORIAL_SCOPE!r}")
    editorial_status = editorial["status"]
    if editorial_status not in EDITORIAL_STATUSES:
        raise ValueError(f"editorial review.status must be one of {sorted(EDITORIAL_STATUSES)}")
    raw_blocks = editorial["blocks"]
    if not isinstance(raw_blocks, list) or not raw_blocks:
        raise ValueError("editorial review.blocks must be a non-empty list")
    editorial_blocks: list[EditorialBlock] = []
    seen_block_ids: set[str] = set()
    for index, value in enumerate(raw_blocks):
        owner = f"editorial review.blocks[{index}]"
        block = _object(value, owner)
        _exact_fields(block, {"id", "sha256", "decision", "note"}, owner)
        block_id = block["id"]
        digest = block["sha256"]
        decision = block["decision"]
        note = block["note"]
        if not isinstance(block_id, str) or not BLOCK_ID.fullmatch(block_id):
            raise ValueError(f"{owner}.id is not a supported narrative block ID")
        if block_id in seen_block_ids:
            raise ValueError(f"editorial review contains duplicate block ID: {block_id}")
        seen_block_ids.add(block_id)
        if not isinstance(digest, str) or not SHA256.fullmatch(digest):
            raise ValueError(f"{owner}.sha256 must be a lowercase SHA-256 digest")
        if decision not in EDITORIAL_DECISIONS:
            raise ValueError(f"{owner}.decision must be one of {sorted(EDITORIAL_DECISIONS)}")
        if not isinstance(note, str):
            raise ValueError(f"{owner}.note must be a string")
        if decision == "revise" and not note.strip():
            raise ValueError(f"{owner}.note must explain a revise decision")
        editorial_blocks.append(
            EditorialBlock(
                id=block_id,
                sha256=digest,
                decision=decision,
                note=note.strip(),
            )
        )
    has_revisions = any(block.decision == "revise" for block in editorial_blocks)
    if editorial_status == "approved" and has_revisions:
        raise ValueError("approved editorial review cannot contain revise decisions")
    if editorial_status == "changes-required" and not has_revisions:
        raise ValueError("changes-required editorial review must contain a revise decision")
    if editorial_status == "changes-required" and verdict != "needs-revision":
        raise ValueError("changes-required editorial review requires a needs-revision verdict")
    if verdict != "needs-revision" and editorial_status != "approved":
        raise ValueError("a ready review verdict requires approved narrative prose")
    if (
        version >= 3
        and editorial_status == "approved"
        and reviewer_method != "independent-cold-review"
    ):
        raise ValueError(
            "version 3 approved prose requires reviewer.method independent-cold-review"
        )
    if version >= 4 and evidence_status != "claim-checked" and verdict != "needs-revision":
        raise ValueError("evidence changes-required status requires a needs-revision verdict")

    target_value = data["target"]
    target = (
        None
        if target_value is None
        else _source_input(target_value, "review target", resolved_root, "targets")
    )
    if version >= 4:
        assert build_manifest is not None
        assert cold_read is not None
        assert review_package is not None
        try:
            package_raw = json.loads(review_package.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid review package {review_package.path}: {exc}") from exc
        package = _object(package_raw, "review package")
        if package.get("version") != 1:
            raise ValueError("review package must declare version 1")
        for owner, expected in (
            ("resume", data["resume"]),
            ("build_manifest", data["build_manifest"]),
            ("plan", data["plan"]),
            ("direction", data["direction"]),
            ("target", data["target"]),
            ("cold_read", data["cold_read"]),
        ):
            if package.get(owner) != expected:
                raise ValueError(f"review package {owner} does not match review record")
        try:
            cold_read_raw = json.loads(cold_read.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid cold-read package {cold_read.path}: {exc}") from exc
        cold_read_data = _object(cold_read_raw, "cold-read package")
        if cold_read_data.get("version") != 1:
            raise ValueError("cold-read package must declare version 1")
        if cold_read_data.get("resume") != data["resume"]:
            raise ValueError("cold-read package resume does not match review record")
        if cold_read_data.get("target") != data["target"]:
            raise ValueError("cold-read package target does not match review record")
        package_blocks = cold_read_data.get("blocks")
        if not isinstance(package_blocks, list):
            raise ValueError("review package cold_read.blocks must be a list")
        package_block_pins: dict[str, str] = {}
        for index, value in enumerate(package_blocks):
            block = _object(value, f"review package cold_read.blocks[{index}]")
            block_id = block.get("id")
            digest = block.get("sha256")
            if not isinstance(block_id, str) or not isinstance(digest, str):
                raise ValueError(f"review package cold_read.blocks[{index}] has invalid block pins")
            if block_id in package_block_pins:
                raise ValueError(f"review package contains duplicate block ID: {block_id}")
            package_block_pins[block_id] = digest
        reviewed_block_pins = {block.id: block.sha256 for block in editorial_blocks}
        if package_block_pins != reviewed_block_pins:
            raise ValueError("review decisions do not cover the exact review package blocks")
        if version >= 5:
            selection_appendix = _object(
                package.get("selection_appendix"), "review package selection_appendix"
            )
            memory = _object(
                selection_appendix.get("feedback_memory"),
                "review package feedback_memory",
            )
            package_rules = memory.get("rules")
            if not isinstance(package_rules, list):
                raise ValueError("review package feedback_memory.rules must be a list")
            package_pins = {
                (
                    str(_object(rule, "review package feedback rule").get("id")),
                    int(_object(rule, "review package feedback rule").get("revision", 0)),
                ): (
                    _object(rule, "review package feedback rule").get("path"),
                    _object(rule, "review package feedback rule").get("sha256"),
                )
                for rule in package_rules
            }
            reviewed_pins = {
                (rule.id, rule.revision): (
                    rule.source.path.relative_to(resolved_root).as_posix(),
                    rule.source.sha256,
                )
                for rule in feedback_rules
            }
            if package_pins != reviewed_pins:
                raise ValueError("feedback review does not cover the exact applicable rules")
    return ReviewRecord(
        source=source,
        version=version,
        reviewed_at=reviewed_at,
        resume=_source_input(data["resume"], "review resume", resolved_root, "resumes"),
        plan=_source_input(data["plan"], "review plan", resolved_root, "resumes/plans"),
        direction=_source_input(data["direction"], "review direction", resolved_root, "directions"),
        target=target,
        verdict=verdict,
        hiring_read=hiring_read,
        findings={name: int(value) for name, value in findings.items()},
        next_route=next_route,
        next_summary=next_summary.strip(),
        editorial_status=editorial_status,
        editorial_blocks=tuple(editorial_blocks),
        reviewer_method=reviewer_method,
        reviewer_context=reviewer_context,
        build_manifest=build_manifest,
        cold_read=cold_read,
        review_package=review_package,
        evidence_status=evidence_status,
        structured_claims=structured_claims,
        feedback_status=feedback_status,
        feedback_rules=tuple(feedback_rules),
    )
