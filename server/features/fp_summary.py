"""Free practice summary feature. Migrated from tools.py / f1_data.py."""
from __future__ import annotations

import f1_data
from features.base import Feature, register_feature


_REQUIRED_ARGS = ("round_number", "fp_number")


@register_feature
class FpSummaryFeature(Feature):
    name = "get_fp_summary"
    applies_to = ("practice_session",)
    description = (
        "PRIMITIVE TOOL. Free practice session summary with stint classification. "
        "Each driver's stints are labelled long_run (8+ laps same compound, race-pace sim), "
        "quali_sim (1-2 laps on fresh soft, best single-lap pace), short_run (setup/balance), "
        "or installation (first pit-out lap). Returns best_lap_time_s, best_lap_compound, "
        "speed_st, long_run_count, quali_sim_count per driver, sorted fastest to slowest. "
        "Includes session_notes explaining fuel load and programme-type caveats. "
        "Use for any FP1/FP2/FP3 question: fastest driver, programme analysis, race pace estimation."
    )
    required_args = _REQUIRED_ARGS
    tool_schema = {
        "type": "object",
        "properties": {
            "round_number": {"type": "integer", "description": "The 2026 season round number."},
            "fp_number": {"type": "integer", "description": "Free practice number: 1, 2, or 3."},
        },
        "required": list(_REQUIRED_ARGS),
    }

    def is_relevant_for(self, question: str, resolved: dict | None) -> float:
        # Mode-driven orchestration replaced keyword predicates. The Feature
        # ABC still requires this method; the agentic fallback path may call
        # it (returns 0 = "no opinion from this layer").
        return 0.0

    def execute(self, **args) -> dict:
        return f1_data.get_fp_summary(
            args["round_number"],
            args["fp_number"],
        )

    def make_widget(self, result: dict) -> dict:
        return {}

    def should_show_widget(self, result: dict) -> bool:
        return False
