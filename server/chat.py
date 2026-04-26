# server/chat.py
"""
Agentic chat loop supporting both Anthropic (Claude) and OpenAI (GPT).

Set LLM_PROVIDER=anthropic (default) or LLM_PROVIDER=openai in your .env.
The corresponding API key (ANTHROPIC_API_KEY / OPENAI_API_KEY) must also be set.
"""
import json
import os
import logging
import re
from typing import Any
import anthropic
try:
    import openai as openai_sdk
except ImportError:
    openai_sdk = None
from tools import TOOL_DEFINITIONS, OPENAI_TOOL_DEFINITIONS, execute_tool
from resolver import resolve_query_context, resolve_context_from_history
from driver_styles import get_comparison_framing
from circuit_profiles import get_circuit_profile
from energy_2026 import get_energy_2026_knowledge

MAX_TOOL_ROUNDS = 8
logger = logging.getLogger(__name__)

import datetime

CURRENT_YEAR = datetime.date.today().year


def _make_qualifying_battle_widget(result: dict) -> dict:
    return {
        "type": "qualifying_battle",
        "title": f"{result.get('driver_a')} vs {result.get('driver_b')}",
        "event": result.get("event"),
        "session": result.get("compared_segment") or result.get("session"),
        "driver_a": result.get("driver_a"),
        "driver_b": result.get("driver_b"),
        "faster_driver": result.get("faster_driver"),
        "overall_gap_s": result.get("overall_gap_s"),
        "decisive_sector": result.get("decisive_sector"),
        "decisive_sector_gap_s": result.get("decisive_sector_gap_s"),
        "decisive_corner": result.get("decisive_corner"),
        "cause_type": result.get("cause_type"),
        "cause_explanation": result.get("cause_explanation"),
        "cause_explanations": result.get("cause_explanations") or [],
        "zone_summary": result.get("zone_summary"),
        "energy_relevant": result.get("energy_relevant"),
        "energy_reason": result.get("energy_reason"),
        "is_teammate_comparison": result.get("is_teammate_comparison") or False,
        "teammate_context": result.get("teammate_context"),
        "sector_comparison": result.get("sector_comparison"),
        "style_comparison": result.get("style_comparison"),
        "speed_trace": result.get("speed_trace") or [],
        "track_map": result.get("track_map") or [],
        "focus_window_trace": result.get("focus_window_trace") or [],
    }


def _make_race_story_widget(result: dict) -> dict:
    race = result.get("race") or {}
    qualifying = result.get("qualifying") or {}
    radio = result.get("radio_highlights") or []
    return {
        "type": "race_story",
        "title": result.get("driver"),
        "subtitle": result.get("event"),
        "driver_code": result.get("code"),
        "team": result.get("team"),
        "grid_position": race.get("grid_position") or qualifying.get("position"),
        "finish_position": race.get("finish_position"),
        "points": race.get("points"),
        "status": race.get("status"),
        "pit_stops": result.get("pit_stops") or [],
        "story_points": result.get("story_points") or [],
        "interval_summary": result.get("interval_summary"),
        "position_timeline_summary": result.get("position_timeline_summary"),
        "radio_highlights": radio[:3],
        "rivalry_story": result.get("rivalry_story") or [],
    }


def _make_race_pace_battle_widget(result: dict) -> dict:
    aligned_stints = []
    for stint in result.get("aligned_stints") or []:
        stint_a = stint.get("driver_a") or stint.get("stint_a") or {}
        stint_b = stint.get("driver_b") or stint.get("stint_b") or {}
        laps_a = set(stint_a.get("lap_numbers") or [])
        laps_b = set(stint_b.get("lap_numbers") or [])
        overlap = len(laps_a & laps_b) if laps_a and laps_b else None
        aligned_stints.append({
            "compound": stint.get("compound"),
            "driver_a": stint_a,
            "driver_b": stint_b,
            "pace_delta_s": stint.get("pace_delta_s"),
            "deg_rate_delta": stint.get("deg_rate_delta"),
            "lap_overlap": overlap,
        })

    return {
        "type": "race_pace_battle",
        "title": f"{result.get('driver_a')} vs {result.get('driver_b')}",
        "event": result.get("event"),
        "session": result.get("session"),
        "driver_a": result.get("driver_a"),
        "driver_b": result.get("driver_b"),
        "fuel_corrected_pace_a_s": result.get("fuel_corrected_pace_a_s"),
        "fuel_corrected_pace_b_s": result.get("fuel_corrected_pace_b_s"),
        "overall_pace_delta_s": result.get("overall_pace_delta_s"),
        "avg_deg_rate_a_s_per_lap": result.get("avg_deg_rate_a_s_per_lap"),
        "avg_deg_rate_b_s_per_lap": result.get("avg_deg_rate_b_s_per_lap"),
        "deg_rate_delta": result.get("deg_rate_delta"),
        "decisive_factor": result.get("decisive_factor"),
        "aligned_stints": aligned_stints,
        "undercut_opportunity": result.get("undercut_opportunity"),
    }


def _make_corner_comparison_widget(result: dict) -> dict:
    return {
        "type": "corner_comparison",
        "title": f"{result.get('driver_a')} vs {result.get('driver_b')}",
        "event": result.get("event"),
        "session": result.get("session"),
        "driver_a": result.get("driver_a"),
        "driver_b": result.get("driver_b"),
        "faster_driver": result.get("faster_driver"),
        "overall_gap_s": result.get("overall_gap_s"),
        "setup_direction_inference": result.get("setup_direction_inference"),
        "gain_location_summary": result.get("gain_location_summary") or [],
        "cause_breakdown": result.get("cause_breakdown") or {},
        "avg_straight_speed_a_kph": result.get("avg_straight_speed_a_kph"),
        "avg_straight_speed_b_kph": result.get("avg_straight_speed_b_kph"),
    }


def _make_circuit_profile_widget(result: dict) -> dict:
    return {
        "type": "circuit_profile",
        "circuit_name": result.get("circuit_name"),
        "circuit_key": result.get("circuit_key"),
        "character": result.get("character"),
        "downforce_level": result.get("downforce_level"),
        "sector_1": result.get("sector_1"),
        "sector_2": result.get("sector_2"),
        "sector_3": result.get("sector_3"),
        "energy_profile": result.get("energy_profile"),
        "style_verdict": result.get("style_verdict"),
        "tyre_challenge": result.get("tyre_challenge"),
        "narrative": result.get("narrative"),
    }


def _widgets_from_preloaded(preloaded: dict | None) -> list[dict]:
    if not preloaded or "result" not in preloaded:
        return []
    tool = preloaded.get("tool")
    result = preloaded.get("result") or {}
    if tool == "get_driver_race_story":
        return [_make_race_story_widget(result)]
    if tool == "analyze_qualifying_battle":
        return [_make_qualifying_battle_widget(result)]
    if tool == "analyze_race_pace_battle":
        return [_make_race_pace_battle_widget(result)]
    if tool == "compare_corner_profiles":
        return [_make_corner_comparison_widget(result)]
    if tool == "analyze_team_performance" and isinstance(result.get("corner_comparison"), dict):
        return [_make_corner_comparison_widget(result["corner_comparison"])]
    return []


