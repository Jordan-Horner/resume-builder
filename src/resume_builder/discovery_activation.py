"""Review and explicitly activate a cold-start discovery portfolio."""

from __future__ import annotations

import difflib
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

from job_puller.config import InventoryConfig
from job_puller.normalize import normalized_key

from .atomic import atomic_write_text
from .discovery_evidence import TitlePosture
from .discovery_portfolio import ColdStartLane, ColdStartPortfolio, ColdStartQuery

MANAGED_FAMILY_PREFIX = "resume-discovery-"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DiscoveryActivationRecord(StrictModel):
    schema_version: Literal[1] = 1
    activated_at: str
    portfolio_path: str
    portfolio_hash: str
    config_path: str
    before_hash: str
    after_hash: str
    backup_path: str
    backup_hash: str
    enabled_query_ids: list[str] = Field(min_length=1)


class DiscoveryActivationPreview(StrictModel):
    confirmation_hash: str
    before_hash: str
    after_hash: str
    enabled_query_ids: list[str]
    added_families: list[str]
    replaced_families: list[str]
    unified_diff: str
    rendered_config: str


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def load_portfolio(path: Path) -> ColdStartPortfolio:
    return ColdStartPortfolio.model_validate_json(path.read_text(encoding="utf-8"))


def save_portfolio(path: Path, portfolio: ColdStartPortfolio) -> None:
    atomic_write_text(path, portfolio.model_dump_json(indent=2) + "\n")


def edit_portfolio(
    portfolio: ColdStartPortfolio,
    *,
    operation: Literal["enable", "disable", "remove", "add"],
    query_id: str | None = None,
    query: str | None = None,
    lane: ColdStartLane | None = None,
) -> ColdStartPortfolio:
    """Apply one explicit, locally validated portfolio edit."""
    items = [item.model_copy(deep=True) for item in portfolio.queries]
    if operation == "add":
        if query is None or lane is None:
            raise ValueError("add requires query and lane")
        if lane == ColdStartLane.HISTORICAL_TITLE:
            raise ValueError("historical titles can only come from resume evidence")
        posture = (
            TitlePosture.EXPLORATORY
            if lane == ColdStartLane.EXPLORATION
            else TitlePosture.ADJACENT
            if lane == ColdStartLane.ADJACENT_TITLE
            else None
        )
        digest = hashlib.sha256(f"{lane.value}\n{query.casefold().strip()}".encode()).hexdigest()[
            :12
        ]
        items.append(
            ColdStartQuery(
                query_id=f"user-{lane.value}-{digest}",
                lane=lane,
                query=query,
                source_ids=["user-explicit"],
                reason="Explicitly added during discovery portfolio review.",
                posture=posture,
            )
        )
    else:
        if not query_id:
            raise ValueError(f"{operation} requires query_id")
        matches = [item for item in items if item.query_id == query_id]
        if not matches:
            raise ValueError(f"portfolio query not found: {query_id}")
        if operation == "remove":
            items = [item for item in items if item.query_id != query_id]
        else:
            matches[0].enabled = operation == "enable"
    payload = portfolio.model_dump(mode="json")
    payload["queries"] = [item.model_dump(mode="json") for item in items]
    return ColdStartPortfolio.model_validate(payload)


def _family_for(query: ColdStartQuery) -> dict[str, object]:
    family: dict[str, object] = {
        "name": f"{MANAGED_FAMILY_PREFIX}{query.query_id}",
        "enabled": True,
        "titles": [query.query],
    }
    if query.lane == ColdStartLane.CAPABILITY_COMBINATION:
        family.update(
            {
                "provider_query": query.query,
                "commercial_admission": "query_result",
                "commercial_only": True,
            }
        )
    return family


