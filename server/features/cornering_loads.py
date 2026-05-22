"""Cornering loads (qualifying / single-lap) feature. Migrated from tools.py / f1_data.py.

Note: cross-feature. The chat layer merges _make_grip_commitment_summary
into the qualifying_battle widget; this feature does not emit its own
widget. It is registered for tool dispatch and audit purposes.
"""
from __future__ import annotations

import f1_data
from features.base import Feature, register_feature


@register_feature
class CorneringLoadsFeature(Feature):
    name = "analyze_cornering_loads"
    applies_to = ("pair_of_drivers", "session")
    triggered_by_modes = frozenset({"grip_comparison", "driver_comparison"})
    description = (
        "DEEP ANALYSIS PRIMITIVE. Compute lateral G and grip utilisation for two drivers across all corners of their fastest laps, "
        "using curvature derived from X/Y position telemetry. Returns per-corner stats (peak G, apex G, load variance, "
        "steering correction count, % time above 90% theoretical grip) plus an overall summary and a human-readable narrative. "
        "Also returns GGV-based metrics derived from the session's empirical grip envelope (not a theoretical formula): "
        "ggv_util_pct (% of the car's demonstrated grip ellipse used, combining lat + long), "
        "envelope_time_pct (% of cornering time within 15% of the empirical limit), "
        "throttle_acceptance_pct (% of corner exits where full throttle is applied while still laterally loaded — the bravery metric), "
        "entry_bravery_pct (% of entries near the combined limit while still braking), "
        "bravery_score (composite 0–100). "
        "Use this for qualifying / single-lap grip style and bravery comparisons."
    )
    required_args = ("round_number", "session_type", "driver_a", "driver_b")
    tool_schema = {
        "type": "object",
        "properties": {
            "round_number": {"type": "integer", "description": "The 2026 season round number."},
            "session_type": {"type": "string", "description": "Session type: Q, R, FP1, FP2, FP3, S, SQ, SS."},
            "driver_a": {"type": "string", "description": "First driver's 3-letter code."},
            "driver_b": {"type": "string", "description": "Second driver's 3-letter code."},
            "lap_number_a": {"type": "integer", "description": "Optional specific lap number for driver_a."},
            "lap_number_b": {"type": "integer", "description": "Optional specific lap number for driver_b."},
        },
        "required": ["round_number", "session_type", "driver_a", "driver_b"],
    }

    def is_relevant_for(self, question: str, resolved: dict | None) -> float:
        # Mode-driven orchestration replaced keyword predicates. The Feature
        # ABC still requires this method; the agentic fallback path may call
        # it (returns 0 = "no opinion from this layer").
        return 0.0

    def execute(self, **args) -> dict:
        return f1_data.analyze_cornering_loads(
            args["round_number"],
            args["session_type"],
            args["driver_a"],
            args["driver_b"],
            args.get("lap_number_a"),
            args.get("lap_number_b"),
        )

    def make_widget(self, result: dict) -> dict:
        # Cross-feature: the chat layer merges grip_commitment into qualifying_battle.
        return {}

    def should_show_widget(self, result: dict) -> bool:
        # cornering_loads contributes grip_commitment to qualifying_battle widget
        # via cross-feature merge in chat.py. The standalone corner_analysis widget
        # is also emitted by chat.py's composer (only when no qualifying widget
        # is present). This Feature's own widget contribution is None.
        return False
