"""Bounded retrieval of canonical career evidence for quick job screens."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from collections.abc import Sequence
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from .layout import VaultLayout
from .validation import parse_frontmatter

if TYPE_CHECKING:
    from .posting_interpretation import PostingCriterion, PostingInterpretation

MAX_EVIDENCE_CARDS = 20
MAX_EVIDENCE_CHARACTERS = 6_000
MAX_EXCERPT_CHARACTERS = 350
MAX_CRITERION_EVIDENCE_CARDS = 12
MAX_FACTS_PER_CRITERION = 3

_TOKEN = re.compile(r"[a-z0-9+#.]{3,}", re.IGNORECASE)
_EMAIL = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
_PHONE = re.compile(r"(?<!\d)(?:\+?1[ .-]?)?(?:\(?\d{3}\)?[ .-]?)\d{3}[ .-]?\d{4}(?!\d)")
_URL = re.compile(r"\b(?:https?://|www\.)\S+", re.IGNORECASE)
_MARKDOWN_HEADING = re.compile(r"^#+\s+.*$", re.MULTILINE)
_HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
_YEAR = re.compile(r"\b(?:19|20)\d{2}\b")
_CAREER_STAGE = re.compile(
    r"\b(?:campus hire|new grad(?:uate)?|recent graduate|currently pursuing|"
    r"entry[ -]level|intern(?:ship)?|\d+\s*(?:[-\u2013\u2014]|to)\s*\d+\s+years?)\b",
    re.IGNORECASE,
)

_STOP_WORDS = {
    "about",
    "also",
    "and",
    "are",
    "company",
    "from",
    "have",
    "into",
    "job",
    "our",
    "role",
    "that",
    "the",
    "their",
    "this",
    "through",
    "using",
    "with",
    "will",
    "work",
    "you",
    "your",
}

_CRITERION_STOP_WORDS = _STOP_WORDS | {
    "ability",
    "candidate",
    "demonstrated",
    "experience",
    "including",
    "knowledge",
    "preferred",
    "proficiency",
    "required",
    "responsibilities",
    "skills",
    "strong",
    "years",
}
_WEAK_SINGLE_TERM_ANCHORS = {
    "cloud",
    "customer",
    "development",
    "engineering",
    "management",
    "operations",
    "platform",
    "production",
    "services",
    "software",
    "support",
    "systems",
    "technical",
}

_ADJACENT_GENERIC_TERMS = _WEAK_SINGLE_TERM_ANCHORS | {
    "developer",
    "engineer",
    "experience",
    "lead",
    "principal",
    "senior",
    "staff",
    "team",
    "years",
}

_CATEGORY_LIMITS = {
    "employment": 10,
    "projects": 4,
    "skills": 4,
    "education": 2,
    "certifications": 2,
}

EvidenceCategory = Literal["employment", "projects", "skills", "education", "certifications"]

EvidenceId = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]
EvidenceType = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)
]
EvidenceTitle = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)
]


class EvidenceStrength(StrEnum):
    DEMONSTRATED = "demonstrated"
    SUPPORTING = "supporting"
    CREDENTIAL = "credential"


class EvidenceCoverage(StrEnum):
    GOOD = "good"
    PARTIAL = "partial"
    LOW = "low"


class EvidenceStrategy(StrEnum):
    POSTING_WIDE = "posting-wide"
    CRITERION_DRIVEN = "criterion-driven"


class CriterionEvidenceStatus(StrEnum):
    DEMONSTRATED_CANDIDATE = "demonstrated-candidate"
    SUPPORTING_CANDIDATE = "supporting-candidate"
    NO_CANDIDATE_EVIDENCE = "no-candidate-evidence"
    NOT_RESUME_EVALUABLE = "not-resume-evaluable"


class ScreeningEvidenceCard(BaseModel):
    """One private, canonical fact excerpt supplied to a screening model."""

    model_config = ConfigDict(extra="forbid")

    fact_id: EvidenceId
    category: EvidenceCategory
    fact_type: EvidenceType
    title: EvidenceTitle
    excerpt: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=400)]
    organization: (
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
        | None
    ) = None
    strength: EvidenceStrength
    sha256: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class CriterionEvidenceMatch(BaseModel):
    """Retrieval candidates for one validated posting criterion."""

    model_config = ConfigDict(extra="forbid")

    criterion_id: EvidenceId
    label: EvidenceTitle
    description: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=600)
    ]
    importance: Literal["required", "preferred"]
    requirement_type: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)
    ]
    status: CriterionEvidenceStatus
    fact_ids: list[EvidenceId] = Field(default_factory=list, max_length=MAX_FACTS_PER_CRITERION)


class ScreeningEvidenceSelection(BaseModel):
    """Bounded evidence selected locally from the canonical vault."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    evidence_revision: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
    coverage: EvidenceCoverage
    eligible_fact_count: int = Field(ge=0)
    candidate_characters: int = Field(ge=0, le=MAX_EVIDENCE_CHARACTERS)
    cards: list[ScreeningEvidenceCard] = Field(default_factory=list, max_length=MAX_EVIDENCE_CARDS)
    strategy: EvidenceStrategy = EvidenceStrategy.POSTING_WIDE
    criterion_matches: list[CriterionEvidenceMatch] = Field(default_factory=list, max_length=30)