def _widgets_from_analysis_evidence(plan: dict, evidence: list[dict]) -> list[dict]:
    widgets = []
    has_primary_qualifying_widget = False
    for item in evidence:
        if item.get("tool") == "analyze_qualifying_battle" and "result" in item:
            has_primary_qualifying_widget = True
            break

    for item in evidence:
        if "result" not in item:
            continue
        tool = item.get("tool")
        if tool == "analyze_qualifying_battle":
            widgets.append(_make_qualifying_battle_widget(item["result"]))
        elif tool == "get_driver_race_story":
            widgets.append(_make_race_story_widget(item["result"]))
        elif tool == "analyze_race_pace_battle":
            widgets.append(_make_race_pace_battle_widget(item["result"]))
        elif tool == "compare_corner_profiles":
            if plan.get("focus") == "qualifying" and has_primary_qualifying_widget:
                continue
            widgets.append(_make_corner_comparison_widget(item["result"]))
        elif tool == "analyze_team_performance" and isinstance(item["result"].get("corner_comparison"), dict):
            widgets.append(_make_corner_comparison_widget(item["result"]["corner_comparison"]))
        elif tool == "get_circuit_profile":
            widgets.append(_make_circuit_profile_widget(item["result"]))

    deduped = []
    seen: set = set()
    for widget in widgets:
        key = (widget.get("type"), widget.get("title"), widget.get("subtitle"))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(widget)
    return deduped


def _merge_widgets(*groups: list[dict]) -> list[dict]:
    merged = []
    seen: set = set()
    for group in groups:
        for widget in group or []:
            key = (widget.get("type"), widget.get("title"), widget.get("subtitle"))
            if key in seen:
                continue
            seen.add(key)
            merged.append(widget)
    return merged


def _find_evidence_result(evidence: list[dict], tool_name: str) -> dict | None:
    for item in evidence:
        if item.get("tool") == tool_name and isinstance(item.get("result"), dict):
            return item["result"]
    return None


def _cause_label(cause_type: str | None) -> str:
    labels = {
        "braking": "braking",
        "minimum_speed": "minimum speed",
        "traction": "traction",
        "straight_line_speed": "straight-line speed",
        "straight_line_speed_energy_limited": "ERS clipping / straight-line speed",
        "mixed": "mixed telemetry",
    }
    return labels.get(cause_type or "", cause_type or "mixed telemetry")


def _canonical_reason_from_cause(cause: dict, result: dict) -> str:
    faster = result.get("faster_driver") or result.get("driver_a")
    slower = result.get("slower_driver") or result.get("driver_b")
    distance = cause.get("distance_m")
    delta = cause.get("delta_speed_kph")
    label = _cause_label(cause.get("cause_type"))
    distance_text = f" at {distance}m" if distance is not None else ""
    delta_text = f"{abs(delta):.1f} kph" if isinstance(delta, (int, float)) else "a speed"

    if cause.get("cause_type") == "straight_line_speed_energy_limited":
        cause_text = f"Cause: {slower} faded while still full throttle, consistent with earlier deployment taper or clipping."
    elif cause.get("cause_type") == "traction":
        cause_text = f"Cause: {faster} got to throttle earlier or cleaner on corner exit."
    elif cause.get("cause_type") == "braking":
        cause_text = f"Cause: {faster} carried the braking phase deeper while {slower} had already committed to the brake."
    elif cause.get("cause_type") == "minimum_speed":
        cause_text = f"Cause: {faster} carried a cleaner arc and did not slow the car as much mid-corner."
    elif cause.get("cause_type") == "straight_line_speed":
        cause_text = f"Cause: {faster} had the stronger straight-line speed phase."
    else:
        cause_text = f"Cause: {label} was the clearest telemetry mechanism."

    return f"{cause_text} Effect: {faster} was {delta_text} faster than {slower}{distance_text}."


def _canonicalize_qualifying_analysis(analysis: dict, evidence: list[dict]) -> dict:
    result = _find_evidence_result(evidence, "analyze_qualifying_battle")
    if not result:
        return analysis

    causes = result.get("cause_explanations") or []
    primary = causes[0] if causes else None
    if not primary:
        return analysis

    canonical = dict(analysis or {})
    faster = result.get("faster_driver")
    gap = result.get("overall_gap_s")
    sector = result.get("decisive_sector")
    sector_gap = result.get("decisive_sector_gap_s")
    distance = primary.get("distance_m") or result.get("decisive_distance_m")
    delta = primary.get("delta_speed_kph")
    location = result.get("decisive_corner") or (f"{distance}m" if distance is not None else "the decisive zone")

    gap_text = f"{abs(gap):.3f}s" if isinstance(gap, (int, float)) else "the gap"
    sector_text = (
        f", with {sector} worth {abs(sector_gap):.3f}s"
        if sector and isinstance(sector_gap, (int, float))
        else ""
    )
    delta_text = f" and a {abs(delta):.1f} kph speed difference" if isinstance(delta, (int, float)) else ""
    canonical["direct_answer"] = (
        f"{faster} was ahead by {gap_text}{sector_text}. "
        f"The primary marker is {location}{delta_text}."
    )
    canonical["primary_reason"] = _canonical_reason_from_cause(primary, result)
    canonical["secondary_reasons"] = [
        _canonical_reason_from_cause(cause, result)
        for cause in causes[1:3]
    ]
    canonical["strongest_evidence"] = result.get("strongest_evidence") or canonical.get("strongest_evidence") or []
    canonical["caveats"] = result.get("caveats") or canonical.get("caveats") or []
    canonical["confidence"] = canonical.get("confidence") or ("high" if result.get("telemetry_available") else "medium")
    return canonical


