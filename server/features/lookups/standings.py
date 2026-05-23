"""Standings + season-wide stats lookup features."""
from __future__ import annotations

import f1_data
from features.base import Feature, register_feature


@register_feature
class DriverStandingsFeature(Feature):
    name = "get_driver_standings"
    applies_to = ()
    description = "PRIMITIVE TOOL. Current 2026 driver championship standings."
    required_args = ()
    tool_schema = {
        "type": "object",
        "properties": {
            "limit": {"type": "integer", "description": "Number of drivers to return (1-20). Defaults to 20."},
        },
        "required": [],
    }

    def execute(self, **args):
        return f1_data.get_drivers()[:args.get("limit", 20)]

    def make_widget(self, result):
        return {}

    def should_show_widget(self, result):
        return False


@register_feature
class ConstructorStandingsFeature(Feature):
    name = "get_constructor_standings"
    applies_to = ()
    description = "PRIMITIVE TOOL. Current 2026 constructor championship standings."
    required_args = ()
    tool_schema = {
        "type": "object",
        "properties": {},
        "required": [],
    }

    def execute(self, **args):
        return f1_data.get_constructor_standings()

    def make_widget(self, result):
        return {}

    def should_show_widget(self, result):
        return False


@register_feature
class DriverSeasonStatsFeature(Feature):
    name = "get_driver_season_stats"
    applies_to = ()
    description = "PRIMITIVE TOOL. Detailed 2026 season statistics for one driver."
    required_args = ("driver_name",)
    tool_schema = {
        "type": "object",
        "properties": {
            "driver_name": {"type": "string", "description": "Driver full name, surname, or 3-letter code."},
        },
        "required": ["driver_name"],
    }

    def execute(self, **args):
        stats = f1_data.get_driver_stats(args["driver_name"])
        if stats is None:
            raise ValueError(
                f"Driver not found: {args['driver_name']!r}. Try the driver's surname or 3-letter code."
            )
        return stats

    def make_widget(self, result):
        return {}

    def should_show_widget(self, result):
        return False
