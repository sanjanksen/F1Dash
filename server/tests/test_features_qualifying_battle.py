import pytest

pytestmark = pytest.mark.usefixtures("reset_feature_registry")


def _load_feat():
    from features.base import FEATURE_REGISTRY
    from features.registry import discover_features
    FEATURE_REGISTRY.clear()
    discover_features()
    return FEATURE_REGISTRY["analyze_qualifying_battle"]


def test_qualifying_battle_registered_after_discover():
    from features.base import FEATURE_REGISTRY
    from features.registry import discover_features
    FEATURE_REGISTRY.clear()
    discover_features()
    assert "analyze_qualifying_battle" in FEATURE_REGISTRY


def test_qualifying_battle_applies_to_pair_of_drivers():
    feat = _load_feat()
    assert "pair_of_drivers" in feat.applies_to


def test_qualifying_battle_relevance_high_for_quali_keyword():
    feat = _load_feat()
    score = feat.is_relevant_for("Why was Leclerc faster in qualifying?", {})
    assert score >= 0.5


def test_qualifying_battle_mode_only_does_not_fire():
    feat = _load_feat()
    score = feat.is_relevant_for(
        "What is the weather forecast?",
        {"analysis_mode": "qualifying_battle"},
    )
    assert score < 0.5


def test_qualifying_battle_make_widget_produces_typed_widget():
    feat = _load_feat()
    sample = {
        "driver_a": "NOR", "driver_b": "PIA",
        "faster_driver": "NOR", "overall_gap_s": 0.12,
        "event": "Imola", "compared_segment": "Q3",
    }
    w = feat.make_widget(sample)
    assert w["type"] == "qualifying_battle"
    assert w["driver_a"] == "NOR"
    assert w["driver_b"] == "PIA"
    assert w["faster_driver"] == "NOR"


def test_qualifying_battle_should_show_widget_respects_availability():
    feat = _load_feat()
    assert feat.should_show_widget({"driver_a": "NOR"}) is True
    assert feat.should_show_widget({"available": False}) is False


def test_qualifying_battle_declares_triggered_by_modes():
    from features.base import FEATURE_REGISTRY
    from features.registry import discover_features
    discover_features()
    feat = FEATURE_REGISTRY["analyze_qualifying_battle"]
    assert feat.triggered_by_modes == frozenset({"driver_comparison"})
