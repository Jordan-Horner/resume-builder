"""Choose the hybrid resume-review path from the validated synthesis strategy."""

from __future__ import annotations

from typing import Any

from .synthesis_models import SynthesisPlan


def hybrid_review_route(plan: SynthesisPlan) -> dict[str, Any]:
    """Return a transparent fit band and the review work it warrants."""
    transferable = sorted(
        item.concept_id for item in plan.concept_fit if item.status == "transferable"
    )
    unsupported = sorted(
        item.concept_id for item in plan.concept_fit if item.status == "unsupported"
    )
    open_risks = sorted(
        item.risk_id for item in plan.reviewer_risks if item.status in {"partial", "unresolved"}
    )
    signals: list[str] = []
    if plan.target_mode:
        signals.append(f"target mode is {plan.target_mode}")
    if transferable:
        signals.append(f"transferable concepts: {', '.join(transferable)}")
    if unsupported:
        signals.append(f"unsupported concepts: {', '.join(unsupported)}")
    if open_risks:
        signals.append(f"open reviewer risks: {', '.join(open_risks)}")
    if plan.gaps:
        signals.append(f"documented evidence gaps: {len(plan.gaps)}")

    if plan.target_mode == "exploratory":
        fit_band = "weak-or-exploratory"
        run_career_review = False
        next_action = "surface-evidence-gap"
        rationale = (
            "The plan is exploratory, so rewriting alone is unlikely to create a strong fit. "
            "Run language review, explain the genuine gap, and reserve the full career review "
            "for an explicit user request."
        )
    elif (
        plan.target_mode == "direct"
        and not transferable
        and not unsupported
        and not open_risks
        and not plan.gaps
    ):
        fit_band = "strong-and-well-positioned"
        run_career_review = False
        next_action = "language-review"
        rationale = (
            "The plan is direct, all concepts are demonstrated, and no material risk or gap "
            "is open. The independent language review is sufficient by default."
        )
    else:
        fit_band = "competitive-but-improvable"
        run_career_review = True
        next_action = "career-review"
        rationale = (
            "The evidence is close enough to benefit from selection, positioning, and hiring-"
            "manager judgment. Run the deeper career review after the language pass."
        )

    return {
        "version": 1,
        "policy": "hybrid-review",
        "language_review": {
            "required": True,
            "scope": "all new or changed narrative prose with unchanged approvals reused",
        },
        "fit": {
            "band": fit_band,
            "signals": signals,
        },
        "career_review": {
            "run": run_career_review,
            "next_action": next_action,
            "rationale": rationale,
        },
    }
