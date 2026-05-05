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


@patch('resolver.get_drivers')
@patch('resolver.get_circuits')
def test_resolve_query_context_race_pace_comparison(mock_circuits, mock_drivers):
    mock_drivers.return_value = [
        {"full_name": "Max Verstappen", "code": "VER", "driver_id": "verstappen", "team": "Red Bull"},
        {"full_name": "Lando Norris", "code": "NOR", "driver_id": "norris", "team": "McLaren"},
    ]
    mock_circuits.return_value = [
        {"round": 3, "event_name": "Japanese Grand Prix", "circuit_name": "Suzuka", "country": "Japan"},
    ]

    result = resolver.resolve_query_context("Why did Verstappen pull away from Norris on race pace at Suzuka?")

    assert result["analysis_mode"] == "race_pace_comparison"
    assert result["analysis_focus"] == "race"


@patch('resolver.get_drivers')
@patch('resolver.get_circuits')
def test_resolve_query_context_team_performance_analysis(mock_circuits, mock_drivers):
    mock_drivers.return_value = [
        {"full_name": "Charles Leclerc", "code": "LEC", "driver_id": "leclerc", "team": "Ferrari"},
        {"full_name": "Lewis Hamilton", "code": "HAM", "driver_id": "hamilton", "team": "Ferrari"},
    ]
    mock_circuits.return_value = [
        {"round": 3, "event_name": "Japanese Grand Prix", "circuit_name": "Suzuka", "country": "Japan"},
    ]

    result = resolver.resolve_query_context("What was Ferrari's setup direction through the corners at Suzuka?")

    assert result["entity_type"] == "team"
    assert result["entity_name"] == "Ferrari"
    assert result["analysis_mode"] == "team_performance"


@patch('resolver.get_drivers')
@patch('resolver.get_circuits')
def test_standings_scope_driver(mock_circuits, mock_drivers):
    mock_drivers.return_value = []
    mock_circuits.return_value = []
    result = resolver.resolve_query_context("Who leads the championship?")
    assert result["scope"] == "standings"
    assert result["suggested_tool"] == "get_driver_standings"


@patch('resolver.get_drivers')
@patch('resolver.get_circuits')
def test_standings_scope_constructor(mock_circuits, mock_drivers):
    mock_drivers.return_value = []
    mock_circuits.return_value = []
    result = resolver.resolve_query_context("What are the constructor standings?")
    assert result["scope"] == "standings"
    assert result["suggested_tool"] == "get_constructor_standings"


@patch('resolver.get_drivers')
@patch('resolver.get_circuits')
def test_standings_scope_points_table(mock_circuits, mock_drivers):
    mock_drivers.return_value = []
    mock_circuits.return_value = []
    result = resolver.resolve_query_context("Show me the points table")
    assert result["scope"] == "standings"
    assert result["suggested_tool"] == "get_driver_standings"


@patch('resolver._extract_entities_llm', return_value={})
@patch('resolver.get_drivers')
@patch('resolver.get_circuits')
def test_resolve_query_context_circuit_scope_tell_me_about(mock_circuits, mock_drivers, mock_llm):
    """'tell me about the X circuit' sets scope=circuit and analysis_mode=circuit_profile."""
    mock_drivers.return_value = []
    mock_circuits.return_value = [
        {"round": 6, "event_name": "Miami Grand Prix", "circuit_name": "Miami International Autodrome", "country": "United States"},
    ]

    result = resolver.resolve_query_context("tell me about the miami circuit")

    assert result["scope"] == "circuit"
    assert result["analysis_mode"] == "circuit_profile"
    assert result["country"] == "United States"
    assert result["event_name"] == "Miami Grand Prix"


@patch('resolver._extract_entities_llm', return_value={})
@patch('resolver.get_drivers')
@patch('resolver.get_circuits')
def test_resolve_query_context_circuit_scope_circuit_guide(mock_circuits, mock_drivers, mock_llm):
    """'circuit guide' phrasing also triggers circuit scope."""
    mock_drivers.return_value = []
    mock_circuits.return_value = [
        {"round": 3, "event_name": "Japanese Grand Prix", "circuit_name": "Suzuka Circuit", "country": "Japan"},
    ]

    result = resolver.resolve_query_context("circuit guide for suzuka")

    assert result["scope"] == "circuit"
    assert result["analysis_mode"] == "circuit_profile"
    assert result["country"] == "Japan"


@patch('resolver._extract_entities_llm', return_value={})
@patch('resolver.get_drivers')
@patch('resolver.get_circuits')
def test_resolve_query_context_team_circuit_fit(mock_circuits, mock_drivers, mock_llm):
    mock_circuits.return_value = []
    mock_drivers.return_value = [
        {"full_name": "George Russell", "code": "RUS", "driver_id": "russell", "team": "Mercedes"},
        {"full_name": "Kimi Antonelli", "code": "ANT", "driver_id": "antonelli", "team": "Mercedes"},
    ]

    result = resolver.resolve_query_context("what kind of tracks suit Mercedes")

    assert result["entity_type"] == "team"
    assert result["entity_name"] == "Mercedes"
    assert result["analysis_mode"] == "team_circuit_fit"


