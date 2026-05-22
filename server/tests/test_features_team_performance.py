import pytest

pytestmark = pytest.mark.usefixtures("reset_feature_registry")


def _load_feat():
    from features.base import FEATURE_REGISTRY
    from features.registry import discover_features
    FEATURE_REGISTRY.clear()
    discover_features()
    return FEATURE_REGISTRY["analyze_team_performance"]


def test_team_performance_registered_after_discover():
    from features.base import FEATURE_REGISTRY
    from features.registry import discover_features
    FEATURE_REGISTRY.clear()
    discover_features()
    assert "analyze_team_performance" in FEATURE_REGISTRY


def test_team_performance_relevance_high_for_team_compare():
    feat = _load_feat()
    assert feat.is_relevant_for("Which teammate was stronger as a team?", {}) >= 0.5
    assert feat.is_relevant_for("Show the standings", {}) < 0.5


def test_team_performance_make_widget_delegates_subkey():
    feat = _load_feat()
    sample = {
        "team": "Ferrari",
        "corner_comparison": {
            "driver_a": "LEC",
            "driver_b": "HAM",
            "event": "Monaco",
            "session": "Q",
        },
    }
    w = feat.make_widget(sample)
    assert w.get("type") == "corner_comparison"
    assert w.get("driver_a") == "LEC"


def test_team_performance_should_show_widget_requires_corner_comparison_dict():
    feat = _load_feat()
    assert feat.should_show_widget({"corner_comparison": {"x": "y"}}) is True
    assert feat.should_show_widget({"corner_comparison": None}) is False
    assert feat.should_show_widget({}) is False


def test_team_performance_declares_triggered_by_modes():
    from features.base import FEATURE_REGISTRY
    from features.registry import discover_features
    discover_features()
    feat = FEATURE_REGISTRY["analyze_team_performance"]
    assert feat.triggered_by_modes == frozenset({"team_performance"})
