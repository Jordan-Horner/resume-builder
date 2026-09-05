"""Publish the rolling main-channel notice only after the image push succeeds."""

import json
import os
import re
import subprocess


def main() -> None:
    repository = os.environ["GITHUB_REPOSITORY"]
    revision = os.environ["GITHUB_SHA"]
    digest = os.environ["IMAGE_DIGEST"]
    if not re.fullmatch(r"[a-f0-9]{40}", revision) or not re.fullmatch(
        r"sha256:[a-f0-9]{64}", digest
    ):
        raise ValueError("invalid image publication metadata")
    metadata = {"revision": revision, "digest": digest, "built_at": os.environ["BUILD_DATE"]}
    body = (
        f"Latest tested main-channel Docker build: `{revision[:12]}`.\n\n"
        f"[Changes and source](https://github.com/{repository}/commit/{revision})\n\n"
        f"Image: `ghcr.io/{repository.lower()}@{digest}`\n\n"
        "Pull and recreate the container from your Docker host. Back up the workspace first. "
        "This is a rolling development channel, not a numbered stable release.\n\n"
        "<!-- resume-builder-update\n" + json.dumps(metadata) + "\n-->"
    )

    def api(path: str, payload: dict[str, object] | None = None, method: str = "POST") -> object:
        args = ["gh", "api", f"repos/{repository}/{path}"]
        if payload is not None:
            args.extend(["--method", method, "--input", "-"])
        result = subprocess.run(
            args,
            input=json.dumps(payload) if payload is not None else None,
            text=True,
            capture_output=True,
            check=True,
        )
        return json.loads(result.stdout)

    # A dedicated moving tag describes the same build as the moving image tag.
    refs = api("git/matching-refs/tags/main-build")
    exists = isinstance(refs, list) and any(ref["ref"] == "refs/tags/main-build" for ref in refs)
    if exists:
        api("git/refs/tags/main-build", {"sha": revision, "force": True}, "PATCH")
    else:
        api("git/refs", {"ref": "refs/tags/main-build", "sha": revision})
    releases = api("releases?per_page=100")
    existing = (
        next((item for item in releases if item["tag_name"] == "main-build"), None)
        if isinstance(releases, list)
        else None
    )
    payload = {
        "tag_name": "main-build",
        "name": f"Main build · {revision[:12]}",
        "body": body,
        "prerelease": True,
        "make_latest": "false",
    }
    if existing:
        api(f"releases/{existing['id']}", payload, "PATCH")
    else:
        api("releases", payload)


if __name__ == "__main__":
    main()
