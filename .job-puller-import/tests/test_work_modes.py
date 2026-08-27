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
