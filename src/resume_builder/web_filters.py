"""Inventory viewing filters, independent from collection configuration."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from job_puller.locations import matches_local_location, matches_search_location

FilterTerm = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class ViewFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")
    roles: list[FilterTerm] = Field(default_factory=list, max_length=22)
    workModes: list[Literal["remote", "hybrid", "onsite"]] = Field(default_factory=list)
    country: str = Field(default="", max_length=100)
    locations: list[FilterTerm] = Field(default_factory=list, max_length=50)
    employmentTypes: list[Literal["fulltime", "parttime", "contract", "temporary"]] = Field(
        default_factory=list
    )
    minimumPay: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    currency: str = Field(default="USD", pattern=r"^[A-Z]{3}$")
    period: Literal["year", "hour"] = "year"
    includeUnknownPay: bool = True
    includeUnknownMode: bool = True
    includeUnmatchedLocation: bool = False


def matches_view(job: dict[str, Any], filters: ViewFilters) -> bool:
    # Legacy clients may still send roles. Discovery owns roles, not this view.
    modes = set(job["work_modes"]) & {"remote", "hybrid", "onsite"}
    if filters.workModes and not modes.intersection(filters.workModes):
        if modes or not filters.includeUnknownMode:
            return False
    location = str(job.get("location") or "")
    # Country always applies, including remote jobs; local narrowing never
    # replaces it. Unknown residency remains available for review.
    if (
        filters.country
        and matches_search_location(location, filters.country, str(job.get("country") or ""))
        is False
    ):
        return False
    if filters.locations and modes != {"remote"}:
        if not any(
            matches_local_location(location, term) is not False for term in filters.locations
        ):
            return False
    if filters.minimumPay is not None:
        upper = job.get("salary_max") or job.get("salary_min")
        interval = str(job.get("salary_interval") or "").lower()
        periods = {
            "year": "year",
            "yearly": "year",
            "annual": "year",
            "hour": "hour",
            "hourly": "hour",
        }
        comparable = (
            upper is not None
            and job.get("salary_currency") == filters.currency
            and periods.get(interval) == filters.period
        )
        # Do not invent currency conversion or hours worked per year.
        if upper is None or not comparable:
            return filters.includeUnknownPay
        if upper < filters.minimumPay:
            return False
    return True
