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


def test_stint_degradation_relevance_high_for_degradation_keyword():
    feat = _load_feat()
    score = feat.is_relevant_for("What was Norris's tyre degradation in Imola?", {})
    assert score >= 0.5


def test_stint_degradation_mode_only_does_not_fire():
    feat = _load_feat()
    score = feat.is_relevant_for(
        "What is the weather forecast?",
        {"analysis_mode": "race_pace_comparison"},
    )
    assert score < 0.5


def test_stint_degradation_make_widget_delegates_to_chat_builder():
    feat = _load_feat()
    import chat
    sample = {
        "driver": "NOR", "event": "Imola",
        "stints": [{"compound": "MEDIUM", "scatter_data": [(1, 80.0)]}],
    }
    w = feat.make_widget(sample)
    legacy = chat._make_deg_trend_chart_widget(sample)
    assert w["type"] == "deg_trend_chart"
    assert w["type"] == legacy["type"]


def test_stint_degradation_should_show_widget_requires_stints():
    feat = _load_feat()
    assert feat.should_show_widget({
        "stints": [{"compound": "MEDIUM", "scatter_data": [(1, 80.0)]}],
    }) is True
    assert feat.should_show_widget({"stints": []}) is False
    assert feat.should_show_widget({}) is False
    # Stints with no scatter/regression data get filtered out in builder
    assert feat.should_show_widget({
        "stints": [{"compound": "MEDIUM"}],
    }) is False
