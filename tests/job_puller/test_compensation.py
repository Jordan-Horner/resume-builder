from job_puller.compensation import CompensationRange, extract_compensation_range
from job_puller.models import JobObservation


def test_extracts_explicit_annual_pay_range():
    assert extract_compensation_range("Pay Range\n$62,300 - $115,700 per year") == (
        CompensationRange(62_300, 115_700, "USD", "yearly")
    )


def test_extracts_compact_hourly_compensation_range():
    assert extract_compensation_range("Compensation range: US$45 to $65 per hour") == (
        CompensationRange(45, 65, "USD", "hourly")
    )


def test_extracts_labeled_base_salary_as_yearly_compensation():
    assert extract_compensation_range("Salary:\n$80,000-$90,000 base salary") == (
        CompensationRange(80_000, 90_000, "USD", "yearly")
    )


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
