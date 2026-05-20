# server/tests/test_tools.py
import pytest
from unittest.mock import patch
import tools


def test_execute_tool_get_driver_standings_returns_sliced_list():
    mock_drivers = [
        {"full_name": "Max Verstappen", "team": "Red Bull", "standing": 1,
         "points": 150.0, "wins": 4, "code": "VER", "nationality": "Dutch",
         "driver_id": "verstappen"},
        {"full_name": "Lando Norris", "team": "McLaren", "standing": 2,
         "points": 120.0, "wins": 2, "code": "NOR", "nationality": "British",
         "driver_id": "norris"},
    ]
    with patch('tools.get_drivers', return_value=mock_drivers):
        result = tools.execute_tool("get_driver_standings", {"limit": 1})
    assert len(result) == 1
    assert result[0]["full_name"] == "Max Verstappen"


def test_execute_tool_get_driver_standings_default_limit():
    mock_drivers = [{"full_name": f"Driver {i}", "standing": i} for i in range(1, 22)]
    with patch('tools.get_drivers', return_value=mock_drivers):
        result = tools.execute_tool("get_driver_standings", {})
    assert len(result) == 20  # default limit


def test_execute_tool_get_constructor_standings():
    mock = [{"team": "Red Bull Racing", "position": 1, "points": 200.0, "wins": 4}]
    with patch('tools.get_constructor_standings', return_value=mock):
        result = tools.execute_tool("get_constructor_standings", {})
    assert result[0]["team"] == "Red Bull Racing"


def test_execute_tool_get_driver_season_stats_found():
    mock_stats = {"driver": "Lando Norris", "wins": 2, "podiums": 6, "points": 120.0}
    with patch('tools.get_driver_stats', return_value=mock_stats):
        result = tools.execute_tool("get_driver_season_stats", {"driver_name": "norris"})
    assert result["driver"] == "Lando Norris"


def test_execute_tool_get_driver_season_stats_not_found():
    with patch('tools.get_driver_stats', return_value=None):
        with pytest.raises(ValueError, match="not found"):
            tools.execute_tool("get_driver_season_stats", {"driver_name": "nobody"})


def test_execute_tool_get_race_results():
    mock = {"race_name": "Bahrain Grand Prix", "results": []}
    with patch('tools.get_race_results', return_value=mock):
        result = tools.execute_tool("get_race_results", {"round_number": 1})
    assert result["race_name"] == "Bahrain Grand Prix"


def test_execute_tool_get_qualifying_results():
    mock = {"race_name": "Bahrain Grand Prix", "results": []}
    with patch('tools.get_qualifying_results', return_value=mock):
        result = tools.execute_tool("get_qualifying_results", {"round_number": 1})
    assert result["race_name"] == "Bahrain Grand Prix"


def test_execute_tool_get_season_schedule():
    mock = [{"round": 1, "event_name": "Bahrain Grand Prix", "date": "2025-03-02"}]
    with patch('tools.get_circuits', return_value=mock):
        result = tools.execute_tool("get_season_schedule", {})
    assert result[0]["event_name"] == "Bahrain Grand Prix"


def test_execute_tool_get_head_to_head():
    mock = {"driver_a": "Max Verstappen", "driver_b": "Lando Norris",
            "points_gap": 30.0, "races_a_ahead": 5, "races_b_ahead": 3}
    with patch('tools.get_head_to_head', return_value=mock):
        result = tools.execute_tool("get_head_to_head",
                                    {"driver_a": "verstappen", "driver_b": "norris"})
    assert result["driver_a"] == "Max Verstappen"


def test_execute_tool_get_session_fastest_laps():
    mock = [{"driver": "NOR", "position": 1, "lap_time": "1:26.456"}]
    with patch('tools.get_session_fastest_laps', return_value=mock):
        result = tools.execute_tool("get_session_fastest_laps",
                                    {"round_number": 8, "session_type": "Q"})
    assert result[0]["driver"] == "NOR"


def test_execute_tool_get_driver_lap_times():
    mock = {"driver": "NOR", "laps": [{"lap_number": 1, "lap_time": "1:26.456"}]}
    with patch('tools.get_driver_lap_times', return_value=mock):
        result = tools.execute_tool("get_driver_lap_times",
                                    {"round_number": 8, "session_type": "Q", "driver_code": "NOR"})
    assert result["driver"] == "NOR"