class _IndexedFact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    card: ScreeningEvidenceCard
    searchable: str
    themes: list[str]
    latest_year: int


def adjacent_evidence_signal(
    job: object, cards: Sequence[ScreeningEvidenceCard]
) -> dict[str, object]:
    """Return a conservative local signal for screening an unfamiliar title."""
    if not isinstance(job, dict):
        return {"eligible": False, "matched_fact_count": 0, "matched_terms": []}
    posting_tokens = _tokens(
        "\n".join(str(job.get(key) or "") for key in ("title", "description", "description_text"))
    )
    matched_fact_ids: list[str] = []
    matched_terms: set[str] = set()
    for card in cards:
        if card.strength != EvidenceStrength.DEMONSTRATED:
            continue
        overlap = (
            posting_tokens & _tokens(f"{card.title}\n{card.excerpt}")
        ) - _ADJACENT_GENERIC_TERMS
        if not overlap:
            continue
        matched_fact_ids.append(str(card.fact_id))
        matched_terms.update(overlap)
    return {
        "eligible": len(matched_fact_ids) >= 2 and len(matched_terms) >= 2,
        "matched_fact_count": len(matched_fact_ids),
        "matched_terms": sorted(matched_terms)[:12],
    }


def _tokens(value: str) -> set[str]:
    return {
        token.casefold() for token in _TOKEN.findall(value) if token.casefold() not in _STOP_WORDS
    }


def _safe_text(body: str) -> str:
    text = _HTML_COMMENT.sub(" ", body)
    text = _MARKDOWN_HEADING.sub(" ", text)
    text = _EMAIL.sub("[email removed]", text)
    text = _PHONE.sub("[phone removed]", text)
    text = _URL.sub("[link removed]", text)
    return " ".join(text.split())


def _safe_excerpt(body: str) -> str:
    text = _safe_text(body)
    if len(text) <= MAX_EXCERPT_CHARACTERS:
        return text
    sentences = _SENTENCE_END.split(text)
    selected = ""
    for sentence in sentences:
        candidate = f"{selected} {sentence}".strip()
        if len(candidate) > MAX_EXCERPT_CHARACTERS - 1:
            break
        selected = candidate
    if selected:
        return selected
    return text[: MAX_EXCERPT_CHARACTERS - 1].rstrip() + "…"


def _strength(category: str, fact_type: str) -> EvidenceStrength:
    if category == "skills":
        return EvidenceStrength.SUPPORTING
    if category in {"education", "certifications"}:
        return EvidenceStrength.CREDENTIAL
    return EvidenceStrength.DEMONSTRATED


def _fact_paths(layout: VaultLayout) -> list[Path]:
    """Return real Markdown facts, excluding filesystem metadata sidecars."""
    return [
        path
        for path in sorted(layout.facts.rglob("*.md"))
        if not any(part.startswith("._") or part == ".DS_Store" for part in path.parts)
    ]


