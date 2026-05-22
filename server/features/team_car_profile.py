"""Team car profile feature. Migrated from tools.py."""
from __future__ import annotations

import logging

from features.base import Feature, register_feature

logger = logging.getLogger(__name__)


_RELEVANT_KEYWORDS = (
    "car characteristics", "car balance", "low-speed", "high-speed",
    "dirty air", "car profile", "team car", "car strength", "car weakness",
)


@register_feature
class TeamCarProfileFeature(Feature):
    name = "get_team_car_profile"
    applies_to = ("team",)
    description = (
        "PRIMITIVE TOOL. Dated, sourced public-reporting context about a team's car strengths or weaknesses. "
        "This is editorial context, not deterministic telemetry; use it only after or alongside data tools."
    )
    required_args = ("team_name",)
    tool_schema = {
        "type": "object",
        "properties": {
            "team_name": {"type": "string", "description": "Constructor name or close match."},
        },
        "required": ["team_name"],
    }

    def is_relevant_for(self, question: str, resolved: dict | None) -> float:
        q = (question or "").lower()
        return 0.65 if any(kw in q for kw in _RELEVANT_KEYWORDS) else 0.0

    def execute(self, **args) -> dict:
        from team_car_profiles import get_team_car_profile
        team_name = args["team_name"]
        profile = get_team_car_profile(team_name)
        if profile is None:
            logger.warning(
                "Missing team_car_profile for query=%r — add an entry to team_car_profiles.py",
                team_name,
            )
            return {
                "team_query": team_name,
                "profile_type": "curated_editorial",
                "available": False,
                "caveat": "No sourced public-reporting profile is currently curated for this team.",
                "guidance_for_model": (
                    "I do not have a curated car-character profile for this team. "
                    "Do not invent traits — say the profile is unavailable."
                ),
            }
        return profile

    def make_widget(self, result: dict) -> dict:
        return {}

    def should_show_widget(self, result: dict) -> bool:
        return False
