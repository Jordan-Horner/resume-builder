"""Neutral, non-scanning job-search files for new and upgraded workspaces."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .atomic import atomic_write_text

SETUP_PATH = Path("job-search/setup.json")
PREFERENCES_PATH = Path("job-search/preferences.yml")
SEARCH_CONFIG_PATH = Path("job-search/config/search.yml")
PORTFOLIO_PATH = Path("build/job-search/cold-start-portfolio.json")
ACTIVATION_BACKUP_PATH = Path("build/job-search/search-before-discovery.yml")
ACTIVATION_RECORD_PATH = Path("build/job-search/discovery-activation.json")


def neutral_preferences() -> dict[str, Any]:
    """Return preference defaults that contain no candidate assumptions."""
    return {
        "schema_version": 1,
        "accepted_work_modes": [],
        "desired_title_terms": [],
        "interest_terms": [],
        "excluded_title_terms": [],
        "senior_title_terms": [],
        "accepted_senior_role_terms": [],
        "unwanted_title_terms": [],
        "excluded_companies": [],
        "job_dispositions": {},
        "accepted_location_terms": [],
        "excluded_location_terms": [],
        "include_unknown_locations": True,
        "minimum_salary": None,
        "preferred_salary": None,
        "salary_currency": None,
        "salary_period": None,
        "resume_globs": ["resumes/baselines/*.md", "resumes/tailored/*.md"],
        "screening_profile": {},
        "personalization": {
            "enabled": True,
            "mode": "shadow",
            "exploration_fraction": 0.15,
        },
    }


def inactive_search_config() -> dict[str, Any]:
    """Return a valid but inert collector configuration for a new workspace."""
    return {
        "schema_version": 1,
        "enabled": False,
        "use_bundled_boards": True,
        "database_path": "data/inventory.db",
        "raw_payload_retention_days": 30,
        "initial_lookback_days": 7,
        "checkpoint_overlap_hours": 6,
        "request_timeout_seconds": 30,
        "search": {
            "location": "United States",
            "accepted_work_modes": ["remote"],
            "families": [],
        },
        "providers": {},
    }


def enable_bundled_board_catalog(root: Path) -> None:
    """Explicitly opt an existing workspace into packaged public boards."""
    from job_puller.config import InventoryConfig

    path = root / SEARCH_CONFIG_PATH
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    raw["use_bundled_boards"] = True
    InventoryConfig.model_validate(raw)
    atomic_write_text(path, yaml.safe_dump(raw, sort_keys=False))


def scaffold_job_search(root: Path) -> list[str]:
    """Install missing neutral job-search files without replacing user configuration."""
    installed: list[str] = []
    files = {
        PREFERENCES_PATH: yaml.safe_dump(neutral_preferences(), sort_keys=False),
        SEARCH_CONFIG_PATH: yaml.safe_dump(inactive_search_config(), sort_keys=False),
    }
    for relative, content in files.items():
        destination = root / relative
        if not destination.exists():
            atomic_write_text(destination, content)
            installed.append(relative.as_posix())
    return installed
