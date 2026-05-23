"""Team circuit fit feature. Migrated from tools.py / f1_data.py."""
from __future__ import annotations

import f1_data
from features.base import Feature, register_feature


@register_feature
class TeamCircuitFitFeature(Feature):
    name = "analyze_team_circuit_fit"
    applies_to = ("team",)
    triggered_by_modes = frozenset({"team_circuit_fit"})
    description = (
        "PRIMITIVE TOOL. Derives a team's historical circuit-fit tendencies from real qualifying or race classifications. "
        "It compares the team's average result at each circuit archetype against that team's own season baseline, "
        "then reports over/under-performance by character, style verdict, and downforce level. "
        "Use for questions like 'what kind of tracks does Mercedes suit?', 'is McLaren better at high-speed circuits?', "
        "or 'does Ferrari historically overperform at late-braker tracks?'. This is not private setup data."
    )
    required_args = ("team_name",)
    tool_schema = {
        "type": "object",
        "properties": {
            "team_name": {"type": "string", "description": "Constructor name or close match, e.g. Mercedes, McLaren, Ferrari."},
            "years": {"type": "array", "items": {"type": "integer"}, "description": "Optional completed seasons. Defaults to the three seasons before the current year."},
            "session_type": {"type": "string", "description": "Q for qualifying fit or R for race fit. Defaults to Q."},
        },
        "required": ["team_name"],
    }

    def execute(self, **args) -> dict:
        return f1_data.analyze_team_circuit_fit(
            args["team_name"],
            args.get("years"),
            args.get("session_type", "Q"),
        )

    def make_widget(self, result: dict) -> dict:
        return {}

    def should_show_widget(self, result: dict) -> bool:
        return False
