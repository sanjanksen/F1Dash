import pytest

pytestmark = pytest.mark.usefixtures("reset_feature_registry")


def _load_feat():
    from features.base import FEATURE_REGISTRY
    from features.registry import discover_features
    FEATURE_REGISTRY.clear()
    discover_features()
    return FEATURE_REGISTRY["analyze_energy_management"]


def test_energy_management_registered_after_discover():
    from features.base import FEATURE_REGISTRY
    from features.registry import discover_features
    FEATURE_REGISTRY.clear()
    discover_features()
    assert "analyze_energy_management" in FEATURE_REGISTRY


def test_energy_management_applies_to_driver():
    feat = _load_feat()
    assert "driver" in feat.applies_to


def test_energy_management_relevance_high_for_energy_keyword():
    feat = _load_feat()
    score = feat.is_relevant_for("Did Norris have any clipping in Imola?", {})
    assert score >= 0.5


def test_energy_management_make_widget_delegates_to_chat_builder():
    feat = _load_feat()
    import chat
    sample = {
        "drivers": [{"driver": "NOR"}],
        "event": "Imola",
        "speed_trace_a": [{"d": 0.0, "v": 280}],
    }
    w = feat.make_widget(sample)
    legacy = chat._make_energy_management_widget(sample)
    assert w["type"] == "energy_management"
    assert w["type"] == legacy["type"]


def test_energy_management_should_show_widget_requires_speed_trace():
    feat = _load_feat()
    assert feat.should_show_widget({"speed_trace_a": [{"d": 0.0}]}) is True
    assert feat.should_show_widget({"speed_trace_a": []}) is False
    assert feat.should_show_widget({}) is False
