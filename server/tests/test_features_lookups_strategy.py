import pytest

pytestmark = pytest.mark.usefixtures("reset_feature_registry")


def test_driver_strategy_registered():
    from features.base import FEATURE_REGISTRY
    from features.registry import discover_features
    discover_features()
    assert "get_driver_strategy" in FEATURE_REGISTRY
