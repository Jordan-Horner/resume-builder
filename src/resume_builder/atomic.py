"""Atomic filesystem helpers for canonical vault data."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def atomic_write_bytes(path: Path, content: bytes) -> None:
    """Replace *path* atomically with *content* on the same filesystem."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def atomic_write_text(path: Path, content: str) -> None:
    """Replace a UTF-8 text file atomically."""
    atomic_write_bytes(path, content.encode("utf-8"))


def atomic_write_json(path: Path, content: Any) -> None:
    """Serialize JSON consistently and replace the destination atomically."""
    rendered = json.dumps(content, indent=2, ensure_ascii=False) + "\n"
    atomic_write_text(path, rendered)
