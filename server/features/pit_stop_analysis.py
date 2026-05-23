"""Pit stop strategy feature. Migrated from chat.py / tools.py / f1_data.py."""
from __future__ import annotations

import f1_data
from features.base import Feature, register_feature


_REQUIRED_ARGS = ("round_number",)


def _build_pit_stop_strategy_widget(result: dict) -> dict:
    return {
        "type": "pit_stop_strategy",
        "title": f"{result.get('event')} strategy",
        "event": result.get("event"),
        "session": result.get("session"),
        "total_laps": result.get("total_laps"),
        "drivers": result.get("drivers") or [],
    }


@register_feature
class PitStopAnalysisFeature(Feature):
    name = "get_pit_stop_analysis"
    applies_to = ("race_session",)
    description = (
        "PRIMITIVE TOOL. Pit stop strategy for all classified finishers in a race. "
        "Returns per-driver stints (compound, start_lap, end_lap, laps), pit stop laps, "
        "pit durations from OpenF1, and compound changes. Drivers sorted by finish position. "
        "Use for 'who had the fastest pit stops?', 'show me the strategy', "
        "'did anyone undercut on the pit stop?'."
    )
    required_args = _REQUIRED_ARGS
    tool_schema = {
        "type": "object",
        "properties": {
            "round_number": {"type": "integer", "description": "The 2026 season round number."},
        },
        "required": list(_REQUIRED_ARGS),
    }

    def execute(self, **args) -> dict:
        return f1_data.get_pit_stop_analysis(args["round_number"])

    def make_widget(self, result: dict) -> dict:
        return _build_pit_stop_strategy_widget(result)

    def should_show_widget(self, result: dict) -> bool:
        if not result.get("available", True):
            return False
        total_laps = result.get("total_laps") or 0
        if total_laps < 10:
            return False
        drivers = result.get("drivers") or []
        if len(drivers) < 3:
            return False
        compounds = {d.get("compound") for d in drivers if isinstance(d, dict)}
        stop_counts = {d.get("stop_count") for d in drivers if isinstance(d, dict)}
        # at least 2 drivers differ in compound OR stop_count
        if len(compounds) >= 2 or len(stop_counts) >= 2:
            return True
        return False
