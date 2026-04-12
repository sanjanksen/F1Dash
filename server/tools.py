"""
Tool definitions for both Anthropic and OpenAI agentic loops.

Tool taxonomy:
- Composite recap tools: broad user-facing summaries and narratives
- Primitive tools: factual building blocks for narrower questions
- Deep analysis primitives: telemetry, pace, race control, weather

The model should prefer composite recap tools for broad "tell me about..."
questions and use primitives for focused follow-ups.
"""
from f1_data import (
    get_circuit_corners,
    get_circuit_details,
    get_circuits,
    get_clean_pace_summary,
    get_constructor_standings,
    get_driver_lap_times,
    get_driver_race_story,
    get_driver_stats,
    get_driver_strategy,
    get_driver_weekend_overview,
    get_drivers,
    get_head_to_head,
    get_historical_circuit_performance,
    get_lap_telemetry,
    get_qualifying_progression,
    get_qualifying_results,
    get_race_control_messages,
    get_race_report,
    get_race_results,
    get_safety_car_periods,
    get_sector_comparison,
    get_session_fastest_laps,
    get_session_results,
    get_session_weather,
    get_team_weekend_overview,
    get_telemetry_comparison,
    get_track_position_comparison,
)


def _tool(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {
        "name": name,
        "description": description,
        "input_schema": {
            "type": "object",
            "properties": properties,
            "required": required,
        },
    }


COMPOSITE_TOOL_DEFINITIONS = [
    _tool(
        "get_driver_race_story",
        "COMPOSITE RECAP TOOL. Narrative-ready race story for one driver in one round. "
        "Use this first for broad prompts like 'how did Russell's race go?' or 'talk me through Norris's race'.",
        {
            "round_number": {"type": "integer", "description": "The 2026 season round number."},
            "driver_name": {"type": "string", "description": "Driver full name, surname, or 3-letter code."},
        },
        ["round_number", "driver_name"],
    ),
    _tool(
        "get_driver_weekend_overview",
        "COMPOSITE RECAP TOOL. High-level factual weekend or race overview for one driver. "
        "Use this for broad driver recap questions when you want summary structure more than narrative.",
        {
            "round_number": {"type": "integer", "description": "The 2026 season round number."},
            "driver_name": {"type": "string", "description": "Driver full name, surname, or 3-letter code."},
        },
        ["round_number", "driver_name"],
    ),
    _tool(
        "get_team_weekend_overview",
        "COMPOSITE RECAP TOOL. High-level weekend overview for a team across both drivers. "
        "Use this first for broad prompts like 'how did Ferrari do this weekend?'.",
        {
            "round_number": {"type": "integer", "description": "The 2026 season round number."},
            "team_name": {"type": "string", "description": "Current constructor name or close match."},
        },
        ["round_number", "team_name"],
    ),
    _tool(
        "get_race_report",
        "COMPOSITE RECAP TOOL. Whole-race recap independent of any one driver or team. "
        "Use this first for broad race recap prompts like 'what happened in the race?'.",
        {
            "round_number": {"type": "integer", "description": "The 2026 season round number."},
        },
        ["round_number"],
    ),
]


PRIMITIVE_TOOL_DEFINITIONS = [
    _tool(
        "get_driver_standings",
        "PRIMITIVE TOOL. Current 2026 driver championship standings.",
        {
            "limit": {"type": "integer", "description": "Number of drivers to return (1-20). Defaults to 20."},
        },
        [],
    ),
    _tool(
        "get_constructor_standings",
        "PRIMITIVE TOOL. Current 2026 constructor championship standings.",
        {},
        [],
    ),
    _tool(
        "get_driver_season_stats",
        "PRIMITIVE TOOL. Detailed 2026 season statistics for one driver.",
        {
            "driver_name": {"type": "string", "description": "Driver full name, surname, or 3-letter code."},
        },
        ["driver_name"],
    ),
    _tool(
        "get_season_schedule",
        "PRIMITIVE TOOL. Full 2026 race calendar with rounds, event names, locations, countries, and dates.",
        {},
        [],
    ),
    _tool(
        "get_race_results",
        "PRIMITIVE TOOL. Raw race classification for one round. "
        "Use for pure results lookup, not as the first tool for a broad recap.",
        {
            "round_number": {"type": "integer", "description": "The 2026 season round number."},
        },
        ["round_number"],
    ),
    _tool(
        "get_qualifying_results",
        "PRIMITIVE TOOL. Raw qualifying classification with Q1/Q2/Q3 times for one round.",
        {
            "round_number": {"type": "integer", "description": "The 2026 season round number."},
        },
        ["round_number"],
    ),
    _tool(
        "get_session_results",
        "PRIMITIVE TOOL. Rich FastF1 session classification metadata such as grid, classified position, status, team color, and driver number. "
        "Use for session metadata and penalty-aware classification details.",
        {
            "round_number": {"type": "integer", "description": "The 2026 season round number."},
            "session_type": {"type": "string", "description": "Session type: Q, R, FP1, FP2, FP3, S, SQ, SS."},
        },
        ["round_number", "session_type"],
    ),
    _tool(
        "get_head_to_head",
        "PRIMITIVE TOOL. Compare two drivers across all 2026 races they both contested.",
        {
            "driver_a": {"type": "string", "description": "First driver full name, surname, or 3-letter code."},
            "driver_b": {"type": "string", "description": "Second driver full name, surname, or 3-letter code."},
        },
        ["driver_a", "driver_b"],
    ),
    _tool(
        "get_driver_strategy",
        "PRIMITIVE TOOL. Tyre strategy and stints for one driver or the whole field. "
        "Use for specific pit/strategy questions. For broad race recaps, prefer composite tools first.",
        {
            "round_number": {"type": "integer", "description": "The 2026 season round number."},
            "session_type": {"type": "string", "description": "Session type, usually R or S."},
            "driver_code": {"type": "string", "description": "Optional 3-letter driver code."},
        },
        ["round_number", "session_type"],
    ),
    _tool(
        "get_qualifying_progression",
        "PRIMITIVE TOOL. Q1/Q2/Q3 progression and improvements by driver.",
        {
            "round_number": {"type": "integer", "description": "The 2026 season round number."},
        },
        ["round_number"],
    ),
    _tool(
        "get_session_fastest_laps",
        "PRIMITIVE TOOL. Fastest-lap leaderboard for a session with sectors and speed traps.",
        {
            "round_number": {"type": "integer", "description": "The 2026 season round number."},
            "session_type": {"type": "string", "description": "Session type: Q, R, FP1, FP2, FP3, S, SQ, SS."},
        },
        ["round_number", "session_type"],
    ),
    _tool(
        "get_driver_lap_times",
        "PRIMITIVE TOOL. All laps for one driver in one session, with sectors, compounds, tyre life, and pit flags.",
        {
            "round_number": {"type": "integer", "description": "The 2026 season round number."},
            "session_type": {"type": "string", "description": "Session type: Q, R, FP1, FP2, FP3, S, SQ, SS."},
            "driver_code": {"type": "string", "description": "3-letter driver code."},
        },
        ["round_number", "session_type", "driver_code"],
    ),
    _tool(
        "get_clean_pace_summary",
        "PRIMITIVE TOOL. Clean-lap pace summary filtering out inaccurate, deleted, and pit laps.",
        {
            "round_number": {"type": "integer", "description": "The 2026 season round number."},
            "session_type": {"type": "string", "description": "Session type: Q, R, FP1, FP2, FP3, S, SQ, SS."},
            "driver_codes": {"type": "array", "items": {"type": "string"}, "description": "Optional 3-letter driver codes."},
            "green_only": {"type": "boolean", "description": "Keep only green-flag laps. Defaults to true."},
            "limit": {"type": "integer", "description": "Representative laps per driver. Defaults to 10."},
        },
        ["round_number", "session_type"],
    ),
    _tool(
        "get_sector_comparison",
        "PRIMITIVE TOOL. Fastest-lap sector comparison between two drivers.",
        {
            "round_number": {"type": "integer", "description": "The 2026 season round number."},
            "session_type": {"type": "string", "description": "Session type: Q, R, FP1, FP2, FP3, S, SQ, SS."},
            "driver_a": {"type": "string", "description": "First driver's 3-letter code."},
            "driver_b": {"type": "string", "description": "Second driver's 3-letter code."},
        },
        ["round_number", "session_type", "driver_a", "driver_b"],
    ),
    _tool(
        "get_safety_car_periods",
        "PRIMITIVE TOOL. SC/VSC timing and pit-stop impact for a session. "
        "Use for specific safety-car questions. For broad race recaps, prefer composite tools first.",
        {
            "round_number": {"type": "integer", "description": "The 2026 season round number."},
            "session_type": {"type": "string", "description": "Session type, usually R or S."},
        },
        ["round_number", "session_type"],
    ),
    _tool(
        "get_session_weather",
        "PRIMITIVE TOOL. Weather evolution through a session.",
        {
            "round_number": {"type": "integer", "description": "The 2026 season round number."},
            "session_type": {"type": "string", "description": "Session type: Q, R, FP1, FP2, FP3, S, SQ, SS."},
        },
        ["round_number", "session_type"],
    ),
    _tool(
        "get_circuit_corners",
        "PRIMITIVE TOOL. Circuit corner map with corner numbers and distances.",
        {
            "round_number": {"type": "integer", "description": "The 2026 season round number."},
        },
        ["round_number"],
    ),
    _tool(
        "get_circuit_details",
        "PRIMITIVE TOOL. Circuit metadata including corners, marshal lights, marshal sectors, and rotation.",
        {
            "round_number": {"type": "integer", "description": "The 2026 season round number."},
        },
        ["round_number"],
    ),
    _tool(
        "get_historical_circuit_performance",
        "PRIMITIVE TOOL. Historical quali/race top performers for the same circuit across recent years.",
        {
            "round_number": {"type": "integer", "description": "The 2026 season round number."},
            "years": {"type": "array", "items": {"type": "integer"}, "description": "Optional years list."},
        },
        ["round_number"],
    ),
]


DEEP_ANALYSIS_TOOL_DEFINITIONS = [
    _tool(
        "get_lap_telemetry",
        "DEEP ANALYSIS PRIMITIVE. Full telemetry for one driver's lap with speed, throttle, brake, gear, RPM, and DRS.",
        {
            "round_number": {"type": "integer", "description": "The 2026 season round number."},
            "session_type": {"type": "string", "description": "Session type: Q, R, FP1, FP2, FP3, S, SQ, SS."},
            "driver_code": {"type": "string", "description": "3-letter driver code."},
            "lap_number": {"type": "integer", "description": "Optional specific lap number."},
        },
        ["round_number", "session_type", "driver_code"],
    ),
    _tool(
        "get_telemetry_comparison",
        "DEEP ANALYSIS PRIMITIVE. Overlay two drivers' telemetry traces aligned by distance.",
        {
            "round_number": {"type": "integer", "description": "The 2026 season round number."},
            "session_type": {"type": "string", "description": "Session type: Q, R, FP1, FP2, FP3, S, SQ, SS."},
            "driver_a": {"type": "string", "description": "First driver's 3-letter code."},
            "driver_b": {"type": "string", "description": "Second driver's 3-letter code."},
            "lap_number_a": {"type": "integer", "description": "Optional lap number for driver_a."},
            "lap_number_b": {"type": "integer", "description": "Optional lap number for driver_b."},
        },
        ["round_number", "session_type", "driver_a", "driver_b"],
    ),
    _tool(
        "get_track_position_comparison",
        "DEEP ANALYSIS PRIMITIVE. Compare two drivers using raw position data and speed aligned by distance.",
        {
            "round_number": {"type": "integer", "description": "The 2026 season round number."},
            "session_type": {"type": "string", "description": "Session type: Q, R, FP1, FP2, FP3, S, SQ, SS."},
            "driver_a": {"type": "string", "description": "First driver's 3-letter code."},
            "driver_b": {"type": "string", "description": "Second driver's 3-letter code."},
            "lap_number_a": {"type": "integer", "description": "Optional lap number for driver_a."},
            "lap_number_b": {"type": "integer", "description": "Optional lap number for driver_b."},
        },
        ["round_number", "session_type", "driver_a", "driver_b"],
    ),
    _tool(
        "get_race_control_messages",
        "DEEP ANALYSIS PRIMITIVE. Race control messages for a session, optionally filtered by keyword or driver number.",
        {
            "round_number": {"type": "integer", "description": "The 2026 season round number."},
            "session_type": {"type": "string", "description": "Session type: Q, R, FP1, FP2, FP3, S, SQ, SS."},
            "category": {"type": "string", "description": "Optional keyword filter."},
            "limit": {"type": "integer", "description": "Maximum messages to return. Defaults to 50."},
        },
        ["round_number", "session_type"],
    ),
]


TOOL_DEFINITIONS = (
    COMPOSITE_TOOL_DEFINITIONS
    + PRIMITIVE_TOOL_DEFINITIONS
    + DEEP_ANALYSIS_TOOL_DEFINITIONS
)


OPENAI_TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": t["name"],
            "description": t["description"],
            "parameters": t["input_schema"],
        },
    }
    for t in TOOL_DEFINITIONS
]


