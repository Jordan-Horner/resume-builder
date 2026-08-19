from __future__ import annotations

from collections.abc import Callable

import pytest


@pytest.fixture
def run_main() -> Callable[..., int]:
    def run(function: Callable[[list[str]], int], *arguments: object) -> int:
        return function([str(item) for item in arguments])

    return run
