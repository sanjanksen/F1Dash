"""
Tool definitions for both Anthropic and OpenAI agentic loops.

Tool taxonomy:
- Composite recap tools: broad user-facing summaries and narratives
- Primitive tools: factual building blocks for narrower questions
- Deep analysis primitives: telemetry, pace, race control, weather

The model should prefer composite recap tools for broad "tell me about..."
questions and use primitives for focused follow-ups.
"""
from driver_styles import get_driver_style, get_comparison_framing
from circuit_profiles import get_circuit_profile
from team_car_profiles import get_team_car_profile
from f1_data import (
    analyze_cornering_loads,
    analyze_race_cornering_profile,
    analyze_qualifying_battle,
    analyze_race_pace_battle,
    analyze_stint_degradation,
    analyze_team_circuit_fit,
    analyze_team_performance,
    analyze_team_telemetry_traits,
    compare_corner_profiles,
    extract_corner_profiles,
    get_circuit_corners,
    get_circuit_details,
    get_circuit_track_map,
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
    get_pit_stop_analysis,
    analyze_weather_pace_correlation,
    get_fp_summary,
    get_speed_trap_leaderboard,
    get_sprint_results,
    get_sprint_qualifying_results,
    get_lap_delta_trace,
    get_driver_form_trend,
    get_sc_probability,
    get_head_to_head_history,
    get_session_style_fingerprint,
    get_driver_skill_rating,
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
        "COMPOSITE RECAP TOOL. Narrative-ready race or sprint story for one driver in one round. "
        "Use this first for broad prompts like 'how did Russell's race go?' or 'how did Norris do in the sprint?'. "
        "Pass session_type='S' for a sprint race story, session_type='R' (default) for the main race.",
        {
            "round_number": {"type": "integer", "description": "The 2026 season round number."},
            "driver_name": {"type": "string", "description": "Driver full name, surname, or 3-letter code."},
            "session_type": {"type": "string", "description": "R (default, main race) or S (sprint race)."},
        },
        ["round_number", "driver_name"],
    ),
    _tool(
        "get_driver_weekend_overview",
        "COMPOSITE RECAP TOOL. High-level factual weekend or race overview for one driver. "
        "Use this for broad driver recap questions when you want summary structure more than narrative. "
        "Pass session_type='S' for a sprint overview, session_type='R' (default) for the main race.",
        {
            "round_number": {"type": "integer", "description": "The 2026 season round number."},
            "driver_name": {"type": "string", "description": "Driver full name, surname, or 3-letter code."},
            "session_type": {"type": "string", "description": "R (default, main race) or S (sprint race)."},
        },
        ["round_number", "driver_name"],
    ),
    _tool(
        "get_team_weekend_overview",
        "COMPOSITE RECAP TOOL. High-level weekend overview for a team across both drivers. "
        "Use this first for broad prompts like 'how did Ferrari do this weekend?'. "
        "Pass session_type='S' for a sprint weekend overview, session_type='R' (default) for the main race.",
        {
            "round_number": {"type": "integer", "description": "The 2026 season round number."},
            "team_name": {"type": "string", "description": "Current constructor name or close match."},
            "session_type": {"type": "string", "description": "R (default, main race) or S (sprint race)."},
        },
        ["round_number", "team_name"],
    ),
    _tool(
        "get_race_report",
        "COMPOSITE RECAP TOOL. Whole-race or sprint recap independent of any one driver or team. "
        "Use this first for broad race recap prompts like 'what happened in the race?' or 'recap the sprint'. "
        "Pass session_type='S' for a sprint race recap, session_type='R' (default) for the main race.",
        {
            "round_number": {"type": "integer", "description": "The 2026 season round number."},
            "session_type": {"type": "string", "description": "R (default, main race) or S (sprint race recap)."},
        },
        ["round_number"],
    ),
]


