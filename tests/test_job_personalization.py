from __future__ import annotations

from resume_builder.job_personalization import (
    build_shadow_order,
    extract_preference_traits,
    extract_seniority,
    load_shadow_settings,
)


def _item(job_id: str, score_kind: str, *, title: str = "Operations Engineer"):
    results = {
        "strong": ("strong_match", "pursue", "medium"),
        "stretch": ("worthwhile_stretch", "pursue_as_stretch", "medium"),
        "weak": ("weak_fit", "deprioritize", "high"),
    }
    fit, recommendation, confidence = results[score_kind]
    return {
        "id": job_id,
        "title": title,
        "source_order": int(job_id[-1]),
        "active": True,
        "deterministic": {"interest": {}, "hard_conflicts": []},
        "screening": {
            "status": "complete",
            "result": {
                "fit": fit,
                "recommendation": recommendation,
                "confidence": confidence,
            },
        },
    }


def test_shadow_order_keeps_every_active_job_and_does_not_learn_from_ignored_jobs():
    items = [_item("job-1", "strong"), _item("job-2", "stretch"), _item("job-3", "weak")]

    order, scores = build_shadow_order(
        items,
        preferences={"personalization": {"exploration_fraction": 0}},
        positive_titles=[],
    )

    assert order == ["job-1", "job-2", "job-3"]
    assert set(order) == {"job-1", "job-2", "job-3"}
    assert all(
        score["learning_sources"]["ignored_jobs_used_as_negative"] is False
        for score in scores.values()
    )


def test_applied_title_is_a_positive_signal_but_not_a_visibility_filter():
    items = [
        _item("job-1", "stretch", title="Cloud Support Engineer"),
        _item("job-2", "stretch", title="Database Administrator"),
    ]

    order, scores = build_shadow_order(
        items,
        preferences={"personalization": {"exploration_fraction": 0}},
        positive_titles=["Technical Support Engineer"],
    )

    assert order == ["job-1", "job-2"]
    assert scores["job-1"]["score"] > scores["job-2"]["score"]
    assert len(order) == len(items)


def test_clearance_preference_is_a_modest_positive_score_signal():
    clearance = _item("job-1", "stretch")
    clearance["deterministic"]["clearance_requirement"] = True
    ordinary = _item("job-2", "stretch")

    order, scores = build_shadow_order(
        [ordinary, clearance],
        preferences={
            "clearance_preference": "prefer",
            "personalization": {"exploration_fraction": 0},
        },
        positive_titles=[],
    )

    assert order == ["job-1", "job-2"]
    assert scores["job-1"]["score"] > scores["job-2"]["score"]


def test_exploration_preserves_complete_set_and_marks_exploration_slot():
    items = [_item(f"job-{index}", "strong" if index < 5 else "weak") for index in range(1, 7)]

    order, scores = build_shadow_order(
        items,
        preferences={"personalization": {"exploration_fraction": 0.2}},
        positive_titles=[],
    )

    assert set(order) == {f"job-{index}" for index in range(1, 7)}
    assert sum(bool(value.get("exploration_slot")) for value in scores.values()) == 1


def test_exploration_never_promotes_a_confirmed_ineligible_job():
    items = [_item("job-1", "strong"), _item("job-2", "weak"), _item("job-3", "weak")]
    items[-1]["screening"]["result"]["recommendation"] = "do_not_apply"

    order, scores = build_shadow_order(
        items,
        preferences={"personalization": {"exploration_fraction": 0.5}},
        positive_titles=[],
    )

    assert order[-1] == "job-3"
    assert scores["job-3"].get("exploration_slot") is None


def test_shadow_settings_reject_non_shadow_or_excessive_exploration():
    try:
        load_shadow_settings({"personalization": {"mode": "active"}})
    except ValueError as exc:
        assert "must be shadow" in str(exc)
    else:
        raise AssertionError("active mode should not be accepted")

    try:
        load_shadow_settings({"personalization": {"exploration_fraction": 0.75}})
    except ValueError as exc:
        assert "from 0 to 0.5" in str(exc)
    else:
        raise AssertionError("unsafe exploration fraction should not be accepted")


