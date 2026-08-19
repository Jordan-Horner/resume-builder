from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from resume_builder import project_report
from resume_builder.workspace import (
    CommandResult,
    WorkspaceError,
    connect_existing_workspace,
    default_github_repository,
    discover_workspace,
    github_repository_from_remote,
    initialize_workspace,
    workspace_status,
)


def test_default_github_repository_uses_authenticated_owner(tmp_path: Path) -> None:
    def runner(arguments: tuple[str, ...] | list[str], cwd: Path) -> CommandResult:
        assert tuple(arguments) == ("gh", "api", "user", "--jq", ".login")
        assert cwd == tmp_path.resolve()
        return CommandResult(0, "example-owner\n")

    assert default_github_repository(runner=runner, cwd=tmp_path) == "example-owner/resume-vault"


def test_default_github_repository_requires_authenticated_owner(tmp_path: Path) -> None:
    def runner(arguments: tuple[str, ...] | list[str], cwd: Path) -> CommandResult:
        return CommandResult(1, stderr="not authenticated")

    assert default_github_repository(runner=runner, cwd=tmp_path) is None


@pytest.mark.parametrize(
    ("remote", "expected"),
    [
        ("https://github.com/example/resume-vault.git", "example/resume-vault"),
        ("git@github.com:example/resume-vault.git", "example/resume-vault"),
        ("ssh://git@github.com/example/resume-vault.git", "example/resume-vault"),
        ("https://gitlab.com/example/resume-vault.git", None),
    ],
)
def test_github_repository_from_remote(remote: str, expected: str | None) -> None:
    assert github_repository_from_remote(remote) == expected


def _configure_git(path: Path) -> None:
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=path, check=True)


