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

    def is_relevant_for(self, question: str, resolved: dict | None) -> float:
        # Mode-driven orchestration replaced keyword predicates. The Feature
        # ABC still requires this method; the agentic fallback path may call
        # it (returns 0 = "no opinion from this layer").
        return 0.0

    def execute(self, **args) -> dict:
        return f1_data.get_pit_stop_analysis(args["round_number"])

    def make_widget(self, result: dict) -> dict:
        return _build_pit_stop_strategy_widget(result)

    def should_show_widget(self, result: dict) -> bool:
        return bool(result) and result.get("available", True) is not False
