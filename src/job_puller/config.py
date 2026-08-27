from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SearchFamily(StrictModel):
    name: str
    terms: list[str] = Field(min_length=1)


class SearchSettings(StrictModel):
    location: str = "United States"
    remote_only: bool = True
    families: list[SearchFamily] = Field(min_length=1)


class CommercialProvider(StrictModel):
    enabled: bool = True
    results_wanted: int = Field(default=50, ge=1, le=1000)
    fetch_descriptions: bool = True


class AtsBoard(StrictModel):
    id: str
    name: str
    api_url: str | None = None
    careers_url: str | None = None
    extra: dict = Field(default_factory=dict)


class AtsProvider(StrictModel):
    enabled: bool = True
    boards: list[AtsBoard] = Field(default_factory=list)


class Providers(StrictModel):
    linkedin: CommercialProvider = Field(default_factory=CommercialProvider)
    indeed: CommercialProvider = Field(default_factory=CommercialProvider)
    greenhouse: AtsProvider = Field(default_factory=AtsProvider)
    lever: AtsProvider = Field(default_factory=AtsProvider)
    ashby: AtsProvider = Field(default_factory=AtsProvider)
    smartrecruiters: AtsProvider = Field(default_factory=AtsProvider)
    workday: AtsProvider = Field(default_factory=AtsProvider)


class InventoryConfig(StrictModel):
    schema_version: Literal[1] = 1
    database_path: str = "data/inventory.db"
    raw_payload_retention_days: int = Field(default=30, ge=1)
    initial_lookback_days: int = Field(default=7, ge=1, le=90)
    checkpoint_overlap_hours: int = Field(default=6, ge=0, le=48)
    request_timeout_seconds: float = Field(default=30, ge=5, le=180)
    search: SearchSettings
    providers: Providers = Field(default_factory=Providers)

    @model_validator(mode="after")
    def require_provider(self) -> InventoryConfig:
        if not any(getattr(self.providers, name).enabled for name in type(self.providers).model_fields):
            raise ValueError("at least one provider must be enabled")
        return self


def load_config(path: Path) -> InventoryConfig:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"configuration file not found: {path}") from exc
    except yaml.YAMLError as exc:
        raise ValueError(f"invalid YAML in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"configuration root must be a mapping: {path}")
    try:
        return InventoryConfig.model_validate(data)
    except ValidationError as exc:
        raise ValueError(str(exc)) from exc


def resolve_database_path(config_path: Path, configured: str) -> Path:
    path = Path(configured).expanduser()
    if path.is_absolute():
        return path
    project_root = config_path.resolve().parent.parent
    return project_root / path
