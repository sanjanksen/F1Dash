"""Race cornering profile feature. Migrated from tools.py / f1_data.py."""
from __future__ import annotations

import f1_data
from features.base import Feature, register_feature


_RELEVANT_KEYWORDS = (
    "race cornering", "race corner profile", "cornering in the race",
    "race grip", "race-long grip", "race g-force", "race g force",
    "corner profile", "tyre stress",
)


@register_feature
class RaceCorneringProfileFeature(Feature):
    name = "analyze_race_cornering_profile"
    applies_to = ("pair_of_drivers", "session")
    description = (
        "DEEP ANALYSIS PRIMITIVE. Compute lateral G and grip utilisation aggregated across an ENTIRE RACE for two drivers. "
        "Processes every clean race lap (pit laps excluded) and returns overall summary stats plus a per-stint breakdown. "
        "Use this when asked about race-long grip usage, tyre stress, or who pushes harder through corners over a full race distance. "
        "Returns: avg corner grip utilisation %, % cornering time above 90% grip, corrections per corner, load variance per stint, "
        "combined grip utilisation % (lat+long vector), trail brake % at corner entry, "
        "GGV-based metrics: ggv_util_pct (empirical envelope utilisation), envelope_time_pct, "
        "throttle_acceptance_pct (exit bravery — full power under lateral load), "
        "entry_bravery_pct, bravery_score (0–100 composite) per stint and overall."
    )
    required_args = ("round_number", "driver_a", "driver_b")
    tool_schema = {
        "type": "object",
        "properties": {
            "round_number": {"type": "integer", "description": "The 2026 season round number."},
            "driver_a": {"type": "string", "description": "First driver's 3-letter code."},
            "driver_b": {"type": "string", "description": "Second driver's 3-letter code."},
        },
        "required": ["round_number", "driver_a", "driver_b"],
    }

    def is_relevant_for(self, question: str, resolved: dict | None) -> float:
        q = (question or "").lower()
        return 0.65 if any(kw in q for kw in _RELEVANT_KEYWORDS) else 0.0

    def execute(self, **args) -> dict:
        return f1_data.analyze_race_cornering_profile(
            args["round_number"],
            args["driver_a"],
            args["driver_b"],
        )

    def make_widget(self, result: dict) -> dict:
        return {}

    def should_show_widget(self, result: dict) -> bool:
        return False
