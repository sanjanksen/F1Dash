"""Team performance feature. Migrated from chat.py / tools.py / f1_data.py.

Widget special case: the legacy branch passed the result's `corner_comparison`
subkey into `_make_corner_comparison_widget`, not the whole result.
"""
from __future__ import annotations

import f1_data
from features.base import Feature, register_feature


_RELEVANT_KEYWORDS = (
    "team performance", "team analysis", "team comparison",
    "both drivers", "which teammate", "team-wide", "team setup",
    "teammates", "as a team",
)

_RELEVANT_MODES: frozenset[str] = frozenset()

_REQUIRED_ARGS = ("round_number", "team_name", "session_type")


@register_feature
class TeamPerformanceFeature(Feature):
    name = "analyze_team_performance"
    applies_to = ("team", "session")
    description = (
        "DEEP ANALYSIS PRIMITIVE. Compare both teammates' corner profiles and (in race sessions) degradation for a team. "
        "Returns setup_direction_inference, gain_location_summary, and per-driver stint degradation. "
        "Use for questions like 'how did Ferrari compare as a team?' or 'which teammate was stronger in the corners?'."
    )
    required_args = _REQUIRED_ARGS
    tool_schema = {
        "type": "object",
        "properties": {
            "round_number": {"type": "integer", "description": "The 2026 season round number."},
            "team_name": {"type": "string", "description": "Team name or close match (e.g. Ferrari, McLaren, Mercedes)."},
            "session_type": {"type": "string", "description": "Session type: Q, R, FP1, FP2, FP3, S, SQ, SS."},
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
        return f1_data.analyze_team_performance(
            args["round_number"],
            args["team_name"],
            args["session_type"],
        )

    def make_widget(self, result: dict) -> dict:
        from features.corner_profiles import _build_corner_comparison_widget
        return _build_corner_comparison_widget(result["corner_comparison"])

    def should_show_widget(self, result: dict) -> bool:
        return isinstance(result.get("corner_comparison"), dict)
