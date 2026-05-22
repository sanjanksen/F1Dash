"""Lap-data lookup features (driver lap times, telemetry, sectors)."""
from __future__ import annotations

import f1_data
from features.base import Feature, register_feature


_LAPTIME_KEYWORDS = ("lap time", "lap times", "lap-by-lap", "lap by lap", "stint", "pace")
_TELEMETRY_KEYWORDS = ("telemetry", "throttle", "brake", "gear", "rpm", "drs", "speed trace")
_SECTOR_KEYWORDS = ("sector", "s1", "s2", "s3")


@register_feature
class DriverLapTimesFeature(Feature):
    name = "get_driver_lap_times"
    applies_to = ()
    description = (
        "PRIMITIVE TOOL. All laps for one driver in one session, with sectors, compounds, "
        "tyre life, and pit flags."
    )
    required_args = ("round_number", "session_type", "driver_code")
    tool_schema = {
        "type": "object",
        "properties": {
            "round_number": {"type": "integer", "description": "The 2026 season round number."},
            "session_type": {"type": "string", "description": "Session type: Q, R, FP1, FP2, FP3, S, SQ, SS."},
            "driver_code": {"type": "string", "description": "3-letter driver code."},
        },
        "required": ["round_number", "session_type", "driver_code"],
    }

    def is_relevant_for(self, question, resolved):
        q = (question or "").lower()
        return 0.6 if any(kw in q for kw in _LAPTIME_KEYWORDS) else 0.0

    def execute(self, **args):
        return f1_data.get_driver_lap_times(args["round_number"], args["session_type"], args["driver_code"])

    def make_widget(self, result):
        return {}

    def should_show_widget(self, result):
        return False


@register_feature
class LapTelemetryFeature(Feature):
    name = "get_lap_telemetry"
    applies_to = ()
    description = (
        "DEEP ANALYSIS PRIMITIVE. Full telemetry for one driver's lap with speed, throttle, brake, "
        "gear, RPM, and DRS. Each sample carries drs_active: bool — true only when the FastF1 DRS "
        "channel reads 10/12/14 (open and active)."
    )
    required_args = ("round_number", "session_type", "driver_code")
    tool_schema = {
        "type": "object",
        "properties": {
            "round_number": {"type": "integer", "description": "The 2026 season round number."},
            "session_type": {"type": "string", "description": "Session type: Q, R, FP1, FP2, FP3, S, SQ, SS."},
            "driver_code": {"type": "string", "description": "3-letter driver code."},
            "lap_number": {"type": "integer", "description": "Optional specific lap number."},
        },
        "required": ["round_number", "session_type", "driver_code"],
    }

    def is_relevant_for(self, question, resolved):
        q = (question or "").lower()
        return 0.65 if any(kw in q for kw in _TELEMETRY_KEYWORDS) else 0.0

    def execute(self, **args):
        return f1_data.get_lap_telemetry(
            args["round_number"],
            args["session_type"],
            args["driver_code"],
            args.get("lap_number"),
        )

    def make_widget(self, result):
        return {}

    def should_show_widget(self, result):
        return False


@register_feature
class SectorComparisonFeature(Feature):
    name = "get_sector_comparison"
    applies_to = ()
    description = "PRIMITIVE TOOL. Fastest-lap sector comparison between two drivers."
    required_args = ("round_number", "session_type", "driver_a", "driver_b")
    tool_schema = {
        "type": "object",
        "properties": {
            "round_number": {"type": "integer", "description": "The 2026 season round number."},
            "session_type": {"type": "string", "description": "Session type: Q, R, FP1, FP2, FP3, S, SQ, SS."},
            "driver_a": {"type": "string", "description": "First driver's 3-letter code."},
            "driver_b": {"type": "string", "description": "Second driver's 3-letter code."},
        },
        "required": ["round_number", "session_type", "driver_a", "driver_b"],
    }

    def is_relevant_for(self, question, resolved):
        q = (question or "").lower()
        return 0.65 if any(kw in q for kw in _SECTOR_KEYWORDS) else 0.0

    def execute(self, **args):
        return f1_data.get_sector_comparison(
            args["round_number"], args["session_type"], args["driver_a"], args["driver_b"]
        )

    def make_widget(self, result):
        return {}

    def should_show_widget(self, result):
        return False


@register_feature
class TelemetryComparisonFeature(Feature):
    name = "get_telemetry_comparison"
    applies_to = ()
    description = (
        "DEEP ANALYSIS PRIMITIVE. Overlay two drivers' telemetry traces aligned by distance. "
        "Deployment-curve-aware clipping segments are surfaced via analyze_energy_management "
        "(uses the 290/355 km/h MGU-K taper)."
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

    def is_relevant_for(self, question, resolved):
        q = (question or "").lower()
        return 0.65 if any(kw in q for kw in _TELEMETRY_KEYWORDS) else 0.0

    def execute(self, **args):
        return f1_data.get_telemetry_comparison(
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
