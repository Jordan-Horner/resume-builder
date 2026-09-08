from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from job_puller.config import AtsBoard, BoardRegistry, BoardRegistryProviders

SCRIPT = Path(__file__).parents[2] / "scripts" / "curate_employer_boards.py"
SPEC = importlib.util.spec_from_file_location("curate_employer_boards", SCRIPT)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


def test_normalized_company_removes_punctuation_and_legal_suffixes() -> None:
    assert module.normalized_company("Adobe Systems Incorporated") == "adobesystems"
    assert module.normalized_company("JPMorgan Chase & Co.") == "jpmorganchase"


def test_candidate_uses_canonical_company_and_source_tags() -> None:
    employers = {"nvidia": ("NVIDIA", {"fortune-500-2026", "linkedin-top-2026"})}
    candidate = module._candidate_from_job(
        {
            "company": "NVIDIA, Inc.",
            "url": "https://job-boards.greenhouse.io/nvidia/jobs/123",
        },
        employers,
    )

    assert candidate is not None
    assert candidate.provider == "greenhouse"
    assert candidate.company == "NVIDIA"
    assert candidate.tags == {"fortune-500-2026", "linkedin-top-2026"}
    assert candidate.board == AtsBoard(
        id="nvidia",
        name="NVIDIA",
        enabled=False,
        careers_url="https://job-boards.greenhouse.io/nvidia",
    )


def test_merge_curated_adds_tags_to_an_existing_board() -> None:
    current = BoardRegistry(
        providers=BoardRegistryProviders(
            greenhouse=[AtsBoard(id="nvidia", name="NVIDIA", tags=["existing"])]
        )
    )
    discovered = BoardRegistry(
        providers=BoardRegistryProviders(
            greenhouse=[
                AtsBoard(
                    id="nvidia",
                    name="NVIDIA",
                    tags=["fortune-500-2026", "recognized-employer"],
                )
            ]
        )
    )

    merged = module._merge_curated(current, discovered)

    assert merged.providers.greenhouse[0].tags == [
        "existing",
        "fortune-500-2026",
        "recognized-employer",
    ]