PRIMITIVE_TOOL_DEFINITIONS = [
    _tool(
        "get_driver_style_profile",
        (
            "PRIMITIVE TOOL. Returns a driver's known driving style profile: corner approach (V-line vs U-line), "
            "steering consistency, braking commitment, apex style, throttle application, car preference "
            "(oversteer/understeer), and key telemetry signatures. Use this when analysing qualifying "
            "differences, corner profiles, or any question about how a driver attacks a corner. "
            "For a head-to-head comparison, call with both driver codes — the response includes a "
            "style_prediction describing where each driver should theoretically gain or lose."
        ),
        {
            "driver_a": {"type": "string", "description": "3-letter driver code (e.g. VER, NOR, PIA)."},
            "driver_b": {"type": "string", "description": "Optional second driver code for a head-to-head style comparison."},
        },
        ["driver_a"],
    ),
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
        "get_sprint_results",
        "PRIMITIVE TOOL. Raw sprint race finishing order for one round. Use for sprint race results lookup.",
        {
            "round_number": {"type": "integer", "description": "The 2026 season round number."},
        },
        ["round_number"],
    ),
    _tool(
        "get_sprint_qualifying_results",
        "PRIMITIVE TOOL. Sprint qualifying/shootout classification for one round (SQ1/SQ2/SQ3 segment times).",
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
        "get_circuit_track_map",
        "PRIMITIVE TOOL. GPS-derived circuit shape: downsampled {x, y, distance_m} points from the fastest lap plus sector boundary distances. Use for circuit map visualization.",
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
    _tool(
        "get_circuit_profile",
        (
            "PRIMITIVE TOOL. Returns a structured knowledge profile for a circuit: character (power/technical/street), "
            "per-sector types and style advantages (V-line vs U-line vs late-braker), energy deployment demand, "
            "clipping risk, tyre challenge, and a narrative summary. "
            "Use before or alongside telemetry analysis to contextualise WHY a gap opened in a specific sector. "
            "For example: if Sector 2 is 'high_speed_sweepers' with 'u_line_favored', a minimum-speed advantage "
            "in that sector is structurally expected for a U-line driver."
        ),
        {
            "country": {"type": "string", "description": "Country name for the circuit (e.g. Japan, Italy, Azerbaijan)."},
            "event_name": {"type": "string", "description": "Optional event name to disambiguate (e.g. Miami, United States Grand Prix)."},
        },
        ["country"],
    ),
    _tool(
        "analyze_team_circuit_fit",
        "PRIMITIVE TOOL. Derives a team's historical circuit-fit tendencies from real qualifying or race classifications. "
        "It compares the team's average result at each circuit archetype against that team's own season baseline, "
        "then reports over/under-performance by character, style verdict, and downforce level. "
        "Use for questions like 'what kind of tracks does Mercedes suit?', 'is McLaren better at high-speed circuits?', "
        "or 'does Ferrari historically overperform at late-braker tracks?'. This is not private setup data.",
        {
            "team_name": {"type": "string", "description": "Constructor name or close match, e.g. Mercedes, McLaren, Ferrari."},
            "years": {"type": "array", "items": {"type": "integer"}, "description": "Optional completed seasons. Defaults to the three seasons before the current year."},
            "session_type": {"type": "string", "description": "Q for qualifying fit or R for race fit. Defaults to Q."},
        },
        ["team_name"],
    ),
    _tool(
        "analyze_team_telemetry_traits",
        "PRIMITIVE TOOL. Session-specific telemetry characterization for a team's current car behavior. "
        "Compares the team's fastest-lap corner/straight traits against the field median: apex speed, exit speed, "
        "braking point, straight-line speed, full throttle, braking, and coasting. "
        "Use with analyze_team_circuit_fit when a specific round/session is known.",
        {
            "round_number": {"type": "integer", "description": "The 2026 season round number."},
            "team_name": {"type": "string", "description": "Constructor name or close match."},
            "session_type": {"type": "string", "description": "Q, R, FP1, FP2, FP3, S, SQ, SS. Defaults to Q."},
            "field_limit": {"type": "integer", "description": "Fastest field sample size. Defaults to 10."},
        },
        ["round_number", "team_name"],
    ),
    _tool(
        "get_team_car_profile",
        "PRIMITIVE TOOL. Dated, sourced public-reporting context about a team's car strengths or weaknesses. "
        "This is editorial context, not deterministic telemetry; use it only after or alongside data tools.",
        {
            "team_name": {"type": "string", "description": "Constructor name or close match."},
        },
        ["team_name"],
    ),
    _tool(
        "get_pit_stop_analysis",
        "PRIMITIVE TOOL. Pit stop strategy for all classified finishers in a race. "
        "Returns per-driver stints (compound, start_lap, end_lap, laps), pit stop laps, "
        "pit durations from OpenF1, and compound changes. Drivers sorted by finish position. "
        "Use for 'who had the fastest pit stops?', 'show me the strategy', "
        "'did anyone undercut on the pit stop?'.",
        {
            "round_number": {"type": "integer", "description": "The 2026 season round number."},
        },
        ["round_number"],
    ),
    _tool(
        "get_fp_summary",
        "PRIMITIVE TOOL. Free practice session summary with stint classification. "
        "Each driver's stints are labelled long_run (8+ laps same compound, race-pace sim), "
        "quali_sim (1-2 laps on fresh soft, best single-lap pace), short_run (setup/balance), "
        "or installation (first pit-out lap). Returns best_lap_time_s, best_lap_compound, "
        "speed_st, long_run_count, quali_sim_count per driver, sorted fastest to slowest. "
        "Includes session_notes explaining fuel load and programme-type caveats. "
        "Use for any FP1/FP2/FP3 question: fastest driver, programme analysis, race pace estimation.",
        {
            "round_number": {"type": "integer", "description": "The 2026 season round number."},
            "fp_number": {"type": "integer", "description": "Free practice number: 1, 2, or 3."},
        },
        ["round_number", "fp_number"],
    ),
    _tool(
        "get_speed_trap_leaderboard",
        "PRIMITIVE TOOL. Peak speed at each timing trap for every driver, scanning all laps. "
        "Returns four ranked lists: speed_st (main straight), speed_fl (finish line), "
        "speed_i1 (intermediate 1), speed_i2 (intermediate 2). Each entry: driver, team, "
        "speed_kph, lap_number, compound, rank. A driver's fastest ST may come on a different "
        "lap than their fastest FL — each trap is ranked independently. "
        "Use for 'who had the highest top speed?', 'speed trap leaderboard', "
        "'who was fastest down the straight?', 'drag/straight-line speed' questions.",
        {
            "round_number": {"type": "integer", "description": "The 2026 season round number."},
            "session_type": {"type": "string", "description": "Session type: Q, R, FP1, FP2, FP3, S, SQ, SS."},
        },
        ["round_number", "session_type"],
    ),
    _tool(
        "get_lap_delta_trace",
        "PRIMITIVE TOOL. Cumulative time delta at every 100m of the lap between two drivers. "
        "Use for precise spatial questions like 'where did Norris gain time on Leclerc?' — "
        "returns a trace showing exactly which sectors, corners, or straights produced the gap. "
        "Works for qualifying and race fastest laps.",
        {
            "round_number": {"type": "integer", "description": "Race round number."},
            "session_type": {"type": "string", "description": "Q for qualifying, R for race."},
            "driver_a":     {"type": "string", "description": "First driver code (e.g. NOR)."},
            "driver_b":     {"type": "string", "description": "Second driver code (e.g. LEC)."},
            "lap_type":     {"type": "string", "description": "fastest (default) or qualifying."},
        },
        ["round_number", "session_type", "driver_a", "driver_b"],
    ),
    _tool(
        "get_driver_form_trend",
        "PRIMITIVE TOOL. Rolling form trend for a driver over their last N races: positions gained/lost vs grid at each round, trend classification (improving/declining/stable), and rolling average.",
        {
            "driver_name": {"type": "string", "description": "Driver name, code, or abbreviation."},
            "last_n":      {"type": "integer", "description": "Number of recent races to include (default 8)."},
        },
        ["driver_name"],
    ),
    _tool(
        "get_sc_probability",
        "PRIMITIVE TOOL. Historical safety car / VSC deployment probability for the circuit hosting a given round. Returns probability 0–1, classification, and rank vs other circuits.",
        {
            "round_number": {"type": "integer", "description": "Race round number."},
        },
        ["round_number"],
    ),
    _tool(
        "get_head_to_head_history",
        "PRIMITIVE TOOL. Multi-season head-to-head comparison between two drivers: win rate, average finishing position delta, and race-by-race breakdown across shared seasons.",
        {
            "driver_a": {"type": "string", "description": "First driver name or code."},
            "driver_b": {"type": "string", "description": "Second driver name or code."},
            "seasons":  {"type": "array", "items": {"type": "integer"}, "description": "List of seasons to compare (default: last 3 complete seasons)."},
        },
        ["driver_a", "driver_b"],
    ),
    _tool(
        "get_session_style_fingerprint",
        "PRIMITIVE TOOL. Aggregated driving style fingerprint for a driver across all corners in a session: trail braking rate, throttle acceptance, entry bravery, GGV utilisation, and apex speed.",
        {
            "round_number":  {"type": "integer", "description": "Race round number."},
            "session_type":  {"type": "string", "description": "Q for qualifying, R for race."},
            "driver_name":   {"type": "string", "description": "Driver name or code."},
        },
        ["round_number", "session_type", "driver_name"],
    ),
]


