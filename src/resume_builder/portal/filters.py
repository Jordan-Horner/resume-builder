"""Inventory viewing filters, independent from collection configuration."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from job_puller.compensation import convert_compensation_period
from job_puller.locations import matches_local_location, matches_search_location

from ..opportunities.screening import has_clearance_requirement

FilterTerm = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class ViewFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")
    roles: list[FilterTerm] = Field(default_factory=list, max_length=22)
    workModes: list[Literal["remote", "hybrid", "onsite"]] = Field(default_factory=list)
    excludedWorkModes: list[Literal["remote", "hybrid", "onsite"]] = Field(default_factory=list)
    country: str = Field(default="", max_length=100)
    locations: list[FilterTerm] = Field(default_factory=list, max_length=50)
    employmentTypes: list[Literal["fulltime", "parttime", "contract", "temporary"]] = Field(
        default_factory=list
    )
    excludedEmploymentTypes: list[Literal["fulltime", "parttime", "contract", "temporary"]] = Field(
        default_factory=list
    )
    minimumPay: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    currency: str = Field(default="USD", pattern=r"^[A-Z]{3}$")
    period: Literal["year", "hour"] = "year"
    includeUnknownPay: bool = True
    includeUnknownMode: bool = True
    includeUnmatchedLocation: bool = False
    clearanceMode: Literal["all", "exclude", "only"] = "all"

    @model_validator(mode="before")
    @classmethod
    def migrate_clearance_boolean(cls, value: Any) -> Any:
        if not isinstance(value, dict) or "includeClearanceJobs" not in value:
            return value
        migrated = dict(value)
        legacy = migrated.pop("includeClearanceJobs")
        if type(legacy) is not bool:
            raise ValueError("includeClearanceJobs must be true or false")
        migrated.setdefault("clearanceMode", "all" if legacy else "exclude")
        return migrated

    @model_validator(mode="after")
    def selections_must_not_overlap(self) -> ViewFilters:
        if set(self.workModes).intersection(self.excludedWorkModes):
            raise ValueError("work modes cannot be both included and excluded")
        if set(self.employmentTypes).intersection(self.excludedEmploymentTypes):
            raise ValueError("employment types cannot be both included and excluded")
        return self


def matches_view(job: dict[str, Any], filters: ViewFilters) -> bool:
    # Legacy clients may still send roles. Discovery owns roles, not this view.
    if filters.clearanceMode != "all":
        requires_clearance = has_clearance_requirement(
            str(job.get("title") or ""), str(job.get("description") or "")
        )
        if filters.clearanceMode == "exclude" and requires_clearance:
            return False
        if filters.clearanceMode == "only" and not requires_clearance:
            return False
    modes = set(job["work_modes"]) & {"remote", "hybrid", "onsite"}
    if modes.intersection(filters.excludedWorkModes):
        return False
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
        converted_upper = (
            convert_compensation_period(float(upper), interval, filters.period)
            if isinstance(upper, (int, float))
            else None
        )
        # Unknown currencies and periods remain visible unless the user chose
        # the strict unknown-pay policy.
        if converted_upper is None or job.get("salary_currency") != filters.currency:
            return filters.includeUnknownPay
        if converted_upper < filters.minimumPay:
            return False
    return True