def _vault_fingerprint(layout: VaultLayout) -> str:
    records = []
    for path in _fact_paths(layout):
        stat = path.stat()
        records.append((layout.relative(path), stat.st_size, stat.st_mtime_ns))
    return hashlib.sha256(json.dumps(records, separators=(",", ":")).encode()).hexdigest()


@lru_cache(maxsize=8)
def _load_index(vault_root: str, fingerprint: str) -> tuple[_IndexedFact, ...]:
    del fingerprint  # It exists to invalidate the process-local parsed-fact cache.
    layout = VaultLayout.load(Path(vault_root))
    indexed: list[_IndexedFact] = []
    for path in _fact_paths(layout):
        metadata, body = parse_frontmatter(path)
        if metadata.get("status") != "confirmed":
            continue
        category = str(metadata.get("category") or "")
        if category not in _CATEGORY_LIMITS:
            continue
        fact_id = metadata.get("id")
        title = metadata.get("title")
        fact_type = metadata.get("type")
        if not all(
            isinstance(value, str) and value.strip() for value in (fact_id, title, fact_type)
        ):
            continue
        searchable_body = _safe_text(body)
        excerpt = _safe_excerpt(body)
        if not excerpt:
            continue
        raw_themes = metadata.get("themes", [])
        themes = (
            [str(item) for item in raw_themes if str(item).strip()]
            if isinstance(raw_themes, list)
            else []
        )
        organization = metadata.get("organization")
        rendered_organization = str(organization).strip() if organization else None
        sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
        card = ScreeningEvidenceCard(
            fact_id=str(fact_id),
            category=cast(EvidenceCategory, category),
            fact_type=str(fact_type),
            title=str(title),
            excerpt=excerpt,
            organization=rendered_organization,
            strength=_strength(category, str(fact_type)),
            sha256=sha256,
        )
        years = [int(value) for value in _YEAR.findall(f"{title} {body}")]
        indexed.append(
            _IndexedFact(
                card=card,
                searchable=" ".join((str(title), " ".join(themes), searchable_body)),
                themes=themes,
                latest_year=max(years, default=0),
            )
        )
    return tuple(indexed)


def _score(fact: _IndexedFact, title: str, description: str) -> int:
    title_tokens = _tokens(title)
    description_tokens = _tokens(description)
    fact_tokens = _tokens(fact.searchable)
    title_overlap = len(fact_tokens & title_tokens)
    description_overlap = len(fact_tokens & description_tokens)
    score = title_overlap * 12 + min(description_overlap, 12) * 2
    normalized_title = " ".join(title.casefold().split())
    fact_title = " ".join(fact.card.title.casefold().split())
    if normalized_title and (
        normalized_title in fact.searchable.casefold() or fact_title in normalized_title
    ):
        score += 18
    for theme in fact.themes:
        if theme.casefold().replace("-", " ") in f"{title}\n{description}".casefold():
            score += 6
    if score > 0 and fact.card.strength == EvidenceStrength.DEMONSTRATED:
        score += 3
    elif fact.card.strength == EvidenceStrength.CREDENTIAL and description_overlap == 0:
        score -= 4
    return score


def _criterion_tokens(criterion: PostingCriterion) -> set[str]:
    value = " ".join(
        (
            criterion.label,
            criterion.description,
            criterion.source_excerpt,
            *criterion.retrieval_terms,
        )
    )
    return {
        token.casefold()
        for token in _TOKEN.findall(value)
        if token.casefold() not in _CRITERION_STOP_WORDS
        and token.casefold() not in _WEAK_SINGLE_TERM_ANCHORS
    }


def _criterion_phrases(criterion: PostingCriterion) -> set[str]:
    phrases = {" ".join(value.casefold().split()) for value in criterion.retrieval_terms}
    label = " ".join(criterion.label.casefold().split())
    if label:
        phrases.add(label)
    return {phrase for phrase in phrases if phrase and phrase not in _CRITERION_STOP_WORDS}


