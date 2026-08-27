from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True, slots=True)
class CachedProviderDetail:
    response_body: str
    fetched_at: datetime
    expires_at: datetime


class ProviderDetailCache(Protocol):
    def get_provider_detail(
        self, provider: str, provider_job_id: str, parser_version: str
    ) -> CachedProviderDetail | None: ...

    def put_provider_detail(
        self,
        provider: str,
        provider_job_id: str,
        parser_version: str,
        response_body: str,
        fetched_at: datetime,
        expires_at: datetime,
    ) -> None: ...
