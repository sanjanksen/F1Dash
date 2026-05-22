import pytest

pytestmark = pytest.mark.usefixtures("reset_feature_registry")


def _load_feat():
    from features.base import FEATURE_REGISTRY
    from features.registry import discover_features
    FEATURE_REGISTRY.clear()
    discover_features()
    return FEATURE_REGISTRY["analyze_undercut_overcut"]


def test_undercut_overcut_registered_after_discover():
    from features.base import FEATURE_REGISTRY
    from features.registry import discover_features
    FEATURE_REGISTRY.clear()
    discover_features()
    assert "analyze_undercut_overcut" in FEATURE_REGISTRY


def test_undercut_overcut_applies_to_driver_and_race_session():
    feat = _load_feat()
    assert "driver" in feat.applies_to
    assert "race_session" in feat.applies_to


def test_undercut_overcut_make_widget_produces_typed_widget():
    feat = _load_feat()
    sample = {
        "driver_code": "NOR", "current_lap": 14, "event": "Imola",
        "round_number": 7, "advantage_s": 0.4, "recommendation": "pit_now",
    }
    w = feat.make_widget(sample)
    assert w["type"] == "undercut_overcut"
    assert w["driver_code"] == "NOR"
    assert w["recommendation"] == "pit_now"


def test_undercut_overcut_should_show_widget_respects_availability():
    feat = _load_feat()
    full = {
        "available": True,
        "driver_code": "NOR",
        "pit_loss_s": 21.0,
        "advantage_by_rejoin_lap": [{"lap": 1}, {"lap": 2}, {"lap": 3}],
        "advantage_s": 0.8,
    }
    assert feat.should_show_widget(full) is True
    assert feat.should_show_widget({"available": False}) is False


def test_undercut_overcut_should_show_widget_meaningful_signal():
    feat = _load_feat()
    sample = {
        "available": True,
        "pit_loss_s": 22.3,
        "advantage_by_rejoin_lap": [{"lap": 18}, {"lap": 19}, {"lap": 20}],
        "advantage_s": -1.2,
    }
    assert feat.should_show_widget(sample) is True


def test_undercut_overcut_should_show_widget_suppresses_negligible():
    feat = _load_feat()
    # advantage below the 0.5 threshold
    sample = {
        "available": True,
        "pit_loss_s": 22.3,
        "advantage_by_rejoin_lap": [{"lap": 18}, {"lap": 19}, {"lap": 20}],
        "advantage_s": 0.2,
    }
    assert feat.should_show_widget(sample) is False
