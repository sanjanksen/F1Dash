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


def test_qualifying_results_declares_triggered_by_modes():
    from features.base import FEATURE_REGISTRY
    from features.registry import discover_features
    discover_features()
    feat = FEATURE_REGISTRY["get_qualifying_results"]
    assert feat.triggered_by_modes == frozenset({"driver_comparison"})


def test_sprint_qualifying_results_declares_triggered_by_modes():
    from features.base import FEATURE_REGISTRY
    from features.registry import discover_features
    discover_features()
    feat = FEATURE_REGISTRY["get_sprint_qualifying_results"]
    assert feat.triggered_by_modes == frozenset({"driver_comparison"})


def test_qualifying_results_fires_only_on_Q_not_SQ():
    from features.registry import features_for_mode, discover_features
    discover_features()
    resolved_q = {
        "analysis_mode": "driver_comparison", "session_type": "Q",
        "round_number": 7, "drivers": [{"code": "A"}, {"code": "B"}],
    }
    feats = [f.name for f in features_for_mode("driver_comparison", resolved_q)]
    assert "get_qualifying_results" in feats
    assert "get_sprint_qualifying_results" not in feats


def test_sprint_qualifying_results_fires_only_on_SQ_not_Q():
    from features.registry import features_for_mode, discover_features
    discover_features()
    resolved_sq = {
        "analysis_mode": "driver_comparison", "session_type": "SQ",
        "round_number": 7, "drivers": [{"code": "A"}, {"code": "B"}],
    }
    feats = [f.name for f in features_for_mode("driver_comparison", resolved_sq)]
    assert "get_sprint_qualifying_results" in feats
    assert "get_qualifying_results" not in feats
