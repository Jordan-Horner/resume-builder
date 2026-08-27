from __future__ import annotations

import hashlib
import html
import re
from datetime import UTC, datetime
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from bs4 import BeautifulSoup

TRACKING_KEYS = {
    "lever-source",
    "ref",
    "refid",
    "source",
    "trackingid",
    "trk",
    "utm_campaign",
    "utm_medium",
    "utm_source",
}


def clean_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", html.unescape(value or "")).strip()


def html_to_text(value: str | None) -> str:
    if not value:
        return ""
    soup = BeautifulSoup(value, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    return "\n".join(line.strip() for line in soup.get_text("\n").splitlines() if line.strip())


def canonical_url(value: str | None) -> str:
    if not value:
        return ""
    try:
        parts = urlsplit(value.strip())
    except ValueError:
        return ""
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        return ""
    query = [
        (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k.lower() not in TRACKING_KEYS
    ]
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, urlencode(query), ""))


def normalized_key(value: str | None) -> str:
    text = clean_text(value).lower()
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def description_hash(text: str) -> str:
    normalized = normalized_key(text)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest() if normalized else ""


def parse_datetime(value: object) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, (int, float)):
        seconds = float(value) / 1000 if float(value) > 10_000_000_000 else float(value)
        dt = datetime.fromtimestamp(seconds, tz=UTC)
    else:
        raw = str(value).strip().replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(raw)
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)
