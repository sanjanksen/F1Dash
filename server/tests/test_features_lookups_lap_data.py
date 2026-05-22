import pytest

pytestmark = pytest.mark.usefixtures("reset_feature_registry")


def test_driver_lap_times_registered():
    from features.base import FEATURE_REGISTRY
    from features.registry import discover_features
    discover_features()
    assert "get_driver_lap_times" in FEATURE_REGISTRY


def test_lap_telemetry_registered():
    from features.base import FEATURE_REGISTRY
    from features.registry import discover_features
    discover_features()
    assert "get_lap_telemetry" in FEATURE_REGISTRY


def test_sector_comparison_registered():
    from features.base import FEATURE_REGISTRY
    from features.registry import discover_features
    discover_features()
    assert "get_sector_comparison" in FEATURE_REGISTRY


def test_telemetry_comparison_registered():
    from features.base import FEATURE_REGISTRY
    from features.registry import discover_features
    discover_features()
    assert "get_telemetry_comparison" in FEATURE_REGISTRY
