import pytest

pytestmark = pytest.mark.usefixtures("reset_feature_registry")


def _load_feat():
    from features.base import FEATURE_REGISTRY
    from features.registry import discover_features
    FEATURE_REGISTRY.clear()
    discover_features()
    return FEATURE_REGISTRY["analyze_team_circuit_fit"]


def test_team_circuit_fit_registered_after_discover():
    from features.base import FEATURE_REGISTRY
    from features.registry import discover_features
    FEATURE_REGISTRY.clear()
    discover_features()
    assert "analyze_team_circuit_fit" in FEATURE_REGISTRY


def test_team_circuit_fit_relevance_high_for_fit_keyword():
    feat = _load_feat()
    assert feat.is_relevant_for("What kind of tracks does Mercedes suit?", {}) >= 0.5
    assert feat.is_relevant_for("Show the lap times", {}) < 0.5


def test_team_circuit_fit_no_widget():
    feat = _load_feat()
    assert feat.make_widget({"any": "thing"}) == {}
    assert feat.should_show_widget({"any": "thing"}) is False


def test_team_circuit_fit_declares_triggered_by_modes():
    from features.base import FEATURE_REGISTRY
    from features.registry import discover_features
    discover_features()
    feat = FEATURE_REGISTRY["analyze_team_circuit_fit"]
    assert feat.triggered_by_modes == frozenset({"team_circuit_fit"})
