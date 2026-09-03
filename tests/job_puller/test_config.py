from pathlib import Path

import pytest

from job_puller.cli import _default_config_path
from job_puller.config import SearchFamily, load_config, resolve_database_path
from job_puller.work_modes import WorkMode


def test_example_config_is_valid():
    path = Path(__file__).parents[2] / "config" / "job-puller" / "search.example.yml"
    config = load_config(path)
    assert config.schema_version == 1
    assert config.providers.linkedin.enabled
    assert len(config.search.families) == 5


def test_relative_database_path_is_project_relative():
    path = Path(__file__).parents[1] / "config" / "search.example.yml"
    resolved = resolve_database_path(path, "data/inventory.db")
    assert resolved == Path(__file__).parents[1] / "data" / "inventory.db"


def test_external_board_registry_is_loaded(tmp_path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "boards.yml").write_text(
        """schema_version: 1
providers:
  greenhouse:
    - {id: acme, name: Acme, enabled: false, tags: [faang-plus]}
""",
        encoding="utf-8",
    )
    path = config_dir / "search.yml"
    path.write_text(
        """schema_version: 1
board_registry_path: config/boards.yml
search:
  families: [{name: reliability, titles: [SRE]}]
""",
        encoding="utf-8",
    )
    config = load_config(path)
    board = config.providers.greenhouse.boards[0]
    assert board.id == "acme"
    assert board.enabled is False
    assert board.tags == ["faang-plus"]


def test_unknown_config_key_surfaces(tmp_path):
    path = tmp_path / "search.yml"
    path.write_text(
        "schema_version: 1\nunknown: true\nsearch:\n  families: [{name: x, titles: [x]}]\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="unknown"):
        load_config(path)


def test_environment_can_select_default_config(monkeypatch):
    monkeypatch.setenv("JOB_PULLER_CONFIG", "/tmp/example-search.yml")
    assert _default_config_path() == "/tmp/example-search.yml"


def test_family_title_validation_surfaces_unsafe_quotes(tmp_path):
    path = tmp_path / "search.yml"
    path.write_text(
        "schema_version: 1\nsearch:\n  families:\n    - name: x\n      titles: ['bad\\\"title']\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="double quotes"):
        load_config(path)


def test_family_rejects_overlapping_query_titles_and_aliases(tmp_path):
    path = tmp_path / "search.yml"
    path.write_text(
        """schema_version: 1
search:
  families:
    - name: support
      titles: [support engineer]
      title_aliases: [Support Engineer]
""",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="must not overlap"):
        load_config(path)


def test_family_rejects_a_title_that_is_also_excluded(tmp_path):
    path = tmp_path / "search.yml"
    path.write_text(
        """schema_version: 1
search:
  families:
    - name: support
      titles: [support engineer]
      excluded_titles: [Support Engineer]
""",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="accepted and excluded"):
        load_config(path)


def test_unknown_family_result_limit_surfaces(tmp_path):
    path = tmp_path / "search.yml"
    path.write_text(
        """schema_version: 1
search:
  families: [{name: reliability, titles: [SRE]}]
providers:
  indeed:
    family_results_wanted: {missing: 200}
""",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="unknown families: missing"):
        load_config(path)


def test_remote_linkedin_requires_descriptions(tmp_path):
    path = tmp_path / "search.yml"
    path.write_text(
        """schema_version: 1
search:
  remote_only: true
  families: [{name: reliability, titles: [SRE]}]
providers:
  linkedin: {enabled: true, fetch_descriptions: false}
""",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="requires description fetching"):
        load_config(path)


def test_accepted_work_modes_replace_legacy_remote_only(tmp_path):
    path = tmp_path / "search.yml"
    path.write_text(
        """schema_version: 1
search:
  accepted_work_modes: [remote, hybrid]
  families: [{name: reliability, titles: [SRE]}]
""",
        encoding="utf-8",
    )
    config = load_config(path)
    assert config.search.accepted_work_modes == {WorkMode.REMOTE, WorkMode.HYBRID}
    assert config.search.remote_only is False


def test_work_mode_config_rejects_legacy_and_new_fields_together(tmp_path):
    path = tmp_path / "search.yml"
    path.write_text(
        """schema_version: 1
search:
  remote_only: true
  accepted_work_modes: [remote]
  families: [{name: reliability, titles: [SRE]}]
""",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="accepted_work_modes or legacy remote_only"):
        load_config(path)


def test_linkedin_scan_capacity_must_cover_largest_target(tmp_path):
    path = tmp_path / "search.yml"
    path.write_text(
        """schema_version: 1
search:
  families: [{name: reliability, titles: [SRE]}]
providers:
  linkedin: {results_wanted: 25, max_cards_scanned: 10}
""",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="max_cards_scanned"):
        load_config(path)


def test_query_result_admission_requires_an_explicit_commercial_query():
    with pytest.raises(ValueError, match="requires provider_query"):
        SearchFamily(
            name="invalid-discovery",
            titles=["support engineer"],
            commercial_admission="query_result",
        )

    family = SearchFamily(
        name="capability-discovery",
        titles=["production services engineer"],
        provider_query="AWS Kubernetes",
        commercial_admission="query_result",
        commercial_only=True,
    )

    assert family.provider_query == "AWS Kubernetes"
