"""Results lookup features (race, qualifying, sprint, sprint quali, session)."""
from __future__ import annotations

import f1_data
from features.base import Feature, register_feature


_RACE_KEYWORDS = ("result", "finish", "classification", "winner", "won", "podium")
_QUALI_KEYWORDS = ("qualifying", "quali", "pole", "q1", "q2", "q3", "grid")
_SPRINT_KEYWORDS = ("sprint",)
_SESSION_KEYWORDS = ("session", "result", "classification")


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
        q = (question or "").lower()
        return 0.65 if any(kw in q for kw in _RACE_KEYWORDS) else 0.0

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
        q = (question or "").lower()
        return 0.65 if any(kw in q for kw in _QUALI_KEYWORDS) else 0.0

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
        q = (question or "").lower()
        return 0.65 if any(kw in q for kw in _SPRINT_KEYWORDS) else 0.0

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
        q = (question or "").lower()
        has_sprint = any(kw in q for kw in _SPRINT_KEYWORDS)
        has_quali = any(kw in q for kw in _QUALI_KEYWORDS)
        if has_sprint and has_quali:
            return 0.75
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
        q = (question or "").lower()
        return 0.55 if any(kw in q for kw in _SESSION_KEYWORDS) else 0.0

    def execute(self, **args):
        return f1_data.get_session_results(args["round_number"], args["session_type"])

    def make_widget(self, result):
        return {}

    def should_show_widget(self, result):
        return False
