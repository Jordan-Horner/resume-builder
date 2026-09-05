"""Read-only, bounded checks of successfully published container builds."""

from __future__ import annotations

import json
import os
import re
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from typing import Any

import httpx

REPOSITORY = "Jordan-Horner/resume-builder"
RELEASE_URL = f"https://github.com/{REPOSITORY}/releases/tag/main-build"
API_URL = f"https://api.github.com/repos/{REPOSITORY}/releases/tags/main-build"


class UpdateChecker:
    """Cache checks across clients; never install software or access Docker."""

    def __init__(
        self, *, client: httpx.Client | None = None, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self.client = client
        self.clock = clock
        self.lock = threading.Lock()
        self.next_check = 0.0
        self.cached: dict[str, Any] | None = None
        self.last_success: str | None = None

    def _fetch(self) -> dict[str, Any]:
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
        token_file = os.environ.get("RESUME_BUILDER_UPDATE_TOKEN_FILE")
        if token_file:
            token = Path(token_file).read_text().strip()
            if token:
                headers["Authorization"] = f"Bearer {token}"
        # No user-supplied URL or redirect: credentials only go to GitHub.
        client = self.client or httpx.Client(timeout=5, follow_redirects=False)
        try:
            with client.stream("GET", API_URL, headers=headers, timeout=5) as response:
                response.raise_for_status()
                content = bytearray()
                for chunk in response.iter_bytes():
                    content.extend(chunk)
                    if len(content) > 128_000:
                        raise ValueError("release metadata too large")
                payload = json.loads(content)
            if not isinstance(payload, dict) or payload.get("draft"):
                raise ValueError("invalid release")
            match = re.search(
                r"<!-- resume-builder-update\n(.*?)\n-->", str(payload.get("body", "")), re.DOTALL
            )
            if not match:
                raise ValueError("missing publication metadata")
            metadata = json.loads(match[1])
            if not isinstance(metadata, dict) or not re.fullmatch(
                r"[0-9a-f]{40}", str(metadata.get("revision", ""))
            ):
                raise ValueError("invalid revision")
            if not re.fullmatch(r"sha256:[0-9a-f]{64}", str(metadata.get("digest", ""))):
                raise ValueError("invalid image digest")
            return metadata
        finally:
            if self.client is None:
                client.close()

    def status(self) -> dict[str, Any]:
        with self.lock:
            if self.cached is not None and self.clock() < self.next_check:
                return dict(self.cached)
            revision = os.environ.get("RESUME_BUILDER_BUILD_REVISION", "development")
            channel = os.environ.get("RESUME_BUILDER_BUILD_CHANNEL", "development")
            installed_date = os.environ.get("RESUME_BUILDER_BUILD_DATE", "")
            result: dict[str, Any] = {
                "version": version("resume-builder"),
                "revision": revision,
                "channel": channel,
                "built_at": installed_date,
                "status": "development",
                "latest_revision": None,
                "release_url": RELEASE_URL,
                "last_success_at": self.last_success,
                "message": "Local development build; update checks are disabled.",
            }
            ttl = 3600
            if re.fullmatch(r"[0-9a-f]{40}", revision) and channel == "main":
                try:
                    latest = self._fetch()
                    published = datetime.fromisoformat(latest["built_at"].replace("Z", "+00:00"))
                    installed = datetime.fromisoformat(installed_date.replace("Z", "+00:00"))
                    if published.tzinfo is None or installed.tzinfo is None:
                        raise ValueError("missing timezone")
                    status = (
                        "up_to_date"
                        if latest["revision"] == revision
                        else "update_available"
                        if published >= installed
                        else "ahead"
                    )
                    self.last_success = datetime.now(UTC).isoformat()
                    result.update(
                        status=status,
                        latest_revision=latest["revision"],
                        last_success_at=self.last_success,
                        message={
                            "up_to_date": "Up to date",
                            "update_available": "Update available",
                            "ahead": "This build is newer than the published channel.",
                        }[status],
                    )
                except (httpx.HTTPError, OSError, ValueError, KeyError, TypeError, AttributeError):
                    # No raw network exception: it may contain authentication data.
                    ttl = 300
                    result.update(
                        status="unavailable",
                        message="Unable to check for updates. Check network access and, for private repositories, the read-only update credential.",
                    )
            self.cached = result
            self.next_check = self.clock() + ttl
            return dict(result)
