"""Validate versioned resume synthesis plans and their compiled output."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from .audit import role_arc_payloads
from .loader import load_synthesis_plan


def sha256_file(path: Path) -> str:
    """Hash a synthesis plan for the build manifest."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(argv: Sequence[str] | None = None) -> int:
    """Validate a synthesis plan independently of resume compilation."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan", type=Path)
    parser.add_argument("--vault-root", type=Path, default=Path("vault"))
    args = parser.parse_args(argv)
    try:
        vault_root = args.vault_root.expanduser().resolve()
        project_root = vault_root.parent
        plan = load_synthesis_plan(args.plan, project_root, vault_root)
        result = {
            "valid": True,
            "version": plan.version,
            "plan": plan.source.relative_to(project_root).as_posix(),
            "resume": plan.resume.relative_to(project_root).as_posix(),
            "direction": plan.direction.relative_to(project_root).as_posix(),
            "stories": len(plan.stories),
            "core_stories": sum(story.importance == "core" for story in plan.stories),
            "supporting_stories": sum(story.importance == "supporting" for story in plan.stories),
            "summary_job": plan.summary_job,
            "summary_fact_ids": list(plan.summary_fact_ids),
            "summary_body_fact_ids": list(plan.summary_body_fact_ids),
            "progression_role_ids": list(plan.progression),
            "exclusions": len(plan.exclusions),
            "gaps": list(plan.gaps),
            "target_mode": plan.target_mode,
            "concept_fit": [
                {
                    "concept_id": item.concept_id,
                    "status": item.status,
                    "fact_ids": list(item.fact_ids),
                    "rationale": item.rationale,
                }
                for item in plan.concept_fit
            ],
            "reviewer_risks": [
                {
                    "id": item.risk_id,
                    "concern": item.concern,
                    "status": item.status,
                    "fact_ids": list(item.fact_ids),
                    "planning_action": item.planning_action,
                }
                for item in plan.reviewer_risks
            ],
            "presentation": (
                {
                    "competencies": plan.presentation.competencies,
                    "competencies_job": plan.presentation.competencies_job,
                    "compressed_role_ids": list(plan.presentation.compressed_role_ids),
                }
                if plan.presentation is not None
                else None
            ),
            "role_arcs": role_arc_payloads(plan),
            "page_budget": (
                {
                    "max_pages": plan.page_budget.max_pages,
                    "source": plan.page_budget.source,
                }
                if plan.page_budget is not None
                else None
            ),
            "resume_template": (
                {
                    "content": plan.resume_template.content.template_id,
                    "theme": plan.resume_template.theme.theme_id,
                    "renderer": plan.resume_template.theme.renderer.relative_to(
                        project_root
                    ).as_posix(),
                }
                if plan.resume_template is not None
                else None
            ),
            "sha256": sha256_file(plan.source),
        }
    except (OSError, ValueError) as exc:
        print(json.dumps({"error": str(exc)}, indent=2), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
