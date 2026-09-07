"""Career dashboard queries and deliberate job-disposition actions."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import tempfile
import threading
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, NoReturn
from uuid import uuid4

import httpx
import yaml
from bs4 import BeautifulSoup

from job_puller.compensation import extract_compensation_range
from job_puller.config import load_config, resolve_database_path, resolve_project_path
from job_puller.database import InventoryDatabase
from job_puller.locations import location_key, matching_location_terms
from job_puller.normalize import normalized_key

from .agent_config import DEFAULT_AGENT_CONFIG, load_agent_config, render_default_agent_config
from .agent_contracts import ModelProviderError
from .agent_openrouter import OpenRouterAdapter
from .applications import current_application_status, iter_records, record_application
from .atomic import atomic_write_json, atomic_write_text
from .discovery_activation import MANAGED_FAMILY_PREFIX, preview_activation
from .discovery_evidence import (
    ResumeDocument,
    extract_query_expansion,
    extract_title_seed,
    interpret_resume_evidence,
)
from .discovery_portfolio import (
    ColdStartLane,
    ColdStartPortfolio,
    build_cold_start_portfolio,
    generate_title_suggestions,
    load_cached_title_generation,
)
from .job_onboarding import (
    CompensationAnswers,
    EligibilityAnswers,
    JobSearchSetupAnswer,
    JobSearchSetupState,
    LocationAnswers,
    RoleGroup,
    RoleIntent,
    RoleProposal,
    SetupStatus,
    SetupStep,
    activation_preview,
    apply_answer,
    portfolio_from_setup_state,
    start_setup,
)
from .job_onboarding import (
    activate as activate_setup,
)
from .job_onboarding import (
    load_state as load_setup_state,
)
from .job_onboarding import (
    save_state as save_setup_state,
)
from .job_personalization import (
    extract_preference_traits,
    extract_seniority,
    load_feedback_events,
    score_shadow_job,
)
from .job_screening import EligibilityStatus, ScreeningCache, deterministic_ineligible_result
from .job_setup_defaults import PORTFOLIO_PATH, PREFERENCES_PATH, scaffold_job_search
from .job_target import parse_target
from .jobs import get_job_screening_packet
from .layout import VaultLayout
from .posting_interpretation import PostingInterpretationCache, PostingInterpretationService
from .preferences import _validated as validate_preferences
from .project_report import project_report
from .role_policy import MAX_TITLE_LENGTH, MIN_TITLE_LENGTH, check_query_capacity, clean_titles
from .salary_estimation import (
    SALARY_CACHE_PATH,
    SalaryEstimationService,
    build_salary_packet,
    has_posted_salary,
)
from .screening_service import ScreeningService, enrich_packet_from_cached_interpretation
from .source_import import (
    SUPPORTED,
    apply_import_plan,
    build_import_plan,
    load_manifest,
    resume_manifest_sources,
)

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
JOB_FEEDBACK_PATH = Path("job-search/job-feedback.json")
JOB_SCREENING_OUTPUT = Path("job-search/new-job-screens.json")
JOB_FEEDBACK_ACTIONS = frozenset({"interested", "not_interested", "applied"})
JOB_FEEDBACK_REASONS = frozenset(
    {
        "company",
        "compensation",
        "customer_facing",
        "day_to_day",
        "location",
        "on_call",
        "phone_support",
        "role",
        "seniority",
        "travel",
        "work_mode",
    }
)
LOGGER = logging.getLogger(__name__)


class ScreeningInputError(RuntimeError):
    """A screening input could not be decoded or read safely."""


def _raise_screening_input_error(job_id: str, stage: str, exc: UnicodeError) -> NoReturn:
    LOGGER.warning(
        "job_screen_failed job_id=%s stage=%s error_category=%s",
        job_id,
        stage,
        exc.__class__.__name__,
    )
    raise ScreeningInputError(
        "Job screening could not read one of its inputs. Refresh your jobs and try again."
    ) from exc


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
        self._salary_lock = threading.Lock()
        self._screening_lock = threading.Lock()

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
        sources = resume_manifest_sources(manifest)
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
        if setup is not None:
            if setup.status == SetupStatus.READY_TO_ACTIVATE:
                # Older portal versions recorded completion before activating the
                # generated search families. Require the explicit recovery step.
                complete = False
            elif setup.status == SetupStatus.ACTIVE:
                complete = True
        if not source_names:
            step = "resume"
        elif setup is None or setup.status == SetupStatus.SKIPPED:
            step = "ai_choice"
        elif setup.status == SetupStatus.IN_PROGRESS:
            step = "location" if setup.step == SetupStep.ELIGIBILITY else setup.step.value
        elif setup.status == SetupStatus.READY_TO_ACTIVATE:
            step = "activation"
        else:
            step = "complete"
        if (
            setup is not None
            and setup.status == SetupStatus.IN_PROGRESS
            and setup.step == SetupStep.ROLES
            and record.get("suggestion_choice_session") == setup.session_id
        ):
            step = "ai_choice"
        progress = {
            "resume": 1,
            "ai_choice": 1,
            "roles": 2,
            "eligibility": 3,
            "location": 3,
            "compensation": 4,
            "review": 5,
            "activation": 5,
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
            plan = build_import_plan(layout, [str(source)], [], document_kind="resume")
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

    def configure_openrouter(self, api_key: Any) -> dict[str, Any]:
        if not isinstance(api_key, str) or not 1 <= len(api_key.strip()) <= 512:
            raise ValueError("Enter an OpenRouter API key")
        key = api_key.strip()
        if any(character.isspace() for character in key):
            raise ValueError("The API key must not contain spaces or line breaks")
        try:
            response = httpx.get(
                "https://openrouter.ai/api/v1/key",
                headers={"Authorization": f"Bearer {key}"},
                timeout=15,
                follow_redirects=False,
                trust_env=False,
            )
        except httpx.HTTPError as exc:
            raise ValueError("Could not reach OpenRouter. Your saved key is unchanged.") from exc
        if response.status_code in {401, 403}:
            raise ValueError("OpenRouter rejected this key. Check it and try again.")
        if response.status_code != 200:
            raise ValueError("OpenRouter could not verify the key. Please try again shortly.")
        try:
            if not isinstance(response.json().get("data"), dict):
                raise ValueError("Invalid key response")
        except (ValueError, AttributeError) as exc:
            raise ValueError(
                "OpenRouter returned an unexpected response. The key was not saved."
            ) from exc
        with self._state_lock:
            config_path = self.workspace / DEFAULT_AGENT_CONFIG
            if not config_path.is_file():
                atomic_write_text(config_path, render_default_agent_config())
            else:
                load_agent_config(config_path)
            self._save_openrouter_key(key)
        return {
            "connected": True,
            "message": "OpenRouter connected. Your existing model settings are preserved.",
        }

    def configure_bright_data(
        self, api_key: Any, enabled: Any, max_records_per_refresh: Any
    ) -> dict[str, Any]:
        from .bright_data import (
            BrightDataSettings,
            bright_data_key,
            bright_data_secret_path,
            save_bright_data_settings,
        )

        if not isinstance(enabled, bool):
            raise ValueError("Choose whether Bright Data enrichment is enabled")
        if (
            not isinstance(max_records_per_refresh, int)
            or isinstance(max_records_per_refresh, bool)
            or not 1 <= max_records_per_refresh <= 1000
        ):
            raise ValueError("Bright Data record limit must be from 1 to 1000")
        key = api_key.strip() if isinstance(api_key, str) else ""
        if key and (len(key) > 512 or any(character.isspace() for character in key)):
            raise ValueError("The API token must not contain spaces or line breaks")
        if enabled and not (key or bright_data_key(self.workspace)):
            raise ValueError("Enter a Bright Data API token before enabling enrichment")
        with self._state_lock:
            if key:
                secret_path = bright_data_secret_path(self.workspace)
                atomic_write_text(secret_path, key + "\n")
                secret_path.chmod(0o600)
            save_bright_data_settings(
                self.workspace,
                BrightDataSettings(
                    enabled=enabled,
                    max_records_per_refresh=max_records_per_refresh,
                ),
            )
        return {
            "connected": bool(key or bright_data_key(self.workspace)),
            "enabled": enabled,
            "max_records_per_refresh": max_records_per_refresh,
            "message": "Bright Data integration saved.",
        }

    def enrich_bright_data(self) -> dict[str, Any]:
        from job_puller.source_resolution import (
            AtsCatalog,
            linkedin_targets,
            resolve_linkedin_sources,
        )

        from .bright_data import (
            bright_data_key,
            enrich_linkedin_targets,
            load_bright_data_settings,
            save_captured_boards,
        )

        settings = load_bright_data_settings(self.workspace)
        token = bright_data_key(self.workspace)
        if not settings.enabled or not token:
            raise ValueError("Connect and enable Bright Data before enriching jobs")
        config_path = self.workspace / JOBS_CONFIG
        config = load_config(config_path)
        database = InventoryDatabase(
            resolve_database_path(config_path, config.database_path),
            config.raw_payload_retention_days,
        )
        database.migrate()
        with self._state_lock:
            targets = linkedin_targets(database)
            report = enrich_linkedin_targets(
                database,
                targets,
                api_token=token,
                limit=min(settings.max_records_per_refresh, 25),
                timeout=max(60, config.request_timeout_seconds),
            )
            board_seeds = save_captured_boards(
                database, config_path, timeout=config.request_timeout_seconds
            )
            report["board_seeds"] = board_seeds
            followup_catalog = AtsCatalog.load(
                resolve_project_path(config_path, "cache/ats-source-catalog")
            ).add_configured_boards(load_config(config_path))
            captured = [
                target
                for target in linkedin_targets(database)
                if target.direct_apply_url or followup_catalog.boards_for(target.company)
            ]
            if captured and (board_seeds.get("added") or report.get("apply_links_added")):
                report["ats_followup"] = resolve_linkedin_sources(
                    database,
                    followup_catalog,
                    timeout=config.request_timeout_seconds,
                    apply=True,
                    max_board_requests=25,
                    workers=config.source_resolution.workers,
                    targets=captured,
                ).as_dict()
        report["message"] = (
            f"Bright Data checked {report['requested']} job(s): "
            f"{report['improved']} improved, {report['no_change']} unchanged, "
            f"{report['failed']} failed, and {report['skipped_cached']} already checked."
        )
        return report

    def _primary_resume_document(self) -> ResumeDocument:
        layout = VaultLayout.load(self.workspace / "vault")
        manifest = load_manifest(layout)
        sources = resume_manifest_sources(manifest)
        documents = [
            ResumeDocument(
                source_id=str(item["id"]),
                content=layout.snapshot_path(item["snapshot"]).read_text(encoding="utf-8"),
            )
            for item in sources
        ]
        if not documents:
            raise ValueError("add a resume before choosing role suggestions")
        by_id = {item.source_id: item for item in documents}
        selected = max(
            sources,
            key=lambda item: (
                str(item.get("refreshed_at") or item.get("imported_at") or ""),
                int(item.get("extracted_characters") or 0),
            ),
        )
        return by_id[str(selected["id"])]

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
        with self._state_lock:
            existing = load_setup_state(self.workspace)
            if existing is not None and existing.status == SetupStatus.IN_PROGRESS:
                known = {normalized_key(role.title) for role in existing.roles}
                for role in semantic_roles:
                    if normalized_key(role.title) not in known:
                        existing.roles.append(role)
                        known.add(normalized_key(role.title))
                existing.step = SetupStep.ROLES
                save_setup_state(self.workspace, existing)
            else:
                start_setup(self.workspace, additional_roles=semantic_roles)
            record = self._onboarding_record()
            if "suggestion_choice_session" in record:
                record.pop("suggestion_choice_session")
                atomic_write_json(self.workspace / ONBOARDING_STATE_PATH, record)
        return self.onboarding_status()

    def answer_preference_step(self, step: str, answer: dict[str, Any]) -> dict[str, Any]:
        state = load_setup_state(self.workspace)
        if state is None:
            raise ValueError("preference setup has not started")
        try:
            setup_step = SetupStep(step)
        except ValueError as exc:
            raise ValueError(f"unsupported onboarding step: {step}") from exc
        if step == "roles" and "titles" in answer:
            answer = {
                "titles": self.preview_role_titles(
                    {"scope": "onboarding", "titles": answer["titles"]}
                )["titles"]
            }
        updated = apply_answer(
            self.workspace,
            JobSearchSetupAnswer(
                session_id=state.session_id,
                step=setup_step,
                answer=answer,
            ),
        )
        if updated.status == SetupStatus.READY_TO_ACTIVATE:
            preview = activation_preview(self.workspace)
            updated = activate_setup(self.workspace, preview["confirmation_hash"])
            atomic_write_json(
                self.workspace / ONBOARDING_STATE_PATH,
                {
                    "schema_version": 2,
                    "completed": True,
                    "completed_at": datetime.now(UTC).isoformat(),
                },
            )
        return self.onboarding_status()

    def activate_job_search(self) -> dict[str, Any]:
        """Finish a legacy ready-to-activate setup without starting a scan."""
        with self._state_lock:
            preview = activation_preview(self.workspace)
            activate_setup(self.workspace, preview["confirmation_hash"])
            atomic_write_json(
                self.workspace / ONBOARDING_STATE_PATH,
                {
                    "schema_version": 2,
                    "completed": True,
                    "completed_at": datetime.now(UTC).isoformat(),
                },
            )
        return self.onboarding_status()

    def _job_search_preferences_revision(self) -> str:
        paths = [
            self.workspace / PREFERENCES_PATH,
            self.workspace / JOBS_CONFIG,
            self.workspace / PORTFOLIO_PATH,
        ]
        rendered = "\n".join(
            path.read_text(encoding="utf-8") if path.is_file() else "" for path in paths
        )
        return hashlib.sha256(rendered.encode("utf-8")).hexdigest()

    def job_search_preferences(self) -> dict[str, Any]:
        scaffold_job_search(self.workspace)
        preferences = validate_preferences(
            yaml.safe_load((self.workspace / PREFERENCES_PATH).read_text(encoding="utf-8"))
        )
        profile = dict(preferences.get("screening_profile") or {})
        setup = load_setup_state(self.workspace)
        config = load_config(self.workspace / JOBS_CONFIG)
        titles = preferences.get("desired_title_terms", [])
        titles = list(dict.fromkeys(str(title).strip() for title in titles if str(title).strip()))
        return {
            "status": setup.status.value
            if setup
            else "active"
            if config.enabled
            else "not_configured",
            "revision": self._job_search_preferences_revision(),
            "titles": titles,
            "country": profile.get("intended_work_country") or "United States",
            "work_modes": preferences.get("accepted_work_modes") or [],
            "onsite_locations": preferences.get("accepted_location_terms") or [],
            "remote_location_terms": profile.get("remote_location_terms") or [],
            "clearance_preference": preferences.get("clearance_preference", "neutral"),
            "preferred_job_attributes": preferences.get("preferred_job_attributes") or [],
            "avoided_job_attributes": preferences.get("avoided_job_attributes") or [],
            "compensation": {
                "skipped": preferences.get("minimum_salary") is None
                and preferences.get("preferred_salary") is None,
                "minimum": preferences.get("minimum_salary"),
                "target": preferences.get("preferred_salary"),
                "currency": preferences.get("salary_currency"),
                "period": preferences.get("salary_period"),
            },
        }

    _clean_titles = staticmethod(clean_titles)

    def _legacy_active_setup_state(
        self,
        current: dict[str, Any],
        preferences: dict[str, Any],
        *,
        country: str,
        location: LocationAnswers,
        compensation: CompensationAnswers,
    ) -> JobSearchSetupState | None:
        """Reconstruct portal bookkeeping for a pre-onboarding active workspace."""
        if not load_config(self.workspace / JOBS_CONFIG).enabled:
            return None
        profile = dict(preferences.get("screening_profile") or {})
        timestamp = datetime.now(UTC).isoformat()
        roles = [
            RoleProposal(
                role_id=(
                    f"role-legacy-{hashlib.sha256(title.casefold().encode()).hexdigest()[:12]}"
                ),
                title=title,
                group=RoleGroup.RELATED,
                intent=RoleIntent.SEARCH,
                lane=ColdStartLane.ADJACENT_TITLE,
                source_ids=["legacy-preferences"],
                reason="Preserved from search preferences created before portal onboarding.",
            )
            for title in current["titles"]
        ]
        return JobSearchSetupState(
            session_id=f"legacy-{current['revision'][:24]}",
            status=SetupStatus.ACTIVE,
            step=SetupStep.COMPLETE,
            created_at=timestamp,
            updated_at=timestamp,
            evidence_hash=f"legacy-{current['revision']}",
            source_ids=[],
            roles=roles,
            eligibility=EligibilityAnswers(
                intended_country=country,
                authorized_to_work=profile.get("authorized_to_work"),
                requires_sponsorship=profile.get("requires_sponsorship"),
                held_clearances=profile.get("held_clearances") or [],
                holds_clearance_or_public_trust=profile.get("holds_clearance_or_public_trust"),
                willing_to_obtain_clearance=profile.get("willing_to_obtain_clearance"),
            ),
            location=location,
            compensation=compensation,
        )

    def preview_role_titles(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Validate an unsaved selection against the current shared search budget."""
        if payload.get("scope") not in {"onboarding", "settings"}:
            raise ValueError("role scope must be onboarding or settings")
        titles = clean_titles(payload.get("titles"), allow_empty=True)
        remaining = check_query_capacity(titles)
        return {
            "titles": titles,
            "remaining": remaining,
            "minimum_length": MIN_TITLE_LENGTH,
            "maximum_length": MAX_TITLE_LENGTH,
        }

    def update_job_search_preferences(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._state_lock:
            current = self.job_search_preferences()
            if payload.get("revision") != current["revision"]:
                raise ValueError("these preferences changed in another tab; reload and try again")
            titles = self._clean_titles(payload.get("titles"))
            self.preview_role_titles({"scope": "settings", "titles": titles})
            country = str(payload.get("country") or "").strip()
            location = LocationAnswers.model_validate(
                {
                    "search_country": country,
                    "accepted_work_modes": payload.get("work_modes"),
                    "accepted_onsite_locations": payload.get("onsite_locations", []),
                    "remote_location_terms": payload.get("remote_location_terms") or None,
                }
            )
            compensation = CompensationAnswers.model_validate(payload.get("compensation"))
            clearance_preference = payload.get("clearance_preference", "neutral")
            if clearance_preference not in {"neutral", "prefer", "exclude"}:
                raise ValueError("clearance_preference must be neutral, prefer, or exclude")
            preferences_path = self.workspace / PREFERENCES_PATH
            config_path = self.workspace / JOBS_CONFIG
            preferences = yaml.safe_load(preferences_path.read_text(encoding="utf-8"))
            state = load_setup_state(self.workspace)
            if state is None:
                state = self._legacy_active_setup_state(
                    current,
                    preferences,
                    country=country,
                    location=location,
                    compensation=compensation,
                )
            if state is None:
                raise ValueError("finish job-search setup before editing search preferences")
            existing = {normalized_key(item.title): item for item in state.roles}
            selected_keys = {normalized_key(title) for title in titles}
            roles = [
                item.model_copy(update={"intent": RoleIntent.DONT_SEED})
                for item in state.roles
                if normalized_key(item.title) not in selected_keys
            ]
            for title in titles:
                role = existing.get(normalized_key(title))
                roles.append(
                    role.model_copy(update={"title": title, "intent": RoleIntent.SEARCH})
                    if role
                    else RoleProposal(
                        role_id=f"role-user-{hashlib.sha256(title.casefold().encode()).hexdigest()[:12]}",
                        title=title,
                        group=RoleGroup.RELATED,
                        intent=RoleIntent.SEARCH,
                        lane=ColdStartLane.ADJACENT_TITLE,
                        source_ids=["user-confirmed-settings"],
                        reason="Explicitly added in Search preferences.",
                    )
                )
            state.roles = roles
            state.location = location
            state.eligibility = (
                state.eligibility.model_copy(update={"intended_country": country})
                if state.eligibility
                else EligibilityAnswers(intended_country=country)
            )
            state.compensation = compensation
            state.status = SetupStatus.ACTIVE
            state.step = SetupStep.COMPLETE
            state.updated_at = datetime.now(UTC).isoformat()

            preferences["desired_title_terms"] = titles
            preferences["accepted_work_modes"] = location.accepted_work_modes
            preferences["accepted_location_terms"] = [
                value.strip() for value in location.accepted_onsite_locations if value.strip()
            ]
            preferences["minimum_salary"] = compensation.minimum
            preferences["preferred_salary"] = compensation.target
            preferences["salary_currency"] = compensation.currency
            preferences["salary_period"] = compensation.period
            preferences["clearance_preference"] = clearance_preference
            preferences["preferred_job_attributes"] = payload.get("preferred_job_attributes", [])
            preferences["avoided_job_attributes"] = payload.get("avoided_job_attributes", [])
            profile = dict(preferences.get("screening_profile") or {})
            profile["intended_work_country"] = country
            profile["remote_location_terms"] = location.remote_location_terms
            preferences["screening_profile"] = profile
            preferences = validate_preferences(preferences)

            config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
            manual_queries = {
                normalized_key(str(value))
                for family in config.get("search", {}).get("families", [])
                if isinstance(family, dict)
                and not str(family.get("name", "")).startswith(MANAGED_FAMILY_PREFIX)
                for value in [family.get("provider_query"), *(family.get("titles") or [])]
                if value
            }
            generated_portfolio = portfolio_from_setup_state(state)
            queries = [
                item
                for item in generated_portfolio.queries
                if normalized_key(item.query) not in manual_queries
            ]
            check_query_capacity(item.query for item in queries)
            portfolio = ColdStartPortfolio(
                generated_at=datetime.now(UTC).isoformat(),
                resume_hash=state.evidence_hash,
                queries=queries,
            )
            config.setdefault("search", {})["location"] = country
            config["search"]["accepted_work_modes"] = location.accepted_work_modes
            preview = preview_activation(portfolio, yaml.safe_dump(config, sort_keys=False))

            atomic_write_text(preferences_path, yaml.safe_dump(preferences, sort_keys=False))
            atomic_write_text(
                self.workspace / PORTFOLIO_PATH, portfolio.model_dump_json(indent=2) + "\n"
            )
            atomic_write_text(config_path, preview.rendered_config)
            save_setup_state(self.workspace, state)
        return self.job_search_preferences()

    def previous_preference_step(self) -> dict[str, Any]:
        state = load_setup_state(self.workspace)
        if state is None or state.status != SetupStatus.IN_PROGRESS:
            raise ValueError("preference setup is not in progress")
        if state.step == SetupStep.ROLES:
            record = self._onboarding_record()
            record["suggestion_choice_session"] = state.session_id
            atomic_write_json(self.workspace / ONBOARDING_STATE_PATH, record)
            return self.onboarding_status()
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

    def career_resumes(self) -> dict[str, Any]:
        from .web_career import list_resumes

        return list_resumes(self.workspace)

    def career_resume_preview(self, resume_id: str) -> dict[str, Any]:
        from .web_career import resolve_resume_preview

        return resolve_resume_preview(self.workspace, resume_id)

    def restore_career_resume(self, resume_id: str) -> dict[str, Any]:
        from .web_career import restore_directional_resume

        with self._state_lock:
            return restore_directional_resume(self.workspace, resume_id)

    def application_resume_preview(self, application_id: str) -> dict[str, Any]:
        from .web_career import resolve_application_resume_preview

        return resolve_application_resume_preview(self.workspace, application_id)

    def job_resume_recommendation(self, job_id: str) -> dict[str, Any]:
        """Resolve existing target, direction, match, and resume artifacts for one job."""
        job = self.get_job(job_id)
        if job is None:
            raise ValueError(f"job not found: {job_id}")
        target_path: Path | None = None
        target_data: dict[str, Any] | None = None
        for candidate in sorted((self.workspace / "targets").glob("*.md")):
            if candidate.name == "README.md":
                continue
            try:
                data, _ = parse_target(candidate)
            except ValueError:
                continue
            same_url = bool(job.get("url") and data.get("source", {}).get("url") == job["url"])
            same_identity = normalized_key(str(data.get("company"))) == normalized_key(
                job["company"]
            ) and normalized_key(str(data.get("role"))) == normalized_key(job["title"])
            if same_url or same_identity:
                target_path, target_data = candidate, data
                break

        baselines = sorted((self.workspace / "resumes" / "baselines").glob("*.md"))
        selected: Path | None = None
        kind: str | None = None
        match_report: Path | None = None
        match_label: str | None = None
        if target_path is not None and (self.workspace / "vault" / "vault.json").is_file():
            report = project_report(self.workspace / "vault", strict=False)
            relative_target = target_path.relative_to(self.workspace).as_posix()
            target_record = next(
                (item for item in report["targets"] if item["path"] == relative_target), None
            )
            if target_record and target_record.get("tailored_resume"):
                selected = self.workspace / target_record["tailored_resume"]
                kind = "tailored"
            else:
                direction = str(target_data.get("direction")) if target_data else ""
                baseline_record = next(
                    (
                        item
                        for item in report["resumes"]
                        if item["kind"] == "baseline" and item.get("direction") == direction
                    ),
                    None,
                )
                if baseline_record:
                    selected = self.workspace / baseline_record["path"]
                    kind = "directional"
            if selected is not None:
                candidate_report = (
                    self.workspace
                    / "build"
                    / "matches"
                    / f"{target_path.stem}--{selected.stem}.json"
                )
                if candidate_report.is_file():
                    match_report = candidate_report
                    try:
                        match_payload = json.loads(candidate_report.read_text(encoding="utf-8"))
                    except (OSError, json.JSONDecodeError):
                        match_payload = {}
                    semantic = match_payload.get("semantic_review")
                    if isinstance(semantic, dict) and isinstance(semantic.get("label"), str):
                        match_label = semantic["label"]
        if selected is None and len(baselines) == 1:
            selected = baselines[0]
            kind = "directional"
        if selected is None:
            saved_screen = (
                self.saved_job_screen(job_id)
                if (self.workspace / PREFERENCES_PATH).is_file()
                and (self.workspace / DEFAULT_AGENT_CONFIG).is_file()
                else None
            )
            screen_payload = saved_screen.get("result") if saved_screen else None
            resume_match = (
                screen_payload.get("resume_match") if isinstance(screen_payload, dict) else None
            )
            if isinstance(resume_match, dict):
                resume_id = resume_match.get("resume_id")
                expected_hash = resume_match.get("sha256")
                candidate = self.workspace / str(resume_id)
                baselines_root = (self.workspace / "resumes" / "baselines").resolve()
                if (
                    isinstance(resume_id, str)
                    and isinstance(expected_hash, str)
                    and candidate.resolve().is_relative_to(baselines_root)
                    and candidate.is_file()
                    and hashlib.sha256(candidate.read_bytes()).hexdigest() == expected_hash
                ):
                    selected = candidate
                    kind = "directional"
                    match_label = str(resume_match.get("label") or "Unknown match")

        if selected is None:
            return {
                "status": "unavailable",
                "recommended_resume": None,
                "target": target_path.relative_to(self.workspace).as_posix()
                if target_path
                else None,
                "match": None,
                "message": "Build a directional resume before attaching one to applications.",
            }
        return {
            "status": "available",
            "recommended_resume": {
                "id": selected.relative_to(self.workspace).as_posix(),
                "name": selected.stem.replace("-", " ").title(),
                "kind": kind,
            },
            "target": target_path.relative_to(self.workspace).as_posix() if target_path else None,
            "match": {"label": match_label or "Unknown match"},
            "match_report": (
                match_report.relative_to(self.workspace).as_posix() if match_report else None
            ),
            "message": None,
        }

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

    def _feedback_events(self) -> list[dict[str, Any]]:
        return load_feedback_events(self.workspace / JOB_FEEDBACK_PATH)

    def _append_feedback_event(
        self,
        job: dict[str, Any],
        action: str,
        reasons: list[str],
        screening: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        event = {
            "id": f"JF-{uuid4()}",
            "action": action,
            "reasons": reasons,
            "created_at": datetime.now(UTC).isoformat(),
            "job": {
                "id": job["id"],
                "title": job["title"],
                "company": job["company"],
                "location": job["location"],
                "work_modes": job["work_modes"],
                "salary_min": job["salary_min"],
                "salary_max": job["salary_max"],
                "salary_currency": job["salary_currency"],
                "traits": extract_preference_traits(job),
                "seniority": extract_seniority(job),
                "description_hash": hashlib.sha256(job["description"].encode()).hexdigest(),
                "screening": screening,
            },
        }
        events = self._feedback_events()
        events.append(event)
        atomic_write_json(
            self.workspace / JOB_FEEDBACK_PATH,
            {"schema_version": 1, "events": events},
        )
        return event

    def _feedback_screen_snapshot(self, job_id: str) -> dict[str, Any] | None:
        if not all(
            (self.workspace / path).is_file()
            for path in (JOBS_CONFIG, PREFERENCES_PATH, DEFAULT_AGENT_CONFIG)
        ):
            return None
        screen = self.saved_job_screen(job_id)
        result = screen.get("result") if isinstance(screen, dict) else None
        if not isinstance(result, dict):
            return None
        labels = {
            str(item.get("criterion_id")): str(item.get("label") or "")
            for item in result.get("criterion_evidence") or []
            if isinstance(item, dict)
        }
        criteria = [
            {
                "label": labels.get(str(item.get("criterion_id")), ""),
                "outcome": str(item.get("outcome") or "unknown"),
            }
            for item in result.get("criterion_assessments") or []
            if isinstance(item, dict) and labels.get(str(item.get("criterion_id")))
        ]
        resume = result.get("resume_match")
        resume_snapshot = (
            {
                key: resume.get(key)
                for key in ("resume_id", "name", "label")
                if resume.get(key) is not None
            }
            if isinstance(resume, dict)
            else None
        )
        return {
            "fit": result.get("fit"),
            "recommendation": result.get("recommendation"),
            "confidence": result.get("confidence"),
            "resume_match": resume_snapshot,
            "criteria": criteria,
        }

    def record_job_open(self, job_id: str) -> None:
        """Record one weak positive signal when the original posting is opened."""
        job = self.get_job(job_id)
        if job is None:
            raise ValueError(f"job not found: {job_id}")
        screening = self._feedback_screen_snapshot(job_id)
        with self._state_lock:
            if any(
                event.get("action") == "opened_posting"
                and isinstance(event.get("job"), dict)
                and event["job"].get("id") == job_id
                for event in self._feedback_events()
            ):
                return
            self._append_feedback_event(job, "opened_posting", [], screening)

    @staticmethod
    def _validated_feedback(action: object, reasons: object) -> tuple[str, list[str]]:
        if not isinstance(action, str) or action not in JOB_FEEDBACK_ACTIONS:
            raise ValueError("unsupported feedback action")
        if not isinstance(reasons, list) or not all(isinstance(item, str) for item in reasons):
            raise ValueError("feedback reasons must be a list of names")
        cleaned = list(dict.fromkeys(reason.strip() for reason in reasons if reason.strip()))
        unknown = set(cleaned) - JOB_FEEDBACK_REASONS
        if unknown:
            raise ValueError("unsupported feedback reason: " + ", ".join(sorted(unknown)))
        if len(cleaned) > 4:
            raise ValueError("choose no more than four feedback reasons")
        return action, cleaned

    def job_feedback(self, job_id: str) -> dict[str, Any]:
        job = self.get_job(job_id)
        if job is None:
            raise ValueError(f"job not found: {job_id}")
        events = self._feedback_events()
        latest = next(
            (
                event
                for event in reversed(events)
                if event.get("action") in JOB_FEEDBACK_ACTIONS
                and isinstance(event.get("job"), dict)
                and event["job"].get("id") == job_id
            ),
            None,
        )
        deterministic: dict[str, Any] = {"interest": {}, "hard_conflicts": []}
        clearance_preference = "neutral"
        if (self.workspace / PREFERENCES_PATH).is_file():
            from .jobs import _load_preferences

            preferences = _load_preferences(self.workspace / PREFERENCES_PATH)
            clearance_preference = str(preferences.get("clearance_preference", "neutral"))
        if (self.workspace / JOBS_CONFIG).is_file():
            packet = self._screening_packet(job_id)
            prescreen = packet.deterministic_prescreen
            constraints = prescreen.get("constraints") if isinstance(prescreen, dict) else None
            deterministic = {
                "interest": prescreen.get("interest", {}) if isinstance(prescreen, dict) else {},
                "hard_conflicts": (
                    constraints.get("hard_conflicts", []) if isinstance(constraints, dict) else []
                ),
                "clearance_requirement": (
                    constraints.get("clearance_requirement", False)
                    if isinstance(constraints, dict)
                    else False
                ),
            }
            screen = self.saved_job_screen(job_id)
        else:
            screen = None
        positive_titles = [
            str(item.get("role") or "") for item in self.list_applications() if item.get("role")
        ]
        score = score_shadow_job(
            {
                **job,
                "active": True,
                "source_order": 0,
                "preference_traits": extract_preference_traits(job),
                "deterministic": deterministic,
                "screening": screen,
            },
            positive_titles=positive_titles,
            clearance_preference=clearance_preference,
            feedback_events=events,
        )
        public_latest = (
            {
                "action": latest["action"],
                "reasons": latest["reasons"],
                "created_at": latest["created_at"],
            }
            if latest
            else None
        )
        return {"job_id": job_id, "latest": public_latest, "personalization": score}

    def record_job_feedback(self, job_id: str, action: object, reasons: object) -> dict[str, Any]:
        normalized_action, normalized_reasons = self._validated_feedback(action, reasons)
        if normalized_action == "applied":
            raise ValueError("applied feedback is recorded by marking the job applied")
        job = self.get_job(job_id)
        if job is None:
            raise ValueError(f"job not found: {job_id}")
        screening = self._feedback_screen_snapshot(job_id)
        with self._state_lock:
            self._append_feedback_event(job, normalized_action, normalized_reasons, screening)
            if normalized_action == "not_interested":
                dismissed = self._dismissed_job_ids()
                dismissed.add(job_id)
                self._write_dismissed_job_ids(dismissed)
        return self.job_feedback(job_id)

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

    def _quick_screen_summaries(self) -> dict[str, dict[str, Any]]:
        path = self.workspace / JOB_SCREENING_OUTPUT
        if not path.is_file():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ValueError(f"invalid job screening output: {path}") from exc
        raw_jobs = payload.get("jobs") if isinstance(payload, dict) else None
        if (
            not isinstance(payload, dict)
            or payload.get("schema_version") != 1
            or not isinstance(raw_jobs, list)
        ):
            raise ValueError(f"invalid job screening output: {path}")
        reason_labels = {
            "hard_constraint_conflict": "Outside required preferences",
            "incomplete_listing": "Incomplete listing",
            "no_saved_search_signal": "Outside saved searches",
        }
        summaries: dict[str, dict[str, Any]] = {}
        for item in raw_jobs:
            if not isinstance(item, dict) or not item.get("id"):
                continue
            screen = item.get("screening")
            if not isinstance(screen, dict) or screen.get("status") not in {
                "complete",
                "skipped",
                "failed",
            }:
                continue
            status = str(screen["status"])
            raw_result = screen.get("result")
            result: dict[str, Any] = raw_result if isinstance(raw_result, dict) else {}
            raw_resume = result.get("resume_match")
            resume: dict[str, Any] = raw_resume if isinstance(raw_resume, dict) else {}
            if status == "complete":
                fit_labels = {
                    "strong_match": "Strong fit",
                    "good_match": "Good fit",
                    "worthwhile_stretch": "Stretch",
                    "weak_fit": "Weak fit",
                    "insufficient_information": "Unknown",
                }
                label = str(resume.get("label") or "").removesuffix(" match") or fit_labels.get(
                    str(result.get("fit")), "Unknown"
                )
            elif status == "skipped":
                label = reason_labels.get(str(screen.get("reason")), "Skipped")
            else:
                label = "Screen unavailable"
            summaries[str(item["id"])] = {
                "status": status,
                "label": label,
                "resume_name": resume.get("name") if status == "complete" else None,
                "generated_at": result.get("generated_at") if status == "complete" else None,
            }
        return summaries

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
            clearanceMode=(
                "exclude"
                if preferences.get("clearance_preference", "neutral") == "exclude"
                else "all"
            ),
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
        screen_summaries = self._quick_screen_summaries()
        jobs: list[dict[str, Any]] = []
        for raw in self._inventory_loader():
            job = self._serialize_job(raw)
            job["quick_screen"] = screen_summaries.get(job["id"])
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
        screen_summaries = self._quick_screen_summaries()
        for raw in self._inventory_loader():
            if str(raw.get("id")) == job_id:
                job = self._serialize_job(raw)
                job["quick_screen"] = screen_summaries.get(job["id"])
                return job
        return None

    def estimate_job_salary(self, job_id: str, *, refresh: bool = False) -> dict[str, Any]:
        """Run only on an explicit estimate request; browsing never calls the model."""
        with self._salary_lock:
            inventory = self._inventory_loader()
            job = next((item for item in inventory if str(item.get("id")) == job_id), None)
            if job is None:
                raise LookupError(f"job not found: {job_id}")
            packet = build_salary_packet(job, inventory)
            estimator = SalaryEstimationService(self.workspace / SALARY_CACHE_PATH)
            if has_posted_salary(packet.job):
                posted, cached = estimator.estimate(packet, adapter=None, model="")
                return {**posted.model_dump(mode="json"), "cached": cached}
            config_path = self.workspace / DEFAULT_AGENT_CONFIG
            config = load_agent_config(config_path) if config_path.is_file() else None
            api_key = self._openrouter_key() if config else ""
            adapter = OpenRouterAdapter(config, api_key=api_key) if config and api_key else None
            result, cached = estimator.estimate(
                packet,
                adapter=adapter,
                model=config.models.fast if config else "",
                refresh=refresh,
            )
            return {**result.model_dump(mode="json"), "cached": cached}

    def saved_job_salary(self, job_id: str) -> dict[str, Any] | None:
        """Return a current saved estimate without invoking the model."""
        with self._salary_lock:
            inventory = self._inventory_loader()
            job = next((item for item in inventory if str(item.get("id")) == job_id), None)
            if job is None:
                raise LookupError(f"job not found: {job_id}")
            packet = build_salary_packet(job, inventory)
            estimator = SalaryEstimationService(self.workspace / SALARY_CACHE_PATH)
            if has_posted_salary(packet.job):
                posted, cached = estimator.estimate(packet, adapter=None, model="")
                return {**posted.model_dump(mode="json"), "cached": cached}
            config_path = self.workspace / DEFAULT_AGENT_CONFIG
            if not config_path.is_file():
                return None
            config = load_agent_config(config_path)
            result = estimator.get(packet, model=config.models.fast)
            return {**result.model_dump(mode="json"), "cached": True} if result else None

    @staticmethod
    def _present_screen(result: Any, *, cached: bool) -> dict[str, Any]:
        fit_labels = {
            "strong_match": "Strong fit",
            "good_match": "Good fit",
            "worthwhile_stretch": "Worthwhile stretch",
            "weak_fit": "Weak fit",
            "insufficient_information": "Not enough information",
        }
        recommendation_labels = {
            "pursue": "Pursue",
            "pursue_as_stretch": "Consider as a stretch",
            "verify_eligibility": "Verify eligibility",
            "needs_more_evidence": "Needs more evidence",
            "deprioritize": "Deprioritize",
            "do_not_apply": "Do not apply",
        }
        payload = result.model_dump(mode="json")
        preference_only = payload.get("model") == "local/deterministic"
        incomplete_screen = (
            not preference_only
            and payload.get("fit") == "insufficient_information"
            and not payload.get("evidence_used")
            and not payload.get("criterion_evidence")
        )
        if payload.get("fit") == "insufficient_information":
            payload["confidence"] = "low"
        violated_codes = {
            str(item.get("code"))
            for item in payload.get("constraints", [])
            if item.get("strength") == "required" and item.get("state") == "violated"
        }
        qualification_codes = {
            "sponsorship",
            "active_clearance",
            "obtain_clearance",
            "clearance",
            "license",
        }
        payload["screening_label"] = "Preference check" if preference_only else "Quick screen"
        payload["fit_label"] = (
            "Fit not evaluated"
            if preference_only
            else "Screen incomplete"
            if incomplete_screen
            else fit_labels[payload["fit"]]
        )
        if incomplete_screen:
            payload["reasoning_summary"] = (
                "This screen did not compare the posting with enough verified career evidence. "
                "Refresh it to run the criteria-based screen. This is not a judgment that you "
                "lack the required experience."
            )
        structured_strengths = payload.get("strengths", [])
        payload["strengths"] = [
            str(item.get("statement"))
            for item in structured_strengths
            if isinstance(item, dict) and item.get("statement")
        ]
        payload["evidence_used"] = [
            {
                "fact_id": item.get("fact_id"),
                "title": item.get("title"),
                "category": item.get("category"),
                "strength": item.get("strength"),
            }
            for item in payload.get("evidence_used", [])
            if isinstance(item, dict)
        ]
        if payload["eligibility"] == "ineligible" and not (violated_codes & qualification_codes):
            payload["eligibility_label"] = "Outside your preferences"
        elif payload["eligibility"] == "ineligible":
            payload["eligibility_label"] = "Eligibility requirement not met"
        elif payload["eligibility"] == "unknown":
            payload["eligibility_label"] = "Eligibility needs review"
        else:
            payload["eligibility_label"] = "Eligible"
        payload["recommendation_label"] = recommendation_labels[payload["recommendation"]]
        assessments = payload.get("preference_assessments", [])
        matches = [item for item in assessments if item.get("outcome") == "match"]
        conflicts = [item for item in assessments if item.get("outcome") == "conflict"]
        unknowns = [item for item in assessments if item.get("outcome") == "unknown"]
        if not assessments:
            preference_label = "No job preferences saved"
        elif matches and conflicts:
            preference_label = "Mixed"
        elif conflicts:
            preference_label = "Probably not for you"
        elif matches:
            preference_label = "Looks aligned"
        else:
            preference_label = "Not enough information"
        payload["preference_fit"] = {
            "label": preference_label,
            "matches": matches[:2],
            "conflicts": conflicts[:2],
            "unknown_count": len(unknowns),
        }
        return {"status": "complete", "cached": cached, "result": payload}

    def _screening_packet(self, job_id: str) -> Any:
        return get_job_screening_packet(
            job_id,
            config_path=self.workspace / JOBS_CONFIG,
            preferences_path=self.workspace / PREFERENCES_PATH,
            workspace=self.workspace,
        )

    def saved_job_screen(self, job_id: str) -> dict[str, Any] | None:
        """Return a cached quick screen without invoking a model."""
        with self._screening_lock:
            packet = self._screening_packet(job_id)
            config_path = self.workspace / DEFAULT_AGENT_CONFIG
            if not config_path.is_file():
                return None
            config = load_agent_config(config_path)
            cache_path = self.workspace / "build/job-search/screening-cache.sqlite"
            cache = ScreeningCache(cache_path)
            packet = enrich_packet_from_cached_interpretation(
                packet,
                model=config.models.fast,
                interpretation_cache=PostingInterpretationCache(cache_path),
                vault_root=self.workspace / "vault",
            )
            result = cache.get(packet, config.models.fast)
            return self._present_screen(result, cached=True) if result else None

    def screen_job(self, job_id: str, *, refresh: bool = False) -> dict[str, Any]:
        """Run the existing bounded job screen after an explicit user request."""
        with self._screening_lock:
            try:
                packet = self._screening_packet(job_id)
            except UnicodeError as exc:
                _raise_screening_input_error(job_id, "screening_packet", exc)
            if packet.eligibility == EligibilityStatus.INELIGIBLE:
                return self._present_screen(deterministic_ineligible_result(packet), cached=False)
            config_path = self.workspace / DEFAULT_AGENT_CONFIG
            if not config_path.is_file() or not self._openrouter_configured():
                raise ValueError("Connect OpenRouter in Settings before screening this job")
            try:
                config = load_agent_config(config_path)
                adapter = OpenRouterAdapter(
                    config,
                    api_key=self._openrouter_key(),
                    timeout_seconds=25,
                    retries=1,
                )
            except UnicodeError as exc:
                _raise_screening_input_error(job_id, "provider_configuration", exc)
            cache_path = self.workspace / "build/job-search/screening-cache.sqlite"
            service = ScreeningService(
                adapter,
                ScreeningCache(cache_path),
                interpretation_service=PostingInterpretationService(
                    adapter, PostingInterpretationCache(cache_path)
                ),
                interpretation_model=config.models.fast,
                vault_root=self.workspace / "vault",
            )
            packet = enrich_packet_from_cached_interpretation(
                packet,
                model=config.models.fast,
                interpretation_cache=PostingInterpretationCache(cache_path),
                vault_root=self.workspace / "vault",
            )
            try:
                result, cached = service.screen(packet, model=config.models.fast, refresh=refresh)
            except UnicodeError as exc:
                _raise_screening_input_error(job_id, "screening_service", exc)
            return self._present_screen(result, cached=cached)

    def mark_not_interested(self, job_id: str) -> None:
        self.record_job_feedback(job_id, "not_interested", [])

    def mark_applied(self, job_id: str) -> dict[str, Any]:
        job = self.get_job(job_id)
        if job is None:
            raise ValueError(f"job not found: {job_id}")
        screening = self._feedback_screen_snapshot(job_id)
        with self._state_lock:
            for _, record in iter_records(self.workspace / APPLICATIONS_ROOT):
                if str(record["application"].get("job_id")) == job_id:
                    return record
            recommendation = self.job_resume_recommendation(job_id)
            resume_record = recommendation.get("recommended_resume")
            resume_path = (
                self.workspace / resume_record["id"] if isinstance(resume_record, dict) else None
            )
            target_value = recommendation.get("target")
            report_value = recommendation.get("match_report")
            match_value = recommendation.get("match")
            record = record_application(
                self.workspace / APPLICATIONS_ROOT,
                self.workspace,
                company=job["company"],
                role=job["title"],
                job_id=job_id,
                application_url=job["url"],
                resume=resume_path,
                target=self.workspace / target_value if isinstance(target_value, str) else None,
                match_report=self.workspace / report_value
                if isinstance(report_value, str)
                else None,
                match_classification=(
                    match_value.get("label") if isinstance(match_value, dict) else None
                ),
            )
            self._append_feedback_event(job, "applied", [], screening)
            return record

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
                    "resume": self._application_resume_view(
                        application.get("resume"), application["id"]
                    ),
                    "resume_attribution": self._resume_attribution(application.get("resume")),
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

    def _application_resume_view(
        self, artifact: object, application_id: str
    ) -> dict[str, Any] | None:
        if not isinstance(artifact, dict) or not isinstance(artifact.get("path"), str):
            return None
        path = Path(artifact["path"])
        kind = "tailored" if path.parts[:2] == ("resumes", "tailored") else "directional"
        snapshot_value = artifact.get("snapshot_path")
        snapshot = (
            (self.workspace / snapshot_value).resolve() if isinstance(snapshot_value, str) else None
        )
        snapshot_root = (self.workspace / APPLICATIONS_ROOT / "resume-snapshots").resolve()
        if snapshot is not None and not snapshot.is_relative_to(snapshot_root):
            snapshot = None
        available = bool(snapshot and snapshot.is_file()) or (self.workspace / path).is_file()
        return {
            "name": path.stem.replace("-", " ").title(),
            "kind": kind,
            "path": artifact["path"],
            "sha256": artifact.get("sha256"),
            "available": available,
            "preview_url": (
                f"/api/applications/{application_id}/resume-preview"
                if snapshot is not None and snapshot.is_file()
                else None
            ),
            "detail": (
                "Tailored for this job" if kind == "tailored" else "Closest directional resume"
            )
            + ("" if available else " · File unavailable"),
        }

    @staticmethod
    def _resume_attribution(artifact: object) -> str:
        if not isinstance(artifact, dict) or not isinstance(artifact.get("path"), str):
            return "not_recorded"
        return "tailored" if artifact["path"].startswith("resumes/tailored/") else "directional"

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
        from .bright_data import bright_data_key, load_bright_data_settings

        bright_data_settings = load_bright_data_settings(self.workspace)
        bright_data_connected = bool(bright_data_key(self.workspace))
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
            },
            {
                "id": "gmail",
                "name": "Gmail",
                "description": "Detect applications and status updates from your inbox.",
                "status": "connected" if gmail_connected else "not_connected",
                "detail": "Read-only access" if gmail_connected else "Not connected",
            },
            {
                "id": "telegram",
                "name": "Telegram",
                "description": "Use the private career assistant from Telegram.",
                "status": "connected" if telegram_configured else "not_connected",
                "detail": "Private bot ready" if telegram_configured else "Not connected",
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
                else ("Webhook key required" if discord_configured else "Not connected"),
            },
            {
                "id": "openrouter",
                "name": "OpenRouter",
                "description": "Power screening and assistant features with your model provider.",
                "status": "connected" if openrouter_connected else "not_connected",
                "detail": "API key available" if openrouter_connected else "API key not available",
            },
            {
                "id": "bright-data",
                "name": "Bright Data",
                "description": "Enrich unresolved LinkedIn jobs with location, pay, and Apply links.",
                "status": "connected"
                if bright_data_connected and bright_data_settings.enabled
                else ("configured" if bright_data_connected else "not_connected"),
                "detail": (
                    f"On · up to {bright_data_settings.max_records_per_refresh} per refresh"
                    if bright_data_connected and bright_data_settings.enabled
                    else ("Connected · Off" if bright_data_connected else "Not connected")
                ),
                "settings": {
                    "enabled": bright_data_settings.enabled,
                    "max_records_per_refresh": bright_data_settings.max_records_per_refresh,
                },
            },
        ]
