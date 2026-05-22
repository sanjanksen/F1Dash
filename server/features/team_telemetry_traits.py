"""Team telemetry traits feature. Migrated from tools.py / f1_data.py."""
from __future__ import annotations

import f1_data
from features.base import Feature, register_feature


_RELEVANT_KEYWORDS = (
    "team trait", "team style", "team dna", "car signature",
    "team telemetry", "telemetry trait", "car trait",
)


@register_feature
class TeamTelemetryTraitsFeature(Feature):
    name = "analyze_team_telemetry_traits"
    applies_to = ("team",)
    triggered_by_modes = frozenset({"team_circuit_fit"})
    description = (
        "PRIMITIVE TOOL. Session-specific telemetry characterization for a team's current car behavior. "
        "Compares the team's fastest-lap corner/straight traits against the field median: apex speed, exit speed, "
        "braking point, straight-line speed, full throttle, braking, and coasting. "
        "Use with analyze_team_circuit_fit when a specific round/session is known."
    )
    required_args = ("round_number", "team_name")
    tool_schema = {
        "type": "object",
        "properties": {
            "round_number": {"type": "integer", "description": "The 2026 season round number."},
            "team_name": {"type": "string", "description": "Constructor name or close match."},
            "session_type": {"type": "string", "description": "Q, R, FP1, FP2, FP3, S, SQ, SS. Defaults to Q."},
            "field_limit": {"type": "integer", "description": "Fastest field sample size. Defaults to 10."},
        },
        "required": ["round_number", "team_name"],
    }

    def is_relevant_for(self, question: str, resolved: dict | None) -> float:
        q = (question or "").lower()
        return 0.65 if any(kw in q for kw in _RELEVANT_KEYWORDS) else 0.0

    def execute(self, **args) -> dict:
        return f1_data.analyze_team_telemetry_traits(
            args["round_number"],
            args["team_name"],
            args.get("session_type", "Q"),
            args.get("field_limit", 10),
        )

    def make_widget(self, result: dict) -> dict:
        return {}

    def should_show_widget(self, result: dict) -> bool:
        return False
