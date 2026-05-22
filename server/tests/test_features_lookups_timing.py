import pytest

pytestmark = pytest.mark.usefixtures("reset_feature_registry")


def test_clean_pace_summary_registered():
    from features.base import FEATURE_REGISTRY
    from features.registry import discover_features
    discover_features()
    assert "get_clean_pace_summary" in FEATURE_REGISTRY


def test_track_position_comparison_registered():
    from features.base import FEATURE_REGISTRY
    from features.registry import discover_features
    discover_features()
    assert "get_track_position_comparison" in FEATURE_REGISTRY


def test_qualifying_progression_registered():
    from features.base import FEATURE_REGISTRY
    from features.registry import discover_features
    discover_features()
    assert "get_qualifying_progression" in FEATURE_REGISTRY


def test_session_fastest_laps_registered():
    from features.base import FEATURE_REGISTRY
    from features.registry import discover_features
    discover_features()
    assert "get_session_fastest_laps" in FEATURE_REGISTRY


def test_speed_trap_leaderboard_registered():
    from features.base import FEATURE_REGISTRY
    from features.registry import discover_features
    discover_features()
    assert "get_speed_trap_leaderboard" in FEATURE_REGISTRY