def test_three_reasoned_phone_rejections_lower_only_phone_heavy_jobs():
    phone_job = _item("job-1", "strong", title="Technical Support Engineer")
    phone_job["preference_traits"] = ["phone_support"]
    escalation_job = _item("job-2", "strong", title="Technical Support Engineer")
    feedback = [
        {
            "action": "not_interested",
            "reasons": ["phone_support"],
            "job": {"id": f"old-{index}", "traits": ["phone_support"]},
        }
        for index in range(3)
    ]

    _, scores = build_shadow_order(
        [phone_job, escalation_job],
        preferences={"personalization": {"exploration_fraction": 0}},
        positive_titles=[],
        feedback_events=feedback,
    )

    assert scores["job-1"]["interest_score"] < scores["job-2"]["interest_score"]
    assert any("phone support" in reason.lower() for reason in scores["job-1"]["reasons"])


def test_preference_traits_are_small_and_deterministic():
    assert extract_preference_traits(
        {
            "title": "Support Engineer",
            "description": "Handle inbound phone calls and join an on-call rotation.",
        }
    ) == ["on_call", "phone_support"]


def test_seniority_uses_specific_title_signals_before_description_fallback():
    assert extract_seniority({"title": "Senior Staff Engineer"}) == "staff"
    assert extract_seniority({"title": "Backend Engineer, New Grad"}) == "new_grad"
    assert (
        extract_seniority(
            {"title": "Backend Engineer", "description": "This is an entry-level position."}
        )
        == "entry"
    )
    assert extract_seniority({"title": "Backend Engineer"}) == "unknown"


def test_company_affinity_requires_an_explicit_company_reason():
    item = _item("job-1", "strong")
    item["company"] = "Example"
    ordinary_like = {
        "action": "interested",
        "reasons": ["day_to_day"],
        "job": {"id": "old-1", "company": "Example"},
    }
    company_like = {
        "action": "interested",
        "reasons": ["company"],
        "job": {"id": "old-2", "company": "Example"},
    }

    ordinary = build_shadow_order(
        [item], preferences={}, positive_titles=[], feedback_events=[ordinary_like]
    )[1]["job-1"]
    explicit = build_shadow_order(
        [item], preferences={}, positive_titles=[], feedback_events=[company_like]
    )[1]["job-1"]

    assert ordinary["company_score"] == 0.5
    assert explicit["company_score"] > ordinary["company_score"]


def test_positive_posting_opens_favor_shared_duties_without_overriding_fit():
    incident_role = _item("job-1", "stretch", title="Technical Support Engineer")
    incident_role["screening"]["result"]["criterion_evidence"] = [
        {"criterion_id": "new-incident", "label": "Lead incident response"}
    ]
    phone_role = _item("job-2", "stretch", title="Technical Support Engineer")
    phone_role["screening"]["result"]["criterion_evidence"] = [
        {"criterion_id": "new-phone", "label": "Handle inbound phone queue"}
    ]
    opened = {
        "action": "opened_posting",
        "job": {
            "id": "old-1",
            "title": "Technical Support Engineer",
            "screening": {"criteria": [{"label": "Own incident response", "outcome": "supported"}]},
        },
    }

    _, scores = build_shadow_order(
        [incident_role, phone_role],
        preferences={"personalization": {"exploration_fraction": 0}},
        positive_titles=[],
        feedback_events=[opened],
    )

    assert scores["job-1"]["fit_score"] == scores["job-2"]["fit_score"]
    assert scores["job-1"]["interest_score"] > scores["job-2"]["interest_score"]
    assert scores["job-1"]["interest_score"] < 0.6


def test_seniority_pattern_uses_historical_titles_and_positive_contrast():
    senior = _item("job-1", "strong", title="Senior DevOps Engineer")
    staff = _item("job-2", "strong", title="Staff DevOps Engineer")
    feedback = [
        {
            "action": "not_interested",
            "job": {"id": f"senior-{index}", "title": "Senior DevOps Engineer"},
        }
        for index in range(3)
    ] + [
        {
            "action": "interested",
            "job": {"id": "staff-positive", "title": "Staff DevOps Engineer"},
        }
    ]

    _, scores = build_shadow_order(
        [senior, staff],
        preferences={"personalization": {"exploration_fraction": 0}},
        positive_titles=[],
        feedback_events=feedback,
    )

    pattern = scores["job-1"]["learning_sources"]["seniority_pattern"]
    assert pattern == {
        "level": "senior",
        "negative_same_level": 3,
        "positive_same_level": 0,
        "positive_other_level": 1,
        "applied": True,
    }
    assert scores["job-1"]["interest_score"] < scores["job-2"]["interest_score"]
    assert any("other levels" in reason for reason in scores["job-1"]["reasons"])


