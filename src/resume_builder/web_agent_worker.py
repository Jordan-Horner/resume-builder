"""Compatibility facade and process entry point for portal assistant work."""

from .portal.assistant_worker import (
    WEB_INSTRUCTIONS,
    _instructions_for_window,
    main,
    run_proposal,
    run_turn,
)

__all__ = [
    "WEB_INSTRUCTIONS",
    "_instructions_for_window",
    "main",
    "run_proposal",
    "run_turn",
]

if __name__ == "__main__":
    main()
