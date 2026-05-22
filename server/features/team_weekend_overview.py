"""Team weekend overview feature. Migrated from tools.py / f1_data.py."""
from __future__ import annotations

import f1_data
from features.base import Feature, register_feature


_REQUIRED_ARGS = ("round_number", "team_name")


@register_feature
class TeamWeekendOverviewFeature(Feature):
    name = "get_team_weekend_overview"
    applies_to = ("team", "session")
    description = (
        "COMPOSITE RECAP TOOL. High-level weekend overview for a team across both drivers. "
        "Use this first for broad prompts like 'how did Ferrari do this weekend?'. "
        "Pass session_type='S' for a sprint weekend overview, session_type='R' (default) for the main race."
    )
    required_args = _REQUIRED_ARGS
    tool_schema = {
        "type": "object",
        "properties": {
            "round_number": {"type": "integer", "description": "The 2026 season round number."},
            "team_name": {"type": "string", "description": "Current constructor name or close match."},
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
        return f1_data.get_team_weekend_overview(
            args["round_number"],
            args["team_name"],
            session_type=args.get("session_type", "R"),
        )

    def make_widget(self, result: dict) -> dict:
        return {}

    def should_show_widget(self, result: dict) -> bool:
        return False
