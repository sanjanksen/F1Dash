"""Unit tests for server/strategy_math.py — pure-math undercut/overcut model."""
import strategy_math
from strategy_math import (
    compute_undercut_window,
    compute_pit_loss_variants,
    VSC_PIT_LOSS_FRACTION,
    SC_PIT_LOSS_FRACTION,
)


def _snapshot(*, pit_loss=22.0, track_temp=35.0, current_compound="MEDIUM",
              tyre_age=18, deg_slope=0.06, base_pace=95.0, base_pace_new=93.5,
              next_compound="HARD", stint_laps_used=12,
              has_cliff=False, pre_cliff=None, post_cliff=None, cliff_age=None,
              cars=None, sc_state="green", gap=2.0, target=None):
    return {
        "pit_loss_s": pit_loss,
        "track_temp_c": track_temp,
        "driver": {
            "compound": current_compound,
            "tyre_age": tyre_age,
            "deg_slope": deg_slope,
            "base_pace": base_pace,
            "base_pace_new": base_pace_new,
            "next_compound": next_compound,
            "stint_laps_used": stint_laps_used,
            "has_cliff": has_cliff,
            "pre_cliff_slope": pre_cliff,
            "post_cliff_slope": post_cliff,
            "cliff_age": cliff_age,
        },
        "target": target,
        "gap_to_target_s": gap,
        "cars_in_rejoin_window": cars or [],
        "active_sc_state": sc_state,
    }


def test_clear_undercut_available():
    """Small pit_loss, big fresh-tyre delta, no traffic → pit_now."""
    # Worn pace ~95 + 0.10*25 = 97.5; fresh ~70 + 1.0 = 71; delta = ~26.5.
    snap = _snapshot(
        pit_loss=8.0, track_temp=40.0,
        current_compound="MEDIUM", tyre_age=25, deg_slope=0.10,
        base_pace=95.0, base_pace_new=70.0, next_compound="MEDIUM",
        stint_laps_used=20, cars=[],
    )
    result = compute_undercut_window("VER", 25, None, snap)
    assert result["advantage_s"] > 0
    assert result["recommendation"] == "pit_now"
    assert result["crossover_lap"] == 1
    assert result["undercut_available"] is True


def test_clear_overcut_overcut():
    """Singapore-style: huge pit_loss, tiny fresh delta → stay_out."""
    # Worn ~95 + 0.06*22 = 96.32; fresh ~93.9 + 1.6 = 95.5; delta=0.82s.
    snap = _snapshot(
        pit_loss=28.0, track_temp=31.0,
        current_compound="MEDIUM", tyre_age=22, deg_slope=0.06,
        base_pace=95.2, base_pace_new=93.9, next_compound="HARD",
        stint_laps_used=15, cars=[],
    )
    result = compute_undercut_window("NOR", 25, "VER", snap)
    assert result["advantage_s"] < -3.0
    assert result["recommendation"] == "stay_out"
    assert result["crossover_lap"] is None


def test_marginal_recommendation():
    """Close-to-zero advantage → marginal."""
    # Need advantage in (-3, 1) and not a pit_now scenario.
    snap = _snapshot(
        pit_loss=22.0, track_temp=35.0,
        current_compound="MEDIUM", tyre_age=20, deg_slope=0.05,
        base_pace=92.0, base_pace_new=71.5, next_compound="HARD",
        stint_laps_used=12, cars=[],
    )
    # worn = 92 + 0.05*20 = 93; fresh = 71.5 + 1.6 = 73.1; delta = 19.9
    # advantage at N=1 = 19.9 - 22 - 1.2 = -3.3 → tweak so it's marginal
    snap["driver"]["base_pace"] = 92.5
    # worn = 92.5 + 1.0 = 93.5; fresh = 73.1; delta = 20.4 → adv = 20.4 - 22 - 1.2 = -2.8
    result = compute_undercut_window("HAM", 20, None, snap)
    assert -3.0 < result["advantage_s"] < 1.0
    assert result["recommendation"] == "marginal"


def test_missing_target_driver():
    """target=None → no traffic_cost computed, still produces a valid result."""
    snap = _snapshot(target=None, cars=[])
    result = compute_undercut_window("RUS", 18, None, snap)
    assert result["target_driver_code"] is None
    assert result["traffic_cost_s"] == 0.0
    assert result["confidence"] in {"high", "moderate", "low"}
    assert isinstance(result["rationale"], list)


