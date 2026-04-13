from unittest.mock import patch

import resolver


@patch('resolver.get_drivers')
@patch('resolver.get_circuits')
def test_resolve_query_context_driver_event(mock_circuits, mock_drivers):
    mock_drivers.return_value = [
        {"full_name": "George Russell", "code": "RUS", "driver_id": "russell", "team": "Mercedes"},
        {"full_name": "Lando Norris", "code": "NOR", "driver_id": "norris", "team": "McLaren"},
    ]
    mock_circuits.return_value = [
        {"round": 3, "event_name": "Japanese Grand Prix", "circuit_name": "Suzuka", "country": "Japan"},
        {"round": 6, "event_name": "Miami Grand Prix", "circuit_name": "Miami", "country": "United States"},
    ]

    result = resolver.resolve_query_context("How did Russell do at Suzuka?")

    assert result["entity_type"] == "driver"
    assert result["entity_name"] == "George Russell"
    assert result["round_number"] == 3
    assert result["event_name"] == "Japanese Grand Prix"
    assert result["suggested_tool"] == "get_driver_race_story"


@patch('resolver.get_drivers')
@patch('resolver.get_circuits')
def test_resolve_query_context_team(mock_circuits, mock_drivers):
    mock_drivers.return_value = [
        {"full_name": "George Russell", "code": "RUS", "driver_id": "russell", "team": "Mercedes"},
        {"full_name": "Kimi Antonelli", "code": "ANT", "driver_id": "antonelli", "team": "Mercedes"},
    ]
    mock_circuits.return_value = [
        {"round": 3, "event_name": "Japanese Grand Prix", "circuit_name": "Suzuka", "country": "Japan"},
    ]

    result = resolver.resolve_query_context("How did Mercedes do in Japan?")

    assert result["entity_type"] == "team"
    assert result["entity_name"] == "Mercedes"
    assert result["round_number"] == 3
    assert result["suggested_tool"] == "get_team_weekend_overview"


@patch('resolver.get_drivers')
@patch('resolver.get_circuits')
def test_resolve_query_context_race_report(mock_circuits, mock_drivers):
    mock_drivers.return_value = []
    mock_circuits.return_value = [
        {"round": 3, "event_name": "Japanese Grand Prix", "circuit_name": "Suzuka", "country": "Japan"},
    ]

    result = resolver.resolve_query_context("Give me the Japanese GP race recap")

    assert result["round_number"] == 3
    assert result["scope"] == "race_report"
    assert result["suggested_tool"] == "get_race_report"


@patch('resolver.get_drivers')
@patch('resolver.get_circuits')
def test_resolve_query_context_inherits_event_from_previous(mock_circuits, mock_drivers):
    mock_drivers.return_value = [
        {"full_name": "George Russell", "code": "RUS", "driver_id": "russell", "team": "Mercedes"},
        {"full_name": "Lando Norris", "code": "NOR", "driver_id": "norris", "team": "McLaren"},
    ]
    mock_circuits.return_value = [
        {"round": 3, "event_name": "Japanese Grand Prix", "circuit_name": "Suzuka", "country": "Japan"},
    ]

    previous = resolver.resolve_query_context("How did Lando do at Suzuka?")
    result = resolver.resolve_query_context("Tell me about George here", previous)

    assert result["entity_name"] == "George Russell"
    assert result["round_number"] == 3
    assert result["event_name"] == "Japanese Grand Prix"
    assert result["used_previous_context"] is True


@patch('resolver.get_drivers')
@patch('resolver.get_circuits')
def test_resolve_context_from_history(mock_circuits, mock_drivers):
    mock_drivers.return_value = [
        {"full_name": "George Russell", "code": "RUS", "driver_id": "russell", "team": "Mercedes"},
        {"full_name": "Lando Norris", "code": "NOR", "driver_id": "norris", "team": "McLaren"},
    ]
    mock_circuits.return_value = [
        {"round": 3, "event_name": "Japanese Grand Prix", "circuit_name": "Suzuka", "country": "Japan"},
    ]

    history = [
        {"role": "user", "content": "How did Lando do at Suzuka?"},
        {"role": "assistant", "content": "Answer"},
        {"role": "user", "content": "What about George here?"},
    ]
    result = resolver.resolve_context_from_history(history)

    assert result["entity_name"] == "George Russell"
    assert result["round_number"] == 3
    assert result["used_previous_context"] is True


