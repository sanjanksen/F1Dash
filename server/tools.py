"""
Tool definitions for both Anthropic and OpenAI agentic loops.

Tool taxonomy:
- Composite recap tools: broad user-facing summaries and narratives
- Primitive tools: factual building blocks for narrower questions
- Deep analysis primitives: telemetry, pace, race control, weather

The model should prefer composite recap tools for broad "tell me about..."
questions and use primitives for focused follow-ups.
"""
import logging

from driver_styles import get_driver_style, get_comparison_framing
from circuit_profiles import get_circuit_profile
from team_car_profiles import get_team_car_profile
import f1_data
from f1_data import (
    analyze_cornering_loads,
    analyze_race_cornering_profile,
    analyze_qualifying_battle,
    analyze_race_pace_battle,
    analyze_stint_degradation,
    analyze_team_circuit_fit,
    analyze_team_performance,
    analyze_team_telemetry_traits,
    analyze_undercut_overcut,
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
    analyze_active_aero_usage,
    analyze_energy_management,
    analyze_override_usage,
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
)
from openf1 import get_intervals, get_live_position_timeline, get_team_radio

logger = logging.getLogger(__name__)


def _search_editorial_content_safe(query: str, limit: int = 5, min_date: str | None = None):
    """Lazy import so test environments without supabase installed don't break tool import."""
    try:
        from editorial.search import search_editorial_content
    except Exception as e:  # pragma: no cover — defensive only
        logger.warning("editorial.search import failed: %s", type(e).__name__)
        return {"available": False, "reason": "editorial_db_unavailable", "results": []}
    return search_editorial_content(query, limit=limit, min_date=min_date)


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


# Composite recap tools are now provided by FEATURE_REGISTRY (Phase E2).
# The auto-extension block at the bottom of this file extends TOOL_DEFINITIONS
# with their registry-derived schemas.
COMPOSITE_TOOL_DEFINITIONS: list[dict] = []


# Primitive tools are now provided by FEATURE_REGISTRY (Phase E2). The
# auto-extension block at the bottom of this file extends TOOL_DEFINITIONS
# with their registry-derived schemas.
PRIMITIVE_TOOL_DEFINITIONS: list[dict] = []


