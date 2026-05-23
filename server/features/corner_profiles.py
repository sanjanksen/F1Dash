"""Corner-profile comparison deep analysis feature. Migrated from chat.py / tools.py / f1_data.py.

This feature has cross-feature orchestration in chat.py's evidence composer
(focus-based skip when a qualifying battle widget is also present). The
cross-feature branch stays on the legacy if/elif path — chat.py's
_CROSS_FEATURE_TOOLS set makes _registry_widget skip this tool. The Feature
class is registered but dormant for the cross-feature case; Phase E unifies.
"""
from __future__ import annotations

import f1_data
from features.base import Feature, register_feature


_REQUIRED_ARGS = ("round_number", "session_type", "driver_a", "driver_b")


def _build_corner_comparison_widget(result: dict) -> dict:
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
        "total_time_gained_s": result.get("total_time_gained_s"),
    }


@register_feature
class CornerProfilesFeature(Feature):
    name = "compare_corner_profiles"
    applies_to = ("pair_of_drivers",)
    triggered_by_modes = frozenset({"driver_comparison"})
    description = (
        "DEEP ANALYSIS PRIMITIVE. Compare corner-by-corner telemetry between two drivers. "
        "Returns per-corner cause classification (braking/minimum_speed/traction/mixed), "
        "setup direction inference (corner_heavy/straight_heavy/balanced), average straight speeds, "
        "and gain location summary showing the top 3 corners where the faster driver has an advantage. "
        "Use for questions like 'is Ferrari better in corners or on straights vs Mercedes?' or "
        "'where does Norris gain time on Leclerc in quali?'."
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

    def execute(self, **args) -> dict:
        return f1_data.compare_corner_profiles(
            args["round_number"],
            args["session_type"],
            args["driver_a"],
            args["driver_b"],
            args.get("lap_number_a"),
            args.get("lap_number_b"),
        )

    def make_widget(self, result: dict) -> dict:
        return _build_corner_comparison_widget(result)

    def should_show_widget(self, result: dict) -> bool:
        if not result.get("available", True):
            return False
        gain_locations = result.get("gain_location_summary") or []
        if len(gain_locations) < 1:
            return False
        speed_a = result.get("avg_straight_speed_a")
        speed_b = result.get("avg_straight_speed_b")
        brake_delta = result.get("braking_point_delta_m")
        speed_material = (speed_a is not None and speed_b is not None
                          and abs(speed_a - speed_b) >= 2)
        brake_material = brake_delta is not None and abs(brake_delta) >= 5
        return speed_material or brake_material
