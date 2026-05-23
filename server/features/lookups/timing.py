"""Timing / pace lookup features."""
from __future__ import annotations

import f1_data
from features.base import Feature, register_feature


@register_feature
class CleanPaceSummaryFeature(Feature):
    name = "get_clean_pace_summary"
    applies_to = ()
    description = (
        "PRIMITIVE TOOL. Clean-lap pace summary filtering out inaccurate, deleted, and pit laps."
    )
    required_args = ("round_number", "session_type")
    tool_schema = {
        "type": "object",
        "properties": {
            "round_number": {"type": "integer", "description": "The 2026 season round number."},
            "session_type": {"type": "string", "description": "Session type: Q, R, FP1, FP2, FP3, S, SQ, SS."},
            "driver_codes": {"type": "array", "items": {"type": "string"}, "description": "Optional 3-letter driver codes."},
            "green_only": {"type": "boolean", "description": "Keep only green-flag laps. Defaults to true."},
            "limit": {"type": "integer", "description": "Representative laps per driver. Defaults to 10."},
        },
        "required": ["round_number", "session_type"],
    }

    def execute(self, **args):
        return f1_data.get_clean_pace_summary(
            args["round_number"],
            args["session_type"],
            args.get("driver_codes"),
            args.get("green_only", True),
            args.get("limit", 10),
        )

    def make_widget(self, result):
        return {}

    def should_show_widget(self, result):
        return False


@register_feature
class TrackPositionComparisonFeature(Feature):
    name = "get_track_position_comparison"
    applies_to = ()
    description = (
        "DEEP ANALYSIS PRIMITIVE. Compare two drivers using raw position data and speed aligned by distance."
    )
    required_args = ("round_number", "session_type", "driver_a", "driver_b")
    tool_schema = {
        "type": "object",
        "properties": {
            "round_number": {"type": "integer", "description": "The 2026 season round number."},
            "session_type": {"type": "string", "description": "Session type: Q, R, FP1, FP2, FP3, S, SQ, SS."},
            "driver_a": {"type": "string", "description": "First driver's 3-letter code."},
            "driver_b": {"type": "string", "description": "Second driver's 3-letter code."},
            "lap_number_a": {"type": "integer", "description": "Optional lap number for driver_a."},
            "lap_number_b": {"type": "integer", "description": "Optional lap number for driver_b."},
        },
        "required": ["round_number", "session_type", "driver_a", "driver_b"],
    }

    def execute(self, **args):
        return f1_data.get_track_position_comparison(
            args["round_number"],
            args["session_type"],
            args["driver_a"],
            args["driver_b"],
            args.get("lap_number_a"),
            args.get("lap_number_b"),
        )

    def make_widget(self, result):
        return {}

    def should_show_widget(self, result):
        return False


@register_feature
class QualifyingProgressionFeature(Feature):
    name = "get_qualifying_progression"
    applies_to = ()
    description = "PRIMITIVE TOOL. Q1/Q2/Q3 progression and improvements by driver."
    required_args = ("round_number",)
    tool_schema = {
        "type": "object",
        "properties": {
            "round_number": {"type": "integer", "description": "The 2026 season round number."},
        },
        "required": ["round_number"],
    }

    def execute(self, **args):
        return f1_data.get_qualifying_progression(args["round_number"])

    def make_widget(self, result):
        return {}

    def should_show_widget(self, result):
        return False


@register_feature
class SessionFastestLapsFeature(Feature):
    name = "get_session_fastest_laps"
    applies_to = ()
    description = "PRIMITIVE TOOL. Fastest-lap leaderboard for a session with sectors and speed traps."
    required_args = ("round_number", "session_type")
    tool_schema = {
        "type": "object",
        "properties": {
            "round_number": {"type": "integer", "description": "The 2026 season round number."},
            "session_type": {"type": "string", "description": "Session type: Q, R, FP1, FP2, FP3, S, SQ, SS."},
        },
        "required": ["round_number", "session_type"],
    }

    def execute(self, **args):
        return f1_data.get_session_fastest_laps(args["round_number"], args["session_type"])

    def make_widget(self, result):
        return {}

    def should_show_widget(self, result):
        return False


@register_feature
class SpeedTrapLeaderboardFeature(Feature):
    name = "get_speed_trap_leaderboard"
    applies_to = ()
    description = (
        "PRIMITIVE TOOL. Peak speed at each timing trap for every driver, scanning all laps. "
        "Returns four ranked lists: speed_st (main straight), speed_fl (finish line), "
        "speed_i1 (intermediate 1), speed_i2 (intermediate 2). Each entry: driver, team, "
        "speed_kph, lap_number, compound, drs_open, rank. A driver's fastest ST may come on a "
        "different lap than their fastest FL — each trap is ranked independently. "
        "DRS state: each row carries drs_open: bool derived from telemetry at the moment of the "
        "peak reading. By default, if some drivers' peaks came DRS-open and others DRS-closed, "
        "the tool returns a refusal payload (with a `refusal` field plus per-row drs_open) "
        "because mixing DRS states inflates the gap by ~6+ km/h. Re-call with "
        "allow_mixed_drs=true to get the raw figures anyway. "
        "Use for 'who had the highest top speed?', 'speed trap leaderboard', "
        "'who was fastest down the straight?', 'drag/straight-line speed' questions."
    )
    required_args = ("round_number", "session_type")
    tool_schema = {
        "type": "object",
        "properties": {
            "round_number": {"type": "integer", "description": "The 2026 season round number."},
            "session_type": {"type": "string", "description": "Session type: Q, R, FP1, FP2, FP3, S, SQ, SS."},
            "allow_mixed_drs": {"type": "boolean", "description": "Optional. If true, return ranked rows even when some peaks were DRS-open and others DRS-closed. Default false (the tool refuses with a payload that explains why)."},
        },
        "required": ["round_number", "session_type"],
    }

    def execute(self, **args):
        return f1_data.get_speed_trap_leaderboard(
            args["round_number"],
            args["session_type"],
            bool(args.get("allow_mixed_drs", False)),
        )

    def make_widget(self, result):
        return {}

    def should_show_widget(self, result):
        return False
