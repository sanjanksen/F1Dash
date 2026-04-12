# server/tools.py
"""
Tool definitions for the Anthropic tool-use agentic loop.

TOOL_DEFINITIONS — list of tool schemas passed to client.messages.create(tools=...)
execute_tool(name, args) — dispatcher that runs the matching f1_data function
"""
from f1_data import (
    get_drivers,
    get_constructor_standings,
    get_driver_stats,
    get_race_results,
    get_qualifying_results,
    get_circuits,
    get_head_to_head,
    get_session_fastest_laps,
    get_driver_lap_times,
    get_sector_comparison,
    get_lap_telemetry,
)

TOOL_DEFINITIONS = [
    {
        "name": "get_driver_standings",
        "description": (
            "Get the current 2025 Formula 1 driver championship standings. "
            "Returns position, points, wins, team, and nationality for each driver. "
            "Use this when the user asks who is leading the championship, how many "
            "points a driver has, or wants a general standings overview."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Number of drivers to return (1–20). Defaults to 20 for full standings.",
                }
            },
            "required": [],
        },
    },
    {
        "name": "get_constructor_standings",
        "description": (
            "Get the current 2025 Formula 1 constructor (team) championship standings. "
            "Returns position, team name, nationality, total points, and wins. "
            "Use this when the user asks about team standings, which team is winning, "
            "or how much a team leads by."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "get_driver_season_stats",
        "description": (
            "Get detailed 2025 season statistics for a specific driver: wins, podiums, "
            "fastest laps, championship position, points, and their last 5 race results. "
            "Use this when the user asks about a particular driver's performance, results, "
            "or season summary. Pass the driver's full name, surname, or 3-letter code "
            "(e.g. 'Verstappen', 'VER', 'norris')."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "driver_name": {
                    "type": "string",
                    "description": "Driver's full name, surname, or 3-letter code (case-insensitive).",
                }
            },
            "required": ["driver_name"],
        },
    },
    {
        "name": "get_race_results",
        "description": (
            "Get the full race classification for a specific 2025 Grand Prix. "
            "Returns finishing position, driver, team, points, fastest lap, and race status "
            "for every classified finisher. Use this when the user asks who won a race, "
            "what the results were for a specific round, or how a driver finished in a race."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "round_number": {
                    "type": "integer",
                    "description": "The round number in the 2025 season (1–24). Use get_season_schedule first if unsure of the round number.",
                }
            },
            "required": ["round_number"],
        },
    },
    {
        "name": "get_qualifying_results",
        "description": (
            "Get the qualifying session results (Q1, Q2, Q3 lap times) for a specific "
            "2025 Grand Prix round. Returns grid positions and times for all drivers. "
            "Use this when the user asks about pole position, qualifying pace, grid order, "
            "or time gaps in qualifying."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "round_number": {
                    "type": "integer",
                    "description": "The round number in the 2025 season (1–24). Use get_season_schedule first if unsure of the round number.",
                }
            },
            "required": ["round_number"],
        },
    },
    {
        "name": "get_season_schedule",
        "description": (
            "Get the complete 2025 Formula 1 season calendar: all 24 rounds with race names, "
            "circuit locations, countries, and dates. Use this when the user asks about "
            "upcoming races, which round a specific Grand Prix is, the season calendar, "
            "or before looking up race/qualifying results by round number."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "get_head_to_head",
        "description": (
            "Compare two drivers directly across all 2025 races they both competed in. "
            "Returns points totals, points gap, wins each, and a head-to-head race count "
            "(how many times each driver finished ahead of the other). "
            "Use this when the user wants to compare two drivers, asks who is faster, "
            "or wants to see a rivalry breakdown."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "driver_a": {
                    "type": "string",
                    "description": "First driver's full name, surname, or 3-letter code.",
                },
                "driver_b": {
                    "type": "string",
                    "description": "Second driver's full name, surname, or 3-letter code.",
                },
            },
            "required": ["driver_a", "driver_b"],
        },
    },
    {
        "name": "get_session_fastest_laps",
        "description": (
            "Get the leaderboard of fastest laps for every driver in a specific session "
            "(qualifying, race, practice). Includes sector times (S1/S2/S3) and speed trap "
            "values (SpeedI1/SpeedI2/SpeedFL/SpeedST). Use this to see how all drivers "
            "compared in a session, or to find sector-by-sector breakdowns."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "round_number": {
                    "type": "integer",
                    "description": "The 2025 season round number.",
                },
                "session_type": {
                    "type": "string",
                    "description": "Session type: 'Q' (qualifying), 'R' (race), 'FP1', 'FP2', 'FP3', 'S' (sprint), 'SQ' (sprint qualifying), 'SS' (sprint shootout).",
                },
            },
            "required": ["round_number", "session_type"],
        },
    },
    {
        "name": "get_driver_lap_times",
        "description": (
            "Get every lap a specific driver completed in a session, with per-lap sector "
            "splits, speed traps, tyre compound, tyre life, and pit stop flags. "
            "Use this when you need to understand how a driver's pace evolved lap-by-lap, "
            "when they pitted, or how their tyre performance changed."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "round_number": {
                    "type": "integer",
                    "description": "The 2025 season round number.",
                },
                "session_type": {
                    "type": "string",
                    "description": "Session type: 'Q', 'R', 'FP1', 'FP2', 'FP3', 'S', 'SQ', 'SS'.",
                },
                "driver_code": {
                    "type": "string",
                    "description": "3-letter driver code (e.g. 'NOR', 'VER', 'LEC').",
                },
            },
            "required": ["round_number", "session_type", "driver_code"],
        },
    },
    {
        "name": "get_sector_comparison",
        "description": (
            "Compare two drivers' fastest laps sector by sector. Shows lap time for each, "
            "the time gap per sector (positive = driver_a slower), and speed trap deltas "
            "at each measurement point (SpeedI1 = intermediate 1, SpeedI2 = intermediate 2, "
            "SpeedFL = finish line, SpeedST = speed trap). "
            "Use this to answer: 'Why was Norris 0.3s faster than Leclerc in S2 at Monaco?'"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "round_number": {
                    "type": "integer",
                    "description": "The 2025 season round number.",
                },
                "session_type": {
                    "type": "string",
                    "description": "Session type: 'Q', 'R', 'FP1', 'FP2', 'FP3', 'S', 'SQ', 'SS'.",
                },
                "driver_a": {
                    "type": "string",
                    "description": "First driver's 3-letter code (e.g. 'NOR').",
                },
                "driver_b": {
                    "type": "string",
                    "description": "Second driver's 3-letter code (e.g. 'LEC').",
                },
            },
            "required": ["round_number", "session_type", "driver_a", "driver_b"],
        },
    },
    {
        "name": "get_lap_telemetry",
        "description": (
            "Get full telemetry data for a driver's lap — speed, throttle, brake, gear, "
            "and DRS status sampled every 100 metres along the circuit. Defaults to the "
            "driver's fastest lap in the session. Use this for the deepest analysis: "
            "explaining corner-by-corner pace differences, braking points, traction zones, "
            "or DRS activation. Warning: telemetry is slow to load on first call (cached after)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "round_number": {
                    "type": "integer",
                    "description": "The 2025 season round number.",
                },
                "session_type": {
                    "type": "string",
                    "description": "Session type: 'Q', 'R', 'FP1', 'FP2', 'FP3', 'S', 'SQ', 'SS'.",
                },
                "driver_code": {
                    "type": "string",
                    "description": "3-letter driver code (e.g. 'NOR').",
                },
                "lap_number": {
                    "type": "integer",
                    "description": "Specific lap number to fetch telemetry for. If omitted, uses the driver's fastest lap.",
                },
            },
            "required": ["round_number", "session_type", "driver_code"],
        },
    },
]


