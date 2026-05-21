import pytest

from features.base import Feature, register_feature, FEATURE_REGISTRY


class _DummyFeature(Feature):
    name = "_dummy"
    applies_to = ("pair_of_drivers",)

    def is_relevant_for(self, question, resolved):
        return 1.0 if "dummy" in question.lower() else 0.0

    def execute(self, **args):
        return {"ok": True}

    def make_widget(self, result):
        return {"type": "dummy", "ok": result["ok"]}

    def should_show_widget(self, result):
        return result.get("ok") is True


@pytest.fixture(autouse=True)
def isolate_feature_registry():
    saved = dict(FEATURE_REGISTRY)
    FEATURE_REGISTRY.clear()
    yield
    FEATURE_REGISTRY.clear()
    FEATURE_REGISTRY.update(saved)


def test_feature_subclass_must_set_name():
    """Features without a `name` class attribute must raise TypeError."""
    with pytest.raises(TypeError):
        class _Bad(Feature):
            applies_to = ()
            def is_relevant_for(self, q, r): return 0
            def execute(self, **a): return {}
            def make_widget(self, r): return {}
            def should_show_widget(self, r): return False
        _Bad()


def test_register_feature_adds_to_registry():
    """The decorator registers the class in FEATURE_REGISTRY by name."""
    @register_feature
    class _F(_DummyFeature):
        name = "_test_register"

    assert "_test_register" in FEATURE_REGISTRY
    assert FEATURE_REGISTRY["_test_register"].name == "_test_register"


def test_register_feature_rejects_duplicate_names():
    """Re-registering the same name should raise."""
    @register_feature
    class _A(_DummyFeature):
        name = "_dup"

    with pytest.raises(ValueError):
        @register_feature
        class _B(_DummyFeature):
            name = "_dup"


def test_is_relevant_for_returns_float_in_unit_interval():
    """Predicate contract: return must be a float between 0 and 1."""
    f = _DummyFeature()
    assert f.is_relevant_for("dummy question", {}) == 1.0
    assert f.is_relevant_for("other question", {}) == 0.0


def test_register_feature_rejects_non_feature_classes():
    """@register_feature must reject non-Feature classes with TypeError."""
    class _NotAFeature:
        name = "_not_a_feature"

    with pytest.raises(TypeError):
        register_feature(_NotAFeature)


from features.registry import discover_features, candidates_for, rank_by_relevance


def test_discover_features_imports_all_modules_under_features_package():
    """discover_features walks server/features/ and imports every .py module,
    triggering @register_feature side effects."""
    # The autouse fixture already cleared the registry. discover_features
    # should run without error and return an integer count.
    count = discover_features()
    assert isinstance(count, int)
    assert count >= 0


def test_candidates_for_filters_by_applies_to():
    """candidates_for returns features whose applies_to is satisfied by the
    resolved entity types."""

    @register_feature
    class _NeedsPair(_DummyFeature):
        name = "_needs_pair"
        applies_to = ("pair_of_drivers",)

    @register_feature
    class _NeedsCircuit(_DummyFeature):
        name = "_needs_circuit"
        applies_to = ("circuit",)

    resolved = {"drivers": [{"code": "NOR"}, {"code": "PIA"}]}
    cands = candidates_for(resolved)
    names = {f.name for f in cands}
    assert "_needs_pair" in names
    assert "_needs_circuit" not in names


def test_rank_by_relevance_returns_scored_features_sorted_descending():
    """rank_by_relevance asks each candidate is_relevant_for, returns
    [(feature, score)] sorted by score descending."""

    @register_feature
    class _High(_DummyFeature):
        name = "_high"
        def is_relevant_for(self, q, r): return 0.9

    @register_feature
    class _Low(_DummyFeature):
        name = "_low"
        def is_relevant_for(self, q, r): return 0.2

    @register_feature
    class _Mid(_DummyFeature):
        name = "_mid"
        def is_relevant_for(self, q, r): return 0.55

    cands = list(FEATURE_REGISTRY.values())
    ranked = rank_by_relevance("any question", {}, cands)
    assert [f.name for f, score in ranked] == ["_high", "_mid", "_low"]
    assert all(0.0 <= score <= 1.0 for _, score in ranked)


def test_rank_by_relevance_clamps_invalid_scores():
    """A predicate returning > 1.0 or < 0.0 should be clamped, not raise."""

    @register_feature
    class _Bad(_DummyFeature):
        name = "_bad"
        def is_relevant_for(self, q, r): return 5.0

    @register_feature
    class _Neg(_DummyFeature):
        name = "_neg"
        def is_relevant_for(self, q, r): return -1.0

    cands = list(FEATURE_REGISTRY.values())
    ranked = rank_by_relevance("q", {}, cands)
    scores = {f.name: s for f, s in ranked}
    assert scores["_bad"] == 1.0
    assert scores["_neg"] == 0.0