DEEP_ANALYSIS_TOOL_DEFINITIONS = [
    _tool(
        "analyze_qualifying_battle",
        "DEEP ANALYSIS PRIMITIVE. Backend-derived causal summary for a qualifying battle between two drivers. "
        "Use this for questions like 'why was Leclerc faster than Norris in quali?' when you need where and why the gap happened, not just the final times. "
        "Pass session_type='SQ' for sprint qualifying/shootout.",
        {
            "round_number": {"type": "integer", "description": "The 2026 season round number."},
            "driver_a": {"type": "string", "description": "First driver's 3-letter code."},
            "driver_b": {"type": "string", "description": "Second driver's 3-letter code."},
            "session_type": {"type": "string", "description": "Q (default, regular qualifying) or SQ (sprint qualifying/shootout)."},
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
        "analyze_cornering_loads",
        "DEEP ANALYSIS PRIMITIVE. Compute lateral G and grip utilisation for two drivers across all corners of their fastest laps, "
        "using curvature derived from X/Y position telemetry. Returns per-corner stats (peak G, apex G, load variance, "
        "steering correction count, % time above 90% theoretical grip) plus an overall summary and a human-readable narrative. "
        "Also returns GGV-based metrics derived from the session's empirical grip envelope (not a theoretical formula): "
        "ggv_util_pct (% of the car's demonstrated grip ellipse used, combining lat + long), "
        "envelope_time_pct (% of cornering time within 15% of the empirical limit), "
        "throttle_acceptance_pct (% of corner exits where full throttle is applied while still laterally loaded — the bravery metric), "
        "entry_bravery_pct (% of entries near the combined limit while still braking), "
        "bravery_score (composite 0–100). "
        "Use this for qualifying / single-lap grip style and bravery comparisons.",
        {
            "round_number": {"type": "integer", "description": "The 2026 season round number."},
            "session_type": {"type": "string", "description": "Session type: Q, R, FP1, FP2, FP3, S, SQ, SS."},
            "driver_a": {"type": "string", "description": "First driver's 3-letter code."},
            "driver_b": {"type": "string", "description": "Second driver's 3-letter code."},
            "lap_number_a": {"type": "integer", "description": "Optional specific lap number for driver_a."},
            "lap_number_b": {"type": "integer", "description": "Optional specific lap number for driver_b."},
        },
        ["round_number", "session_type", "driver_a", "driver_b"],
    ),
    _tool(
        "analyze_race_cornering_profile",
        "DEEP ANALYSIS PRIMITIVE. Compute lateral G and grip utilisation aggregated across an ENTIRE RACE for two drivers. "
        "Processes every clean race lap (pit laps excluded) and returns overall summary stats plus a per-stint breakdown. "
        "Use this when asked about race-long grip usage, tyre stress, or who pushes harder through corners over a full race distance. "
        "Returns: avg corner grip utilisation %, % cornering time above 90% grip, corrections per corner, load variance per stint, "
        "combined grip utilisation % (lat+long vector), trail brake % at corner entry, "
        "GGV-based metrics: ggv_util_pct (empirical envelope utilisation), envelope_time_pct, "
        "throttle_acceptance_pct (exit bravery — full power under lateral load), "
        "entry_bravery_pct, bravery_score (0–100 composite) per stint and overall.",
        {
            "round_number": {"type": "integer", "description": "The 2026 season round number."},
            "driver_a": {"type": "string", "description": "First driver's 3-letter code."},
            "driver_b": {"type": "string", "description": "Second driver's 3-letter code."},
        },
        ["round_number", "driver_a", "driver_b"],
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
        "Fits linear and polynomial regression on fuel-corrected lap times vs tyre age per stint compound. "
        "Returns deg_rate_s_per_lap, fuel_corrected_pace_at_age_1_s, r_squared, consistency_std_dev_s, "
        "raw_pace_trend_s_per_lap, cliff_lap_est (tyre age where degradation accelerates nonlinearly — "
        "the polynomial breakpoint), quad_coeff (positive = accelerating deg curve), laps_past_cliff "
        "(how many laps driven past the cliff before pitting — use this to explain forced or strategic pit stops), "
        "and a tyre_management summary with per-compound cliff_lap_est and laps_past_cliff. "
        "The raw trend is what the stopwatch did; deg_rate_s_per_lap adds back expected fuel-burn gain "
        "to estimate tyre performance loss. For tyre-management rankings, lower positive_deg_rate_s_per_lap "
        "is the primary signal; consistency_std_dev_s is lap-to-lap noise and r_squared is confidence/trust "
        "in the trend, not pace. "
        "Use for questions about tyre wear, degradation rate, tyre management, pit timing decisions, "
        "or how pace evolved over a stint.",
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
        "(tyre_degradation/raw_pace_advantage/strategy_execution/mixed), tyre_management summaries with "
        "deg rate, consistency, R², and per-compound cliff_lap_est and laps_past_cliff, plus undercut "
        "analysis with cliff_context showing whether each driver's tyres had hit the cliff when they pitted. "
        "Use for questions like 'who had better race pace?', 'why did Verstappen pull away from Hamilton?', "
        "or 'was the undercut forced by tyre degradation?'.",
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
    _tool(
        "get_driver_skill_rating",
        "PRIMITIVE TOOL. Bayesian driver skill estimate: how good is this driver independent of the car? "
        "Returns posterior mean skill in standard deviation (SD) units (1 SD ≈ 0.3s/lap advantage over a median driver in a median car), "
        "90% credible interval, rank among all rated drivers, and a plain-English interpretation. "
        "Model trained on pairwise race finishes across multiple seasons, with constructor-year effects removed. "
        "Use for questions like 'how good is Norris really?' or 'is Hamilton still elite?' or 'who is the best driver independent of their car?'",
        {
            "driver_name": {"type": "string", "description": "Driver full name, surname, or 3-letter code (e.g. NOR, Norris)."},
        },
        ["driver_name"],
    ),
    _tool(
        "analyze_weather_pace_correlation",
        "DEEP ANALYSIS PRIMITIVE. Correlates track temperature with lap time evolution. "
        "For qualifying: Q1/Q2/Q3 segments with temperature, best lap, and top-5 average. "
        "For race: 10-lap blocks with temperature and pace. "
        "Use reactively to explain anomalies: why Q3 was slower than Q2, why pace fell off mid-race, "
        "whether a track temperature drop or rainfall explains an unexpected result.",
        {
            "round_number": {"type": "integer", "description": "The 2026 season round number."},
            "session_type": {"type": "string", "description": "Q (default) or R."},
        },
        ["round_number"],
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
        return get_intervals(args["round_number"], args.get("driver_ref"), args.get("limit", 25), args.get("session_type", "R"))
    if name == "get_live_position_timeline":
        return get_live_position_timeline(args["round_number"], args["session_type"], args.get("driver_ref"), args.get("limit", 50))
    if name == "analyze_qualifying_battle":
        return analyze_qualifying_battle(args["round_number"], args["driver_a"], args["driver_b"], session_type=args.get("session_type", "Q"))
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
    if name == "get_sprint_results":
        return get_sprint_results(args["round_number"])
    if name == "get_sprint_qualifying_results":
        return get_sprint_qualifying_results(args["round_number"])
    if name == "get_driver_weekend_overview":
        return get_driver_weekend_overview(args["round_number"], args["driver_name"], session_type=args.get("session_type", "R"))
    if name == "get_driver_race_story":
        return get_driver_race_story(args["round_number"], args["driver_name"], session_type=args.get("session_type", "R"))
    if name == "get_team_weekend_overview":
        return get_team_weekend_overview(args["round_number"], args["team_name"], session_type=args.get("session_type", "R"))
    if name == "get_race_report":
        return get_race_report(args["round_number"], session_type=args.get("session_type", "R"))
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
    if name == "get_circuit_track_map":
        return get_circuit_track_map(args["round_number"])
    if name == "get_historical_circuit_performance":
        return get_historical_circuit_performance(args["round_number"], args.get("years"))
    if name == "analyze_cornering_loads":
        return analyze_cornering_loads(
            args["round_number"],
            args["session_type"],
            args["driver_a"],
            args["driver_b"],
            args.get("lap_number_a"),
            args.get("lap_number_b"),
        )
    if name == "analyze_race_cornering_profile":
        return analyze_race_cornering_profile(
            args["round_number"],
            args["driver_a"],
            args["driver_b"],
        )
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
    if name == "analyze_team_circuit_fit":
        return analyze_team_circuit_fit(
            args["team_name"],
            args.get("years"),
            args.get("session_type", "Q"),
        )
    if name == "analyze_team_telemetry_traits":
        return analyze_team_telemetry_traits(
            args["round_number"],
            args["team_name"],
            args.get("session_type", "Q"),
            args.get("field_limit", 10),
        )
    if name == "get_team_car_profile":
        profile = get_team_car_profile(args["team_name"])
        if profile is None:
            return {
                "team_query": args["team_name"],
                "profile_type": "curated_editorial",
                "available": False,
                "caveat": "No sourced public-reporting profile is currently curated for this team.",
            }
        return profile
    if name == "get_circuit_profile":
        profile = get_circuit_profile(args["country"], args.get("event_name", ""))
        if profile is None:
            raise ValueError(f"No circuit profile found for country={args['country']!r}.")
        return profile
    if name == "get_driver_style_profile":
        driver_b = args.get("driver_b")
        if driver_b:
            result = get_comparison_framing(args["driver_a"], driver_b)
            if result is None:
                # At least one driver unknown — return whatever we have
                a = get_driver_style(args["driver_a"])
                b = get_driver_style(driver_b)
                return {"driver_a": a, "driver_b": b}
            return result
        profile = get_driver_style(args["driver_a"])
        if profile is None:
            raise ValueError(f"No style profile found for driver code {args['driver_a']!r}.")
        return profile
    if name == "get_pit_stop_analysis":
        return get_pit_stop_analysis(args["round_number"])
    if name == "analyze_weather_pace_correlation":
        return analyze_weather_pace_correlation(args["round_number"], args.get("session_type", "Q"))
    if name == "get_fp_summary":
        return get_fp_summary(args["round_number"], args["fp_number"])
    if name == "get_speed_trap_leaderboard":
        return get_speed_trap_leaderboard(args["round_number"], args["session_type"])
    if name == "get_lap_delta_trace":
        return get_lap_delta_trace(
            args["round_number"], args["session_type"],
            args["driver_a"], args["driver_b"],
            args.get("lap_type", "fastest"),
        )
    if name == "get_driver_form_trend":
        return get_driver_form_trend(args["driver_name"], args.get("last_n", 8))
    if name == "get_sc_probability":
        return get_sc_probability(args["round_number"])
    if name == "get_head_to_head_history":
        return get_head_to_head_history(args["driver_a"], args["driver_b"], args.get("seasons"))
    if name == "get_session_style_fingerprint":
        return get_session_style_fingerprint(args["round_number"], args["session_type"], args["driver_name"])
    if name == "get_driver_skill_rating":
        return get_driver_skill_rating(args["driver_name"])
    raise ValueError(f"Unknown tool: {name!r}")
