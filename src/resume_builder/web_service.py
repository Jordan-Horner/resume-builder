"""Career dashboard queries and deliberate job-disposition actions."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import threading
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup

from job_puller.compensation import extract_compensation_range
from job_puller.config import load_config, resolve_database_path
from job_puller.database import InventoryDatabase
from job_puller.locations import location_key, matching_location_terms
from job_puller.normalize import normalized_key

from .agent_config import DEFAULT_AGENT_CONFIG, load_agent_config, render_default_agent_config
from .agent_contracts import ModelProviderError
from .agent_openrouter import OpenRouterAdapter
from .applications import current_application_status, iter_records, record_application
from .atomic import atomic_write_json, atomic_write_text
from .discovery_evidence import (
    ResumeDocument,
    extract_query_expansion,
    extract_title_seed,
    interpret_resume_evidence,
)
from .discovery_portfolio import (
    ColdStartLane,
    build_cold_start_portfolio,
    generate_title_suggestions,
    load_cached_title_generation,
)
from .job_onboarding import (
    JobSearchSetupAnswer,
    RoleGroup,
    RoleIntent,
    RoleProposal,
    SetupStatus,
    SetupStep,
    apply_answer,
    start_setup,
)
from .job_onboarding import (
    load_state as load_setup_state,
)
from .job_onboarding import (
    save_state as save_setup_state,
)
from .layout import VaultLayout
from .source_import import SUPPORTED, apply_import_plan, build_import_plan, load_manifest

JOBS_CONFIG = Path("job-search/config/search.yml")
APPLICATIONS_ROOT = Path("applications")
STATE_PATH = Path("job-search/dashboard-state.json")
WORK_MODES = frozenset({"remote", "hybrid", "onsite"})
DATE_RANGES = frozenset({0, 1, 3, 7, 14, 30})
EMPLOYMENT_TYPES = frozenset({"fulltime", "parttime", "contract", "temporary"})
ONBOARDING_STATE_PATH = Path("job-search/web-onboarding.json")
MAX_RESUME_BYTES = 10 * 1024 * 1024
OPENROUTER_SECRET_PATH = Path("build/secrets/openrouter-key")
TITLE_GENERATION_CACHE_PATH = Path("build/job-search/title-generation.json")


InventoryLoader = Callable[[], list[dict[str, Any]]]


def _clean_description(value: object) -> str:
    description = str(value or "").strip()
    if not description:
        return ""
    if not re.search(r"<[a-zA-Z][^>]*>", description):
        return description
    document = BeautifulSoup(description, "html.parser")
    for hidden in document.find_all(("script", "style")):
        hidden.decompose()
    for block in document.find_all(("p", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6")):
        block.append("\n\n")
    lines = [" ".join(line.split()) for line in document.get_text(" ").splitlines()]
    return "\n\n".join(line for line in lines if line)


def _employment_categories(value: object) -> set[str]:
    normalized = re.sub(r"[_-]+", " ", str(value or "").casefold())
    categories: set[str] = set()
    if re.search(r"\bfull\s*time\b", normalized):
        categories.add("fulltime")
    if re.search(r"\bpart\s*time\b", normalized):
        categories.add("parttime")
    if "contract" in normalized:
        categories.add("contract")
    if "temporary" in normalized or "internship" in normalized:
        categories.add("temporary")
    return categories


def _job_timestamp(job: dict[str, Any]) -> datetime | None:
    value = job.get("posted_at") or job.get("first_seen_at")
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


class DashboardService:
    """Shape private workspace data for the local frontend."""

    def __init__(
        self,
        workspace: Path,
        *,
        inventory_loader: InventoryLoader | None = None,
    ) -> None:
        self.workspace = workspace.expanduser().resolve()
        self._inventory_loader = inventory_loader or self._load_inventory
        self._state_lock = threading.Lock()

    def _onboarding_record(self) -> dict[str, Any]:
        path = self.workspace / ONBOARDING_STATE_PATH
        if not path.is_file():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ValueError(f"invalid onboarding state: {path}") from exc
        return payload if isinstance(payload, dict) else {}

    def onboarding_status(self) -> dict[str, Any]:
        layout = VaultLayout.load(self.workspace / "vault", allow_missing=True)
        manifest = load_manifest(layout)
        sources = manifest.get("sources", [])
        source_names = [
            str(item.get("filenames", ["Resume"])[0])
            for item in sources
            if isinstance(item, dict) and item.get("filenames")
        ]
        config_path = self.workspace / JOBS_CONFIG
        existing_search_active = False
        if config_path.is_file():
            existing_search_active = load_config(config_path).enabled
        record = self._onboarding_record()
        setup = load_setup_state(self.workspace)
        complete = bool(record.get("skipped") or record.get("completed"))
        # Existing configured workspaces should not be forced through a new first-run flow.
        if not record and source_names and existing_search_active:
            complete = True
        if setup is not None and setup.status in {
            SetupStatus.READY_TO_ACTIVATE,
            SetupStatus.ACTIVE,
        }:
            complete = True
        if not source_names:
            step = "resume"
        elif setup is None or setup.status == SetupStatus.SKIPPED:
            step = "ai_choice"
        elif setup.status == SetupStatus.IN_PROGRESS:
            step = "location" if setup.step == SetupStep.ELIGIBILITY else setup.step.value
        else:
            step = "complete"
        progress = {
            "resume": 1,
            "ai_choice": 1,
            "roles": 2,
            "eligibility": 3,
            "location": 3,
            "compensation": 4,
            "review": 5,
            "complete": 5,
        }[step]
        return {
            "needs_onboarding": not complete,
            "step": step,
            "progress": progress,
            "resume_count": len(source_names),
            "resume_names": source_names,
            "openrouter_configured": self._openrouter_configured(),
            "setup": setup.model_dump(mode="json") if setup else None,
        }

    def import_resume(self, filename: str, content: bytes) -> dict[str, Any]:
        clean_name = Path(filename).name.strip()
        if not clean_name or clean_name in {".", ".."}:
            raise ValueError("choose a resume file to upload")
        if Path(clean_name).suffix.casefold() not in SUPPORTED:
            allowed = ", ".join(sorted(SUPPORTED))
            raise ValueError(f"unsupported resume type; use one of: {allowed}")
        if not content:
            raise ValueError("the uploaded resume is empty")
        if len(content) > MAX_RESUME_BYTES:
            raise ValueError("the uploaded resume must be 10 MB or smaller")

        upload_root = self.workspace / "build" / "onboarding-uploads"
        upload_root.mkdir(parents=True, exist_ok=True)
        temporary = Path(tempfile.mkdtemp(prefix="resume-", dir=upload_root))
        source = temporary / clean_name
        try:
            source.write_bytes(content)
            layout = VaultLayout.load(self.workspace / "vault", allow_missing=True)
            plan = build_import_plan(layout, [str(source)], [])
            if plan.errors:
                raise ValueError(plan.errors[0]["error"])
            if plan.empty:
                raise ValueError("no readable resume text was found in that file")
            apply_import_plan(layout, plan)
            return {
                "filename": clean_name,
                "added": plan.added,
                "already_registered": plan.unchanged > 0,
                "registered_sources": len(plan.manifest["sources"]),
            }
        finally:
            shutil.rmtree(temporary, ignore_errors=True)

    def skip_onboarding(self) -> None:
        atomic_write_json(
            self.workspace / ONBOARDING_STATE_PATH,
            {
                "schema_version": 1,
                "completed": False,
                "skipped": True,
                "skipped_at": datetime.now(UTC).isoformat(),
            },
        )

    def _openrouter_secret_path(self) -> Path:
        override = os.environ.get("RESUME_BUILDER_OPENROUTER_KEY_FILE", "").strip()
        return (
            Path(override).expanduser().resolve()
            if override
            else (self.workspace / OPENROUTER_SECRET_PATH)
        )

    def _openrouter_key(self) -> str:
        path = self._openrouter_secret_path()
        if path.is_file():
            return path.read_text(encoding="utf-8").strip()
        config_path = self.workspace / DEFAULT_AGENT_CONFIG
        env_name = (
            load_agent_config(config_path).api_key_env
            if config_path.is_file()
            else "OPENROUTER_API_KEY"
        )
        return os.environ.get(env_name, "").strip()

    def _openrouter_configured(self) -> bool:
        return bool(self._openrouter_key())

    def _save_openrouter_key(self, api_key: str) -> None:
        path = self._openrouter_secret_path()
        atomic_write_text(path, api_key.strip() + "\n")
        path.chmod(0o600)

    def _primary_resume_document(self) -> ResumeDocument:
        layout = VaultLayout.load(self.workspace / "vault")
        manifest = load_manifest(layout)
        documents = [
            ResumeDocument(
                source_id=str(item["id"]),
                content=layout.snapshot_path(item["snapshot"]).read_text(encoding="utf-8"),
            )
            for item in manifest["sources"]
        ]
        if not documents:
            raise ValueError("add a resume before choosing role suggestions")
        return max(documents, key=lambda item: len(item.content))

    def _semantic_roles(self, api_key: str) -> list[RoleProposal]:
        document = self._primary_resume_document()
        config_path = self.workspace / DEFAULT_AGENT_CONFIG
        if not config_path.is_file():
            atomic_write_text(config_path, render_default_agent_config())
        config = load_agent_config(config_path)
        adapter = OpenRouterAdapter(config, api_key=api_key)
        interpretation_path = self.workspace / "build/job-search/resume-interpretation.json"
        cache_key = hashlib.sha256(
            ("line-reader-v1:" + config.models.fast + ":" + document.content).encode()
        ).hexdigest()
        if interpretation_path.is_file():
            cached = json.loads(interpretation_path.read_text(encoding="utf-8"))
            if cached.get("key") == cache_key:
                cached_document = ResumeDocument.model_validate(cached["document"])
                if cached_document.content == document.content:
                    document = cached_document
        try:
            document = interpret_resume_evidence(document, adapter, model=config.models.fast)
        except ModelProviderError as exc:
            raise ValueError(
                "OpenRouter could not interpret the resume. Please try again."
            ) from exc
        atomic_write_json(
            interpretation_path,
            {
                "key": cache_key,
                "document": document.model_dump(mode="json"),
            },
        )
        title_seed = extract_title_seed([document])
        expansion = extract_query_expansion(document)
        cache_path = self.workspace / TITLE_GENERATION_CACHE_PATH
        generation = load_cached_title_generation(cache_path, document, config.models.fast)
        if generation is None:
            try:
                generation = generate_title_suggestions(
                    document,
                    adapter,
                    model=config.models.fast,
                )
            except ModelProviderError as exc:
                raise ValueError(
                    "OpenRouter could not create role suggestions. Check the key and try again, "
                    "or continue without AI."
                ) from exc
            atomic_write_json(cache_path, generation.model_dump(mode="json"))
        portfolio = build_cold_start_portfolio(
            document,
            title_seed,
            expansion,
            generation,
        )
        return [
            RoleProposal(
                role_id=f"role-{query.query_id}",
                title=query.query,
                group=(
                    RoleGroup.CURRENT_RECENT
                    if query.lane == ColdStartLane.HISTORICAL_TITLE
                    else RoleGroup.RELATED
                ),
                intent=(
                    RoleIntent.SEARCH
                    if query.lane == ColdStartLane.HISTORICAL_TITLE
                    else RoleIntent.EXPLORE
                ),
                lane=query.lane,
                source_ids=query.source_ids,
                evidence_role=query.evidence_role,
                evidence_terms=query.evidence_terms,
                reason=query.reason,
            )
            for query in portfolio.queries
            if query.lane
            in {
                ColdStartLane.HISTORICAL_TITLE,
                ColdStartLane.ADJACENT_TITLE,
                ColdStartLane.EXPLORATION,
            }
        ]

    def start_preference_setup(self, *, use_ai: bool, api_key: str = "") -> dict[str, Any]:
        key = api_key.strip() or self._openrouter_key()
        semantic_roles: list[RoleProposal] = []
        if use_ai:
            if not key:
                raise ValueError("enter an OpenRouter API key or continue without AI")
            semantic_roles = self._semantic_roles(key)
            if api_key.strip():
                self._save_openrouter_key(api_key)
        existing = load_setup_state(self.workspace)
        start_setup(
            self.workspace,
            restart=existing is not None,
            additional_roles=semantic_roles,
        )
        return self.onboarding_status()

    def answer_preference_step(self, step: str, answer: dict[str, Any]) -> dict[str, Any]:
        state = load_setup_state(self.workspace)
        if state is None:
            raise ValueError("preference setup has not started")
        try:
            setup_step = SetupStep(step)
        except ValueError as exc:
            raise ValueError(f"unsupported onboarding step: {step}") from exc
        updated = apply_answer(
            self.workspace,
            JobSearchSetupAnswer(
                session_id=state.session_id,
                step=setup_step,
                answer=answer,
            ),
        )
        if updated.status == SetupStatus.READY_TO_ACTIVATE:
            atomic_write_json(
                self.workspace / ONBOARDING_STATE_PATH,
                {
                    "schema_version": 2,
                    "completed": True,
                    "completed_at": datetime.now(UTC).isoformat(),
                },
            )
        return self.onboarding_status()

    def previous_preference_step(self) -> dict[str, Any]:
        state = load_setup_state(self.workspace)
        if state is None or state.status != SetupStatus.IN_PROGRESS:
            raise ValueError("preference setup is not in progress")
        previous = {
            SetupStep.ELIGIBILITY: SetupStep.ROLES,
            SetupStep.LOCATION: SetupStep.ROLES,
            SetupStep.COMPENSATION: SetupStep.LOCATION,
            SetupStep.REVIEW: SetupStep.COMPENSATION,
        }.get(state.step)
        if previous is None:
            raise ValueError("this is the first preference step")
        state.step = previous
        state.updated_at = datetime.now(UTC).isoformat()
        save_setup_state(self.workspace, state)
        return self.onboarding_status()

    def _load_inventory(self) -> list[dict[str, Any]]:
        config_path = self.workspace / JOBS_CONFIG
        config = load_config(config_path)
        database = InventoryDatabase(
            resolve_database_path(config_path, config.database_path),
            config.raw_payload_retention_days,
        )
        database.migrate()
        return database.active_inventory()

    def _dismissed_job_ids(self) -> set[str]:
        path = self.workspace / STATE_PATH
        if not path.is_file():
            return set()
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ValueError(f"invalid dashboard state: {path}") from exc
        values = payload.get("dismissed_job_ids", []) if isinstance(payload, dict) else []
        return {value for value in values if isinstance(value, str) and value.strip()}

    def _write_dismissed_job_ids(self, values: set[str]) -> None:
        atomic_write_json(
            self.workspace / STATE_PATH,
            {"schema_version": 2, "dismissed_job_ids": sorted(values)},
        )

    @staticmethod
    def _serialize_job(job: dict[str, Any]) -> dict[str, Any]:
        modes = [str(mode) for mode in job.get("work_modes", []) if str(mode)]
        providers = [str(provider) for provider in job.get("providers", []) if str(provider)]
        description = _clean_description(job.get("description_text"))
        compensation = (
            extract_compensation_range(description)
            if job.get("salary_min") is None and job.get("salary_max") is None
            else None
        )
        return {
            "id": str(job.get("id", "")),
            "title": str(job.get("title", "Untitled role")),
            "company": str(job.get("company", "Unknown company")),
            "location": str(job.get("location") or "Location not listed"),
            "country": str(job.get("country") or ""),
            "employment_type": job.get("employment_type"),
            "salary_min": compensation.minimum if compensation else job.get("salary_min"),
            "salary_max": compensation.maximum if compensation else job.get("salary_max"),
            "salary_currency": (
                compensation.currency if compensation else job.get("salary_currency")
            ),
            "salary_interval": (
                compensation.interval if compensation else job.get("salary_interval")
            ),
            "posted_at": job.get("posted_at"),
            "first_seen_at": job.get("first_seen_at"),
            "last_seen_at": job.get("last_seen_at"),
            "description": description,
            "work_modes": modes,
            "providers": providers,
            "url": job.get("url"),
        }

    def blocked_companies(self) -> list[str]:
        import yaml

        path = self.workspace / "job-search/preferences.yml"
        if not path.exists():
            return []
        raw = yaml.safe_load(path.read_text())
        if not isinstance(raw, dict):
            raise ValueError("Invalid job search preferences")
        values = raw.get("excluded_companies", [])
        if not isinstance(values, list) or not all(isinstance(item, str) for item in values):
            raise ValueError("Invalid excluded companies preference")
        return values

    def set_company_blocked(self, company: str, blocked: bool) -> list[str]:
        import yaml

        from .job_setup_defaults import neutral_preferences
        from .preferences import _validated

        if (
            not isinstance(company, str)
            or not 1 <= len(company.strip()) <= 200
            or not normalized_key(company)
        ):
            raise ValueError("Choose a valid company name")
        if type(blocked) is not bool:
            raise ValueError("blocked must be true or false")
        company = company.strip()
        with self._state_lock:
            path = self.workspace / "job-search/preferences.yml"
            raw = yaml.safe_load(path.read_text()) if path.exists() else neutral_preferences()
            values = self.blocked_companies()
            key = normalized_key(company)
            if blocked:
                if not any(normalized_key(item) == key for item in values):
                    values.append(company)
            else:
                values = [item for item in values if normalized_key(item) != key]
            raw["excluded_companies"] = values
            _validated(raw)
            atomic_write_text(path, yaml.safe_dump(raw, sort_keys=False))
        return values

    def job_filter_defaults(self) -> dict[str, Any]:
        from .jobs import _load_preferences
        from .web_filters import ViewFilters

        path = self.workspace / "job-search/preferences.yml"
        preferences = _load_preferences(path) if path.exists() else {}
        profile = preferences.get("screening_profile") or {}
        return ViewFilters(
            country=profile.get("intended_work_country") or "",
            workModes=preferences.get("accepted_work_modes") or [],
            minimumPay=preferences.get("minimum_salary"),
            currency=preferences.get("salary_currency") or "USD",
            period=preferences.get("salary_period") or "year",
        ).model_dump()

    def list_jobs(
        self,
        *,
        search: str = "",
        work_mode: str = "",
        date_days: int = 0,
        employment_type: str = "",
        view_filters: str = "",
    ) -> list[dict[str, Any]]:
        from .web_filters import ViewFilters, matches_view

        view = ViewFilters.model_validate_json(view_filters) if view_filters else ViewFilters()
        # Country is a workspace boundary, not a client-side viewing choice.
        # Apply it to the combined inventory, including global ATS boards.
        scope = self.job_filter_defaults()["country"]
        view = view.model_copy(update={"country": scope, "includeUnmatchedLocation": False})
        normalized_mode = work_mode.strip().casefold()
        if normalized_mode and normalized_mode not in WORK_MODES:
            raise ValueError(f"unsupported work mode: {work_mode}")
        normalized_type = employment_type.strip().casefold()
        if normalized_type and normalized_type not in EMPLOYMENT_TYPES:
            raise ValueError(f"unsupported employment type: {employment_type}")
        if date_days not in DATE_RANGES:
            raise ValueError(f"unsupported date range: {date_days}")
        cutoff = datetime.now(UTC) - timedelta(days=date_days) if date_days else None
        query = search.strip().casefold()
        dismissed = self._dismissed_job_ids()
        blocked = {normalized_key(company) for company in self.blocked_companies()}
        applied = {
            str(record["application"].get("job_id"))
            for _, record in iter_records(self.workspace / APPLICATIONS_ROOT)
            if record["application"].get("job_id")
        }
        jobs: list[dict[str, Any]] = []
        for raw in self._inventory_loader():
            job = self._serialize_job(raw)
            if not job["id"] or job["id"] in dismissed or job["id"] in applied:
                continue
            if normalized_key(str(job["company"])) in blocked:
                continue
            if not matches_view(job, view):
                continue
            if view.employmentTypes and not set(view.employmentTypes).intersection(
                _employment_categories(job["employment_type"])
            ):
                continue
            if normalized_mode and normalized_mode not in job["work_modes"]:
                continue
            if normalized_type and normalized_type not in _employment_categories(
                job["employment_type"]
            ):
                continue
            if cutoff and ((timestamp := _job_timestamp(job)) is None or timestamp < cutoff):
                continue
            haystack = " ".join(
                str(job[field]) for field in ("title", "company", "location", "description")
            ).casefold()
            if query:
                location_match = bool(matching_location_terms(str(job["location"]), [query]))
                if location_key(query) == "united states":
                    if not location_match:
                        continue
                elif query not in haystack and not location_match:
                    continue
            jobs.append(job)
        return jobs

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        for raw in self._inventory_loader():
            if str(raw.get("id")) == job_id:
                return self._serialize_job(raw)
        return None

    def mark_not_interested(self, job_id: str) -> None:
        if self.get_job(job_id) is None:
            raise ValueError(f"job not found: {job_id}")
        with self._state_lock:
            dismissed = self._dismissed_job_ids()
            dismissed.add(job_id)
            self._write_dismissed_job_ids(dismissed)

    def mark_applied(self, job_id: str) -> dict[str, Any]:
        job = self.get_job(job_id)
        if job is None:
            raise ValueError(f"job not found: {job_id}")
        with self._state_lock:
            for _, record in iter_records(self.workspace / APPLICATIONS_ROOT):
                if str(record["application"].get("job_id")) == job_id:
                    return record
            return record_application(
                self.workspace / APPLICATIONS_ROOT,
                self.workspace,
                company=job["company"],
                role=job["title"],
                job_id=job_id,
                application_url=job["url"],
            )

    def list_applications(self) -> list[dict[str, Any]]:
        applications: list[dict[str, Any]] = []
        for _, record in iter_records(self.workspace / APPLICATIONS_ROOT):
            application = record["application"]
            events = sorted(
                record.get("events", []),
                key=lambda event: (
                    str(event.get("effective_on", "")),
                    str(event.get("recorded_at", "")),
                ),
                reverse=True,
            )
            applications.append(
                {
                    "id": application["id"],
                    "company": application["company"],
                    "role": application["role"],
                    "job_id": application.get("job_id"),
                    "application_url": application.get("application_url"),
                    "applied_on": application["applied_on"],
                    "created_at": application["created_at"],
                    "current_status": current_application_status(record),
                    "events": [
                        {
                            "id": event["id"],
                            "status": event["status"],
                            "effective_on": event["effective_on"],
                            "stage": event.get("stage"),
                            "note": event.get("note"),
                        }
                        for event in events
                    ],
                }
            )
        return sorted(applications, key=lambda item: item["applied_on"], reverse=True)

    def list_integrations(self) -> list[dict[str, Any]]:
        job_config_path = self.workspace / JOBS_CONFIG
        enabled_providers: list[str] = []
        if job_config_path.is_file():
            config = load_config(job_config_path)
            for name in type(config.providers).model_fields:
                if getattr(config.providers, name).enabled:
                    enabled_providers.append(name)

        from .gmail_automation import default_state_path, default_token_path

        gmail_connected = default_token_path(default_state_path()).is_file()

        agent_config_path = self.workspace / "agent/config.yml"
        telegram_configured = False
        openrouter_connected = self._openrouter_configured()
        if agent_config_path.is_file():
            from .agent_config import load_agent_config
            from .agent_telegram_setup import default_telegram_token_path, resolve_telegram_token

            agent_config = load_agent_config(agent_config_path)
            telegram_configured = bool(
                agent_config.channels.telegram.enabled
                and resolve_telegram_token(
                    agent_config.channels.telegram,
                    token_path=default_telegram_token_path(),
                )
            )

        automation_config_path = self.workspace / "automation/config.yml"
        discord_configured = False
        discord_connected = False
        if automation_config_path.is_file():
            from .automation import load_config as load_automation_config

            automation_config = load_automation_config(automation_config_path)
            discord_configured = automation_config.notifications.sink == "discord"
            discord_connected = discord_configured and bool(
                os.environ.get(automation_config.notifications.webhook_env)
            )
        return [
            {
                "id": "job-providers",
                "name": "Job providers",
                "description": "Sources that keep your job review queue current.",
                "status": "connected" if enabled_providers else "not_connected",
                "detail": f"{len(enabled_providers)} sources enabled"
                if enabled_providers
                else "No sources enabled",
                "setup_command": "resume-builder onboard run",
            },
            {
                "id": "gmail",
                "name": "Gmail",
                "description": "Detect applications and status updates from your inbox.",
                "status": "connected" if gmail_connected else "not_connected",
                "detail": "Read-only access" if gmail_connected else "Setup required",
                "setup_command": "resume-builder gmail connect",
            },
            {
                "id": "telegram",
                "name": "Telegram",
                "description": "Use the private career assistant from Telegram.",
                "status": "connected" if telegram_configured else "not_connected",
                "detail": "Private bot ready" if telegram_configured else "Setup required",
                "setup_command": "resume-builder agent telegram-setup",
            },
            {
                "id": "discord",
                "name": "Discord",
                "description": "Receive job refresh and application notifications.",
                "status": "connected"
                if discord_connected
                else ("configured" if discord_configured else "not_connected"),
                "detail": "Webhook ready"
                if discord_connected
                else ("Webhook key required" if discord_configured else "Setup required"),
                "setup_command": "resume-builder automation init --timezone America/New_York",
            },
            {
                "id": "openrouter",
                "name": "OpenRouter",
                "description": "Power screening and assistant features with your model provider.",
                "status": "connected" if openrouter_connected else "not_connected",
                "detail": "API key available" if openrouter_connected else "API key not available",
                "setup_command": "resume-builder agent init",
            },
        ]
