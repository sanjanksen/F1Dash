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


def test_active_aero_make_widget_produces_typed_widget():
    feat = _load_feat()
    sample = {
        "driver_code": "NOR", "round_number": 7, "session_type": "Q",
        "lap_number": 12, "circuit_slug": "imola",
        "segments": [], "total_z_mode_seconds": 0.0,
    }
    w = feat.make_widget(sample)
    assert w["type"] == "active_aero"
    assert w["driver_code"] == "NOR"
    assert w["lap_number"] == 12


def test_active_aero_should_show_widget_respects_availability():
    feat = _load_feat()
    full = {
        "available": True,
        "driver_code": "NOR",
        "circuit_in_coverage": True,
        "total_z_mode_seconds": 1.2,
    }
    assert feat.should_show_widget(full) is True
    assert feat.should_show_widget({"available": False}) is False


def test_active_aero_should_show_widget_meaningful_signal():
    feat = _load_feat()
    sample = {
        "available": True,
        "circuit_in_coverage": True,
        "total_z_mode_seconds": 0.8,
    }
    assert feat.should_show_widget(sample) is True


def test_active_aero_should_show_widget_suppresses_negligible():
    feat = _load_feat()
    # z-mode time below the 0.3 threshold
    sample = {
        "available": True,
        "circuit_in_coverage": True,
        "total_z_mode_seconds": 0.1,
    }
    assert feat.should_show_widget(sample) is False


def test_active_aero_should_show_widget_suppresses_when_circuit_uncovered():
    feat = _load_feat()
    sample = {
        "available": True,
        "circuit_in_coverage": False,
        "total_z_mode_seconds": 5.0,
    }
    assert feat.should_show_widget(sample) is False
