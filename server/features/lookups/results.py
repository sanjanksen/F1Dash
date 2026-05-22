"""Results lookup features (race, qualifying, sprint, sprint quali, session)."""
from __future__ import annotations

import f1_data
from features.base import Feature, register_feature


@register_feature
class RaceResultsFeature(Feature):
    name = "get_race_results"
    applies_to = ()
    description = (
        "PRIMITIVE TOOL. Raw race classification for one round. "
        "Use for pure results lookup, not as the first tool for a broad recap."
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
        return f1_data.get_race_results(args["round_number"])

    def make_widget(self, result):
        return {}

    def should_show_widget(self, result):
        return False


@register_feature
class QualifyingResultsFeature(Feature):
    name = "get_qualifying_results"
    applies_to = ()
    triggered_by_modes = frozenset({"driver_comparison"})
    description = "PRIMITIVE TOOL. Raw qualifying classification with Q1/Q2/Q3 times for one round."
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
        return f1_data.get_qualifying_results(args["round_number"])

    def make_widget(self, result):
        return {}

    def should_show_widget(self, result):
        return False


@register_feature
class SprintResultsFeature(Feature):
    name = "get_sprint_results"
    applies_to = ()
    description = "PRIMITIVE TOOL. Raw sprint race finishing order for one round. Use for sprint race results lookup."
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
        return f1_data.get_sprint_results(args["round_number"])

    def make_widget(self, result):
        return {}

    def should_show_widget(self, result):
        return False


@register_feature
class SprintQualifyingResultsFeature(Feature):
    name = "get_sprint_qualifying_results"
    applies_to = ()
    triggered_by_modes = frozenset({"driver_comparison"})
    description = (
        "PRIMITIVE TOOL. Sprint qualifying/shootout classification for one round "
        "(SQ1/SQ2/SQ3 segment times)."
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
        return f1_data.get_sprint_qualifying_results(args["round_number"])

    def make_widget(self, result):
        return {}

    def should_show_widget(self, result):
        return False


@register_feature
class SessionResultsFeature(Feature):
    name = "get_session_results"
    applies_to = ()
    description = (
        "PRIMITIVE TOOL. Rich FastF1 session classification metadata such as grid, classified "
        "position, status, team color, and driver number. "
        "Use for session metadata and penalty-aware classification details."
    )
    required_args = ("round_number", "session_type")
    tool_schema = {
        "type": "object",
        "properties": {
            "round_number": {"type": "integer", "description": "The 2026 season round number."},
            "session_type": {"type": "string", "description": "Session type: Q, R, FP1, FP2, FP3, S, SQ, SS."},
        },
        "required": ["round_number", "session_type"],
    }

    def is_relevant_for(self, question, resolved):
        # Mode-driven orchestration replaced keyword predicates. The Feature
        # ABC still requires this method; the agentic fallback path may call
        # it (returns 0 = "no opinion from this layer").
        return 0.0

    def execute(self, **args):
        return f1_data.get_session_results(args["round_number"], args["session_type"])

    def make_widget(self, result):
        return {}

    def should_show_widget(self, result):
        return False