@patch('resolver.get_drivers')
@patch('resolver.get_circuits')
def test_pit_strategy_scope_routes_to_pit_stop_analysis(mock_circuits, mock_drivers):
    mock_drivers.return_value = []
    mock_circuits.return_value = [
        {"round": 3, "event_name": "Japanese Grand Prix", "circuit_name": "Suzuka", "country": "Japan"},
    ]

    result = resolver.resolve_query_context("who had the fastest pit stop at Suzuka?")

    assert result["scope"] == "pit_strategy"
    assert result["suggested_tool"] == "get_pit_stop_analysis"


@patch('resolver.get_drivers')
@patch('resolver.get_circuits')
def test_undercut_scope_routes_to_pit_stop_analysis(mock_circuits, mock_drivers):
    mock_drivers.return_value = []
    mock_circuits.return_value = [
        {"round": 3, "event_name": "Japanese Grand Prix", "circuit_name": "Suzuka", "country": "Japan"},
    ]

    result = resolver.resolve_query_context("did anyone undercut at the Japanese GP?")

    assert result["scope"] == "pit_strategy"
    assert result["suggested_tool"] == "get_pit_stop_analysis"


@patch('resolver.get_drivers')
@patch('resolver.get_circuits')
def test_weather_pace_scope_routes_to_weather_correlation(mock_circuits, mock_drivers):
    mock_drivers.return_value = []
    mock_circuits.return_value = [
        {"round": 3, "event_name": "Japanese Grand Prix", "circuit_name": "Suzuka", "country": "Japan"},
    ]

    result = resolver.resolve_query_context("did the track temperature drop affect pace in qualifying at Suzuka?")

    assert result["scope"] == "weather_pace"
    assert result["suggested_tool"] == "analyze_weather_pace_correlation"


@patch('resolver.get_drivers')
@patch('resolver.get_circuits')
def test_degradation_scope_with_driver_routes_to_stint_degradation(mock_circuits, mock_drivers):
    mock_drivers.return_value = [
        {"full_name": "George Russell", "code": "RUS", "driver_id": "russell", "team": "Mercedes"},
    ]
    mock_circuits.return_value = [
        {"round": 3, "event_name": "Japanese Grand Prix", "circuit_name": "Suzuka", "country": "Japan"},
    ]

    result = resolver.resolve_query_context("how was Russell's tyre degradation at Suzuka?")

    assert result["scope"] == "degradation"
    assert result["suggested_tool"] == "analyze_stint_degradation"


@patch('resolver.get_drivers')
@patch('resolver.get_circuits')
def test_degradation_scope_without_driver_returns_no_tool(mock_circuits, mock_drivers):
    mock_drivers.return_value = []
    mock_circuits.return_value = [
        {"round": 3, "event_name": "Japanese Grand Prix", "circuit_name": "Suzuka", "country": "Japan"},
    ]

    result = resolver.resolve_query_context("how was tyre degradation at Suzuka?")

    assert result["scope"] == "degradation"
    assert result.get("suggested_tool") is None


@patch('resolver.get_drivers')
@patch('resolver.get_circuits')
def test_strategy_keyword_without_pit_terms_stays_strategy_scope(mock_circuits, mock_drivers):
    mock_drivers.return_value = [
        {"full_name": "George Russell", "code": "RUS", "driver_id": "russell", "team": "Mercedes"},
    ]
    mock_circuits.return_value = [
        {"round": 3, "event_name": "Japanese Grand Prix", "circuit_name": "Suzuka", "country": "Japan"},
    ]

    result = resolver.resolve_query_context("what was Russell's strategy at Suzuka?")

    assert result["scope"] == "strategy"


@patch('resolver.get_drivers')
@patch('resolver.get_circuits')
def test_fp_scope_routes_to_fp_summary(mock_circuits, mock_drivers):
    mock_drivers.return_value = []
    mock_circuits.return_value = [
        {"round": 3, "event_name": "Japanese Grand Prix", "circuit_name": "Suzuka", "country": "Japan"},
    ]
    result = resolver.resolve_query_context("who was fastest in FP1 at Suzuka?")
    assert result["scope"] == "fp"
    assert result["suggested_tool"] == "get_fp_summary"
    assert result["fp_number"] == 1


@patch('resolver.get_drivers')
@patch('resolver.get_circuits')
def test_fp2_scope_carries_fp_number(mock_circuits, mock_drivers):
    mock_drivers.return_value = []
    mock_circuits.return_value = [
        {"round": 3, "event_name": "Japanese Grand Prix", "circuit_name": "Suzuka", "country": "Japan"},
    ]
    result = resolver.resolve_query_context("what programmes did the drivers run in free practice 2 at Suzuka?")
    assert result["scope"] == "fp"
    assert result["fp_number"] == 2
    assert result["suggested_tool"] == "get_fp_summary"


