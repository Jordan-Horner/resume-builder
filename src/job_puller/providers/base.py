from __future__ import annotations

import threading
from datetime import datetime
from typing import Protocol

from job_puller.models import ProviderResult


class Provider(Protocol):
    name: str
    source_key: str

    def fetch(
        self, since: datetime, *, cancel: threading.Event | None = None
    ) -> ProviderResult: ...
