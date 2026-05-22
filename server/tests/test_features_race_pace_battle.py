import pytest

pytestmark = pytest.mark.usefixtures("reset_feature_registry")


def _load_feat():
    from features.base import FEATURE_REGISTRY
    from features.registry import discover_features
    FEATURE_REGISTRY.clear()
    discover_features()
    return FEATURE_REGISTRY["analyze_race_pace_battle"]


def test_race_pace_battle_registered_after_discover():
    from features.base import FEATURE_REGISTRY
    from features.registry import discover_features
    FEATURE_REGISTRY.clear()
    discover_features()
    assert "analyze_race_pace_battle" in FEATURE_REGISTRY


def test_race_pace_battle_applies_to_pair_of_drivers():
    feat = _load_feat()
    assert "pair_of_drivers" in feat.applies_to


def test_race_pace_battle_relevance_high_for_race_pace_keyword():
    feat = _load_feat()
    score = feat.is_relevant_for("Who had better race pace in Imola?", {})
    assert score >= 0.5


def test_race_pace_battle_mode_only_does_not_fire():
    feat = _load_feat()
    score = feat.is_relevant_for(
        "What is the weather forecast?",
        {"analysis_mode": "race_pace_comparison"},
    )
    assert score < 0.5


def test_race_pace_battle_make_widget_produces_typed_widget():
    feat = _load_feat()
    sample = {"driver_a": "VER", "driver_b": "HAM", "event": "Imola"}
    w = feat.make_widget(sample)
    assert w["type"] == "race_pace_battle"
    assert w["driver_a"] == "VER"
    assert w["driver_b"] == "HAM"


def test_race_pace_battle_should_show_widget_respects_availability():
    feat = _load_feat()
    assert feat.should_show_widget({"driver_a": "VER"}) is True
    assert feat.should_show_widget({"available": False}) is False
