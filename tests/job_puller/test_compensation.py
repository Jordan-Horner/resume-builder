from job_puller.compensation import (
    CompensationRange,
    convert_compensation_period,
    extract_compensation_range,
)
from job_puller.models import JobObservation


def test_extracts_explicit_annual_pay_range():
    assert extract_compensation_range("Pay Range\n$62,300 - $115,700 per year") == (
        CompensationRange(62_300, 115_700, "USD", "yearly")
    )


def test_extracts_compact_hourly_compensation_range():
    assert extract_compensation_range("Compensation range: US$45 to $65 per hour") == (
        CompensationRange(45, 65, "USD", "hourly")
    )


def test_converts_hourly_and_yearly_compensation_for_comparison():
    assert convert_compensation_period(24, "hourly", "year") == 49_920
    assert convert_compensation_period(104_000, "yearly", "hour") == 50
    assert convert_compensation_period(24, None, "year") is None
    assert convert_compensation_period(104_000, None, "year") == 104_000


def test_extracts_labeled_base_salary_as_yearly_compensation():
    assert extract_compensation_range("Salary:\n$80,000-$90,000 base salary") == (
        CompensationRange(80_000, 90_000, "USD", "yearly")
    )


def test_extracts_annual_salary_range_without_thousands_separators():
    assert extract_compensation_range("Salary:\n$140000-$160000") == (
        CompensationRange(140_000, 160_000, "USD", "yearly")
    )


def test_extracts_labeled_annual_range_with_iso_currency_suffixes():
    description = (
        "The base salary range is 176,000 USD - 276,000 USD for Level 4, "
        "and 208,000 USD - 333,500 USD for Level 5."
    )

    assert extract_compensation_range(description) == (
        CompensationRange(176_000, 276_000, "USD", "yearly")
    )


def test_rejects_unlabeled_or_mixed_iso_currency_ranges():
    assert extract_compensation_range("The range is 80,000 USD - 90,000 USD.") is None
    assert extract_compensation_range("Salary range is 80,000 USD - 90,000 CAD.") is None


def test_repairs_truncated_thousands_group_in_labeled_salary_range():
    description = "The base salary range for this role is $143,00 to $210,000."

    assert extract_compensation_range(description) == (
        CompensationRange(143_000, 210_000, "USD", "yearly")
    )


def test_does_not_repair_unlabeled_or_implausible_malformed_ranges():
    assert extract_compensation_range("The range is $143,00 to $210,000.") is None
    assert extract_compensation_range("Salary range: $14,00 to $2,100.") is None


def test_infers_unlabeled_annual_sized_range():
    assert extract_compensation_range("The expected range is $80K-$90K.") == (
        CompensationRange(80_000, 90_000, "USD", "yearly")
    )


def test_rejects_ambiguous_and_implausible_ranges():
    assert extract_compensation_range("A benefit worth $620-$1,150") is None
    assert extract_compensation_range("Salary range: $2 - $4 per year") is None


def test_job_observation_uses_description_only_when_structured_salary_is_absent():
    inferred = JobObservation(
        provider="linkedin",
        provider_job_id="1",
        title="Support Engineer",
        company="Example",
        source_url="https://example.com/jobs/1",
        description_text="Salary Range: $90K\u2013$120K annually",
    )
    structured = JobObservation(
        provider="linkedin",
        provider_job_id="2",
        title="Support Engineer",
        company="Example",
        source_url="https://example.com/jobs/2",
        description_text="Salary Range: $90K\u2013$120K annually",
        salary_min=80_000,
        salary_max=100_000,
        salary_currency="USD",
        salary_interval="yearly",
    )

    assert (inferred.salary_min, inferred.salary_max) == (90_000, 120_000)
    assert (structured.salary_min, structured.salary_max) == (80_000, 100_000)
