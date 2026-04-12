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