def execute_tool(name: str, args: dict):
    if name == "get_driver_standings":
        return get_drivers()[:args.get("limit", 20)]
    if name == "get_constructor_standings":
        return get_constructor_standings()
    if name == "get_driver_season_stats":
        stats = get_driver_stats(args["driver_name"])
        if stats is None:
            raise ValueError(f"Driver not found: {args['driver_name']!r}. Try the driver's surname or 3-letter code.")
        return stats
    if name == "get_season_schedule":
        return get_circuits()
    if name == "get_race_results":
        return get_race_results(args["round_number"])
    if name == "get_qualifying_results":
        return get_qualifying_results(args["round_number"])
    if name == "get_session_results":
        return get_session_results(args["round_number"], args["session_type"])
    if name == "get_head_to_head":
        return get_head_to_head(args["driver_a"], args["driver_b"])
    if name == "get_driver_strategy":
        return get_driver_strategy(args["round_number"], args["session_type"], args.get("driver_code"))
    if name == "get_driver_weekend_overview":
        return get_driver_weekend_overview(args["round_number"], args["driver_name"])
    if name == "get_driver_race_story":
        return get_driver_race_story(args["round_number"], args["driver_name"])
    if name == "get_team_weekend_overview":
        return get_team_weekend_overview(args["round_number"], args["team_name"])
    if name == "get_race_report":
        return get_race_report(args["round_number"])
    if name == "get_qualifying_progression":
        return get_qualifying_progression(args["round_number"])
    if name == "get_session_fastest_laps":
        return get_session_fastest_laps(args["round_number"], args["session_type"])
    if name == "get_driver_lap_times":
        return get_driver_lap_times(args["round_number"], args["session_type"], args["driver_code"])
    if name == "get_clean_pace_summary":
        return get_clean_pace_summary(
            args["round_number"],
            args["session_type"],
            args.get("driver_codes"),
            args.get("green_only", True),
            args.get("limit", 10),
        )
    if name == "get_sector_comparison":
        return get_sector_comparison(args["round_number"], args["session_type"], args["driver_a"], args["driver_b"])
    if name == "get_safety_car_periods":
        return get_safety_car_periods(args["round_number"], args["session_type"])
    if name == "get_session_weather":
        return get_session_weather(args["round_number"], args["session_type"])
    if name == "get_circuit_corners":
        return get_circuit_corners(args["round_number"])
    if name == "get_circuit_details":
        return get_circuit_details(args["round_number"])
    if name == "get_historical_circuit_performance":
        return get_historical_circuit_performance(args["round_number"], args.get("years"))
    if name == "get_lap_telemetry":
        return get_lap_telemetry(args["round_number"], args["session_type"], args["driver_code"], args.get("lap_number"))
    if name == "get_telemetry_comparison":
        return get_telemetry_comparison(
            args["round_number"],
            args["session_type"],
            args["driver_a"],
            args["driver_b"],
            args.get("lap_number_a"),
            args.get("lap_number_b"),
        )
    if name == "get_track_position_comparison":
        return get_track_position_comparison(
            args["round_number"],
            args["session_type"],
            args["driver_a"],
            args["driver_b"],
            args.get("lap_number_a"),
            args.get("lap_number_b"),
        )
    if name == "get_race_control_messages":
        return get_race_control_messages(
            args["round_number"],
            args["session_type"],
            args.get("category"),
            args.get("limit", 50),
        )
    raise ValueError(f"Unknown tool: {name!r}")
