"""Energy-management deep analysis feature. Migrated from chat.py / tools.py / f1_data.py."""
from __future__ import annotations

import f1_data
from features.base import Feature, register_feature


_RELEVANT_KEYWORDS = (
    "energy", "battery", "deployment", "harvesting", "mguk", "mguh",
    "ers", "clipping", "lift and coast", "lift-and-coast", "lift",
)

# No specific mode binding — energy questions arise across race + quali.
_RELEVANT_MODES: frozenset[str] = frozenset()

_REQUIRED_ARGS = ("round_number", "session_type", "driver_a")


def _build_energy_management_widget(result: dict) -> dict:
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


@register_feature
class EnergyManagementFeature(Feature):
    name = "analyze_energy_management"
    applies_to = ("driver",)
    description = (
        "DEEP ANALYSIS PRIMITIVE. Analyze likely 2026-style energy management patterns such as lift-and-coast and possible late-straight clipping. "
        "This tool uses telemetry heuristics and explicitly distinguishes measured signals from inferred energy behavior."
    )
    required_args = _REQUIRED_ARGS
    tool_schema = {
        "type": "object",
        "properties": {
            "round_number": {"type": "integer"},
            "session_type": {"type": "string"},
            "driver_a": {"type": "string"},
            "driver_b": {"type": "string"},
            "lap_number_a": {"type": "integer"},
            "lap_number_b": {"type": "integer"},
        },
        "required": list(_REQUIRED_ARGS),
    }

    def is_relevant_for(self, question: str, resolved: dict | None) -> float:
        q = (question or "").lower()
        mode = (resolved or {}).get("analysis_mode")
        has_keyword = any(kw in q for kw in _RELEVANT_KEYWORDS)
        has_mode = mode in _RELEVANT_MODES
        if has_keyword and has_mode:
            return 0.85
        if has_keyword:
            return 0.65
        if has_mode:
            return 0.45
        return 0.0

    def execute(self, **args) -> dict:
        return f1_data.analyze_energy_management(
            args["round_number"],
            args["session_type"],
            args["driver_a"],
            args.get("driver_b"),
            args.get("lap_number_a"),
            args.get("lap_number_b"),
        )

    def make_widget(self, result: dict) -> dict:
        return _build_energy_management_widget(result)

    def should_show_widget(self, result: dict) -> bool:
        # Legacy gate: `if w.get("speed_trace_a"): widgets.append(w)`
        return bool(result.get("speed_trace_a"))
