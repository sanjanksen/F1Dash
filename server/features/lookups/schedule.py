"""Season schedule lookup feature."""
from __future__ import annotations

import f1_data
from features.base import Feature, register_feature


_SCHEDULE_KEYWORDS = (
    "schedule", "calendar", "round", "race", "when", "next race",
    "last race", "latest race", "upcoming",
)


@register_feature
class SeasonScheduleFeature(Feature):
    name = "get_season_schedule"
    applies_to = ()
    description = (
        "PRIMITIVE TOOL. Full 2026 race calendar with rounds, event names, locations, "
        "countries, and dates."
    )
    required_args = ()
    tool_schema = {
        "type": "object",
        "properties": {},
        "required": [],
    }

    def is_relevant_for(self, question, resolved):
        q = (question or "").lower()
        return 0.65 if any(kw in q for kw in _SCHEDULE_KEYWORDS) else 0.0

    def execute(self, **args):
        return f1_data.get_circuits()

    def make_widget(self, result):
        return {}

    def should_show_widget(self, result):
        return False
