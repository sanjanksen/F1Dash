"""Driver weekend overview feature. Migrated from tools.py / f1_data.py."""
from __future__ import annotations

import f1_data
from features.base import Feature, register_feature


_REQUIRED_ARGS = ("round_number", "driver_name")


@register_feature
class DriverWeekendOverviewFeature(Feature):
    name = "get_driver_weekend_overview"
    applies_to = ("driver", "session")
    description = (
        "COMPOSITE RECAP TOOL. High-level factual weekend or race overview for one driver. "
        "Use this for broad driver recap questions when you want summary structure more than narrative. "
        "Pass session_type='S' for a sprint overview, session_type='R' (default) for the main race."
    )
    required_args = _REQUIRED_ARGS
    tool_schema = {
        "type": "object",
        "properties": {
            "round_number": {"type": "integer", "description": "The 2026 season round number."},
            "driver_name": {"type": "string", "description": "Driver full name, surname, or 3-letter code."},
            "session_type": {"type": "string", "description": "R (default, main race) or S (sprint race)."},
        },
        "required": list(_REQUIRED_ARGS),
    }

    def execute(self, **args) -> dict:
        return f1_data.get_driver_weekend_overview(
            args["round_number"],
            args["driver_name"],
            session_type=args.get("session_type", "R"),
        )

    def make_widget(self, result: dict) -> dict:
        return {}

    def should_show_widget(self, result: dict) -> bool:
        return False
