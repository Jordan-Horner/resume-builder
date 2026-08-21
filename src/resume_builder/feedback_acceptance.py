"""Accept reviewed feedback revisions and manage promoted rules."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .atomic import atomic_write_bytes, atomic_write_json
from .feedback_resolution import (
    RULE_ID,
    SESSION_ID,
    _effective_digest,
    _identity_digest,
    _nonempty,
    _object,
    _project_file,
    _read_json,
    _validate_rule,
    _validate_session,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _retire_rule(path: Path, data: dict[str, Any], reason: str) -> None:
    data["status"] = "retired"
    data["retired_at"] = _now()
    data["retirement_reason"] = reason
    atomic_write_json(path, data)


def _atomic_json_updates(updates: list[tuple[Path, dict[str, Any]]]) -> None:
    """Write related feedback records together and restore them on failure."""
    originals = {
        update_path: update_path.read_bytes() if update_path.is_file() else None
        for update_path, _ in updates
    }
    try:
        for update_path, value in updates:
            atomic_write_json(update_path, value)
    except BaseException:
        for update_path, original in originals.items():
            if original is None:
                update_path.unlink(missing_ok=True)
            else:
                atomic_write_bytes(update_path, original)
        raise


def _approved_wording_rule(
    root: Path,
    session: dict[str, Any],
    current: dict[str, Any],
    accepted_result: dict[str, str],
) -> tuple[Path, dict[str, Any], str]:
    """Create a fact-scoped rule for one explicitly approved current sentence."""
    scope = _object(_object(session.get("identity"), "feedback identity").get("scope"), "scope")
    if scope.get("level") != "facts":
        raise ValueError("approved wording memory requires fact-scoped feedback")

    source = _object(current.get("source"), "feedback revision source")
    resume_path = _project_file(root, source.get("resume"), "feedback source resume", "resumes")
    from .compilation import sha256_file
    from .feedback_recording import _block_inventory

    if sha256_file(resume_path) != accepted_result["resume_sha256"]:
        raise ValueError("approved wording resume changed after preview publication")
    block_id = _nonempty(source.get("block_id"), "feedback source block_id")
    block = _block_inventory(resume_path).get(block_id)
    if block is None:
        raise ValueError("approved wording block no longer exists in the accepted resume")
    fact_ids = scope.get("fact_ids")
    evidence = block.get("evidence")
    if (
        not isinstance(fact_ids, list)
        or not isinstance(evidence, list)
        or not set(str(item) for item in fact_ids).issubset(str(item) for item in evidence)
    ):
        raise ValueError("approved wording no longer cites its fact-scoped evidence")
    sentence = _nonempty(block.get("text"), "approved wording sentence")

    wording_scope = dict(scope)
    wording_scope["resume"] = None
    identity = {
        "subject_key": f"{session['identity']['subject_key']}-approved-wording",
        "kind": "presentation",
        "scope": wording_scope,
    }
    rule_id = f"ER-{_identity_digest(identity)}"
    rule_path = root / "editorial" / "rules" / f"{rule_id}.json"
    if rule_path.is_file():
        rule = _read_json(rule_path, "approved wording rule")
        _validate_rule(rule, rule_path, root)
        if rule["identity"] != identity:
            raise ValueError("existing approved wording rule has a different semantic identity")
        revisions = list(rule["revisions"])
    else:
        revisions = []
        rule = {
            "version": 1,
            "id": rule_id,
            "status": "active",
            "identity": identity,
            "strength": "preference",
            "current_revision": 0,
            "revisions": [],
            "retired_at": None,
            "retirement_reason": None,
        }
    revisions.append(
        {
            "revision": len(revisions) + 1,
            "accepted_at": _now(),
            "source_session": session["id"],
            "source_session_revision": session["current_revision"],
            "summary": "The user explicitly approved this sentence for future reuse.",
            "instruction": (
                "Reuse the approved sentence by default when this accomplishment is selected; "
                "adapt it only when the target or page constraint requires a different emphasis."
            ),
            "must_preserve": current["must_preserve"],
            "must_avoid": current["must_avoid"],
            "preferred_examples": [sentence],
        }
    )
    rule.update(
        {
            "status": "active",
            "strength": "preference",
            "current_revision": len(revisions),
            "revisions": revisions,
            "retired_at": None,
            "retirement_reason": None,
        }
    )
    return rule_path, rule, sentence


def _acceptance_result(
    root: Path,
    session: dict[str, Any],
    preview: Path,
) -> dict[str, str]:
    """Validate that one user-approved preview contains the exact open revision."""
    from .compilation import sha256_file

    preview_path = _project_file(root, preview.as_posix(), "accepted feedback preview", "build")
    if not preview_path.name.endswith(".preview.json"):
        raise ValueError("accepted feedback preview must be a *.preview.json file")
    preview_data = _read_json(preview_path, "accepted feedback preview")
    if (
        preview_data.get("version") not in {2, 3}
        or preview_data.get("phase") != "preview"
        or preview_data.get("valid") is not True
        or preview_data.get("final_review_status") != "awaiting-user-approval"
    ):
        raise ValueError("feedback acceptance requires a successful current preview")
    build_record = _object(preview_data.get("build_manifest"), "preview build manifest")
    output_record = _object(preview_data.get("output"), "preview output")
    build_path = _project_file(root, build_record.get("path"), "preview build", "build")
    output_path = _project_file(root, output_record.get("path"), "preview output", "build")
    for path, record, owner in (
        (build_path, build_record, "preview build"),
        (output_path, output_record, "preview output"),
    ):
        if record.get("sha256") != sha256_file(path):
            raise ValueError(f"{owner} changed after preview publication")
    build = _read_json(build_path, "accepted feedback build")
    memory = _object(build.get("feedback_memory"), "accepted feedback build memory")
    guidance = memory.get("rules")
    if not isinstance(guidance, list):
        raise ValueError("accepted feedback build has no effective guidance")
    current_revision = int(session["current_revision"])
    current = session["revisions"][current_revision - 1]
    digest = _effective_digest(session["identity"], session["strength"], current)
    matching_guidance = [
        item
        for item in guidance
        if isinstance(item, dict)
        and item.get("source") == "open-session"
        and item.get("id") == session["id"]
        and item.get("revision") == current_revision
        and item.get("effective_digest") == digest
    ]
    if len(matching_guidance) != 1:
        raise ValueError("preview does not contain the exact current feedback revision")
    result = {
        "resume_sha256": str(_object(build.get("source"), "build source").get("sha256")),
        "build_manifest": build_path.relative_to(root).as_posix(),
        "build_sha256": sha256_file(build_path),
        "preview_manifest": preview_path.relative_to(root).as_posix(),
        "preview_sha256": sha256_file(preview_path),
        "output": output_path.relative_to(root).as_posix(),
        "output_sha256": sha256_file(output_path),
        "effective_digest": digest,
    }
    if preview_data.get("version") == 2:
        from .review_records import load_review_record, review_freshness

        review_record = _object(preview_data.get("review_record"), "preview review record")
        review_path = _project_file(
            root, review_record.get("path"), "preview review", "build/reviews"
        )
        if review_record.get("sha256") != sha256_file(review_path):
            raise ValueError("preview review changed after preview publication")
        review = load_review_record(review_path, root)
        reasons = review_freshness(review)
        if reasons:
            raise ValueError(f"feedback acceptance review is stale or incomplete: {reasons}")
        matching_decisions = [
            decision
            for decision in review.feedback_rules
            if decision.id == session["id"] and decision.revision == current_revision
        ]
        if (
            review.feedback_status != "approved"
            or len(matching_decisions) != 1
            or matching_decisions[0].decision != "complies"
        ):
            raise ValueError("preview lacks approved compliance for the current feedback revision")
        result["review_record"] = review_path.relative_to(root).as_posix()
        result["review_sha256"] = sha256_file(review_path)
    else:
        result["approval"] = "user-approved-preview"
    return result


def accept_feedback(
    project_root: Path,
    *,
    session_id: str | None = None,
    resume: Path | None = None,
    preview: Path | None = None,
    remember_approved_wording: bool = False,
    acceptance_result_fn: Callable[
        [Path, dict[str, Any], Path], dict[str, str]
    ] = _acceptance_result,
) -> dict[str, object]:
    """Accept current feedback sessions and promote only their latest revisions."""
    root = project_root.expanduser().resolve()
    sessions_root = root / "build" / "feedback"
    paths: list[Path]
    if session_id is not None:
        if not SESSION_ID.fullmatch(session_id):
            raise ValueError("feedback session ID must look like FB-<12 lowercase hex characters>")
        paths = [sessions_root / f"{session_id}.json"]
    else:
        if resume is None:
            raise ValueError("accept requires a session ID or --resume")
        resume_path = _project_file(root, resume.as_posix(), "accepted feedback resume", "resumes")
        relative_resume = resume_path.relative_to(root).as_posix()
        paths = []
        for candidate in sorted(sessions_root.glob("FB-*.json")):
            value = _read_json(candidate, "feedback session")
            _validate_session(value, candidate, root)
            revisions = value.get("revisions")
            current_source = (
                _object(revisions[-1], "feedback revision").get("source")
                if isinstance(revisions, list) and revisions
                else None
            )
            if (
                value.get("status") == "open"
                and isinstance(revisions, list)
                and revisions
                and _object(current_source, "feedback source").get("resume") == relative_resume
            ):
                paths.append(candidate)
    if not paths:
        raise ValueError("no open feedback sessions matched the acceptance request")
    if len(paths) != 1:
        raise ValueError(
            "feedback acceptance must name one exact session; accept additional sessions separately"
        )
    if preview is None:
        raise ValueError("feedback acceptance requires --preview for the user-approved result")
    accepted: list[dict[str, object]] = []
    for path in paths:
        if not path.is_file():
            raise ValueError(f"feedback session does not exist: {path.stem}")
        session = _read_json(path, "feedback session")
        _validate_session(session, path, root)
        if session["status"] != "open":
            raise ValueError(f"feedback session is not open: {path.stem}")
        accepted_result = acceptance_result_fn(root, session, preview)
        promotion = session["promotion"]
        current = session["revisions"][session["current_revision"] - 1]
        wording_update: tuple[Path, dict[str, Any], str] | None = None
        if remember_approved_wording:
            if promotion != "hydrate":
                raise ValueError(
                    "--remember-approved-wording is only needed for factual corrections; "
                    "other reusable feedback should use its existing preferred_examples"
                )
            wording_update = _approved_wording_rule(root, session, current, accepted_result)
        if promotion == "hydrate":
            session["status"] = "needs-hydration"
            session["accepted_at"] = _now()
            session["accepted_result"] = accepted_result
            updates: list[tuple[Path, dict[str, Any]]] = []
            wording_rule_id = None
            wording_sentence = None
            if wording_update is not None:
                wording_path, wording_rule, wording_sentence = wording_update
                wording_rule_id = str(wording_rule["id"])
                session["promoted_rule"] = {
                    "id": wording_rule_id,
                    "revision": wording_rule["current_revision"],
                    "path": wording_path.relative_to(root).as_posix(),
                }
                updates.append((wording_path, wording_rule))
            updates.append((path, session))
            _atomic_json_updates(updates)
            accepted.append(
                {
                    "session_id": session["id"],
                    "route": "hydrate+memory" if wording_rule_id else "hydrate",
                    "rule": wording_rule_id,
                    "preferred_sentence": wording_sentence,
                }
            )
            continue
        if promotion == "none":
            session["status"] = "closed"
            session["accepted_at"] = _now()
            session["accepted_result"] = accepted_result
            atomic_write_json(path, session)
            accepted.append({"session_id": session["id"], "route": "closed", "rule": None})
            continue
        rules_root = root / "editorial" / "rules"
        rule_path = rules_root / f"{session['rule_id']}.json"
        if rule_path.is_file():
            rule = _read_json(rule_path, "feedback rule")
            _validate_rule(rule, rule_path, root)
            if rule["identity"] != session["identity"]:
                raise ValueError("existing feedback rule has a different semantic identity")
            revisions = list(rule["revisions"])
        else:
            revisions = []
            rule = {
                "version": 1,
                "id": session["rule_id"],
                "status": "active",
                "identity": session["identity"],
                "strength": session["strength"],
                "current_revision": 0,
                "revisions": [],
                "retired_at": None,
                "retirement_reason": None,
            }
        accepted_at = _now()
        revisions.append(
            {
                "revision": len(revisions) + 1,
                "accepted_at": accepted_at,
                "source_session": session["id"],
                "source_session_revision": session["current_revision"],
                "summary": current["summary"],
                "instruction": current["instruction"],
                "must_preserve": current["must_preserve"],
                "must_avoid": current["must_avoid"],
                "preferred_examples": current["preferred_examples"],
            }
        )
        rule.update(
            {
                "status": "active",
                "strength": session["strength"],
                "current_revision": len(revisions),
                "revisions": revisions,
                "retired_at": None,
                "retirement_reason": None,
            }
        )
        superseded_ids = list(current["supersedes"])
        previous_rule = session.get("promoted_rule")
        if (
            isinstance(previous_rule, dict)
            and isinstance(previous_rule.get("id"), str)
            and previous_rule["id"] != session["rule_id"]
            and previous_rule["id"] not in superseded_ids
        ):
            superseded_ids.append(previous_rule["id"])
        superseded_records: list[tuple[Path, dict[str, Any]]] = []
        for superseded_id in superseded_ids:
            superseded_path = rules_root / f"{superseded_id}.json"
            if not superseded_path.is_file():
                raise ValueError(f"superseded feedback rule does not exist: {superseded_id}")
            superseded = _read_json(superseded_path, "superseded feedback rule")
            _validate_rule(superseded, superseded_path, root)
            superseded_records.append((superseded_path, superseded))
        retired_updates: list[tuple[Path, dict[str, Any]]] = []
        for superseded_path, superseded in superseded_records:
            retired = dict(superseded)
            retired["status"] = "retired"
            retired["retired_at"] = _now()
            retired["retirement_reason"] = (
                f"Superseded by {session['rule_id']} revision {len(revisions)}."
            )
            retired_updates.append((superseded_path, retired))
        session["status"] = "accepted"
        session["accepted_at"] = accepted_at
        session["accepted_result"] = accepted_result
        session["promoted_rule"] = {
            "id": rule["id"],
            "revision": rule["current_revision"],
            "path": rule_path.relative_to(root).as_posix(),
        }
        updates = [*retired_updates, (rule_path, rule), (path, session)]
        _atomic_json_updates(updates)
        accepted.append(
            {
                "session_id": session["id"],
                "route": "memory",
                "rule": rule["id"],
                "revision": rule["current_revision"],
                "receipt": f"Saved for future resumes: {current['instruction']}",
            }
        )
    return {"valid": True, "accepted": accepted}


def retire_feedback_rule(rule_id: str, reason: str, project_root: Path) -> dict[str, object]:
    root = project_root.expanduser().resolve()
    if not RULE_ID.fullmatch(rule_id):
        raise ValueError("feedback rule ID must look like ER-<12 lowercase hex characters>")
    path = root / "editorial" / "rules" / f"{rule_id}.json"
    if not path.is_file():
        raise ValueError(f"feedback rule does not exist: {rule_id}")
    rule = _read_json(path, "feedback rule")
    _validate_rule(rule, path, root)
    _retire_rule(path, rule, _nonempty(reason, "retirement reason"))
    return {"valid": True, "rule": rule_id, "status": "retired"}
