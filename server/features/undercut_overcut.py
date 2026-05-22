"""Undercut/overcut deep analysis feature. Migrated from chat.py / tools.py / f1_data.py."""
from __future__ import annotations

import f1_data
from features.base import Feature, register_feature


_RELEVANT_KEYWORDS = (
    "undercut", "overcut", "pit window", "pit timing", "should they pit",
    "should he pit", "should she pit", "should pit",
)

_RELEVANT_MODES: frozenset[str] = frozenset()

_REQUIRED_ARGS = ("driver_code", "lap_number")


@register_feature
class UndercutOvercutFeature(Feature):
    name = "analyze_undercut_overcut"
    applies_to = ("driver", "race_session")
    description = (
        "PRIMITIVE TOOL. Quantitative undercut/overcut calculator. Use whenever the user "
        "asks 'should X have pitted', 'was the undercut on', 'would the overcut have worked', "
        "or any variant of 'should they pit now'. Returns advantage in seconds, crossover lap, "
        "and a pit_now/stay_out/marginal recommendation. "
        "Do NOT use this for general race-pace questions — use analyze_race_pace_battle."
    )
    required_args = _REQUIRED_ARGS
    tool_schema = {
        "type": "object",
        "properties": {
            "driver_code": {"type": "string"},
            "lap_number": {"type": "integer"},
            "target_driver_code": {"type": "string"},
            "round_number": {"type": "integer"},
            "session_type": {"type": "string", "default": "R"},
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
        round_number = args.get("round_number")
        if round_number is None:
            from f1_data import get_circuits
            circuits = get_circuits()
            if circuits:
                round_number = circuits[-1].get("round")
        if round_number is None:
            raise ValueError("analyze_undercut_overcut requires round_number when no schedule is available.")
        return f1_data.analyze_undercut_overcut(
            args["driver_code"],
            args["lap_number"],
            int(round_number),
            args.get("target_driver_code"),
            args.get("session_type", "R"),
        )

    def make_widget(self, result: dict) -> dict:
        import chat
        return chat._make_undercut_overcut_widget(result)

    def should_show_widget(self, result: dict) -> bool:
        # Legacy branch always appended the widget unconditionally.
        if not result.get("available", True):
            return False
        return True
