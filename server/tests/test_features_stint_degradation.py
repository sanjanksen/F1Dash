import pytest

pytestmark = pytest.mark.usefixtures("reset_feature_registry")


def _load_feat():
    from features.base import FEATURE_REGISTRY
    from features.registry import discover_features
    FEATURE_REGISTRY.clear()
    discover_features()
    return FEATURE_REGISTRY["analyze_stint_degradation"]


def test_stint_degradation_registered_after_discover():
    from features.base import FEATURE_REGISTRY
    from features.registry import discover_features
    FEATURE_REGISTRY.clear()
    discover_features()
    assert "analyze_stint_degradation" in FEATURE_REGISTRY


def test_stint_degradation_applies_to_driver():
    feat = _load_feat()
    assert "driver" in feat.applies_to


def test_stint_degradation_make_widget_produces_typed_widget():
    feat = _load_feat()
    sample = {
        "driver": "NOR", "event": "Imola",
        "stints": [{"compound": "MEDIUM", "scatter_data": [(1, 80.0)]}],
    }
    w = feat.make_widget(sample)
    assert w["type"] == "deg_trend_chart"
    assert w["driver"] == "NOR"
    assert w["event"] == "Imola"
    assert len(w["stints"]) == 1


def test_stint_degradation_should_show_widget_requires_stints():
    feat = _load_feat()
    good_stint = {
        "compound": "MEDIUM",
        "lap_count": 18,
        "r_squared": 0.6,
        "deg_rate_s_per_lap": 0.08,
    }
    assert feat.should_show_widget({"available": True, "stints": [good_stint]}) is True
    assert feat.should_show_widget({"stints": []}) is False
    assert feat.should_show_widget({}) is False
    # Stints with no scatter/regression data are skipped
    assert feat.should_show_widget({
        "stints": [{"compound": "MEDIUM"}],
    }) is False


def test_stint_degradation_should_show_widget_meaningful_signal():
    feat = _load_feat()
    sample = {
        "available": True,
        "stints": [
            {"compound": "S", "lap_count": 8, "r_squared": 0.4, "deg_rate_s_per_lap": 0.12},
            {"compound": "M", "lap_count": 22, "r_squared": 0.7, "deg_rate_s_per_lap": 0.09},
        ],
    }
    assert feat.should_show_widget(sample) is True


def test_stint_degradation_should_show_widget_suppresses_negligible():
    feat = _load_feat()
    # Every stint has r_squared just under the 0.25 threshold
    sample = {
        "available": True,
        "stints": [
            {"compound": "M", "lap_count": 18, "r_squared": 0.20, "deg_rate_s_per_lap": 0.08},
            {"compound": "H", "lap_count": 12, "r_squared": 0.10, "deg_rate_s_per_lap": 0.07},
        ],
    }
    assert feat.should_show_widget(sample) is False
