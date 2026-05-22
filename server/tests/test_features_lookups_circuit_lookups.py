import pytest

pytestmark = pytest.mark.usefixtures("reset_feature_registry")


def test_circuit_details_registered():
    from features.base import FEATURE_REGISTRY
    from features.registry import discover_features
    discover_features()
    assert "get_circuit_details" in FEATURE_REGISTRY


def test_circuit_corners_registered():
    from features.base import FEATURE_REGISTRY
    from features.registry import discover_features
    discover_features()
    assert "get_circuit_corners" in FEATURE_REGISTRY


def test_circuit_track_map_registered():
    from features.base import FEATURE_REGISTRY
    from features.registry import discover_features
    discover_features()
    assert "get_circuit_track_map" in FEATURE_REGISTRY


def test_historical_circuit_performance_registered():
    from features.base import FEATURE_REGISTRY
    from features.registry import discover_features
    discover_features()
    assert "get_historical_circuit_performance" in FEATURE_REGISTRY
