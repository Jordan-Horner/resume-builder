"""Compatibility facade and entry point for the local portal."""

from .portal.app import create_app, main

__all__ = ["create_app", "main"]

if __name__ == "__main__":
    main()