@patch('resolver.get_drivers')
@patch('resolver.get_circuits')
def test_speed_trap_scope_routes_to_leaderboard(mock_circuits, mock_drivers):
    mock_drivers.return_value = []
    mock_circuits.return_value = [
        {"round": 3, "event_name": "Japanese Grand Prix", "circuit_name": "Suzuka", "country": "Japan"},
    ]
    result = resolver.resolve_query_context("who had the highest top speed in qualifying at Suzuka?")
    assert result["scope"] == "speed_trap"
    assert result["suggested_tool"] == "get_speed_trap_leaderboard"


@patch('resolver.get_drivers')
@patch('resolver.get_circuits')
def test_speed_trap_scope_straight_line_language(mock_circuits, mock_drivers):
    mock_drivers.return_value = []
    mock_circuits.return_value = [
        {"round": 3, "event_name": "Japanese Grand Prix", "circuit_name": "Suzuka", "country": "Japan"},
    ]
    result = resolver.resolve_query_context("who was fastest down the straight in the race at Suzuka?")
    assert result["scope"] == "speed_trap"
    assert result["suggested_tool"] == "get_speed_trap_leaderboard"


def test_suggest_tool_sprint_race_driver_entity():
    from resolver import _suggest_tool
    result = _suggest_tool("driver", "overview", "S")
    assert result == "get_driver_race_story"


def test_suggest_tool_sprint_qualifying_standalone():
    from resolver import _suggest_tool
    result = _suggest_tool(None, "qualifying", "SQ")
    assert result == "get_sprint_qualifying_results"


def test_suggest_tool_sprint_race_no_entity():
    from resolver import _suggest_tool
    result = _suggest_tool(None, "race_report", "S")
    assert result == "get_race_report"


def test_detect_session_scope_sprint_qualifying_gives_sq():
    from resolver import _detect_session_scope
    session_type, scope = _detect_session_scope("sprint qualifying at miami")
    assert session_type == "SQ", f"expected SQ, got {session_type}"


def test_detect_session_scope_sprint_quali_gives_sq():
    from resolver import _detect_session_scope
    session_type, scope = _detect_session_scope("sprint quali at miami")
    assert session_type == "SQ"


def test_detect_session_scope_sq_gives_sq():
    from resolver import _detect_session_scope
    session_type, scope = _detect_session_scope("who was fastest in sq at miami")
    assert session_type == "SQ"


def test_detect_session_scope_sprint_shootout_gives_sq():
    from resolver import _detect_session_scope
    session_type, _ = _detect_session_scope("recap the sprint shootout")
    assert session_type == "SQ"


def test_detect_session_scope_plain_qualifying_still_gives_q():
    from resolver import _detect_session_scope
    session_type, scope = _detect_session_scope("how did norris do in qualifying")
    assert session_type == "Q"


def test_detect_session_scope_sprint_race_gives_s():
    from resolver import _detect_session_scope
    session_type, _ = _detect_session_scope("how did piastri do in the sprint")
    assert session_type == "S"


@patch('resolver._extract_entities_llm', return_value={})
@patch('resolver.get_drivers')
@patch('resolver.get_circuits')
def test_single_driver_sprint_qualifying_routes_to_sprint_qualifying_results(mock_circuits, mock_drivers, mock_llm):
    mock_drivers.return_value = [
        {"full_name": "Lando Norris", "code": "NOR", "driver_id": "norris", "team": "McLaren"},
    ]
    mock_circuits.return_value = [
        {"round": 6, "event_name": "Miami Grand Prix", "circuit_name": "Miami", "country": "United States"},
    ]

    result = resolver.resolve_query_context("How did Norris do in sprint qualifying at Miami?")

    assert result["entity_type"] == "driver"
    assert result["session_type"] == "SQ"
    assert result["suggested_tool"] == "get_sprint_qualifying_results"


@patch('resolver._extract_entities_llm', return_value={})
@patch('resolver.get_drivers')
@patch('resolver.get_circuits')
def test_sprint_quali_comparison_uses_sq_analysis(mock_circuits, mock_drivers, mock_llm):
    mock_drivers.return_value = [
        {"full_name": "Lando Norris", "code": "NOR", "driver_id": "norris", "team": "McLaren"},
        {"full_name": "Oscar Piastri", "code": "PIA", "driver_id": "piastri", "team": "McLaren"},
    ]
    mock_circuits.return_value = [
        {"round": 6, "event_name": "Miami Grand Prix", "circuit_name": "Miami", "country": "United States"},
    ]

    result = resolver.resolve_query_context("Why was Norris faster than Piastri in sprint quali at Miami?")

    assert result["session_type"] == "SQ"
    assert result["analysis_mode"] == "driver_comparison"
    assert result["analysis_focus"] == "qualifying"