def test_execute_tool_get_sector_comparison():
    mock = {"driver_a": "NOR", "driver_b": "LEC", "overall_gap_s": -0.256}
    with patch('tools.get_sector_comparison', return_value=mock):
        result = tools.execute_tool("get_sector_comparison",
                                    {"round_number": 8, "session_type": "Q",
                                     "driver_a": "NOR", "driver_b": "LEC"})
    assert result["overall_gap_s"] == -0.256


def test_execute_tool_get_lap_telemetry():
    mock = {"driver": "NOR", "telemetry": [{"distance_m": 0, "speed_kph": 150.0}]}
    with patch('tools.get_lap_telemetry', return_value=mock):
        result = tools.execute_tool("get_lap_telemetry",
                                    {"round_number": 8, "session_type": "Q", "driver_code": "NOR"})
    assert result["driver"] == "NOR"


def test_execute_tool_analyze_energy_management():
    mock = {"mode": "comparison", "confidence": "medium", "inference_summary": ["Likely clipping signal."]}
    with patch('tools.analyze_energy_management', return_value=mock):
        result = tools.execute_tool("analyze_energy_management", {
            "round_number": 3, "session_type": "Q", "driver_a": "LEC", "driver_b": "NOR"
        })
    assert result["mode"] == "comparison"
    assert result["confidence"] == "medium"


def test_execute_tool_analyze_qualifying_battle():
    mock = {"faster_driver": "LEC", "cause_type": "straight_line_speed", "decisive_sector": "Sector 1"}
    with patch('tools.analyze_qualifying_battle', return_value=mock):
        result = tools.execute_tool("analyze_qualifying_battle", {
            "round_number": 3, "driver_a": "LEC", "driver_b": "NOR"
        })
    assert result["faster_driver"] == "LEC"
    assert result["decisive_sector"] == "Sector 1"


def test_execute_tool_get_team_radio():
    mock = {"messages": [{"recording_url": "https://example.test/radio.mp3"}]}
    with patch('tools.get_team_radio', return_value=mock):
        result = tools.execute_tool("get_team_radio", {"round_number": 3, "session_type": "Q", "driver_ref": "NOR"})
    assert result["messages"][0]["recording_url"].endswith(".mp3")


def test_execute_tool_get_intervals():
    mock = {"intervals": [{"gap_to_leader": "+3.2"}]}
    with patch('tools.get_intervals', return_value=mock):
        result = tools.execute_tool("get_intervals", {"round_number": 3})
    assert result["intervals"][0]["gap_to_leader"] == "+3.2"


def test_execute_tool_get_live_position_timeline():
    mock = {"positions": [{"position": 4}]}
    with patch('tools.get_live_position_timeline', return_value=mock):
        result = tools.execute_tool("get_live_position_timeline", {"round_number": 3, "session_type": "R"})
    assert result["positions"][0]["position"] == 4


def test_execute_tool_unknown_raises_value_error():
    with pytest.raises(ValueError, match="Unknown tool"):
        tools.execute_tool("launch_rocket", {})


def test_tool_definitions_are_valid_schemas():
    """Every tool definition must have name, description, and input_schema."""
    for tool in tools.TOOL_DEFINITIONS:
        assert "name" in tool
        assert "description" in tool
        assert len(tool["description"]) > 20, f"Tool {tool['name']} description too short"
        assert "input_schema" in tool
        assert tool["input_schema"]["type"] == "object"


def test_tool_definitions_count():
    """Tool registry should include the expanded FastF1 analysis surface."""
    assert len(tools.TOOL_DEFINITIONS) >= 20


def test_execute_tool_get_telemetry_comparison():
    mock = {"driver_a": "NOR", "driver_b": "LEC", "comparison": [{"distance_m": 0, "delta_speed": 5.0}]}
    with patch('tools.get_telemetry_comparison', return_value=mock):
        result = tools.execute_tool("get_telemetry_comparison", {
            "round_number": 8, "session_type": "Q",
            "driver_a": "NOR", "driver_b": "LEC"
        })
    assert result["driver_a"] == "NOR"
    assert result["comparison"][0]["delta_speed"] == 5.0


def test_execute_tool_get_circuit_corners():
    mock = [{"number": 1, "label": None, "distance_m": 150}]
    with patch('tools.get_circuit_corners', return_value=mock):
        result = tools.execute_tool("get_circuit_corners", {"round_number": 8})
    assert result[0]["number"] == 1


