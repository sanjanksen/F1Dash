from team_car_profiles import TEAM_CAR_PROFILES, get_team_car_profile


def test_mclaren_present_medium_confidence():
    p = get_team_car_profile("McLaren")
    assert p is not None
    assert p["team"] == "McLaren"
    assert p["confidence"] == "medium"


def test_alpine_present_medium_confidence():
    p = get_team_car_profile("Alpine")
    assert p is not None
    assert p["team"] == "Alpine"
    assert p["confidence"] == "medium"


def test_williams_present_medium_confidence():
    p = get_team_car_profile("Williams")
    assert p is not None
    assert p["team"] == "Williams"
    assert p["confidence"] == "medium"


def test_audi_present_low_confidence():
    p = get_team_car_profile("Audi")
    assert p is not None
    assert p["team"] == "Audi"
    assert p["confidence"] == "low"


def test_racing_bulls_disambiguated_from_red_bull():
    rb = get_team_car_profile("Racing Bulls")
    red_bull = get_team_car_profile("Red Bull")
    assert rb is not None
    assert red_bull is not None
    assert rb["team"] == "Racing Bulls"
    assert red_bull["team"] == "Red Bull Racing"
    assert rb["team"] != red_bull["team"]


def test_new_entries_stamped_2026_05_19():
    for key in ("mclaren", "alpine", "williams", "racing bulls", "audi"):
        assert TEAM_CAR_PROFILES[key]["last_reviewed"] == "2026-05-19"
        assert TEAM_CAR_PROFILES[key]["caveat"]
        for trait in TEAM_CAR_PROFILES[key]["traits"]:
            assert "source" in trait
            assert "source_url" in trait
