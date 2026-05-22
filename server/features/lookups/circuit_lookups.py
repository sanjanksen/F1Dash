"""Circuit metadata lookup features."""
from __future__ import annotations

import f1_data
from features.base import Feature, register_feature


@register_feature
class CircuitDetailsFeature(Feature):
    name = "get_circuit_details"
    applies_to = ()
    description = (
        "PRIMITIVE TOOL. Circuit metadata including corners, marshal lights, marshal sectors, "
        "and rotation."
    )
    required_args = ("round_number",)
    tool_schema = {
        "type": "object",
        "properties": {
            "round_number": {"type": "integer", "description": "The 2026 season round number."},
        },
        "required": ["round_number"],
    }

    def is_relevant_for(self, question, resolved):
        # Mode-driven orchestration replaced keyword predicates. The Feature
        # ABC still requires this method; the agentic fallback path may call
        # it (returns 0 = "no opinion from this layer").
        return 0.0

    def execute(self, **args):
        return f1_data.get_circuit_details(args["round_number"])

    def make_widget(self, result):
        return {}

    def should_show_widget(self, result):
        return False


@register_feature
class CircuitCornersFeature(Feature):
    name = "get_circuit_corners"
    applies_to = ()
    description = "PRIMITIVE TOOL. Circuit corner map with corner numbers and distances."
    required_args = ("round_number",)
    tool_schema = {
        "type": "object",
        "properties": {
            "round_number": {"type": "integer", "description": "The 2026 season round number."},
        },
        "required": ["round_number"],
    }

    def is_relevant_for(self, question, resolved):
        # Mode-driven orchestration replaced keyword predicates. The Feature
        # ABC still requires this method; the agentic fallback path may call
        # it (returns 0 = "no opinion from this layer").
        return 0.0

    def execute(self, **args):
        return f1_data.get_circuit_corners(args["round_number"])

    def make_widget(self, result):
        return {}

    def should_show_widget(self, result):
        return False


@register_feature
class CircuitTrackMapFeature(Feature):
    name = "get_circuit_track_map"
    applies_to = ()
    triggered_by_modes = frozenset({"circuit_profile"})
    description = (
        "PRIMITIVE TOOL. GPS-derived circuit shape: downsampled {x, y, distance_m} points from the "
        "fastest lap plus sector boundary distances. Use for circuit map visualization."
    )
    required_args = ("round_number",)
    tool_schema = {
        "type": "object",
        "properties": {
            "round_number": {"type": "integer", "description": "The 2026 season round number."},
        },
        "required": ["round_number"],
    }

    def is_relevant_for(self, question, resolved):
        # Mode-driven orchestration replaced keyword predicates. The Feature
        # ABC still requires this method; the agentic fallback path may call
        # it (returns 0 = "no opinion from this layer").
        return 0.0

    def execute(self, **args):
        return f1_data.get_circuit_track_map(args["round_number"])

    def make_widget(self, result):
        return {}

    def should_show_widget(self, result):
        return False


@register_feature
class HistoricalCircuitPerformanceFeature(Feature):
    name = "get_historical_circuit_performance"
    applies_to = ()
    triggered_by_modes = frozenset({"circuit_profile"})
    description = (
        "PRIMITIVE TOOL. Historical quali/race top performers for the same circuit across recent years."
    )
    required_args = ("round_number",)
    tool_schema = {
        "type": "object",
        "properties": {
            "round_number": {"type": "integer", "description": "The 2026 season round number."},
            "years": {"type": "array", "items": {"type": "integer"}, "description": "Optional years list."},
        },
        "required": ["round_number"],
    }

    def is_relevant_for(self, question, resolved):
        # Mode-driven orchestration replaced keyword predicates. The Feature
        # ABC still requires this method; the agentic fallback path may call
        # it (returns 0 = "no opinion from this layer").
        return 0.0

    def execute(self, **args):
        return f1_data.get_historical_circuit_performance(args["round_number"], args.get("years"))

    def make_widget(self, result):
        return {}

    def should_show_widget(self, result):
        return False
