import pytest

pytestmark = pytest.mark.usefixtures("reset_feature_registry")


def test_pit_stop_analysis_registered():
    from features.base import FEATURE_REGISTRY
    from features.registry import discover_features
    discover_features()
    assert "get_pit_stop_analysis" in FEATURE_REGISTRY


def test_pit_stop_analysis_applies_to_race_session():
    from features.base import FEATURE_REGISTRY
    from features.registry import discover_features
    discover_features()
    feat = FEATURE_REGISTRY["get_pit_stop_analysis"]
    assert "race_session" in feat.applies_to


def test_pit_stop_analysis_relevance_high_for_pit_questions():
    from features.base import FEATURE_REGISTRY
    from features.registry import discover_features
    discover_features()
    feat = FEATURE_REGISTRY["get_pit_stop_analysis"]
    assert feat.is_relevant_for("Who had the fastest pit stops?", {}) >= 0.5
    assert feat.is_relevant_for("What's the weather?", {}) < 0.5


def test_pit_stop_analysis_make_widget_delegates():
    from features.base import FEATURE_REGISTRY
    from features.registry import discover_features
    discover_features()
    feat = FEATURE_REGISTRY["get_pit_stop_analysis"]
    sample = {"round_number": 7, "drivers": []}
    w = feat.make_widget(sample)
    assert w.get("type") == "pit_stop_strategy"


def test_pit_stop_analysis_should_show_widget_suppresses_empty():
    from features.base import FEATURE_REGISTRY
    from features.registry import discover_features
    discover_features()
    feat = FEATURE_REGISTRY["get_pit_stop_analysis"]
    assert feat.should_show_widget({"available": False}) is False
    assert feat.should_show_widget({}) is False
    assert feat.should_show_widget({"available": True}) is True
