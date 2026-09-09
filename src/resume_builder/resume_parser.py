"""Compatibility facade for canonical resume Markdown parsing."""

from .resume_documents.markdown import (
    EVIDENCE,
    HEADING,
    SECTION_ALIASES,
    SKILL_LINE,
    STORY,
    compile_markdown,
    delimited,
    evidence_text,
    frontmatter,
    heading_blocks,
    list_blocks,
    sections,
    story_id,
)

__all__ = [
    "EVIDENCE",
    "HEADING",
    "SECTION_ALIASES",
    "SKILL_LINE",
    "STORY",
    "compile_markdown",
    "delimited",
    "evidence_text",
    "frontmatter",
    "heading_blocks",
    "list_blocks",
    "sections",
    "story_id",
]