def _canonicalize_race_pace_analysis(analysis: dict, evidence: list[dict]) -> dict:
    result = _find_evidence_result(evidence, "analyze_race_pace_battle")
    if not result:
        return analysis

    canonical = dict(analysis or {})
    driver_a = result.get("driver_a")
    driver_b = result.get("driver_b")
    pace_delta = result.get("overall_pace_delta_s")
    deg_delta = result.get("deg_rate_delta")
    factor = result.get("decisive_factor")

    pace_leader = None
    if isinstance(pace_delta, (int, float)):
        pace_leader = driver_a if pace_delta < 0 else driver_b
        pace_loser = driver_b if pace_leader == driver_a else driver_a
        pace_text = f"{pace_leader} had the fuel-corrected pace edge by {abs(pace_delta):.3f}s/lap over {pace_loser}"
    else:
        pace_loser = None
        pace_text = "The clean-lap pace split was not strong enough to call from the available data"

    deg_leader = None
    if isinstance(deg_delta, (int, float)):
        deg_leader = driver_a if deg_delta < 0 else driver_b
        deg_loser = driver_b if deg_leader == driver_a else driver_a
        deg_text = f"{deg_leader}'s tyres degraded {abs(deg_delta):.3f}s/lap less than {deg_loser}'s"
    else:
        deg_text = "The degradation split was not available"

    if factor == "tyre_degradation" and deg_leader:
        canonical["direct_answer"] = f"{deg_leader} had the race-pace advantage mainly through degradation. {deg_text}."
        canonical["primary_reason"] = f"Cause: {deg_leader} kept the tyres alive better over the stint. Effect: {deg_text}."
    elif factor == "raw_pace_advantage" and pace_leader:
        canonical["direct_answer"] = f"{pace_text}. The decisive factor was raw pace rather than tyre fall-off."
        canonical["primary_reason"] = f"Cause: {pace_leader} was quicker on comparable clean laps after fuel correction. Effect: {pace_text}."
    elif factor == "strategy_execution":
        note = (result.get("undercut_opportunity") or {}).get("note")
        canonical["direct_answer"] = f"{pace_text}. The underlying pace and degradation split was small, so strategy execution mattered most."
        canonical["primary_reason"] = f"Cause: the pace and deg numbers were too close for one driver to win it on speed alone. Effect: {note or 'track position and stint timing became the deciding layer.'}"
    else:
        canonical["direct_answer"] = f"{pace_text}. The evidence is mixed rather than one clean race-pace cause."
        canonical["primary_reason"] = f"Cause: raw pace and tyre degradation did not point to a single dominant mechanism. Effect: {pace_text}."

    secondary = []
    if isinstance(deg_delta, (int, float)) and factor != "tyre_degradation":
        secondary.append(f"Cause: tyre drop-off still shaped the stint. Effect: {deg_text}.")
    if isinstance(pace_delta, (int, float)) and factor != "raw_pace_advantage":
        secondary.append(f"Cause: baseline clean-air pace still mattered. Effect: {pace_text}.")
    note = (result.get("undercut_opportunity") or {}).get("note")
    if note and factor != "strategy_execution":
        secondary.append(f"Cause: pit timing created a possible undercut layer. Effect: {note}")
    canonical["secondary_reasons"] = secondary[:3]
    canonical["strongest_evidence"] = canonical.get("strongest_evidence") or [
        pace_text,
        deg_text,
        f"Decisive factor: {factor or 'mixed'}",
    ]
    canonical["confidence"] = canonical.get("confidence") or "medium"
    return canonical

SYSTEM_PROMPT = f"""You are an expert Formula 1 analyst with access to real-time {CURRENT_YEAR} season data through tools.

Your job is to answer questions about the {CURRENT_YEAR} F1 season accurately, using the tools provided to fetch up-to-date data. Do not rely on your training knowledge for current standings, results, or points — always fetch the relevant data first.

Today's date is {datetime.date.today().isoformat()}.

Guidelines:
- If the user's latest message explicitly names a Grand Prix, circuit, round, year, or session, that explicit reference OVERRIDES prior conversation context.
- When the latest message explicitly names an event like "Japanese GP" or "Suzuka", resolve the event from get_season_schedule first before calling any race/session-specific tool.
- Do not let follow-up context about a previous race override a newly named event in the latest user message.
- For broad recap questions, prefer COMPOSITE RECAP TOOLS first. Use PRIMITIVE TOOLS only for narrower follow-up questions or when the user explicitly asks for one slice of information.
- For championship standings: use get_driver_standings or get_constructor_standings
- For a specific driver's season: use get_driver_season_stats
- For a broad question about a driver's race or weekend, start with get_driver_race_story or get_driver_weekend_overview before using any narrower tool
- For a broad question about a team's race or weekend, start with get_team_weekend_overview before using narrower team or driver tools
- For a broad question about the whole race, use get_race_report
- For rich classification, penalties, grid vs finish, or team-color/headshot metadata: use get_session_results
- For comparing two drivers: use get_head_to_head
- For race results: use get_race_results with the round number
- For qualifying: use get_qualifying_results
- For calendar/schedule questions OR when asked about "the most recent race" / "latest race": call get_season_schedule first to find which rounds have already occurred based on today's date, then fetch that round's results
- For stint/tyre strategy, pit timing, or undercut/overcut questions: use get_driver_strategy
- For qualifying storylines like who improved through Q1/Q2/Q3: use get_qualifying_progression
- For trustworthy pace rankings, especially when traffic, deleted laps, or yellows matter: use get_clean_pace_summary
- For sector-by-sector pace: use get_sector_comparison
- For causal qualifying battle questions like "why was Leclerc faster than Norris in quali?" use analyze_qualifying_battle
- For lap-by-lap pace: use get_driver_lap_times
- For corner-level analysis (braking points, gear shifts, throttle application): use get_lap_telemetry or get_telemetry_comparison. These include gear, RPM, throttle, and brake at every 100m — use them to make specific claims like "Norris was still in 4th gear at 1400m while Leclerc had already dropped to 3rd, braking 20m earlier"
- For structured corner profiles (entry/apex/exit speeds, braking point, gear at apex, traction point, straight acceleration, DRS, clipping) for a single driver: use extract_corner_profiles
- For comparing two drivers corner-by-corner (where the faster driver gains, cause classification, setup direction, avg straight speeds): use compare_corner_profiles
- For a team's setup direction or which teammate is stronger through the corners: use analyze_team_performance
- For tyre degradation rate, stint deg model, or how a driver's pace degraded per lap on a compound: use analyze_stint_degradation
- For race pace comparison between two drivers (fuel-corrected pace delta, degradation rates, undercut analysis, decisive factor): use analyze_race_pace_battle. Prefer this over manual lap time inspection for 'why did X pull away from Y in the race?' questions
- For 2026-style energy questions like lift-and-coast, clipping, super-clipping, deployment taper, or energy recovery behavior: use analyze_energy_management
- For racing-line or on-track position comparisons, track maps, or where a gain happened physically on the lap: use get_track_position_comparison
- For team radio or in-car context, use get_team_radio
- For live-style gap-to-leader / interval questions in a race, use get_intervals
- For cleaner position change timelines in a session, use get_live_position_timeline
- For richer circuit-map context like marshal sectors/lights or rotation for track-map overlays: use get_circuit_details or get_circuit_corners
- For safety car / VSC questions, strategy impact, who got screwed by the SC: use get_safety_car_periods
- For deleted laps, race control decisions, incidents, or steward-style explanations: use get_race_control_messages
- For weather conditions, rain timing, temperature impact on tyres/pace: use get_session_weather
- FastF1 does not provide direct ERS state of charge, harvest maps, or deployment maps. For energy questions, clearly distinguish measured telemetry from inference.

Answer quality rules:
- Lead with the number or the fact. "Russell finished P3, 8 seconds off the lead" beats "Russell had a solid race finishing in the top 3".
- Sound like a knowledgeable person explaining to someone who follows F1 — not an analyst filing a report. After the first mention, use "he" and "his", not the driver code or full name every sentence.
- Keep the driver as the active subject. "Norris was clipping at 600m" beats "the speed delta at 600m was indicative of clipping for Norris".
- No filler phrases: no "it's worth noting", no "interestingly", no "this suggests that", no "it appears", no "Additional factors included", no "reflecting his", no "consistent with", no "in line with". State things directly.
- Never say the same fact twice in different words across consecutive sentences.
- If data is missing, acknowledge it in a short embedded clause — not a standalone disclaimer sentence at the end. "without radio context, the deployment target is unclear" is fine. "The precise team strategies are unknown due to unavailable team radio footage." is not.
- Stay focused on exactly what was asked. If asked about one driver, lead with that driver.
- Use the conversation history for follow-up questions.
- 3-5 sentences for most answers. Use bullets only when listing genuinely separate items.
- If you cannot determine which specific race or round the question refers to, ask ONE short clarifying question before calling any data tools. Do not guess a round number and do not call tools with a missing or uncertain race context."""

