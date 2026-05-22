import pytest

pytestmark = pytest.mark.usefixtures("reset_feature_registry")


def test_driver_strategy_registered():
    from features.base import FEATURE_REGISTRY
    from features.registry import discover_features
    discover_features()
    assert "get_driver_strategy" in FEATURE_REGISTRY


def test_driver_strategy_declares_triggered_by_modes():
    from features.base import FEATURE_REGISTRY
    from features.registry import discover_features
    discover_features()
    feat = FEATURE_REGISTRY["get_driver_strategy"]
    assert feat.triggered_by_modes == frozenset({"race_pace_comparison"})