DEEP_ANALYSIS_TOOL_DEFINITIONS = [
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
        "analyze_override_usage",
        "DEEP ANALYSIS PRIMITIVE. Detect 2026 override-mode boost segments for a specific lap. "
        "Identifies where a driver was within 1 second of the car ahead and used the extended 350 kW deployment "
        "to accelerate past 290 km/h up to 337 km/h. Use this for specific-lap questions like "
        "'did Verstappen use override on lap 14?' For broad race narratives, prefer get_driver_race_story which "
        "already weaves override evidence into overtake descriptions.",
        {
            "driver_code": {"type": "string", "description": "3-letter driver code."},
            "round_number": {"type": "integer", "description": "The 2026 season round number."},
            "session_type": {"type": "string", "description": "Session type: Q, R, FP1, FP2, FP3, S, SQ, SS."},
            "lap_number": {"type": "integer", "description": "Specific lap number to analyse."},
        },
        ["driver_code", "round_number", "session_type", "lap_number"],
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


def _require_args(args: dict, required: list[str], tool_name: str) -> None:
    missing = [k for k in required if k not in args or args[k] in (None, "")]
    if missing:
        raise ValueError(
            f"Tool {tool_name!r} called without required arg(s): {', '.join(missing)}. "
            f"Please retry with the missing field(s) populated."
        )


def execute_tool(name: str, args: dict):
    # Registry dispatch (Phase B): if the tool is in FEATURE_REGISTRY,
    # validate required_args then call feature.execute(). Phase C3 adds
    # audit logging around the call so live-production decisions show up
    # in get_audit_log() (currently in-memory; JSONL flush is deferred).
    if name in _FEATURE_REGISTRY:
        feat = _FEATURE_REGISTRY[name]
        required = list(getattr(feat, "required_args", ()) or ())
        if required:
            _require_args(args, required, name)
        import time as _time
        from features.base import audit_log as _audit_log
        _t0 = _time.time()
        try:
            result = feat.execute(**args)
        except Exception:
            _audit_log(
                feature_name=name,
                question=None,
                applies_to_passed=True,
                relevance_score=None,
                executed=True,
                widget_emitted=False,
                duration_ms=int((_time.time() - _t0) * 1000),
                error=True,
                source="execute_tool",
            )
            raise
        _audit_log(
            feature_name=name,
            question=None,
            applies_to_passed=True,
            relevance_score=None,
            executed=True,
            widget_emitted=False,
            duration_ms=int((_time.time() - _t0) * 1000),
            error=False,
            source="execute_tool",
        )
        return result

    if name == "get_team_radio":
        _require_args(args, ["round_number", "session_type"], name)
        return get_team_radio(args["round_number"], args["session_type"], args.get("driver_ref"), args.get("limit", 10))
    if name == "get_intervals":
        _require_args(args, ["round_number"], name)
        return get_intervals(args["round_number"], args.get("driver_ref"), args.get("limit", 25), args.get("session_type", "R"))
    if name == "get_live_position_timeline":
        _require_args(args, ["round_number", "session_type"], name)
        return get_live_position_timeline(args["round_number"], args["session_type"], args.get("driver_ref"), args.get("limit", 50))
    if name == "analyze_qualifying_battle":
        _require_args(args, ["round_number", "driver_a", "driver_b"], name)
        return analyze_qualifying_battle(args["round_number"], args["driver_a"], args["driver_b"], session_type=args.get("session_type", "Q"))
    if name == "get_driver_standings":
        return get_drivers()[:args.get("limit", 20)]
    if name == "get_constructor_standings":
        return get_constructor_standings()
    if name == "get_driver_season_stats":
        _require_args(args, ["driver_name"], name)
        stats = get_driver_stats(args["driver_name"])
        if stats is None:
            raise ValueError(f"Driver not found: {args['driver_name']!r}. Try the driver's surname or 3-letter code.")
        return stats
    if name == "get_season_schedule":
        return get_circuits()
    if name == "get_race_results":
        _require_args(args, ["round_number"], name)
        return get_race_results(args["round_number"])
    if name == "get_qualifying_results":
        _require_args(args, ["round_number"], name)
        return get_qualifying_results(args["round_number"])
    if name == "get_session_results":
        _require_args(args, ["round_number", "session_type"], name)
        return get_session_results(args["round_number"], args["session_type"])
    if name == "get_head_to_head":
        _require_args(args, ["driver_a", "driver_b"], name)
        return get_head_to_head(args["driver_a"], args["driver_b"])
    if name == "get_driver_strategy":
        _require_args(args, ["round_number", "session_type"], name)
        return get_driver_strategy(args["round_number"], args["session_type"], args.get("driver_code"))
    if name == "get_sprint_results":
        _require_args(args, ["round_number"], name)
        return get_sprint_results(args["round_number"])
    if name == "get_sprint_qualifying_results":
        _require_args(args, ["round_number"], name)
        return get_sprint_qualifying_results(args["round_number"])
    if name == "get_driver_weekend_overview":
        _require_args(args, ["round_number", "driver_name"], name)
        return get_driver_weekend_overview(args["round_number"], args["driver_name"], session_type=args.get("session_type", "R"))
    if name == "get_driver_race_story":
        _require_args(args, ["round_number", "driver_name"], name)
        return get_driver_race_story(args["round_number"], args["driver_name"], session_type=args.get("session_type", "R"))
    if name == "get_team_weekend_overview":
        _require_args(args, ["round_number", "team_name"], name)
        return get_team_weekend_overview(args["round_number"], args["team_name"], session_type=args.get("session_type", "R"))
    if name == "get_race_report":
        _require_args(args, ["round_number"], name)
        return get_race_report(args["round_number"], session_type=args.get("session_type", "R"))
    if name == "get_qualifying_progression":
        _require_args(args, ["round_number"], name)
        return get_qualifying_progression(args["round_number"])
    if name == "get_session_fastest_laps":
        _require_args(args, ["round_number", "session_type"], name)
        return get_session_fastest_laps(args["round_number"], args["session_type"])
    if name == "get_driver_lap_times":
        _require_args(args, ["round_number", "session_type", "driver_code"], name)
        return get_driver_lap_times(args["round_number"], args["session_type"], args["driver_code"])
    if name == "get_clean_pace_summary":
        _require_args(args, ["round_number", "session_type"], name)
        return get_clean_pace_summary(
            args["round_number"],
            args["session_type"],
            args.get("driver_codes"),
            args.get("green_only", True),
            args.get("limit", 10),
        )
    if name == "get_sector_comparison":
        _require_args(args, ["round_number", "session_type", "driver_a", "driver_b"], name)
        return get_sector_comparison(args["round_number"], args["session_type"], args["driver_a"], args["driver_b"])
    if name == "compare_mini_sectors":
        _require_args(args, ["driver_a", "driver_b", "lap_number", "round_number"], name)
        return f1_data.compare_mini_sectors(
            driver_a=args["driver_a"],
            driver_b=args["driver_b"],
            lap_number=args["lap_number"],
            round_number=args["round_number"],
            session_type=args.get("session_type", "Q"),
            n=args.get("n", 25),
        )
    if name == "get_safety_car_periods":
        _require_args(args, ["round_number", "session_type"], name)
        return get_safety_car_periods(args["round_number"], args["session_type"])
    if name == "get_session_weather":
        _require_args(args, ["round_number", "session_type"], name)
        return get_session_weather(args["round_number"], args["session_type"])
    if name == "get_circuit_corners":
        _require_args(args, ["round_number"], name)
        return get_circuit_corners(args["round_number"])
    if name == "get_circuit_details":
        _require_args(args, ["round_number"], name)
        return get_circuit_details(args["round_number"])
    if name == "get_circuit_track_map":
        _require_args(args, ["round_number"], name)
        return get_circuit_track_map(args["round_number"])
    if name == "get_historical_circuit_performance":
        _require_args(args, ["round_number"], name)
        return get_historical_circuit_performance(args["round_number"], args.get("years"))
    if name == "analyze_cornering_loads":
        _require_args(args, ["round_number", "session_type", "driver_a", "driver_b"], name)
        return analyze_cornering_loads(
            args["round_number"],
            args["session_type"],
            args["driver_a"],
            args["driver_b"],
            args.get("lap_number_a"),
            args.get("lap_number_b"),
        )
    if name == "analyze_race_cornering_profile":
        _require_args(args, ["round_number", "driver_a", "driver_b"], name)
        return analyze_race_cornering_profile(
            args["round_number"],
            args["driver_a"],
            args["driver_b"],
        )
    if name == "get_lap_telemetry":
        _require_args(args, ["round_number", "session_type", "driver_code"], name)
        return get_lap_telemetry(args["round_number"], args["session_type"], args["driver_code"], args.get("lap_number"))
    if name == "analyze_energy_management":
        _require_args(args, ["round_number", "session_type", "driver_a"], name)
        return analyze_energy_management(
            args["round_number"],
            args["session_type"],
            args["driver_a"],
            args.get("driver_b"),
            args.get("lap_number_a"),
            args.get("lap_number_b"),
        )
    if name == "analyze_override_usage":
        _require_args(args, ["driver_code", "round_number", "session_type", "lap_number"], name)
        return analyze_override_usage(
            args["driver_code"],
            args["round_number"],
            args["session_type"],
            args["lap_number"],
        )
    if name == "analyze_active_aero_usage":
        _require_args(args, ["driver_code", "round_number", "session_type", "lap_number"], name)
        return analyze_active_aero_usage(
            args["driver_code"],
            args["round_number"],
            args["session_type"],
            args["lap_number"],
        )
    if name == "get_telemetry_comparison":
        _require_args(args, ["round_number", "session_type", "driver_a", "driver_b"], name)
        return get_telemetry_comparison(
            args["round_number"],
            args["session_type"],
            args["driver_a"],
            args["driver_b"],
            args.get("lap_number_a"),
            args.get("lap_number_b"),
        )
    if name == "get_track_position_comparison":
        _require_args(args, ["round_number", "session_type", "driver_a", "driver_b"], name)
        return get_track_position_comparison(
            args["round_number"],
            args["session_type"],
            args["driver_a"],
            args["driver_b"],
            args.get("lap_number_a"),
            args.get("lap_number_b"),
        )
    if name == "get_race_control_messages":
        _require_args(args, ["round_number", "session_type"], name)
        return get_race_control_messages(
            args["round_number"],
            args["session_type"],
            args.get("category"),
            args.get("limit", 50),
        )
    if name == "extract_corner_profiles":
        _require_args(args, ["round_number", "session_type", "driver_code"], name)
        return extract_corner_profiles(
            args["round_number"],
            args["session_type"],
            args["driver_code"],
            args.get("lap_number"),
        )
    if name == "compare_corner_profiles":
        _require_args(args, ["round_number", "session_type", "driver_a", "driver_b"], name)
        return compare_corner_profiles(
            args["round_number"],
            args["session_type"],
            args["driver_a"],
            args["driver_b"],
            args.get("lap_number_a"),
            args.get("lap_number_b"),
        )
    if name == "analyze_stint_degradation":
        _require_args(args, ["round_number", "driver_code"], name)
        return analyze_stint_degradation(
            args["round_number"],
            args["driver_code"],
            args.get("session_type", "R"),
        )
    if name == "analyze_race_pace_battle":
        _require_args(args, ["round_number", "driver_a", "driver_b"], name)
        return analyze_race_pace_battle(
            args["round_number"],
            args["driver_a"],
            args["driver_b"],
            args.get("session_type", "R"),
        )
    if name == "analyze_team_performance":
        _require_args(args, ["round_number", "team_name", "session_type"], name)
        return analyze_team_performance(
            args["round_number"],
            args["team_name"],
            args["session_type"],
        )
    if name == "analyze_team_circuit_fit":
        _require_args(args, ["team_name"], name)
        return analyze_team_circuit_fit(
            args["team_name"],
            args.get("years"),
            args.get("session_type", "Q"),
        )
    if name == "analyze_team_telemetry_traits":
        _require_args(args, ["round_number", "team_name"], name)
        return analyze_team_telemetry_traits(
            args["round_number"],
            args["team_name"],
            args.get("session_type", "Q"),
            args.get("field_limit", 10),
        )
    if name == "get_team_car_profile":
        _require_args(args, ["team_name"], name)
        profile = get_team_car_profile(args["team_name"])
        if profile is None:
            logger.warning(
                "Missing team_car_profile for query=%r — add an entry to team_car_profiles.py",
                args["team_name"],
            )
            return {
                "team_query": args["team_name"],
                "profile_type": "curated_editorial",
                "available": False,
                "caveat": "No sourced public-reporting profile is currently curated for this team.",
                "guidance_for_model": (
                    "I do not have a curated car-character profile for this team. "
                    "Do not invent traits — say the profile is unavailable."
                ),
            }
        return profile
    if name == "get_circuit_profile":
        _require_args(args, ["country"], name)
        profile = get_circuit_profile(args["country"], args.get("event_name", ""))
        if profile is None:
            raise ValueError(f"No circuit profile found for country={args['country']!r}.")
        return profile
    if name == "get_driver_style_profile":
        _require_args(args, ["driver_a"], name)
        driver_b = args.get("driver_b")
        if driver_b:
            result = get_comparison_framing(args["driver_a"], driver_b)
            if result is None:
                a = get_driver_style(args["driver_a"])
                b = get_driver_style(driver_b)
                if a is None and b is None:
                    logger.warning(
                        "Missing driver_style profiles for both drivers in comparison: %r and %r — add entries to driver_styles.py",
                        args["driver_a"],
                        driver_b,
                    )
                    return {
                        "driver_a_query": args["driver_a"],
                        "driver_b_query": driver_b,
                        "profile_type": "curated_editorial",
                        "available": False,
                        "caveat": "No curated style profiles are available for either driver.",
                        "guidance_for_model": (
                            "I do not have curated style profiles for either driver. "
                            "Do not invent traits — say the profiles are unavailable."
                        ),
                    }
                return {"driver_a": a, "driver_b": b}
            return result
        profile = get_driver_style(args["driver_a"])
        if profile is None:
            logger.warning(
                "Missing driver_style profile for query=%r — add an entry to driver_styles.py",
                args["driver_a"],
            )
            return {
                "driver_query": args["driver_a"],
                "profile_type": "curated_editorial",
                "available": False,
                "caveat": "No curated style profile is available for this driver.",
                "guidance_for_model": (
                    "I do not have a curated style profile for this driver. "
                    "Do not invent traits — say the profile is unavailable."
                ),
            }
        return profile
    if name == "get_pit_stop_analysis":
        _require_args(args, ["round_number"], name)
        return get_pit_stop_analysis(args["round_number"])
    if name == "analyze_weather_pace_correlation":
        _require_args(args, ["round_number"], name)
        return analyze_weather_pace_correlation(args["round_number"], args.get("session_type", "Q"))
    if name == "get_fp_summary":
        _require_args(args, ["round_number", "fp_number"], name)
        return get_fp_summary(args["round_number"], args["fp_number"])
    if name == "analyze_undercut_overcut":
        _require_args(args, ["driver_code", "lap_number"], name)
        round_number = args.get("round_number")
        if round_number is None:
            from f1_data import CURRENT_YEAR  # noqa: F401  (use as fallback)
            circuits = get_circuits()
            if circuits:
                round_number = circuits[-1].get("round")
        if round_number is None:
            raise ValueError("analyze_undercut_overcut requires round_number when no schedule is available.")
        return analyze_undercut_overcut(
            args["driver_code"],
            args["lap_number"],
            int(round_number),
            args.get("target_driver_code"),
            args.get("session_type", "R"),
        )
    if name == "get_speed_trap_leaderboard":
        _require_args(args, ["round_number", "session_type"], name)
        return get_speed_trap_leaderboard(
            args["round_number"],
            args["session_type"],
            bool(args.get("allow_mixed_drs", False)),
        )
    if name == "search_editorial_content":
        _require_args(args, ["query"], name)
        return _search_editorial_content_safe(
            args["query"],
            limit=int(args.get("limit", 5)),
            min_date=args.get("min_date"),
        )
    raise ValueError(f"Unknown tool: {name!r}")


# ---------------------------------------------------------------------------
# Feature-registry integration
# ---------------------------------------------------------------------------
#
# At import time, walk server/features/ and extend TOOL_DEFINITIONS +
# OPENAI_TOOL_DEFINITIONS with registered Feature classes. execute_tool
# checks FEATURE_REGISTRY first; falls back to the legacy if/elif chain
# for not-yet-migrated tools.

from features.registry import discover_features as _discover_features
from features.base import FEATURE_REGISTRY as _FEATURE_REGISTRY

_discover_features()


def _feature_to_anthropic_schema(feat) -> dict:
    return {
        "name": feat.name,
        "description": feat.description or "",
        "input_schema": feat.tool_schema or {"type": "object", "properties": {}},
    }


def _feature_to_openai_schema(feat) -> dict:
    return {
        "type": "function",
        "function": {
            "name": feat.name,
            "description": feat.description or "",
            "parameters": feat.tool_schema or {"type": "object", "properties": {}},
        },
    }


# Replace static entries with their registry equivalents (registry wins),
# and append any registry-only features.
_existing_anthropic = {t["name"]: i for i, t in enumerate(TOOL_DEFINITIONS)}
_existing_openai = {t["function"]["name"]: i for i, t in enumerate(OPENAI_TOOL_DEFINITIONS)}

for _name, _feat in _FEATURE_REGISTRY.items():
    if _name in _existing_anthropic:
        TOOL_DEFINITIONS[_existing_anthropic[_name]] = _feature_to_anthropic_schema(_feat)
    else:
        TOOL_DEFINITIONS.append(_feature_to_anthropic_schema(_feat))
    if _name in _existing_openai:
        OPENAI_TOOL_DEFINITIONS[_existing_openai[_name]] = _feature_to_openai_schema(_feat)
    else:
        OPENAI_TOOL_DEFINITIONS.append(_feature_to_openai_schema(_feat))
