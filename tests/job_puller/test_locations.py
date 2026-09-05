import pytest

from job_puller.locations import matching_location_terms


@pytest.mark.parametrize(
    "alias", ["US", "USA", "U.S.", "U.S.A.", "United States", "United States of America"]
)
@pytest.mark.parametrize("term", ["USA", "U.S.", "United States"])
def test_country_aliases_match_both_directions(alias: str, term: str) -> None:
    assert matching_location_terms(f"Remote ({alias})", [term]) == [term]


@pytest.mark.parametrize(
    "location", ["Australia", "Austria", "Austin, TX", "Russia", "USSR", "New York", "USAID", ""]
)
def test_no_substring_or_inferred_country(location: str) -> None:
    assert matching_location_terms(location, ["US"]) == []


def test_compound_terms_and_unicode_cities() -> None:
    assert matching_location_terms("USA", ["United States", "USA", "US"]) == ["United States"]
    assert matching_location_terms("Boston, U.S.A.", ["Boston United States"]) == [
        "Boston United States"
    ]
    assert matching_location_terms("Montréal, Canada", ["Montréal"]) == ["Montréal"]
    assert matching_location_terms("USA", ["", " ", "."]) == []


def test_us_search_uses_state_context_and_keeps_unknown_distinct():
    from job_puller.locations import matches_search_location

    for value in [
        "USA",
        "U.S.A.",
        "United States",
        "Boston, MA",
        "Austin, TX",
        "New York, NY (Hybrid)",
    ]:
        assert matches_search_location(value, "United States") is True
    for value in ["Toronto, ON", "London, UK", "Australia", "Remote - Canada"]:
        assert matches_search_location(value, "United States") is False
    assert matches_search_location("Remote", "United States") is None
    assert matches_search_location("Boston, MA", "United States", "Canada") is False
    assert matches_search_location("Remote", "USA", "US") is True
    for value in ["San Francisco", "Boston", "CA"]:
        assert matches_search_location(value, "USA") is None
