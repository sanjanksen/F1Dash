import re

from circuit_profiles import (
    CALENDAR_YEAR,
    CIRCUIT_TEXT_ALIASES,
    get_circuit_profile,
    match_circuit_from_text,
)


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


def test_match_circuit_from_text_canonical_aliases():
    circuits = [
        {"round": 1, "event_name": "Bahrain Grand Prix", "circuit_name": "Bahrain International Circuit", "country": "Bahrain"},
        {"round": 2, "event_name": "Saudi Arabian Grand Prix", "circuit_name": "Jeddah Corniche Circuit", "country": "Saudi Arabia"},
        {"round": 3, "event_name": "Japanese Grand Prix", "circuit_name": "Suzuka International Racing Course", "country": "Japan"},
        {"round": 4, "event_name": "Emilia Romagna Grand Prix", "circuit_name": "Autodromo Enzo e Dino Ferrari", "country": "Italy"},
        {"round": 5, "event_name": "Spanish Grand Prix", "circuit_name": "Circuit de Barcelona-Catalunya", "country": "Spain"},
        {"round": 6, "event_name": "Canadian Grand Prix", "circuit_name": "Circuit Gilles Villeneuve", "country": "Canada"},
        {"round": 7, "event_name": "British Grand Prix", "circuit_name": "Silverstone Circuit", "country": "United Kingdom"},
        {"round": 8, "event_name": "Belgian Grand Prix", "circuit_name": "Circuit de Spa-Francorchamps", "country": "Belgium"},
        {"round": 9, "event_name": "Dutch Grand Prix", "circuit_name": "Circuit Zandvoort", "country": "Netherlands"},
        {"round": 10, "event_name": "Italian Grand Prix", "circuit_name": "Autodromo Nazionale Monza", "country": "Italy"},
        {"round": 11, "event_name": "Azerbaijan Grand Prix", "circuit_name": "Baku City Circuit", "country": "Azerbaijan"},
        {"round": 12, "event_name": "United States Grand Prix", "circuit_name": "Circuit of the Americas", "country": "United States"},
        {"round": 13, "event_name": "Mexico City Grand Prix", "circuit_name": "Autodromo Hermanos Rodriguez", "country": "Mexico"},
        {"round": 14, "event_name": "Sao Paulo Grand Prix", "circuit_name": "Autodromo Jose Carlos Pace", "country": "Brazil"},
        {"round": 15, "event_name": "Las Vegas Grand Prix", "circuit_name": "Las Vegas Strip Circuit", "country": "United States"},
    ]

    cases = {
        "suzuka": "Japan",
        "monza": "Italy",
        "spa": "Belgium",
        "silverstone": "United Kingdom",
        "interlagos": "Brazil",
        "cota": "United States",
        "imola": "Italy",
        "montreal": "Canada",
        "baku": "Azerbaijan",
        "jeddah": "Saudi Arabia",
        "las vegas": "United States",
        "mexico city": "Mexico",
        "barcelona": "Spain",
        "zandvoort": "Netherlands",
    }

    for alias in cases:
        assert alias in CIRCUIT_TEXT_ALIASES, f"alias {alias!r} must live in CIRCUIT_TEXT_ALIASES"

    for alias, expected_country in cases.items():
        result = match_circuit_from_text(alias, circuits)
        assert result is not None, f"alias {alias!r} should match a circuit"
        assert result["country"] == expected_country, (
            f"alias {alias!r} matched {result['country']!r}, expected {expected_country!r}"
        )


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
