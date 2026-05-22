"""Race report feature. Migrated from tools.py / f1_data.py."""
from __future__ import annotations

import f1_data
from features.base import Feature, register_feature


_RELEVANT_KEYWORDS = (
    "race report", "race summary", "full race", "race recap",
    "tell me about the race", "what happened in the race",
    "recap the sprint", "recap the race", "what happened",
)

_RELEVANT_MODES: frozenset[str] = frozenset()

_REQUIRED_ARGS = ("round_number",)


@register_feature
class RaceReportFeature(Feature):
    name = "get_race_report"
    applies_to = ("race_session",)
    description = (
        "COMPOSITE RECAP TOOL. Whole-race or sprint recap independent of any one driver or team. "
        "Use this first for broad race recap prompts like 'what happened in the race?' or 'recap the sprint'. "
        "Pass session_type='S' for a sprint race recap, session_type='R' (default) for the main race."
    )
    required_args = _REQUIRED_ARGS
    tool_schema = {
        "type": "object",
        "properties": {
            "round_number": {"type": "integer", "description": "The 2026 season round number."},
            "session_type": {"type": "string", "description": "R (default, main race) or S (sprint race recap)."},
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
        return f1_data.get_race_report(
            args["round_number"],
            session_type=args.get("session_type", "R"),
        )

    def make_widget(self, result: dict) -> dict:
        return {}

    def should_show_widget(self, result: dict) -> bool:
        return False