def _contains_phrase(searchable: str, phrase: str) -> bool:
    return (
        re.search(
            rf"(?<![a-z0-9+#.]){re.escape(phrase)}(?![a-z0-9+#.])",
            searchable,
        )
        is not None
    )


def _criterion_score(
    fact: _IndexedFact,
    criterion: PostingCriterion,
    document_frequency: Counter[str],
    document_count: int,
) -> float:
    query_tokens = _criterion_tokens(criterion)
    fact_tokens = _tokens(fact.searchable)
    overlap = query_tokens & fact_tokens
    searchable = " ".join(fact.searchable.casefold().split())
    exact_phrases = {
        phrase for phrase in _criterion_phrases(criterion) if _contains_phrase(searchable, phrase)
    }
    strong_exact_phrases = {
        phrase
        for phrase in exact_phrases
        if " " in phrase or phrase not in _WEAK_SINGLE_TERM_ANCHORS
    }
    if not query_tokens and not strong_exact_phrases:
        return 0
    # A model-supplied retrieval term is source-anchored during interpretation validation.
    # One exact term can therefore qualify a fact; otherwise require two distinct anchors.
    if not strong_exact_phrases and len(overlap) < 2:
        return 0
    rarity = sum(
        1 + math.log((document_count + 1) / (document_frequency[token] + 1)) for token in overlap
    )
    title_overlap = len(overlap & _tokens(fact.card.title))
    score = rarity * 4 + title_overlap * 8 + len(strong_exact_phrases) * 18
    if fact.card.strength == EvidenceStrength.DEMONSTRATED:
        score += 5
    elif fact.card.strength == EvidenceStrength.CREDENTIAL and not strong_exact_phrases:
        score -= 3
    return score


def _career_stage_role_facts(index: tuple[_IndexedFact, ...]) -> list[_IndexedFact]:
    """Return bounded confirmed work-history endpoints for career-stage comparisons."""
    roles = [
        item
        for item in index
        if item.card.category == "employment" and item.card.fact_type == "role" and item.latest_year
    ]
    if not roles:
        return []
    oldest = min(roles, key=lambda item: (item.latest_year, item.card.fact_id))
    newest = max(roles, key=lambda item: (item.latest_year, item.card.fact_id))
    return list({item.card.fact_id: item for item in (newest, oldest)}.values())


def _is_career_stage_criterion(criterion: PostingCriterion) -> bool:
    text = " ".join(
        (
            criterion.label,
            criterion.description,
            criterion.source_excerpt,
            *criterion.retrieval_terms,
        )
    )
    return _CAREER_STAGE.search(text) is not None


def _foundation(
    index: tuple[_IndexedFact, ...], ranked: list[tuple[int, _IndexedFact]]
) -> list[_IndexedFact]:
    selected: list[_IndexedFact] = []
    role_facts = [
        item
        for item in index
        if item.card.category == "employment" and item.card.fact_type == "role"
    ]
    if role_facts:
        selected.append(max(role_facts, key=lambda item: (item.latest_year, item.card.fact_id)))
    demonstrated = [
        item
        for score, item in ranked
        if score > 0 and item.card.strength == EvidenceStrength.DEMONSTRATED
    ]
    if demonstrated:
        selected.append(demonstrated[0])
    skill_candidates = [
        item for score, item in ranked if score > 0 and item.card.category == "skills"
    ]
    selected.extend(skill_candidates[:2])
    return list({item.card.fact_id: item for item in selected}.values())


def _selection_revision(cards: list[ScreeningEvidenceCard]) -> str:
    content = [(card.fact_id, card.sha256) for card in cards]
    return hashlib.sha256(json.dumps(content, separators=(",", ":")).encode()).hexdigest()