def execute_tool(name: str, args: dict):
    """
    Dispatch a tool call by name and return the result.

    Raises ValueError for unknown tool names or driver-not-found errors.
    All other exceptions from data functions propagate naturally so the
    agentic loop can catch them and set is_error=True in the tool_result.
    """
    if name == "get_driver_standings":
        limit = args.get("limit", 20)
        return get_drivers()[:limit]

    if name == "get_constructor_standings":
        return get_constructor_standings()

    if name == "get_driver_season_stats":
        stats = get_driver_stats(args["driver_name"])
        if stats is None:
            raise ValueError(f"Driver not found: {args['driver_name']!r}. "
                             "Try the driver's surname or 3-letter code.")
        return stats

    if name == "get_race_results":
        return get_race_results(args["round_number"])

    if name == "get_qualifying_results":
        return get_qualifying_results(args["round_number"])

    if name == "get_season_schedule":
        return get_circuits()

    if name == "get_head_to_head":
        return get_head_to_head(args["driver_a"], args["driver_b"])

    if name == "get_session_fastest_laps":
        return get_session_fastest_laps(args["round_number"], args["session_type"])

    if name == "get_driver_lap_times":
        return get_driver_lap_times(args["round_number"], args["session_type"], args["driver_code"])

    if name == "get_sector_comparison":
        return get_sector_comparison(
            args["round_number"], args["session_type"],
            args["driver_a"], args["driver_b"]
        )

    if name == "get_lap_telemetry":
        return get_lap_telemetry(
            args["round_number"], args["session_type"],
            args["driver_code"], args.get("lap_number")
        )

    raise ValueError(f"Unknown tool: {name!r}")
