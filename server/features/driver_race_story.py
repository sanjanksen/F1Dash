"""Driver race story feature. Migrated from chat.py / tools.py / f1_data.py."""
from __future__ import annotations

import f1_data
from features.base import Feature, register_feature


_REQUIRED_ARGS = ("round_number", "driver_name")


def _build_race_story_widget(result: dict) -> dict:
    race = result.get("race") or {}
    qualifying = result.get("qualifying") or {}
    radio = result.get("radio_highlights") or []
    return {
        "type": "race_story",
        "title": result.get("driver"),
        "subtitle": result.get("event"),
        "driver_code": result.get("code"),
        "team": result.get("team"),
        "grid_position": race.get("grid_position") or qualifying.get("position"),
        "finish_position": race.get("finish_position"),
        "points": race.get("points"),
        "status": race.get("status"),
        "pit_stops": result.get("pit_stops") or [],
        "story_points": result.get("story_points") or [],
        "interval_summary": result.get("interval_summary"),
        "position_timeline_summary": result.get("position_timeline_summary"),
        "radio_highlights": radio[:3],
        "rivalry_story": result.get("rivalry_story") or [],
    }


@register_feature
class DriverRaceStoryFeature(Feature):
    name = "get_driver_race_story"
    applies_to = ("driver", "race_session")
    triggered_by_modes = frozenset({"driver_comparison"})
    description = (
        "COMPOSITE RECAP TOOL. Narrative-ready race or sprint story for one driver in one round. "
        "Use this first for broad prompts like 'how did Russell's race go?' or 'how did Norris do in the sprint?'. "
        "Pass session_type='S' for a sprint race story, session_type='R' (default) for the main race."
    )
    required_args = _REQUIRED_ARGS
    tool_schema = {
        "type": "object",
        "properties": {
            "round_number": {"type": "integer", "description": "The 2026 season round number."},
            "driver_name": {"type": "string", "description": "Driver full name, surname, or 3-letter code."},
            "session_type": {"type": "string", "description": "R (default, main race) or S (sprint race)."},
        },
        "required": list(_REQUIRED_ARGS),
    }

    def is_relevant_for(self, question: str, resolved: dict | None) -> float:
        # Mode-driven orchestration replaced keyword predicates. The Feature
        # ABC still requires this method; the agentic fallback path may call
        # it (returns 0 = "no opinion from this layer").
        return 0.0

    def execute(self, **args) -> dict:
        return f1_data.get_driver_race_story(
            args["round_number"],
            args["driver_name"],
            session_type=args.get("session_type", "R"),
        )

    def make_widget(self, result: dict) -> dict:
        return _build_race_story_widget(result)

    def should_show_widget(self, result: dict) -> bool:
        return bool(result) and result.get("available", True) is not False
