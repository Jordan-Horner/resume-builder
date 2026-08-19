#!/usr/bin/env python3
"""Compatibility wrapper for the packaged source importer."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "src"))

from resume_builder.source_import import main

if __name__ == "__main__":
    raise SystemExit(main())
