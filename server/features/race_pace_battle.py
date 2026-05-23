"""Race-pace-battle deep analysis feature. Migrated from chat.py / tools.py / f1_data.py."""
from __future__ import annotations

import f1_data
from features.base import Feature, register_feature


_REQUIRED_ARGS = ("round_number", "driver_a", "driver_b")


def _build_race_pace_battle_widget(result: dict) -> dict:
    aligned_stints = []
    for stint in result.get("aligned_stints") or []:
        stint_a = stint.get("driver_a") or stint.get("stint_a") or {}
        stint_b = stint.get("driver_b") or stint.get("stint_b") or {}
        laps_a = set(stint_a.get("lap_numbers") or [])
        laps_b = set(stint_b.get("lap_numbers") or [])
        overlap = len(laps_a & laps_b) if laps_a and laps_b else None
        aligned_stints.append({
            "compound": stint.get("compound"),
            "driver_a": stint_a,
            "driver_b": stint_b,
            "pace_delta_s": stint.get("pace_delta_s"),
            "deg_rate_delta": stint.get("deg_rate_delta"),
            "lap_overlap": overlap,
        })

    return {
        "type": "race_pace_battle",
        "title": f"{result.get('driver_a')} vs {result.get('driver_b')}",
        "event": result.get("event"),
        "session": result.get("session"),
        "driver_a": result.get("driver_a"),
        "driver_b": result.get("driver_b"),
        "fuel_corrected_pace_a_s": result.get("fuel_corrected_pace_a_s"),
        "fuel_corrected_pace_b_s": result.get("fuel_corrected_pace_b_s"),
        "overall_pace_delta_s": result.get("overall_pace_delta_s"),
        "avg_deg_rate_a_s_per_lap": result.get("avg_deg_rate_a_s_per_lap"),
        "avg_deg_rate_b_s_per_lap": result.get("avg_deg_rate_b_s_per_lap"),
        "tyre_management_a": result.get("tyre_management_a"),
        "tyre_management_b": result.get("tyre_management_b"),
        "deg_rate_delta": result.get("deg_rate_delta"),
        "decisive_factor": result.get("decisive_factor"),
        "aligned_stints": aligned_stints,
        "undercut_opportunity": result.get("undercut_opportunity"),
        "clipping_callout": result.get("clipping_comparison"),
        "clipping_segments_a": (result.get("clipping_signature_a") or {}).get("segments") or [],
        "clipping_segments_b": (result.get("clipping_signature_b") or {}).get("segments") or [],
        "total_clipping_seconds_a": (result.get("clipping_signature_a") or {}).get("total_clipping_seconds"),
        "total_clipping_seconds_b": (result.get("clipping_signature_b") or {}).get("total_clipping_seconds"),
    }


@register_feature
class RacePaceBattleFeature(Feature):
    name = "analyze_race_pace_battle"
    applies_to = ("pair_of_drivers", "race_session")
    triggered_by_modes = frozenset({"race_pace_comparison", "driver_comparison"})
    description = (
        "DEEP ANALYSIS PRIMITIVE. Compare race pace and tyre degradation between two drivers. "
        "Race equivalent of analyze_qualifying_battle. Returns fuel-corrected pace delta, "
        "per-compound degradation rate comparison, aligned stints, decisive_factor classification "
        "(tyre_degradation/raw_pace_advantage/strategy_execution/mixed), tyre_management summaries with deg rate, "
        "consistency, and R², and undercut analysis. "
        "Use for questions like 'who had better race pace?' or 'why did Verstappen pull away from Hamilton in the race?'."
    )
    required_args = _REQUIRED_ARGS
    tool_schema = {
        "type": "object",
        "properties": {
            "round_number": {"type": "integer"},
            "driver_a": {"type": "string"},
            "driver_b": {"type": "string"},
            "session_type": {"type": "string", "default": "R"},
        },
        "required": list(_REQUIRED_ARGS),
    }

    def execute(self, **args) -> dict:
        return f1_data.analyze_race_pace_battle(
            args["round_number"],
            args["driver_a"],
            args["driver_b"],
            args.get("session_type", "R"),
        )

    def make_widget(self, result: dict) -> dict:
        return _build_race_pace_battle_widget(result)

    def should_show_widget(self, result: dict) -> bool:
        if not result.get("available", True):
            return False
        # Require at least one compound-matched stint pair with >= 3 overlapping
        # laps. Cross-compound comparisons aren't meaningful per the underlying
        # analyzer, so aligned_stints is the right denominator.
        aligned = result.get("aligned_stints") or []
        best_overlap = 0
        for stint in aligned:
            stint_a = stint.get("stint_a") or stint.get("driver_a") or {}
            stint_b = stint.get("stint_b") or stint.get("driver_b") or {}
            laps_a = set(stint_a.get("lap_numbers") or [])
            laps_b = set(stint_b.get("lap_numbers") or [])
            if laps_a and laps_b:
                best_overlap = max(best_overlap, len(laps_a & laps_b))
        if aligned and best_overlap < 3:
            return False
        overall = result.get("overall_pace_delta_s")
        deg = result.get("deg_rate_delta")
        if overall is None and deg is None:
            return False
        overall_material = overall is not None and abs(overall) >= 0.15
        deg_material = deg is not None and abs(deg) >= 0.05
        return overall_material or deg_material
