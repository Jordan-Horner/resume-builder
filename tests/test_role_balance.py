from pathlib import Path

from resume_builder.role_balance import role_balance_diagnostic
from resume_builder.synthesis_models import RoleArc, SynthesisPlan, SynthesisStory


def _story(
    story_id: str,
    role_id: str,
    *,
    importance: str = "core",
    priority: int = 5,
) -> SynthesisStory:
    return SynthesisStory(
        story_id=story_id,
        section="experience",
        role_ids=(role_id,),
        fact_ids=(f"FACT-{story_id}",),
        primary_job=f"job-{story_id}",
        priority=priority,
        importance=importance,
        rationale="Test story.",
        claim_focus=f"Focus {story_id}.",
    )


def _plan(
    stories: list[SynthesisStory],
    arcs: list[RoleArc],
) -> SynthesisPlan:
    return SynthesisPlan(
        source=Path("/project/resumes/plans/test.yaml"),
        version=7,
        resume=Path("/project/resumes/test.md"),
        direction=Path("/project/directions/test.md"),
        target_argument="Test target.",
        summary_job="Test summary.",
        summary_fact_ids=(),
        summary_body_fact_ids=(),
        progression=tuple(role_id for arc in arcs for role_id in arc.role_ids),
        stories=tuple(stories),
        exclusions=(),
        gaps=(),
        role_arcs=tuple(arcs),
    )


def _arc(
    role_id: str,
    emphasis: str,
    story_ids: list[str],
    *,
    required: list[str] | None = None,
    optional: list[str] | None = None,
) -> RoleArc:
    return RoleArc(
        role_ids=(role_id,),
        emphasis=emphasis,
        arc_focus="Test arc.",
        story_ids=tuple(story_ids),
        selection_rationale="Test allocation.",
        omitted_signals=(),
        required_story_ids=tuple(required or []),
        optional_story_ids=tuple(optional or []),
    )


def _entry(role_id: str, story_ids: list[str], words: int) -> dict[str, object]:
    words_per_story = max(1, words // len(story_ids))
    return {
        "evidence": [role_id],
        "bullets": [
            {"story": story_id, "text": "word " * words_per_story} for story_id in story_ids
        ],
    }


def test_role_balance_routes_protected_backward_weighting_to_user() -> None:
    stories = [_story(f"lead-{index}", "ROLE-LEAD") for index in range(2)] + [
        _story(f"older-{index}", "ROLE-OLDER") for index in range(4)
    ]
    plan = _plan(
        stories,
        [
            _arc("ROLE-LEAD", "lead", ["lead-0", "lead-1"], required=["lead-0", "lead-1"]),
            _arc(
                "ROLE-OLDER",
                "supporting",
                [f"older-{index}" for index in range(4)],
                required=[f"older-{index}" for index in range(4)],
            ),
        ],
    )
    payload = {
        "experience": [
            _entry("ROLE-LEAD", ["lead-0", "lead-1"], 30),
            _entry("ROLE-OLDER", [f"older-{index}" for index in range(4)], 60),
        ]
    }

    result = role_balance_diagnostic(payload, plan)

    assert result["status"] == "user-decision"
    inversion = result["inversions"][0]
    assert inversion["story_surplus"] == 2
    assert inversion["automatic_candidate_story_ids"] == []
    assert inversion["required_reduction"] == 1


def test_role_balance_ignores_one_extra_story_without_large_word_ratio() -> None:
    stories = [_story(f"lead-{index}", "ROLE-LEAD") for index in range(2)] + [
        _story(f"older-{index}", "ROLE-OLDER") for index in range(3)
    ]
    plan = _plan(
        stories,
        [
            _arc("ROLE-LEAD", "lead", ["lead-0", "lead-1"]),
            _arc("ROLE-OLDER", "supporting", ["older-0", "older-1", "older-2"]),
        ],
    )
    payload = {
        "experience": [
            _entry("ROLE-LEAD", ["lead-0", "lead-1"], 40),
            _entry("ROLE-OLDER", ["older-0", "older-1", "older-2"], 60),
        ]
    }

    result = role_balance_diagnostic(payload, plan)

    assert result["status"] == "no-inversion-detected"
    assert result["inversions"] == []


def test_role_balance_routes_declared_optional_content_to_reviewer() -> None:
    lead = [_story(f"lead-{index}", "ROLE-LEAD") for index in range(2)]
    older = [
        _story("older-core-0", "ROLE-OLDER"),
        _story("older-core-1", "ROLE-OLDER"),
        _story("older-optional", "ROLE-OLDER", importance="supporting", priority=1),
    ]
    plan = _plan(
        lead + older,
        [
            _arc("ROLE-LEAD", "lead", ["lead-0", "lead-1"]),
            _arc(
                "ROLE-OLDER",
                "supporting",
                ["older-core-0", "older-core-1", "older-optional"],
                required=["older-core-0", "older-core-1"],
                optional=["older-optional"],
            ),
        ],
    )
    payload = {
        "experience": [
            _entry("ROLE-LEAD", ["lead-0", "lead-1"], 20),
            _entry(
                "ROLE-OLDER",
                ["older-core-0", "older-core-1", "older-optional"],
                60,
            ),
        ]
    }

    result = role_balance_diagnostic(payload, plan)

    assert result["status"] == "reviewer-decision"
    assert result["inversions"][0]["automatic_candidate_story_ids"] == ["older-optional"]


def test_role_balance_uses_largest_visible_lead_as_reference() -> None:
    stories = (
        [_story("lead-small", "ROLE-LEAD-SMALL")]
        + [_story(f"lead-large-{index}", "ROLE-LEAD-LARGE") for index in range(3)]
        + [_story(f"older-{index}", "ROLE-OLDER") for index in range(4)]
    )
    plan = _plan(
        stories,
        [
            _arc("ROLE-LEAD-SMALL", "lead", ["lead-small"]),
            _arc(
                "ROLE-LEAD-LARGE",
                "lead",
                ["lead-large-0", "lead-large-1", "lead-large-2"],
            ),
            _arc("ROLE-OLDER", "supporting", [f"older-{index}" for index in range(4)]),
        ],
    )
    payload = {
        "experience": [
            _entry("ROLE-LEAD-SMALL", ["lead-small"], 10),
            _entry(
                "ROLE-LEAD-LARGE",
                ["lead-large-0", "lead-large-1", "lead-large-2"],
                60,
            ),
            _entry("ROLE-OLDER", [f"older-{index}" for index in range(4)], 70),
        ]
    }

    result = role_balance_diagnostic(payload, plan)

    assert result["reference"]["role_ids"] == ["ROLE-LEAD-LARGE"]
    assert result["status"] == "no-inversion-detected"
