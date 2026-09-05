import copy
import runpy
import subprocess

import pytest


@pytest.fixture
def promotion(tmp_path, monkeypatch):
    module = runpy.run_path("scripts/promote_container_image.py")
    main = module["main"]
    image = "ghcr.io/jordan-horner/resume-builder"
    revision = "a" * 40
    for name, value in {
        "GITHUB_REPOSITORY": "Jordan-Horner/resume-builder",
        "GITHUB_SHA": revision,
        "GITHUB_RUN_ID": "123",
        "GITHUB_RUN_ATTEMPT": "2",
        "DIGEST_DIRECTORY": str(tmp_path / "digests"),
        "GITHUB_OUTPUT": str(tmp_path / "output"),
    }.items():
        monkeypatch.setenv(name, value)
    (tmp_path / "digests").mkdir()
    manifests = {}
    descriptors = []
    for arch, letter, runtime_letter, attestation_letter in (
        ("amd64", "b", "d", "f"),
        ("arm64", "c", "e", "1"),
    ):
        digest = "sha256:" + letter * 64
        runtime_digest = "sha256:" + runtime_letter * 64
        items = [
            {"digest": runtime_digest, "platform": {"os": "linux", "architecture": arch}},
            {
                "digest": "sha256:" + attestation_letter * 64,
                "platform": {"os": "unknown", "architecture": "unknown"},
                "annotations": {
                    "vnd.docker.reference.type": "attestation-manifest",
                    "vnd.docker.reference.digest": runtime_digest,
                },
            },
        ]
        manifests[f"{image}@{digest}"] = {"digest": digest, "manifests": items}
        descriptors.extend(copy.deepcopy(items))
        (tmp_path / "digests" / f"{arch}.txt").write_text(digest)
    combined = {"digest": "sha256:" + "2" * 64, "manifests": descriptors}
    manifests[f"{image}:candidate-123-2"] = combined
    manifests[f"{image}:main"] = combined
    manifests[f"{image}:sha-{revision}"] = combined
    calls = []
    state = {"current": revision, "fail_push": False}

    def command(*args):
        calls.append(args)
        if args[0] == "gh":
            return state["current"]
        if state["fail_push"] and f"{image}:main" in args:
            raise subprocess.CalledProcessError(1, args)
        return ""

    monkeypatch.setitem(main.__globals__, "command", command)
    monkeypatch.setitem(main.__globals__, "inspect", lambda reference: manifests[reference])
    return main, manifests, calls, state, tmp_path, image


def test_promotes_exact_verified_index_and_preserves_attestations(promotion):
    main, _, calls, _, root, image = promotion
    main()
    assert calls[-1][-1] == image + "@sha256:" + "2" * 64
    assert calls[-2][0] == "gh"  # Freshness check immediately precedes tag mutation.
    assert (root / "output").read_text() == "promoted=true\ndigest=sha256:" + "2" * 64 + "\n"


def test_superseded_commit_never_advances_release_tags(promotion):
    main, _, calls, state, root, image = promotion
    state["current"] = "9" * 40
    main()
    assert not any(f"{image}:main" in call for call in calls)
    assert not (root / "output").exists()


@pytest.mark.parametrize("damage", ["missing", "malformed", "wrong-platform", "lost-attestation"])
def test_invalid_candidate_cannot_be_promoted(promotion, damage):
    main, manifests, calls, _, root, image = promotion
    if damage == "missing":
        (root / "digests/arm64.txt").unlink()
    elif damage == "malformed":
        (root / "digests/amd64.txt").write_text("not-a-digest")
    elif damage == "wrong-platform":
        manifests[image + "@sha256:" + "b" * 64]["manifests"][0]["platform"]["architecture"] = (
            "arm64"
        )
    else:
        manifests[f"{image}:candidate-123-2"]["manifests"].pop()
    with pytest.raises(ValueError):
        main()
    assert not any(f"{image}:main" in call for call in calls)
    assert not (root / "output").exists()


def test_failed_push_cannot_authorize_announcement(promotion):
    main, _, _, state, root, _ = promotion
    state["fail_push"] = True
    with pytest.raises(subprocess.CalledProcessError):
        main()
    assert not (root / "output").exists()