def _build_analysis_system_prompt() -> str:
    energy = get_energy_2026_knowledge()
    energy_terms = "\n".join(f"  - {k}: {v}" for k, v in energy.get("terms", {}).items())
    energy_rules = "\n".join(f"  - {r}" for r in energy.get("interpretation_rules", []))
    energy_limits = "\n".join(f"  - {l}" for l in energy.get("limitations", []))

    return f"""You are the analysis stage for an F1 product.

You do not answer like a chatbot. You read retrieved evidence and produce a JSON analysis object.

## Core Analysis Rules
- Focus on causal explanation, not data recap.
- direct_answer must state WHERE the gap came from (sector, corner, distance) and HOW MUCH (seconds, kph). Never just "Driver A was faster due to X" — always "Driver A took Xs in SectorN" or "gap opened at Xm where A carried Y kph more".
- Identify the single biggest factor first, then keep going. You MUST populate secondary_reasons with at least 2 distinct, non-overlapping factors whenever the evidence supports them. Do not stop at one cause — a qualifying or race gap almost always has multiple contributing mechanisms. Find them all.
- Use only the strongest evidence from the supplied tool results.
- If the evidence includes a zone summary, decisive corner, decisive distance, or speed differential, those numbers must appear in direct_answer or primary_reason.
- Separate mechanism from outcome. Each primary_reason and secondary_reasons item must be understandable as: Cause = driver/car behavior or mechanism; Effect = measured telemetry or time outcome. Do not blur these together as a vague "because he was faster" statement.
- When mentioning a telemetry marker distance, state both what caused the gain and what effect it produced. Example: "Cause: Piastri carried a cleaner arc through Spoon. Effect: he was 11.2 kph faster at 3800m and that made Sector 2 decisive."
- Do not restate every statistic you see.
- Keep reasons non-overlapping. Each secondary reason must be a genuinely distinct mechanism from the primary.
- Do not claim setup, tyre condition, balance, confidence, or car behavior unless explicitly present in the supplied evidence.
- If telemetry or energy evidence is unavailable, say that clearly and do not invent a braking/traction/setup explanation.
- If the evidence is mixed or weak, say so in uncertainties.
- Output valid JSON only.

## Mechanism vocabulary — use in primary_reason and secondary_reasons
When naming mechanisms, use the language an F1 engineer or analyst would use:
- Braking gain: "carried the braking deeper", "later braking point", "better braking stability", "trail-braked into the corner"
- Traction gain: "got the power down earlier", "better traction off the apex", "more drive out of slow corners"
- Entry speed gain: "higher minimum speed", "more committed through the entry", "rolled more speed into the corner"
- High-speed gain: "more confident in the high-speed stuff", "carried it through the fast corners"
- Straight-line: "top speed advantage", "DRS gain", "drag penalty on the straight", "ran out of deployment early (clipping)"
- Tyre deg: "tyres went off the cliff", "graining cost them", "higher deg rate", "the tyre dropped out of its window"
- Strategy: "undercut worked", "came out on track position", "the free stop under the safety car"
- Qualifying specific: "purple in S2 was the difference", "left time on the table in the final sector", "found time on the second run"

## Driver Style Context
When the evidence contains a `context_type: driver_style_comparison` item, use the style codes to frame technique explanations. Each code has a plain-language meaning — use both:

- **corner_approach: v_line** — V-shaped corner. The driver carries the braking deep, commits hard and late, sharp rotation into a tight apex, lower minimum speed. Gains come in the braking zone and entry phase. In slow corners this driver outbrakes rivals and rotates the car aggressively. Watch for a speed advantage at the corner entry that disappears or reverses at exit.
- **corner_approach: u_line** — U-shaped arc. The driver brakes a fraction earlier, rolls speed through the mid-corner, higher minimum speed through a rounder arc. Gains come in fast sweepers and at corner exit — more speed onto the straight. Watch for a slight deficit at entry that's overturned by higher exit speed.
- **braking_style: late_aggressive** — pushes the braking point as deep as possible, threshold braking right at the limit, fully committed under braking. Big gains into slow corners when it works; risks locked fronts and flat spots when it doesn't.
- **braking_style: early_settle** — loads weight transfer progressively over a longer distance, the car is more settled at turn-in. Trades raw braking gain for better rotation and front-end feel — cleaner entry, less risk of overshoot.
- **throttle_style: early_explosive** — gets the power down before the apex, plants the throttle early, high exit speed. Demands good traction from the car; if the rear steps out, they're managing wheelspin instead of driving the straight.
- **throttle_style: gradual** — feeds in the power progressively, especially effective on worn rubber. Easier on the tyres and less wheelspin, but leaves some exit speed on the table compared to an explosive application.
- **car_preference: oversteer** — pointed car, trusts the loose rear end, uses the slide to rotate. Quick and aggressive when the rear is predictable; a handful if it snaps.
- **car_preference: understeer** — stable rear, front-led turn-in, the front initiates late. Consistent and manageable but limits rotation speed in tight corners.

Treat style profiles as hypotheses to test against the telemetry, not as facts. A driver's known style predicts where they should gain — check whether the actual data confirms or contradicts it. Never cite style profile alone as evidence; it must be corroborated by a tool result.

## Circuit Profile Context
When the evidence contains a `context_type: circuit_profile` item, treat it as **background hypothesis, not fact**. It is curated prior knowledge about circuit character — not derived from the actual session telemetry. The telemetry and tool results always take precedence.

Use it as a starting hypothesis to test against the real data:
- If sector_2 is high_speed_sweepers with u_line_favored AND the telemetry confirms the U-line driver gained there — the profile matches, use it to strengthen the explanation
- If the telemetry contradicts the profile's prediction — say so explicitly. The real data wins. Explain why the expected pattern didn't hold (track evolution, setup, compound, conditions)
- Use energy_profile.clipping_risk as a prompt to CHECK the telemetry for late-straight speed fade — not as confirmation that clipping occurred
- Use tyre_challenge as a framing hypothesis for degradation differences — verify against actual stint data before citing it
- Never cite the circuit profile alone as evidence. It must be corroborated by a tool result to appear in primary_reason or secondary_reasons

## 2026 Energy Rules
Known facts:
  - MGU-K output is ~350 kW (up from 120 kW previous era)
  - Target ~8.5 MJ per lap of energy recuperation under braking
  - No MGU-H — recovery is braking-centric
  - At high speed, deployment can taper early so the car is at full throttle but no longer accelerating at the same rate

Key terms:
{energy_terms}

Interpretation rules:
{energy_rules}

Limitations — always apply these:
{energy_limits}

## Cornering Load & Grip Utilisation Data
When evidence contains results from `analyze_cornering_loads` or `analyze_race_cornering_profile`, you are writing about driving CHARACTER — not metrics. Use the F1 vocabulary below. Every number must serve a character description, not the other way around.

**Metric → F1 character language:**

- **High grip utilisation** → *tyre confidence*, *committed to the limit*, *trusting the front end*, *really carrying it in*, *not leaving anything on the table*, *leaning on the rubber*. Say: "NOR had more confidence in the front end — really committed through every corner" then cite the 74% as proof.
- **Low grip utilisation** → *measured*, *more comfort window*, *not fully leaning on it*, *keeping something in reserve*. In a race this is often a strength: the tyre hasn't been asked to do as much.
- **High pct_above_90_grip** → *operating right on the edge*, *no margin*, *fully committed*, *living on the absolute limit*, *nothing left to give*. Physically this means the tyre is at maximum lateral load — any more and it slides. "For a third of every corner he had no safety net — fully committed, the car on the absolute edge."
- **High avg_load_variance** → the driver is **fighting the car** — *making corrections through the apex*, *chasing oversteer*, *chasing understeer*, *a bit twitchy*, *the car's a handful*, *hacking at the wheel*, *can't get it settled*. Use oversteer/understeer language: "the rear was getting a bit loose through the apex" (if combined with high corrections at exit) or "the car was pushing wide on entry, he was fighting the front" (if corrections cluster at entry). The key phrase: *working the tyre harder than the lap time requires*.
- **Low avg_load_variance** → *smooth arc*, *natural rotation*, *one committed first input and holds it*, *the car does exactly what he asks*, *planted through the apex*, *progressive and clean*. "PIA was rotating the car in one smooth arc — the load barely flickered."
- **High corrections_per_corner** → *chasing the balance*, *having to react mid-corner*, *fighting oversteer* or *fighting understeer*. More corrections = the driver is a passenger for part of the corner. "NOR was making four or five corrections where PIA needed two — he was having to drive the car more."
- **Low corrections_per_corner** → *clean committed arc*, *natural rotation*, *one input and done*, *drives the car in rather than reacting to it*.

**Inferences you can draw from combined signals:**
- High util + low variance = *confident, committed, clean* — extracting maximum lap time, tyre being loaded efficiently
- High util + high variance = *committed but fighting it* — fast single lap but burning the tyre, the rear or front is edgy
- Low util + low variance = *smooth and measured* — easy on the rubber, strong race pace but may leave qualifying time on the table
- Low util + high variance = *struggling for confidence* — fighting the car without pushing hard enough to compensate, the worst combination
- High corrections at high speed = rear stepping out under load, *snap oversteer*, the car is pointy and the driver is managing it
- High corrections at low speed = *rotating problem*, car won't change direction cleanly, *the front's not biting*

**Core vocabulary list to use naturally:**
oversteer, understeer, snap oversteer, trailing the rear, the rear's loose, the front's not biting, pushing wide, washes wide, fighting the car, chasing the rear, chasing the balance, committed, on the limit, no margin, natural rotation, rotating the car, one clean arc, smooth progressive arc, the car does what he asks, leaning on the front, trusting the rubber, tyre confidence, living on the edge, pointed car, planted rear, front-end bite, carrying it in, pointy setup, the car's a handful, the rear gets snappy

**Rules:**
- Write about the DRIVER and their CHARACTER first. Numbers are proof of the character claim.
- Use oversteer/understeer naturally — these are the words F1 fans understand.
- Qualifying: more commitment + cleaner inputs = more single-lap time. Race: high commitment + high variance = *the confidence level drops as the stint ages — the tyre can't keep holding that level of demand*.
- Never say "lateral load variance" or "grip utilisation percentage" in the answer. Use the vocabulary above instead.

## Required JSON Output
- direct_answer: string — must include WHERE and HOW MUCH
- primary_reason: string
- secondary_reasons: array of strings (minimum 2 when evidence supports)
- strongest_evidence: array of strings
- caveats: array of strings
- confidence: one of high, medium, low
"""

