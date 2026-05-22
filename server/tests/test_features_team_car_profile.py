import pytest

pytestmark = pytest.mark.usefixtures("reset_feature_registry")


def _load_feat():
    from features.base import FEATURE_REGISTRY
    from features.registry import discover_features
    FEATURE_REGISTRY.clear()
    discover_features()
    return FEATURE_REGISTRY["get_team_car_profile"]


def test_team_car_profile_registered_after_discover():
    from features.base import FEATURE_REGISTRY
    from features.registry import discover_features
    FEATURE_REGISTRY.clear()
    discover_features()
    assert "get_team_car_profile" in FEATURE_REGISTRY


def test_team_car_profile_relevance_high_for_car_keyword():
    feat = _load_feat()
    assert feat.is_relevant_for("What are McLaren's car characteristics?", {}) >= 0.5
    assert feat.is_relevant_for("Who is leading the championship?", {}) < 0.5


def test_team_car_profile_no_widget():
    feat = _load_feat()
    assert feat.make_widget({"any": "thing"}) == {}
    assert feat.should_show_widget({"any": "thing"}) is False
