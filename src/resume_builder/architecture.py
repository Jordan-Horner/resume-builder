"""Architecture boundaries for the resume_builder package."""

from __future__ import annotations

import ast
from collections.abc import Mapping
from pathlib import Path

FACADE_LINE_BUDGETS = {
    "agent": 20,
    "agent_config": 40,
    "agent_openrouter": 10,
    "agent_state": 10,
    "agent_telegram": 35,
    "agent_tools": 10,
    "applications": 90,
    "artifact_paths": 10,
    "artifact_status": 25,
    "ats": 10,
    "ats_readability": 20,
    "compilation": 250,
    "directions": 450,
    "direction_diagnostics": 20,
    "direction_schema": 60,
    "feedback_memory": 250,
    "evidence": 50,
    "evidence_questions": 30,
    "gmail_semantic": 30,
    "job_matching": 400,
    "job_report": 10,
    "jobs": 40,
    "layout": 30,
    "match_grading": 50,
    "migration": 60,
    "minting": 20,
    "pdf_rendering": 25,
    "plans": 40,
    "previewing": 35,
    "project_report": 60,
    "report_policy": 15,
    "rendering": 80,
    "resume_parser": 60,
    "review_records": 300,
    "schema_upgrade": 40,
    "source_import": 80,
    "synthesis": 180,
    "workspace": 40,
    "workspace_state": 50,
    "workspace_templates": 15,
    "validation": 70,
    "verification": 30,
    "web": 15,
    "web_agent": 10,
    "web_agent_resume": 30,
    "web_agent_state": 10,
    "web_agent_worker": 25,
    "web_career": 45,
    "web_filters": 10,
    "web_integrations": 20,
    "web_job_sources": 40,
    "web_schedule": 25,
    "web_service": 70,
    "web_system": 10,
}

FORBIDDEN_IMPORTS = {
    "compilation": {
        "feedback_memory",
        "reviews.feedback_acceptance",
        "reviews.feedback_recording",
    },
    "reviews.feedback_resolution": {
        "compilation",
        "reviews.feedback_acceptance",
        "feedback_memory",
        "reviews.feedback_recording",
        "review_records",
    },
    "reviews.schema": {
        "reviews.feedback_acceptance",
        "feedback_memory",
        "reviews.feedback_recording",
        "review_records",
    },
    "reviews.approval": {
        "reviews.feedback_acceptance",
        "feedback_memory",
        "reviews.feedback_recording",
        "review_records",
    },
    "planning.audit": {"synthesis", "planning.loader"},
    "planning.loader": {"synthesis", "planning.audit"},
    "planning.models": {"synthesis", "planning.audit", "planning.loader"},
    "planning.schema": {"synthesis", "planning.audit", "planning.loader"},
    "planning.summary": {"synthesis", "planning.audit", "planning.loader"},
}

FORBIDDEN_PACKAGE_IMPORTS: dict[str, set[str]] = {
    "application_tracking": {"automation", "opportunities", "portal"},
    "assistant": {
        "application_tracking",
        "document_export",
        "matching",
        "planning",
        "portal",
        "reviews",
        "role_profiles",
    },
    "document_export": {
        "application_tracking",
        "assistant",
        "automation",
        "matching",
        "opportunities",
        "planning",
        "portal",
        "reviews",
        "role_profiles",
    },
    "opportunities": {"assistant", "automation", "portal"},
    "planning": {"assistant", "automation", "opportunities", "portal", "reviews"},
    "matching": {"application_tracking", "assistant", "automation", "portal", "reviews"},
    "reviews": {"assistant", "automation", "opportunities", "portal"},
    "role_profiles": {
        "application_tracking",
        "assistant",
        "automation",
        "opportunities",
        "portal",
        "reviews",
    },
    "resume_documents": {
        "application_tracking",
        "assistant",
        "automation",
        "document_export",
        "matching",
        "opportunities",
        "planning",
        "portal",
        "reviews",
        "role_profiles",
    },
    "vault": {
        "application_tracking",
        "assistant",
        "automation",
        "document_export",
        "matching",
        "opportunities",
        "planning",
        "portal",
        "resume_documents",
        "reviews",
        "role_profiles",
    },
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


def _module_name(package: Path, path: Path) -> str:
    relative = path.relative_to(package).with_suffix("")
    parts = relative.parts
    if parts[-1] == "__init__":
        return ".".join(parts[:-1]) or "__init__"
    return ".".join(parts)


def _qualified_module_imports(
    path: Path,
    *,
    module: str,
    known: set[str],
    package_name: str,
) -> set[str]:
    """Return package-local imports for a possibly nested Python module."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[str] = set()
    current_package = module.rpartition(".")[0]
    if path.name == "__init__.py":
        current_package = "" if module == "__init__" else module

    def add(candidate: str) -> bool:
        normalized = candidate.removeprefix(f"{package_name}.")
        if normalized == package_name:
            normalized = "__init__"
        matches = [
            known_module
            for known_module in known
            if normalized == known_module or normalized.startswith(f"{known_module}.")
        ]
        if not matches:
            return False
        imports.add(max(matches, key=lambda value: value.count(".")))
        return True

    def relative_base(level: int, imported: str | None) -> str | None:
        parts = current_package.split(".") if current_package else []
        climb = level - 1
        if climb > len(parts):
            return None
        base = parts[: len(parts) - climb]
        if imported:
            base.extend(imported.split("."))
        suffix = ".".join(base)
        return f"{package_name}.{suffix}" if suffix else package_name

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.level:
                base = relative_base(node.level, node.module)
            elif node.module == package_name or (
                node.module and node.module.startswith(f"{package_name}.")
            ):
                base = node.module
            else:
                base = None
            if base is None:
                continue
            for alias in node.names:
                if alias.name != "*" and add(f"{base}.{alias.name}"):
                    continue
                add(base)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == package_name or alias.name.startswith(f"{package_name}."):
                    add(alias.name)
    imports.discard(module)
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
    forbidden_package_imports: Mapping[str, set[str]] | None = None,
) -> list[str]:
    """Return deterministic architecture violations for one package directory."""
    budgets = FACADE_LINE_BUDGETS if facade_line_budgets is None else facade_line_budgets
    forbidden_rules = FORBIDDEN_IMPORTS if forbidden_imports is None else forbidden_imports
    package_rules = (
        FORBIDDEN_PACKAGE_IMPORTS
        if forbidden_package_imports is None
        else forbidden_package_imports
    )
    paths = {_module_name(package, path): path for path in package.rglob("*.py")}
    known = set(paths)
    graph = {
        name: _qualified_module_imports(
            path,
            module=name,
            known=known,
            package_name=package.name,
        )
        for name, path in paths.items()
    }
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
    for source_package, forbidden_packages in package_rules.items():
        source_prefix = f"{source_package}."
        for module, dependencies in graph.items():
            if module != source_package and not module.startswith(source_prefix):
                continue
            unexpected = sorted(
                dependency
                for dependency in dependencies
                if any(
                    dependency == forbidden or dependency.startswith(f"{forbidden}.")
                    for forbidden in forbidden_packages
                )
            )
            if unexpected:
                errors.append(f"{module} imports forbidden packages: {unexpected}")
    for cycle in _cycles(graph):
        errors.append(f"package import cycle: {' -> '.join(cycle)}")
    return errors
