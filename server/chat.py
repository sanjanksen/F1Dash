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
from concurrent.futures import ThreadPoolExecutor
from typing import Any
import anthropic
try:
    import openai as openai_sdk
except ImportError:
    openai_sdk = None
try:
    import openai
except ImportError:
    openai = None
from tools import TOOL_DEFINITIONS, OPENAI_TOOL_DEFINITIONS, execute_tool
from resolver import resolve_query_context, resolve_context_from_history, _cached_drivers
from driver_styles import get_comparison_framing
from circuit_profiles import get_circuit_profile
from energy_2026 import get_energy_2026_knowledge
from evidence_shaping import (
    CORNERING_TOOL_NAMES,
    reject_data_table_for_cornering,
    strip_heavy_payload_fields,
)

MAX_TOOL_ROUNDS = 8
MAX_DETERMINISTIC_TOOL_WORKERS = 4
logger = logging.getLogger(__name__)


class LLMTransientError(RuntimeError):
    """Raised when a model-provider call should be surfaced as 'retry later'."""

    def __init__(self, message: str, *, provider: str, kind: str):
        super().__init__(message)
        self.provider = provider
        self.kind = kind  # "rate_limit" | "connection" | "api"


def _call_anthropic(client, **kwargs):
    try:
        return client.messages.create(**kwargs)
    except anthropic.RateLimitError as e:
        logger.warning("Anthropic rate-limited: %s", type(e).__name__)
        raise LLMTransientError("Anthropic rate-limited", provider="anthropic", kind="rate_limit") from e
    except anthropic.APIConnectionError as e:
        logger.warning("Anthropic connection error: %s", type(e).__name__)
        raise LLMTransientError("Anthropic connection error", provider="anthropic", kind="connection") from e
    except anthropic.APIError as e:
        logger.error("Anthropic API error: %s", type(e).__name__, exc_info=True)
        raise LLMTransientError("Anthropic API error", provider="anthropic", kind="api") from e


def _call_openai(client, **kwargs):
    if openai is None:
        return client.chat.completions.create(**kwargs)
    try:
        return client.chat.completions.create(**kwargs)
    except openai.RateLimitError as e:
        logger.warning("OpenAI rate-limited: %s", type(e).__name__)
        raise LLMTransientError("OpenAI rate-limited", provider="openai", kind="rate_limit") from e
    except openai.APIConnectionError as e:
        logger.warning("OpenAI connection error: %s", type(e).__name__)
        raise LLMTransientError("OpenAI connection error", provider="openai", kind="connection") from e
    except openai.APIError as e:
        logger.error("OpenAI API error: %s", type(e).__name__, exc_info=True)
        raise LLMTransientError("OpenAI API error", provider="openai", kind="api") from e

import datetime

CURRENT_YEAR = datetime.date.today().year


def _make_qualifying_battle_widget(result: dict) -> dict:
    energy_analysis = result.get("energy_analysis") or {}
    clipping_callout = energy_analysis.get("clipping_comparison")
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
        "grip_commitment": result.get("grip_commitment"),
        "clipping_callout": clipping_callout,
    }


