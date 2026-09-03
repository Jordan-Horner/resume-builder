"""Local resume evidence extraction for cold-start job discovery."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal, NamedTuple

from pydantic import BaseModel, ConfigDict, Field

from job_puller.normalize import normalized_key


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ResumeDocument(StrictModel):
    source_id: str
    content: str = Field(min_length=1)


class HistoricalTitleState(StrEnum):
    ACTIVE = "active"
    HISTORICAL_CONTEXT = "historical_context"


class TitlePosture(StrEnum):
    ADJACENT = "adjacent"
    EXPLORATORY = "exploratory"


class HistoricalTitleSeed(StrictModel):
    seed_id: str
    exact_title: str
    query_title: str
    normalized_title: str
    source_ids: list[str] = Field(min_length=1)
    most_recent_end_year: int | None = None
    state: HistoricalTitleState
    reason: str


class TitleSeedReport(StrictModel):
    schema_version: Literal[1] = 1
    corpus_hash: str
    generated_at: str
    historical_titles: list[HistoricalTitleSeed] = Field(min_length=1)


class EvidenceQueryKind(StrEnum):
    CAPABILITY_COMBINATION = "capability_combination"


class EvidenceQuerySeed(StrictModel):
    seed_id: str
    kind: EvidenceQueryKind
    query: str
    evidence_terms: list[str] = Field(min_length=2, max_length=2)
    source_id: str
    evidence_role: str
    support_count: int = Field(ge=1)


class ResumeQueryExpansion(StrictModel):
    schema_version: Literal[1] = 1
    corpus_hash: str
    capability_combinations: list[EvidenceQuerySeed] = Field(default_factory=list)


class _RoleEvidence(NamedTuple):
    title: str
    date_text: str
    text: str


_WORK_HEADING = re.compile(r"^##\s+(.+?)\s*(?:\||—)\s*(.+?)\s*(?:\||—)\s*(.+?)\s*$")
_HTML_COMMENT = re.compile(r"<!--.*?-->")
_YEAR = re.compile(r"\b(?:19|20)\d{2}\b")
_BOLD_TITLE = re.compile(r"^\*\*(.+?)\*\*$")
_SKILL_LINE = re.compile(r"^\*\*(.+?):\*\*\s*(.+)$")
_GENERIC_CAPABILITIES = {
    "cross-team coordination",
    "incident triage",
    "bug escalation",
    "customer issue reproduction",
    "log analysis",
    "runbooks",
}
_LOW_SIGNAL_CAPABILITIES = {"git", "jira", "english", "spanish"}


def _hash(value: object) -> str:
    rendered = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def _contains_phrase(text: str, phrase: str) -> bool:
    normalized = f" {normalized_key(text)} "
    candidate = f" {normalized_key(phrase)} "
    return bool(normalized_key(phrase)) and candidate in normalized


def _query_title(exact_title: str) -> str:
    title = re.split(r"\s+through\s+", exact_title, maxsplit=1, flags=re.IGNORECASE)[0]
    return re.split(r"\s*/\s*", title, maxsplit=1)[0].strip()


def _end_year(date_text: str) -> int | None:
    if re.search(r"\b(?:present|current)\b", date_text, flags=re.IGNORECASE):
        return datetime.now(UTC).year
    years = [int(value) for value in _YEAR.findall(date_text)]
    return max(years) if years else None


def _resume_sections(document: ResumeDocument) -> tuple[list[_RoleEvidence], str]:
    """Return role-scoped evidence plus global skills from one Markdown resume."""
    roles: list[_RoleEvidence] = []
    section = ""
    current_title = ""
    current_date = ""
    current_lines: list[str] = []
    awaiting_date = False

    def flush() -> None:
        nonlocal current_title, current_date, current_lines, awaiting_date
        if current_title:
            roles.append(_RoleEvidence(current_title, current_date, "\n".join(current_lines)))
        current_title = ""
        current_date = ""
        current_lines = []
        awaiting_date = False

    skill_lines: list[str] = []
    for raw_line in document.content.splitlines():
        line = _HTML_COMMENT.sub("", raw_line).strip()
        if line.startswith("# "):
            flush()
            section = normalized_key(line[2:])
            continue
        if line.startswith("## ") and not _WORK_HEADING.match(line):
            flush()
            section = normalized_key(line[3:])
            continue
        if section == "technical skills" and line and not line.startswith("#"):
            skill_lines.append(line)
            continue
        if section not in {"work experience", "experience"}:
            continue
        if line.startswith("## "):
            match = _WORK_HEADING.match(line)
            if match:
                flush()
                current_title = match.group(2).strip()
                current_date = match.group(3).strip()
            continue
        if line.startswith("### "):
            flush()
            continue
        bold = _BOLD_TITLE.match(line)
        if bold:
            flush()
            current_title = bold.group(1).strip()
            awaiting_date = True
            continue
        if awaiting_date and line:
            current_date = line
            awaiting_date = False
            continue
        if current_title and line.startswith("-"):
            current_lines.append(line)
    flush()
    return roles, "\n".join(skill_lines)


def _structured_skills(document: ResumeDocument) -> list[tuple[str, str]]:
    section = ""
    skills: list[tuple[str, str]] = []
    for raw_line in document.content.splitlines():
        line = _HTML_COMMENT.sub("", raw_line).strip()
        if line.startswith("# "):
            section = normalized_key(line[2:])
            continue
        if line.startswith("## "):
            section = normalized_key(line[3:])
            continue
        if section != "technical skills":
            continue
        match = _SKILL_LINE.match(line)
        if match:
            category = normalized_key(match.group(1))
            values = match.group(2).split(",")
        elif line.startswith("-"):
            category = "uncategorized"
            values = line.lstrip("- ").split(",")
        else:
            continue
        for value in values:
            term = value.strip().strip(".;")
            if term:
                skills.append((category, term))
    return skills


def extract_query_expansion(document: ResumeDocument) -> ResumeQueryExpansion:
    """Extract bounded literal capability combinations from one resume."""
    roles, _ = _resume_sections(document)
    skills = _structured_skills(document)
    resume_hash = hashlib.sha256(document.content.encode("utf-8")).hexdigest()
    if not roles or not skills:
        return ResumeQueryExpansion(corpus_hash=resume_hash)

    capability_terms = {
        normalized_key(term): term
        for category, term in skills
        if category != "languages"
        and normalized_key(term) not in _GENERIC_CAPABILITIES
        and normalized_key(term) not in _LOW_SIGNAL_CAPABILITIES
        and 1 <= len(normalized_key(term).split()) <= 3
    }
    pair_candidates: dict[tuple[str, str], tuple[int, int, str]] = {}
    for role in roles:
        role_year = _end_year(role.date_text) or 0
        for evidence_line in role.text.splitlines():
            present = sorted(
                key
                for key, term in capability_terms.items()
                if _contains_phrase(evidence_line, term)
            )
            for left_index, left in enumerate(present):
                for right in present[left_index + 1 :]:
                    pair = (left, right)
                    prior = pair_candidates.get(pair, (0, 0, role.title))
                    pair_candidates[pair] = (
                        prior[0] + 1,
                        max(prior[1], role_year),
                        role.title,
                    )

    combinations = [
        EvidenceQuerySeed(
            seed_id=f"capability-{_hash(pair)[:12]}",
            kind=EvidenceQueryKind.CAPABILITY_COMBINATION,
            query=f"{capability_terms[pair[0]]} {capability_terms[pair[1]]}",
            evidence_terms=[capability_terms[pair[0]], capability_terms[pair[1]]],
            source_id=document.source_id,
            evidence_role=role_title,
            support_count=support,
        )
        for pair, (support, _year, role_title) in sorted(
            pair_candidates.items(), key=lambda item: (-item[1][0], -item[1][1], item[0])
        )[:6]
    ]
    return ResumeQueryExpansion(corpus_hash=resume_hash, capability_combinations=combinations)


def extract_title_seed(documents: list[ResumeDocument]) -> TitleSeedReport:
    """Extract recent and historical employment titles without inferring preferences."""
    if len(documents) != 1:
        raise ValueError("title discovery requires exactly one resume document")
    document = documents[0]
    roles, _ = _resume_sections(document)
    observations: dict[str, dict[str, Any]] = {}
    for role in roles:
        query_title = _query_title(role.title)
        key = normalized_key(query_title)
        if not key:
            continue
        item = observations.setdefault(
            key,
            {
                "exact_title": role.title,
                "query_title": query_title,
                "source_ids": set(),
                "end_years": [],
            },
        )
        item["source_ids"].add(document.source_id)
        year = _end_year(role.date_text)
        if year is not None:
            item["end_years"].append(year)
    if not observations:
        raise ValueError("no employment titles were found in Work Experience headings")

    known_years = [year for item in observations.values() for year in item["end_years"]]
    latest_year = max(known_years, default=datetime.now(UTC).year)
    historical_titles = []
    for key, item in sorted(
        observations.items(), key=lambda pair: (-max(pair[1]["end_years"], default=0), pair[0])
    ):
        recent_year = max(item["end_years"], default=None)
        active = recent_year is not None and recent_year >= latest_year - 2
        historical_titles.append(
            HistoricalTitleSeed(
                seed_id=f"historical-{_hash(key)[:12]}",
                exact_title=item["exact_title"],
                query_title=item["query_title"],
                normalized_title=key,
                source_ids=sorted(item["source_ids"]),
                most_recent_end_year=recent_year,
                state=(
                    HistoricalTitleState.ACTIVE
                    if active
                    else HistoricalTitleState.HISTORICAL_CONTEXT
                ),
                reason=(
                    "Current or latest resume title; eligible for the bounded historical-title lane."
                    if active
                    else "Older resume title retained as history; no routine query unless later promoted."
                ),
            )
        )

    corpus_hash = hashlib.sha256(f"{document.source_id}\n{document.content}".encode()).hexdigest()
    return TitleSeedReport(
        corpus_hash=corpus_hash,
        generated_at=datetime.now(UTC).isoformat(),
        historical_titles=historical_titles,
    )
