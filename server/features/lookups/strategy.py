"""Strategy lookup feature."""
from __future__ import annotations

import f1_data
from features.base import Feature, register_feature


_STRATEGY_KEYWORDS = (
    "strategy", "stint", "tyre", "tire", "pit", "compound", "undercut", "overcut",
)


@register_feature
class DriverStrategyFeature(Feature):
    name = "get_driver_strategy"
    applies_to = ()
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
        q = (question or "").lower()
        return 0.65 if any(kw in q for kw in _STRATEGY_KEYWORDS) else 0.0

    def execute(self, **args):
        return f1_data.get_driver_strategy(
            args["round_number"], args["session_type"], args.get("driver_code")
        )

    def make_widget(self, result):
        return {}

    def should_show_widget(self, result):
        return False
