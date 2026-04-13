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
    analyze_qualifying_battle,
    analyze_race_pace_battle,
    analyze_stint_degradation,
    analyze_team_performance,
    compare_corner_profiles,
    extract_corner_profiles,
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
    analyze_energy_management,
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
from openf1 import get_intervals, get_live_position_timeline, get_team_radio


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
        "analyze_qualifying_battle",
        "DEEP ANALYSIS PRIMITIVE. Backend-derived causal summary for a qualifying battle between two drivers. "
        "Use this for questions like 'why was Leclerc faster than Norris in quali?' when you need where and why the gap happened, not just the final times.",
        {
            "round_number": {"type": "integer", "description": "The 2026 season round number."},
            "driver_a": {"type": "string", "description": "First driver's 3-letter code."},
            "driver_b": {"type": "string", "description": "Second driver's 3-letter code."},
        },
        ["round_number", "driver_a", "driver_b"],
    ),
    _tool(
        "get_team_radio",
        "DEEP ANALYSIS PRIMITIVE. OpenF1 team radio metadata for a session, optionally filtered to one driver. "
        "Use this for questions about what was said on the radio or to add in-car context to a race story.",
        {
            "round_number": {"type": "integer", "description": "The 2026 season round number."},
            "session_type": {"type": "string", "description": "Session type: Q, R, FP1, FP2, FP3, S, SQ, SS."},
            "driver_ref": {"type": "string", "description": "Optional driver name, surname, or 3-letter code."},
            "limit": {"type": "integer", "description": "Maximum radio entries to return. Defaults to 10."},
        },
        ["round_number", "session_type"],
    ),
    _tool(
        "get_intervals",
        "DEEP ANALYSIS PRIMITIVE. OpenF1 race intervals and gap-to-leader timeline, optionally for one driver. "
        "Use this for race-story questions about who was closing, dropping back, or sitting in undercut range.",
        {
            "round_number": {"type": "integer", "description": "The 2026 season round number."},
            "driver_ref": {"type": "string", "description": "Optional driver name, surname, or 3-letter code."},
            "limit": {"type": "integer", "description": "Maximum interval entries to return. Defaults to 25."},
        },
        ["round_number"],
    ),
    _tool(
        "get_live_position_timeline",
        "DEEP ANALYSIS PRIMITIVE. OpenF1 position timeline for a session, optionally for one driver. "
        "Use this for cleaner live-style position changes and race-shape reconstruction.",
        {
            "round_number": {"type": "integer", "description": "The 2026 season round number."},
            "session_type": {"type": "string", "description": "Session type: Q, R, FP1, FP2, FP3, S, SQ, SS."},
            "driver_ref": {"type": "string", "description": "Optional driver name, surname, or 3-letter code."},
            "limit": {"type": "integer", "description": "Maximum position entries to return. Defaults to 50."},
        },
        ["round_number", "session_type"],
    ),
    _tool(
        "analyze_energy_management",
        "DEEP ANALYSIS PRIMITIVE. Analyze likely 2026-style energy management patterns such as lift-and-coast and possible late-straight clipping. "
        "This tool uses telemetry heuristics and explicitly distinguishes measured signals from inferred energy behavior.",
        {
            "round_number": {"type": "integer", "description": "The 2026 season round number."},
            "session_type": {"type": "string", "description": "Session type: Q, R, FP1, FP2, FP3, S, SQ, SS."},
            "driver_a": {"type": "string", "description": "Primary driver's 3-letter code."},
            "driver_b": {"type": "string", "description": "Optional comparison driver's 3-letter code."},
            "lap_number_a": {"type": "integer", "description": "Optional lap number for driver_a."},
            "lap_number_b": {"type": "integer", "description": "Optional lap number for driver_b."},
        },
        ["round_number", "session_type", "driver_a"],
    ),
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
    _tool(
        "extract_corner_profiles",
        "DEEP ANALYSIS PRIMITIVE. Per-corner and per-straight telemetry breakdown for a driver's lap. "
        "Returns entry/apex/exit speed, braking point, gear at apex, traction point, straight acceleration, DRS activation, "
        "clipping detection, and whole-lap usage summary (full_throttle_pct, braking_pct, gear distribution). "
        "Use for questions like 'what gear does Hamilton use at Turn 8?' or 'where is Leclerc braking?'.",
        {
            "round_number": {"type": "integer", "description": "The 2026 season round number."},
            "session_type": {"type": "string", "description": "Session type: Q, R, FP1, FP2, FP3, S, SQ, SS."},
            "driver_code": {"type": "string", "description": "3-letter driver code."},
            "lap_number": {"type": "integer", "description": "Optional specific lap number. Defaults to fastest lap."},
        },
        ["round_number", "session_type", "driver_code"],
    ),
    _tool(
        "compare_corner_profiles",
        "DEEP ANALYSIS PRIMITIVE. Compare corner-by-corner telemetry between two drivers. "
        "Returns per-corner cause classification (braking/minimum_speed/traction/mixed), "
        "setup direction inference (corner_heavy/straight_heavy/balanced), average straight speeds, "
        "and gain location summary showing the top 3 corners where the faster driver has an advantage. "
        "Use for questions like 'is Ferrari better in corners or on straights vs Mercedes?' or "
        "'where does Norris gain time on Leclerc in quali?'.",
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
        "analyze_stint_degradation",
        "DEEP ANALYSIS PRIMITIVE. Compute tyre degradation model for a driver's race stints. "
        "Fits linear regression on fuel-corrected lap times vs tyre age per stint compound. "
        "Returns deg_rate_s_per_lap, fuel_corrected_pace_at_age_1_s, r_squared, consistency_std_dev_s. "
        "Use for questions about tyre wear, degradation rate, or how pace evolved over a stint.",
        {
            "round_number": {"type": "integer", "description": "The 2026 season round number."},
            "driver_code": {"type": "string", "description": "3-letter driver code."},
            "session_type": {"type": "string", "description": "Session type: R or S. Defaults to R."},
        },
        ["round_number", "driver_code"],
    ),
    _tool(
        "analyze_race_pace_battle",
        "DEEP ANALYSIS PRIMITIVE. Compare race pace and tyre degradation between two drivers. "
        "Race equivalent of analyze_qualifying_battle. Returns fuel-corrected pace delta, "
        "per-compound degradation rate comparison, aligned stints, decisive_factor classification "
        "(tyre_degradation/raw_pace_advantage/strategy_execution/mixed), and undercut analysis. "
        "Use for questions like 'who had better race pace?' or 'why did Verstappen pull away from Hamilton in the race?'.",
        {
            "round_number": {"type": "integer", "description": "The 2026 season round number."},
            "driver_a": {"type": "string", "description": "First driver's 3-letter code."},
            "driver_b": {"type": "string", "description": "Second driver's 3-letter code."},
            "session_type": {"type": "string", "description": "Session type: R or S. Defaults to R."},
        },
        ["round_number", "driver_a", "driver_b"],
    ),
    _tool(
        "analyze_team_performance",
        "DEEP ANALYSIS PRIMITIVE. Compare both teammates' corner profiles and (in race sessions) degradation for a team. "
        "Returns setup_direction_inference, gain_location_summary, and per-driver stint degradation. "
        "Use for questions like 'how did Ferrari compare as a team?' or 'which teammate was stronger in the corners?'.",
        {
            "round_number": {"type": "integer", "description": "The 2026 season round number."},
            "team_name": {"type": "string", "description": "Team name or close match (e.g. Ferrari, McLaren, Mercedes)."},
            "session_type": {"type": "string", "description": "Session type: Q, R, FP1, FP2, FP3, S, SQ, SS."},
        },
        ["round_number", "team_name", "session_type"],
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
    if name == "get_team_radio":
        return get_team_radio(args["round_number"], args["session_type"], args.get("driver_ref"), args.get("limit", 10))
    if name == "get_intervals":
        return get_intervals(args["round_number"], args.get("driver_ref"), args.get("limit", 25))
    if name == "get_live_position_timeline":
        return get_live_position_timeline(args["round_number"], args["session_type"], args.get("driver_ref"), args.get("limit", 50))
    if name == "analyze_qualifying_battle":
        return analyze_qualifying_battle(args["round_number"], args["driver_a"], args["driver_b"])
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
    if name == "analyze_energy_management":
        return analyze_energy_management(
            args["round_number"],
            args["session_type"],
            args["driver_a"],
            args.get("driver_b"),
            args.get("lap_number_a"),
            args.get("lap_number_b"),
        )
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
    if name == "extract_corner_profiles":
        return extract_corner_profiles(
            args["round_number"],
            args["session_type"],
            args["driver_code"],
            args.get("lap_number"),
        )
    if name == "compare_corner_profiles":
        return compare_corner_profiles(
            args["round_number"],
            args["session_type"],
            args["driver_a"],
            args["driver_b"],
            args.get("lap_number_a"),
            args.get("lap_number_b"),
        )
    if name == "analyze_stint_degradation":
        return analyze_stint_degradation(
            args["round_number"],
            args["driver_code"],
            args.get("session_type", "R"),
        )
    if name == "analyze_race_pace_battle":
        return analyze_race_pace_battle(
            args["round_number"],
            args["driver_a"],
            args["driver_b"],
            args.get("session_type", "R"),
        )
    if name == "analyze_team_performance":
        return analyze_team_performance(
            args["round_number"],
            args["team_name"],
            args["session_type"],
        )
    raise ValueError(f"Unknown tool: {name!r}")
