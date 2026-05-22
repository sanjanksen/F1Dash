import pytest

pytestmark = pytest.mark.usefixtures("reset_feature_registry")


def _load_feat():
    from features.base import FEATURE_REGISTRY
    from features.registry import discover_features
    FEATURE_REGISTRY.clear()
    discover_features()
    return FEATURE_REGISTRY["analyze_undercut_overcut"]


def test_undercut_overcut_registered_after_discover():
    from features.base import FEATURE_REGISTRY
    from features.registry import discover_features
    FEATURE_REGISTRY.clear()
    discover_features()
    assert "analyze_undercut_overcut" in FEATURE_REGISTRY


def test_undercut_overcut_applies_to_driver_and_race_session():
    feat = _load_feat()
    assert "driver" in feat.applies_to
    assert "race_session" in feat.applies_to


def test_undercut_overcut_relevance_high_for_undercut_keyword():
    feat = _load_feat()
    score = feat.is_relevant_for("Should Norris have pitted on lap 14 for the undercut?", {})
    assert score >= 0.5


def test_undercut_overcut_make_widget_delegates_to_chat_builder():
    feat = _load_feat()
    import chat
    sample = {
        "driver_code": "NOR", "current_lap": 14, "event": "Imola",
        "round_number": 7, "advantage_s": 0.4, "recommendation": "pit_now",
    }
    w = feat.make_widget(sample)
    legacy = chat._make_undercut_overcut_widget(sample)
    assert w["type"] == "undercut_overcut"
    assert w["type"] == legacy["type"]


def test_undercut_overcut_should_show_widget_respects_availability():
    feat = _load_feat()
    assert feat.should_show_widget({"driver_code": "NOR"}) is True
    assert feat.should_show_widget({"available": False}) is False
