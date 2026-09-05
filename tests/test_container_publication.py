import json
import runpy
import subprocess
from pathlib import Path

import pytest
import yaml


def test_publication_waits_for_checks_and_announces_only_after_push():
    workflow = yaml.load(Path(".github/workflows/ci.yml").read_text(), Loader=yaml.BaseLoader)
    publish = workflow["jobs"]["publish"]
    assert set(publish["needs"]) == {"secrets", "container", "test", "frontend"}
    assert "github.event_name == 'push'" in publish["if"]
    assert "refs/heads/main" in publish["if"]
    steps = publish["steps"]
    build = next(step for step in steps if step.get("id") == "image")
    assert build["with"]["push"] == "true"
    assert build["with"]["platforms"] == "linux/amd64,linux/arm64"
    assert "github.sha" in build["with"]["tags"]
    assert "publish_container_release.py" in steps[-1]["run"]
    assert steps[-1]["env"]["IMAGE_DIGEST"] == "${{ steps.image.outputs.digest }}"


def test_registry_deployment_preserves_volume_and_has_no_docker_control():
    document = yaml.safe_load(Path("compose.deploy.yaml").read_text())
    assert list(document["services"]) == ["resume-builder"]
    service = document["services"]["resume-builder"]
    assert "build" not in service
    assert service["image"].startswith("ghcr.io/jordan-horner/resume-builder:")
    assert service["command"] == ["serve"]
    assert service["environment"]["RESUME_BUILDER_WORKSPACE"] == "/workspace"
    assert service["ports"] == [
        "${RESUME_BUILDER_WEB_BIND:-127.0.0.1}:${RESUME_BUILDER_WEB_PORT:-8766}:8765"
    ]
    assert service["volumes"] == [
        "${RESUME_BUILDER_WORKSPACE_PATH:-resume-builder-workspace}:/workspace",
        "${RESUME_BUILDER_RUNTIME_PATH:-resume-builder-state}:/state",
    ]
    assert set(document["volumes"]) == {"workspace", "state"}
    assert "docker.sock" not in str(document)


def test_local_compose_is_one_container_with_shared_workspace_and_state():
    document = yaml.safe_load(Path("compose.yaml").read_text())
    assert list(document["services"]) == ["resume-builder"]
    service = document["services"]["resume-builder"]
    assert service["command"] == ["serve"]
    assert service["environment"]["RESUME_BUILDER_WORKSPACE"] == "/workspace"
    assert service["environment"]["RESUME_BUILDER_AUTOMATION_STATE"].startswith("/state/")
    assert service["environment"]["RESUME_BUILDER_AGENT_STATE"].startswith("/state/")
    assert service["volumes"] == [
        "${RESUME_BUILDER_WORKSPACE_PATH:?Set RESUME_BUILDER_WORKSPACE_PATH}:/workspace",
        "${RESUME_BUILDER_RUNTIME_PATH:?Set RESUME_BUILDER_RUNTIME_PATH}:/state",
    ]


def test_image_starts_the_portal_first_service_and_checks_its_health():
    dockerfile = Path("Dockerfile").read_text()
    assert 'ENTRYPOINT ["resume-builder-entrypoint"]' in dockerfile
    assert 'CMD ["serve"]' in dockerfile
    assert "/api/system/status" in dockerfile


def test_entrypoint_keeps_existing_roots_and_nests_fresh_read_only_parents():
    entrypoint = Path("docker/resume-builder-entrypoint.sh").read_text()
    assert 'workspace_parent=$(dirname "${workspace}")' in entrypoint
    assert 'if [ ! -w "${workspace_parent}" ]' in entrypoint
    assert 'workspace="${workspace%/}/workspace"' in entrypoint
    assert 'export RESUME_BUILDER_WORKSPACE="${workspace}"' in entrypoint


def test_version_api_is_read_only(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from resume_builder.web import create_app

    monkeypatch.delenv("RESUME_BUILDER_BUILD_REVISION", raising=False)
    client = TestClient(create_app(tmp_path))
    assert client.get("/api/system/version").json()["status"] == "development"
    assert client.post("/api/system/version").status_code == 405


@pytest.mark.parametrize("existing", [False, True])
def test_release_notice_contains_only_successful_image_identity(monkeypatch, existing):
    monkeypatch.setenv("GITHUB_REPOSITORY", "Jordan-Horner/resume-builder")
    monkeypatch.setenv("GITHUB_SHA", "a" * 40)
    monkeypatch.setenv("IMAGE_DIGEST", "sha256:" + "b" * 64)
    monkeypatch.setenv("BUILD_DATE", "2026-09-05T12:00:00Z")
    calls = []

    def run(args, **kwargs):
        calls.append((args, kwargs))
        if "git/matching-refs" in args[2]:
            result = [{"ref": "refs/tags/main-build"}] if existing else []
        elif args[2].endswith("releases?per_page=100"):
            result = [{"tag_name": "main-build", "id": 123}] if existing else []
        else:
            result = {}
        return subprocess.CompletedProcess(args, 0, json.dumps(result))

    monkeypatch.setattr(subprocess, "run", run)
    runpy.run_path("scripts/publish_container_release.py")["main"]()
    args, options = calls[-1]
    payload = json.loads(options["input"])
    assert payload["prerelease"] is True
    assert "sha256:" + "b" * 64 in payload["body"]
    assert "<!-- resume-builder-update" in payload["body"]
    assert ("PATCH" in args) == existing


def test_no_announcement_without_valid_image_digest(monkeypatch):
    monkeypatch.setenv("GITHUB_REPOSITORY", "Jordan-Horner/resume-builder")
    monkeypatch.setenv("GITHUB_SHA", "a" * 40)
    monkeypatch.setenv("IMAGE_DIGEST", "")
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: pytest.fail("must not publish"))
    with pytest.raises(ValueError):
        runpy.run_path("scripts/publish_container_release.py")["main"]()
