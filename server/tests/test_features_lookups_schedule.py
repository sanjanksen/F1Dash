import pytest

pytestmark = pytest.mark.usefixtures("reset_feature_registry")


def test_season_schedule_registered():
    from features.base import FEATURE_REGISTRY
    from features.registry import discover_features
    discover_features()
    assert "get_season_schedule" in FEATURE_REGISTRY
