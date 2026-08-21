"""Pure workflow policy for project readiness and next actions."""

from __future__ import annotations

from typing import Any


def _next_action(
    vault: dict[str, Any],
    directions: list[dict[str, Any]],
    resumes: list[dict[str, Any]],
    targets: list[dict[str, Any]],
    evaluations: dict[str, Any],
    errors: list[str],
) -> dict[str, str]:
    registered_sources = int(vault.get("registered_sources", 0))
    facts = int(vault.get("facts", 0))
    if not registered_sources and not facts:
        return {
            "route": "needs-sources",
            "message": "Add a resume, LinkedIn export, career note, or other source material.",
        }
    if registered_sources and not facts:
        return {
            "route": "needs-hydration",
            "message": "Source registration is complete; finish reviewed career-fact hydration.",
        }
    if not vault.get("valid"):
        return {"route": "fix-vault", "message": "Resolve the vault validation errors."}
    readiness = _initial_draft_readiness(vault)
    if not readiness["ready"]:
        return {
            "route": "needs-hydration",
            "message": "Hydrate enough role and experience evidence for a safe first draft.",
        }
    if errors:
        return {"route": "fix-project", "message": "Resolve invalid project records."}
    if not directions:
        return {
            "route": "needs-direction",
            "message": "Choose the target career direction before building the first draft.",
        }
    baselines = [record for record in resumes if record["kind"] == "baseline"]
    if not baselines:
        return {"route": "build-baseline", "message": "Build the first directional baseline."}
    for record in baselines:
        if record["plan"]["status"] != "valid":
            return {"route": "plan", "message": f"Create or repair the plan for {record['path']}."}
        if record["build"]["status"] != "current":
            return {
                "route": "preview",
                "message": f"Build and preview {record['path']} from current inputs.",
            }
        if record["preview"]["status"] != "current":
            return {
                "route": "preview",
                "message": f"Preview {record['path']} for user edits.",
            }
        if record["preview"].get("release_readiness") == "revise-language":
            return {
                "route": "revise-language",
                "message": f"Revise the flagged language in {record['path']}.",
            }
    for target in targets:
        if target["tailored_resume"] is None:
            return {
                "route": "tailor",
                "message": f"Build a tailored resume for {target['company']} — {target['role']}.",
            }
        tailored = next(record for record in resumes if record["path"] == target["tailored_resume"])
        if tailored["build"]["status"] != "current":
            return {
                "route": "preview",
                "message": f"Build and preview {tailored['path']} from current inputs.",
            }
        if tailored["preview"]["status"] != "current":
            return {
                "route": "preview",
                "message": f"Preview {tailored['path']} for user edits.",
            }
        if tailored["preview"].get("release_readiness") == "revise-language":
            return {
                "route": "revise-language",
                "message": f"Revise the flagged language in {tailored['path']}.",
            }
        if tailored["mint"]["status"] != "current":
            return {
                "route": "mint",
                "message": f"Mint {tailored['path']} after explicit final approval.",
            }
    if evaluations["unsealed"]:
        return {
            "route": "seal-evaluations",
            "message": "Finish editorial comparison and seal the remaining regression cases.",
        }
    if evaluations["uncovered_baselines"]:
        return {
            "route": "assess-regression-coverage",
            "message": "Add a regression case only if an uncovered baseline has a suitable earlier resume in the same lane.",
        }
    return {
        "route": "maintain",
        "message": "The current workflow is ready for the next target or vault update.",
    }


def _initial_draft_readiness(vault: dict[str, Any]) -> dict[str, object]:
    """Require role chronology and usable experience evidence when typed counts exist."""
    facts = int(vault.get("facts", 0))
    raw_types = vault.get("types")
    if not isinstance(raw_types, dict):
        return {"ready": facts > 0, "reasons": [] if facts else ["no canonical facts"]}
    roles = int(raw_types.get("role", 0))
    evidence = sum(
        int(raw_types.get(kind, 0))
        for kind in ("accomplishment", "incident", "leadership", "project", "responsibility")
    )
    reasons = []
    if roles == 0:
        reasons.append("no supported role chronology")
    if evidence == 0:
        reasons.append("no usable experience evidence")
    return {"ready": not reasons, "reasons": reasons}


def _onboarding_status(
    next_action: dict[str, str],
    vault: dict[str, Any],
) -> dict[str, object]:
    """Describe the progressive first-run stage without storing duplicate state."""
    route = next_action["route"]
    messages = {
        "needs-sources": (
            "I don't have any resume material yet. Attach one or more resume files, give me "
            "the exact folder path where they are stored, paste resume text, provide a "
            "LinkedIn export, or start from career notes."
        ),
        "needs-hydration": (
            "I registered your source material, but career-fact extraction is not finished. "
            "I will review the imported evidence before asking you for anything else."
        ),
        "needs-direction": (
            "I imported your resume and found enough information to build from it. Some "
            "experience may be undersold, particularly around outcomes, scale, and leadership. "
            "Choose a target direction first; after I build the initial draft, I'll ask only "
            "the questions most likely to strengthen it."
        ),
        "build-baseline": "Your evidence and direction are ready for the first resume draft.",
    }
    return {
        "stage": route,
        "active": route in messages,
        "message": messages.get(route, next_action["message"]),
        "initial_draft_readiness": _initial_draft_readiness(vault),
    }
