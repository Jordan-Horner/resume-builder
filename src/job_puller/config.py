from __future__ import annotations

import os
from importlib.resources import files
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from .work_modes import WorkMode


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SearchFamily(StrictModel):
    name: str
    enabled: bool = True
    titles: list[str] = Field(min_length=1)
    provider_query: str | None = None
    commercial_admission: Literal["title_match", "query_result"] = "title_match"
    commercial_only: bool = False
    title_aliases: list[str] = Field(default_factory=list)
    excluded_titles: list[str] = Field(default_factory=list)

    @field_validator("titles", "title_aliases", "excluded_titles")
    @classmethod
    def validate_titles(cls, titles: list[str]) -> list[str]:
        cleaned = [title.strip() for title in titles]
        if any(not title for title in cleaned):
            raise ValueError("job titles cannot be blank")
        if any('"' in title for title in cleaned):
            raise ValueError("job titles cannot contain double quotes")
        if len({title.casefold() for title in cleaned}) != len(cleaned):
            raise ValueError("job title rules must be unique within each list")
        return cleaned

    @field_validator("provider_query")
    @classmethod
    def validate_provider_query(cls, query: str | None) -> str | None:
        if query is None:
            return None
        cleaned = query.strip()
        if not cleaned:
            raise ValueError("provider query cannot be blank")
        if '"' in cleaned:
            raise ValueError("provider query cannot contain double quotes")
        return cleaned

    @model_validator(mode="after")
    def require_distinct_title_rules(self) -> SearchFamily:
        accepted = [*self.titles, *self.title_aliases]
        if len({title.casefold() for title in accepted}) != len(accepted):
            raise ValueError("titles and title_aliases must not overlap")
        if {title.casefold() for title in accepted} & {
            title.casefold() for title in self.excluded_titles
        }:
            raise ValueError("accepted and excluded title rules must not overlap")
        if self.commercial_admission == "query_result" and not self.provider_query:
            raise ValueError("query_result admission requires provider_query")
        if self.commercial_only and not self.provider_query:
            raise ValueError("commercial_only families require provider_query")
        return self

    @property
    def accepted_titles(self) -> list[str]:
        """Title phrases admitted locally after a provider search."""
        return [*self.titles, *self.title_aliases]


class SearchSettings(StrictModel):
    location: str = "United States"
    remote_only: bool = True
    accepted_work_modes: set[WorkMode] | None = None
    families: list[SearchFamily] = Field(default_factory=list)

    @model_validator(mode="after")
    def normalize_work_modes(self) -> SearchSettings:
        if (
            "accepted_work_modes" in self.model_fields_set
            and "remote_only" in self.model_fields_set
        ):
            raise ValueError("set accepted_work_modes or legacy remote_only, not both")
        if self.accepted_work_modes is None:
            self.accepted_work_modes = (
                {WorkMode.REMOTE}
                if self.remote_only
                else {WorkMode.REMOTE, WorkMode.HYBRID, WorkMode.ONSITE, WorkMode.UNKNOWN}
            )
        elif not self.accepted_work_modes:
            raise ValueError("accepted_work_modes cannot be empty")
        self.remote_only = self.accepted_work_modes == {WorkMode.REMOTE}
        return self


class CommercialProvider(StrictModel):
    enabled: bool = True
    results_wanted: int = Field(default=50, ge=1, le=1000)
    fetch_descriptions: bool = True
    request_delay_seconds: float = Field(default=0, ge=0, le=30)
    family_results_wanted: dict[str, int] = Field(default_factory=dict)

    @field_validator("family_results_wanted")
    @classmethod
    def validate_family_results_wanted(cls, limits: dict[str, int]) -> dict[str, int]:
        if any(limit < 1 or limit > 1000 for limit in limits.values()):
            raise ValueError("family result limits must be between 1 and 1000")
        return limits


class LinkedInProviderSettings(CommercialProvider):
    results_wanted: int = Field(default=10, ge=1, le=1000)
    request_delay_seconds: float = Field(default=3.2, ge=0, le=30)
    incremental_lookback_hours: int = Field(default=48, ge=1, le=168)
    max_cards_scanned: int = Field(default=50, ge=1, le=1000)
    detail_cache_hours: int = Field(default=24, ge=1, le=168)
    remote_policy: Literal["strict", "balanced", "source"] = "strict"

    @model_validator(mode="after")
    def require_scan_capacity(self) -> LinkedInProviderSettings:
        largest_target = max([self.results_wanted, *self.family_results_wanted.values()])
        if self.max_cards_scanned < largest_target:
            raise ValueError("LinkedIn max_cards_scanned must cover every configured result target")
        return self


