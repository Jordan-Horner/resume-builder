"""Cross-process locking for a configured private workspace."""

from __future__ import annotations

import asyncio
import fcntl
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path


def _lock_path(workspace: Path) -> Path:
    root = workspace.expanduser().resolve()
    marker = root / ".git"
    if marker.is_dir():
        git_directory = marker
    elif marker.is_file():
        value = marker.read_text(encoding="utf-8").strip()
        if not value.startswith("gitdir: "):
            raise ValueError(f"invalid Git workspace marker: {marker}")
        git_directory = Path(value.removeprefix("gitdir: "))
        if not git_directory.is_absolute():
            git_directory = (root / git_directory).resolve()
    else:
        git_directory = root
    return git_directory / "resume-builder-workspace.lock"


@contextmanager
def workspace_lock(workspace: Path, *, exclusive: bool) -> Iterator[None]:
    """Serialize workspace mutations while allowing concurrent readers."""
    with _lock_path(workspace).open("a+b") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


@asynccontextmanager
async def async_workspace_lock(
    workspace: Path, *, exclusive: bool
) -> AsyncIterator[None]:
    """Asynchronously acquire the same lock without blocking the event loop."""
    stream = _lock_path(workspace).open("a+b")
    try:
        operation = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
        await asyncio.to_thread(fcntl.flock, stream, operation)
        yield
    finally:
        await asyncio.to_thread(fcntl.flock, stream, fcntl.LOCK_UN)
        stream.close()
