"""Driver race story feature. Migrated from chat.py / tools.py / f1_data.py."""
from __future__ import annotations

import f1_data
from features.base import Feature, register_feature


_RELEVANT_KEYWORDS = (
    "race recap", "race story", "what happened", "walk me through",
    "tell me about", "summary", "recap", "how did", "race go",
    "sprint go", "sprint story",
)

_RELEVANT_MODES: frozenset[str] = frozenset()

_REQUIRED_ARGS = ("round_number", "driver_name")


@register_feature
class DriverRaceStoryFeature(Feature):
    name = "get_driver_race_story"
    applies_to = ("driver", "race_session")
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
        q = (question or "").lower()
        mode = (resolved or {}).get("analysis_mode")
        has_keyword = any(kw in q for kw in _RELEVANT_KEYWORDS)
        has_mode = mode in _RELEVANT_MODES
        if has_keyword and has_mode:
            return 0.85
        if has_keyword:
            return 0.65
        if has_mode:
            return 0.45
        return 0.0

    def execute(self, **args) -> dict:
        return f1_data.get_driver_race_story(
            args["round_number"],
            args["driver_name"],
            session_type=args.get("session_type", "R"),
        )

    def make_widget(self, result: dict) -> dict:
        import chat
        return chat._make_race_story_widget(result)

    def should_show_widget(self, result: dict) -> bool:
        return bool(result) and result.get("available", True) is not False