@patch('resolver.get_drivers')
@patch('resolver.get_circuits')
def test_resolve_query_context_multi_driver_qualifying_analysis(mock_circuits, mock_drivers):
    mock_drivers.return_value = [
        {"full_name": "Lando Norris", "code": "NOR", "driver_id": "norris", "team": "McLaren"},
        {"full_name": "Charles Leclerc", "code": "LEC", "driver_id": "leclerc", "team": "Ferrari"},
    ]
    mock_circuits.return_value = [
        {"round": 3, "event_name": "Japanese Grand Prix", "circuit_name": "Suzuka", "country": "Japan"},
    ]

    result = resolver.resolve_query_context("Can you explain how Leclerc beat Lando in qualifying at Suzuka?")

    assert result["entity_type"] == "multi_driver"
    assert result["entity_names"] == ["Charles Leclerc", "Lando Norris"]
    assert result["entity_codes"] == ["LEC", "NOR"]
    assert result["round_number"] == 3
    assert result["analysis_mode"] == "driver_comparison"
    assert result["analysis_focus"] == "qualifying"


@patch('resolver.get_drivers')
@patch('resolver.get_circuits')
def test_resolve_query_context_inherits_multi_driver_analysis_context(mock_circuits, mock_drivers):
    mock_drivers.return_value = [
        {"full_name": "Lando Norris", "code": "NOR", "driver_id": "norris", "team": "McLaren"},
        {"full_name": "Charles Leclerc", "code": "LEC", "driver_id": "leclerc", "team": "Ferrari"},
    ]
    mock_circuits.return_value = [
        {"round": 3, "event_name": "Japanese Grand Prix", "circuit_name": "Suzuka", "country": "Japan"},
    ]

    previous = resolver.resolve_query_context("How did Leclerc beat Lando in qualifying at Suzuka?")
    result = resolver.resolve_query_context("Where exactly did he get the edge there?", previous)

    assert result["round_number"] == 3
    assert result["used_previous_context"] is True
    assert result["analysis_mode"] == "driver_comparison"
    assert result["entity_names"] == ["Charles Leclerc", "Lando Norris"]


@patch('resolver.get_drivers')
@patch('resolver.get_circuits')
def test_resolve_query_context_energy_scope(mock_circuits, mock_drivers):
    mock_drivers.return_value = [
        {"full_name": "Lando Norris", "code": "NOR", "driver_id": "norris", "team": "McLaren"},
    ]
    mock_circuits.return_value = [
        {"round": 3, "event_name": "Japanese Grand Prix", "circuit_name": "Suzuka", "country": "Japan"},
    ]

    result = resolver.resolve_query_context("Was Norris clipping at Suzuka qualifying?")

    assert result["entity_type"] == "driver"
    assert result["entity_code"] == "NOR"
    assert result["scope"] == "energy"
    assert result["suggested_tool"] == "analyze_energy_management"


@patch('resolver.get_drivers')
@patch('resolver.get_circuits')
def test_resolve_query_context_prefers_explicit_japan_over_other_rounds(mock_circuits, mock_drivers):
    mock_drivers.return_value = [
        {"full_name": "Lando Norris", "code": "NOR", "driver_id": "norris", "team": "McLaren"},
        {"full_name": "Charles Leclerc", "code": "LEC", "driver_id": "leclerc", "team": "Ferrari"},
    ]
    mock_circuits.return_value = [
        {"round": 1, "event_name": "Australian Grand Prix", "circuit_name": "Albert Park", "country": "Australia"},
        {"round": 3, "event_name": "Japanese Grand Prix", "circuit_name": "Suzuka", "country": "Japan"},
    ]

    result = resolver.resolve_query_context("Why was Leclerc faster than Lando in qualifying at Suzuka?")

    assert result["round_number"] == 3
    assert result["event_name"] == "Japanese Grand Prix"