ANALYSIS_SYSTEM_PROMPT = _build_analysis_system_prompt()

ANSWER_WRITER_SYSTEM_PROMPT = """You are the final answer writer for an F1 analysis product.

You will receive a structured analysis JSON object. Write the final user-facing answer.

Voice: You're a knowledgeable F1 person explaining what happened to another fan — not an analyst filing a report, not a commentator reading stats off a sheet. Think Karun Chandhok or Anthony Davidson in a post-session debrief: direct, specific, character-driven. You use the words F1 fans know.

## F1 vocabulary — use these naturally, not as a checklist

**Handling & cornering commitment:**
oversteer, understeer, snap oversteer, loose rear, the rear steps out, the front's not biting, pushing wide, washes wide, pointed car, planted rear, front-end bite, tyre confidence, committed to the limit, carrying it in, leaning on the front, trusting the rubber, on the edge, no margin, fully committed, not leaving anything on the table, natural rotation, one clean arc, chasing the balance, fighting the car, a bit twitchy, the car does what he asks

**Braking:**
carries the braking deep, late on the brakes, threshold braking, trail braking, locked the fronts, binding the brakes, gets it stopped later, braking stability, pushes the braking point, really committed under braking, flat spot, overbraking, the braking zone, outbrakes him

**Traction & exit:**
gets the power down early, plants the throttle, traction limited, wheelspin, squaring off the corner, opens the steering early, gets drive out of the slow corners, exit wheelspin, chases the rear under power, gains on exit, loses it on the way out

**Qualifying:**
purple sector, personal best, left time on the table, banker lap, flying lap, tow, slipstream, found the grip on the second run, the track came to him, pushed everything onto that lap, scrubbed set, green tyre, hung it all out, the lap was already cooked before S3, committed everything to that corner

**Tyres & degradation:**
going off the cliff, tyres on their knees, graining, blistering, deg rate, thermal deg, mechanical wear, the rubber goes away, falls out of the window, the tyre can't hold this, the pace just drops off, working the rubber harder than the lap requires, the tyre's not in its window, scrubbing heat in, managing heat

**Race pace management:**
push laps, coasting lap, backing into the tyres, managing the pace, lift and coast, negative split, positive split, in clean air, stuck in traffic, DRS train, track position, open road ahead

**Strategy:**
undercut, overcut, free pit stop, pit window, safety car window, VSC, covering the undercut, the strategy call, sitting on old rubber, fresh rubber, building the gap, gap management, nailed the out-lap, came out in traffic

**Straight-line & energy:**
top speed trap, slipstream, tow, drag penalty, sacrificing downforce, high-drag setup, losing it on the straights, gains it all back in the corners, clipping (deployment runs out before end of straight), harvesting under braking

## Rules

- Open with WHERE and HOW MUCH. Name the sector, corner, or distance. "Leclerc took 0.3s in Sector 2" or "The gap opened at 800m — he was carrying 21 kph more."
- Explain every major reason as cause then effect. The cause is the driver behavior, car behavior, setup/deployment mechanism, or technique. The effect is the measured result: time gained, speed delta, sector gap, or throttle/brake outcome.
- Do not write a loose second explanation after the widget-style summary. If you add supporting points, make them explicitly connected to the same P/S/T-style markers: "Cause: ... Effect: ..."
- Never present telemetry effects as if they are separate causes. "He was 11 kph faster" is an effect; the cause is "he carried a cleaner mid-corner arc" or "he got to throttle earlier."
- Do not introduce extra mechanisms in later paragraphs unless they are in primary_reason or secondary_reasons. If you mention an extra brake/coast or style observation, label it as supporting context, not another reason for the gap.
- Driver is the subject. "Norris was already clipping at 600m" not "a speed fade was observed for Norris." Use "he" and "his" freely.
- Plain language. "He ran out of deployment earlier down the straight" not "an earlier deployment taper."
- Never say the same thing twice.
- No filler: no "this advantage allowed", "Additional factors included", "reflecting his", "consistent with", "pointing to", "it appears".
- No energy rule primer — say what the data showed, one clause, move on.
- No standalone disclaimer at the end. Embed qualifiers mid-sentence.
- 3-5 sentences. Use bullets only for genuinely separate contributing factors.
- For cornering data: NEVER say "lateral load variance", "grip utilisation percentage", "avg_corrections_per_corner". Those are internal metrics. Translate to character language: "Norris had more tyre confidence — really committed, on the absolute limit for a third of every corner" is correct. "Norris had 74% avg_grip_utilisation_pct" is completely wrong.
- For tyre data: NEVER say "deg_rate_delta" or "fuel-corrected pace". Say "his tyres were dropping off faster" or "once you strip out the fuel, he had the edge on raw pace."
"""


