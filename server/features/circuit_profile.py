"""Circuit profile feature. Migrated from tools.py / chat.py.

Note: this feature is cross-feature in chat.py (the legacy widget composer
passes a track_map alongside the result). It is registered here so the
registry is the source of truth for discovery/dispatch, but chat.py's
_CROSS_FEATURE_TOOLS set keeps it on the legacy widget path for now.
"""
from __future__ import annotations

from features.base import Feature, register_feature


def _build_circuit_profile_widget(result: dict) -> dict:
    """Builds a circuit_profile widget. If `result` carries a `track_map`
    key (cross-feature injection from get_circuit_track_map), it is attached
    to the widget."""
    widget = {
        "type": "circuit_profile",
        "circuit_name": result.get("circuit_name"),
        "circuit_key": result.get("circuit_key"),
        "character": result.get("character"),
        "downforce_level": result.get("downforce_level"),
        "sector_1": result.get("sector_1"),
        "sector_2": result.get("sector_2"),
        "sector_3": result.get("sector_3"),
        "energy_profile": result.get("energy_profile"),
        "style_verdict": result.get("style_verdict"),
        "tyre_challenge": result.get("tyre_challenge"),
        "narrative": result.get("narrative"),
    }
    track_map = result.get("track_map")
    if track_map:
        widget["track_map"] = track_map
    return widget


@register_feature
class CircuitProfileFeature(Feature):
    name = "get_circuit_profile"
    applies_to = ("session",)
    triggered_by_modes = frozenset({"circuit_profile"})
    description = (
        "PRIMITIVE TOOL. Returns a structured knowledge profile for a circuit: character (power/technical/street), "
        "per-sector types and style advantages (V-line vs U-line vs late-braker), energy deployment demand, "
        "clipping risk, tyre challenge, and a narrative summary. "
        "Use before or alongside telemetry analysis to contextualise WHY a gap opened in a specific sector. "
        "For example: if Sector 2 is 'high_speed_sweepers' with 'u_line_favored', a minimum-speed advantage "
        "in that sector is structurally expected for a U-line driver."
    )
    required_args = ("country",)
    tool_schema = {
        "type": "object",
        "properties": {
            "country": {"type": "string", "description": "Country name for the circuit (e.g. Japan, Italy, Azerbaijan)."},
            "event_name": {"type": "string", "description": "Optional event name to disambiguate (e.g. Miami, United States Grand Prix)."},
        },
        "required": ["country"],
    }

    def execute(self, **args) -> dict:
        from circuit_profiles import get_circuit_profile
        profile = get_circuit_profile(args["country"], args.get("event_name", ""))
        if profile is None:
            raise ValueError(f"No circuit profile found for country={args['country']!r}.")
        return profile

    def make_widget(self, result: dict) -> dict:
        return _build_circuit_profile_widget(result)

    def should_show_widget(self, result: dict) -> bool:
        if not result.get("available", True):
            return False
        required_top = ("circuit_name", "downforce_level", "character")
        if any(not result.get(k) for k in required_top):
            return False
        optional = ("sector_1", "sector_2", "sector_3", "tyre_challenge", "style_verdict")
        present = sum(1 for k in optional if result.get(k))
        return present >= 2
