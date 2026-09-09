from __future__ import annotations

from collections.abc import Callable

import pytest


@pytest.fixture
def run_main() -> Callable[..., int]:
    def run(function: Callable[[list[str]], int], *arguments: object) -> int:
        return function([str(item) for item in arguments])

    return run


@pytest.fixture(autouse=True)
def _strip_ambient_openrouter_env(monkeypatch: pytest.MonkeyPatch) -> None:
    # onboarding_status() reports OpenRouter configuration from the developer's
    # shell; tests must start from a deterministic unconfigured baseline. Tests
    # that need a key opt in with monkeypatch.setenv.
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("RESUME_BUILDER_OPENROUTER_KEY_FILE", raising=False)