# ── Anthropic ────────────────────────────────────────────────────────────────

_anthropic_client: anthropic.Anthropic | None = None


def _suggested_tool_args(resolved: dict) -> dict | None:
    tool = resolved.get("suggested_tool")
    round_number = resolved.get("round_number")
    if not tool or round_number is None:
        return None

    if tool in ("get_driver_race_story", "get_driver_weekend_overview"):
        if not resolved.get("entity_name"):
            return None
        return {"round_number": round_number, "driver_name": resolved["entity_name"]}

    if tool == "get_team_weekend_overview":
        if not resolved.get("entity_name"):
            return None
        return {"round_number": round_number, "team_name": resolved["entity_name"]}

    if tool == "get_race_report":
        return {"round_number": round_number}

    if tool == "get_safety_car_periods":
        session_type = resolved.get("session_type") or "R"
        return {"round_number": round_number, "session_type": session_type}

    if tool == "get_team_radio":
        session_type = resolved.get("session_type") or "R"
        args = {"round_number": round_number, "session_type": session_type}
        if resolved.get("entity_code"):
            args["driver_ref"] = resolved["entity_code"]
        return args

    if tool == "analyze_energy_management":
        session_type = resolved.get("session_type") or "Q"
        if resolved.get("entity_type") == "driver" and resolved.get("entity_code"):
            return {
                "round_number": round_number,
                "session_type": session_type,
                "driver_a": resolved["entity_code"],
            }
        if resolved.get("entity_type") == "multi_driver" and len(resolved.get("entity_codes") or []) >= 2:
            codes = resolved["entity_codes"]
            return {
                "round_number": round_number,
                "session_type": session_type,
                "driver_a": codes[0],
                "driver_b": codes[1],
            }

    return None


def _extract_json_object(text: str) -> dict:
    try:
        return json.loads(text)
    except Exception:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            raise
        return json.loads(match.group(0))


def _build_analysis_plan(message: str, resolved: dict) -> dict | None:
    analysis_mode = resolved.get("analysis_mode")
    round_number = resolved.get("round_number")

    # ── circuit_profile mode ─────────────────────────────────────────────────
    if analysis_mode == "circuit_profile":
        country = resolved.get("country")
        event_name = resolved.get("event_name")
        if not country:
            return None
        tool_calls = [
            ("get_circuit_profile", {"country": country, "event_name": event_name or ""}),
        ]
        if round_number:
            tool_calls.append(("get_historical_circuit_performance", {"round_number": round_number}))
        return {
            "analysis_mode": "circuit_profile",
            "focus": "circuit",
            "question": message,
            "round_number": round_number,
            "event_name": event_name,
            "country": country,
            "tool_calls": tool_calls,
        }

    # ── team_performance mode ────────────────────────────────────────────────
    if analysis_mode == "team_performance":
        team = resolved.get("entity_name")
        if round_number is None or not team:
            return None
        session_type = resolved.get("session_type") or "Q"
        return {
            "analysis_mode": "team_performance",
            "focus": "team",
            "question": message,
            "round_number": round_number,
            "event_name": resolved.get("event_name"),
            "country": resolved.get("country"),
            "team": team,
            "tool_calls": [
                ("analyze_team_performance", {
                    "round_number": round_number,
                    "team_name": team,
                    "session_type": session_type,
                }),
            ],
        }

    # ── race_pace_comparison mode ────────────────────────────────────────────
    if analysis_mode == "race_pace_comparison":
        codes = resolved.get("entity_codes") or []
        names = resolved.get("entity_names") or []
        if round_number is None or len(codes) < 2 or len(names) < 2:
            return None
        session_type = resolved.get("session_type") or "R"
        return {
            "analysis_mode": "race_pace_comparison",
            "focus": "race",
            "question": message,
            "round_number": round_number,
            "event_name": resolved.get("event_name"),
            "country": resolved.get("country"),
            "drivers": [
                {"name": names[0], "code": codes[0]},
                {"name": names[1], "code": codes[1]},
            ],
            "tool_calls": [
                ("analyze_race_pace_battle", {
                    "round_number": round_number,
                    "driver_a": codes[0],
                    "driver_b": codes[1],
                    "session_type": session_type,
                }),
                ("get_safety_car_periods", {"round_number": round_number, "session_type": session_type}),
                ("get_driver_strategy", {"round_number": round_number, "session_type": session_type}),
            ],
        }

    # ── driver_comparison mode ───────────────────────────────────────────────
    if analysis_mode != "driver_comparison":
        return None

    codes = resolved.get("entity_codes") or []
    names = resolved.get("entity_names") or []
    if round_number is None or len(codes) < 2 or len(names) < 2:
        return None

    focus = resolved.get("analysis_focus") or ("qualifying" if resolved.get("session_type") == "Q" else "race")
    session_type = "Q" if focus == "qualifying" else (resolved.get("session_type") or "R")

    plan = {
        "analysis_mode": "driver_comparison",
        "focus": focus,
        "question": message,
        "round_number": round_number,
        "event_name": resolved.get("event_name"),
        "country": resolved.get("country"),
        "drivers": [
            {"name": names[0], "code": codes[0]},
            {"name": names[1], "code": codes[1]},
        ],
        "tool_calls": [],
    }

    if focus == "qualifying":
        plan["tool_calls"] = [
            ("get_qualifying_results", {"round_number": round_number}),
            ("analyze_qualifying_battle", {
                "round_number": round_number,
                "driver_a": codes[0],
                "driver_b": codes[1],
            }),
            ("compare_corner_profiles", {
                "round_number": round_number,
                "session_type": "Q",
                "driver_a": codes[0],
                "driver_b": codes[1],
            }),
            ("get_team_radio", {
                "round_number": round_number,
                "session_type": "Q",
                "driver_ref": codes[0],
                "limit": 6,
            }),
            ("get_team_radio", {
                "round_number": round_number,
                "session_type": "Q",
                "driver_ref": codes[1],
                "limit": 6,
            }),
        ]
        return plan

    if focus in ("race", "session"):
        plan["tool_calls"] = [
            ("get_driver_race_story", {"round_number": round_number, "driver_name": names[0]}),
            ("get_driver_race_story", {"round_number": round_number, "driver_name": names[1]}),
            ("analyze_race_pace_battle", {
                "round_number": round_number,
                "driver_a": codes[0],
                "driver_b": codes[1],
                "session_type": resolved.get("session_type") or "R",
            }),
            ("get_safety_car_periods", {
                "round_number": round_number,
                "session_type": resolved.get("session_type") or "R",
            }),
        ]
        return plan

    return None


