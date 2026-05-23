"""Mini-sectors heatmap feature. Migrated from chat.py / tools.py / f1_data.py.

This is the pilot feature for the registry refactor. The underlying
analysis function stays in f1_data.py; this module wraps it with the
applies_to + make_widget + should_show_widget surface
the registry expects.
"""
from __future__ import annotations

import f1_data
from features.base import Feature, register_feature


_REQUIRED_ARGS = ("driver_a", "driver_b", "lap_number", "round_number")


def _build_mini_sector_heatmap_widget(result: dict) -> dict:
    """Map compare_mini_sectors output to the mini_sector_heatmap widget shape."""
    if not result.get("available", True):
        return {
            "type": "mini_sector_heatmap",
            "available": False,
            "reason": result.get("reason"),
        }
    return {
        "type": "mini_sector_heatmap",
        "available": True,
        "driver_a": result.get("driver_a"),
        "driver_b": result.get("driver_b"),
        "lap_number": result.get("lap_number"),
        "round_number": result.get("round_number"),
        "session_type": result.get("session_type"),
        "n_segments": result.get("n_segments"),
        "weather_state": result.get("weather_state"),
        "segments": result.get("segments") or [],
        "cumulative_delta": result.get("cumulative_delta") or [],
        "total_delta_s": result.get("total_delta_s"),
        "segments_won_a": result.get("segments_won_a"),
        "segments_won_b": result.get("segments_won_b"),
        "segments_tied": result.get("segments_tied"),
        "drs_mix_warning": result.get("drs_mix_warning", False),
    }


@register_feature
class MiniSectorsFeature(Feature):
    name = "compare_mini_sectors"
    applies_to = ("pair_of_drivers", "lap")
    description = (
        "PRIMITIVE TOOL. Compare two drivers across 25 equal-distance mini-sectors of a single lap. "
        "Returns per-segment time delta (driver_a - driver_b), cumulative delta along "
        "distance, segment-win counts, and a DRS-mix warning if one driver had DRS "
        "open in a segment and the other didn't. Use for 'where on the lap was X "
        "faster than Y' questions - mini-sectors localize gains to ~200m resolution "
        "vs the 3-sector coarse default. Prefer over get_sector_comparison when the "
        "user wants granular location-of-gain analysis."
    )
    required_args = _REQUIRED_ARGS
    tool_schema = {
        "type": "object",
        "properties": {
            "driver_a": {"type": "string"},
            "driver_b": {"type": "string"},
            "lap_number": {"type": "integer"},
            "round_number": {"type": "integer"},
            "session_type": {"type": "string", "default": "Q"},
            "n": {"type": "integer", "default": 25},
        },
        "required": list(_REQUIRED_ARGS),
    }

    def execute(self, **args) -> dict:
        return f1_data.compare_mini_sectors(
            driver_a=args["driver_a"],
            driver_b=args["driver_b"],
            lap_number=args["lap_number"],
            round_number=args["round_number"],
            session_type=args.get("session_type", "Q"),
            n=args.get("n", 25),
        )

    def make_widget(self, result: dict) -> dict:
        return _build_mini_sector_heatmap_widget(result)

    def should_show_widget(self, result: dict) -> bool:
        if not result.get("available", True):
            return False
        segments = result.get("segments") or []
        if len(segments) < 10:
            return False
        won_a = result.get("segments_won_a") or 0
        won_b = result.get("segments_won_b") or 0
        if (won_a + won_b) < 3:
            return False
        total = result.get("total_delta_s")
        if total is None or abs(total) < 0.05:
            return False
        return True
