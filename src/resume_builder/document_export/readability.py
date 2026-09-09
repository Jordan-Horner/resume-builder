"""Deterministic ATS readability checks for the exact minted PDF."""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any, TypedDict

REPORT_VERSION = 1
MAX_RECOMMENDED_BYTES = 5 * 1024 * 1024
SECTION_TITLES = {
    "summary": "Professional Summary",
    "competencies": "Core Competencies",
    "experience": "Work Experience",
    "projects": "Selected Projects",
    "education": "Education",
    "certifications": "Certifications",
    "skills": "Technical Skills",
}


class ReadabilityCheck(TypedDict):
    id: str
    passed: bool
    points: int
    blocking: bool


def _tokens(value: str) -> list[str]:
    return re.findall(r"[a-z0-9+#.]+", value.casefold())


def _contains_tokens(extracted: str, value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return True
    available = _tokens(extracted)
    required = _tokens(value)
    return all(token in available for token in required)


def _find_sequence(haystack: Sequence[str], needle: Sequence[str], start: int) -> int | None:
    if not needle:
        return start
    end = len(haystack) - len(needle) + 1
    for index in range(start, max(start, end)):
        if list(haystack[index : index + len(needle)]) == list(needle):
            return index
    return None


def _ordered_anchors(payload: dict[str, Any]) -> list[tuple[str, str]]:
    anchors: list[tuple[str, str]] = []
    candidate = payload.get("candidate")
    if isinstance(candidate, dict) and isinstance(candidate.get("name"), str):
        anchors.append(("candidate.name", candidate["name"]))
    section_order = payload.get("section_order")
    if not isinstance(section_order, list):
        section_order = list(SECTION_TITLES)
    for section_id in section_order:
        if section_id not in SECTION_TITLES:
            continue
        if section_id != "summary" and not payload.get(section_id):
            continue
        anchors.append((f"section.{section_id}", SECTION_TITLES[section_id]))
        if section_id == "experience":
            for index, item in enumerate(payload.get("experience", [])):
                if isinstance(item, dict) and isinstance(item.get("company"), str):
                    anchors.append((f"experience[{index}].company", item["company"]))
    return anchors


def _reading_order(extracted: str, payload: dict[str, Any]) -> tuple[bool, list[str]]:
    haystack = _tokens(extracted)
    cursor = 0
    missing_or_scrambled: list[str] = []
    for owner, value in _ordered_anchors(payload):
        needle = _tokens(value)
        found = _find_sequence(haystack, needle, cursor)
        if found is None:
            missing_or_scrambled.append(owner)
            continue
        cursor = found + len(needle)
    return not missing_or_scrambled, missing_or_scrambled


def build_ats_readability_report(
    pages: list[str],
    payload: dict[str, Any],
    *,
    missing_blocks: list[str],
    bad_glyphs: bool,
    encrypted: bool,
    image_objects: int,
    file_size_bytes: int,
) -> dict[str, Any]:
    """Return a versioned parseability report without predicting an employer decision."""
    extracted = "\n".join(pages)
    empty_pages = [index + 1 for index, value in enumerate(pages) if not value.strip()]
    order_ok, order_issues = _reading_order(extracted, payload)
    candidate = payload.get("candidate")
    candidate = candidate if isinstance(candidate, dict) else {}
    contact_fields = {
        key: _contains_tokens(extracted, candidate.get(key))
        for key in ("name", "email", "phone", "location")
        if isinstance(candidate.get(key), str) and candidate[key].strip()
    }
    contact_ok = bool(contact_fields.get("name")) and all(contact_fields.values())
    section_order = payload.get("section_order")
    section_order = section_order if isinstance(section_order, list) else list(SECTION_TITLES)
    section_fields = {
        section_id: _contains_tokens(extracted, SECTION_TITLES[section_id])
        for section_id in section_order
        if section_id in SECTION_TITLES
        and (section_id == "summary" or bool(payload.get(section_id)))
    }
    section_ok = bool(section_fields.get("summary")) and all(section_fields.values())
    experience_fields: dict[str, bool] = {}
    for index, item in enumerate(payload.get("experience", [])):
        if not isinstance(item, dict):
            continue
        for key in ("company", "role", "dates"):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                experience_fields[f"experience[{index}].{key}"] = _contains_tokens(extracted, value)
    experience_ok = all(experience_fields.values())
    checks: list[ReadabilityCheck] = [
        {
            "id": "extractable-pages",
            "passed": bool(pages) and not empty_pages,
            "points": 15,
            "blocking": True,
        },
        {
            "id": "content-completeness",
            "passed": not missing_blocks,
            "points": 25,
            "blocking": True,
        },
        {"id": "reading-order", "passed": order_ok, "points": 20, "blocking": True},
        {"id": "contact-recognition", "passed": contact_ok, "points": 15, "blocking": True},
        {"id": "section-recognition", "passed": section_ok, "points": 10, "blocking": True},
        {"id": "employment-structure", "passed": experience_ok, "points": 10, "blocking": True},
        {"id": "supported-glyphs", "passed": not bad_glyphs, "points": 2, "blocking": True},
        {"id": "not-encrypted", "passed": not encrypted, "points": 1, "blocking": True},
        {"id": "no-image-objects", "passed": image_objects == 0, "points": 1, "blocking": True},
        {
            "id": "reasonable-file-size",
            "passed": file_size_bytes <= MAX_RECOMMENDED_BYTES,
            "points": 1,
            "blocking": False,
        },
    ]
    score = sum(check["points"] for check in checks if check["passed"])
    blocking_failures = [
        check["id"] for check in checks if check["blocking"] and not check["passed"]
    ]
    advisories = [check["id"] for check in checks if not check["blocking"] and not check["passed"]]
    return {
        "version": REPORT_VERSION,
        "status": "PASS" if not blocking_failures else "FAIL",
        "parseability_score": score,
        "score_scale": 100,
        "method": (
            "Deterministic readability checks for the minted PDF; not an ATS ranking, "
            "job-match score, interview probability, or guarantee for every vendor."
        ),
        "checks": checks,
        "blocking_failures": blocking_failures,
        "advisories": advisories,
        "details": {
            "empty_pages": empty_pages,
            "missing_blocks": missing_blocks,
            "reading_order_issues": order_issues,
            "contacts": contact_fields,
            "sections": section_fields,
            "employment_fields": experience_fields,
            "image_objects": image_objects,
            "file_size_bytes": file_size_bytes,
        },
    }
