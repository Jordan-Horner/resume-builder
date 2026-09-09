"""Render safe human-readable job-match reports."""

from __future__ import annotations

import html
import re
import unicodedata
from collections.abc import Sequence
from typing import Any


def _source_text(value: object) -> str:
    text = "".join(
        " " if char.isspace() or unicodedata.category(char) in {"Cc", "Cf"} else char
        for char in str(value)
    )
    return re.sub(r" +", " ", text).strip()


def _inline(value: object) -> str:
    return re.sub(r"([\\`*_\[\]!.:~])", r"\\\1", html.escape(_source_text(value), quote=False))


def _cell(value: object) -> str:
    return _inline(value).replace("|", "\\|")


def _code(value: object) -> str:
    text = _source_text(value)
    fence = "`" * (max((len(run) for run in re.findall(r"`+", text)), default=0) + 1)
    return (
        f"{fence} {text} {fence}"
        if "`" in text or text.startswith(" ") or text.endswith(" ")
        else f"{fence}{text}{fence}"
    )


def _list(values: Sequence[object]) -> str:
    return ", ".join(_inline(value) for value in values) or "none"


def markdown_report(result: dict[str, Any]) -> str:
    """Render a concise, human-reviewable companion to the JSON audit."""
    lines = [
        f"# Job Match: {_inline(result['target']['company'])} — {_inline(result['target']['role'])}",
        "",
        "This is an exact-retrieval and preservation report, not an ATS score or hiring verdict.",
        "",
        f"- Target: {_code(result['target']['path'])}",
        f"- Resume: {_code(result['resume']['path'])}",
        f"- Direction: {_code(result['target']['direction'])}",
        "",
        "## Exact retrieval",
        "",
        "| Search group | Importance | Found | Demonstrated | Matched terms | Locations |",
        "|---|---|---:|---:|---|---|",
    ]
    for group in result["resume"]["audit"]["exact_retrieval"]["groups"]:
        terms = ", ".join(str(match["term"]) for match in group["matches"]) or "—"
        owners = sorted(
            {
                str(location["owner"])
                for match in group["matches"]
                for location in match["locations"]
            }
        )
        lines.append(
            "| {id} | {importance} | {found} | {demonstrated} | {terms} | {locations} |".format(
                id=_cell(group["id"]),
                importance=_cell(group["importance"]),
                found="yes" if group["found"] else "no",
                demonstrated="yes" if group["demonstrated"] else "no",
                terms=_cell(terms),
                locations=_cell(", ".join(owners) or "—"),
            )
        )
    retrieval = result["resume"]["audit"]["exact_retrieval"]
    lines.extend(
        [
            "",
            f"Required groups not retrieved: {_list(retrieval['required_missing_group_ids'])}",
            f"Retrieved only outside experience/project proof: {_list(retrieval['listed_without_demonstration_group_ids'])}",
        ]
    )
    if comparison := result.get("comparison"):
        delta = comparison["delta"]
        lines.extend(
            [
                "",
                "## Baseline comparison",
                "",
                f"- Baseline: {_code(comparison['baseline']['path'])}",
                f"- Retrieval gained: {_list(delta['retrieval']['gained_group_ids'])}",
                f"- Retrieval lost: {_list(delta['retrieval']['lost_group_ids'])}",
                f"- Evidence IDs added: {_list(delta['evidence']['added_fact_ids'])}",
                f"- Evidence IDs removed: {_list(delta['evidence']['removed_fact_ids'])}",
            ]
        )
    if semantic := result.get("semantic_review"):
        lines.extend(
            [
                "",
                "## Semantic classification",
                "",
                f"**Match: {_inline(semantic['label'])}**",
                "",
                _inline(semantic["reason"]),
                "",
                "| Criterion | Requirement type | Status | Sufficiency | Confidence | Gap |",
                "|---|---|---|---|---|---|",
            ]
        )
        for criterion in semantic["criteria"]:
            lines.append(
                "| {criterion} | {requirement_type} | {status} | {sufficiency} | {confidence} | {gap} |".format(
                    criterion=_cell(criterion["criterion_id"]),
                    requirement_type=_cell(criterion["requirement_type"]),
                    status=_cell(criterion["status"]),
                    sufficiency=_cell(criterion["evidence_sufficiency"]),
                    confidence=_cell(criterion["confidence"]),
                    gap=_cell(criterion["gap"] or "—"),
                )
            )
        lines.extend(
            [
                "",
                f"Controlling criteria: {_list(semantic['controlling_criterion_ids'])}",
                f"Lifestyle risks: {_list(semantic['lifestyle_risk_ids'])}",
            ]
        )
    lines.extend(
        [
            "",
            "## Required judgment",
            "",
            (
                "The semantic classification above is the controlling resume-only match."
                if result.get("semantic_review")
                else "Review each posting criterion against cited resume evidence. Use met, partial, not_met, or undecidable; do not convert this lexical report into a percentage or pass prediction."
            ),
            "",
        ]
    )
    return "\n".join(lines)
