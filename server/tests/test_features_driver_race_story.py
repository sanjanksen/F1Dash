import pytest

pytestmark = pytest.mark.usefixtures("reset_feature_registry")


def _load_feat():
    from features.base import FEATURE_REGISTRY
    from features.registry import discover_features
    FEATURE_REGISTRY.clear()
    discover_features()
    return FEATURE_REGISTRY["get_driver_race_story"]


def test_driver_race_story_registered_after_discover():
    from features.base import FEATURE_REGISTRY
    from features.registry import discover_features
    FEATURE_REGISTRY.clear()
    discover_features()
    assert "get_driver_race_story" in FEATURE_REGISTRY


def test_driver_race_story_relevance_high_for_race_recap():
    feat = _load_feat()
    assert feat.is_relevant_for("How did Russell's race go?", {}) >= 0.5
    assert feat.is_relevant_for("Show the lap times", {}) < 0.5


def test_driver_race_story_make_widget_delegates():
    feat = _load_feat()
    sample = {"driver": "George Russell", "event": "Japanese GP", "code": "RUS"}
    w = feat.make_widget(sample)
    assert w.get("type") == "race_story"


def test_driver_race_story_should_show_widget_suppresses_unavailable():
    feat = _load_feat()
    assert feat.should_show_widget({"available": False}) is False
    assert feat.should_show_widget({}) is False
    assert feat.should_show_widget({"driver": "x"}) is True


def test_driver_race_story_declares_triggered_by_modes():
    from features.base import FEATURE_REGISTRY
    from features.registry import discover_features
    discover_features()
    feat = FEATURE_REGISTRY["get_driver_race_story"]
    assert feat.triggered_by_modes == frozenset({"driver_comparison"})
