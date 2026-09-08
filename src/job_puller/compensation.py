"""Extract plausible currency ranges from job descriptions."""

from __future__ import annotations

import re
from dataclasses import dataclass

AMOUNT = r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"

DOLLAR_RANGE = re.compile(
    r"(?P<currency>CA\$|C\$|US\$|\$|€|£)\s*"
    rf"(?P<minimum>{AMOUNT})\s*(?P<minimum_k>[kK])?\s*"
    r"(?:-|\u2013|\u2014|to)\s*"
    r"(?:(?P<second_currency>CA\$|C\$|US\$|\$|€|£)\s*)?"
    rf"(?P<maximum>{AMOUNT})\s*(?P<maximum_k>[kK])?\s*"
    r"(?:(?P<interval>per\s+(?:year|annum|hour|month|week|day)|"
    r"annually|yearly|hourly|monthly|weekly|daily|/(?:year|yr|hour|hr|month|week|day))|"
    r"(?P<base_salary>base\s+salary))?\b",
    re.IGNORECASE,
)

ISO_SUFFIX_ANNUAL_RANGE = re.compile(
    r"\b(?:base\s+)?(?:salary|pay|compensation)(?:\s+range)?\b[^\d\n]{0,80}"
    rf"(?P<minimum>{AMOUNT})\s*"
    r"(?P<currency>USD|CAD|EUR|GBP)\s*"
    r"(?:-|\u2013|\u2014|to)\s*"
    rf"(?P<maximum>{AMOUNT})\s*"
    r"(?P<second_currency>USD|CAD|EUR|GBP)\b",
    re.IGNORECASE,
)

MALFORMED_LABELED_ANNUAL_MINIMUM = re.compile(
    r"\b(?:base\s+)?salary\s+range\b[^$\n]{0,80}"
    r"(?P<currency>CA\$|C\$|US\$|\$|€|£)\s*"
    r"(?P<minimum>\d{2,3},\d{2})\s*"
    r"(?:-|\u2013|\u2014|to)\s*"
    r"(?:(?P<second_currency>CA\$|C\$|US\$|\$|€|£)\s*)?"
    r"(?P<maximum>\d{1,3}(?:,\d{3})+)(?:\.\d+)?\b",
    re.IGNORECASE,
)

CURRENCIES = {
    "$": "USD",
    "US$": "USD",
    "CA$": "CAD",
    "C$": "CAD",
    "€": "EUR",
    "£": "GBP",
}


@dataclass(frozen=True, slots=True)
class CompensationRange:
    minimum: float
    maximum: float
    currency: str
    interval: str


def _amount(value: str, compact: str | None) -> float:
    amount = float(value.replace(",", ""))
    return amount * 1_000 if compact else amount


def _interval(value: str) -> str:
    normalized = value.casefold().replace("/", "").replace("per ", "").strip()
    if normalized in {"year", "yr", "annum", "annually", "yearly"}:
        return "yearly"
    if normalized in {"hour", "hr", "hourly"}:
        return "hourly"
    if normalized in {"month", "monthly"}:
        return "monthly"
    if normalized in {"week", "weekly"}:
        return "weekly"
    return "daily"


def _repair_labeled_annual_minimum(description: str) -> str:
    """Repair one missing trailing zero in an otherwise plausible labeled range."""
    for match in MALFORMED_LABELED_ANNUAL_MINIMUM.finditer(description):
        currency_symbol = match.group("currency").upper()
        second_symbol = (match.group("second_currency") or currency_symbol).upper()
        if CURRENCIES[currency_symbol] != CURRENCIES[second_symbol]:
            continue
        repaired_minimum = f"{match.group('minimum')}0"
        minimum = _amount(repaired_minimum, None)
        maximum = _amount(match.group("maximum"), None)
        if 10_000 <= minimum <= maximum <= 2_000_000:
            start, end = match.span("minimum")
            return f"{description[:start]}{repaired_minimum}{description[end:]}"
    return description


def extract_compensation_range(description: str) -> CompensationRange | None:
    """Return the first plausible range, inferring annual periods from annual-sized amounts."""
    description = _repair_labeled_annual_minimum(description)
    for match in DOLLAR_RANGE.finditer(description):
        minimum = _amount(match.group("minimum"), match.group("minimum_k"))
        maximum = _amount(match.group("maximum"), match.group("maximum_k"))
        interval_value = match.group("interval")
        if interval_value:
            interval = _interval(interval_value)
        elif match.group("base_salary") or minimum >= 10_000:
            interval = "yearly"
        else:
            continue
        bounds = {
            "yearly": (10_000, 2_000_000),
            "hourly": (5, 2_000),
            "monthly": (500, 200_000),
            "weekly": (100, 50_000),
            "daily": (25, 20_000),
        }[interval]
        if minimum > maximum or minimum < bounds[0] or maximum > bounds[1]:
            continue
        currency_symbol = match.group("currency").upper()
        second_symbol = (match.group("second_currency") or currency_symbol).upper()
        if CURRENCIES[currency_symbol] != CURRENCIES[second_symbol]:
            continue
        return CompensationRange(minimum, maximum, CURRENCIES[currency_symbol], interval)
    for match in ISO_SUFFIX_ANNUAL_RANGE.finditer(description):
        minimum = _amount(match.group("minimum"), None)
        maximum = _amount(match.group("maximum"), None)
        currency = match.group("currency").upper()
        if (
            currency == match.group("second_currency").upper()
            and 10_000 <= minimum <= maximum <= 2_000_000
        ):
            return CompensationRange(minimum, maximum, currency, "yearly")
    return None
