"""Prepare, repair, and validate hash-pinned editorial resume reviews."""

from __future__ import annotations

import hashlib
import json
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import __version__
from .atomic import atomic_write_json, atomic_write_text
from .compilation import compile_markdown
from .feedback_memory import RULE_ID, SESSION_ID, manifest_guidance_freshness
from .layout import contained_path
from .synthesis import load_synthesis_plan, role_arc_payloads

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
BLOCK_ID = re.compile(
    r"^(?:candidate\.headline|summary|competencies\[\d+\]|"
    r"experience\[\d+\]\.bullets\[\d+\]|projects\[\d+\]\.(?:name|description|tech)|"
    r"education\[\d+\]\.description)$"
)


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
class NarrativeReviewBlock:
    """One narrative block with the visible context needed for editorial judgment."""

    id: str
    text: str
    context: dict[str, str | None]
    advisories: tuple[str, ...] = ()


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


def _neighbor_context(items: list[str], index: int) -> dict[str, str | None]:
    """Return the adjacent visible prose surrounding one ordered block."""
    return {
        "previous_block": items[index - 1] if index > 0 else None,
        "next_block": items[index + 1] if index + 1 < len(items) else None,
    }


def _opening_advisories(text: str, role: str | None) -> tuple[str, ...]:
    """Flag high-confidence role-title repetition without deciding editorial quality."""
    if not role:
        return ()
    opening = re.match(
        r"^(?:as|in\s+(?:my|the)\s+role\s+as)\s+(?:an?\s+)?([^,;:]+)[,;:]",
        text,
        re.IGNORECASE,
    )
    if opening is None:
        return ()
    words = re.compile(r"[a-z0-9]+")
    opening_tokens = set(words.findall(opening.group(1).casefold()))
    role_tokens = set(words.findall(role.casefold()))
    if opening_tokens and opening_tokens <= role_tokens:
        return (
            "opening may repeat the visible role heading; verify that it adds scope, "
            "authority, chronology, contrast, or necessary qualification",
        )
    return ()


def _density_advisories(text: str) -> tuple[str, ...]:
    """Flag likely nested enumerations without imposing a universal length limit."""
    comma_count = text.count(",")
    conjunction_count = len(re.findall(r"\b(?:and|or)\b", text, re.IGNORECASE))
    has_clause_pivot = re.search(r"\b(?:while|then)\b", text, re.IGNORECASE) is not None
    if (comma_count >= 6 and conjunction_count >= 2) or (comma_count >= 5 and has_clause_pivot):
        return (
            "block may contain nested lists competing with its main claim; verify that each "
            "enumerated detail materially improves proof, scope, outcome, or differentiation",
        )
    return ()


def _contribution_advisories(text: str) -> tuple[str, ...]:
    """Flag openings that describe tool contact or leave authority unresolved."""
    advisories: list[str] = []
    if re.match(r"^(?:used|utilized|leveraged)\b", text, re.IGNORECASE):
        advisories.append(
            "opening describes tool use rather than the candidate's contribution; verify that "
            "the supported diagnosis, resolution, change, or result leads the sentence"
        )
    if re.match(r"^participated in or led\b", text, re.IGNORECASE):
        advisories.append(
            "opening leaves the candidate's authority unresolved; preserve uncertainty but "
            "state the supported contribution directly"
        )
    return tuple(advisories)


def _prose_advisories(text: str, role: str | None = None) -> tuple[str, ...]:
    """Return high-confidence prompts for contextual editorial review."""
    return (
        *_opening_advisories(text, role),
        *_density_advisories(text),
        *_contribution_advisories(text),
    )


def narrative_block_inventory(path: Path) -> tuple[NarrativeReviewBlock, ...]:
    """Return narrative prose with its visible resume context in reading order."""
    return narrative_block_inventory_from_markdown(path.read_text(encoding="utf-8"))


