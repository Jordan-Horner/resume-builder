"""Canonical locations for generated artifacts tied to one resume source."""

from __future__ import annotations

from pathlib import Path


def default_resume_output_base(resume: Path) -> Path:
    """Return the extensionless base for one resume's internal artifacts."""
    return Path("build") / "resumes" / resume.stem / "resume"


def resume_output_base(project_root: Path, resume: Path) -> Path:
    """Return the absolute extensionless base for one resume's artifacts."""
    return project_root / default_resume_output_base(resume)
