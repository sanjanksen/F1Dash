"""Undercut/overcut deep analysis feature. Migrated from chat.py / tools.py / f1_data.py."""
from __future__ import annotations

import f1_data
from features.base import Feature, register_feature


_REQUIRED_ARGS = ("driver_code", "lap_number")


def _build_undercut_overcut_widget(result: dict) -> dict:
    """Map an analyze_undercut_overcut tool result to a UI widget dict."""
    return {
        "type": "undercut_overcut",
        "driver_code": result.get("driver_code"),
        "target_driver_code": result.get("target_driver_code"),
        "current_lap": result.get("current_lap"),
        "event": result.get("event"),
        "round_number": result.get("round_number"),
        "session_type": result.get("session_type"),
        "advantage_s": result.get("advantage_s"),
        "crossover_lap": result.get("crossover_lap"),
        "recommendation": result.get("recommendation"),
        "confidence": result.get("confidence"),
        "active_sc_state": result.get("active_sc_state"),
        "pit_loss_s": result.get("pit_loss_s"),
        "pit_loss_green_s": result.get("pit_loss_green_s"),
        "delta_fresh_pace_s_per_lap": result.get("delta_fresh_pace_s_per_lap"),
        "out_lap_warmup_s": result.get("out_lap_warmup_s"),
        "traffic_cost_s": result.get("traffic_cost_s"),
        "advantage_by_rejoin_lap": result.get("advantage_by_rejoin_lap") or [],
        "rationale": result.get("rationale") or [],
        "inputs_summary": result.get("inputs_summary") or {},
    }


@register_feature
class UndercutOvercutFeature(Feature):
    name = "analyze_undercut_overcut"
    applies_to = ("driver", "race_session")
    description = (
        "PRIMITIVE TOOL. Quantitative undercut/overcut calculator. Use whenever the user "
        "asks 'should X have pitted', 'was the undercut on', 'would the overcut have worked', "
        "or any variant of 'should they pit now'. Returns advantage in seconds, crossover lap, "
        "and a pit_now/stay_out/marginal recommendation. "
        "Do NOT use this for general race-pace questions — use analyze_race_pace_battle."
    )
    required_args = _REQUIRED_ARGS
    tool_schema = {
        "type": "object",
        "properties": {
            "driver_code": {"type": "string"},
            "lap_number": {"type": "integer"},
            "target_driver_code": {"type": "string"},
            "round_number": {"type": "integer"},
            "session_type": {"type": "string", "default": "R"},
        },
        "required": list(_REQUIRED_ARGS),
    }

    def execute(self, **args) -> dict:
        round_number = args.get("round_number")
        if round_number is None:
            from f1_data import get_circuits
            circuits = get_circuits()
            if circuits:
                round_number = circuits[-1].get("round")
        if round_number is None:
            raise ValueError("analyze_undercut_overcut requires round_number when no schedule is available.")
        return f1_data.analyze_undercut_overcut(
            args["driver_code"],
            args["lap_number"],
            int(round_number),
            args.get("target_driver_code"),
            args.get("session_type", "R"),
        )

    def make_widget(self, result: dict) -> dict:
        return _build_undercut_overcut_widget(result)

    def should_show_widget(self, result: dict) -> bool:
        if not result.get("available", True):
            return False
        pit_loss = result.get("pit_loss_s")
        if pit_loss is None or pit_loss <= 0:
            return False
        rejoin_laps = result.get("advantage_by_rejoin_lap") or []
        if len(rejoin_laps) < 2:
            return False
        advantage = result.get("advantage_s")
        if advantage is None or abs(advantage) < 0.5:
            return False
        return True
