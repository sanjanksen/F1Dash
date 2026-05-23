"""Driver style profile feature. Migrated from tools.py."""
from __future__ import annotations

import logging

from features.base import Feature, register_feature

logger = logging.getLogger(__name__)


@register_feature
class DriverStyleProfileFeature(Feature):
    name = "get_driver_style_profile"
    applies_to = ("driver",)
    description = (
        "PRIMITIVE TOOL. Returns a driver's known driving style profile: corner approach (V-line vs U-line), "
        "steering consistency, braking commitment, apex style, throttle application, car preference "
        "(oversteer/understeer), and key telemetry signatures. Use this when analysing qualifying "
        "differences, corner profiles, or any question about how a driver attacks a corner. "
        "For a head-to-head comparison, call with both driver codes — the response includes a "
        "style_prediction describing where each driver should theoretically gain or lose."
    )
    required_args = ("driver_a",)
    tool_schema = {
        "type": "object",
        "properties": {
            "driver_a": {"type": "string", "description": "3-letter driver code (e.g. VER, NOR, PIA)."},
            "driver_b": {"type": "string", "description": "Optional second driver code for a head-to-head style comparison."},
        },
        "required": ["driver_a"],
    }

    def execute(self, **args) -> dict:
        from driver_styles import get_driver_style, get_comparison_framing
        driver_a = args["driver_a"]
        driver_b = args.get("driver_b")
        if driver_b:
            result = get_comparison_framing(driver_a, driver_b)
            if result is None:
                a = get_driver_style(driver_a)
                b = get_driver_style(driver_b)
                if a is None and b is None:
                    logger.warning(
                        "Missing driver_style profiles for both drivers in comparison: %r and %r — add entries to driver_styles.py",
                        driver_a, driver_b,
                    )
                    return {
                        "driver_a_query": driver_a,
                        "driver_b_query": driver_b,
                        "profile_type": "curated_editorial",
                        "available": False,
                        "caveat": "No curated style profiles are available for either driver.",
                        "guidance_for_model": (
                            "I do not have curated style profiles for either driver. "
                            "Do not invent traits — say the profiles are unavailable."
                        ),
                    }
                return {"driver_a": a, "driver_b": b}
            return result
        profile = get_driver_style(driver_a)
        if profile is None:
            logger.warning(
                "Missing driver_style profile for query=%r — add an entry to driver_styles.py",
                driver_a,
            )
            return {
                "driver_query": driver_a,
                "profile_type": "curated_editorial",
                "available": False,
                "caveat": "No curated style profile is available for this driver.",
                "guidance_for_model": (
                    "I do not have a curated style profile for this driver. "
                    "Do not invent traits — say the profile is unavailable."
                ),
            }
        return profile

    def make_widget(self, result: dict) -> dict:
        return {}

    def should_show_widget(self, result: dict) -> bool:
        return False
