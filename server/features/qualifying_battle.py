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


_REQUIRED_ARGS = ("round_number", "driver_a", "driver_b")


def _build_qualifying_battle_widget(result: dict) -> dict:
    energy_analysis = result.get("energy_analysis") or {}
    clipping_callout = energy_analysis.get("clipping_comparison")
    return {
        "type": "qualifying_battle",
        "title": f"{result.get('driver_a')} vs {result.get('driver_b')}",
        "event": result.get("event"),
        "session": result.get("compared_segment") or result.get("session"),
        "driver_a": result.get("driver_a"),
        "driver_b": result.get("driver_b"),
        "faster_driver": result.get("faster_driver"),
        "overall_gap_s": result.get("overall_gap_s"),
        "decisive_sector": result.get("decisive_sector"),
        "decisive_sector_gap_s": result.get("decisive_sector_gap_s"),
        "decisive_corner": result.get("decisive_corner"),
        "cause_type": result.get("cause_type"),
        "cause_explanation": result.get("cause_explanation"),
        "cause_explanations": result.get("cause_explanations") or [],
        "zone_summary": result.get("zone_summary"),
        "energy_relevant": result.get("energy_relevant"),
        "energy_reason": result.get("energy_reason"),
        "is_teammate_comparison": result.get("is_teammate_comparison") or False,
        "teammate_context": result.get("teammate_context"),
        "sector_comparison": result.get("sector_comparison"),
        "style_comparison": result.get("style_comparison"),
        "speed_trace": result.get("speed_trace") or [],
        "drs_states": [
            bool(p.get("drs_a_active") or p.get("drs_b_active"))
            for p in (result.get("speed_trace") or [])
        ],
        "track_map": result.get("track_map") or [],
        "focus_window_trace": result.get("focus_window_trace") or [],
        "grip_commitment": result.get("grip_commitment"),
        "clipping_callout": clipping_callout,
    }


@register_feature
class QualifyingBattleFeature(Feature):
    name = "analyze_qualifying_battle"
    applies_to = ("pair_of_drivers",)
    triggered_by_modes = frozenset({"driver_comparison"})
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
        # Mode-driven orchestration replaced keyword predicates. The Feature
        # ABC still requires this method; the agentic fallback path may call
        # it (returns 0 = "no opinion from this layer").
        return 0.0

    def execute(self, **args) -> dict:
        return f1_data.analyze_qualifying_battle(
            args["round_number"],
            args["driver_a"],
            args["driver_b"],
            session_type=args.get("session_type", "Q"),
        )

    def make_widget(self, result: dict) -> dict:
        return _build_qualifying_battle_widget(result)

    def should_show_widget(self, result: dict) -> bool:
        if not result.get("available", True):
            return False
        # Match legacy chat.py branch: it always appended the widget when a
        # result existed (no quality gate beyond availability).
        return True