@patch('resolver.get_drivers')
@patch('resolver.get_circuits')
def test_resolve_query_context_detects_quali_shorthand(mock_circuits, mock_drivers):
    mock_drivers.return_value = [
        {"full_name": "Lando Norris", "code": "NOR", "driver_id": "norris", "team": "McLaren"},
        {"full_name": "Charles Leclerc", "code": "LEC", "driver_id": "leclerc", "team": "Ferrari"},
    ]
    mock_circuits.return_value = [
        {"round": 3, "event_name": "Japanese Grand Prix", "circuit_name": "Suzuka", "country": "Japan"},
    ]

    result = resolver.resolve_query_context("Why was Leclerc faster than Lando in quali at Suzuka?")

    assert result["session_type"] == "Q"
    assert result["scope"] == "qualifying"
    assert result["analysis_mode"] == "driver_comparison"
    assert result["analysis_focus"] == "qualifying"


@patch('resolver.get_drivers')
@patch('resolver.get_circuits')
def test_match_event_montreal(mock_circuits, mock_drivers):
    mock_drivers.return_value = []
    mock_circuits.return_value = [
        {"round": 9, "event_name": "Canadian Grand Prix", "circuit_name": "Circuit Gilles Villeneuve", "country": "Canada"},
    ]
    result = resolver.resolve_query_context("What happened at Montreal this year?")
    assert result["round_number"] == 9


@patch('resolver.get_drivers')
@patch('resolver.get_circuits')
def test_match_event_sakhir(mock_circuits, mock_drivers):
    mock_drivers.return_value = []
    mock_circuits.return_value = [
        {"round": 1, "event_name": "Bahrain Grand Prix", "circuit_name": "Bahrain International Circuit", "country": "Bahrain"},
    ]
    result = resolver.resolve_query_context("Tell me about the Sakhir race")
    assert result["round_number"] == 1


@patch('resolver.get_drivers')
@patch('resolver.get_circuits')
def test_match_event_budapest(mock_circuits, mock_drivers):
    mock_drivers.return_value = []
    mock_circuits.return_value = [
        {"round": 13, "event_name": "Hungarian Grand Prix", "circuit_name": "Hungaroring", "country": "Hungary"},
    ]
    result = resolver.resolve_query_context("How was the race in Budapest?")
    assert result["round_number"] == 13


@patch('resolver.get_drivers')
@patch('resolver.get_circuits')
def test_suggest_tool_qualifying_strategy_not_race_story(mock_circuits, mock_drivers):
    """Qualifying scope with 'strategy' keyword must NOT route to get_driver_race_story."""
    mock_drivers.return_value = [
        {"full_name": "Lewis Hamilton", "code": "HAM", "driver_id": "hamilton", "team": "Ferrari"},
    ]
    mock_circuits.return_value = [
        {"round": 3, "event_name": "Japanese Grand Prix", "circuit_name": "Suzuka", "country": "Japan"},
    ]
    result = resolver.resolve_query_context("What was Hamilton's qualifying strategy at Suzuka?")
    assert result["session_type"] == "Q"
    assert result["suggested_tool"] != "get_driver_race_story"


@patch('resolver.get_drivers')
@patch('resolver.get_circuits')
def test_detect_analysis_mode_outqualify(mock_circuits, mock_drivers):
    mock_drivers.return_value = [
        {"full_name": "Lando Norris", "code": "NOR", "driver_id": "norris", "team": "McLaren"},
        {"full_name": "Charles Leclerc", "code": "LEC", "driver_id": "leclerc", "team": "Ferrari"},
    ]
    mock_circuits.return_value = [
        {"round": 3, "event_name": "Japanese Grand Prix", "circuit_name": "Suzuka", "country": "Japan"},
    ]
    result = resolver.resolve_query_context("How did Norris outqualify Leclerc at Suzuka?")
    assert result["analysis_mode"] == "driver_comparison"
    assert result["analysis_focus"] == "qualifying"


@patch('resolver.get_drivers')
@patch('resolver.get_circuits')
def test_detect_analysis_mode_gap_between(mock_circuits, mock_drivers):
    mock_drivers.return_value = [
        {"full_name": "Max Verstappen", "code": "VER", "driver_id": "verstappen", "team": "Red Bull"},
        {"full_name": "Lando Norris", "code": "NOR", "driver_id": "norris", "team": "McLaren"},
    ]
    mock_circuits.return_value = [
        {"round": 3, "event_name": "Japanese Grand Prix", "circuit_name": "Suzuka", "country": "Japan"},
    ]
    result = resolver.resolve_query_context("What was the gap between Verstappen and Norris in the race at Suzuka?")
    assert result["analysis_mode"] == "driver_comparison"
