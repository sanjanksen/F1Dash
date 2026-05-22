"""Race-pace-battle deep analysis feature. Migrated from chat.py / tools.py / f1_data.py."""
from __future__ import annotations

import f1_data
from features.base import Feature, register_feature


_RELEVANT_KEYWORDS = (
    "race pace", "pace", "stint pace", "tyre pace", "pulled away", "pull away",
)

_RELEVANT_MODES = frozenset({"race_pace_comparison"})

_REQUIRED_ARGS = ("round_number", "driver_a", "driver_b")


@register_feature
class RacePaceBattleFeature(Feature):
    name = "analyze_race_pace_battle"
    applies_to = ("pair_of_drivers",)
    description = (
        "DEEP ANALYSIS PRIMITIVE. Compare race pace and tyre degradation between two drivers. "
        "Race equivalent of analyze_qualifying_battle. Returns fuel-corrected pace delta, "
        "per-compound degradation rate comparison, aligned stints, decisive_factor classification "
        "(tyre_degradation/raw_pace_advantage/strategy_execution/mixed), tyre_management summaries with deg rate, "
        "consistency, and R², and undercut analysis. "
        "Use for questions like 'who had better race pace?' or 'why did Verstappen pull away from Hamilton in the race?'."
    )
    required_args = _REQUIRED_ARGS
    tool_schema = {
        "type": "object",
        "properties": {
            "round_number": {"type": "integer"},
            "driver_a": {"type": "string"},
            "driver_b": {"type": "string"},
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
        return f1_data.analyze_race_pace_battle(
            args["round_number"],
            args["driver_a"],
            args["driver_b"],
            args.get("session_type", "R"),
        )

    def make_widget(self, result: dict) -> dict:
        import chat
        return chat._make_race_pace_battle_widget(result)

    def should_show_widget(self, result: dict) -> bool:
        if not result.get("available", True):
            return False
        # Legacy branch always appended this widget when present.
        return True
