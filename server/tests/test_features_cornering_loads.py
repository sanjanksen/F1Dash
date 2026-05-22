import pytest

pytestmark = pytest.mark.usefixtures("reset_feature_registry")


def _load_feat():
    from features.base import FEATURE_REGISTRY
    from features.registry import discover_features
    FEATURE_REGISTRY.clear()
    discover_features()
    return FEATURE_REGISTRY["analyze_cornering_loads"]


def test_cornering_loads_registered_after_discover():
    from features.base import FEATURE_REGISTRY
    from features.registry import discover_features
    FEATURE_REGISTRY.clear()
    discover_features()
    assert "analyze_cornering_loads" in FEATURE_REGISTRY


def test_cornering_loads_relevance_high_for_grip_keyword():
    feat = _load_feat()
    assert feat.is_relevant_for("Compare cornering loads between Norris and Verstappen", {}) >= 0.5
    assert feat.is_relevant_for("Who won qualifying?", {}) < 0.5


def test_cornering_loads_no_widget_cross_feature():
    feat = _load_feat()
    # Cross-feature: grip_commitment is merged into qualifying_battle, no standalone widget.
    assert feat.make_widget({"any": "thing"}) == {}
    assert feat.should_show_widget({"any": "thing"}) is False


def test_cornering_loads_declares_triggered_by_modes():
    from features.base import FEATURE_REGISTRY
    from features.registry import discover_features
    discover_features()
    feat = FEATURE_REGISTRY["analyze_cornering_loads"]
    assert feat.triggered_by_modes == frozenset({"grip_comparison", "driver_comparison"})
