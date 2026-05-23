"""Active-aero deep analysis feature. Migrated from chat.py / tools.py / f1_data.py."""
from __future__ import annotations

import f1_data
from features.base import Feature, register_feature


_REQUIRED_ARGS = ("driver_code", "round_number", "session_type", "lap_number")


def _build_active_aero_widget(result: dict) -> dict:
    return {
        "type": "active_aero",
        "driver_code": result.get("driver_code"),
        "round_number": result.get("round_number"),
        "session_type": result.get("session_type"),
        "lap_number": result.get("lap_number"),
        "circuit_slug": result.get("circuit_slug"),
        "circuit_in_coverage": result.get("circuit_in_coverage", False),
        "segments": result.get("segments") or [],
        "total_z_mode_seconds": result.get("total_z_mode_seconds", 0.0),
        "estimated_lap_time_delta_s": result.get("estimated_lap_time_delta_s", 0.0),
        "inferred": result.get("inferred", True),
        "note": result.get("note"),
    }


@register_feature
class ActiveAeroFeature(Feature):
    name = "analyze_active_aero_usage"
    applies_to = ("driver", "lap")
    description = (
        "DEEP ANALYSIS PRIMITIVE. Detect 2026 active-aero Z-mode (low-drag) usage on a specific lap. "
        "Returns segments where Z-mode was active inside FIA-permitted aero zones, total Z-mode "
        "seconds, and an estimated speed gain vs full-X-mode. May return inferred=True when FastF1 "
        "doesn't expose the active-aero channel directly — in that case the result is derived from "
        "per-circuit aero-zone definitions and speed-trace heuristics, and the chat layer should "
        "hedge accordingly. Use for specific-lap questions like 'where did Norris run Z-mode on lap 12?'."
    )
    required_args = _REQUIRED_ARGS
    tool_schema = {
        "type": "object",
        "properties": {
            "driver_code": {"type": "string"},
            "round_number": {"type": "integer"},
            "session_type": {"type": "string"},
            "lap_number": {"type": "integer"},
        },
        "required": list(_REQUIRED_ARGS),
    }

    def execute(self, **args) -> dict:
        return f1_data.analyze_active_aero_usage(
            args["driver_code"],
            args["round_number"],
            args["session_type"],
            args["lap_number"],
        )

    def make_widget(self, result: dict) -> dict:
        return _build_active_aero_widget(result)

    def should_show_widget(self, result: dict) -> bool:
        if not result.get("available", True):
            return False
        if not result.get("circuit_in_coverage"):
            return False
        z_secs = result.get("total_z_mode_seconds") or 0
        if z_secs < 0.3:
            return False
        # f1_data derives estimated_lap_time_delta_s as z_secs * 0.02, so an
        # absolute-magnitude gate on it is redundant with the z_secs gate and
        # effectively unreachable for any z_secs < 1.0s. Drop the redundant
        # check; surfacing a 0.3s+ Z-mode usage is signal enough.
        return True
