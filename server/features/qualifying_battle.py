"""Qualifying-battle deep analysis feature. Migrated from chat.py / tools.py / f1_data.py.

This feature has cross-feature orchestration in chat.py's evidence composer
(it merges grip_commitment from analyze_cornering_loads). The cross-feature
branch stays on the legacy if/elif path — chat.py's _CROSS_FEATURE_TOOLS set
makes _registry_widget skip this tool. The Feature class is therefore
registered but dormant for the cross-feature case; Phase E will unify.
"""
from __future__ import annotations

import f1_data
from features.base import Feature, register_feature


_RELEVANT_KEYWORDS = (
    "qualifying", "quali", "q3", "q2", "q1", "pole", "battle",
)

_RELEVANT_MODES = frozenset({"qualifying_battle"})

_REQUIRED_ARGS = ("round_number", "driver_a", "driver_b")


@register_feature
class QualifyingBattleFeature(Feature):
    name = "analyze_qualifying_battle"
    applies_to = ("pair_of_drivers",)
    description = (
        "DEEP ANALYSIS PRIMITIVE. Backend-derived causal summary for a qualifying battle between two drivers. "
        "Use this for questions like 'why was Leclerc faster than Norris in quali?' when you need where and why the gap happened, not just the final times. "
        "Pass session_type='SQ' for sprint qualifying/shootout."
    )
    required_args = _REQUIRED_ARGS
    tool_schema = {
        "type": "object",
        "properties": {
            "round_number": {"type": "integer"},
            "driver_a": {"type": "string"},
            "driver_b": {"type": "string"},
            "session_type": {"type": "string", "default": "Q"},
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
        return f1_data.analyze_qualifying_battle(
            args["round_number"],
            args["driver_a"],
            args["driver_b"],
            session_type=args.get("session_type", "Q"),
        )

    def make_widget(self, result: dict) -> dict:
        import chat
        return chat._make_qualifying_battle_widget(result)

    def should_show_widget(self, result: dict) -> bool:
        if not result.get("available", True):
            return False
        # Match legacy chat.py branch: it always appended the widget when a
        # result existed (no quality gate beyond availability).
        return True
