"""Circuit profile feature. Migrated from tools.py / chat.py.

Note: this feature is cross-feature in chat.py (the legacy widget composer
passes a track_map alongside the result). It is registered here so the
registry is the source of truth for discovery/dispatch, but chat.py's
_CROSS_FEATURE_TOOLS set keeps it on the legacy widget path for now.
"""
from __future__ import annotations

from features.base import Feature, register_feature


_RELEVANT_KEYWORDS = (
    "circuit", "track", "layout", "downforce", "character", "sectors",
    "circuit profile", "track profile",
)


@register_feature
class CircuitProfileFeature(Feature):
    name = "get_circuit_profile"
    applies_to = ("session",)
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

    def is_relevant_for(self, question: str, resolved: dict | None) -> float:
        q = (question or "").lower()
        return 0.65 if any(kw in q for kw in _RELEVANT_KEYWORDS) else 0.0

    def execute(self, **args) -> dict:
        from circuit_profiles import get_circuit_profile
        profile = get_circuit_profile(args["country"], args.get("event_name", ""))
        if profile is None:
            raise ValueError(f"No circuit profile found for country={args['country']!r}.")
        return profile

    def make_widget(self, result: dict) -> dict:
        import chat
        return chat._make_circuit_profile_widget(result)

    def should_show_widget(self, result: dict) -> bool:
        return bool(result) and result.get("available", True) is not False
