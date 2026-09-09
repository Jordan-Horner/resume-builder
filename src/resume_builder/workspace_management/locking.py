"""Cross-process locking for a configured private workspace."""

from __future__ import annotations

import asyncio
import fcntl
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path


def _lock_path(workspace: Path, name: str) -> Path:
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
    return git_directory / name


@contextmanager
def _file_lock(path: Path, operation: int) -> Iterator[None]:
    with path.open("a+b") as stream:
        fcntl.flock(stream, operation)
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


class WorkspaceBusyError(RuntimeError):
    """Another operation holds the workspace writes lock."""


@contextmanager
def workspace_lock(workspace: Path, *, exclusive: bool, wait: bool = True) -> Iterator[None]:
    """Keep Git sync out of active work and serialize workspace mutations.

    With ``wait=False``, a contended exclusive acquisition fails fast with
    ``WorkspaceBusyError`` instead of blocking behind the current holder.
    """
    sync_gate = _lock_path(workspace, "resume-builder-workspace.lock")
    with _file_lock(sync_gate, fcntl.LOCK_SH):
        if exclusive:
            writes = _lock_path(workspace, "resume-builder-workspace-writes.lock")
            operation = fcntl.LOCK_EX if wait else fcntl.LOCK_EX | fcntl.LOCK_NB
            try:
                with _file_lock(writes, operation):
                    yield
            except BlockingIOError:
                raise WorkspaceBusyError(
                    "another workspace operation holds the write lock"
                ) from None
        else:
            yield


@contextmanager
def workspace_sync_lock(workspace: Path) -> Iterator[None]:
    """Wait for active work, then give Git exclusive access to the workspace."""
    path = _lock_path(workspace, "resume-builder-workspace.lock")
    with _file_lock(path, fcntl.LOCK_EX):
        yield


@asynccontextmanager
async def async_workspace_lock(
    workspace: Path, *, exclusive: bool, wait: bool = True
) -> AsyncIterator[None]:
    """Asynchronously acquire the same lock without blocking the event loop."""
    sync_stream = _lock_path(workspace, "resume-builder-workspace.lock").open("a+b")
    write_stream = None
    try:
        await asyncio.to_thread(fcntl.flock, sync_stream, fcntl.LOCK_SH)
        if exclusive:
            operation = fcntl.LOCK_EX if wait else fcntl.LOCK_EX | fcntl.LOCK_NB
            candidate = _lock_path(
                workspace, "resume-builder-workspace-writes.lock"
            ).open("a+b")
            try:
                await asyncio.to_thread(fcntl.flock, candidate, operation)
            except BlockingIOError:
                candidate.close()
                raise WorkspaceBusyError(
                    "another workspace operation holds the write lock"
                ) from None
            write_stream = candidate
        yield
    finally:
        if write_stream is not None:
            await asyncio.to_thread(fcntl.flock, write_stream, fcntl.LOCK_UN)
            write_stream.close()
        await asyncio.to_thread(fcntl.flock, sync_stream, fcntl.LOCK_UN)
        sync_stream.close()
