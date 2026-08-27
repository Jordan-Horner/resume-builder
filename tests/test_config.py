from pathlib import Path

import pytest

from job_puller.cli import _default_config_path
from job_puller.config import load_config, resolve_database_path


def test_example_config_is_valid():
    path = Path(__file__).parents[1] / "config" / "search.example.yml"
    config = load_config(path)
    assert config.schema_version == 1
    assert config.providers.linkedin.enabled
    assert len(config.search.families) == 5


def test_relative_database_path_is_project_relative():
    path = Path(__file__).parents[1] / "config" / "search.example.yml"
    resolved = resolve_database_path(path, "data/inventory.db")
    assert resolved == Path(__file__).parents[1] / "data" / "inventory.db"


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
