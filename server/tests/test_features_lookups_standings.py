import pytest

pytestmark = pytest.mark.usefixtures("reset_feature_registry")


def test_driver_standings_registered():
    from features.base import FEATURE_REGISTRY
    from features.registry import discover_features
    discover_features()
    assert "get_driver_standings" in FEATURE_REGISTRY


def test_constructor_standings_registered():
    from features.base import FEATURE_REGISTRY
    from features.registry import discover_features
    discover_features()
    assert "get_constructor_standings" in FEATURE_REGISTRY


def test_driver_season_stats_registered():
    from features.base import FEATURE_REGISTRY
    from features.registry import discover_features
    discover_features()
    assert "get_driver_season_stats" in FEATURE_REGISTRY
