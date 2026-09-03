from __future__ import annotations

import json
from pathlib import Path

import pytest

from resume_builder.provider_comparison import compare_providers


class ComparisonDatabase:
    def provider_window_jobs(self, _started, _completed, _providers):
        return [
            {
                "provider": "linkedin",
                "job_id": "shared",
                "complete_description": 1,
                "has_posted_at": 1,
                "has_location": 1,
            },
            {
                "provider": "linkedin",
                "job_id": "linkedin-only",
                "complete_description": 0,
                "has_posted_at": 1,
                "has_location": 1,
            },
            {
                "provider": "indeed",
                "job_id": "shared",
                "complete_description": 1,
                "has_posted_at": 1,
                "has_location": 1,
            },
            {
                "provider": "indeed",
                "job_id": "indeed-only",
                "complete_description": 1,
                "has_posted_at": 0,
                "has_location": 1,
            },
        ]


def _manifest(path: Path, *, status: str = "complete") -> None:
    path.write_text(
        json.dumps(
            {
                "status": status,
                "started_at": "2026-09-03T12:00:00+00:00",
                "completed_at": "2026-09-03T13:00:00+00:00",
                "search_config_hash": "search-hash",
                "preference_hash": "preference-hash",
                "provider_runs": [
                    {"provider": "linkedin", "outcome": "healthy"},
                    {"provider": "indeed", "outcome": "capped"},
                ],
            }
        ),
        encoding="utf-8",
    )


def test_comparison_uses_canonical_overlap_and_useful_unique_delta(tmp_path: Path):
    manifest = tmp_path / "refresh.json"
    screens = tmp_path / "screens.json"
    _manifest(manifest)
    screens.write_text(
        json.dumps(
            {
                "jobs": [
                    {
                        "id": "linkedin-only",
                        "screening": {
                            "status": "complete",
                            "result": {"recommendation": "pursue_as_stretch"},
                        },
                    },
                    {
                        "id": "indeed-only",
                        "screening": {
                            "status": "complete",
                            "result": {"recommendation": "deprioritize"},
                        },
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    comparison = compare_providers(
        ComparisonDatabase(), manifest_path=manifest, screening_path=screens
    )

    assert comparison.payload["status"] == "valid_observation"
    assert comparison.payload["policy_frozen"] is True
    assert comparison.payload["shared_canonical_jobs"] == 1
    assert comparison.payload["providers"]["linkedin"]["useful_unique_jobs"] == 1
    assert comparison.payload["providers"]["indeed"]["useful_unique_jobs"] == 0


def test_comparison_refuses_an_in_progress_refresh(tmp_path: Path):
    manifest = tmp_path / "refresh.json"
    _manifest(manifest, status="in_progress")

    with pytest.raises(ValueError, match="still running"):
        compare_providers(ComparisonDatabase(), manifest_path=manifest)