def select_screening_evidence(
    vault_root: Path, job: dict[str, object]
) -> ScreeningEvidenceSelection:
    """Select a private, diverse, high-recall set of confirmed career facts."""
    resolved = vault_root.expanduser().resolve()
    if not (resolved / "vault.json").is_file():
        return ScreeningEvidenceSelection(
            evidence_revision=hashlib.sha256(b"no-canonical-evidence").hexdigest(),
            coverage=EvidenceCoverage.LOW,
            eligible_fact_count=0,
            candidate_characters=0,
            cards=[],
        )
    layout = VaultLayout.load(resolved)
    index = _load_index(str(resolved), _vault_fingerprint(layout))
    title = str(job.get("title") or "")
    description = str(job.get("description_text") or job.get("description") or "")
    ranked = sorted(
        ((_score(item, title, description), item) for item in index),
        key=lambda pair: (-pair[0], -pair[1].latest_year, pair[1].card.fact_id),
    )

    chosen: list[ScreeningEvidenceCard] = []
    chosen_ids: set[str] = set()
    category_counts: Counter[str] = Counter()
    characters = 0

    def add(item: _IndexedFact) -> None:
        nonlocal characters
        card = item.card
        if card.fact_id in chosen_ids:
            return
        if category_counts[card.category] >= _CATEGORY_LIMITS[card.category]:
            return
        candidate_tokens = _tokens(card.excerpt)
        for prior in chosen:
            prior_tokens = _tokens(prior.excerpt)
            union = candidate_tokens | prior_tokens
            if union and len(candidate_tokens & prior_tokens) / len(union) >= 0.82:
                return
        size = len(card.title) + len(card.excerpt) + len(card.organization or "")
        if len(chosen) >= MAX_EVIDENCE_CARDS or characters + size > MAX_EVIDENCE_CHARACTERS:
            return
        chosen.append(card)
        chosen_ids.add(card.fact_id)
        category_counts[card.category] += 1
        characters += size

    for item in _foundation(index, ranked):
        add(item)
    for score, item in ranked:
        if score <= 0:
            continue
        add(item)

    score_by_id = {item.card.fact_id: score for score, item in ranked}
    chosen.sort(key=lambda card: (-score_by_id.get(card.fact_id, 0), card.fact_id))

    demonstrated_count = sum(card.strength == EvidenceStrength.DEMONSTRATED for card in chosen)
    if len(chosen) >= 8 and demonstrated_count >= 3:
        coverage = EvidenceCoverage.GOOD
    elif chosen:
        coverage = EvidenceCoverage.PARTIAL
    else:
        coverage = EvidenceCoverage.LOW
    return ScreeningEvidenceSelection(
        evidence_revision=_selection_revision(chosen),
        coverage=coverage,
        eligible_fact_count=len(index),
        candidate_characters=characters,
        cards=chosen,
    )


