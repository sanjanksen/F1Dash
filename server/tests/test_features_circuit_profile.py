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


def test_circuit_profile_make_widget_delegates():
    feat = _load_feat()
    sample = {"circuit_name": "Imola", "character": "technical"}
    w = feat.make_widget(sample)
    assert w["type"] == "circuit_profile"
    assert w["circuit_name"] == "Imola"


def test_circuit_profile_should_show_widget_respects_availability():
    feat = _load_feat()
    sample = {
        "circuit_name": "Imola",
        "downforce_level": "high",
        "character": "technical",
        "sector_1": "fast",
        "sector_2": "rhythm",
    }
    assert feat.should_show_widget(sample) is True
    assert feat.should_show_widget({"available": False}) is False
    assert feat.should_show_widget({}) is False


def test_circuit_profile_should_show_widget_meaningful_signal():
    feat = _load_feat()
    sample = {
        "available": True,
        "circuit_name": "Suzuka",
        "downforce_level": "medium",
        "character": "flowing",
        "sector_1": "fast", "sector_2": "rhythm", "sector_3": "stop-start",
        "tyre_challenge": "high",
    }
    assert feat.should_show_widget(sample) is True


def test_circuit_profile_should_show_widget_suppresses_negligible():
    feat = _load_feat()
    # Only one optional field present → fails the >=2 optional check
    sample = {
        "circuit_name": "Imola",
        "downforce_level": "high",
        "character": "technical",
        "sector_1": "fast",
    }
    assert feat.should_show_widget(sample) is False


def test_circuit_profile_declares_triggered_by_modes():
    from features.base import FEATURE_REGISTRY
    from features.registry import discover_features
    discover_features()
    feat = FEATURE_REGISTRY["get_circuit_profile"]
    assert feat.triggered_by_modes == frozenset({"circuit_profile"})
