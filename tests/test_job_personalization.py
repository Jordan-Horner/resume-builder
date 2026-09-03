from __future__ import annotations

from resume_builder.job_personalization import build_shadow_order, load_shadow_settings


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
