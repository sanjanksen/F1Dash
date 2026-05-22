import pytest

pytestmark = pytest.mark.usefixtures("reset_feature_registry")


def _load_feat():
    from features.base import FEATURE_REGISTRY
    from features.registry import discover_features
    FEATURE_REGISTRY.clear()
    discover_features()
    return FEATURE_REGISTRY["analyze_race_pace_battle"]


def test_race_pace_battle_registered_after_discover():
    from features.base import FEATURE_REGISTRY
    from features.registry import discover_features
    FEATURE_REGISTRY.clear()
    discover_features()
    assert "analyze_race_pace_battle" in FEATURE_REGISTRY


def test_race_pace_battle_applies_to_pair_of_drivers():
    feat = _load_feat()
    assert "pair_of_drivers" in feat.applies_to


def test_race_pace_battle_make_widget_produces_typed_widget():
    feat = _load_feat()
    sample = {"driver_a": "VER", "driver_b": "HAM", "event": "Imola"}
    w = feat.make_widget(sample)
    assert w["type"] == "race_pace_battle"
    assert w["driver_a"] == "VER"
    assert w["driver_b"] == "HAM"


def test_race_pace_battle_should_show_widget_respects_availability():
    feat = _load_feat()
    assert feat.should_show_widget({"driver_a": "VER", "overall_pace_delta_s": 0.3}) is True
    assert feat.should_show_widget({"available": False}) is False


def test_race_pace_battle_should_show_widget_meaningful_signal():
    feat = _load_feat()
    sample = {
        "available": True,
        "lap_overlap": 12,
        "overall_pace_delta_s": 0.25,
        "deg_rate_delta": 0.01,
    }
    assert feat.should_show_widget(sample) is True


def test_race_pace_battle_should_show_widget_suppresses_negligible():
    feat = _load_feat()
    # Flip overall pace delta below the 0.15 threshold, deg also immaterial
    sample = {
        "available": True,
        "lap_overlap": 12,
        "overall_pace_delta_s": 0.05,
        "deg_rate_delta": 0.01,
    }
    assert feat.should_show_widget(sample) is False


def test_race_pace_battle_declares_triggered_by_modes():
    from features.base import FEATURE_REGISTRY
    from features.registry import discover_features
    discover_features()
    feat = FEATURE_REGISTRY["analyze_race_pace_battle"]
    assert feat.triggered_by_modes == frozenset({"race_pace_comparison", "driver_comparison"})