def _retrieve_analysis_evidence(plan: dict, resolved: dict | None = None) -> list[dict]:
    evidence = []
    for tool_name, args in plan.get("tool_calls", []):
        try:
            logger.info("Deterministic analysis tool call: %s args=%s", tool_name, args)
            evidence.append({
                "tool": tool_name,
                "args": args,
                "result": execute_tool(tool_name, args),
            })
        except Exception as exc:
            evidence.append({
                "tool": tool_name,
                "args": args,
                "error": str(exc),
            })

    # ── Auto-inject driver style context ────────────────────────────────────
    drivers = plan.get("drivers") or []
    if len(drivers) >= 2:
        try:
            style = get_comparison_framing(drivers[0]["code"], drivers[1]["code"])
            if style:
                evidence.append({
                    "context_type": "driver_style_comparison",
                    "driver_a": drivers[0]["code"],
                    "driver_b": drivers[1]["code"],
                    "data": style,
                })
        except Exception as exc:
            logger.warning("Driver style context injection failed: %s", exc)

    # ── Auto-inject circuit profile ─────────────────────────────────────────
    country = plan.get("country") or (resolved.get("country") if resolved else None)
    event_name = plan.get("event_name") or (resolved.get("event_name") if resolved else None)
    if country:
        try:
            profile = get_circuit_profile(country, event_name or "")
            if profile:
                evidence.append({
                    "context_type": "circuit_profile",
                    "country": country,
                    "event_name": event_name,
                    "data": profile,
                })
        except Exception as exc:
            logger.warning("Circuit profile context injection failed: %s", exc)

    return evidence


def _prepare_resolved_context(message: str, history: list[dict]) -> tuple[dict, dict | None]:
    previous_context = resolve_context_from_history(history)
    return _prepare_resolved_context_from_previous(message, previous_context)


def _prepare_resolved_context_from_previous(message: str, previous_context: dict | None) -> tuple[dict, dict | None]:
    resolved = resolve_query_context(message, previous_context)

    preloaded = None
    if resolved.get("routing_confidence") == "high":
        args = _suggested_tool_args(resolved)
        tool = resolved.get("suggested_tool")
        if tool and args:
            try:
                logger.info("Preloading suggested tool: %s args=%s", tool, args)
                preloaded = {
                    "tool": tool,
                    "args": args,
                    "result": execute_tool(tool, args),
                }
            except Exception as exc:
                logger.warning("Preload failed for tool %s args=%s error=%s", tool, args, exc)
                preloaded = {
                    "tool": tool,
                    "args": args,
                    "error": str(exc),
                }

    return resolved, preloaded


def _build_request_system_prompt(resolved: dict, preloaded: dict | None) -> str:
    if not resolved.get("has_explicit_context") and not resolved.get("used_previous_context"):
        return SYSTEM_PROMPT

    lines = [
        "Deterministic backend-resolved context for the latest user message:",
        f"- entity_type: {resolved.get('entity_type')}",
        f"- entity_name: {resolved.get('entity_name')}",
        f"- entity_code: {resolved.get('entity_code')}",
        f"- event_name: {resolved.get('event_name')}",
        f"- round_number: {resolved.get('round_number')}",
        f"- session_type: {resolved.get('session_type')}",
        f"- scope: {resolved.get('scope')}",
        f"- suggested_tool: {resolved.get('suggested_tool')}",
        f"- resolution_confidence: {resolved.get('resolution_confidence')}",
        f"- routing_confidence: {resolved.get('routing_confidence')}",
        f"- used_previous_context: {resolved.get('used_previous_context')}",
        "Treat this resolved context as higher priority than ambiguous prior chat history.",
    ]

    if resolved.get("routing_confidence") == "medium" and resolved.get("suggested_tool"):
        lines.append(
            f"Routing directive: start with {resolved.get('suggested_tool')} unless the latest message explicitly requires a narrower tool."
        )

    needs_clarification = resolved.get("needs_clarification")
    if needs_clarification == "which_race":
        lines.append(
            "⚠ CLARIFICATION NEEDED: The resolver could not determine which race this question refers to. "
            "Ask the user which race or round they mean — one short question. Do NOT call any data tools yet."
        )
    elif needs_clarification == "general_ambiguity":
        lines.append(
            "⚠ CLARIFICATION NEEDED: The question is too ambiguous to route confidently. "
            "Ask one short clarifying question to understand what the user is looking for. Do NOT call any tools yet."
        )

    if preloaded:
        lines.append("High-confidence backend preloaded tool result:")
        lines.append(f"- preloaded_tool: {preloaded.get('tool')}")
        lines.append(f"- preloaded_args: {preloaded.get('args')}")
        if "result" in preloaded:
            lines.append(f"- preloaded_result_json: {json.dumps(preloaded['result'], default=str)}")
        if "error" in preloaded:
            lines.append(f"- preloaded_error: {preloaded['error']}")

    return SYSTEM_PROMPT + "\n\n" + "\n".join(lines)


def _build_analysis_user_prompt(question: str, resolved: dict, plan: dict, evidence: list[dict]) -> str:
    payload = {
        "question": question,
        "resolved_context": {
            "event_name": resolved.get("event_name"),
            "round_number": resolved.get("round_number"),
            "session_type": resolved.get("session_type"),
            "analysis_mode": resolved.get("analysis_mode"),
            "analysis_focus": resolved.get("analysis_focus"),
            "entity_names": resolved.get("entity_names"),
            "entity_codes": resolved.get("entity_codes"),
        },
        "plan": plan,
        "evidence": evidence,
    }
    return json.dumps(payload, default=str)


def _build_answer_writer_prompt(question: str, analysis: dict) -> str:
    return json.dumps({
        "question": question,
        "analysis": analysis,
    }, default=str)


def _try_deterministic_analysis(question: str, history: list[dict], *, provider: str) -> dict | None:
    previous_context = resolve_context_from_history(history)
    resolved = resolve_query_context(question, previous_context)
    plan = _build_analysis_plan(question, resolved)
    if not plan:
        return None

    evidence = _retrieve_analysis_evidence(plan, resolved)
    if not evidence:
        return None

    try:
        if provider == "openai":
            analysis = _run_openai_analysis(question, resolved, plan, evidence)
            if plan.get("focus") == "qualifying":
                analysis = _canonicalize_qualifying_analysis(analysis, evidence)
            elif plan.get("analysis_mode") == "race_pace_comparison":
                analysis = _canonicalize_race_pace_analysis(analysis, evidence)
            return {
                "response": _run_openai_answer_writer(question, analysis),
                "widgets": _widgets_from_analysis_evidence(plan, evidence),
            }

        analysis = _run_anthropic_analysis(question, resolved, plan, evidence)
        if plan.get("focus") == "qualifying":
            analysis = _canonicalize_qualifying_analysis(analysis, evidence)
        elif plan.get("analysis_mode") == "race_pace_comparison":
            analysis = _canonicalize_race_pace_analysis(analysis, evidence)
        return {
            "response": _run_anthropic_answer_writer(question, analysis),
            "widgets": _widgets_from_analysis_evidence(plan, evidence),
        }
    except Exception as exc:
        logger.warning("Deterministic analysis failed; falling back to normal tool loop. error=%s", exc)
        return None

