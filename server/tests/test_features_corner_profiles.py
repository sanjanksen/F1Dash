from unittest.mock import patch

import pytest

pytestmark = pytest.mark.usefixtures("reset_feature_registry")


def _load_feat():
    from features.base import FEATURE_REGISTRY
    from features.registry import discover_features
    FEATURE_REGISTRY.clear()
    discover_features()
    return FEATURE_REGISTRY["compare_corner_profiles"]


def test_corner_profiles_registered_after_discover():
    from features.base import FEATURE_REGISTRY
    from features.registry import discover_features
    FEATURE_REGISTRY.clear()
    discover_features()
    assert "compare_corner_profiles" in FEATURE_REGISTRY


def test_corner_profiles_applies_to_pair_of_drivers():
    feat = _load_feat()
    assert "pair_of_drivers" in feat.applies_to


def test_corner_profiles_make_widget_produces_typed_widget():
    feat = _load_feat()
    sample = {"driver_a": "NOR", "driver_b": "LEC", "event": "Imola"}
    w = feat.make_widget(sample)
    assert w["type"] == "corner_comparison"
    assert w["driver_a"] == "NOR"
    assert w["driver_b"] == "LEC"


def test_corner_profiles_should_show_widget_respects_availability():
    feat = _load_feat()
    sample = {
        "driver_a": "NOR",
        "gain_location_summary": [{"corner": "T1"}],
        "total_time_gained_s": 0.18,
    }
    assert feat.should_show_widget(sample) is True
    assert feat.should_show_widget({"available": False}) is False


def test_corner_profiles_should_show_widget_meaningful_signal():
    feat = _load_feat()
    # Speed delta ≥ 2 kph: speed_material is True regardless of total gain.
    sample = {
        "available": True,
        "gain_location_summary": [{"corner": "T3"}, {"corner": "T7"}],
        "avg_straight_speed_a_kph": 312.0,
        "avg_straight_speed_b_kph": 308.0,
        "total_time_gained_s": 0.02,
    }
    assert feat.should_show_widget(sample) is True


def test_corner_profiles_should_show_widget_meaningful_time_gained_only():
    """Even with sub-threshold straight-speed delta, a material total_time_gained_s
    must surface the widget."""
    feat = _load_feat()
    sample = {
        "available": True,
        "gain_location_summary": [{"corner": "T3"}],
        "avg_straight_speed_a_kph": 311.0,
        "avg_straight_speed_b_kph": 310.5,
        "total_time_gained_s": 0.12,
    }
    assert feat.should_show_widget(sample) is True


def test_corner_profiles_should_show_widget_suppresses_negligible():
    feat = _load_feat()
    # gain locations present but speed delta < 2 kph and |total time gained| < 0.05s
    sample = {
        "available": True,
        "gain_location_summary": [{"corner": "T3"}],
        "avg_straight_speed_a_kph": 311.0,
        "avg_straight_speed_b_kph": 310.5,
        "total_time_gained_s": 0.02,
    }
    assert feat.should_show_widget(sample) is False


def test_corner_profiles_declares_triggered_by_modes():
    from features.base import FEATURE_REGISTRY
    from features.registry import discover_features
    discover_features()
    feat = FEATURE_REGISTRY["compare_corner_profiles"]
    assert feat.triggered_by_modes == frozenset({"driver_comparison"})


def test_corner_profiles_widget_surfaces_per_corner_time_gained_and_total():
    """gain_location_summary rows must carry time_gained_s (signed) and
    time_gained_estimate; the widget exposes total_time_gained_s at the
    root so the React component can show a rollup."""
    feat = _load_feat()
    result = {
        "driver_a": "NOR",
        "driver_b": "LEC",
        "event": "Imola",
        "faster_driver": "NOR",
        "overall_gap_s": -0.15,
        "gain_location_summary": [
            {
                "corner": "corner_3",
                "cause": "minimum_speed",
                "apex_delta_kph": 8.0,
                "exit_delta_kph": 5.0,
                "time_gained_s": 0.094,
                "time_gained_estimate": False,
                "corner_length_m": 120.0,
            },
            {
                "corner": "corner_7",
                "cause": "traction",
                "apex_delta_kph": -4.0,
                "exit_delta_kph": 6.0,
                "time_gained_s": -0.041,
                "time_gained_estimate": True,
                "corner_length_m": None,
            },
        ],
        "total_time_gained_s": 0.094,
    }
    widget = feat.make_widget(result)
    rows = widget.get("gain_location_summary") or []
    assert len(rows) == 2
    assert rows[0]["time_gained_s"] == 0.094
    assert rows[0]["time_gained_estimate"] is False
    assert rows[1]["time_gained_s"] == -0.041
    assert rows[1]["time_gained_estimate"] is True
    assert widget["total_time_gained_s"] == 0.094


def test_corner_profiles_gate_uses_real_compare_corner_profiles_field_names():
    """End-to-end check: compare_corner_profiles' actual return dict must
    contain the keys the gate reads. Stubs extract_corner_profiles so we
    exercise the full assembly without needing FastF1 telemetry."""
    import f1_data

    def _make_profile(driver, lap_time_s, apex_kph, straight_kph):
        return {
            "event": "Imola GP",
            "lap_time": "1:18.000" if lap_time_s == 78.0 else "1:18.100",
            "lap_time_s": lap_time_s,
            "corner_profiles": {
                "corner_1": {
                    "apex_speed_kph": apex_kph,
                    "entry_speed_kph": apex_kph + 40,
                    "exit_speed_kph": apex_kph + 20,
                    "braking_point_m": 250,
                    "apex_gear": 3,
                    "corner_length_m": 120.0,
                },
            },
            "straight_profiles": [
                {"max_speed_kph": straight_kph},
                {"max_speed_kph": straight_kph - 4},
            ],
            "lap_summary": {},
        }

    profile_a = _make_profile("NOR", 78.0, 132.0, 312.0)
    profile_b = _make_profile("LEC", 78.1, 124.0, 308.0)

    with patch("f1_data.extract_corner_profiles", side_effect=[profile_a, profile_b]):
        out = f1_data.compare_corner_profiles(7, "Q", "NOR", "LEC")

    # Confirm the real return shape carries the keys the feature gate reads.
    assert "avg_straight_speed_a_kph" in out
    assert "avg_straight_speed_b_kph" in out
    assert "total_time_gained_s" in out
    assert "gain_location_summary" in out
    # And the gate fires on this realistic payload.
    feat = _load_feat()
    assert feat.should_show_widget(out) is True
