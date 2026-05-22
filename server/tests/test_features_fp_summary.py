import pytest

pytestmark = pytest.mark.usefixtures("reset_feature_registry")


def _load_feat():
    from features.base import FEATURE_REGISTRY
    from features.registry import discover_features
    FEATURE_REGISTRY.clear()
    discover_features()
    return FEATURE_REGISTRY["get_fp_summary"]


def test_fp_summary_registered_after_discover():
    from features.base import FEATURE_REGISTRY
    from features.registry import discover_features
    FEATURE_REGISTRY.clear()
    discover_features()
    assert "get_fp_summary" in FEATURE_REGISTRY


def test_fp_summary_relevance_high_for_practice_keyword():
    feat = _load_feat()
    assert feat.is_relevant_for("Who was fastest in FP1?", {}) >= 0.5
    assert feat.is_relevant_for("Show the race results", {}) < 0.5


def test_fp_summary_no_widget():
    feat = _load_feat()
    assert feat.make_widget({"any": "thing"}) == {}
    assert feat.should_show_widget({"any": "thing"}) is False
