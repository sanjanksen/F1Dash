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


def test_driver_race_story_make_widget_delegates():
    feat = _load_feat()
    sample = {"driver": "George Russell", "event": "Japanese GP", "code": "RUS"}
    w = feat.make_widget(sample)
    assert w.get("type") == "race_story"


def test_driver_race_story_should_show_widget_suppresses_unavailable():
    feat = _load_feat()
    full = {
        "available": True,
        "driver": "x",
        "race": {"finish_position": 3},
        "story_points": [{"lap": 1}],
        "pit_stops": [{"lap": 18}],
    }
    assert feat.should_show_widget({"available": False}) is False
    assert feat.should_show_widget({}) is False
    assert feat.should_show_widget(full) is True


def test_driver_race_story_should_show_widget_meaningful_signal():
    feat = _load_feat()
    sample = {
        "available": True,
        "race": {"status": "FINISHED"},
        "story_points": [{"lap": 1}, {"lap": 14}],
        "interval_summary": {"close": True},
        "radio_highlights": [{"lap": 20}],
    }
    assert feat.should_show_widget(sample) is True


def test_driver_race_story_should_show_widget_suppresses_negligible():
    feat = _load_feat()
    # Only one storyful field present, fails the >=2 gate
    sample = {
        "available": True,
        "race": {"finish_position": 7},
        "story_points": [{"lap": 1}],
    }
    assert feat.should_show_widget(sample) is False


def test_driver_race_story_declares_triggered_by_modes():
    from features.base import FEATURE_REGISTRY
    from features.registry import discover_features
    discover_features()
    feat = FEATURE_REGISTRY["get_driver_race_story"]
    assert feat.triggered_by_modes == frozenset({"driver_comparison"})
