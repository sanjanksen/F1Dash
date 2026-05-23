"""Season schedule lookup feature."""
from __future__ import annotations

import f1_data
from features.base import Feature, register_feature


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

    def execute(self, **args):
        return f1_data.get_circuits()

    def make_widget(self, result):
        return {}

    def should_show_widget(self, result):
        return False
