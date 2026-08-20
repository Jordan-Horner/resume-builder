"""Architecture boundaries for the resume_builder package."""

from __future__ import annotations

import ast
from collections.abc import Mapping
from pathlib import Path

FACADE_LINE_BUDGETS = {
    "compilation": 250,
    "directions": 450,
    "feedback_memory": 250,
    "project_report": 650,
    "review_records": 300,
    "synthesis": 180,
}

FORBIDDEN_IMPORTS = {
    "compilation": {"feedback_acceptance", "feedback_memory", "feedback_recording"},
    "feedback_resolution": {
        "compilation",
        "feedback_acceptance",
        "feedback_memory",
        "feedback_recording",
        "review_records",
    },
    "review_schema": {
        "feedback_acceptance",
        "feedback_memory",
        "feedback_recording",
        "review_records",
    },
    "synthesis_audit": {"synthesis", "synthesis_loader"},
    "synthesis_loader": {"synthesis", "synthesis_audit"},
    "synthesis_models": {"synthesis", "synthesis_audit", "synthesis_loader"},
}


def _module_imports(path: Path, known: set[str], package_name: str) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[str] = set()

    def add(candidate: str) -> None:
        root = candidate.split(".", 1)[0]
        if root in known:
            imports.add(root)

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.level == 1:
                if node.module:
                    add(node.module)
                else:
                    for alias in node.names:
                        add(alias.name)
            elif node.level == 0 and node.module == package_name:
                for alias in node.names:
                    add(alias.name)
            elif node.level == 0 and node.module and node.module.startswith(f"{package_name}."):
                add(node.module.removeprefix(f"{package_name}."))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith(f"{package_name}."):
                    add(alias.name.removeprefix(f"{package_name}."))
    return imports


def _cycles(graph: dict[str, set[str]]) -> list[tuple[str, ...]]:
    found: set[tuple[str, ...]] = set()
    visiting: list[str] = []
    visited: set[str] = set()

    def visit(module: str) -> None:
        if module in visiting:
            start = visiting.index(module)
            cycle = [*visiting[start:], module]
            rotations = [
                tuple(cycle[index:-1] + cycle[:index] + [cycle[index]])
                for index in range(len(cycle) - 1)
            ]
            found.add(min(rotations))
            return
        if module in visited:
            return
        visiting.append(module)
        for dependency in sorted(graph[module]):
            visit(dependency)
        visiting.pop()
        visited.add(module)

    for module in sorted(graph):
        visit(module)
    return sorted(found)


def audit_architecture(
    package: Path,
    *,
    facade_line_budgets: Mapping[str, int] | None = None,
    forbidden_imports: Mapping[str, set[str]] | None = None,
) -> list[str]:
    """Return deterministic architecture violations for one package directory."""
    budgets = FACADE_LINE_BUDGETS if facade_line_budgets is None else facade_line_budgets
    forbidden_rules = FORBIDDEN_IMPORTS if forbidden_imports is None else forbidden_imports
    paths = {path.stem: path for path in package.glob("*.py")}
    known = set(paths)
    graph = {name: _module_imports(path, known, package.name) for name, path in paths.items()}
    errors: list[str] = []
    for module, budget in budgets.items():
        path = paths[module]
        lines = len(path.read_text(encoding="utf-8").splitlines())
        if lines > budget:
            errors.append(f"{module}.py has {lines} lines; facade budget is {budget}")
    for module, forbidden in forbidden_rules.items():
        unexpected = sorted(graph[module] & forbidden)
        if unexpected:
            errors.append(f"{module}.py imports forbidden orchestration layers: {unexpected}")
    for cycle in _cycles(graph):
        errors.append(f"package import cycle: {' -> '.join(cycle)}")
    return errors