def narrative_block_inventory_from_markdown(
    markdown: str,
) -> tuple[NarrativeReviewBlock, ...]:
    """Return narrative prose from an in-memory canonical resume."""
    payload = compile_markdown(markdown)
    blocks: list[NarrativeReviewBlock] = []
    candidate = _object(payload.get("candidate"), "candidate")
    candidate_name = str(candidate.get("name", "")) or None
    headline = candidate.get("headline")
    if isinstance(headline, str) and headline.strip():
        headline = headline.strip()
        blocks.append(
            NarrativeReviewBlock(
                id="candidate.headline",
                text=headline,
                context={"section": "Header", "candidate_name": candidate_name},
                advisories=_prose_advisories(headline),
            )
        )
    summary = str(payload["summary"])
    blocks.append(
        NarrativeReviewBlock(
            id="summary",
            text=summary,
            context={"section": "Professional Summary", "headline": str(headline or "") or None},
            advisories=_prose_advisories(summary),
        )
    )
    competency_texts = [str(item["text"]) for item in payload["competencies"]]
    for index, text in enumerate(competency_texts):
        blocks.append(
            NarrativeReviewBlock(
                id=f"competencies[{index}]",
                text=text,
                context={
                    "section": "Core Competencies",
                    **_neighbor_context(competency_texts, index),
                },
                advisories=_prose_advisories(text),
            )
        )
    for experience_index, experience in enumerate(payload["experience"]):
        bullet_texts = [str(bullet["text"]) for bullet in experience["bullets"]]
        company = str(experience.get("company", "")) or None
        role = str(experience.get("role", "")) or None
        dates = str(experience.get("dates", "")) or None
        location = str(experience.get("location", "")) or None
        for bullet_index, bullet in enumerate(experience["bullets"]):
            text = str(bullet["text"])
            blocks.append(
                NarrativeReviewBlock(
                    id=f"experience[{experience_index}].bullets[{bullet_index}]",
                    text=text,
                    context={
                        "section": "Work Experience",
                        "company": company,
                        "role": role,
                        "dates": dates,
                        "location": location,
                        **_neighbor_context(bullet_texts, bullet_index),
                    },
                    advisories=_prose_advisories(text, role),
                )
            )
    for index, project in enumerate(payload["projects"]):
        name = str(project["name"])
        description = str(project["description"])
        blocks.append(
            NarrativeReviewBlock(
                id=f"projects[{index}].name",
                text=name,
                context={"section": "Selected Projects"},
                advisories=_prose_advisories(name),
            )
        )
        blocks.append(
            NarrativeReviewBlock(
                id=f"projects[{index}].description",
                text=description,
                context={"section": "Selected Projects", "project": name},
                advisories=_prose_advisories(description),
            )
        )
        if project.get("tech"):
            blocks.append(
                NarrativeReviewBlock(
                    id=f"projects[{index}].tech",
                    text=str(project["tech"]),
                    context={
                        "section": "Selected Projects",
                        "project": name,
                        "previous_block": description,
                    },
                    advisories=_prose_advisories(str(project["tech"])),
                )
            )
    for index, education in enumerate(payload["education"]):
        if education.get("description"):
            blocks.append(
                NarrativeReviewBlock(
                    id=f"education[{index}].description",
                    text=str(education["description"]),
                    context={
                        "section": "Education",
                        "degree": str(education.get("degree", "")) or None,
                        "institution": str(education.get("org", "")) or None,
                    },
                    advisories=_prose_advisories(str(education["description"])),
                )
            )
    return tuple(blocks)


def narrative_blocks(path: Path) -> dict[str, str]:
    """Return the stable text-only block map used by versioned review records."""
    return {block.id: block.text for block in narrative_block_inventory(path)}


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
    build_manifest_path = resolved_root / "build" / f"{resume_path.stem}.manifest.json"
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
            and existing_package.get("resume") == expected_resume
            and existing_package.get("build_manifest") == expected_build
            and existing_package.get("plan") == expected_plan
            and existing_package.get("direction") == expected_direction
            and existing_package.get("target") == target_record
            and existing_package.get("cold_read") == expected_cold
        ):
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
            "blocks": [
                {
                    "id": block.id,
                    "sha256": sha256_text(block.text),
                    "decision": None,
                    "note": "",
                    "repair": None,
                }
                for block in inventory
            ],
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


