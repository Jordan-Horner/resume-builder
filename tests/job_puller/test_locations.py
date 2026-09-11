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
    # A location with no geography at all (no text, or a generic label with
    # no country field either) is a data gap, not foreign evidence, so it
    # stays unresolved rather than being treated as "not US".
    assert matches_search_location("Remote", "United States") is None
    assert matches_search_location("Boston, MA", "United States", "Canada") is False
    assert matches_search_location("Remote", "USA", "US") is True
    # A bare US city with no state resolves from GeoText's gazetteer.
    for value in ["San Francisco", "Boston", "Portland"]:
        assert matches_search_location(value, "USA") is True
    # A bare two-letter code has no gazetteer entry of its own and isn't
    # reliable evidence either way, so — unlike a truly empty location — it
    # falls to the default: only positively recognized US locations pass.
    assert matches_search_location("CA", "USA") is False


def test_us_search_only_needs_to_recognize_us_not_catalog_every_country():
    from job_puller.locations import matches_search_location

    # This function only needs to answer "is this US or not" — it never
    # needs to identify which foreign country a posting is in. A real place
    # name that isn't positively recognized as US defaults to excluded.
    for value in ["Some Unrecognized Village", "Zamudio", "Bhubaneswar"]:
        assert matches_search_location(value, "United States") is False
    # A location with no geography at all is a data gap, not foreign
    # evidence — it's the one case that still stays unresolved (visible)
    # rather than excluded, since there's nothing to judge either way.
    for value in ["", "Hybrid", "In-Office", "Remote", "Americas", "Location not listed"]:
        assert matches_search_location(value, "United States") is None


def test_us_search_resolves_bare_foreign_cities_without_a_country_suffix():
    from job_puller.locations import matches_search_location

    for value in ["Bangalore", "Warsaw", "London", "Berlin"]:
        assert matches_search_location(value, "United States") is False


def test_us_search_treats_a_state_country_name_collision_as_the_state():
    from job_puller.locations import matches_search_location

    # "Georgia" is both a US state and a country, but on a US-market job
    # board a bare state name overwhelmingly means the state. This function
    # only needs to recognize US evidence, not identify foreign countries, so
    # there's no longer a reason to leave this ambiguous.
    assert matches_search_location("Georgia", "United States") is True
    assert matches_search_location("Atlanta, Georgia", "United States") is True


def test_us_search_ignores_short_gazetteer_cities_that_collide_with_words():
    from job_puller.locations import matches_search_location

    # GeoText's gazetteer has a real (tiny) city named "Bay" in the
    # Philippines, which would otherwise match the "Bay" in "SF Bay area".
    # The length guard filters it out; the "SF" hub alias (below) is what
    # actually resolves this one correctly.
    assert matches_search_location("Bay", "United States") is False


def test_us_search_recognizes_an_informal_hub_abbreviation():
    from job_puller.locations import matches_search_location

    # Found on the live deployment: "SF Bay area" has no comma/state context,
    # so nothing else here would recognize it as San Francisco, and an
    # unrecognized-but-real location defaults to "not US" (see below) —
    # without this alias a very common, unambiguous US reference would be
    # wrongly excluded.
    assert matches_search_location("SF Bay area", "United States") is True
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


def test_us_search_reads_all_caps_ats_locations():
    from job_puller.locations import matches_search_location

    # Found on the live deployment: some ATS feeds (DXC, Cadence) post
    # locations in ALL CAPS, which GeoText's Title Case city regex otherwise
    # can't match at all, leaving a plainly foreign posting unresolved.
    assert matches_search_location("HUN - BU - BUDAPEST", "United States") is False
    assert matches_search_location("ROU - B - BUCHAREST", "United States") is False
    assert matches_search_location("HSINCHU 05", "United States") is False


def test_us_search_strips_area_descriptors_around_a_real_city():
    from job_puller.locations import matches_search_location

    # Found on the live deployment: a leading "Metro "/"Greater " or a
    # trailing " Area"/" Metro"/" Metropolitan Area"/" Region" glues onto the
    # city as one phrase GeoText won't match, even though the city alone is
    # in its gazetteer.
    assert matches_search_location("Metro Manila", "United States") is False
    for value in [
        "Greater Seattle Area",
        "Greater Chicago Area",
        "Greater Boston",
        "Tulsa Metropolitan Area",
        "Charlotte Metro",
    ]:
        assert matches_search_location(value, "United States") is True


def test_us_search_strips_a_trailing_office_label_after_a_one_word_city():
    from job_puller.locations import matches_search_location

    # Found on the live deployment: GeoText's regex only allows one space
    # before it starts merging words into a single candidate. A two-word
    # city ("San Francisco") already used that space internally, so a
    # trailing word stays separate; a one-word city ("Boston") doesn't, so
    # "Boston Office" merges into one non-matching compound and GeoText finds
    # nothing at all — not even "Boston" alone.
    for value in ["Boston Office", "San Jose Office (HQ)", "San Francisco Office"]:
        assert matches_search_location(value, "United States") is True


def test_us_search_recognizes_officially_renamed_cities():
    from job_puller.locations import matches_search_location

    # Found on the live deployment (Accenture postings): GeoText's gazetteer
    # predates these official renamings, so it never recognized the current
    # city name even though the old name still resolves correctly.
    assert matches_search_location("Bengaluru", "United States") is False
    assert matches_search_location("Bangalore", "United States") is False
    assert matches_search_location("Gurugram", "United States") is False
    assert matches_search_location("Gurgaon", "United States") is False
