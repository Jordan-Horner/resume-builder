import pytest

from job_puller.work_modes import WorkMode, classify_work_arrangement, explicit_arrangement


def test_classifies_explicit_remote_description():
    arrangement = classify_work_arrangement(
        description="This role is fully remote and open across the United States."
    )
    assert arrangement.available_modes == {WorkMode.REMOTE}
    assert arrangement.evidence[0].rule == "description_remote"


def test_hybrid_schedule_beats_generic_remote_language():
    arrangement = classify_work_arrangement(
        description="This is a hybrid role with two remote days per week."
    )
    assert arrangement.available_modes == {WorkMode.HYBRID}


@pytest.mark.parametrize(
    ("title", "description"),
    [
        (
            "Infrastructure Operations Engineer - Core Services",
            "Location: Canton, Massachusetts, United States (Hybrid). You'll be based "
            "in the Canton, MA office for a minimum of three days a week, with the "
            "flexibility to work from home for some of your working week.",
        ),
        (
            "Senior Platform Engineer - Core Infrastructure",
            "This position requires presence in our office location 4 days per week; "
            "the designated work from home day is Tuesday.",
        ),
        (
            "Systems Engineer - NA",
            "This role requires the candidate to be on site with our customer on a "
            "2-3 day per week basis.",
        ),
        (
            "Backend Engineer (Mid-Level)",
            "Based in NYC with ability to work out of our office at least 2 days/week.",
        ),
        (
            "Lead AI Engineer / Architect - Hybrid",
            "Work arrangement: Hybrid. Three days per week on-site. Two days per week remote.",
        ),
        (
            "Systems Engineer - Design & Development - Hybrid",
            "Workplace options: This position is fully on-site, or Hybrid/Flex as desired.",
        ),
    ],
)
def test_inventory_regressions_override_false_remote_label_as_hybrid(title, description):
    arrangement = classify_work_arrangement(
        title=title,
        description=description,
        legacy_remote=True,
    )

    assert arrangement.available_modes == {WorkMode.HYBRID}
    assert arrangement.evidence[0].rule == "description_hybrid"
    assert arrangement.evidence[0].matched_text


@pytest.mark.parametrize(
    "description",
    [
        (
            "Our primary work location is the Deer Creek facility with limited ability "
            "to work remotely. You will primarily be required to come into the office."
        ),
        "Telework and Travel: On-site. This position supports an active contract.",
    ],
)
def test_inventory_regressions_override_false_remote_label_as_onsite(description):
    arrangement = classify_work_arrangement(description=description, legacy_remote=True)

    assert arrangement.available_modes == {WorkMode.ONSITE}
    assert arrangement.evidence[0].rule == "description_onsite"


@pytest.mark.parametrize(
    ("title", "description"),
    [
        ("Cloud Engineer", "This fully remote role operates hybrid cloud infrastructure."),
        (
            "Technical Support Engineer",
            "This fully remote role spans both product ecosystems in a hybrid role.",
        ),
        (
            "Site Reliability Engineer",
            "This role can sit in our NYC office on a hybrid basis, or it can be fully remote.",
        ),
        (
            "Cloud Infrastructure Engineer",
            "This role is fully remote. Future models could potentially involve a hybrid presence.",
        ),
        (
            "Customer Identity Platform Engineer",
            "This role is remote unless you live within 50 miles, in which case onsite "
            "presence may be requested.",
        ),
        ("AI Platform Engineer", "Location: [Location / Hybrid / Remote]"),
        (
            "Systems Engineer",
            "Remote work is available; applicants may attend an in-person interview "
            "regardless of whether a role is designated hybrid or remote.",
        ),
    ],
)
def test_inventory_negative_controls_remain_remote(title, description):
    arrangement = classify_work_arrangement(
        title=title,
        description=description,
        legacy_remote=True,
    )

    assert arrangement.available_modes == {WorkMode.REMOTE}


def test_technical_phrases_do_not_define_work_arrangement():
    for title, description in (
        ("Hybrid Cloud Engineer", "Build hybrid cloud platforms."),
        ("Remote Support Engineer", "Provide remote hands for physical systems."),
    ):
        arrangement = classify_work_arrangement(title=title, description=description)
        assert arrangement.available_modes == {WorkMode.UNKNOWN}


def test_legacy_false_is_unknown_not_onsite():
    arrangement = classify_work_arrangement(
        description="Employees may occasionally work remotely.", legacy_remote=False
    )
    assert arrangement.available_modes == {WorkMode.UNKNOWN}


def test_multiple_provider_modes_are_preserved():
    arrangement = explicit_arrangement(
        [WorkMode.REMOTE, WorkMode.ONSITE],
        source="provider_structured",
        rule="provider_locations",
    )
    assert arrangement.available_modes == {WorkMode.REMOTE, WorkMode.ONSITE}
