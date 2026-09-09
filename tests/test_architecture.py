from pathlib import Path

import pytest

from resume_builder.architecture import _module_imports, audit_architecture


def test_orchestration_architecture_has_no_cycles_or_facade_regressions() -> None:
    package = Path(__file__).resolve().parents[1] / "src" / "resume_builder"
    assert audit_architecture(package) == []


@pytest.mark.parametrize(
    "source",
    [
        "from .beta import value\n",
        "from . import beta\n",
        "from sample_package.beta import value\n",
        "from sample_package import beta\n",
        "import sample_package.beta\n",
    ],
)
def test_module_imports_tracks_static_internal_import_forms(
    tmp_path: Path,
    source: str,
) -> None:
    package = tmp_path / "sample_package"
    package.mkdir()
    module = package / "alpha.py"
    module.write_text(source, encoding="utf-8")

    assert _module_imports(module, {"alpha", "beta"}, package.name) == {"beta"}


def test_audit_rejects_cycle_across_mixed_import_forms(tmp_path: Path) -> None:
    package = tmp_path / "sample_package"
    package.mkdir()
    (package / "alpha.py").write_text("from . import beta\n", encoding="utf-8")
    (package / "beta.py").write_text("from sample_package.alpha import value\n", encoding="utf-8")

    assert audit_architecture(package, facade_line_budgets={}, forbidden_imports={}) == [
        "package import cycle: alpha -> beta -> alpha"
    ]


def test_audit_rejects_forbidden_absolute_import(tmp_path: Path) -> None:
    package = tmp_path / "sample_package"
    package.mkdir()
    (package / "alpha.py").write_text("import sample_package.beta\n", encoding="utf-8")
    (package / "beta.py").write_text("VALUE = 1\n", encoding="utf-8")

    assert audit_architecture(
        package,
        facade_line_budgets={},
        forbidden_imports={"alpha": {"beta"}},
    ) == ["alpha.py imports forbidden orchestration layers: ['beta']"]


def test_audit_rejects_facade_over_budget(tmp_path: Path) -> None:
    package = tmp_path / "sample_package"
    package.mkdir()
    (package / "alpha.py").write_text("VALUE = 1\nOTHER = 2\n", encoding="utf-8")

    assert audit_architecture(
        package,
        facade_line_budgets={"alpha": 1},
        forbidden_imports={},
    ) == ["alpha.py has 2 lines; facade budget is 1"]


def test_audit_accepts_clean_package(tmp_path: Path) -> None:
    package = tmp_path / "sample_package"
    package.mkdir()
    (package / "alpha.py").write_text("from .beta import VALUE\n", encoding="utf-8")
    (package / "beta.py").write_text("VALUE = 1\n", encoding="utf-8")

    assert (
        audit_architecture(
            package,
            facade_line_budgets={"alpha": 2},
            forbidden_imports={"alpha": set()},
        )
        == []
    )


def test_audit_rejects_cycle_between_nested_packages(tmp_path: Path) -> None:
    package = tmp_path / "sample_package"
    (package / "alpha").mkdir(parents=True)
    (package / "beta").mkdir()
    (package / "alpha" / "__init__.py").write_text("", encoding="utf-8")
    (package / "beta" / "__init__.py").write_text("", encoding="utf-8")
    (package / "alpha" / "service.py").write_text(
        "from ..beta.worker import run\n",
        encoding="utf-8",
    )
    (package / "beta" / "worker.py").write_text(
        "from sample_package.alpha.service import start\n",
        encoding="utf-8",
    )

    assert audit_architecture(
        package,
        facade_line_budgets={},
        forbidden_imports={},
    ) == ["package import cycle: alpha.service -> beta.worker -> alpha.service"]


def test_audit_rejects_forbidden_nested_package_dependency(tmp_path: Path) -> None:
    package = tmp_path / "sample_package"
    (package / "domain").mkdir(parents=True)
    (package / "portal").mkdir()
    (package / "domain" / "service.py").write_text(
        "from ..portal.app import create_app\n",
        encoding="utf-8",
    )
    (package / "portal" / "app.py").write_text("VALUE = 1\n", encoding="utf-8")

    assert audit_architecture(
        package,
        facade_line_budgets={},
        forbidden_imports={},
        forbidden_package_imports={"domain": {"portal"}},
    ) == ["domain.service imports forbidden packages: ['portal.app']"]
