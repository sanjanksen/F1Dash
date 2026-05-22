import pytest

pytestmark = pytest.mark.usefixtures("reset_feature_registry")


def _load_feat():
    from features.base import FEATURE_REGISTRY
    from features.registry import discover_features
    FEATURE_REGISTRY.clear()
    discover_features()
    return FEATURE_REGISTRY["get_driver_weekend_overview"]


def test_driver_weekend_overview_registered_after_discover():
    from features.base import FEATURE_REGISTRY
    from features.registry import discover_features
    FEATURE_REGISTRY.clear()
    discover_features()
    assert "get_driver_weekend_overview" in FEATURE_REGISTRY


def test_driver_weekend_overview_relevance_high_for_weekend_keyword():
    feat = _load_feat()
    assert feat.is_relevant_for("How was Russell's weekend?", {}) >= 0.5
    assert feat.is_relevant_for("Show the lap times", {}) < 0.5


def test_driver_weekend_overview_no_widget():
    feat = _load_feat()
    assert feat.make_widget({"any": "thing"}) == {}
    assert feat.should_show_widget({"any": "thing"}) is False
