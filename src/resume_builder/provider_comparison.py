"""Same-window, canonical-delta comparison for commercial job providers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from job_puller.database import InventoryDatabase

from .atomic import atomic_write_json, atomic_write_text

SCHEMA_VERSION = 1
USEFUL_RECOMMENDATIONS = {"pursue", "pursue_as_stretch"}


@dataclass(frozen=True)
class ProviderComparison:
    payload: dict[str, Any]
    markdown: str


def _screen_results(path: Path | None) -> dict[str, dict[str, Any]]:
    if path is None or not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    results: dict[str, dict[str, Any]] = {}
    for item in payload.get("jobs", []):
        if not isinstance(item, dict):
            continue
        screen = item.get("screening")
        if isinstance(screen, dict) and screen.get("status") == "complete":
            result = screen.get("result")
            if isinstance(result, dict):
                results[str(item.get("id") or "")] = result
    return results


def compare_providers(
    database: InventoryDatabase,
    *,
    manifest_path: Path,
    screening_path: Path | None = None,
    providers: tuple[str, str] = ("linkedin", "indeed"),
) -> ProviderComparison:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("status") in {"in_progress", "processing"}:
        raise ValueError("latest refresh is still running; provider comparison would be incomplete")
    started_raw = manifest.get("started_at")
    completed_raw = manifest.get("completed_at")
    if not isinstance(started_raw, str) or not isinstance(completed_raw, str):
        raise ValueError("latest refresh does not contain a complete comparison window")
    runs = [item for item in manifest.get("provider_runs", []) if isinstance(item, dict)]
    coverage: dict[str, list[dict[str, Any]]] = {
        provider: [run for run in runs if run.get("provider") == provider] for provider in providers
    }
    missing = [provider for provider, values in coverage.items() if not values]
    unhealthy = [
        provider
        for provider, values in coverage.items()
        if values
        and not any(
            run.get("outcome") in {"healthy", "healthy-empty", "capped"}
            or (run.get("success") is True and not run.get("suspicious_empty"))
            for run in values
        )
    ]
    started = datetime.fromisoformat(started_raw)
    completed = datetime.fromisoformat(completed_raw)
    observations = database.provider_window_jobs(started, completed, set(providers))
    by_provider = {
        provider: {
            str(item["job_id"]): item for item in observations if item.get("provider") == provider
        }
        for provider in providers
    }
    left, right = providers
    left_ids, right_ids = set(by_provider[left]), set(by_provider[right])
    shared = left_ids & right_ids
    screen_results = _screen_results(screening_path)

    def metrics(provider: str, other_ids: set[str]) -> dict[str, Any]:
        jobs = by_provider[provider]
        ids = set(jobs)
        evaluated = ids & set(screen_results)
        useful = {
            job_id
            for job_id in evaluated
            if screen_results[job_id].get("recommendation") in USEFUL_RECOMMENDATIONS
        }
        unique = ids - other_ids
        return {
            "canonical_jobs": len(ids),
            "shared_jobs": len(ids & other_ids),
            "unique_jobs": len(unique),
            "complete_description_jobs": sum(
                bool(item.get("complete_description")) for item in jobs.values()
            ),
            "jobs_with_posted_at": sum(bool(item.get("has_posted_at")) for item in jobs.values()),
            "jobs_with_location": sum(bool(item.get("has_location")) for item in jobs.values()),
            "semantically_evaluated_jobs": len(evaluated),
            "useful_evaluated_jobs": len(useful),
            "useful_unique_jobs": len(useful & unique),
            "unique_job_ids": sorted(unique),
            "useful_unique_job_ids": sorted(useful & unique),
        }

    provider_metrics = {
        left: metrics(left, right_ids),
        right: metrics(right, left_ids),
    }
    policy_frozen = bool(manifest.get("search_config_hash") and manifest.get("preference_hash"))
    valid = not missing and not unhealthy and policy_frozen
    limitations = []
    if missing:
        limitations.append(f"Missing provider coverage: {', '.join(missing)}.")
    if unhealthy:
        limitations.append(f"Unhealthy provider coverage: {', '.join(unhealthy)}.")
    if not policy_frozen:
        limitations.append(
            "The refresh predates policy hashes, so equal search and preference inputs cannot be proven."
        )
    if not screen_results:
        limitations.append("No semantic screening artifact was available; relevance is ungraded.")
    elif not ((left_ids | right_ids) & set(screen_results)):
        limitations.append(
            "The available semantic screens do not cover jobs in this provider window; relevance is ungraded."
        )
    limitations.append(
        "Counts measure canonical jobs observed in this window; they do not prove exhaustive recall."
    )
    payload = {
        "schema_version": SCHEMA_VERSION,
        "status": "valid_observation" if valid else "invalid_or_incomplete",
        "window": {"started_at": started_raw, "completed_at": completed_raw},
        "providers": provider_metrics,
        "shared_canonical_jobs": len(shared),
        "search_config_hash": manifest.get("search_config_hash"),
        "preference_hash": manifest.get("preference_hash"),
        "policy_frozen": policy_frozen,
        "limitations": limitations,
        "decision_rule": (
            "Compare useful unique jobs after canonical deduplication; raw provider volume alone "
            "does not establish quality or recall."
        ),
    }
    lines = [
        "# LinkedIn and Indeed Same-Window Comparison",
        "",
        f"Status: {payload['status']}",
        f"Window: {started_raw} to {completed_raw}",
        "",
        "| Provider | Canonical | Shared | Unique | Evaluated useful | Useful unique |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for provider in providers:
        item = provider_metrics[provider]
        lines.append(
            f"| {provider.title()} | {item['canonical_jobs']} | {item['shared_jobs']} | "
            f"{item['unique_jobs']} | {item['useful_evaluated_jobs']} | "
            f"{item['useful_unique_jobs']} |"
        )
    lines.extend(("", "## Limitations", ""))
    lines.extend(f"- {item}" for item in limitations)
    return ProviderComparison(payload=payload, markdown="\n".join(lines) + "\n")


def write_provider_comparison(comparison: ProviderComparison, output_path: Path) -> None:
    atomic_write_json(output_path, comparison.payload)
    atomic_write_text(output_path.with_suffix(".md"), comparison.markdown)