def _make_grip_commitment_summary(result: dict) -> dict | None:
    summary = result.get("summary") or {}
    driver_a = result.get("driver_a")
    driver_b = result.get("driver_b")
    a = summary.get(driver_a) if driver_a else None
    b = summary.get(driver_b) if driver_b else None
    if not driver_a or not driver_b or not isinstance(a, dict) or not isinstance(b, dict):
        return None

    def _num(row: dict, key: str):
        v = row.get(key)
        return v if isinstance(v, (int, float)) else None

    def _edge(a_val, b_val, higher_is_better=True):
        if a_val is None or b_val is None:
            return None
        if higher_is_better:
            return driver_a if a_val >= b_val else driver_b
        return driver_a if a_val <= b_val else driver_b

    ggv_a   = _num(a, "avg_ggv_util_pct")
    ggv_b   = _num(b, "avg_ggv_util_pct")
    et_a    = _num(a, "avg_envelope_time_pct")
    et_b    = _num(b, "avg_envelope_time_pct")
    ta_a    = _num(a, "avg_throttle_acceptance_pct")
    ta_b    = _num(b, "avg_throttle_acceptance_pct")
    eb_a    = _num(a, "avg_entry_bravery_pct")
    eb_b    = _num(b, "avg_entry_bravery_pct")
    tb_a    = _num(a, "avg_trail_brake_pct")
    tb_b    = _num(b, "avg_trail_brake_pct")
    var_a   = _num(a, "avg_load_variance")
    var_b   = _num(b, "avg_load_variance")
    corr_a  = _num(a, "avg_corrections_per_corner")
    corr_b  = _num(b, "avg_corrections_per_corner")

    more_committed_driver = _edge(ggv_a, ggv_b, higher_is_better=True)
    cleaner_driver        = _edge(var_a, var_b, higher_is_better=False)

    # Plain-English summary
    parts = []
    if ggv_a is not None and ggv_b is not None:
        hi_d = more_committed_driver
        lo_d = driver_b if hi_d == driver_a else driver_a
        hi_v, lo_v = (ggv_a, ggv_b) if hi_d == driver_a else (ggv_b, ggv_a)
        if abs(ggv_a - ggv_b) >= 1.0:
            parts.append(
                f"{hi_d} used more of what the car can actually do — {hi_v:.0f}% of the car's demonstrated "
                f"grip ceiling vs {lo_v:.0f}% for {lo_d}."
            )
        else:
            parts.append(
                f"Both drivers used a similar fraction of the car's grip ceiling ({hi_v:.0f}% vs {lo_v:.0f}%)."
            )
    if ta_a is not None and ta_b is not None and abs(ta_a - ta_b) >= 3.0:
        hi_d = driver_a if ta_a >= ta_b else driver_b
        lo_d = driver_b if hi_d == driver_a else driver_a
        hi_v, lo_v = (ta_a, ta_b) if hi_d == driver_a else (ta_b, ta_a)
        parts.append(
            f"{hi_d} was more committed at exits — full power in {hi_v:.0f}% of corner exits while the car "
            f"was still turning ({lo_v:.0f}% for {lo_d}), asking the rear to drive forward and corner simultaneously."
        )
    if var_a is not None and var_b is not None and abs(var_a - var_b) >= 0.005:
        clean_d = cleaner_driver
        rough_d = driver_b if clean_d == driver_a else driver_a
        clean_v = var_a if clean_d == driver_a else var_b
        rough_v = var_b if clean_d == driver_a else var_a
        parts.append(
            f"Technique-wise, {clean_d}'s lateral load was steadier through the corners "
            f"({clean_v:.3f} vs {rough_v:.3f} wobble) — a more committed, settled arc rather than "
            f"chasing the balance mid-corner."
        )
    if corr_a is not None and corr_b is not None and abs(corr_a - corr_b) >= 0.5:
        s_d = driver_a if corr_a <= corr_b else driver_b
        b_d = driver_b if s_d == driver_a else driver_a
        s_v = corr_a if s_d == driver_a else corr_b
        b_v = corr_b if s_d == driver_a else corr_a
        parts.append(
            f"{s_d} needed fewer steering adjustments per corner ({s_v:.1f} vs {b_v:.1f} for {b_d}) — "
            f"a cleaner arc through the apex."
        )
    confidence_read = " ".join(parts) if parts else None

    # Fixed data table rows — deterministic, two groups
    def _row(group, label, a_val, b_val, fmt, higher_is_better, edge_label_hi, edge_label_lo):
        ed = _edge(a_val, b_val, higher_is_better)
        if ed is None:
            return None
        return {
            "group": group,
            "label": label,
            "a": a_val,
            "b": b_val,
            "format": fmt,
            "edge": ed,
            "edge_label": edge_label_hi if ed == (driver_a if higher_is_better == (a_val >= (b_val or 0)) else driver_b) else edge_label_lo,
        }

    def _row2(group, label, a_val, b_val, fmt, higher_is_better, edge_label):
        ed = _edge(a_val, b_val, higher_is_better)
        if ed is None:
            return None
        return {"group": group, "label": label, "a": a_val, "b": b_val,
                "format": fmt, "edge": ed, "edge_label": edge_label}

    data_rows = [r for r in [
        _row2("commitment", "% of car's limit",             ggv_a,  ggv_b,  "pct",   True,  "more committed"),
        _row2("commitment", "sustained at the limit",        et_a,   et_b,   "pct",   True,  "more sustained"),
        _row2("commitment", "exits: power while cornering",  ta_a,   ta_b,   "pct",   True,  "more aggressive"),
        _row2("commitment", "entries: braking deep",         eb_a,   eb_b,   "pct",   True,  "deeper"),
        _row2("commitment", "trailing the brake",            tb_a,   tb_b,   "pct",   True,  "carries it deeper"),
        _row2("technique",  "load wobble",                   var_a,  var_b,  "raw3",  False, "cleaner arc"),
        _row2("technique",  "corrections per corner",        corr_a, corr_b, "count", False, "smoother"),
    ] if r is not None]

    return {
        "driver_a": driver_a,
        "driver_b": driver_b,
        "more_committed_driver": more_committed_driver,
        "cleaner_driver": cleaner_driver,
        "confidence_read": confidence_read,
        "data_rows": data_rows,
        "narrative": result.get("narrative"),
        "caveat": result.get("caveat"),
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
        "tyre_management_a": result.get("tyre_management_a"),
        "tyre_management_b": result.get("tyre_management_b"),
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


def _make_circuit_profile_widget(result: dict, track_map: dict | None = None) -> dict:
    widget = {
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
    if track_map:
        widget["track_map"] = track_map
    return widget


def _make_pit_stop_strategy_widget(result: dict) -> dict:
    return {
        "type": "pit_stop_strategy",
        "title": f"{result.get('event')} strategy",
        "event": result.get("event"),
        "session": result.get("session"),
        "total_laps": result.get("total_laps"),
        "drivers": result.get("drivers") or [],
    }


def _make_deg_trend_chart_widget(result: dict) -> dict:
    return {
        "type": "deg_trend_chart",
        "title": f"{result.get('driver')} — {result.get('event')} tyre degradation",
        "driver": result.get("driver"),
        "event": result.get("event"),
        "stints": [
            {
                "compound": s.get("compound"),
                "lap_count": s.get("lap_count"),
                "deg_rate_s_per_lap": s.get("deg_rate_s_per_lap"),
                "r_squared": s.get("r_squared"),
                "scatter_data": s.get("scatter_data") or [],
                "regression_line": s.get("regression_line") or [],
                "cliff_detected": s.get("cliff_detected", False),
                "cliff_tyre_age": s.get("cliff_tyre_age"),
                "cliff_slope_increase_s_per_lap": s.get("cliff_slope_increase_s_per_lap"),
                "cliff_severity_ratio": s.get("cliff_severity_ratio"),
                "pre_cliff_deg_rate_s_per_lap": s.get("pre_cliff_deg_rate_s_per_lap"),
                "post_cliff_deg_rate_s_per_lap": s.get("post_cliff_deg_rate_s_per_lap"),
                "pre_cliff_regression_line": s.get("pre_cliff_regression_line") or [],
                "post_cliff_regression_line": s.get("post_cliff_regression_line") or [],
                "cliff_confidence": s.get("cliff_confidence"),
            }
            for s in (result.get("stints") or [])
            if s.get("scatter_data") or s.get("regression_line")
        ],
    }


def _make_energy_management_widget(result: dict) -> dict:
    drivers = result.get("drivers") or []
    driver_a = drivers[0].get("driver") if drivers else None
    driver_b = drivers[1].get("driver") if len(drivers) > 1 else None
    label = driver_a or "Energy"
    if driver_b:
        label = f"{driver_a} vs {driver_b}"
    return {
        "type": "energy_management",
        "title": f"{label} — {result.get('event')} energy management",
        "driver_a": driver_a,
        "driver_b": driver_b,
        "event": result.get("event"),
        "session": result.get("session"),
        "drivers": drivers,
        "speed_trace_a": result.get("speed_trace_a") or [],
        "speed_trace_b": result.get("speed_trace_b"),
        "energy_metrics_a": result.get("energy_metrics_a") or {},
        "energy_metrics_b": result.get("energy_metrics_b"),
        "straight_breakdown": result.get("straight_breakdown") or [],
        "confidence": result.get("confidence"),
        "inference_summary": result.get("inference_summary") or [],
        "clipping_segments_a": (result.get("clipping_signature_a") or {}).get("segments") or [],
        "clipping_segments_b": (result.get("clipping_signature_b") or {}).get("segments") or [],
        "total_clipping_seconds_a": (result.get("clipping_signature_a") or {}).get("total_clipping_seconds"),
        "total_clipping_seconds_b": (result.get("clipping_signature_b") or {}).get("total_clipping_seconds"),
        "clipping_budget_status_a": (result.get("clipping_signature_a") or {}).get("budget_status"),
        "clipping_budget_status_b": (result.get("clipping_signature_b") or {}).get("budget_status"),
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

    track_map_result = None
    grip_commitment = None
    for item in evidence:
        if "result" not in item:
            continue
        if item.get("tool") == "get_circuit_track_map":
            track_map_result = item["result"]
        elif item.get("tool") == "analyze_cornering_loads":
            grip_commitment = _make_grip_commitment_summary(item["result"])
        if track_map_result is not None and grip_commitment is not None:
            break

    for item in evidence:
        if "result" not in item:
            continue
        tool = item.get("tool")
        if tool == "analyze_qualifying_battle":
            result = dict(item["result"])
            if grip_commitment:
                result["grip_commitment"] = grip_commitment
            widgets.append(_make_qualifying_battle_widget(result))
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
            if plan.get("analysis_mode") == "circuit_profile" and plan.get("emit_context_widget") is False:
                continue
            widgets.append(_make_circuit_profile_widget(item["result"], track_map=track_map_result))
        elif tool == "get_pit_stop_analysis":
            widgets.append(_make_pit_stop_strategy_widget(item["result"]))
        elif tool == "analyze_stint_degradation":
            w = _make_deg_trend_chart_widget(item["result"])
            if w.get("stints"):
                widgets.append(w)
        elif tool == "analyze_energy_management":
            w = _make_energy_management_widget(item["result"])
            if w.get("speed_trace_a"):
                widgets.append(w)

    # Standalone corner_analysis widget: when cornering loads were run but there's no
    # qualifying_battle widget to embed grip_commitment into (pure grip comparison query).
    if grip_commitment and not has_primary_qualifying_widget:
        cornering_result = _find_evidence_result(evidence, "analyze_cornering_loads") or \
                           _find_evidence_result(evidence, "analyze_race_cornering_profile")
        widgets.insert(0, {
            "type": "corner_analysis",
            "driver_a": grip_commitment["driver_a"],
            "driver_b": grip_commitment["driver_b"],
            "event": cornering_result.get("event") if cornering_result else None,
            "session": cornering_result.get("session") if cornering_result else None,
            "grip": grip_commitment,
        })

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


def _sanitize_data_table_widget(widget: dict) -> dict | None:
    if not isinstance(widget, dict) or widget.get("type") != "data_table":
        return None

    raw_rows = widget.get("rows")
    if not isinstance(raw_rows, list) or not raw_rows:
        return None

    raw_columns = widget.get("columns")
    if not isinstance(raw_columns, list) or not raw_columns:
        keys = []
        for row in raw_rows:
            if isinstance(row, dict):
                for key in row.keys():
                    if key not in keys:
                        keys.append(key)
        raw_columns = [{"key": key, "label": str(key).replace("_", " ").title()} for key in keys]

    columns = []
    for column in raw_columns[:8]:
        if not isinstance(column, dict):
            continue
        key = str(column.get("key", "")).strip()
        label = str(column.get("label") or key).strip()
        if not key or not label:
            continue
        align = str(column.get("align", "left")).strip().lower()
        columns.append({
            "key": key[:40],
            "label": label[:48],
            "align": align if align in ("left", "right", "center") else "left",
        })

    if not columns:
        return None

    rows = []
    for raw_row in raw_rows[:20]:
        if not isinstance(raw_row, dict):
            continue
        row = {}
        for column in columns:
            value = raw_row.get(column["key"], "")
            if isinstance(value, (str, int, float, bool)) or value is None:
                row[column["key"]] = "" if value is None else str(value)[:160]
            else:
                row[column["key"]] = json.dumps(value, default=str)[:160]
        rows.append(row)

    if not rows:
        return None

    return {
        "type": "data_table",
        "title": str(widget.get("title") or "Table").strip()[:80],
        "subtitle": str(widget.get("subtitle") or "").strip()[:140],
        "columns": columns,
        "rows": rows,
        "note": str(widget.get("note") or "").strip()[:180],
    }


def _extract_inline_widgets(text: str | None) -> tuple[str, list[dict]]:
    if not text:
        return "", []

    widgets = []

    def add_widgets(raw_json: str) -> None:
        try:
            parsed = json.loads(raw_json)
        except json.JSONDecodeError:
            return
        candidates = parsed if isinstance(parsed, list) else [parsed]
        for candidate in candidates:
            table = _sanitize_data_table_widget(candidate)
            if table:
                widgets.append(table)

    def replace_widget(match: re.Match) -> str:
        add_widgets(match.group("json"))
        return ""

    cleaned = re.sub(
        r"```(?:f1-widget|widget|json-widget)\s*(?P<json>\{.*?\}|\[.*?\])\s*```",
        replace_widget,
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    cleaned = re.sub(
        r"<f1-widget>\s*(?P<json>\{.*?\}|\[.*?\])\s*</f1-widget>",
        replace_widget,
        cleaned,
        flags=re.IGNORECASE | re.DOTALL,
    )
    return cleaned.strip(), widgets


def _payload_with_inline_widgets(
    response: str | None,
    base_widgets: list[dict] | None = None,
    *,
    executed_evidence: list[dict] | None = None,
) -> dict:
    clean_response, inline_widgets = _extract_inline_widgets(response)
    if executed_evidence and any(
        item.get("tool") in CORNERING_TOOL_NAMES for item in executed_evidence
    ):
        inline_widgets = [
            w for w in inline_widgets
            if not reject_data_table_for_cornering(w.get("type"), _infer_widget_source_tool(w, executed_evidence))
        ]
    return {
        "response": clean_response,
        "widgets": _merge_widgets(base_widgets or [], inline_widgets),
    }


def _infer_widget_source_tool(widget: dict, executed_evidence: list[dict]) -> str | None:
    """Heuristic: if a cornering tool ran this turn, assume data_table widgets came from it.

    The LLM emits data_table widgets inline via prose; no explicit tool linkage exists.
    When cornering evidence is present we treat the data_table as cornering-sourced so
    it gets suppressed per system policy.
    """
    if widget.get("type") != "data_table":
        return None
    for item in executed_evidence:
        if item.get("tool") in CORNERING_TOOL_NAMES:
            return item.get("tool")
    return None


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
- For stint/tyre strategy, pit timing, or undercut/overcut questions: use get_driver_strategy (call without driver_code to get the full field strategy grid — essential for undercut/overcut reasoning since you need to see when BOTH drivers pitted, not just one)
- For qualifying storylines like who improved through Q1/Q2/Q3: use get_qualifying_progression
- For trustworthy pace rankings, especially when traffic, deleted laps, or yellows matter: use get_clean_pace_summary
- For sector-by-sector pace: use get_sector_comparison
- For causal qualifying battle questions like "why was Leclerc faster than Norris in quali?" use analyze_qualifying_battle
- For lap-by-lap pace: use get_driver_lap_times
- For corner-level analysis (braking points, gear shifts, throttle application): use get_lap_telemetry or get_telemetry_comparison. These include gear, RPM, throttle, and brake at every 100m — use them to make specific claims like "Norris was still in 4th gear at 1400m while Leclerc had already dropped to 3rd, braking 20m earlier"
- For structured corner profiles (entry/apex/exit speeds, braking point, gear at apex, traction point, straight acceleration, DRS, clipping) for a single driver: use extract_corner_profiles
- For comparing two drivers corner-by-corner (where the faster driver gains, cause classification, setup direction, avg straight speeds): use compare_corner_profiles
- For a team's setup direction or which teammate is stronger through the corners: use analyze_team_performance
- For historical team/car-circuit fit questions like "what kind of tracks suit Mercedes?", "is McLaren better on high-speed circuits?", or "does Ferrari suit late braking tracks?": use analyze_team_circuit_fit. If a specific round/session is known, also use analyze_team_telemetry_traits. Use get_team_car_profile only as dated public-reporting context, not as proof.
- For tyre degradation rate, stint deg model, or how a driver's pace degraded per lap on a compound: use analyze_stint_degradation
- For race pace comparison between two drivers (fuel-corrected pace delta, degradation rates, undercut analysis, decisive factor): use analyze_race_pace_battle. Prefer this over manual lap time inspection for 'why did X pull away from Y in the race?' questions
- For 2026-style energy questions like lift-and-coast, clipping, super-clipping, deployment taper, or energy recovery behavior: use analyze_energy_management
- For racing-line or on-track position comparisons, track maps, or where a gain happened physically on the lap: use get_track_position_comparison
- For team radio or in-car context, use get_team_radio
- For live-style gap-to-leader / interval questions in a race, use get_intervals
- For cleaner position change timelines in a session, use get_live_position_timeline
- For richer circuit-map context like marshal sectors/lights or rotation for track-map overlays: use get_circuit_details or get_circuit_corners
- For safety car / VSC questions, strategy impact, who got screwed by the SC: use get_safety_car_periods — this returns full strategic_crossings data identifying exactly who was advantaged and disadvantaged by each neutralisation, plus pre-computed all_victims and all_beneficiaries lists and period_narrative for each period
- When doing a race recap (get_driver_race_story, get_race_report), the result already includes field_strategy (all drivers' stints) and safety_car_full (SC periods with strategic_crossings). Use these to proactively surface undercut/overcut narrative and SC strategy impact even if the user didn't specifically ask about strategy — it is part of the race story
- For ANY free practice question (who was fastest, what programmes did drivers run, what was the race pace, FP1/FP2/FP3 recap): use get_fp_summary with fp_number=1/2/3. The result classifies every stint as long_run/quali_sim/short_run/installation. Long runs (8+ laps) approximate race pace; quali_sim (1-2 fresh soft laps) approximate single-lap pace. Always embed the fuel-load caveat: FP lap times cannot be directly compared to race or qualifying times.
- For top speed, speed trap, straight-line speed, or drag questions (any session): use get_speed_trap_leaderboard. It returns four ranked lists (speed_st, speed_fl, speed_i1, speed_i2) scanning ALL laps to find each driver's peak at each trap independently. A driver's peak ST speed may be on a different lap than their peak FL speed.
- For sprint race questions ('how did X do in the sprint?', 'recap the sprint race'): use get_driver_race_story or get_race_report with session_type='S'. Do NOT call these with the default session_type for sprint questions.
- For sprint qualifying/shootout questions ('who was fastest in sprint qualifying?', 'sprint shootout recap'): use get_sprint_qualifying_results for raw classification. For causal 'why was X faster than Y in sprint qualifying?' questions, use analyze_qualifying_battle with session_type='SQ'.
- For a driver's sprint weekend story: use get_driver_race_story with session_type='S'
- For a team's sprint result: use get_team_weekend_overview with session_type='S'
- Sprint weekends contain: FP1 (practice), Sprint Qualifying/Shootout (SQ), Sprint Race (S), Qualifying (Q), Race (R). Sprint and sprint qualifying are separate sessions from the main qualifying and race.
- Sprint races are ~17-24 laps with no mandatory pit stops. Tyre degradation and strategy reasoning is less relevant for sprint; focus on pace, position battles, and safety car impact.
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
- When ranking, comparing many entities, or presenting 3+ rows of structured data, do not use a Markdown table. Add a hidden data table widget at the end of your answer using a fenced `f1-widget` JSON block. The JSON shape is: {{"type":"data_table","title":"Short title","subtitle":"Optional scope","columns":[{{"key":"rank","label":"Rank","align":"right"}},{{"key":"driver","label":"Driver"}}],"rows":[{{"rank":"1","driver":"PIA"}}],"note":"Optional caveat"}}. Keep the prose short and let the widget carry the rows.
- Cornering data has its own dedicated widget; data_tables sourced from cornering tools are suppressed in code, so write prose only.
- If you cannot determine which specific race or round the question refers to, ask ONE short clarifying question before calling any data tools. Do not guess a round number and do not call tools with a missing or uncertain race context.
- If a tool result contains `"available": false` and a `guidance_for_model` field, follow that guidance verbatim. Never paper over the gap with invented characteristics."""

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
- If a tool result contains `"available": false` and a `guidance_for_model` field, follow that guidance verbatim. Never paper over the gap with invented characteristics.
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

## Cornering Load & Corner Analysis Data
When evidence contains results from `analyze_cornering_loads` or `analyze_race_cornering_profile`, you are writing about driving CHARACTER — not metrics. Use the F1 vocabulary below. Every number must serve a character description, not the other way around.

There are two orthogonal dimensions: **Commitment** (how much of the car they're using) and **Technique** (how cleanly they're using it). A driver can be high commitment with messy technique (fast but burning the tyre), or smooth technique with low commitment (measured, preserving rubber). Name the pattern.

**Commitment metrics — how hard they're asking the car:**

- **avg_ggv_util_pct** → How much of the car's actual demonstrated grip ceiling the driver used — normalised against what this car on these tyres produced in this session. Not a formula. Directional (braking limit ≠ lateral limit ≠ throttle limit).
  High (>85%): *asking everything of the car*, *no headroom left*, *using the car's full capability*
  Medium (65–85%): *strong commitment, the car is working hard*, *well into the performance window*
  Low (<60%): *keeping something in reserve*, *the envelope isn't fully used*
  Say: "he was asking [X]% of what the car has shown it can produce."

- **avg_envelope_time_pct** → % of cornering time within 15% of the car's empirical combined limit. Higher = sustained near-limit operation, not just peaking at the apex.
  High (>55%): *living at the limit from entry to exit*, *barely eases off*, *the tyre is working hard through every phase*
  Low (<30%): *has a comfort margin through the middle*, *touches the limit briefly but doesn't hold it*

- **avg_throttle_acceptance_pct** → % of corner exits where the driver commits to full power while the car still has significant lateral load — asking the rear to generate drive force AND cornering force simultaneously.
  High (>40%): *power down early while the car's still loaded*, *on the throttle before the car is straight*, *trusting the rear to hook up under load*
  Low (<15%): *waits for the car to settle*, *throttle only once fully straight*
  Say: "he was on the power before the car was straight."

- **avg_entry_bravery_pct** → % of corner entries where the driver is simultaneously near the combined grip limit AND still on the brakes — deep braking into a loaded corner.
  High (>35%): *braking deep into a loaded corner*, *the brake pedal is a rotation tool at the very edge of grip*
  Low (<10%): *braking finished before the lateral load builds*, *clean measured entry*

- **avg_trail_brake_pct** → % of corner entry spent simultaneously cornering AND braking.
  High (>35%): *carrying the brake deep*, *using it to load the front and rotate*, *still on the pedal at turn-in*
  Low (<10%): *finishes braking before the corner*, *clean turn-in*

**Technique metrics — how cleanly they're executing:**

- **avg_load_variance** → Standard deviation of lateral G within each corner — how much the load wobbles. Low = smooth committed arc. High = oscillating load, the car moving around.
  High: *fighting the car* — *chasing oversteer*, *chasing understeer*, *the car's a handful*, *working the tyre harder than the lap requires*
  Low: *smooth arc*, *natural rotation*, *one committed input and holds it*, *the car does exactly what he asks*

- **avg_corrections_per_corner** → How many steering adjustments per corner — the driver reacting rather than committing.
  High: *chasing the balance mid-corner*, *having to react*, *a passenger for part of the corner*
  Low: *clean committed arc*, *one input and done*, *drives the car in rather than reacting to it*

**Inferences — name the pattern, not just the metric:**
- High ggv_util + low variance = *confident and clean* — extracting maximum grip efficiently, the ideal combination
- High ggv_util + high variance = *committed but fighting it* — pushing hard but the car is unsettled, burning the tyre
- Low ggv_util + low variance = *smooth and measured* — preserving the rubber, strong race pace but leaving qualifying time on the table
- Low ggv_util + high variance = *struggling* — fighting the car without compensating with commitment, the worst combination
- High corrections at high speed = rear stepping out under load, *snap oversteer*, driver managing a twitchy rear
- High corrections at low speed = *rotating problem*, front won't bite, car won't change direction cleanly
- High throttle_acceptance + low trail_brake = *exit-focused style* — the aggression is at the exit, not the entry
- High trail_brake + high entry_bravery = *entry-focused style* — the commitment is at the entry, loading the front with the brake
- High ggv_util + high envelope_time = *sustained commitment* — not just peaking at the apex, working the car hard throughout every phase

**Core vocabulary list:**
oversteer, understeer, snap oversteer, trailing the rear, the rear's loose, the front's not biting, pushing wide, washes wide, fighting the car, chasing the rear, chasing the balance, committed, on the limit, no margin, natural rotation, rotating the car, one clean arc, smooth progressive arc, the car does what he asks, leaning on the front, trusting the rubber, tyre confidence, living on the edge, pointed car, planted rear, front-end bite, carrying it in, pointy setup, the car's a handful, the rear gets snappy

**Rules:**
- Write about the DRIVER and their CHARACTER first. Numbers are proof of the character claim.
- Always name the commitment/technique pattern explicitly (e.g. "high commitment, clean technique" or "pushing hard but fighting the balance").
- Qualifying: higher commitment + cleaner technique = more single-lap time. Race: high commitment + high variance = *the confidence level drops as the stint ages — the tyre can't hold that demand indefinitely*.
- Never say metric names in the answer: "avg_load_variance", "avg_ggv_util_pct", "avg_envelope_time_pct", "avg_throttle_acceptance_pct", "avg_entry_bravery_pct", "avg_trail_brake_pct", "avg_corrections_per_corner". Translate to character vocabulary.
- **This ban also covers data_table column headers.** Use plain English: "% of car's limit", "exits: power while cornering (%)", "entries: braking deep (%)", "load wobble", "corrections per corner". Never use internal metric names as column headers.
- **Technique (load wobble / arc quality) is MANDATORY.** If `avg_load_variance` is present in the summary, you MUST describe it — which driver had a smoother arc, what that means physically (oscillating G trace = fighting the car; steady trace = one clean committed arc). Covering only commitment without technique is an incomplete answer.
- **Never cite the same metric at two different granularities.** The summary contains aggregate averages — use those. Do not invent or quote per-corner breakdowns for individual turns. One number per metric per driver.
- **Use the pre-built `narrative` field as your factual foundation.** It already contains the key characterization sentences. Expand on it with driving vocabulary — do not re-derive corner-spread counts or invent per-corner statistics from raw data.

## Race Strategy Reasoning

When `field_strategy` is present in the evidence (a list of all drivers' stint sequences sorted by finish position), use it to reason about undercuts, overcuts, and SC impact. Each entry has: driver code, finish_position, grid_position, pit_stop_count, and a `stints` array where each stint has compound, start_lap, end_lap, laps, tyre_life_start. The pit lap between stint N and stint N+1 is: stint[N].end_lap (the lap the driver pitted on).

**Identifying undercuts:**
An undercut = Driver A (behind B on track) pits earlier to gain on fresh-tyre out-lap before B stops.
- Look for: subject driver or nearby rival has a shorter first/second stint than the other — their subsequent stint starts several laps earlier.
- Undercut succeeded: the earlier-stopping driver's position_start of the next stint is better (lower number) than expected given their original gap.
- Undercut failed: the later-stopper still came out ahead, meaning their gap was large enough to absorb the pit-stop hit.
- Key threshold: undercuts are typically attempted when the on-track gap is under ~2s. A gap over ~4s usually means a rival can't undercut without very significant tyre pace delta.

**Identifying overcuts attempts:**
An overcut = Driver A stays out while B pits, banking track position while B takes the pit stop time loss.
- Look for: subject driver pits significantly LATER (5+ laps) than a rival who was just behind them.
- Overcut succeeded: A came out ahead of B after B's pit, despite being slower on older rubber.
- Overcut failed: B's fresh tyres were faster and B caught/passed A before A pitted, or B came out ahead after A finally stopped.

**When to surface strategy narrative unprompted:**
If the user asks a broad recap question ("how did X's race go?", "what happened in the race?") and the field_strategy shows meaningful pit timing differences between the subject and cars within 3 positions of them, proactively include undercut/overcut analysis. This is core race narrative, not a side detail.

**Safety car strategy analysis:**
The `safety_car_full.periods[N]` contains:
- `pitted_just_before`: drivers who pitted in the final ~90s before SC — paid full pit cost then SC erased the field gap they were building.
- `pitted_before_extended`: pitted 1.5–5 laps before SC — paid full cost, but rivals who pitted during SC got a free stop, neutralizing the fresh-tyre advantage the early stopper was building.
- `pitted_during`: got a near-free stop — pit cost is minimal because the field was already bunching up.
- `strategic_crossings`: explicit pairs of (driver_disadvantaged, driver_advantaged) with a plain-language `note` explaining the mechanism.

The subject driver's personal impact is in `safety_car_impact`. The field-wide picture is in `safety_car_full`. Use both:
- If subject is in `pitted_just_before` for any period: they were unlucky — explain that the SC erased their fresh-tyre advantage.
- If subject is in `pitted_during`: they got a free stop — explain this was a major strategic gain.
- If subject is in a `strategic_crossings.driver_disadvantaged` entry: explicitly name who benefited at their expense.

**Free pit stop economics:**
Full SC: pit stop cost drops from ~22s to ~3–5s in competitive terms (everyone slows). Nearly free.
VSC: cost drops from ~22s to ~8–12s. Meaningful saving, not completely free.
Red flag: pit stop is completely free — cars return to pit lane, everyone can change tyres.

**Covering the undercut:**
If B (ahead) pits 1–3 laps after A (behind) pitted, B likely reacted to cover. Reactive stops are driven by team radio. Look for same-lap or 1-lap-later pits between rivals.

**Double stacking:**
If two teammates (same team) pit within 1–2 consecutive laps, the second car loses ~5–8 extra seconds waiting for the crew to reset. Find this by checking `field_strategy` for same-team drivers with identical or consecutive pit laps.

**Only use strategy language when the data clearly shows it.** Do not claim "undercut" unless the pit lap delta is visible in field_strategy. Do not claim "free stop" unless the pit lap falls within the SC/VSC window in safety_car_full.

## Free Practice Interpretation

`get_fp_summary` returns per-driver stints classified into four types. Read them as follows:

**Stint classifications:**
- `long_run` (8+ consecutive laps, same compound): race-pace simulation. These laps are run on heavier fuel than the race — subtract 0.3–0.5 s/lap mentally to estimate race pace. Avg lap time is more meaningful than best lap for these stints.
- `quali_sim` (1–2 laps, fresh soft/medium, driver's fastest laps): single-lap pace representation. Best lap here is the closest proxy to qualifying pace.
- `short_run` (3–7 laps): setup/balance work, tyre assessment. Times are not representative of either race pace or single-lap pace.
- `installation` (first pit-out lap): warm-up lap, ignore for pace comparisons entirely.

**What you can and cannot conclude:**
- CAN compare long_run avg_lap_s between drivers as race-pace proxy — flag fuel load caveat.
- CAN use quali_sim best_lap_s as single-lap pace proxy — flag that it's not a direct qualifying comparison.
- CANNOT directly compare FP times to qualifying or race times without caveats.
- CANNOT infer tyre wear from FP data — FastF1 does not expose fuel load.
- If a driver has zero quali_sim stints, they did not run a representative push lap.
- `long_run_count` and `quali_sim_count` tell you the programme: high long_run = race focus, high quali_sim = single-lap focus.

**Always embed the session_notes** caveats naturally in your analysis — never skip the fuel-load and programme-type disclaimers.

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
- Only say "cliff", "fell off a cliff", or "fell out of the optimal window" when `cliff_detected` is true. If it is false, describe the stint as linear degradation, noisy degradation, or normal drop-off. If the cliff flag is true, use F1 language: "it looks like the tyre fell out of the optimal window around age 13" or "after age 13 the tyre seems to have dropped out of its window and the degradation got much steeper." Do not claim graining, blistering, or thermal deg unless that cause is separately evidenced.
- When discussing a driver's stints or compounds, always follow chronological race order — first stint first, second stint second. Never reorder stints for narrative effect or to lead with the more impressive number.
- For tyre-management rankings, always show the actual deg rate if it is available. Rank primarily by lower positive deg rate, then use consistency as the noise check and R² as the trust check. Do not rank by R² alone. If raw pace trend is negative, explain that the car got faster on the stopwatch, but the fuel-corrected deg estimate adds back expected fuel burn to estimate tyre loss. Explain `±0.58s` as lap-to-lap spread around the trend, not time lost per lap.
- For team/car characterization, rank evidence in this order: current telemetry traits first, historical circuit-fit trends second, sourced public-reporting profiles third. Never turn any one layer into a definitive private setup claim.
- When the answer ranks drivers, teams, tyres, stints, circuits, or any list with 3+ comparable rows, do not write a Markdown table. Add a hidden `f1-widget` JSON block after the prose with `type: "data_table"`, `title`, optional `subtitle`, `columns`, `rows`, and optional `note`. Use concise strings only; the system will render the widget and remove the JSON from the visible answer.
- Cornering data has its own dedicated Commitment/Technique widget; data_tables sourced from cornering tools are suppressed in code, so write prose only.
- When cornering data is present, your prose MUST cover BOTH dimensions: (1) Commitment — how much of the car's grip ceiling was used, who was more aggressive at entries and exits; (2) Technique — who had the steadier G trace through the corners (load wobble), what that means physically (settled arc vs fighting the car mid-corner). Skipping either dimension is an incomplete answer.
- For tyre-management data_table widgets, the table shape is EXACTLY: one deg-rate column per compound used (e.g. "Medium /lap", "Hard /lap"), followed by ONE "Total lost (s)" column taken from `total_deg_loss_all_stints_s` — the total time lost to tyre wear across all stints combined. Example: `columns: ["Driver","Medium /lap","Hard /lap","Total lost (s)"]`. NEVER include finishing position, race position, "Fin", points, or any race-result field in a tyre-management table. The total-loss column must always be present.

## Circuit profile responses

When `analysis_mode` is `circuit_profile`, a visual widget is already showing the sector breakdown, energy profile, style verdict, and tyre challenge. Do NOT re-narrate those. The user can read them.

Write 2–3 sentences maximum:
1. One sentence on the circuit's overall feel/rhythm — what it actually demands from the car and driver.
2. One sentence on the most important strategic or competitive angle (which driver type wins here, what the key race factor is, what to watch).
3. Embed the caveat naturally ("that's the circuit character — how it actually plays out in 2026 depends on track evolution and compound choices").

Never walk through S1/S2/S3 individually. Never repeat the style verdict text. Never list the energy profile rows. The widget has all of that.

## Race strategy narrative

When the analysis includes strategy reasoning (undercut, overcut, SC free stop, covering, double stack), write it as an F1 person explaining what happened — not a data readout.

**Undercut succeeded:** "He pitted three laps before [rival] and made it count — on fresh rubber his out-lap was quick enough that when [rival] finally stopped, he came back out ahead. The undercut worked."

**Undercut failed:** "They tried the undercut, pitting early, but [rival] had enough of a buffer that the stop didn't flip the position. [Rival] came out ahead and that was that."

**Overcut succeeded:** "They left him out, gambling that staying on track while [rival] stopped would be enough. It was — when [rival] rejoined on fresh tyres, the gap [driver] had built was just enough. He pitted a few laps later and came out ahead."

**Overcut failed:** "They tried to overcut by staying out, but [rival's] fresh rubber was too quick and they caught up before [driver] even stopped."

**Free pit stop (SC):** "The Safety Car was perfect timing — they pitted under it for almost nothing. A stop that would normally cost them 20-odd seconds was basically free." Or the flip: "Brutal timing. They'd pitted [X laps] before the Safety Car came out — paid the full price while [rival] got that same stop almost for free."

**Strategic crossing (SC hurts early stopper):** "The VSC made things complicated. [Driver] had already pitted and was building a gap on fresh tyres when the field bunched up. [Rival] pitted under it and rejoined with similarly fresh rubber at almost no track-position cost — wiping out what [driver] had earned."

**Covering the undercut:** "When [rival] came in, the team responded immediately — [driver] was in the next lap to cover, making sure they didn't give up track position."

**Double stack:** "Ferrari stacked them — [teammate] went first, and [driver] sat in the garage for several extra seconds waiting for the crew to get set again."

**Key rules for strategy writing:**
- Never say `field_strategy`, `strategic_crossings`, `pitted_during_sc`, `pitted_just_before`, or any JSON key. Translate everything.
- Don't state raw lap numbers ("pitted on lap 23"). Write it relationally: "pitted three laps before [rival]", "came in under the Safety Car on lap 28."
- Don't define what an undercut or overcut IS. F1 fans know. Just say what happened.
- If the strategy was a major factor in the result, lead with it or make it the primary explanation — don't bury it at the end.
- If strategy reasoning wasn't directly asked about but is the real story of the race (e.g., an undercut changed the race outcome), include it in 1–2 sentences as part of the race narrative.
- No widget needed for strategy. Clear prose is the right format for this.

## Energy management responses

When `analyze_energy_management` results are present, a widget already shows the speed trace with annotated lift-and-coast and clipping zones, the efficiency metrics, and the per-straight breakdown. Do NOT re-describe zone positions or list straight-by-straight numbers — the widget has all of that.

Write 2–3 sentences:
1. Who has the better energy balance — fewer clips or more efficient harvesting — and what the estimated time cost shows.
2. What the straight breakdown reveals: whether one driver is losing time specifically on DRS straights vs shorter sections.
3. Embed the confidence caveat naturally ("this is inferred from speed/throttle patterns — ERS state isn't directly measured").

Never say "lift_and_coast_events" or "clipping_windows". Use natural language: "runs out of deployment on the main straight", "lifts early before the chicane to harvest", "costs him roughly X seconds across the lap".

## Free practice responses

When `get_fp_summary` results are present:
- Distinguish stint types out loud: "He ran a long race-simulation stint on the Hard" is clear. "His two-lap push on fresh Softs" signals a quali sim.
- Always embed the fuel-load caveat in a short phrase — never omit it: "on a heavier fuel load than race trim", "long runs in FP aren't directly comparable to race pace", "this is an FP time so fuel load matters."
- Use long-run avg_lap_s (not best_lap_s) for race-pace comparisons. Use quali_sim best_lap_s for single-lap pace comparisons. Never compare them against each other.
- If a driver has no quali_sim stints, say so directly: "he didn't run a representative push lap in this session."
- Never say `long_run`, `quali_sim`, `short_run`, or `installation` directly — translate to natural language. Never expose JSON field names.
- For ranking multiple drivers, use a data_table widget with columns: Driver, Team, Best lap (or Avg race pace), Compound, Programme notes.

## Speed trap responses

When `get_speed_trap_leaderboard` results are present:
- speed_st is the main straight trap — most representative of top speed.
- speed_fl, speed_i1, speed_i2 are secondary traps — useful context when the main straight result is anomalous (tow, DRS timing, traffic).
- Note when a driver's top speed came from a suspicious lap (e.g., early in the session before tyres were up to temperature, or on an out-lap).
- If a driver clearly had a tow or slipstream advantage, mention it as a caveat: "that 318 kph might have had help from a tow."
- Use a data_table widget for rankings with 3+ drivers: columns Driver, Team, Speed (kph), Trap, Lap.
- Never say `speed_st`, `speed_fl`, `speed_i1`, `speed_i2` directly — translate: "main straight trap", "finish line", "intermediate sector 1".
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
        return {
            "round_number": round_number,
            "driver_name": resolved["entity_name"],
            "session_type": resolved.get("session_type") or "R",
        }

    if tool == "get_team_weekend_overview":
        if not resolved.get("entity_name"):
            return None
        return {
            "round_number": round_number,
            "team_name": resolved["entity_name"],
            "session_type": resolved.get("session_type") or "R",
        }

    if tool == "get_race_report":
        return {
            "round_number": round_number,
            "session_type": resolved.get("session_type") or "R",
        }

    if tool == "get_sprint_qualifying_results":
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

    if tool == "get_pit_stop_analysis":
        return {"round_number": round_number}

    if tool == "analyze_weather_pace_correlation":
        session_type = resolved.get("session_type") or "Q"
        return {"round_number": round_number, "session_type": session_type}

    if tool == "get_fp_summary":
        fp_number = resolved.get("fp_number") or 1
        return {"round_number": round_number, "fp_number": fp_number}

    if tool == "get_speed_trap_leaderboard":
        session_type = resolved.get("session_type") or "Q"
        return {"round_number": round_number, "session_type": session_type}

    if tool == "analyze_stint_degradation":
        if not resolved.get("entity_code"):
            return None
        session_type = resolved.get("session_type") or "R"
        return {
            "round_number": round_number,
            "driver_code": resolved["entity_code"],
            "session_type": session_type,
        }

    if tool == "analyze_cornering_loads":
        codes = resolved.get("entity_codes") or []
        if len(codes) < 2:
            return None
        return {
            "round_number": round_number,
            "session_type": resolved.get("session_type") or "Q",
            "driver_a": codes[0],
            "driver_b": codes[1],
        }

    if tool == "analyze_race_cornering_profile":
        codes = resolved.get("entity_codes") or []
        if len(codes) < 2:
            return None
        return {
            "round_number": round_number,
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
    normalized_message = message.lower()

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
            tool_calls.append(("get_circuit_track_map", {"round_number": round_number}))
            tool_calls.append(("get_historical_circuit_performance", {"round_number": round_number}))
        return {
            "analysis_mode": "circuit_profile",
            "focus": "circuit",
            "question": message,
            "round_number": round_number,
            "event_name": event_name,
            "country": country,
            "emit_context_widget": (
                bool(resolved.get("has_explicit_context"))
                or any(term in normalized_message for term in ("widget", "map", "graphic", "profile", "circuit", "track", "show it", "bring it up"))
            ),
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
    if analysis_mode == "team_circuit_fit":
        team = resolved.get("entity_name")
        if not team:
            return None
        normalized_question = message.lower()
        session_type = "R" if (resolved.get("session_type") == "R" or "race" in normalized_question) else "Q"
        return {
            "analysis_mode": "team_circuit_fit",
            "focus": "team_fit",
            "question": message,
            "round_number": round_number,
            "team": team,
            "tool_calls": [
                ("analyze_team_circuit_fit", {
                    "team_name": team,
                    "session_type": session_type,
                }),
                ("get_team_car_profile", {
                    "team_name": team,
                }),
            ] + (
                [("analyze_team_telemetry_traits", {
                    "round_number": round_number,
                    "team_name": team,
                    "session_type": session_type,
                })]
                if round_number is not None
                else []
            ),
        }

    if analysis_mode == "grip_comparison":
        codes = resolved.get("entity_codes") or []
        names = resolved.get("entity_names") or []
        if round_number is None or len(codes) < 2 or len(names) < 2:
            return None
        session_type = resolved.get("session_type") or "Q"
        return {
            "analysis_mode": "grip_comparison",
            "focus": "grip",
            "question": message,
            "round_number": round_number,
            "event_name": resolved.get("event_name"),
            "country": resolved.get("country"),
            "drivers": [
                {"name": names[0], "code": codes[0]},
                {"name": names[1], "code": codes[1]},
            ],
            "tool_calls": [
                ("analyze_cornering_loads", {
                    "round_number": round_number,
                    "session_type": session_type,
                    "driver_a": codes[0],
                    "driver_b": codes[1],
                }),
            ],
        }

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

    focus = resolved.get("analysis_focus") or ("qualifying" if resolved.get("session_type") in ("Q", "SQ") else "race")
    quali_session = resolved.get("session_type") if resolved.get("session_type") in ("Q", "SQ") else "Q"
    race_session = resolved.get("session_type") if resolved.get("session_type") in ("R", "S") else "R"

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
        results_tool = "get_sprint_qualifying_results" if quali_session == "SQ" else "get_qualifying_results"
        plan["tool_calls"] = [
            (results_tool, {"round_number": round_number}),
            ("analyze_qualifying_battle", {
                "round_number": round_number,
                "driver_a": codes[0],
                "driver_b": codes[1],
                "session_type": quali_session,
            }),
            ("compare_corner_profiles", {
                "round_number": round_number,
                "session_type": quali_session,
                "driver_a": codes[0],
                "driver_b": codes[1],
            }),
            ("analyze_cornering_loads", {
                "round_number": round_number,
                "session_type": quali_session,
                "driver_a": codes[0],
                "driver_b": codes[1],
            }),
            ("get_team_radio", {
                "round_number": round_number,
                "session_type": quali_session,
                "driver_ref": codes[0],
                "limit": 6,
            }),
            ("get_team_radio", {
                "round_number": round_number,
                "session_type": quali_session,
                "driver_ref": codes[1],
                "limit": 6,
            }),
        ]
        return plan

    if focus in ("race", "session"):
        plan["tool_calls"] = [
            ("get_driver_race_story", {"round_number": round_number, "driver_name": names[0], "session_type": race_session}),
            ("get_driver_race_story", {"round_number": round_number, "driver_name": names[1], "session_type": race_session}),
            ("analyze_race_pace_battle", {
                "round_number": round_number,
                "driver_a": codes[0],
                "driver_b": codes[1],
                "session_type": race_session,
            }),
            ("get_safety_car_periods", {
                "round_number": round_number,
                "session_type": race_session,
            }),
        ]
        return plan

    return None


def _execute_analysis_tool_call(tool_name: str, args: dict) -> dict:
    try:
        logger.info("Deterministic analysis tool call: %s args=%s", tool_name, args)
        result = execute_tool(tool_name, args)
        result = strip_heavy_payload_fields(tool_name, result)
        return {
            "tool": tool_name,
            "args": args,
            "result": result,
        }
    except Exception as exc:
        return {
            "tool": tool_name,
            "args": args,
            "error": str(exc),
        }


def _execute_analysis_tool_calls(tool_calls: list[tuple[str, dict]]) -> list[dict]:
    if not tool_calls:
        return []
    if len(tool_calls) == 1:
        tool_name, args = tool_calls[0]
        return [_execute_analysis_tool_call(tool_name, args)]

    max_workers = min(MAX_DETERMINISTIC_TOOL_WORKERS, len(tool_calls))
    with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="f1dash-analysis-tool") as executor:
        futures = [
            executor.submit(_execute_analysis_tool_call, tool_name, args)
            for tool_name, args in tool_calls
        ]
        return [future.result() for future in futures]


def _retrieve_analysis_evidence(plan: dict, resolved: dict | None = None) -> list[dict]:
    evidence = _execute_analysis_tool_calls(plan.get("tool_calls", []))

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
    preloaded = _preload_resolved_context(resolved)
    return resolved, preloaded


def _preload_resolved_context(resolved: dict) -> dict | None:
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

    return preloaded


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


def _try_deterministic_analysis(question: str, history: list[dict], *, provider: str, resolved_context: dict | None = None) -> dict | None:
    if resolved_context is None:
        previous_context = resolve_context_from_history(history)
        resolved = resolve_query_context(question, previous_context)
    else:
        resolved = resolved_context
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
            return _payload_with_inline_widgets(
                _run_openai_answer_writer(question, analysis),
                _widgets_from_analysis_evidence(plan, evidence),
                executed_evidence=evidence,
            )

        analysis = _run_anthropic_analysis(question, resolved, plan, evidence)
        if plan.get("focus") == "qualifying":
            analysis = _canonicalize_qualifying_analysis(analysis, evidence)
        elif plan.get("analysis_mode") == "race_pace_comparison":
            analysis = _canonicalize_race_pace_analysis(analysis, evidence)
        return _payload_with_inline_widgets(
            _run_anthropic_answer_writer(question, analysis),
            _widgets_from_analysis_evidence(plan, evidence),
            executed_evidence=evidence,
        )
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
    response = _call_anthropic(
        client,
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
    response = _call_anthropic(
        client,
        model="claude-opus-4-7",
        max_tokens=1200,
        system=ANSWER_WRITER_SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": _build_answer_writer_prompt(question, analysis),
        }],
    )
    return "".join(block.text for block in response.content if hasattr(block, "text")).strip()


def _answer_anthropic(message: str, history: list[dict], resolved_context: dict | None = None, preloaded_context: dict | None = None) -> dict:
    client = _get_anthropic_client()
    if resolved_context is None:
        resolved, preloaded = _prepare_resolved_context(message, history)
    else:
        resolved = resolved_context
        preloaded = preloaded_context
    request_system_prompt = _build_request_system_prompt(resolved, preloaded)
    messages = [{"role": h["role"], "content": h["content"]} for h in history]
    messages.append({"role": "user", "content": message})
    executed_evidence = []

    for _ in range(MAX_TOOL_ROUNDS):
        response = _call_anthropic(
            client,
            model="claude-opus-4-7",
            max_tokens=4096,
            system=request_system_prompt,
            tools=TOOL_DEFINITIONS,
            messages=messages,
        )

        if response.stop_reason == "end_turn":
            for block in response.content:
                if hasattr(block, "text"):
                    return _payload_with_inline_widgets(
                        block.text,
                        _merge_widgets(
                            _widgets_from_preloaded(preloaded),
                            _widgets_from_analysis_evidence({}, executed_evidence),
                        ),
                        executed_evidence=executed_evidence,
                    )
            raise ValueError("Claude returned end_turn but no text content block")

        if response.stop_reason == "tool_use":
            tool_results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                try:
                    logger.info("Anthropic tool call: %s args=%s", block.name, block.input)
                    result = execute_tool(block.name, block.input)
                    result = strip_heavy_payload_fields(block.name, result)
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
    response = _call_openai(
        client,
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
    response = _call_openai(
        client,
        model="gpt-4o",
        messages=[
            {"role": "system", "content": ANSWER_WRITER_SYSTEM_PROMPT},
            {"role": "user", "content": _build_answer_writer_prompt(question, analysis)},
        ],
    )
    return response.choices[0].message.content.strip()


def _answer_openai(message: str, history: list[dict], resolved_context: dict | None = None, preloaded_context: dict | None = None) -> dict:
    client = _get_openai_client()
    if resolved_context is None:
        resolved, preloaded = _prepare_resolved_context(message, history)
    else:
        resolved = resolved_context
        preloaded = preloaded_context
    request_system_prompt = _build_request_system_prompt(resolved, preloaded)
    messages = [{"role": "system", "content": request_system_prompt}]
    messages += [{"role": h["role"], "content": h["content"]} for h in history]
    messages.append({"role": "user", "content": message})
    executed_evidence = []

    for _ in range(MAX_TOOL_ROUNDS):
        response = _call_openai(
            client,
            model="gpt-4o",
            messages=messages,
            tools=OPENAI_TOOL_DEFINITIONS,
            tool_choice="auto",
        )

        choice = response.choices[0]

        if choice.finish_reason == "stop":
            return _payload_with_inline_widgets(
                choice.message.content,
                _merge_widgets(
                    _widgets_from_preloaded(preloaded),
                    _widgets_from_analysis_evidence({}, executed_evidence),
                ),
                executed_evidence=executed_evidence,
            )

        if choice.finish_reason == "tool_calls":
            # Append the assistant turn (contains the tool_calls)
            messages.append(choice.message)

            # Execute each tool call and append results
            for tool_call in choice.message.tool_calls:
                try:
                    args = json.loads(tool_call.function.arguments)
                    logger.info("OpenAI tool call: %s args=%s", tool_call.function.name, args)
                    result = execute_tool(tool_call.function.name, args)
                    result = strip_heavy_payload_fields(tool_call.function.name, result)
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

def _valid_driver_codes() -> list[str]:
    return sorted({
        (d.get("code") or "").upper()
        for d in _cached_drivers()
        if d.get("code")
    })


def answer_f1_payload(message: str, history: list[dict] | None = None) -> dict:
    """
    Answer an F1 question using the configured LLM provider.

    history: list of prior {role, content} dicts from the conversation.
    Reads LLM_PROVIDER from the environment (default: 'anthropic').
    """
    try:
        prior = history or []
        provider = os.environ.get("LLM_PROVIDER", "anthropic").lower()
        previous_context = resolve_context_from_history(prior)
        resolved = resolve_query_context(message, previous_context)
        deterministic = _try_deterministic_analysis(message, prior, provider=provider, resolved_context=resolved)
        if deterministic:
            deterministic["valid_driver_codes"] = _valid_driver_codes()
            return deterministic
        preloaded = _preload_resolved_context(resolved)
        if provider == "openai":
            payload = _answer_openai(message, prior, resolved_context=resolved, preloaded_context=preloaded)
        else:
            payload = _answer_anthropic(message, prior, resolved_context=resolved, preloaded_context=preloaded)
        payload["valid_driver_codes"] = _valid_driver_codes()
        return payload
    except LLMTransientError as e:
        if e.kind == "rate_limit":
            msg = "The model is throttling right now — please retry in a moment."
        elif e.kind == "connection":
            msg = "I lost the connection to the model — please retry."
        else:
            msg = "The model API returned an error — please retry."
        return {"response": msg, "widgets": [], "valid_driver_codes": _valid_driver_codes()}


def answer_f1_question(message: str, history: list[dict] | None = None) -> str:
    return answer_f1_payload(message, history)["response"]
