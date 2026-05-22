import pytest

pytestmark = pytest.mark.usefixtures("reset_feature_registry")


def _load_feat():
    from features.base import FEATURE_REGISTRY
    from features.registry import discover_features
    FEATURE_REGISTRY.clear()
    discover_features()
    return FEATURE_REGISTRY["get_driver_style_profile"]


def test_driver_style_profile_registered_after_discover():
    from features.base import FEATURE_REGISTRY
    from features.registry import discover_features
    FEATURE_REGISTRY.clear()
    discover_features()
    assert "get_driver_style_profile" in FEATURE_REGISTRY


def test_driver_style_profile_relevance_high_for_style_keyword():
    feat = _load_feat()
    assert feat.is_relevant_for("What's Norris's driving style?", {}) >= 0.5
    assert feat.is_relevant_for("Who has the most points?", {}) < 0.5


def test_driver_style_profile_no_widget():
    feat = _load_feat()
    assert feat.make_widget({"any": "thing"}) == {}
    assert feat.should_show_widget({"any": "thing"}) is False
