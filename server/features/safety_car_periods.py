"""Safety car periods feature. Migrated from tools.py / f1_data.py."""
from __future__ import annotations

import f1_data
from features.base import Feature, register_feature


_REQUIRED_ARGS = ("round_number", "session_type")


@register_feature
class SafetyCarPeriodsFeature(Feature):
    name = "get_safety_car_periods"
    applies_to = ("race_session",)
    triggered_by_modes = frozenset({"race_pace_comparison", "driver_comparison"})
    description = (
        "PRIMITIVE TOOL. SC/VSC timing and pit-stop impact for a session. "
        "Use for specific safety-car questions. For broad race recaps, prefer composite tools first."
    )
    required_args = _REQUIRED_ARGS
    tool_schema = {
        "type": "object",
        "properties": {
            "round_number": {"type": "integer", "description": "The 2026 season round number."},
            "session_type": {"type": "string", "description": "Session type, usually R or S."},
        },
        "required": list(_REQUIRED_ARGS),
    }

    def execute(self, **args) -> dict:
        return f1_data.get_safety_car_periods(
            args["round_number"],
            args["session_type"],
        )

    def make_widget(self, result: dict) -> dict:
        return {}

    def should_show_widget(self, result: dict) -> bool:
        return False
