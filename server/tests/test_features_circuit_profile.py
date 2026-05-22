import pytest

pytestmark = pytest.mark.usefixtures("reset_feature_registry")


def _load_feat():
    from features.base import FEATURE_REGISTRY
    from features.registry import discover_features
    FEATURE_REGISTRY.clear()
    discover_features()
    return FEATURE_REGISTRY["get_circuit_profile"]


def test_circuit_profile_registered_after_discover():
    from features.base import FEATURE_REGISTRY
    from features.registry import discover_features
    FEATURE_REGISTRY.clear()
    discover_features()
    assert "get_circuit_profile" in FEATURE_REGISTRY


def test_circuit_profile_relevance_high_for_circuit_keyword():
    feat = _load_feat()
    assert feat.is_relevant_for("What's the character of the circuit?", {}) >= 0.5
    assert feat.is_relevant_for("Who won?", {}) < 0.5


def test_circuit_profile_make_widget_delegates():
    feat = _load_feat()
    sample = {"circuit_name": "Imola", "character": "technical"}
    w = feat.make_widget(sample)
    assert w["type"] == "circuit_profile"
    assert w["circuit_name"] == "Imola"


def test_circuit_profile_should_show_widget_respects_availability():
    feat = _load_feat()
    assert feat.should_show_widget({"circuit_name": "Imola"}) is True
    assert feat.should_show_widget({"available": False}) is False
    assert feat.should_show_widget({}) is False