class AtsBoard(StrictModel):
    id: str
    name: str
    enabled: bool = True
    tags: list[str] = Field(default_factory=list)
    api_url: str | None = None
    careers_url: str | None = None
    extra: dict = Field(default_factory=dict)

    @field_validator("id", "name")
    @classmethod
    def require_board_identity(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("ATS board id and name cannot be blank")
        return cleaned

    @field_validator("tags")
    @classmethod
    def normalize_tags(cls, tags: list[str]) -> list[str]:
        cleaned = [tag.strip().casefold() for tag in tags]
        if any(not tag for tag in cleaned):
            raise ValueError("ATS board tags cannot be blank")
        if len(set(cleaned)) != len(cleaned):
            raise ValueError("ATS board tags must be unique")
        return cleaned


class AtsProvider(StrictModel):
    enabled: bool = True
    boards: list[AtsBoard] = Field(default_factory=list)


class Providers(StrictModel):
    linkedin: LinkedInProviderSettings = Field(default_factory=LinkedInProviderSettings)
    indeed: CommercialProvider = Field(default_factory=CommercialProvider)
    jazzhr: AtsProvider = Field(default_factory=AtsProvider)
    rippling: AtsProvider = Field(default_factory=AtsProvider)
    greenhouse: AtsProvider = Field(default_factory=AtsProvider)
    lever: AtsProvider = Field(default_factory=AtsProvider)
    ashby: AtsProvider = Field(default_factory=AtsProvider)
    smartrecruiters: AtsProvider = Field(default_factory=AtsProvider)
    workday: AtsProvider = Field(default_factory=AtsProvider)


class BoardRegistryProviders(StrictModel):
    jazzhr: list[AtsBoard] = Field(default_factory=list)
    rippling: list[AtsBoard] = Field(default_factory=list)
    greenhouse: list[AtsBoard] = Field(default_factory=list)
    lever: list[AtsBoard] = Field(default_factory=list)
    ashby: list[AtsBoard] = Field(default_factory=list)
    smartrecruiters: list[AtsBoard] = Field(default_factory=list)
    workday: list[AtsBoard] = Field(default_factory=list)


class BoardRegistry(StrictModel):
    schema_version: Literal[1] = 1
    providers: BoardRegistryProviders = Field(default_factory=BoardRegistryProviders)


class InventoryConfig(StrictModel):
    schema_version: Literal[1] = 1
    enabled: bool = True
    database_path: str = "data/inventory.db"
    board_registry_path: str | None = None
    use_bundled_boards: bool = False
    raw_payload_retention_days: int = Field(default=30, ge=1)
    initial_lookback_days: int = Field(default=7, ge=1, le=90)
    checkpoint_overlap_hours: int = Field(default=6, ge=0, le=48)
    request_timeout_seconds: float = Field(default=30, ge=5, le=180)
    provider_retry_attempts: int = Field(default=2, ge=1, le=3)
    provider_retry_backoff_seconds: float = Field(default=1, ge=0, le=30)
    search: SearchSettings
    providers: Providers = Field(default_factory=Providers)

    @model_validator(mode="after")
    def require_provider(self) -> InventoryConfig:
        if not self.enabled:
            return self
        if not any(family.enabled for family in self.search.families):
            raise ValueError("enabled configuration requires at least one enabled search family")
        if not any(
            getattr(self.providers, name).enabled for name in type(self.providers).model_fields
        ):
            raise ValueError("at least one provider must be enabled")
        family_names = {family.name for family in self.search.families}
        for provider_name in ("linkedin", "indeed"):
            limits = getattr(self.providers, provider_name).family_results_wanted
            unknown = set(limits) - family_names
            if unknown:
                raise ValueError(
                    f"{provider_name} family result limits reference unknown families: "
                    f"{', '.join(sorted(unknown))}"
                )
        if (
            self.search.remote_only
            and self.providers.linkedin.enabled
            and not self.providers.linkedin.fetch_descriptions
        ):
            raise ValueError("remote-only LinkedIn collection requires description fetching")
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
    linkedin_results_wanted = os.getenv("JOB_PULLER_LINKEDIN_RESULTS_WANTED", "").strip()
    if linkedin_results_wanted:
        try:
            result_target = int(linkedin_results_wanted)
        except ValueError as exc:
            raise ValueError("JOB_PULLER_LINKEDIN_RESULTS_WANTED must be an integer") from exc
        providers = data.setdefault("providers", {})
        if not isinstance(providers, dict):
            raise ValueError(f"providers must be a mapping: {path}")
        linkedin = providers.setdefault("linkedin", {})
        if not isinstance(linkedin, dict):
            raise ValueError(f"providers.linkedin must be a mapping: {path}")
        linkedin["results_wanted"] = result_target
    try:
        config = InventoryConfig.model_validate(data)
    except ValidationError as exc:
        raise ValueError(str(exc)) from exc
    if not config.board_registry_path and not config.use_bundled_boards:
        return config
    registry = (
        load_board_registry(resolve_project_path(path, config.board_registry_path))
        if config.board_registry_path
        else BoardRegistry()
    )
    bundled = (
        BoardRegistry.model_validate_json(
            files("job_puller").joinpath("data/boards.json").read_text()
        )
        if config.use_bundled_boards
        else BoardRegistry()
    )
    provider_updates = {}
    for name in type(registry.providers).model_fields:
        settings = getattr(config.providers, name)
        registry_boards = getattr(registry.providers, name)
        combined = [*settings.boards, *registry_boards]
        identities = [board.id.casefold() for board in combined]
        if len(set(identities)) != len(identities):
            raise ValueError(f"duplicate {name} board id across configuration and registry")
        # Explicit local entries (including disabled ones) override bundled defaults.
        combined.extend(
            board
            for board in getattr(bundled.providers, name)
            if board.id.casefold() not in identities
        )
        provider_updates[name] = settings.model_copy(update={"boards": combined})
    return config.model_copy(
        update={"providers": config.providers.model_copy(update=provider_updates)}
    )


def load_board_registry(path: Path) -> BoardRegistry:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"board registry file not found: {path}") from exc
    except yaml.YAMLError as exc:
        raise ValueError(f"invalid YAML in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"board registry root must be a mapping: {path}")
    try:
        return BoardRegistry.model_validate(data)
    except ValidationError as exc:
        raise ValueError(str(exc)) from exc


def resolve_database_path(config_path: Path, configured: str) -> Path:
    return resolve_project_path(config_path, configured)


def resolve_project_path(config_path: Path, configured: str) -> Path:
    path = Path(configured).expanduser()
    if path.is_absolute():
        return path
    project_root = config_path.resolve().parent.parent
    return project_root / path
