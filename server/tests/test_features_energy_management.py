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


def test_energy_management_make_widget_produces_typed_widget():
    feat = _load_feat()
    sample = {
        "drivers": [{"driver": "NOR"}],
        "event": "Imola",
        "speed_trace_a": [{"d": 0.0, "v": 280}],
    }
    w = feat.make_widget(sample)
    assert w["type"] == "energy_management"
    assert w["driver_a"] == "NOR"
    assert w["event"] == "Imola"


def test_energy_management_should_show_widget_requires_speed_trace():
    feat = _load_feat()
    full = {
        "available": True,
        "speed_trace_a": [{"d": float(i)} for i in range(25)],
        "clipping_signature_a": {"total_clipping_seconds": 0.5},
    }
    assert feat.should_show_widget(full) is True
    assert feat.should_show_widget({"speed_trace_a": []}) is False
    assert feat.should_show_widget({}) is False


def test_energy_management_should_show_widget_meaningful_signal():
    feat = _load_feat()
    # Driver A has no clipping but driver B has a lot -- delta >= 0.1 fires.
    sample = {
        "available": True,
        "speed_trace_a": [{"d": float(i)} for i in range(30)],
        "clipping_signature_a": {"total_clipping_seconds": 0.0},
        "clipping_signature_b": {"total_clipping_seconds": 0.25},
    }
    assert feat.should_show_widget(sample) is True


def test_energy_management_should_show_widget_suppresses_negligible():
    feat = _load_feat()
    # Speed trace long enough but neither clipping signal is material
    sample = {
        "available": True,
        "speed_trace_a": [{"d": float(i)} for i in range(25)],
        "clipping_signature_a": {"total_clipping_seconds": 0.05},
        "clipping_signature_b": {"total_clipping_seconds": 0.03},
    }
    assert feat.should_show_widget(sample) is False
