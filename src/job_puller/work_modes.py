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
    re.compile(
        r"\bhybrid\s+(?:schedule|work(?:ing)?(?:\s+(?:arrangement|model|policy))?|"
        r"workplace|arrangement|model|policy)\b",
        re.I,
    ),
    re.compile(r"\b(?:this|the)\s+(?:role|position|job)\s+is\s+(?:a\s+)?hybrid\b", re.I),
    re.compile(
        r"\b(?:location|work\s+location)\s*[:\-][^.\n]{0,100}\(\s*hybrid\s*\)",
        re.I,
    ),
    re.compile(
        r"\b(?:work\s+arrangement|workplace\s+options?)\s*:\s*"
        r"(?:this\s+(?:role|position)\s+is\s+)?(?:fully\s+on[ -]?site\s*,?\s*or\s+)?"
        r"hybrid(?:\s*/\s*flex)?\b",
        re.I,
    ),
    re.compile(
        r"\b(?:one|two|three|four|five|\d+)\s+(?:remote|office)\s+days?\s+"
        r"(?:each|per)\s+week\b",
        re.I,
    ),
    re.compile(
        r"\b(?:office|in[ -]?office|on[ -]?site)\b.{0,100}"
        r"\b(?:minimum\s+of\s+|at\s+least\s+|up\s+to\s+)?"
        r"(?:one|two|three|four|[1-4]|[1-4]\s*[-\N{EN DASH}]\s*[1-4])\s+days?\s*"
        r"(?:/|a\s+|each\s+|per\s+)week\b",
        re.I | re.S,
    ),
    re.compile(
        r"\b(?:one|two|three|four|[1-4]|[1-4]\s*[-\N{EN DASH}]\s*[1-4])\s+days?\s*"
        r"(?:/|a\s+|each\s+|per\s+)week\b.{0,100}"
        r"\b(?:office|in[ -]?office|on[ -]?site)\b",
        re.I | re.S,
    ),
)
ONSITE_REMOTE_OVERRIDE_PATTERNS = (
    re.compile(
        r"\b(?:work\s+arrangement|workplace\s+type|telework\s+and\s+travel|location)"
        r"\s*:\s*(?:fully\s+)?on[ -]?site\b",
        re.I,
    ),
    re.compile(
        r"\brequir(?:e|es|ed|ing)\b.{0,80}\b(?:come\s+)?into\s+"
        r"(?:the\s+)?office\b",
        re.I | re.S,
    ),
    re.compile(
        r"\b(?:this|the)\s+(?:role|position|job)\s+is\s+(?:a\s+)?"
        r"(?:fully\s+)?on[ -]?site\b",
        re.I,
    ),
)
ONSITE_PATTERNS = (
    *ONSITE_REMOTE_OVERRIDE_PATTERNS,
    re.compile(r"\brequir(?:e|es|ed|ing)\b.{0,60}\b(?:on[ -]?site|in[ -]?office)\b", re.I | re.S),
    re.compile(r"\b(?:on[ -]?site|in[ -]?office)\s+(?:role|position|job)\b", re.I),
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
    if legacy_remote is True and re.search(
        r"\bremote\s+unless\b.{0,160}\b(?:on[ -]?site|in[ -]?office|office\s+presence)\b",
        description,
        re.I | re.S,
    ):
        return explicit_arrangement(
            [WorkMode.REMOTE],
            source="job_description",
            rule="conditional_remote_location",
            matched_text="remote unless",
        )

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
        if mode is WorkMode.REMOTE:
            continue
        if match := pattern.search(location):
            return explicit_arrangement(
                [mode], source="listing_location", rule=rule, matched_text=match.group(0)
            )

    for pattern in HYBRID_PATTERNS:
        if match := pattern.search(description):
            return explicit_arrangement(
                [WorkMode.HYBRID],
                source="job_description",
                rule="description_hybrid",
                matched_text=match.group(0),
            )

    if legacy_remote is True:
        for pattern in ONSITE_REMOTE_OVERRIDE_PATTERNS:
            if match := pattern.search(description):
                return explicit_arrangement(
                    [WorkMode.ONSITE],
                    source="job_description",
                    rule="description_onsite",
                    matched_text=match.group(0),
                )
        return explicit_arrangement(
            [WorkMode.REMOTE],
            source="legacy",
            rule="legacy_remote_true",
        )

    for pattern in ONSITE_PATTERNS:
        if match := pattern.search(description):
            return explicit_arrangement(
                [WorkMode.ONSITE],
                source="job_description",
                rule="description_onsite",
                matched_text=match.group(0),
            )

    if legacy_remote is not False:
        for pattern in REMOTE_PATTERNS:
            if match := pattern.search(description):
                return explicit_arrangement(
                    [WorkMode.REMOTE],
                    source="job_description",
                    rule="description_remote",
                    matched_text=match.group(0),
                )

    for mode, pattern, rule in location_patterns:
        if mode is not WorkMode.REMOTE or legacy_remote is False:
            continue
        if match := pattern.search(location):
            return explicit_arrangement(
                [mode], source="listing_location", rule=rule, matched_text=match.group(0)
            )

    # Keep the title in the signature so callers have one stable classifier
    # interface; deliberately do not infer arrangements from bare title words.
    _ = title
    return explicit_arrangement([WorkMode.UNKNOWN], source="inferred", rule="insufficient_evidence")


def display_work_mode(modes: Iterable[WorkMode]) -> str:
    normalized = frozenset(modes)
    if len(normalized) == 1:
        return next(iter(normalized)).value
    return "mixed" if normalized else WorkMode.UNKNOWN.value
