import pytest

pytestmark = pytest.mark.usefixtures("reset_feature_registry")


def test_race_results_registered():
    from features.base import FEATURE_REGISTRY
    from features.registry import discover_features
    discover_features()
    assert "get_race_results" in FEATURE_REGISTRY


def test_qualifying_results_registered():
    from features.base import FEATURE_REGISTRY
    from features.registry import discover_features
    discover_features()
    assert "get_qualifying_results" in FEATURE_REGISTRY


def test_sprint_results_registered():
    from features.base import FEATURE_REGISTRY
    from features.registry import discover_features
    discover_features()
    assert "get_sprint_results" in FEATURE_REGISTRY


def test_sprint_qualifying_results_registered():
    from features.base import FEATURE_REGISTRY
    from features.registry import discover_features
    discover_features()
    assert "get_sprint_qualifying_results" in FEATURE_REGISTRY


def test_session_results_registered():
    from features.base import FEATURE_REGISTRY
    from features.registry import discover_features
    discover_features()
    assert "get_session_results" in FEATURE_REGISTRY
