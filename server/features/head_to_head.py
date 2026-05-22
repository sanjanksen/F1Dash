"""Head-to-head driver comparison feature. Migrated from tools.py / f1_data.py."""
from __future__ import annotations

import f1_data
from features.base import Feature, register_feature


@register_feature
class HeadToHeadFeature(Feature):
    name = "get_head_to_head"
    applies_to = ("pair_of_drivers",)
    description = "PRIMITIVE TOOL. Compare two drivers across all 2026 races they both contested."
    required_args = ("driver_a", "driver_b")
    tool_schema = {
        "type": "object",
        "properties": {
            "driver_a": {"type": "string", "description": "First driver full name, surname, or 3-letter code."},
            "driver_b": {"type": "string", "description": "Second driver full name, surname, or 3-letter code."},
        },
        "required": ["driver_a", "driver_b"],
    }

    def is_relevant_for(self, question: str, resolved: dict | None) -> float:
        # Mode-driven orchestration replaced keyword predicates. The Feature
        # ABC still requires this method; the agentic fallback path may call
        # it (returns 0 = "no opinion from this layer").
        return 0.0

    def execute(self, **args) -> dict:
        return f1_data.get_head_to_head(args["driver_a"], args["driver_b"])

    def make_widget(self, result: dict) -> dict:
        return {}

    def should_show_widget(self, result: dict) -> bool:
        # head_to_head currently emits no widget; gate stays False until a
        # widget component is wired up.
        return False
