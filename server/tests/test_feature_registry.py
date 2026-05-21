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