def test_execute_tool_get_historical_circuit_performance():
    mock = {"circuit_id": "monaco", "history": [{"year": 2024}]}
    with patch('tools.get_historical_circuit_performance', return_value=mock):
        result = tools.execute_tool("get_historical_circuit_performance", {"round_number": 8})
    assert result["circuit_id"] == "monaco"


def test_execute_tool_get_session_results():
    mock = {"event": "Bahrain Grand Prix", "results": [{"driver": "Max Verstappen"}]}
    with patch('tools.get_session_results', return_value=mock):
        result = tools.execute_tool("get_session_results", {"round_number": 1, "session_type": "R"})
    assert result["results"][0]["driver"] == "Max Verstappen"


def test_execute_tool_get_driver_strategy():
    mock = {"drivers": [{"driver": "Lando Norris", "pit_stop_count": 1}]}
    with patch('tools.get_driver_strategy', return_value=mock):
        result = tools.execute_tool("get_driver_strategy", {"round_number": 1, "session_type": "R", "driver_code": "NOR"})
    assert result["drivers"][0]["pit_stop_count"] == 1


def test_execute_tool_get_qualifying_progression():
    mock = {"drivers": [{"abbreviation": "NOR", "made_q3": True}]}
    with patch('tools.get_qualifying_progression', return_value=mock):
        result = tools.execute_tool("get_qualifying_progression", {"round_number": 1})
    assert result["drivers"][0]["made_q3"] is True


def test_execute_tool_get_clean_pace_summary():
    mock = {"drivers": [{"abbreviation": "NOR", "rank": 1}]}
    with patch('tools.get_clean_pace_summary', return_value=mock):
        result = tools.execute_tool("get_clean_pace_summary", {"round_number": 1, "session_type": "Q"})
    assert result["drivers"][0]["rank"] == 1


def test_execute_tool_get_track_position_comparison():
    mock = {"comparison": [{"distance_m": 100, "delta_speed": 3.5}]}
    with patch('tools.get_track_position_comparison', return_value=mock):
        result = tools.execute_tool("get_track_position_comparison", {
            "round_number": 1, "session_type": "Q", "driver_a": "NOR", "driver_b": "LEC"
        })
    assert result["comparison"][0]["delta_speed"] == 3.5


def test_execute_tool_get_circuit_details():
    mock = {"rotation": 90.0, "corners": []}
    with patch('tools.get_circuit_details', return_value=mock):
        result = tools.execute_tool("get_circuit_details", {"round_number": 1})
    assert result["rotation"] == 90.0


def test_execute_tool_get_race_control_messages():
    mock = {"messages": [{"category": "Track Limits", "message": "Lap deleted"}]}
    with patch('tools.get_race_control_messages', return_value=mock):
        result = tools.execute_tool("get_race_control_messages", {"round_number": 1, "session_type": "Q"})
    assert result["messages"][0]["message"] == "Lap deleted"


def test_execute_tool_get_driver_weekend_overview():
    mock = {"driver": "George Russell", "race": {"finish_position": 4}}
    with patch('tools.get_driver_weekend_overview', return_value=mock):
        result = tools.execute_tool("get_driver_weekend_overview", {"round_number": 3, "driver_name": "Russell"})
    assert result["race"]["finish_position"] == 4


def test_execute_tool_get_driver_race_story():
    mock = {"driver": "George Russell", "story_points": ["Gained 2 places."]}
    with patch('tools.get_driver_race_story', return_value=mock):
        result = tools.execute_tool("get_driver_race_story", {"round_number": 3, "driver_name": "Russell"})
    assert result["story_points"][0] == "Gained 2 places."


def test_execute_tool_get_team_weekend_overview():
    mock = {"team": "Mercedes", "total_points": 20.0}
    with patch('tools.get_team_weekend_overview', return_value=mock):
        result = tools.execute_tool("get_team_weekend_overview", {"round_number": 3, "team_name": "Mercedes"})
    assert result["total_points"] == 20.0


def test_execute_tool_get_race_report():
    mock = {"event": "Japanese Grand Prix", "podium": [{"driver": "Max Verstappen"}]}
    with patch('tools.get_race_report', return_value=mock):
        result = tools.execute_tool("get_race_report", {"round_number": 3})
    assert result["podium"][0]["driver"] == "Max Verstappen"