def select_criterion_screening_evidence(
    vault_root: Path,
    job: dict[str, object],
    interpretation: PostingInterpretation,
) -> ScreeningEvidenceSelection:
    """Retrieve a balanced evidence candidate set for validated posting criteria.

    Retrieval proposes canonical facts for semantic comparison; it does not claim that
    a fact satisfies a criterion. Non-resume criteria are retained as acknowledgements
    but never search the vault.
    """
    del job  # Criteria, rather than the broad posting, own retrieval in this phase.
    resolved = vault_root.expanduser().resolve()
    if not (resolved / "vault.json").is_file():
        index: tuple[_IndexedFact, ...] = ()
    else:
        layout = VaultLayout.load(resolved)
        index = _load_index(str(resolved), _vault_fingerprint(layout))

    document_frequency: Counter[str] = Counter()
    for item in index:
        document_frequency.update(_tokens(item.searchable))

    evaluable = [criterion for criterion in interpretation.criteria if criterion.resume_evaluable]
    priority = sorted(
        evaluable,
        key=lambda criterion: (
            criterion.importance != "required",
            criterion.requirement_type
            not in {
                "mandatory-role-defining",
                "mandatory-substitutable",
            },
            criterion.id,
        ),
    )
    rankings: dict[str, list[_IndexedFact]] = {}
    career_stage_facts = _career_stage_role_facts(index)
    for criterion in priority:
        ranked = sorted(
            (
                (
                    _criterion_score(item, criterion, document_frequency, max(1, len(index))),
                    item,
                )
                for item in index
            ),
            key=lambda pair: (-pair[0], -pair[1].latest_year, pair[1].card.fact_id),
        )
        lexical_matches = [item for score, item in ranked if score > 0]
        if _is_career_stage_criterion(criterion):
            stage_ids = {item.card.fact_id for item in career_stage_facts}
            lexical_matches = career_stage_facts + [
                item for item in lexical_matches if item.card.fact_id not in stage_ids
            ]
        rankings[criterion.id] = lexical_matches

    chosen: list[ScreeningEvidenceCard] = []
    chosen_ids: set[str] = set()
    category_counts: Counter[str] = Counter()
    characters = 0
    mapped_ids: dict[str, list[str]] = {criterion.id: [] for criterion in priority}

    def add(criterion_id: str, item: _IndexedFact) -> None:
        nonlocal characters
        card = item.card
        if card.fact_id in mapped_ids[criterion_id]:
            return
        if len(mapped_ids[criterion_id]) >= MAX_FACTS_PER_CRITERION:
            return
        if card.fact_id in chosen_ids:
            mapped_ids[criterion_id].append(card.fact_id)
            return
        if len(chosen) >= MAX_CRITERION_EVIDENCE_CARDS:
            return
        if category_counts[card.category] >= _CATEGORY_LIMITS[card.category]:
            return
        size = len(card.title) + len(card.excerpt) + len(card.organization or "")
        if characters + size > MAX_EVIDENCE_CHARACTERS:
            return
        chosen.append(card)
        chosen_ids.add(card.fact_id)
        mapped_ids[criterion_id].append(card.fact_id)
        category_counts[card.category] += 1
        characters += size

    # Round-robin selection prevents the first broad criterion from consuming the budget.
    for rank in range(MAX_FACTS_PER_CRITERION):
        for criterion in priority:
            candidates = rankings[criterion.id]
            if rank < len(candidates):
                add(criterion.id, candidates[rank])

    cards_by_id = {card.fact_id: card for card in chosen}
    matches: list[CriterionEvidenceMatch] = []
    for criterion in interpretation.criteria:
        fact_ids = mapped_ids.get(criterion.id, [])
        if not criterion.resume_evaluable:
            status = CriterionEvidenceStatus.NOT_RESUME_EVALUABLE
        elif any(
            cards_by_id[fact_id].strength == EvidenceStrength.DEMONSTRATED for fact_id in fact_ids
        ):
            status = CriterionEvidenceStatus.DEMONSTRATED_CANDIDATE
        elif fact_ids:
            status = CriterionEvidenceStatus.SUPPORTING_CANDIDATE
        else:
            status = CriterionEvidenceStatus.NO_CANDIDATE_EVIDENCE
        matches.append(
            CriterionEvidenceMatch(
                criterion_id=criterion.id,
                label=criterion.label,
                description=criterion.description,
                importance=cast(Literal["required", "preferred"], str(criterion.importance)),
                requirement_type=str(criterion.requirement_type),
                status=status,
                fact_ids=fact_ids,
            )
        )

    core_matches = [
        match
        for match in matches
        if match.importance == "required"
        and match.status != CriterionEvidenceStatus.NOT_RESUME_EVALUABLE
    ]
    if not core_matches:
        core_matches = [
            match
            for match in matches
            if match.status != CriterionEvidenceStatus.NOT_RESUME_EVALUABLE
        ]
    retrieved_core = [match for match in core_matches if match.fact_ids]
    if core_matches and len(retrieved_core) == len(core_matches):
        coverage = EvidenceCoverage.GOOD
    elif retrieved_core:
        coverage = EvidenceCoverage.PARTIAL
    else:
        coverage = EvidenceCoverage.LOW

    return ScreeningEvidenceSelection(
        evidence_revision=_selection_revision(chosen),
        coverage=coverage,
        eligible_fact_count=len(index),
        candidate_characters=characters,
        cards=chosen,
        strategy=EvidenceStrategy.CRITERION_DRIVEN,
        criterion_matches=matches,
    )
