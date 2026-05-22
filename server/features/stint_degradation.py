"""Stint-degradation deep analysis feature. Migrated from chat.py / tools.py / f1_data.py."""
from __future__ import annotations

import f1_data
from features.base import Feature, register_feature


_REQUIRED_ARGS = ("round_number", "driver_code")


def _build_deg_trend_chart_widget(result: dict) -> dict:
    return {
        "type": "deg_trend_chart",
        "title": f"{result.get('driver')} — {result.get('event')} tyre degradation",
        "driver": result.get("driver"),
        "event": result.get("event"),
        "stints": [
            {
                "compound": s.get("compound"),
                "lap_count": s.get("lap_count"),
                "deg_rate_s_per_lap": s.get("deg_rate_s_per_lap"),
                "r_squared": s.get("r_squared"),
                "scatter_data": s.get("scatter_data") or [],
                "regression_line": s.get("regression_line") or [],
                "cliff_detected": s.get("cliff_detected", False),
                "cliff_tyre_age": s.get("cliff_tyre_age"),
                "cliff_slope_increase_s_per_lap": s.get("cliff_slope_increase_s_per_lap"),
                "cliff_severity_ratio": s.get("cliff_severity_ratio"),
                "pre_cliff_deg_rate_s_per_lap": s.get("pre_cliff_deg_rate_s_per_lap"),
                "post_cliff_deg_rate_s_per_lap": s.get("post_cliff_deg_rate_s_per_lap"),
                "pre_cliff_regression_line": s.get("pre_cliff_regression_line") or [],
                "post_cliff_regression_line": s.get("post_cliff_regression_line") or [],
                "cliff_confidence": s.get("cliff_confidence"),
            }
            for s in (result.get("stints") or [])
            if s.get("scatter_data") or s.get("regression_line")
        ],
    }


@register_feature
class StintDegradationFeature(Feature):
    name = "analyze_stint_degradation"
    applies_to = ("driver",)
    description = (
        "DEEP ANALYSIS PRIMITIVE. Compute tyre degradation model for a driver's race stints. "
        "Fits linear regression on fuel-corrected lap times vs tyre age per stint compound. "
        "Returns deg_rate_s_per_lap, fuel_corrected_pace_at_age_1_s, r_squared, consistency_std_dev_s, "
        "raw_pace_trend_s_per_lap, and a tyre_management summary. The raw trend is what the stopwatch did; "
        "deg_rate_s_per_lap adds back expected fuel-burn gain to estimate tyre performance loss. "
        "For tyre-management rankings, lower positive_deg_rate_s_per_lap is the primary signal; "
        "consistency_std_dev_s is lap-to-lap noise and r_squared is confidence/trust in the trend, not pace. "
        "Each stint also includes cliff_detected (bool), and when True: cliff_tyre_age, "
        "cliff_slope_increase_s_per_lap, cliff_severity_ratio, pre_cliff_deg_rate_s_per_lap, "
        "post_cliff_deg_rate_s_per_lap, and cliff_confidence. Use cliff_detected to flag stints where "
        "the tyre appears to have fallen out of the optimal window, producing a materially steeper degradation "
        "phase rather than staying linear. Do not infer graining, blistering, or thermal deg from this flag alone. "
        "Use for questions about tyre wear, degradation rate, tyre management, or how pace evolved over a stint."
    )
    required_args = _REQUIRED_ARGS
    tool_schema = {
        "type": "object",
        "properties": {
            "round_number": {"type": "integer"},
            "driver_code": {"type": "string"},
            "session_type": {"type": "string", "default": "R"},
        },
        "required": list(_REQUIRED_ARGS),
    }

    def is_relevant_for(self, question: str, resolved: dict | None) -> float:
        # Mode-driven orchestration replaced keyword predicates. The Feature
        # ABC still requires this method; the agentic fallback path may call
        # it (returns 0 = "no opinion from this layer").
        return 0.0

    def execute(self, **args) -> dict:
        return f1_data.analyze_stint_degradation(
            args["round_number"],
            args["driver_code"],
            args.get("session_type", "R"),
        )

    def make_widget(self, result: dict) -> dict:
        return _build_deg_trend_chart_widget(result)

    def should_show_widget(self, result: dict) -> bool:
        if not result.get("available", True):
            return False
        stints = result.get("stints") or []
        for stint in stints:
            if not isinstance(stint, dict):
                continue
            lap_count = stint.get("lap_count") or 0
            r2 = stint.get("r_squared")
            deg = stint.get("deg_rate_s_per_lap")
            if (lap_count >= 5
                    and r2 is not None and r2 >= 0.25
                    and deg is not None and abs(deg) >= 0.05):
                return True
        return False