def _get_anthropic_client() -> anthropic.Anthropic:
    global _anthropic_client
    if _anthropic_client is None:
        _anthropic_client = anthropic.Anthropic(
            api_key=os.environ.get("ANTHROPIC_API_KEY")
        )
    return _anthropic_client


def _run_anthropic_analysis(question: str, resolved: dict, plan: dict, evidence: list[dict]) -> dict:
    client = _get_anthropic_client()
    response = client.messages.create(
        model="claude-opus-4-7",
        max_tokens=1200,
        system=ANALYSIS_SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": _build_analysis_user_prompt(question, resolved, plan, evidence),
        }],
    )
    text = "".join(block.text for block in response.content if hasattr(block, "text"))
    return _extract_json_object(text)


def _run_anthropic_answer_writer(question: str, analysis: dict) -> str:
    client = _get_anthropic_client()
    response = client.messages.create(
        model="claude-opus-4-7",
        max_tokens=1200,
        system=ANSWER_WRITER_SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": _build_answer_writer_prompt(question, analysis),
        }],
    )
    return "".join(block.text for block in response.content if hasattr(block, "text")).strip()


def _answer_anthropic(message: str, history: list[dict]) -> dict:
    client = _get_anthropic_client()
    resolved, preloaded = _prepare_resolved_context(message, history)
    request_system_prompt = _build_request_system_prompt(resolved, preloaded)
    messages = [{"role": h["role"], "content": h["content"]} for h in history]
    messages.append({"role": "user", "content": message})
    executed_evidence = []

    for _ in range(MAX_TOOL_ROUNDS):
        response = client.messages.create(
            model="claude-opus-4-7",
            max_tokens=4096,
            system=request_system_prompt,
            tools=TOOL_DEFINITIONS,
            messages=messages,
        )

        if response.stop_reason == "end_turn":
            for block in response.content:
                if hasattr(block, "text"):
                    return {
                        "response": block.text,
                        "widgets": _merge_widgets(
                            _widgets_from_preloaded(preloaded),
                            _widgets_from_analysis_evidence({}, executed_evidence),
                        ),
                    }
            raise ValueError("Claude returned end_turn but no text content block")

        if response.stop_reason == "tool_use":
            tool_results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                try:
                    logger.info("Anthropic tool call: %s args=%s", block.name, block.input)
                    result = execute_tool(block.name, block.input)
                    executed_evidence.append({
                        "tool": block.name,
                        "args": block.input,
                        "result": result,
                    })
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(result, default=str),
                    })
                except Exception as exc:
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": str(exc),
                        "is_error": True,
                    })
            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": tool_results})

        else:
            raise ValueError(f"Unexpected stop_reason from Claude: {response.stop_reason!r}")

    raise ValueError(f"Exceeded {MAX_TOOL_ROUNDS} tool-call rounds without a final answer.")


# ── OpenAI ───────────────────────────────────────────────────────────────────

_openai_client: Any | None = None

def _get_openai_client() -> Any:
    global _openai_client
    if openai_sdk is None:
        raise ImportError("openai package is not installed")
    if _openai_client is None:
        _openai_client = openai_sdk.OpenAI(
            api_key=os.environ.get("OPENAI_API_KEY")
        )
    return _openai_client


def _run_openai_analysis(question: str, resolved: dict, plan: dict, evidence: list[dict]) -> dict:
    client = _get_openai_client()
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": ANALYSIS_SYSTEM_PROMPT},
            {"role": "user", "content": _build_analysis_user_prompt(question, resolved, plan, evidence)},
        ],
        response_format={"type": "json_object"},
    )
    return _extract_json_object(response.choices[0].message.content)


def _run_openai_answer_writer(question: str, analysis: dict) -> str:
    client = _get_openai_client()
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": ANSWER_WRITER_SYSTEM_PROMPT},
            {"role": "user", "content": _build_answer_writer_prompt(question, analysis)},
        ],
    )
    return response.choices[0].message.content.strip()


def _answer_openai(message: str, history: list[dict]) -> dict:
    client = _get_openai_client()
    resolved, preloaded = _prepare_resolved_context(message, history)
    request_system_prompt = _build_request_system_prompt(resolved, preloaded)
    messages = [{"role": "system", "content": request_system_prompt}]
    messages += [{"role": h["role"], "content": h["content"]} for h in history]
    messages.append({"role": "user", "content": message})
    executed_evidence = []

    for _ in range(MAX_TOOL_ROUNDS):
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=messages,
            tools=OPENAI_TOOL_DEFINITIONS,
            tool_choice="auto",
        )

        choice = response.choices[0]

        if choice.finish_reason == "stop":
            return {
                "response": choice.message.content,
                "widgets": _merge_widgets(
                    _widgets_from_preloaded(preloaded),
                    _widgets_from_analysis_evidence({}, executed_evidence),
                ),
            }

        if choice.finish_reason == "tool_calls":
            # Append the assistant turn (contains the tool_calls)
            messages.append(choice.message)

            # Execute each tool call and append results
            for tool_call in choice.message.tool_calls:
                try:
                    args = json.loads(tool_call.function.arguments)
                    logger.info("OpenAI tool call: %s args=%s", tool_call.function.name, args)
                    result = execute_tool(tool_call.function.name, args)
                    executed_evidence.append({
                        "tool": tool_call.function.name,
                        "args": args,
                        "result": result,
                    })
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(result, default=str),
                    })
                except Exception as exc:
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": f"Error: {exc}",
                    })

        else:
            raise ValueError(f"Unexpected finish_reason from OpenAI: {choice.finish_reason!r}")

    raise ValueError(f"Exceeded {MAX_TOOL_ROUNDS} tool-call rounds without a final answer.")


# ── Public interface ─────────────────────────────────────────────────────────

def answer_f1_payload(message: str, history: list[dict] | None = None) -> dict:
    """
    Answer an F1 question using the configured LLM provider.

    history: list of prior {role, content} dicts from the conversation.
    Reads LLM_PROVIDER from the environment (default: 'anthropic').
    """
    prior = history or []
    provider = os.environ.get("LLM_PROVIDER", "anthropic").lower()
    deterministic = _try_deterministic_analysis(message, prior, provider=provider)
    if deterministic:
        return deterministic
    if provider == "openai":
        return _answer_openai(message, prior)
    return _answer_anthropic(message, prior)


def answer_f1_question(message: str, history: list[dict] | None = None) -> str:
    return answer_f1_payload(message, history)["response"]
