import pytest

pytestmark = pytest.mark.usefixtures("reset_feature_registry")


def _load_feat():
    from features.base import FEATURE_REGISTRY
    from features.registry import discover_features
    FEATURE_REGISTRY.clear()
    discover_features()
    return FEATURE_REGISTRY["compare_corner_profiles"]


def test_corner_profiles_registered_after_discover():
    from features.base import FEATURE_REGISTRY
    from features.registry import discover_features
    FEATURE_REGISTRY.clear()
    discover_features()
    assert "compare_corner_profiles" in FEATURE_REGISTRY


def test_corner_profiles_applies_to_pair_of_drivers():
    feat = _load_feat()
    assert "pair_of_drivers" in feat.applies_to


def test_corner_profiles_relevance_high_for_corner_keyword():
    feat = _load_feat()
    score = feat.is_relevant_for("How does Norris compare in the corners?", {})
    assert score >= 0.5


def test_corner_profiles_mode_only_does_not_fire():
    feat = _load_feat()
    score = feat.is_relevant_for(
        "What is the weather forecast?",
        {"analysis_mode": "grip_comparison"},
    )
    assert score < 0.5


def test_corner_profiles_make_widget_delegates_to_chat_builder():
    feat = _load_feat()
    import chat
    sample = {"driver_a": "NOR", "driver_b": "LEC", "event": "Imola"}
    w = feat.make_widget(sample)
    legacy = chat._make_corner_comparison_widget(sample)
    assert w["type"] == "corner_comparison"
    assert w["type"] == legacy["type"]


def test_corner_profiles_should_show_widget_respects_availability():
    feat = _load_feat()
    assert feat.should_show_widget({"driver_a": "NOR"}) is True
    assert feat.should_show_widget({"available": False}) is False