def test_seniority_pattern_requires_positive_contrast_and_clear_majority():
    item = _item("job-1", "strong", title="Senior DevOps Engineer")
    rejections = [
        {
            "action": "not_interested",
            "job": {"id": f"negative-{index}", "title": "Senior DevOps Engineer"},
        }
        for index in range(3)
    ]
    mixed = (
        rejections
        + [
            {
                "action": "interested",
                "job": {"id": f"senior-positive-{index}", "title": "Senior DevOps Engineer"},
            }
            for index in range(2)
        ]
        + [
            {
                "action": "applied",
                "job": {"id": "staff-positive", "title": "Staff DevOps Engineer"},
            }
        ]
    )

    no_contrast = build_shadow_order(
        [item], preferences={}, positive_titles=[], feedback_events=rejections
    )[1]["job-1"]
    contradictory = build_shadow_order(
        [item], preferences={}, positive_titles=[], feedback_events=mixed
    )[1]["job-1"]

    assert no_contrast["learning_sources"]["seniority_pattern"]["applied"] is False
    assert contradictory["learning_sources"]["seniority_pattern"]["applied"] is False


def test_seniority_pattern_does_not_cross_role_families():
    item = _item("job-1", "strong", title="Senior DevOps Engineer")
    feedback = [
        {
            "action": "not_interested",
            "job": {"id": f"support-{index}", "title": "Senior Technical Support Engineer"},
        }
        for index in range(3)
    ] + [
        {
            "action": "interested",
            "job": {"id": "support-positive", "title": "Staff Technical Support Engineer"},
        }
    ]

    score = build_shadow_order(
        [item], preferences={}, positive_titles=[], feedback_events=feedback
    )[1]["job-1"]

    assert score["learning_sources"]["seniority_pattern"] == {
        "level": "senior",
        "negative_same_level": 0,
        "positive_same_level": 0,
        "positive_other_level": 0,
        "applied": False,
    }


def test_exact_positive_job_becomes_hot_only_after_a_usable_screen():
    item = _item("job-1", "strong", title="DevOps Engineer")
    feedback = [{"action": "interested", "job": {"id": "job-1", "title": "DevOps Engineer"}}]

    score = build_shadow_order(
        [item], preferences={}, positive_titles=[], feedback_events=feedback
    )[1]["job-1"]

    assert score["hot"] is True
    assert score["hot_reasons"] == ["career_fit", "exact_interest"]


def test_hard_conflict_never_becomes_hot_even_when_explicitly_interested():
    item = _item("job-1", "strong", title="DevOps Engineer")
    item["deterministic"]["hard_conflicts"] = ["work_mode"]
    feedback = [{"action": "interested", "job": {"id": "job-1", "title": "DevOps Engineer"}}]

    score = build_shadow_order(
        [item], preferences={}, positive_titles=[], feedback_events=feedback
    )[1]["job-1"]

    assert score["hot"] is False
    assert score["hot_reasons"] == []


def test_one_positive_does_not_promote_a_title_family_but_repeated_structured_matches_do():
    item = _item("job-1", "strong", title="DevOps Engineer")
    item["screening"]["result"]["criterion_evidence"] = [
        {"criterion_id": "current", "label": "Operate Kubernetes infrastructure"}
    ]
    one_positive = {
        "action": "interested",
        "job": {
            "id": "old-1",
            "title": "DevOps Engineer",
            "seniority": "unknown",
            "screening": {"criteria": [{"label": "Operate Kubernetes clusters"}]},
        },
    }
    second_positive = {
        "action": "applied",
        "job": {
            "id": "old-2",
            "title": "DevOps Engineer",
            "seniority": "unknown",
            "screening": {"criteria": [{"label": "Kubernetes infrastructure operations"}]},
        },
    }

    one = build_shadow_order(
        [item], preferences={}, positive_titles=[], feedback_events=[one_positive]
    )[1]["job-1"]
    repeated = build_shadow_order(
        [item],
        preferences={},
        positive_titles=[],
        feedback_events=[one_positive, second_positive],
    )[1]["job-1"]

    assert one["hot"] is False
    assert repeated["hot"] is True
    assert repeated["learning_sources"]["positive_pattern_matches"] == 2
    assert "positive_pattern" in repeated["hot_reasons"]
