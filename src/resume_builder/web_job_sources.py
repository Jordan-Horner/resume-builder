"""Compatibility facade and worker entry point for portal job sources."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from .portal.job_sources import (
    CONFIG,
    LOCK,
    NAMES,
    STATE,
    _lock,
    run_worker,
    source_status,
    start_scan,
    toggle_source,
)

__all__ = [
    "CONFIG",
    "LOCK",
    "NAMES",
    "STATE",
    "_lock",
    "run_worker",
    "source_status",
    "start_scan",
    "toggle_source",
]

if __name__ == "__main__":
    try:
        run_worker(Path(sys.argv[1]), Path(sys.argv[2]))
    finally:
        os.close(int(sys.argv[3]))
