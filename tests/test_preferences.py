from __future__ import annotations

from pathlib import Path

import pytest
import yaml

import resume_builder.preferences as preference_module
from resume_builder.job_setup_defaults import PREFERENCES_PATH
from resume_builder.preferences import PreferenceChangeRequest, apply, propose
from resume_builder.workspace import initialize_workspace


class _Inventory:
    def active_inventory(self) -> list[dict[str, object]]:
        return [
            {
                "id": "JOB-EXAMPLE",
                "title": "Reliability Engineer",
                "company": "Example Systems",
                "description_text": "Operate production services.",
                "description_quality": "complete",
                "work_modes": ["onsite"],
                "location": "New York",
                "salary_min": 120000,
            }
        ]


def _workspace(tmp_path: Path) -> Path:
    root = tmp_path / "workspace"
    initialize_workspace(root, git_name="Example User", git_email="example@example.invalid")
    database = root / "job-search" / "data" / "inventory.db"
    database.parent.mkdir(parents=True, exist_ok=True)
    database.touch()
    return root


def test_proposal_previews_local_effect_without_hiding_inventory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _workspace(tmp_path)
    monkeypatch.setattr(preference_module, "_database", lambda path: _Inventory())

    proposal = propose(
        root,
        PreferenceChangeRequest(set={"accepted_work_modes": ["remote"]}),
    )

    assert proposal.risk == "high"
    assert proposal.impact["inventory_jobs"] == 1
    assert proposal.impact["changed_jobs"] == 1
    assert proposal.impact["jobs_deleted"] == 0
    assert proposal.impact["network_calls"] == 0


def test_apply_is_hash_pinned_and_does_not_start_provider_scan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _workspace(tmp_path)
    monkeypatch.setattr(preference_module, "_database", lambda path: _Inventory())
    refreshed: list[bool] = []
    monkeypatch.setattr(
        preference_module,
        "_shortlist",
        lambda *args, **kwargs: refreshed.append(True) or 0,
    )
    proposal = propose(
        root,
        PreferenceChangeRequest(add={"interest_terms": ["incident management"]}),
    )

    with pytest.raises(ValueError, match="confirmation hash"):
        apply(root, "wrong")

    result = apply(root, proposal.confirmation_hash)
    saved = yaml.safe_load((root / PREFERENCES_PATH).read_text(encoding="utf-8"))

    assert saved["interest_terms"] == ["incident management"]
    assert result["provider_scan_started"] is False
    assert result["model_calls"] == 0
    assert refreshed == [True]


def test_apply_rejects_stale_proposal(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    proposal = propose(
        root,
        PreferenceChangeRequest(add={"interest_terms": ["incident management"]}),
    )
    path = root / PREFERENCES_PATH
    current = yaml.safe_load(path.read_text(encoding="utf-8"))
    current["interest_terms"] = ["cloud operations"]
    path.write_text(yaml.safe_dump(current, sort_keys=False), encoding="utf-8")

    with pytest.raises(ValueError, match="changed after the preview"):
        apply(root, proposal.confirmation_hash)


def test_proposal_cannot_modify_dispositions(tmp_path: Path) -> None:
    root = _workspace(tmp_path)

    with pytest.raises(ValueError, match="cannot change"):
        propose(
            root,
            PreferenceChangeRequest(set={"job_dispositions": {"JOB-1": "not_interested"}}),
        )
