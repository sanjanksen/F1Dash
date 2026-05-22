import pytest

pytestmark = pytest.mark.usefixtures("reset_feature_registry")


def _load_feat():
    from features.base import FEATURE_REGISTRY
    from features.registry import discover_features
    FEATURE_REGISTRY.clear()
    discover_features()
    return FEATURE_REGISTRY["get_session_weather"]


def test_session_weather_registered_after_discover():
    from features.base import FEATURE_REGISTRY
    from features.registry import discover_features
    FEATURE_REGISTRY.clear()
    discover_features()
    assert "get_session_weather" in FEATURE_REGISTRY


def test_session_weather_relevance_high_for_weather_keyword():
    feat = _load_feat()
    assert feat.is_relevant_for("What was the weather like?", {}) >= 0.5
    assert feat.is_relevant_for("Show the standings", {}) < 0.5


def test_session_weather_no_widget():
    feat = _load_feat()
    assert feat.make_widget({"any": "thing"}) == {}
    assert feat.should_show_widget({"any": "thing"}) is False