def test_engine_repository_tracks_no_private_workspace_paths() -> None:
    root = Path(__file__).resolve().parents[1]
    tracked = set(
        subprocess.run(
            ["git", "ls-files"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.splitlines()
    )
    forbidden_prefixes = (
        "vault/",
        "resumes/",
        "targets/",
        "editorial/",
        "career/",
        "evals/cases/",
    )
    assert not sorted(path for path in tracked if path.startswith(forbidden_prefixes))
    assert sorted(path for path in tracked if path.startswith("directions/")) == [
        "directions/README.md"
    ]


def test_initialize_local_workspace_creates_independent_repository(tmp_path: Path) -> None:
    target = tmp_path / "workspace"
    subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, check=True)
    (tmp_path / ".gitignore").write_text("/workspace/\n", encoding="utf-8")
    _configure_git(tmp_path)

    result = initialize_workspace(
        target,
        git_name="Test User",
        git_email="test@example.invalid",
    )

    assert result.created is True
    assert result.committed is True
    assert (target / ".git").is_dir()
    assert (target / "vault" / "vault.json").is_file()
    assert (target / "vault" / "README.md").is_file()
    assert (target / "templates" / "resume-template.html").is_file()
    assert (target / ".resume-builder.json").is_file()
    assert discover_workspace(tmp_path) == target.resolve()
    outer_status = subprocess.run(
        ["git", "status", "--short", "--ignored"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    assert "!! workspace/" in outer_status.stdout
    assert (
        "workspace/"
        not in subprocess.run(
            ["git", "ls-files"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    )


def test_initialize_workspace_never_seeds_the_fictional_example(tmp_path: Path) -> None:
    target = tmp_path / "workspace"

    initialize_workspace(target)

    assert list((target / "vault" / "facts").rglob("*.md")) == []
    assert list((target / "vault" / "sources" / "normalized").rglob("*")) == []
    assert list((target / "resumes" / "baselines").glob("*.md")) == []
    assert list((target / "resumes" / "plans").glob("*.yaml")) == []
    assert list((target / "resumes" / "tailored").glob("*.md")) == []
    assert [path.name for path in (target / "directions").glob("*.md")] == ["README.md"]
    assert [path.name for path in (target / "targets").glob("*.md")] == ["README.md"]
    assert list((target / "editorial" / "rules").glob("*.json")) == []
    visible_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in target.rglob("*")
        if path.is_file() and ".git" not in path.parts
    )
    assert "Phoenix Wright" not in visible_text
    assert "Wright Anything Agency" not in visible_text


def test_fresh_workspace_report_is_getting_started_not_an_operational_failure(
    tmp_path: Path, run_main
) -> None:
    target = tmp_path / "workspace"
    initialize_workspace(target)

    assert run_main(project_report.main, "--vault-root", target / "vault", "--strict") == 0
    result = project_report.project_report(target / "vault", strict=True)
    assert result["status"] == "getting-started"
    assert result["onboarding"]["stage"] == "needs-sources"


def test_initialize_refuses_unignored_parent_repository(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, check=True)

    with pytest.raises(WorkspaceError, match="is not ignored"):
        initialize_workspace(tmp_path / "workspace")


def test_initialize_is_idempotent(tmp_path: Path) -> None:
    first = initialize_workspace(tmp_path / "workspace")
    second = initialize_workspace(tmp_path / "workspace")

    assert first.created is True
    assert second.created is False


def test_connect_existing_workspace_preserves_data_and_adds_configuration(
    tmp_path: Path,
) -> None:
    target = tmp_path / "existing"
    target.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=target, check=True)
    _configure_git(target)
    vault = target / "vault"
    vault.mkdir()
    (vault / "vault.json").write_text('{"schema_version": 2}\n', encoding="utf-8")
    marker = target / "keep-me.md"
    marker.write_text("private history\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=target, check=True)
    subprocess.run(["git", "commit", "-m", "Existing workspace"], cwd=target, check=True)

    result = connect_existing_workspace(target)

    assert result.created is False
    assert result.committed is True
    assert result.backup == "local"
    assert marker.read_text(encoding="utf-8") == "private history\n"
    assert (target / ".resume-builder.json").is_file()
    assert discover_workspace(target) == target.resolve()


def test_connect_existing_workspace_requires_independent_git_repository(
    tmp_path: Path,
) -> None:
    target = tmp_path / "existing"
    (target / "vault").mkdir(parents=True)
    (target / "vault" / "vault.json").write_text('{"schema_version": 2}\n', encoding="utf-8")

    with pytest.raises(WorkspaceError, match="independent Git repository"):
        connect_existing_workspace(target)


def _existing_workspace(tmp_path: Path) -> Path:
    target = tmp_path / "existing"
    target.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=target, check=True)
    _configure_git(target)
    (target / "vault").mkdir()
    (target / "vault" / "vault.json").write_text('{"schema_version": 2}\n', encoding="utf-8")
    return target


def test_connect_existing_workspace_rejects_public_github_origin(tmp_path: Path) -> None:
    target = _existing_workspace(tmp_path)

    def runner(arguments: tuple[str, ...] | list[str], cwd: Path) -> CommandResult:
        command = tuple(arguments)
        if command == ("git", "rev-parse", "--is-inside-work-tree"):
            return CommandResult(0, "true\n")
        if command == ("git", "remote", "get-url", "origin"):
            return CommandResult(0, "https://github.com/example/public-vault.git\n")
        if command[:3] == ("gh", "repo", "view"):
            return CommandResult(0, "PUBLIC\n")
        return CommandResult(1)

    with pytest.raises(WorkspaceError, match="origin is PUBLIC"):
        connect_existing_workspace(target, runner=runner)


def test_connect_existing_workspace_verifies_private_github_origin(tmp_path: Path) -> None:
    target = _existing_workspace(tmp_path)

    def runner(arguments: tuple[str, ...] | list[str], cwd: Path) -> CommandResult:
        command = tuple(arguments)
        if command == ("git", "rev-parse", "--is-inside-work-tree"):
            return CommandResult(0, "true\n")
        if command == ("git", "remote", "get-url", "origin"):
            return CommandResult(0, "git@github.com:example/resume-vault.git\n")
        if command[:3] == ("gh", "repo", "view"):
            return CommandResult(0, "PRIVATE\n")
        if command == ("git", "rev-parse", "--verify", "HEAD"):
            return CommandResult(0)
        return CommandResult(1)

    result = connect_existing_workspace(target, runner=runner)

    assert result.backup == "github"
    assert result.github_repository == "example/resume-vault"


def test_connect_existing_workspace_requires_opt_in_for_unverified_origin(
    tmp_path: Path,
) -> None:
    target = _existing_workspace(tmp_path)

    def runner(arguments: tuple[str, ...] | list[str], cwd: Path) -> CommandResult:
        command = tuple(arguments)
        if command == ("git", "rev-parse", "--is-inside-work-tree"):
            return CommandResult(0, "true\n")
        if command == ("git", "remote", "get-url", "origin"):
            return CommandResult(0, "ssh://git@example.invalid/private/resume-vault.git\n")
        if command == ("git", "rev-parse", "--verify", "HEAD"):
            return CommandResult(0)
        return CommandResult(1)

    with pytest.raises(WorkspaceError, match="privacy could not be verified"):
        connect_existing_workspace(target, runner=runner)

    result = connect_existing_workspace(target, allow_unverified_remote=True, runner=runner)
    assert result.backup == "unverified"


def test_workspace_status_reports_local_repository(tmp_path: Path) -> None:
    target = tmp_path / "workspace"
    initialize_workspace(target, git_name="Test User", git_email="test@example.invalid")

    result = workspace_status(target)

    assert result["workspace"] == str(target.resolve())
    assert result["independent_git"] is True
    assert result["backup"] == "local"
    assert result["privacy_verified"] is True


def test_local_configuration_warns_that_backup_is_local(tmp_path: Path) -> None:
    target = tmp_path / "workspace"

    initialize_workspace(target)

    config = json.loads((target / ".resume-builder.json").read_text(encoding="utf-8"))
    assert config["git"] == {"auto_checkpoint": False, "backup": "local"}


def test_github_repository_is_verified_private_before_push(tmp_path: Path) -> None:
    calls: list[tuple[str, ...]] = []

    def runner(arguments: tuple[str, ...] | list[str], cwd: Path) -> CommandResult:
        command = tuple(arguments)
        calls.append(command)
        if command[:3] == ("git", "config", "user.name"):
            return CommandResult(0, "Test User\n")
        if command[:3] == ("git", "config", "user.email"):
            return CommandResult(0, "test@example.invalid\n")
        if command[:3] == ("git", "rev-parse", "--show-toplevel"):
            return CommandResult(1)
        if command[:3] == ("git", "rev-parse", "--is-inside-work-tree"):
            return CommandResult(1)
        if command[:3] == ("gh", "repo", "view"):
            return CommandResult(0, "PRIVATE\n")
        return CommandResult(0, "")

    initialize_workspace(
        tmp_path / "workspace",
        backup="github",
        github_repository="example/private-vault",
        runner=runner,
    )

    verify_index = next(
        index for index, call in enumerate(calls) if call[:3] == ("gh", "repo", "view")
    )
    push_index = next(index for index, call in enumerate(calls) if call[:2] == ("git", "push"))
    assert verify_index < push_index
    assert any("--private" in call for call in calls if call[:3] == ("gh", "repo", "create"))


def test_github_visibility_failure_never_pushes(tmp_path: Path) -> None:
    calls: list[tuple[str, ...]] = []

    def runner(arguments: tuple[str, ...] | list[str], cwd: Path) -> CommandResult:
        command = tuple(arguments)
        calls.append(command)
        if command[:3] == ("git", "config", "user.name"):
            return CommandResult(0, "Test User\n")
        if command[:3] == ("git", "config", "user.email"):
            return CommandResult(0, "test@example.invalid\n")
        if command[:3] == ("git", "rev-parse", "--show-toplevel"):
            return CommandResult(1)
        if command[:3] == ("git", "rev-parse", "--is-inside-work-tree"):
            return CommandResult(1)
        if command[:3] == ("gh", "repo", "view"):
            return CommandResult(0, "PUBLIC\n")
        return CommandResult(0, "")

    with pytest.raises(WorkspaceError, match="no workspace data was pushed"):
        initialize_workspace(
            tmp_path / "workspace",
            backup="github",
            github_repository="example/private-vault",
            runner=runner,
        )

    assert not any(call[:2] == ("git", "push") for call in calls)
    config = json.loads(
        (tmp_path / "workspace" / ".resume-builder.json").read_text(encoding="utf-8")
    )
    assert config["git"] == {"auto_checkpoint": False, "backup": "local"}