def finalize_review_record(
    decisions: Path,
    project_root: Path,
    *,
    output: Path | None = None,
) -> dict[str, Any]:
    """Build and validate a version 4 review record from reviewer decisions."""
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
    decisions_version = data.get("version")
    if decisions_version not in {1, 2, 3}:
        raise ValueError("review decisions must declare version 1, 2, or 3")
    decision_fields = {
        "version",
        "generated_at",
        "review_inputs",
        "reviewer",
        "verdict",
        "hiring_read",
        "findings",
        "next_action",
        "language_review",
    }
    if decisions_version >= 3:
        decision_fields.add("feedback_review")
    _exact_fields(data, decision_fields, "review decisions")
    review_inputs = _object(data["review_inputs"], "review decisions.review_inputs")
    _exact_fields(
        review_inputs,
        {"cold_read", "review_package"},
        "review decisions.review_inputs",
    )
    cold_read = _source_input(
        review_inputs["cold_read"], "review decisions cold_read", resolved_root, "build/reviews"
    )
    review_package = _source_input(
        review_inputs["review_package"],
        "review decisions review_package",
        resolved_root,
        "build/reviews",
    )
    for item, owner in (
        (cold_read, "cold-read package"),
        (review_package, "review package"),
    ):
        if sha256_file(item.path) != item.sha256:
            raise ValueError(f"{owner} changed after reviewer decisions were prepared")
    try:
        package = json.loads(review_package.path.read_text(encoding="utf-8"))
        cold = json.loads(cold_read.path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid pinned review input: {exc}") from exc
    package_data = _object(package, "review package")
    cold_data = _object(cold, "cold-read package")
    if package_data.get("version") != 1 or cold_data.get("version") != 1:
        raise ValueError("review inputs must declare version 1")
    if package_data.get("cold_read") != review_inputs["cold_read"]:
        raise ValueError("review package does not pin the selected cold-read package")

    selection_appendix = _object(
        package_data.get("selection_appendix"), "review package selection_appendix"
    )
    memory = _object(
        selection_appendix.get("feedback_memory"),
        "review package feedback_memory",
    )
    package_feedback_rules = memory.get("rules")
    if not isinstance(package_feedback_rules, list):
        raise ValueError("review package feedback_memory.rules must be a list")
    if package_feedback_rules and decisions_version < 3:
        raise ValueError("applicable feedback rules require review decisions version 3")

    language_review = _object(data["language_review"], "review decisions.language_review")
    _exact_fields(language_review, {"status", "blocks"}, "review decisions.language_review")
    package_blocks = cold_data.get("blocks")
    if not isinstance(package_blocks, list) or not package_blocks:
        raise ValueError("cold-read package has no narrative blocks")
    decision_blocks = language_review.get("blocks")
    if not isinstance(decision_blocks, list) or not decision_blocks:
        raise ValueError("review decisions have no narrative blocks")
    normalized_decision_blocks: list[dict[str, object]] = []
    for index, value in enumerate(decision_blocks):
        owner = f"review decisions.language_review.blocks[{index}]"
        block = _object(value, owner)
        expected_fields = {"id", "sha256", "decision", "note"}
        if decisions_version >= 2:
            expected_fields.add("repair")
        _exact_fields(block, expected_fields, owner)
        repair = block.get("repair")
        if repair is not None:
            repair_data = _object(repair, f"{owner}.repair")
            _exact_fields(repair_data, {"kind", "replacement"}, f"{owner}.repair")
            if repair_data.get("kind") != "wording-only":
                raise ValueError(f"{owner}.repair.kind must be 'wording-only'")
            replacement = repair_data.get("replacement")
            if not isinstance(replacement, str) or not replacement.strip():
                raise ValueError(f"{owner}.repair.replacement must be non-empty prose")
            if block.get("decision") != "revise":
                raise ValueError(f"{owner}.repair requires a revise decision")
        normalized_decision_blocks.append(
            {
                "id": block.get("id"),
                "sha256": block.get("sha256"),
                "decision": block.get("decision"),
                "note": block.get("note"),
            }
        )

    normalized_feedback_rules: list[dict[str, object]] = []
    feedback_status = "not-applicable"
    if decisions_version >= 3:
        feedback_review = _object(data["feedback_review"], "review decisions.feedback_review")
        _exact_fields(feedback_review, {"status", "rules"}, "review decisions.feedback_review")
        raw_feedback_status = feedback_review.get("status")
        if not isinstance(
            raw_feedback_status, str
        ) or raw_feedback_status not in FEEDBACK_STATUSES - {"not-applicable"}:
            raise ValueError("feedback review.status must be approved or changes-required")
        feedback_status = raw_feedback_status
        decision_rules = feedback_review.get("rules")
        if not isinstance(decision_rules, list) or not decision_rules:
            raise ValueError("feedback review.rules must be a non-empty list")
        package_rule_pins: dict[tuple[str, int], dict[str, Any]] = {}
        for index, raw_rule in enumerate(package_feedback_rules):
            owner = f"review package feedback rule[{index}]"
            rule = _object(raw_rule, owner)
            rule_id = rule.get("id")
            revision = rule.get("revision")
            if not isinstance(rule_id, str) or not isinstance(revision, int):
                raise ValueError(f"{owner} has invalid rule identity")
            package_rule_pins[(rule_id, revision)] = rule
        decision_rule_pins: set[tuple[str, int]] = set()
        for index, raw_rule in enumerate(decision_rules):
            owner = f"review decisions.feedback_review.rules[{index}]"
            rule = _object(raw_rule, owner)
            _exact_fields(rule, {"id", "revision", "sha256", "decision", "note"}, owner)
            rule_id = rule.get("id")
            revision = rule.get("revision")
            digest = rule.get("sha256")
            decision = rule.get("decision")
            note = rule.get("note")
            key = (str(rule_id), revision if isinstance(revision, int) else -1)
            package_rule = package_rule_pins.get(key)
            if package_rule is None or package_rule.get("sha256") != digest:
                raise ValueError(f"{owner} does not match an applicable feedback rule")
            if decision not in FEEDBACK_DECISIONS:
                raise ValueError(f"{owner}.decision must be complies or revise")
            if not isinstance(note, str):
                raise ValueError(f"{owner}.note must be a string")
            if decision == "revise" and not note.strip():
                raise ValueError(f"{owner}.note must explain a revise decision")
            decision_rule_pins.add(key)
            normalized_feedback_rules.append(
                {
                    "id": rule_id,
                    "revision": revision,
                    "path": package_rule.get("path"),
                    "sha256": digest,
                    "decision": decision,
                    "note": note.strip(),
                }
            )
        if decision_rule_pins != set(package_rule_pins):
            raise ValueError("feedback review does not cover the exact applicable rules")
        has_feedback_revisions = any(
            rule["decision"] == "revise" for rule in normalized_feedback_rules
        )
        if feedback_status == "approved" and has_feedback_revisions:
            raise ValueError("approved feedback review cannot contain revise decisions")
        if feedback_status == "changes-required" and not has_feedback_revisions:
            raise ValueError("changes-required feedback review requires a revise decision")
        if feedback_status == "changes-required" and data["verdict"] != "needs-revision":
            raise ValueError("feedback changes-required requires a needs-revision verdict")
        if data["verdict"] != "needs-revision" and feedback_status != "approved":
            raise ValueError("a ready verdict requires approved feedback compliance")
    package_pins = {
        str(_object(block, "cold-read block").get("id")): str(
            _object(block, "cold-read block").get("sha256")
        )
        for block in package_blocks
    }
    decision_pins = {
        str(_object(block, "review decision block").get("id")): str(
            _object(block, "review decision block").get("sha256")
        )
        for block in decision_blocks
    }
    if package_pins != decision_pins:
        raise ValueError("review decisions do not cover the exact cold-read narrative blocks")

    build_manifest_record = _object(
        package_data.get("build_manifest"), "review package build_manifest"
    )
    build_manifest = _source_input(
        build_manifest_record, "review package build_manifest", resolved_root, "build"
    )
    if sha256_file(build_manifest.path) != build_manifest.sha256:
        raise ValueError("compiled build changed after the review package was created")
    try:
        build_data = json.loads(build_manifest.path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid compiled build manifest: {exc}") from exc
    evidence = _object(build_data.get("evidence"), "compiled evidence audit")
    structured_claims = evidence.get("structured_claims_checked")
    if not isinstance(structured_claims, int) or isinstance(structured_claims, bool):
        raise ValueError("compiled evidence audit has no structured-claim count")

    reviewer = _object(data["reviewer"], "review decisions.reviewer")
    findings = _object(data["findings"], "review decisions.findings")
    next_action = _object(data["next_action"], "review decisions.next_action")
    record = {
        "version": 5 if decisions_version >= 3 else 4,
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
        "reviewer": reviewer,
        "resume": package_data.get("resume"),
        "plan": package_data.get("plan"),
        "direction": package_data.get("direction"),
        "target": package_data.get("target"),
        "build_manifest": build_manifest_record,
        "cold_read": review_inputs["cold_read"],
        "review_package": review_inputs["review_package"],
        "evidence_integrity": {
            "status": "claim-checked",
            "method": "deterministic-structured-claims",
            "structured_claims": structured_claims,
        },
        "verdict": data["verdict"],
        "hiring_read": data["hiring_read"],
        "findings": findings,
        "next_action": next_action,
        "language_review": {
            "scope": EDITORIAL_SCOPE,
            "status": language_review.get("status"),
            "blocks": normalized_decision_blocks,
        },
    }
    if decisions_version >= 3:
        record["feedback_review"] = {
            "status": feedback_status,
            "rules": normalized_feedback_rules,
        }
    destination = (
        output or reviews_root / f"{decisions_path.name.removesuffix('.decisions.json')}.json"
    )
    destination = (
        destination.resolve()
        if destination.is_absolute()
        else contained_path(resolved_root, destination.as_posix(), "review record output")
    )
    if destination.parent != reviews_root or destination.suffix != ".json":
        raise ValueError("review record output must be a JSON file directly under build/reviews/")
    candidate = reviews_root / f".{destination.stem}.candidate.json"
    atomic_write_json(candidate, record)
    try:
        validated = load_review_record(candidate, resolved_root)
        reasons = review_freshness(validated)
        if reasons:
            raise ValueError(f"review decisions are stale or incomplete: {reasons}")
    finally:
        candidate.unlink(missing_ok=True)
    atomic_write_json(destination, record)
    return {
        "valid": True,
        "record": destination.relative_to(resolved_root).as_posix(),
        "version": record["version"],
        "language_status": validated.editorial_status,
        "verdict": validated.verdict,
        "hiring_read": validated.hiring_read,
        "blocks": len(validated.editorial_blocks),
        "feedback_status": validated.feedback_status,
        "feedback_rules": len(validated.feedback_rules),
    }


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
    atomic_write_text(resume.path, repaired)
    return {
        "valid": True,
        "resume": resume.path.relative_to(resolved_root).as_posix(),
        "repairs_applied": sorted(replacements),
        "next_action": "Run verify and submit every changed block to a fresh independent review.",
    }


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
    """Return the fresh approved review that authorizes minting ``resume``."""
    review_path = project_root / "build" / "reviews" / f"{resume.stem}.json"
    if not review_path.is_file():
        raise ValueError("mint requires a fresh career-professional review record")
    record = load_review_record(review_path, project_root)
    if record.resume.path != resume.resolve():
        raise ValueError("review record names a different resume")
    reasons = review_freshness(record)
    if reasons:
        raise ValueError(f"career-professional review is stale or incomplete: {reasons}")
    if record.editorial_status != "approved":
        rejected = [block.id for block in record.editorial_blocks if block.decision == "revise"]
        raise ValueError(f"career-professional language review requires changes: {rejected}")
    if record.version >= 4 and record.evidence_status != "claim-checked":
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


def main(argv: Sequence[str] | None = None) -> int:
    """Manage career-professional review inputs, repairs, and records."""
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="action", required=True)
    blocks_parser = subparsers.add_parser("blocks", help="List hash-pinned narrative blocks")
    blocks_parser.add_argument("resume", type=Path)
    blocks_parser.add_argument("--project-root", type=Path, default=Path("."))
    package_parser = subparsers.add_parser(
        "package", help="Create the exact cold-read and evidence appendix for review"
    )
    package_parser.add_argument("resume", type=Path)
    package_parser.add_argument("--target", type=Path)
    package_parser.add_argument("--project-root", type=Path, default=Path("."))
    validate_parser = subparsers.add_parser("validate", help="Validate a review record")
    validate_parser.add_argument("record", type=Path)
    validate_parser.add_argument("--project-root", type=Path, default=Path("."))
    finalize_parser = subparsers.add_parser(
        "finalize", help="Create a validated review record from reviewer decisions"
    )
    finalize_parser.add_argument("decisions", type=Path)
    finalize_parser.add_argument("--output", type=Path)
    finalize_parser.add_argument("--project-root", type=Path, default=Path("."))
    repair_parser = subparsers.add_parser(
        "apply-repairs", help="Apply exact wording-only repairs from reviewer decisions"
    )
    repair_parser.add_argument("decisions", type=Path)
    repair_parser.add_argument("--project-root", type=Path, default=Path("."))
    args = parser.parse_args(argv)
    project_root = args.project_root.expanduser().resolve()
    try:
        if args.action == "blocks":
            resume = contained_path(project_root, args.resume.as_posix(), "resume")
            resumes_root = (project_root / "resumes").resolve()
            if not resume.is_relative_to(resumes_root) or not resume.is_file():
                raise ValueError("resume must name an existing file under resumes/")
            blocks = narrative_block_inventory(resume)
            result = {
                "valid": True,
                "resume": {
                    "path": resume.relative_to(project_root).as_posix(),
                    "sha256": sha256_file(resume),
                },
                "scope": EDITORIAL_SCOPE,
                "blocks": [
                    {
                        "id": block.id,
                        "sha256": sha256_text(block.text),
                        "text": block.text,
                        "context": block.context,
                        "advisories": list(block.advisories),
                    }
                    for block in blocks
                ],
            }
        elif args.action == "package":
            output = build_review_package(args.resume, project_root, target=args.target)
            cold_read = output.with_name(f"{output.name.removesuffix('.package.json')}.cold.json")
            decisions = output.with_name(
                f"{output.name.removesuffix('.package.json')}.decisions.json"
            )
            result = {
                "valid": True,
                "cold_read": {
                    "path": cold_read.relative_to(project_root).as_posix(),
                    "sha256": sha256_file(cold_read),
                },
                "package": output.relative_to(project_root).as_posix(),
                "sha256": sha256_file(output),
                "decisions": decisions.relative_to(project_root).as_posix(),
            }
        elif args.action == "finalize":
            result = finalize_review_record(
                args.decisions,
                project_root,
                output=args.output,
            )
        elif args.action == "apply-repairs":
            result = apply_review_repairs(args.decisions, project_root)
        else:
            record = load_review_record(args.record, project_root)
            reasons = review_freshness(record)
            result = {
                "valid": not reasons,
                "version": record.version,
                "evidence_status": record.evidence_status or "legacy-not-separated",
                "language_status": record.editorial_status,
                "verdict": record.verdict,
                "hiring_read": record.hiring_read,
                "reviewer_method": record.reviewer_method,
                "blocks": len(record.editorial_blocks),
                "feedback_status": record.feedback_status,
                "feedback_rules": len(record.feedback_rules),
                "reasons": reasons,
            }
            if reasons:
                print(json.dumps(result, indent=2), file=sys.stderr)
                return 2
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": str(exc)}, indent=2), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    return 0
