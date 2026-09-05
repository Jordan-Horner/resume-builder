import json

import httpx
import pytest

from resume_builder.updates import UpdateChecker


def release(revision="b" * 40, built_at="2026-09-05T12:00:00Z"):
    metadata = {"revision": revision, "built_at": built_at, "digest": "sha256:" + "c" * 64}
    return {"body": "<!-- resume-builder-update\n" + json.dumps(metadata) + "\n-->", "draft": False}


@pytest.fixture
def installed(monkeypatch):
    monkeypatch.setenv("RESUME_BUILDER_BUILD_REVISION", "a" * 40)
    monkeypatch.setenv("RESUME_BUILDER_BUILD_DATE", "2026-09-04T12:00:00Z")
    monkeypatch.setenv("RESUME_BUILDER_BUILD_CHANNEL", "main")
    monkeypatch.delenv("RESUME_BUILDER_UPDATE_TOKEN_FILE", raising=False)


@pytest.mark.parametrize(
    "revision,date,status",
    [
        ("b" * 40, "2026-09-05T12:00:00Z", "update_available"),
        ("a" * 40, "2026-09-04T12:00:00Z", "up_to_date"),
        ("b" * 40, "2026-09-03T12:00:00Z", "ahead"),
    ],
)
def test_compare_published_build(installed, revision, date, status):
    client = httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=release(revision, date)))
    )
    result = UpdateChecker(client=client).status()
    assert result["status"] == status
    assert result["last_success_at"]
    assert result["release_url"].startswith("https://github.com/Jordan-Horner/resume-builder/")


def test_cache_and_failed_refresh_do_not_claim_current(installed):
    responses = [httpx.Response(200, json=release("a" * 40)), httpx.Response(503)]
    clock = [0.0]
    client = httpx.Client(transport=httpx.MockTransport(lambda _: responses.pop(0)))
    checker = UpdateChecker(client=client, clock=lambda: clock[0])
    first = checker.status()
    assert checker.status() == first
    clock[0] = 3601
    failed = checker.status()
    assert failed["status"] == "unavailable"
    assert failed["last_success_at"] == first["last_success_at"]


@pytest.mark.parametrize(
    "payload", [{}, {"body": "not json"}, release("bad"), release(built_at="bad")]
)
def test_invalid_metadata_is_not_an_update(installed, payload):
    client = httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))
    )
    assert UpdateChecker(client=client).status()["status"] == "unavailable"


def test_local_build_does_not_contact_github(monkeypatch):
    monkeypatch.delenv("RESUME_BUILDER_BUILD_REVISION", raising=False)
    client = httpx.Client(transport=httpx.MockTransport(lambda _: pytest.fail("network request")))
    assert UpdateChecker(client=client).status()["status"] == "development"


def test_private_token_stays_server_side(installed, monkeypatch, tmp_path):
    secret = tmp_path / "token"
    secret.write_text("synthetic-private-token")
    monkeypatch.setenv("RESUME_BUILDER_UPDATE_TOKEN_FILE", str(secret))

    def respond(request):
        assert request.headers["Authorization"] == "Bearer synthetic-private-token"
        return httpx.Response(401)

    result = UpdateChecker(client=httpx.Client(transport=httpx.MockTransport(respond))).status()
    assert result["status"] == "unavailable"
    assert "synthetic-private-token" not in json.dumps(result)
