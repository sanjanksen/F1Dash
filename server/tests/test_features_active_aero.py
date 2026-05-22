import pytest

pytestmark = pytest.mark.usefixtures("reset_feature_registry")


def _load_feat():
    from features.base import FEATURE_REGISTRY
    from features.registry import discover_features
    FEATURE_REGISTRY.clear()
    discover_features()
    return FEATURE_REGISTRY["analyze_active_aero_usage"]


def test_active_aero_registered_after_discover():
    from features.base import FEATURE_REGISTRY
    from features.registry import discover_features
    FEATURE_REGISTRY.clear()
    discover_features()
    assert "analyze_active_aero_usage" in FEATURE_REGISTRY


def test_active_aero_applies_to_driver_and_lap():
    feat = _load_feat()
    assert "driver" in feat.applies_to
    assert "lap" in feat.applies_to


def test_active_aero_relevance_high_for_aero_keyword():
    feat = _load_feat()
    score = feat.is_relevant_for("When did Norris use Z-mode on lap 12?", {})
    assert score >= 0.5


def test_active_aero_make_widget_delegates_to_chat_builder():
    feat = _load_feat()
    import chat
    sample = {
        "driver_code": "NOR", "round_number": 7, "session_type": "Q",
        "lap_number": 12, "circuit_slug": "imola",
        "segments": [], "total_z_mode_seconds": 0.0,
    }
    w = feat.make_widget(sample)
    legacy = chat._make_active_aero_widget(sample)
    assert w["type"] == "active_aero"
    assert w["type"] == legacy["type"]


def test_active_aero_should_show_widget_respects_availability():
    feat = _load_feat()
    assert feat.should_show_widget({"driver_code": "NOR"}) is True
    assert feat.should_show_widget({"available": False}) is False
