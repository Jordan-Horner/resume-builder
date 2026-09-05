"""Conservative country aliases for location fields, never free-form prose."""

from __future__ import annotations

import re
from collections.abc import Sequence

_US = re.compile(
    r"(?<!\w)(?:united\s+states(?:\s+of\s+america)?|u\.?s\.?a\.?|u\.?s\.?)(?!\w)",
    re.IGNORECASE,
)
_TOKEN = re.compile(r"[^\W_]+", re.UNICODE)

# Require a city/comma or trailing ZIP context for two-letter state codes.
# Bare CA, IN, OR, etc. are not reliable country evidence.
_US_STATE_CODES = "AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY DC"
_US_CITY_STATE = re.compile(
    r",\s*(?:"
    + "|".join(_US_STATE_CODES.split())
    + r")(?:\s+\d{5}(?:-\d{4})?)?(?=\s*(?:$|[·;(/]))",
    re.IGNORECASE,
)
_STATE_NAMES = "Alabama|Alaska|Arizona|Arkansas|California|Colorado|Connecticut|Delaware|Florida|Georgia|Hawaii|Idaho|Illinois|Indiana|Iowa|Kansas|Kentucky|Louisiana|Maine|Maryland|Massachusetts|Michigan|Minnesota|Mississippi|Missouri|Montana|Nebraska|Nevada|New Hampshire|New Jersey|New Mexico|New York|North Carolina|North Dakota|Ohio|Oklahoma|Oregon|Pennsylvania|Rhode Island|South Carolina|South Dakota|Tennessee|Texas|Utah|Vermont|Virginia|Washington|West Virginia|Wisconsin|Wyoming|District of Columbia"
_STATES = dict(zip(_US_STATE_CODES.split(), _STATE_NAMES.split("|"), strict=True))


def matches_local_location(location: str, query: str) -> bool | None:
    """Expand state names/codes only for local narrowing, not country inference."""
    key = location_key(query)
    for code, name in _STATES.items():
        if key in {code.lower(), name.lower()}:
            if matching_location_terms(location, [name]):
                return True
            if re.search(r",\s*" + code + r"(?=\s*(?:$|\d|[·;(/]))", location, re.IGNORECASE):
                return True
            if location.strip().upper() == code:
                return True
    return matches_search_location(location, query)


def matches_search_location(location: str, query: str, country: str = "") -> bool | None:
    """Match US aliases and city/state context without treating Remote as US."""
    if not query.strip():
        return True
    if not country.strip() and location_key(location) in {
        "",
        "remote",
        "location not listed",
        "worldwide",
        "global",
        "anywhere",
    }:
        return None
    if location_key(query) == "united states" and country.strip():
        return location_key(country) == "united states"
    if matching_location_terms(location, [query]):
        return True
    if location_key(query) == "united states":
        if _US_CITY_STATE.search(location) or matching_location_terms(
            location, [name for name in _STATES.values() if name != "Georgia"]
        ):
            return True
        # Reuse the scraper's country vocabulary; absence of US evidence is
        # not evidence of a foreign country (e.g. a bare city from an ATS).
        from jobspy.model import Country

        foreign_names = [item.value[0] for item in Country if item.name != "USA"]
        if matching_location_terms(location, [*foreign_names, "UK", "United Kingdom"]):
            return False
        if re.search(
            r",\s*(?:ON|QC|BC|AB|MB|NB|NL|NS|NT|NU|PE|SK|YT)(?=\s*(?:$|[;(]))",
            location,
            re.IGNORECASE,
        ):
            return False
        return None
    return bool(country and location_key(country) == location_key(query))


def location_key(value: str) -> str:
    """Normalize explicit US aliases without guessing countries from cities."""
    return " ".join(_TOKEN.findall(_US.sub("United States", value).casefold()))


def matching_location_terms(value: str, terms: Sequence[str]) -> list[str]:
    """Return original matching terms, with whole-token boundaries and aliases."""
    normalized = f" {location_key(value)} "
    matches: list[str] = []
    seen: set[str] = set()
    for term in terms:
        key = location_key(term)
        if key and key not in seen and f" {key} " in normalized:
            matches.append(term)
            seen.add(key)
    return matches
