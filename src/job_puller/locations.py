"""Conservative country aliases for location fields, never free-form prose."""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Sequence

from geotext import GeoText

_US = re.compile(
    r"(?<!\w)(?:united\s+states(?:\s+of\s+america)?|u\.?s\.?a\.?|u\.?s\.?)(?!\w)",
    re.IGNORECASE,
)
_TOKEN = re.compile(r"[^\W_]+", re.UNICODE)

# Require a city/comma or trailing ZIP context for two-letter state codes.
# Bare CA, IN, OR, etc. are not reliable country evidence.
_US_STATE_CODES = "AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY DC"
_US_CITY_STATE = re.compile(
    r"(?:,\s*|(?<=\s))(?:"
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


# GeoText's ~22k-city gazetteer includes many very short entries (e.g. "Bay",
# a small town in the Philippines) that collide with ordinary English words
# ("SF Bay area"). Country names are already full proper nouns and don't need
# this guard; only bare city matches do.
_MIN_RELIABLE_CITY_LENGTH = 4


# GeoText's city regex only matches Title Case words, so an ATS field that
# posts in ALL CAPS (or, rarer, all lowercase) yields zero candidates even
# when the place name itself is in the gazetteer (e.g. "HUN - BU - BUDAPEST").
def _title_cased(location: str) -> str | None:
    if location.isupper() or location.islower():
        return location.title()
    return None


# A leading "Greater "/"Metro(politan) " or trailing descriptor word glues
# onto the city name as one capitalized phrase GeoText can't match as a
# whole ("Metro Manila"), even though the city alone ("Manila") is in the
# gazetteer. A single-word city name is especially exposed to this: GeoText's
# regex only allows one space before it starts merging words into one
# candidate, so a *one-word* city (Boston) swallows a following word
# (Office) into a non-matching compound, while a two-word city (San
# Francisco) already used its one allowed space and stays separate.
_AREA_PREFIX = re.compile(r"^(?:greater|metro(?:politan)?)\s+", re.IGNORECASE)
_AREA_SUFFIX = re.compile(
    r"\s+(?:metro(?:politan)?\s+area|metro(?:politan)?|region|area|office)$", re.IGNORECASE
)


def _area_descriptors_stripped(location: str) -> str | None:
    stripped = _AREA_SUFFIX.sub("", _AREA_PREFIX.sub("", location))
    return stripped if stripped != location else None


# Defaulting an unrecognized location to "not US" (see matches_search_location)
# means an informal hub abbreviation nothing else here resolves can now wrongly
# exclude an obviously-domestic posting. Found on real data: "SF Bay area" has
# no comma/state context and "Bay" alone is filtered out as unreliable, so
# nothing else here would ever recognize it as San Francisco.
_HUB_ALIASES = {"sf": "San Francisco"}
_HUB_ALIAS_RE = re.compile(r"(?<!\w)(?:" + "|".join(_HUB_ALIASES) + r")(?!\w)", re.IGNORECASE)


def _hub_aliases_expanded(location: str) -> str | None:
    expanded = _HUB_ALIAS_RE.sub(lambda match: _HUB_ALIASES[match.group().lower()], location)
    return expanded if expanded != location else None


def _geocoded_country(location: str) -> str | None:
    """Infer an ISO country code from a bare place name (e.g. "Bangalore").

    Only reached once the explicit US/foreign vocabulary above found no
    evidence either way. The caller never needs to know *which* foreign
    country a posting is in, only whether it's confidently US, so this
    doesn't try to be exhaustive about foreign names (no alias list to
    maintain); an unrecognized or unresolved place is `None` here and the
    caller treats that as "not US" by default. The one thing still worth
    getting right is not letting an incidental US-city homonym win over
    stronger, repeated evidence elsewhere in the same string (majority vote,
    below) — that's the only way a real false exclusion could slip in.
    """
    candidates = [location]
    for transform in (_title_cased, _area_descriptors_stripped, _hub_aliases_expanded):
        variant = transform(location)
        if variant and variant not in candidates:
            candidates.append(variant)
    codes: list[str] = []
    for candidate in candidates:
        places = GeoText(candidate)
        reliable_cities = [city for city in places.cities if len(city) >= _MIN_RELIABLE_CITY_LENGTH]
        codes += [GeoText.index.countries[name.lower()] for name in places.countries]
        codes += [GeoText.index.cities[city.lower()] for city in reliable_cities]
    if not codes:
        return None
    # Majority vote, same as GeoText's own `country_mentions`: a location
    # naming its region twice ("San Francisco de Heredia, Heredia, cr")
    # should not lose to a single incidental match ("San Francisco").
    return Counter(codes).most_common(1)[0][0]


def matches_search_location(location: str, query: str, country: str = "") -> bool | None:
    """Match US aliases and city/state context without treating Remote as US."""
    if not query.strip():
        return True
    # A work-arrangement or continent-level label with no city, state, or
    # country carries no geography either way — a data gap, not evidence the
    # job is foreign — so it stays unresolved rather than defaulting to
    # excluded like other unrecognized (but real) place names below.
    if not country.strip() and location_key(location) in {
        "",
        "remote",
        "hybrid",
        "in office",
        "location not listed",
        "worldwide",
        "global",
        "anywhere",
        "americas",
    }:
        return None
    if location_key(query) == "united states" and country.strip():
        return location_key(country) == "united states"
    if matching_location_terms(location, [query]):
        return True
    if location_key(query) == "united states":
        # A bare "Georgia" also names a country, but on a US-market job board
        # it overwhelmingly means the state; a State name is reliable enough
        # US evidence on its own that it doesn't need the majority-vote
        # tie-break below.
        if _US_CITY_STATE.search(location) or matching_location_terms(
            location, list(_STATES.values())
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
        # A location that names some real place but never positively reads as
        # US is treated as not US — this function only needs to recognize US
        # locations, not catalog every other country.
        return _geocoded_country(location) == "US"
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
