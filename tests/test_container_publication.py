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
    service = document["services"]["onboarding"]
    assert "build" not in service
    assert service["image"].startswith("ghcr.io/jordan-horner/resume-builder:")
    assert (
        document["volumes"]["onboarding-workspace"]["name"] == "resume-builder-onboarding-workspace"
    )
    assert "docker.sock" not in str(document)


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
