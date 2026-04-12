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
