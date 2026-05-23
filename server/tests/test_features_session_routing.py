"""Race-only features must not fire on qualifying questions.

Bug repro: user asked 'how did Norris outqualify Piastri' and got a
race_pace_battle widget with stint degradation. Root cause was race
features declaring applies_to=('pair_of_drivers',) instead of
applies_to=('pair_of_drivers', 'race_session').
"""
import pytest

pytestmark = pytest.mark.usefixtures("reset_feature_registry")


@pytest.mark.parametrize("feature_name", [
    "analyze_race_pace_battle",
    "analyze_stint_degradation",
    "analyze_undercut_overcut",
    "get_pit_stop_analysis",
    "get_safety_car_periods",
    "get_driver_strategy",
    "get_driver_race_story",
])
def test_race_features_excluded_for_quali_session(feature_name):
    """A registered race feature must NOT appear in candidates_for when
    session_type=Q."""
    from features.base import FEATURE_REGISTRY
    from features.registry import discover_features, candidates_for
    discover_features()
    quali_resolved = {
        "drivers": [{"code": "NOR"}, {"code": "PIA"}],
        "round_number": 7,
        "session_type": "Q",
    }
    cands = candidates_for(quali_resolved)
    names = {f.name for f in cands}
    assert feature_name not in names, (
        f"{feature_name} should not be a candidate when session_type=Q"
    )


@pytest.mark.parametrize("feature_name", [
    "analyze_race_pace_battle",
    "analyze_stint_degradation",
    "analyze_undercut_overcut",
    "get_pit_stop_analysis",
    "get_safety_car_periods",
    "get_driver_strategy",
    "get_driver_race_story",
])
def test_race_features_included_for_race_session(feature_name):
    """The same features MUST appear in candidates_for when session_type=R."""
    from features.base import FEATURE_REGISTRY
    from features.registry import discover_features, candidates_for
    discover_features()
    race_resolved = {
        "drivers": [{"code": "NOR"}, {"code": "PIA"}],
        "round_number": 7,
        "session_type": "R",
    }
    cands = candidates_for(race_resolved)
    names = {f.name for f in cands}
    assert feature_name in names, (
        f"{feature_name} should be a candidate when session_type=R"
    )
