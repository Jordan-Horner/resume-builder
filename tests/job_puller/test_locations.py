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
    # A bare US city with no state, previously left ambiguous, now resolves
    # from GeoText's gazetteer.
    for value in ["San Francisco", "Boston", "Portland"]:
        assert matches_search_location(value, "USA") is True
    # A bare two-letter code has no gazetteer entry of its own, so it stays
    # unresolved rather than guessing (e.g. "CA" is not reliable US evidence).
    assert matches_search_location("CA", "USA") is None


def test_us_search_resolves_bare_foreign_cities_without_a_country_suffix():
    from job_puller.locations import matches_search_location

    for value in ["Bangalore", "Warsaw", "London", "Berlin"]:
        assert matches_search_location(value, "United States") is False


def test_us_search_leaves_state_country_name_collisions_unresolved():
    from job_puller.locations import matches_search_location

    # "Georgia" is both a US state and a country; GeoText would otherwise
    # resolve it to the country and wrongly hide a domestic Georgia posting.
    assert matches_search_location("Georgia", "United States") is None
    assert matches_search_location("Atlanta, Georgia", "United States") is None


def test_us_search_ignores_short_gazetteer_cities_that_collide_with_words():
    from job_puller.locations import matches_search_location

    # Found by auditing real inventory data: GeoText's gazetteer has a real
    # (tiny) city named "Bay" in the Philippines, which otherwise matched the
    # "Bay" in "SF Bay area" and wrongly hid a Bay Area posting.
    assert matches_search_location("SF Bay area", "United States") is None
    assert matches_search_location("San Francisco Bay Area", "United States") is True


def test_us_search_weighs_repeated_region_mentions_over_a_single_city():
    from job_puller.locations import matches_search_location

    # Found by auditing real inventory data: a Costa Rican city that shares
    # its name with a US one ("San Francisco de Heredia") must not resolve
    # to the US just because "San Francisco" matches first; "Heredia" (the
    # actual region) is named twice and should win the majority vote.
    assert (
        matches_search_location("San Francisco de Heredia, Heredia, cr", "United States") is False
    )