def test_execute_tool_extract_corner_profiles():
    mock = {"driver": "NOR", "corner_profiles": {"corner_1": {"apex_gear": 4}}}
    with patch('tools.extract_corner_profiles', return_value=mock):
        result = tools.execute_tool("extract_corner_profiles", {
            "round_number": 3,
            "session_type": "Q",
            "driver_code": "NOR",
        })
    assert result["corner_profiles"]["corner_1"]["apex_gear"] == 4


def test_execute_tool_compare_corner_profiles():
    mock = {"driver_a": "NOR", "driver_b": "LEC", "setup_direction_inference": "corner_heavy"}
    with patch('tools.compare_corner_profiles', return_value=mock):
        result = tools.execute_tool("compare_corner_profiles", {
            "round_number": 3,
            "session_type": "Q",
            "driver_a": "NOR",
            "driver_b": "LEC",
        })
    assert result["setup_direction_inference"] == "corner_heavy"


def test_execute_tool_analyze_stint_degradation():
    mock = {"driver": "NOR", "stints": [{"compound": "MEDIUM"}]}
    with patch('tools.analyze_stint_degradation', return_value=mock):
        result = tools.execute_tool("analyze_stint_degradation", {
            "round_number": 3,
            "driver_code": "NOR",
        })
    assert result["stints"][0]["compound"] == "MEDIUM"


def test_execute_tool_analyze_race_pace_battle():
    mock = {"driver_a": "NOR", "driver_b": "LEC", "decisive_factor": "raw_pace_advantage"}
    with patch('tools.analyze_race_pace_battle', return_value=mock):
        result = tools.execute_tool("analyze_race_pace_battle", {
            "round_number": 3,
            "driver_a": "NOR",
            "driver_b": "LEC",
        })
    assert result["decisive_factor"] == "raw_pace_advantage"


def test_execute_tool_analyze_team_performance():
    mock = {"team": "Ferrari", "setup_direction_inference": "balanced"}
    with patch('tools.analyze_team_performance', return_value=mock):
        result = tools.execute_tool("analyze_team_performance", {
            "round_number": 3,
            "team_name": "Ferrari",
            "session_type": "Q",
        })
    assert result["team"] == "Ferrari"


def test_get_team_car_profile_logs_warning_on_missing_team(caplog):
    with patch('tools.get_team_car_profile', return_value=None):
        with caplog.at_level("WARNING", logger="tools"):
            result = tools.execute_tool("get_team_car_profile", {"team_name": "NotARealTeam"})
    assert result["available"] is False
    assert "guidance_for_model" in result
    warnings = [r for r in caplog.records if r.levelname == "WARNING"]
    assert any("NotARealTeam" in r.getMessage() and "team_car_profiles.py" in r.getMessage()
               for r in warnings)


def test_get_driver_style_profile_logs_warning_on_missing_driver(caplog):
    with patch('tools.get_driver_style', return_value=None):
        with caplog.at_level("WARNING", logger="tools"):
            result = tools.execute_tool("get_driver_style_profile", {"driver_a": "ZZZ"})
    assert result["available"] is False
    assert "guidance_for_model" in result
    warnings = [r for r in caplog.records if r.levelname == "WARNING"]
    assert any("ZZZ" in r.getMessage() and "driver_styles.py" in r.getMessage()
               for r in warnings)


def test_get_driver_style_profile_logs_warning_on_missing_comparison_pair(caplog):
    with patch('tools.get_comparison_framing', return_value=None), \
         patch('tools.get_driver_style', return_value=None):
        with caplog.at_level("WARNING", logger="tools"):
            result = tools.execute_tool(
                "get_driver_style_profile",
                {"driver_a": "AAA", "driver_b": "BBB"},
            )
    assert result["available"] is False
    assert "guidance_for_model" in result
    warnings = [r for r in caplog.records if r.levelname == "WARNING"]
    assert any("AAA" in r.getMessage() and "BBB" in r.getMessage() for r in warnings)

def test_execute_tool_analyze_team_circuit_fit():
    mock = {"team_query": "Mercedes", "strongest_fit": {"character": "stop_and_go"}}
    with patch('tools.analyze_team_circuit_fit', return_value=mock):
        result = tools.execute_tool("analyze_team_circuit_fit", {
            "team_name": "Mercedes",
            "years": [2023, 2024],
            "session_type": "Q",
        })
    assert result["strongest_fit"]["character"] == "stop_and_go"