def test_cliff_detected_uses_post_cliff_slope():
    """current_tyre_age > cliff_age and has_cliff → post-cliff slope is used."""
    snap = _snapshot(
        tyre_age=22, has_cliff=True, cliff_age=18,
        pre_cliff=0.04, post_cliff=0.18, deg_slope=0.10,
        stint_laps_used=22,
    )
    result = compute_undercut_window("LEC", 22, None, snap)
    assert result["inputs_summary"]["deg_slope_source"] == "post_cliff"
    assert abs(result["inputs_summary"]["deg_slope_used_s_per_lap"] - 0.18) < 1e-6


def test_cool_track_hard_out_lap_penalty_increases():
    """track_temp_c < 30 and compound HARD → out_lap_warmup = 2.0s."""
    snap = _snapshot(track_temp=25.0, next_compound="HARD")
    result = compute_undercut_window("PIA", 12, None, snap)
    assert result["out_lap_warmup_s"] == 2.0


def test_sc_active_reduces_pit_loss_to_35_percent():
    """active_sc_state='sc' → effective pit-loss is 0.35× green."""
    snap = _snapshot(pit_loss=22.0, sc_state="sc")
    result = compute_undercut_window("VER", 30, None, snap)
    expected = round(22.0 * SC_PIT_LOSS_FRACTION, 2)
    assert result["pit_loss_s"] == expected
    assert result["active_sc_state"] == "sc"


def test_vsc_active_reduces_pit_loss_to_55_percent():
    """active_sc_state='vsc' → effective pit-loss is 0.55× green."""
    snap = _snapshot(pit_loss=22.0, sc_state="vsc")
    result = compute_undercut_window("VER", 30, None, snap)
    expected = round(22.0 * VSC_PIT_LOSS_FRACTION, 2)
    assert result["pit_loss_s"] == expected
    assert result["active_sc_state"] == "vsc"
    # And SC must give a smaller pit-loss than VSC.
    snap_sc = _snapshot(pit_loss=22.0, sc_state="sc")
    result_sc = compute_undercut_window("VER", 30, None, snap_sc)
    assert result_sc["pit_loss_s"] < result["pit_loss_s"]


def test_traffic_bound_rejoin_kills_advantage():
    """Slower cars in the rejoin window → positive traffic_cost, reduces advantage."""
    base_snap = _snapshot(
        pit_loss=10.0, current_compound="MEDIUM", tyre_age=20,
        base_pace=95.0, base_pace_new=80.0, next_compound="MEDIUM",
        stint_laps_used=15, cars=[],
    )
    base_result = compute_undercut_window("ALO", 20, None, base_snap)

    busy_snap = dict(base_snap)
    busy_snap["cars_in_rejoin_window"] = [
        {"code": "STR", "predicted_pace": base_result["inputs_summary"]["fresh_pace_s"] + 0.8},
        {"code": "OCO", "predicted_pace": base_result["inputs_summary"]["fresh_pace_s"] + 0.6},
    ]
    busy_result = compute_undercut_window("ALO", 20, None, busy_snap)
    assert busy_result["traffic_cost_s"] > 0
    assert busy_result["advantage_s"] < base_result["advantage_s"]


def test_clean_air_rejoin_zero_traffic_cost():
    """No cars in rejoin window → traffic_cost_s = 0."""
    snap = _snapshot(cars=[])
    result = compute_undercut_window("PIA", 14, None, snap)
    assert result["traffic_cost_s"] == 0.0


def test_compute_pit_loss_variants_returns_three_keys():
    """F19 helper must return green/vsc/sc with correct ratios."""
    result = compute_pit_loss_variants(20.0)
    assert set(result.keys()) == {"green", "vsc", "sc"}
    assert result["green"] == 20.0
    assert result["vsc"] == round(20.0 * VSC_PIT_LOSS_FRACTION, 2)
    assert result["sc"] == round(20.0 * SC_PIT_LOSS_FRACTION, 2)


def test_short_stint_falls_back_to_compound_typical():
    """Stint < 6 laps → compound-typical fallback + low confidence."""
    snap = _snapshot(
        stint_laps_used=4, deg_slope=0.99,  # implausible to confirm it's ignored
        current_compound="SOFT",
    )
    result = compute_undercut_window("BOR", 5, None, snap)
    assert result["inputs_summary"]["deg_slope_source"] == "compound_typical_fallback"
    # SOFT typical = 0.10
    assert abs(result["inputs_summary"]["deg_slope_used_s_per_lap"] - 0.10) < 1e-6
    assert result["confidence"] == "low"
