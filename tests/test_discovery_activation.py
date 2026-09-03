from pathlib import Path

import pytest
import yaml

from job_puller.config import InventoryConfig
from resume_builder.discovery_activation import (
    MANAGED_FAMILY_PREFIX,
    DiscoveryActivationRecord,
    activate_portfolio,
    edit_portfolio,
    preview_activation,
    rollback_activation,
    rollback_confirmation,
    save_portfolio,
)
from resume_builder.discovery_evidence import TitlePosture
from resume_builder.discovery_portfolio import ColdStartLane, ColdStartPortfolio, ColdStartQuery


def portfolio() -> ColdStartPortfolio:
    return ColdStartPortfolio(
        generated_at="2026-09-03T00:00:00+00:00",
        resume_hash="fictional-resume-hash",
        queries=[
            ColdStartQuery(
                query_id="historical-fictional",
                lane=ColdStartLane.HISTORICAL_TITLE,
                query="Production Services Engineer",
                source_ids=["fictional-resume.md"],
                evidence_role="Production Services Engineer",
                reason="Recent fictional role.",
            ),
            ColdStartQuery(
                query_id="capability-fictional",
                lane=ColdStartLane.CAPABILITY_COMBINATION,
                query="AWS Kubernetes",
                source_ids=["fictional-resume.md"],
                evidence_role="Production Services Engineer",
                evidence_terms=["AWS", "Kubernetes"],
                reason="Literal fictional capability combination.",
            ),
        ],
    )


def search_config() -> str:
    return """\
schema_version: 1
database_path: data/inventory.db
search:
  location: United States
  accepted_work_modes: [remote]
  families:
    - name: manually-configured
      enabled: true
      titles: [support engineer]
providers:
  linkedin:
    enabled: true
    request_delay_seconds: 7
  indeed:
    enabled: true
    request_delay_seconds: 5
"""


def test_edit_operations_are_explicit_and_validated() -> None:
    original = portfolio()
    disabled = edit_portfolio(original, operation="disable", query_id="capability-fictional")
    assert disabled.queries[1].enabled is False
    assert original.queries[1].enabled is True

    enabled = edit_portfolio(disabled, operation="enable", query_id="capability-fictional")
    assert enabled.queries[1].enabled is True

    added = edit_portfolio(
        enabled,
        operation="add",
        query="Incident Operations Engineer",
        lane=ColdStartLane.ADJACENT_TITLE,
    )
    assert added.queries[-1].source_ids == ["user-explicit"]
    assert added.queries[-1].posture == TitlePosture.ADJACENT

    removed = edit_portfolio(added, operation="remove", query_id=added.queries[-1].query_id)
    assert len(removed.queries) == len(original.queries)


def test_portfolio_rejects_duplicate_or_fully_disabled_queries() -> None:
    original = portfolio()
    with pytest.raises(ValueError, match="unique"):
        ColdStartPortfolio.model_validate(
            {
                **original.model_dump(mode="json"),
                "queries": [
                    original.queries[0].model_dump(mode="json"),
                    original.queries[0].model_dump(mode="json"),
                ],
            }
        )

    disabled = edit_portfolio(original, operation="disable", query_id="historical-fictional")
    with pytest.raises(ValueError, match="at least one enabled"):
        edit_portfolio(disabled, operation="disable", query_id="capability-fictional")


def test_activation_preview_changes_only_managed_families() -> None:
    preview = preview_activation(portfolio(), search_config())
    payload = yaml.safe_load(preview.rendered_config)
    before = yaml.safe_load(search_config())
    settings = InventoryConfig.model_validate(payload)

    assert settings.search.location == "United States"
    assert settings.providers.linkedin.request_delay_seconds == 7
    assert settings.providers.indeed.request_delay_seconds == 5
    assert settings.search.families[0].name == "manually-configured"
    capability = next(
        item for item in settings.search.families if item.name.endswith("capability-fictional")
    )
    assert capability.provider_query == "AWS Kubernetes"
    assert capability.commercial_admission == "query_result"
    assert capability.commercial_only is True
    assert all(name.startswith(MANAGED_FAMILY_PREFIX) for name in preview.added_families)
    assert payload["providers"] == before["providers"]
    assert payload["search"]["location"] == before["search"]["location"]
    assert payload["search"]["accepted_work_modes"] == before["search"]["accepted_work_modes"]


def test_activation_refuses_to_duplicate_a_manual_search() -> None:
    duplicate = portfolio().model_copy(deep=True)
    duplicate.queries[0].query = "support engineer"

    with pytest.raises(ValueError, match="duplicate manual"):
        preview_activation(duplicate, search_config())


def test_activation_requires_exact_hash_and_rolls_back_safely(tmp_path: Path) -> None:
    portfolio_path = tmp_path / "portfolio.json"
    config_path = tmp_path / "search.yml"
    backup_path = tmp_path / "backup.yml"
    record_path = tmp_path / "activation.json"
    save_portfolio(portfolio_path, portfolio())
    config_path.write_text(search_config(), encoding="utf-8")
    preview = preview_activation(portfolio(), search_config())

    with pytest.raises(ValueError, match="confirmation hash"):
        activate_portfolio(portfolio_path, config_path, backup_path, record_path, "wrong-hash")
    assert not backup_path.exists()
    assert config_path.read_text(encoding="utf-8") == search_config()

    record = activate_portfolio(
        portfolio_path,
        config_path,
        backup_path,
        record_path,
        preview.confirmation_hash,
    )
    assert (
        DiscoveryActivationRecord.model_validate_json(record_path.read_text(encoding="utf-8"))
        == record
    )
    assert config_path.read_text(encoding="utf-8") == preview.rendered_config

    config_path.write_text(preview.rendered_config + "# changed later\n", encoding="utf-8")
    with pytest.raises(ValueError, match="changed after activation"):
        rollback_activation(record_path, rollback_confirmation(record))

    config_path.write_text(preview.rendered_config, encoding="utf-8")
    rollback_activation(record_path, rollback_confirmation(record))
    assert config_path.read_text(encoding="utf-8") == search_config()
