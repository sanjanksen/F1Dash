"""Strategy lookup feature."""
from __future__ import annotations

import f1_data
from features.base import Feature, register_feature


@register_feature
class DriverStrategyFeature(Feature):
    name = "get_driver_strategy"
    applies_to = ("driver", "race_session")
    triggered_by_modes = frozenset({"race_pace_comparison"})
    description = (
        "PRIMITIVE TOOL. Tyre strategy and stints for one driver or the whole field. "
        "Use for specific pit/strategy questions. For broad race recaps, prefer composite tools first."
    )
    required_args = ("round_number", "session_type")
    tool_schema = {
        "type": "object",
        "properties": {
            "round_number": {"type": "integer", "description": "The 2026 season round number."},
            "session_type": {"type": "string", "description": "Session type, usually R or S."},
            "driver_code": {"type": "string", "description": "Optional 3-letter driver code."},
        },
        "required": ["round_number", "session_type"],
    }

    def is_relevant_for(self, question, resolved):
        # Mode-driven orchestration replaced keyword predicates. The Feature
        # ABC still requires this method; the agentic fallback path may call
        # it (returns 0 = "no opinion from this layer").
        return 0.0

    def execute(self, **args):
        return f1_data.get_driver_strategy(
            args["round_number"], args["session_type"], args.get("driver_code")
        )

    def make_widget(self, result):
        return {}

    def should_show_widget(self, result):
        return False
