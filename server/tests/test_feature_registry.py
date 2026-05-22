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


from features.registry import run_pipeline


def test_run_pipeline_executes_only_features_above_threshold():
    """Features with score >= 0.5 execute and produce results; below
    threshold are NOT executed (raises in execute() if it ever runs)."""

    @register_feature
    class _Fires(_DummyFeature):
        name = "_fires"
        applies_to = ("pair_of_drivers",)
        def is_relevant_for(self, q, r): return 0.9
        def execute(self, **a): return {"ok": True, "value": 7}
        def make_widget(self, r): return {"type": "fires_widget", "value": r["value"]}
        def should_show_widget(self, r): return True

    @register_feature
    class _NotRelevant(_DummyFeature):
        name = "_not_relevant"
        applies_to = ("pair_of_drivers",)
        def is_relevant_for(self, q, r): return 0.1
        def execute(self, **a): raise AssertionError("must not execute")
        def make_widget(self, r): return {}
        def should_show_widget(self, r): return False

    resolved = {"drivers": [{"code": "A"}, {"code": "B"}]}
    results = run_pipeline("any q", resolved)
    names = [f.name for f, _, _ in results]
    assert "_fires" in names
    assert "_not_relevant" not in names
    fires_entry = next(r for r in results if r[0].name == "_fires")
    assert fires_entry[1] == {"ok": True, "value": 7}
    assert fires_entry[2] == {"type": "fires_widget", "value": 7}


def test_run_pipeline_passes_args_by_feature_name_to_execute():
    """args_by_feature is a dict keyed by feature name; each value is the kwargs
    dict for that feature's execute() call."""

    @register_feature
    class _Echo(_DummyFeature):
        name = "_echo"
        applies_to = ("pair_of_drivers",)
        def is_relevant_for(self, q, r): return 1.0
        def execute(self, **a): return {"got": a}
        def make_widget(self, r): return {"type": "echo"}
        def should_show_widget(self, r): return True

    resolved = {"drivers": [{"code": "A"}, {"code": "B"}]}
    results = run_pipeline("q", resolved, args_by_feature={"_echo": {"x": 1, "y": 2}})
    assert results[0][1] == {"got": {"x": 1, "y": 2}}


def test_run_pipeline_suppresses_widget_when_should_show_returns_false():
    """When should_show_widget returns False, the widget slot is None but the
    execute result is still returned (so callers can still inspect it)."""

    @register_feature
    class _Quiet(_DummyFeature):
        name = "_quiet"
        applies_to = ("pair_of_drivers",)
        def is_relevant_for(self, q, r): return 0.8
        def execute(self, **a): return {"available": True, "noise": "yes"}
        def make_widget(self, r): return {"type": "quiet"}
        def should_show_widget(self, r): return False  # always suppress

    resolved = {"drivers": [{"code": "A"}, {"code": "B"}]}
    results = run_pipeline("q", resolved)
    assert len(results) == 1
    feat, result, widget = results[0]
    assert feat.name == "_quiet"
    assert result == {"available": True, "noise": "yes"}
    assert widget is None


def test_run_pipeline_catches_execute_exceptions():
    """If feature.execute() raises, the pipeline records an error result
    instead of propagating. Widget gate sees the error result."""

    @register_feature
    class _Broken(_DummyFeature):
        name = "_broken"
        applies_to = ("pair_of_drivers",)
        def is_relevant_for(self, q, r): return 0.9
        def execute(self, **a): raise RuntimeError("kaboom")
        def make_widget(self, r): return {"type": "broken"}
        def should_show_widget(self, r): return r.get("available", True)

    resolved = {"drivers": [{"code": "A"}, {"code": "B"}]}
    results = run_pipeline("q", resolved)
    assert len(results) == 1
    feat, result, widget = results[0]
    assert feat.name == "_broken"
    assert result == {"available": False, "error": "RuntimeError"}
    # should_show_widget returns r.get("available", True) -> False, so widget is None
    assert widget is None


def test_run_pipeline_populates_audit_log():
    """Every above-threshold feature gets an audit record with executed=True;
    below-threshold ones get executed=False. ts is auto-added."""
    from features.base import clear_audit_log, get_audit_log

    @register_feature
    class _A(_DummyFeature):
        name = "_a"
        applies_to = ("pair_of_drivers",)
        def is_relevant_for(self, q, r): return 0.9
        def execute(self, **a): return {"ok": True}
        def make_widget(self, r): return {"type": "a"}
        def should_show_widget(self, r): return True

    @register_feature
    class _B(_DummyFeature):
        name = "_b"
        applies_to = ("pair_of_drivers",)
        def is_relevant_for(self, q, r): return 0.2
        def execute(self, **a): return {}
        def make_widget(self, r): return {}
        def should_show_widget(self, r): return False

    clear_audit_log()
    resolved = {"drivers": [{"code": "A"}, {"code": "B"}]}
    run_pipeline("q", resolved)
    records = {r["feature_name"]: r for r in get_audit_log()}
    assert records["_a"]["executed"] is True
    assert records["_a"]["widget_emitted"] is True
    assert records["_a"]["relevance_score"] == 0.9
    assert "ts" in records["_a"]
    assert records["_b"]["executed"] is False
    assert records["_b"]["widget_emitted"] is False


def test_run_pipeline_respects_custom_threshold():
    """Passing threshold=0.7 means a 0.6 feature does NOT fire."""

    @register_feature
    class _Mid(_DummyFeature):
        name = "_mid"
        applies_to = ("pair_of_drivers",)
        def is_relevant_for(self, q, r): return 0.6
        def execute(self, **a): raise AssertionError("must not execute at threshold=0.7")
        def make_widget(self, r): return {}
        def should_show_widget(self, r): return False

    resolved = {"drivers": [{"code": "A"}, {"code": "B"}]}
    results = run_pipeline("q", resolved, threshold=0.7)
    assert results == []


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
