from job_puller.config import SearchSettings
from job_puller.eligibility import matches_enabled_family, title_matches


def test_title_aliases_expand_recall_without_becoming_provider_queries():
    search = SearchSettings(
        families=[
            {
                "name": "support",
                "titles": ["support engineer"],
                "title_aliases": ["application support analyst"],
            }
        ]
    )

    family = search.families[0]
    assert family.titles == ["support engineer"]
    assert matches_enabled_family("Senior Application Support Analyst", search)


def test_family_exclusions_override_an_accepted_title_phrase():
    assert not title_matches(
        "Desktop Support Engineer",
        ["support engineer"],
        ["desktop support"],
    )
    assert title_matches(
        "Cloud Support Engineer II",
        ["support engineer"],
        ["desktop support"],
    )


def test_exclusion_in_one_family_does_not_reject_a_match_in_another_family():
    search = SearchSettings(
        families=[
            {
                "name": "support",
                "titles": ["support engineer"],
                "excluded_titles": ["platform"],
            },
            {"name": "platform", "titles": ["platform engineer"]},
        ]
    )

    assert matches_enabled_family("Platform Engineer", search)
