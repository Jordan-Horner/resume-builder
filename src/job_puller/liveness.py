from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx

DIRECT_PROVIDERS = {
    "ashby",
    "greenhouse",
    "jazzhr",
    "lever",
    "rippling",
    "smartrecruiters",
    "workday",
}


def verify_job_liveness(
    job: dict[str, Any],
    timeout_seconds: float,
    *,
    transport: httpx.BaseTransport | None = None,
) -> dict[str, object]:
    """Conservatively verify direct ATS URLs without guessing from page copy."""
    checked_at = datetime.now(UTC).isoformat()
    url = str(job.get("url") or "")
    providers = {str(value) for value in job.get("providers", [])}
    base: dict[str, object] = {
        "checked_at": checked_at,
        "url": url,
        "final_url": url,
        "http_status": None,
    }
    if not url:
        return {**base, "status": "inconclusive", "reason": "job has no application URL"}
    if not providers & DIRECT_PROVIDERS:
        return {
            **base,
            "status": "inconclusive",
            "reason": "URL is not backed by a configured direct ATS source",
        }
    try:
        with httpx.Client(
            follow_redirects=True,
            timeout=timeout_seconds,
            transport=transport,
            headers={"User-Agent": "resume-builder-liveness/1"},
        ) as client:
            response = client.get(url)
    except httpx.HTTPError as exc:
        return {
            **base,
            "status": "inconclusive",
            "reason": f"request failed: {type(exc).__name__}",
        }
    final_url = str(response.url)
    result = {**base, "final_url": final_url, "http_status": response.status_code}
    if response.status_code in {401, 403, 429}:
        return {**result, "status": "blocked", "reason": "ATS refused the verification request"}
    if response.status_code in {404, 410}:
        return {**result, "status": "closed", "reason": "direct ATS URL is no longer available"}
    if 200 <= response.status_code < 400:
        redirected = final_url.rstrip("/") != url.rstrip("/")
        return {
            **result,
            "status": "redirected" if redirected else "open",
            "reason": "direct ATS URL resolved successfully",
        }
    return {
        **result,
        "status": "inconclusive",
        "reason": "ATS returned an unexpected response",
    }
