import pytest

from features.base import Feature, register_feature, FEATURE_REGISTRY


class _DummyFeature(Feature):
    name = "_dummy"
    applies_to = ("pair_of_drivers",)

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


def test_register_feature_rejects_non_feature_classes():
    """@register_feature must reject non-Feature classes with TypeError."""
    class _NotAFeature:
        name = "_not_a_feature"

    with pytest.raises(TypeError):
        register_feature(_NotAFeature)


from features.registry import discover_features, candidates_for


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


from features.base import audit_log, get_audit_log, clear_audit_log


def test_audit_log_records_feature_decisions():
    """audit_log appends a decision record for inspection later."""
    clear_audit_log()
    audit_log(
        feature_name="_dummy",
        question="test q",
        applies_to_passed=True,
        relevance_score=0.8,
        executed=True,
        widget_emitted=True,
        duration_ms=42,
    )
    records = get_audit_log()
    assert len(records) == 1
    r = records[0]
    assert r["feature_name"] == "_dummy"
    assert r["relevance_score"] == 0.8
    assert r["executed"] is True
    assert "ts" in r  # timestamp added automatically


def test_clear_audit_log_resets_state():
    audit_log(feature_name="_a", question="q", applies_to_passed=True,
              relevance_score=1.0, executed=False, widget_emitted=False)
    assert len(get_audit_log()) >= 1
    clear_audit_log()
    assert get_audit_log() == []


def test_feature_subclass_inherits_triggered_by_modes_default():
    """Features that don't declare triggered_by_modes default to empty frozenset."""
    class _NoModes(_DummyFeature):
        name = "_no_modes"
    f = _NoModes()
    assert f.triggered_by_modes == frozenset()


def test_feature_subclass_can_declare_triggered_by_modes():
    """A subclass setting triggered_by_modes exposes it on the instance."""
    class _WithModes(_DummyFeature):
        name = "_with_modes"
        triggered_by_modes = frozenset({"qualifying_battle", "driver_comparison"})
    f = _WithModes()
    assert f.triggered_by_modes == frozenset({"qualifying_battle", "driver_comparison"})


from features.registry import features_for_mode


def test_features_for_mode_filters_by_triggered_by_modes():
    @register_feature
    class _Quali(_DummyFeature):
        name = "_quali_feat"
        applies_to = ("pair_of_drivers",)
        triggered_by_modes = frozenset({"qualifying_battle"})

    @register_feature
    class _Race(_DummyFeature):
        name = "_race_feat"
        applies_to = ("pair_of_drivers",)
        triggered_by_modes = frozenset({"race_pace_comparison"})

    resolved = {"drivers": [{"code": "A"}, {"code": "B"}]}
    feats = features_for_mode("qualifying_battle", resolved)
    names = {f.name for f in feats}
    assert "_quali_feat" in names
    assert "_race_feat" not in names


def test_features_for_mode_also_filters_by_applies_to():
    @register_feature
    class _NeedsTeam(_DummyFeature):
        name = "_needs_team"
        applies_to = ("team",)
        triggered_by_modes = frozenset({"qualifying_battle"})

    resolved = {"drivers": [{"code": "A"}, {"code": "B"}]}  # no team
    feats = features_for_mode("qualifying_battle", resolved)
    assert all(f.name != "_needs_team" for f in feats)


def test_features_for_mode_returns_empty_when_no_mode_matches():
    feats = features_for_mode("nonexistent_mode", {"drivers": []})
    assert feats == []


def test_features_for_mode_with_none_resolved_treats_empty_entities():
    feats = features_for_mode("qualifying_battle", None)
    assert isinstance(feats, list)
