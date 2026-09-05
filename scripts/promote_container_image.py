"""Combine tested native images, preserve attestations, then advance release tags."""

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any


def command(*args: str) -> str:
    return subprocess.run(args, text=True, stdout=subprocess.PIPE, check=True).stdout.strip()


def inspect(reference: str) -> dict[str, Any]:
    return json.loads(
        command(
            "docker", "buildx", "imagetools", "inspect", reference, "--format", "{{json .Manifest}}"
        )
    )


def valid_digest(value: str) -> str:
    if not re.fullmatch(r"sha256:[a-f0-9]{64}", value):
        raise ValueError("Invalid candidate image digest")
    return value


def main() -> None:
    repository = os.environ["GITHUB_REPOSITORY"]
    revision = os.environ["GITHUB_SHA"]
    run_id = os.environ["GITHUB_RUN_ID"]
    attempt = os.environ["GITHUB_RUN_ATTEMPT"]
    if repository != "Jordan-Horner/resume-builder" or not re.fullmatch(r"[a-f0-9]{40}", revision):
        raise ValueError("Invalid publication repository or revision")
    if not run_id.isdecimal() or not attempt.isdecimal():
        raise ValueError("Invalid publication run identity")
    image = f"ghcr.io/{repository.lower()}"
    directory = Path(os.environ["DIGEST_DIRECTORY"])
    if {path.name for path in directory.iterdir()} != {"amd64.txt", "arm64.txt"}:
        raise ValueError("Both tested architecture digests are required")
    references = []
    expected: dict[str, dict[str, Any]] = {}
    for arch in ("amd64", "arm64"):
        digest = valid_digest((directory / f"{arch}.txt").read_text().strip())
        reference = f"{image}@{digest}"
        manifest = inspect(reference)
        if manifest["digest"] != digest:
            raise ValueError("Registry did not return the tested candidate")
        descriptors = manifest["manifests"]
        runtime = [item for item in descriptors if item.get("platform", {}).get("os") == "linux"]
        if len(runtime) != 1 or runtime[0]["platform"]["architecture"] != arch:
            raise ValueError(f"Candidate does not contain exactly the expected {arch} image")
        attestations = [
            item
            for item in descriptors
            if item.get("annotations", {}).get("vnd.docker.reference.type")
            == "attestation-manifest"
            and item["annotations"].get("vnd.docker.reference.digest") == runtime[0]["digest"]
        ]
        if not attestations or len(descriptors) != len(runtime) + len(attestations):
            raise ValueError("Candidate attestations are missing or contain unexpected manifests")
        for descriptor in descriptors:
            expected[valid_digest(descriptor["digest"])] = descriptor
        references.append(reference)

    candidate = f"{image}:candidate-{run_id}-{attempt}"
    command("docker", "buildx", "imagetools", "create", "--tag", candidate, *references)
    combined = inspect(candidate)
    actual = {item["digest"]: item for item in combined["manifests"]}
    if actual != expected:
        raise ValueError("Combined image changed tested manifests or attestations")
    digest = valid_digest(combined["digest"])

    # The publication job serializes writers. Check after assembly, immediately
    # before promotion; GitHub commits and registry tags cannot be updated atomically.
    current = command("gh", "api", f"repos/{repository}/commits/main", "--jq", ".sha")
    if current != revision:
        print("Skipping rolling release: this commit has been superseded.")
        return
    command(
        "docker",
        "buildx",
        "imagetools",
        "create",
        "--tag",
        f"{image}:sha-{revision}",
        "--tag",
        f"{image}:main",
        f"{image}@{digest}",
    )
    for tag in (f"sha-{revision}", "main"):
        if inspect(f"{image}:{tag}")["digest"] != digest:
            raise ValueError(f"Published {tag} does not match the verified image index")
    with Path(os.environ["GITHUB_OUTPUT"]).open("a") as output:
        output.write(f"promoted=true\ndigest={digest}\n")


if __name__ == "__main__":
    main()
