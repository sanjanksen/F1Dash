import re

from circuit_profiles import CALENDAR_YEAR, get_circuit_profile


def test_calendar_year_constant():
    assert CALENDAR_YEAR == 2026


def test_great_britain_alias():
    profile = get_circuit_profile("Great Britain")
    assert profile is not None
    assert profile["circuit_key"] == "britain"
    assert "Silverstone" in profile["circuit_name"]


def test_united_kingdom_alias():
    profile = get_circuit_profile("United Kingdom")
    assert profile is not None
    assert profile["circuit_key"] == "britain"
    assert "Silverstone" in profile["circuit_name"]


def test_miami_disambiguation():
    profile = get_circuit_profile("United States", "Miami GP")
    assert profile is not None
    assert profile["circuit_key"] == "miami"
    assert "Miami" in profile["circuit_name"]


def test_cota_default_for_us():
    profile = get_circuit_profile("United States", "United States Grand Prix")
    assert profile is not None
    assert profile["circuit_key"] == "united_states"
    assert "Americas" in profile["circuit_name"]


def test_baku_narrative_qualifies_straight():
    profile = get_circuit_profile("Azerbaijan")
    assert profile is not None
    narrative = profile["narrative"].lower()
    km_match = re.search(r"\d+(\.\d+)?\s*km", narrative)
    assert km_match is not None, "narrative should still mention a km figure"
    prefix = narrative[: km_match.start()]
    assert "main straight" in prefix or "start/finish straight" in prefix, (
        "narrative must qualify the km figure as the main / start-finish "
        f"straight before quoting it; got: {profile['narrative']!r}"
    )