def preview_activation(
    portfolio: ColdStartPortfolio, config_text: str
) -> DiscoveryActivationPreview:
    """Compile a portfolio while preserving every non-family search and provider setting."""
    payload = yaml.safe_load(config_text)
    if not isinstance(payload, dict):
        raise ValueError("search configuration must be a mapping")
    InventoryConfig.model_validate(payload)
    existing = payload.get("search", {}).get("families", [])
    if not isinstance(existing, list):
        raise ValueError("search.families must be a list")
    replaced = [
        str(item.get("name"))
        for item in existing
        if isinstance(item, dict) and str(item.get("name", "")).startswith(MANAGED_FAMILY_PREFIX)
    ]
    retained = [
        item
        for item in existing
        if not (
            isinstance(item, dict) and str(item.get("name", "")).startswith(MANAGED_FAMILY_PREFIX)
        )
    ]
    enabled = [item for item in portfolio.queries if item.enabled]
    manual_queries = {
        normalized_key(str(value))
        for family in retained
        if isinstance(family, dict)
        for value in [family.get("provider_query"), *(family.get("titles") or [])]
        if value
    }
    duplicates = [item.query for item in enabled if normalized_key(item.query) in manual_queries]
    if duplicates:
        raise ValueError(
            "portfolio queries duplicate manual search families: " + ", ".join(duplicates)
        )
    families = [*retained, *(_family_for(item) for item in enabled)]
    payload.setdefault("search", {})["families"] = families
    payload["enabled"] = True
    InventoryConfig.model_validate(payload)
    rendered = yaml.safe_dump(payload, sort_keys=False, allow_unicode=True)
    diff = "".join(
        difflib.unified_diff(
            config_text.splitlines(keepends=True),
            rendered.splitlines(keepends=True),
            fromfile="active-search.yml",
            tofile="proposed-search.yml",
        )
    )
    before_hash = _hash_text(config_text)
    after_hash = _hash_text(rendered)
    confirmation = _hash_text(
        json.dumps(
            {
                "before_hash": before_hash,
                "after_hash": after_hash,
                "portfolio": portfolio.model_dump(mode="json"),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return DiscoveryActivationPreview(
        confirmation_hash=confirmation,
        before_hash=before_hash,
        after_hash=after_hash,
        enabled_query_ids=[item.query_id for item in enabled],
        added_families=[str(item["name"]) for item in families[len(retained) :]],
        replaced_families=replaced,
        unified_diff=diff,
        rendered_config=rendered,
    )


def activate_portfolio(
    portfolio_path: Path,
    config_path: Path,
    backup_path: Path,
    record_path: Path,
    confirmation_hash: str,
) -> DiscoveryActivationRecord:
    portfolio_path = portfolio_path.resolve()
    config_path = config_path.resolve()
    backup_path = backup_path.resolve()
    record_path = record_path.resolve()
    portfolio = load_portfolio(portfolio_path)
    before = config_path.read_text(encoding="utf-8")
    preview = preview_activation(portfolio, before)
    if confirmation_hash != preview.confirmation_hash:
        raise ValueError("activation confirmation hash does not match the current proposal")
    if backup_path.exists() or record_path.exists():
        raise ValueError("activation backup or record already exists; choose a new output path")
    atomic_write_text(backup_path, before)
    record = DiscoveryActivationRecord(
        activated_at=datetime.now(UTC).isoformat(),
        portfolio_path=str(portfolio_path),
        portfolio_hash=_hash_text(portfolio_path.read_text(encoding="utf-8")),
        config_path=str(config_path),
        before_hash=preview.before_hash,
        after_hash=preview.after_hash,
        backup_path=str(backup_path),
        backup_hash=_hash_text(before),
        enabled_query_ids=preview.enabled_query_ids,
    )
    try:
        atomic_write_text(config_path, preview.rendered_config)
        atomic_write_text(record_path, record.model_dump_json(indent=2) + "\n")
    except Exception:
        if (
            config_path.is_file()
            and _hash_text(config_path.read_text(encoding="utf-8")) == preview.after_hash
        ):
            atomic_write_text(config_path, before)
        record_path.unlink(missing_ok=True)
        backup_path.unlink(missing_ok=True)
        raise
    return record


def rollback_activation(record_path: Path, confirmation_hash: str) -> DiscoveryActivationRecord:
    record = DiscoveryActivationRecord.model_validate_json(record_path.read_text(encoding="utf-8"))
    config_path = Path(record.config_path)
    backup_path = Path(record.backup_path)
    current = config_path.read_text(encoding="utf-8")
    backup = backup_path.read_text(encoding="utf-8")
    if _hash_text(current) != record.after_hash:
        raise ValueError("active search configuration changed after activation; refusing rollback")
    if _hash_text(backup) != record.backup_hash:
        raise ValueError("activation backup hash mismatch")
    expected = _hash_text(f"rollback\n{record.after_hash}\n{record.before_hash}")
    if confirmation_hash != expected:
        raise ValueError(f"rollback confirmation hash does not match; expected {expected}")
    atomic_write_text(config_path, backup)
    return record


def rollback_confirmation(record: DiscoveryActivationRecord) -> str:
    return _hash_text(f"rollback\n{record.after_hash}\n{record.before_hash}")