def test_execute_tool_analyze_team_telemetry_traits():
    mock = {"team": "Mercedes", "trait_flags": ["straight_line_speed"]}
    with patch('tools.analyze_team_telemetry_traits', return_value=mock):
        result = tools.execute_tool("analyze_team_telemetry_traits", {
            "round_number": 3,
            "team_name": "Mercedes",
            "session_type": "Q",
        })
    assert result["trait_flags"] == ["straight_line_speed"]


def test_execute_tool_get_team_car_profile():
    result = tools.execute_tool("get_team_car_profile", {"team_name": "Ferrari"})
    assert result["team"] == "Ferrari"
    assert result["profile_type"] == "curated_editorial"


def test_execute_tool_get_team_car_profile_missing_returns_available_false():
    result = tools.execute_tool("get_team_car_profile", {"team_name": "McLaren"})
    assert result["available"] is False


def test_execute_tool_get_sprint_results():
    mock = {"session": "S", "race_name": "Chinese Grand Prix", "results": []}
    with patch('tools.get_sprint_results', return_value=mock):
        result = tools.execute_tool("get_sprint_results", {"round_number": 5})
    assert result["session"] == "S"


def test_execute_tool_get_sprint_qualifying_results():
    mock = {"session": "SQ", "race_name": "Chinese Grand Prix", "results": []}
    with patch('tools.get_sprint_qualifying_results', return_value=mock):
        result = tools.execute_tool("get_sprint_qualifying_results", {"round_number": 5})
    assert result["session"] == "SQ"


def test_execute_tool_get_driver_race_story_passes_session_type():
    mock = {"driver": "Lando Norris", "story_points": []}
    with patch('tools.get_driver_race_story', return_value=mock) as mock_fn:
        tools.execute_tool("get_driver_race_story", {"round_number": 5, "driver_name": "norris", "session_type": "S"})
    mock_fn.assert_called_once_with(5, "norris", session_type="S")


def test_execute_tool_get_driver_race_story_defaults_to_r():
    mock = {"driver": "Lando Norris", "story_points": []}
    with patch('tools.get_driver_race_story', return_value=mock) as mock_fn:
        tools.execute_tool("get_driver_race_story", {"round_number": 5, "driver_name": "norris"})
    mock_fn.assert_called_once_with(5, "norris", session_type="R")


def test_execute_tool_analyze_qualifying_battle_passes_session_type():
    mock = {"session": "SQ", "driver_a": "NOR", "driver_b": "PIA"}
    with patch('tools.analyze_qualifying_battle', return_value=mock) as mock_fn:
        tools.execute_tool("analyze_qualifying_battle", {"round_number": 5, "driver_a": "NOR", "driver_b": "PIA", "session_type": "SQ"})
    mock_fn.assert_called_once_with(5, "NOR", "PIA", session_type="SQ")


def test_require_args_raises_value_error_listing_missing_keys():
    with pytest.raises(ValueError) as exc_info:
        tools._require_args({"round_number": 5}, ["round_number", "driver_a", "driver_b"], "some_tool")
    msg = str(exc_info.value)
    assert "some_tool" in msg
    assert "driver_a" in msg
    assert "driver_b" in msg
    assert "round_number" not in msg


def test_require_args_treats_none_and_empty_string_as_missing():
    with pytest.raises(ValueError) as exc_info:
        tools._require_args({"driver_name": None, "round_number": ""}, ["driver_name", "round_number"], "t")
    msg = str(exc_info.value)
    assert "driver_name" in msg
    assert "round_number" in msg


def test_require_args_passes_when_all_provided():
    tools._require_args({"a": 1, "b": "x"}, ["a", "b"], "t")


def test_execute_tool_missing_driver_name_raises_value_error():
    with pytest.raises(ValueError) as exc_info:
        tools.execute_tool("get_driver_season_stats", {})
    assert "driver_name" in str(exc_info.value)
    assert "get_driver_season_stats" in str(exc_info.value)


def test_execute_tool_missing_round_number_raises_value_error():
    with pytest.raises(ValueError) as exc_info:
        tools.execute_tool("get_race_results", {})
    assert "round_number" in str(exc_info.value)
    assert "get_race_results" in str(exc_info.value)


def test_execute_tool_missing_driver_a_and_b_raises_value_error_listing_both():
    with pytest.raises(ValueError) as exc_info:
        tools.execute_tool("get_head_to_head", {})
    msg = str(exc_info.value)
    assert "driver_a" in msg
    assert "driver_b" in msg
