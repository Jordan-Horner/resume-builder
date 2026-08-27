from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum


class WorkMode(StrEnum):
    REMOTE = "remote"
    HYBRID = "hybrid"
    ONSITE = "onsite"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class WorkModeEvidence:
    mode: WorkMode
    source: str
    rule: str
    matched_text: str = ""


@dataclass(frozen=True, slots=True)
class WorkArrangement:
    available_modes: frozenset[WorkMode]
    evidence: tuple[WorkModeEvidence, ...] = ()

    def __post_init__(self) -> None:
        modes = self.available_modes or frozenset({WorkMode.UNKNOWN})
        if WorkMode.UNKNOWN in modes and len(modes) > 1:
            modes = frozenset(mode for mode in modes if mode is not WorkMode.UNKNOWN)
        object.__setattr__(self, "available_modes", frozenset(modes))

    def supports(self, mode: WorkMode) -> bool:
        return mode in self.available_modes


HYBRID_PATTERNS = (
    re.compile(r"\bhybrid\s+(?:role|position|job|schedule|work\s+arrangement)\b", re.I),
    re.compile(r"\b(?:this|the)\s+(?:role|position|job)\s+is\s+(?:a\s+)?hybrid\b", re.I),
    re.compile(
        r"\b(?:one|two|three|four|five|\d+)\s+(?:remote|office)\s+days?\s+"
        r"(?:each|per)\s+week\b",
        re.I,
    ),
)
ONSITE_PATTERNS = (
    re.compile(r"\brequir(?:e|es|ed|ing)\b.{0,60}\b(?:on[ -]?site|in[ -]?office)\b", re.I | re.S),
    re.compile(r"\b(?:on[ -]?site|in[ -]?office)\s+(?:presence|work|schedule|days?)\b", re.I),
    re.compile(r"\boffice[- ]based\s+(?:role|position|job|work)\b", re.I),
)
REMOTE_PATTERNS = (
    re.compile(r"\b(?:fully|entirely|100\s*%)\s+remote\b", re.I),
    re.compile(r"\bwork(?:ing)?\s+(?:entirely\s+|fully\s+)?remotely\b", re.I),
    re.compile(r"\bwork(?:ing)?\s+from\s+home\b", re.I),
    re.compile(
        r"\b(?:this|the)\s+(?:role|position|job|opportunity)\s+is\s+"
        r"(?:a\s+)?(?:fully\s+|entirely\s+)?remote\b",
        re.I,
    ),
    re.compile(r"\bremote\s+(?:role|position|job|opportunity|workplace)\b", re.I),
    re.compile(r"\b(?:work\s+)?location\s*[:\-]\s*remote\b", re.I),
    re.compile(
        r"\bremote\s+(?:within|across|throughout|from)\s+(?:the\s+)?"
        r"(?:u\.?s\.?|united\s+states|usa)\b",
        re.I,
    ),
)


def explicit_arrangement(
    modes: Iterable[WorkMode | str],
    *,
    source: str,
    rule: str,
    matched_text: str = "",
) -> WorkArrangement:
    normalized = frozenset(WorkMode(mode) for mode in modes)
    return WorkArrangement(
        normalized,
        tuple(WorkModeEvidence(mode, source, rule, matched_text) for mode in normalized),
    )


def classify_work_arrangement(
    *,
    title: str = "",
    location: str = "",
    description: str = "",
    legacy_remote: bool | None = None,
) -> WorkArrangement:
    if legacy_remote is True:
        return explicit_arrangement(
            [WorkMode.REMOTE],
            source="legacy",
            rule="legacy_remote_true",
        )

    structured = f"{title}\n{location}"
    location_patterns = (
        (WorkMode.HYBRID, re.compile(r"\bhybrid\b", re.I), "structured_hybrid"),
        (
            WorkMode.ONSITE,
            re.compile(r"\b(?:on[ -]?site|in[ -]?office|office[- ]based)\b", re.I),
            "structured_onsite",
        ),
        (
            WorkMode.REMOTE,
            re.compile(r"\b(?:remote|work\s+from\s+home|wfh)\b", re.I),
            "structured_remote",
        ),
    )
    # Free-text title uses can be technical (for example, "hybrid cloud" or
    # "remote support"), so only the location field supplies the broad keyword
    # evidence. Explicit arrangement phrases in the description are handled below.
    for mode, pattern, rule in location_patterns:
        if mode is WorkMode.REMOTE and legacy_remote is False:
            continue
        if match := pattern.search(location):
            return explicit_arrangement(
                [mode], source="listing_location", rule=rule, matched_text=match.group(0)
            )

    for mode, patterns, rule in (
        (WorkMode.HYBRID, HYBRID_PATTERNS, "description_hybrid"),
        (WorkMode.ONSITE, ONSITE_PATTERNS, "description_onsite"),
        (WorkMode.REMOTE, REMOTE_PATTERNS, "description_remote"),
    ):
        if mode is WorkMode.REMOTE and legacy_remote is False:
            continue
        for pattern in patterns:
            if match := pattern.search(description):
                return explicit_arrangement(
                    [mode], source="job_description", rule=rule, matched_text=match.group(0)
                )

    # Keep the title in the signature so callers have one stable classifier
    # interface; deliberately do not infer arrangements from bare title words.
    _ = structured
    return explicit_arrangement([WorkMode.UNKNOWN], source="inferred", rule="insufficient_evidence")


def display_work_mode(modes: Iterable[WorkMode]) -> str:
    normalized = frozenset(modes)
    if len(normalized) == 1:
        return next(iter(normalized)).value
    return "mixed" if normalized else WorkMode.UNKNOWN.value
