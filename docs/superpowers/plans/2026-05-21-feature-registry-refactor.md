# Feature Registry Refactor (Codex Architecture) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reorganize F1Dash so each "feature" (tool + executor + widget builder + relevance predicates) lives in ONE file under `server/features/`. The orchestration (mode classifier + analyzer + answer writer) stays the same — only WHERE feature metadata lives changes. Adding a new analytical feature becomes a single-file change.

**Architecture:** A `Feature` base class + `@register_feature` decorator + startup module-scan over `server/features/`. The existing `tools.py` executor chain, `_make_*_widget` functions in `chat.py`, and `_widgets_from_analysis_evidence` composition become generic registry walks. Confidence-scored relevance predicates and a per-request audit trace make the gate decisions visible. Frontend gains a `widgetRegistry` map indexed by widget type.

**Tech Stack:** Pure Python (decorators + module-walk via `pkgutil`), Hypothesis for property tests, no new dependencies. Front-end stays React; no framework change.

---

## Background

We have ~25 analytical features. Each is currently scattered across 5-6 places: tool definition + executor branch + plan builder + analyzer schema + widget builder + frontend dispatch. Codex's diagnosis: the pain is **insufficient code co-location**, not the wrong agent paradigm. Research (Eclipse extension points, OSGi DS, MCP, Spring AI Skills, ToolGate 2026, EcoAct) validates the pattern.

This plan implements:
1. The core feature-registry pattern Codex recommended
2. Three refinements from research: confidence scores, audit trace, auto-discovery (skip Haiku adjudicator + DSL + DAG per "skip" recommendations)
3. A **validation checkpoint** after one pilot feature — decide whether to migrate the rest

**The plan is incremental.** Build infrastructure first, migrate one pilot feature, validate end-to-end, THEN decide on batch migration. No big-bang.

---

## File Structure

| File | Status | Role |
|---|---|---|
| `server/features/__init__.py` | **Create** | Empty marker for the features package |
| `server/features/base.py` | **Create** | `Feature` ABC, `register_feature` decorator, registry, audit trace |
| `server/features/registry.py` | **Create** | Module-scan, lookup helpers, applies/relevance/widget pipeline |
| `server/features/mini_sectors.py` | **Create** | First pilot — migrate `compare_mini_sectors` |
| `server/tools.py` | **Modify** | Add fallback: registered features auto-extend `TOOL_DEFINITIONS` + execute_tool dispatch |
| `server/chat.py` | **Modify** | `_make_mini_sector_heatmap_widget` removed; widget dispatch reads registry |
| `client/src/components/chat-widgets/widgetRegistry.js` | **Create** | Map widget-type → React component |
| `client/src/components/AnswerRenderer.jsx` | **Modify** | Use widgetRegistry instead of per-type if/else for mini-sectors only (pilot scope) |
| `server/tests/test_feature_registry.py` | **Create** | Hypothesis property tests + registry behaviour |
| `server/tests/test_editorial_search.py` | (untouched) | Already passing |

**Scope of this plan:** infrastructure + ONE feature migration (mini_sectors). The remaining 24 features stay where they are. Validation checkpoint at the end decides next step.

---

## Task 1: Feature base class + registry primitives

**Files:**
- Create: `server/features/__init__.py` (empty)
- Create: `server/features/base.py`
- Test: `server/tests/test_feature_registry.py`

- [ ] **Step 1: Write failing tests**

Create `server/tests/test_feature_registry.py`:

```python
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
    FEATURE_REGISTRY.clear()

    @register_feature
    class _F(_DummyFeature):
        name = "_test_register"

    assert "_test_register" in FEATURE_REGISTRY
    assert FEATURE_REGISTRY["_test_register"].name == "_test_register"


def test_register_feature_rejects_duplicate_names():
    """Re-registering the same name should raise."""
    FEATURE_REGISTRY.clear()

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
```

- [ ] **Step 2: Run to verify red**

```
cd server; python -m pytest tests/test_feature_registry.py -v
```

Expected: tests FAIL with `ModuleNotFoundError: features.base`.

- [ ] **Step 3: Implement `server/features/__init__.py` (empty marker) and `server/features/base.py`**

Create `server/features/__init__.py`:

```python
"""Self-contained analytical features.

Each module under this package defines one Feature subclass. The startup
module-walk in registry.py imports them all, triggering @register_feature
side effects. The rest of the system (tools.py, chat.py, AnswerRenderer)
reads from FEATURE_REGISTRY rather than hardcoding feature knowledge.
"""
```

Create `server/features/base.py`:

```python
"""Feature base class + registration decorator.

Each feature is a subclass of Feature with the five-method contract:
    - applies_to: tuple of entity-type strings (cheap broad filter)
    - is_relevant_for(question, resolved) -> float in [0, 1]
    - execute(**args) -> dict (the actual analysis)
    - make_widget(result) -> dict (widget payload)
    - should_show_widget(result) -> bool

Register with @register_feature; the registry is consulted by tools.py
(for execute_tool dispatch) and chat.py (for widget rendering).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


FEATURE_REGISTRY: dict[str, "Feature"] = {}


class Feature(ABC):
    """One analytical feature, fully self-contained."""

    name: str  # tool name; MUST be set on subclass
    applies_to: tuple[str, ...] = ()  # entity-type preconditions
    tool_schema: dict = {}  # JSON schema for the tool's input args
    required_args: tuple[str, ...] = ()  # arg names that must be present
    description: str = ""  # human description for tool registration

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        # Direct subclasses of Feature must declare a name (string)
        if not hasattr(cls, "name") or not isinstance(getattr(cls, "name", None), str):
            raise TypeError(
                f"Feature subclass {cls.__name__} must set class attribute "
                f"`name` to a string"
            )

    @abstractmethod
    def is_relevant_for(self, question: str, resolved: dict | None) -> float:
        """Return relevance in [0, 1]. ≥ 0.5 fires by default."""

    @abstractmethod
    def execute(self, **args) -> dict:
        """Run the analysis. Return a dict the analyzer + widget consume."""

    @abstractmethod
    def make_widget(self, result: dict) -> dict:
        """Map the result to a widget payload (type + fields)."""

    @abstractmethod
    def should_show_widget(self, result: dict) -> bool:
        """Decide whether the widget for this result is worth rendering."""


def register_feature(cls):
    """Decorator that registers a Feature subclass in FEATURE_REGISTRY by name.

    Usage:
        @register_feature
        class MiniSectorsFeature(Feature):
            name = "compare_mini_sectors"
            ...
    """
    if not isinstance(cls, type) or not issubclass(cls, Feature):
        raise TypeError(f"@register_feature must decorate a Feature subclass; got {cls!r}")

    if cls.name in FEATURE_REGISTRY:
        raise ValueError(
            f"Feature name {cls.name!r} already registered "
            f"(by {type(FEATURE_REGISTRY[cls.name]).__name__})"
        )

    FEATURE_REGISTRY[cls.name] = cls()  # store instance
    return cls
```

- [ ] **Step 4: Run tests to verify green**

```
cd server; python -m pytest tests/test_feature_registry.py -v
```

Expected: 4 tests PASS.

- [ ] **Step 5: Full suite still green**

```
cd server; python -m pytest tests/ -q 2>&1 | tail -3
```

Expected: 492 + 4 = 496 passing.

- [ ] **Step 6: Commit**

```bash
git add server/features/__init__.py server/features/base.py server/tests/test_feature_registry.py
git commit -m "feat(features): Feature base class + register_feature decorator

The minimum infrastructure for the feature-registry refactor. Each
Feature subclass declares:
- name (tool name, must be unique)
- applies_to (entity-type preconditions)
- is_relevant_for(question, resolved) -> float in [0,1]
- execute(**args) -> dict
- make_widget(result) -> dict
- should_show_widget(result) -> bool

@register_feature populates the module-level FEATURE_REGISTRY. Duplicate
names raise; missing 'name' on a subclass raises at class definition.

Plan: docs/superpowers/plans/2026-05-21-feature-registry-refactor.md Task 1"
```

---

## Task 2: Auto-discovery via module-scan

**Files:**
- Create: `server/features/registry.py`
- Test: extend `server/tests/test_feature_registry.py`

- [ ] **Step 1: Write failing tests**

Append to `server/tests/test_feature_registry.py`:

```python
from features.registry import discover_features, candidates_for, rank_by_relevance


def test_discover_features_imports_all_modules_under_features_package():
    """discover_features walks server/features/ and imports every .py module,
    triggering @register_feature side effects."""
    FEATURE_REGISTRY.clear()
    discover_features()
    # The pilot feature (Task 3) will register itself once it lands. For now,
    # just assert discover_features runs without error and returns a count.
    count = discover_features()
    assert isinstance(count, int)
    assert count >= 0


def test_candidates_for_filters_by_applies_to():
    """candidates_for returns features whose applies_to is satisfied by the
    resolved entity types."""
    FEATURE_REGISTRY.clear()

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
    FEATURE_REGISTRY.clear()

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
    FEATURE_REGISTRY.clear()

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
```

- [ ] **Step 2: Run to verify red**

Expected: 4 tests FAIL with `ImportError: cannot import name 'discover_features'`.

- [ ] **Step 3: Implement `server/features/registry.py`**

```python
"""Feature discovery, candidate filtering, and relevance ranking."""
from __future__ import annotations

import importlib
import logging
import pkgutil
from typing import Iterable

from features.base import Feature, FEATURE_REGISTRY

logger = logging.getLogger(__name__)


def discover_features() -> int:
    """Walk the `features` package and import every submodule.

    Each module's @register_feature decorator runs as a side effect of
    import, populating FEATURE_REGISTRY. Idempotent — re-importing is a
    no-op because the registry rejects duplicate names.

    Returns the number of features in the registry after discovery.
    """
    import features  # the package itself
    count_before = len(FEATURE_REGISTRY)
    for module_info in pkgutil.iter_modules(features.__path__, prefix="features."):
        if module_info.name in ("features.base", "features.registry"):
            continue
        try:
            importlib.import_module(module_info.name)
        except Exception as e:
            logger.warning(
                "discover_features: failed to import %s: %s",
                module_info.name, type(e).__name__,
            )
    return len(FEATURE_REGISTRY) - count_before + len(FEATURE_REGISTRY)


def _resolved_entity_types(resolved: dict | None) -> set[str]:
    """Map a resolver output to the set of entity-type strings present.

    Conventions:
        - 2+ drivers → "pair_of_drivers"
        - 1+ drivers → "driver"
        - team present → "team"
        - circuit_slug present → "circuit"
        - round_number present + session_type in {R, S} → "race_session"
        - round_number present + session_type in {Q, SQ} → "quali_session"
        - round_number present + session_type in {FP1, FP2, FP3} → "practice_session"
        - lap_number present → "lap"
    """
    if not resolved:
        return set()
    types: set[str] = set()
    drivers = resolved.get("drivers") or []
    if len(drivers) >= 2:
        types.add("pair_of_drivers")
    if len(drivers) >= 1:
        types.add("driver")
    if resolved.get("team"):
        types.add("team")
    if resolved.get("circuit_slug"):
        types.add("circuit")
    session = (resolved.get("session_type") or "").upper()
    if resolved.get("round_number"):
        if session in ("R", "S"):
            types.add("race_session")
        elif session in ("Q", "SQ"):
            types.add("quali_session")
        elif session in ("FP1", "FP2", "FP3"):
            types.add("practice_session")
        types.add("session")  # any session
    if resolved.get("lap_number") is not None:
        types.add("lap")
    return types


def candidates_for(resolved: dict | None) -> list[Feature]:
    """Return features whose applies_to is satisfied by the resolved entities."""
    types = _resolved_entity_types(resolved)
    out: list[Feature] = []
    for feat in FEATURE_REGISTRY.values():
        if not feat.applies_to:
            out.append(feat)
            continue
        if all(req in types for req in feat.applies_to):
            out.append(feat)
    return out


def rank_by_relevance(
    question: str,
    resolved: dict | None,
    candidates: Iterable[Feature],
) -> list[tuple[Feature, float]]:
    """Ask each candidate is_relevant_for, return [(feature, score)] sorted desc.

    Scores are clamped to [0.0, 1.0]. Predicate exceptions are caught and
    treated as 0.0 (skip the feature).
    """
    scored: list[tuple[Feature, float]] = []
    for feat in candidates:
        try:
            raw = float(feat.is_relevant_for(question, resolved))
        except Exception as e:
            logger.warning(
                "is_relevant_for raised for %s: %s",
                feat.name, type(e).__name__,
            )
            raw = 0.0
        score = max(0.0, min(1.0, raw))
        scored.append((feat, score))
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored
```

- [ ] **Step 4: Run tests**

```
cd server; python -m pytest tests/test_feature_registry.py -v
cd server; python -m pytest tests/ -q 2>&1 | tail -3
```

Expected: 8 tests PASS. Full suite 500 passing.

- [ ] **Step 5: Commit**

```bash
git add server/features/registry.py server/tests/test_feature_registry.py
git commit -m "feat(features): auto-discovery + candidates_for + rank_by_relevance

discover_features walks server/features/ via pkgutil and imports every
submodule, triggering @register_feature side effects. Idempotent.

candidates_for(resolved) filters by applies_to against the entity-type
set derived from the resolver output (pair_of_drivers, driver, team,
circuit, race_session, quali_session, lap).

rank_by_relevance asks each candidate is_relevant_for, clamps scores to
[0,1], catches exceptions (treats as 0.0), returns sorted desc.

Plan: docs/superpowers/plans/2026-05-21-feature-registry-refactor.md Task 2"
```

---

## Task 3: Audit trace + per-decision logging

**Files:**
- Modify: `server/features/base.py` (add audit hook)
- Test: extend `server/tests/test_feature_registry.py`

- [ ] **Step 1: Write failing tests**

Append:

```python
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
```

- [ ] **Step 2: Verify red**

Expected: ImportError on `audit_log`.

- [ ] **Step 3: Add audit primitives to `server/features/base.py`**

Append to `server/features/base.py`:

```python
import time

_AUDIT_LOG: list[dict] = []


def audit_log(**fields) -> None:
    """Append a feature-decision record. Best-effort, never raises.

    Records are kept in-memory for the current process. In production,
    a periodic flush to JSONL would persist them; for hobby-scale this
    is fine.
    """
    try:
        fields["ts"] = time.time()
        _AUDIT_LOG.append(fields)
    except Exception:
        pass  # audit must never break the main flow


def get_audit_log() -> list[dict]:
    return list(_AUDIT_LOG)


def clear_audit_log() -> None:
    _AUDIT_LOG.clear()
```

- [ ] **Step 4: Run tests + commit**

```
cd server; python -m pytest tests/test_feature_registry.py -v
cd server; python -m pytest tests/ -q 2>&1 | tail -3
```

Expected: 10 tests PASS. Full suite 502.

```bash
git add server/features/base.py server/tests/test_feature_registry.py
git commit -m "feat(features): in-memory audit log for feature decisions

audit_log(**fields) appends a timestamped record to the module-level
_AUDIT_LOG. get_audit_log() and clear_audit_log() expose it.

Records carry: feature_name, question, applies_to_passed,
relevance_score, executed, widget_emitted, duration_ms, ts.

In-memory only — flushing to JSONL is a follow-up (out of scope here).

Plan: docs/superpowers/plans/2026-05-21-feature-registry-refactor.md Task 3"
```

---

## Task 4: Migrate mini_sectors as the pilot feature

**Files:**
- Create: `server/features/mini_sectors.py`
- (No changes to chat.py / tools.py yet — the existing wiring still works in parallel)
- Test: `server/tests/test_features_mini_sectors.py`

- [ ] **Step 1: Write failing tests**

Create `server/tests/test_features_mini_sectors.py`:

```python
import pytest


def test_mini_sectors_feature_registered_after_discover():
    from features.base import FEATURE_REGISTRY
    from features.registry import discover_features
    FEATURE_REGISTRY.clear()
    discover_features()
    assert "compare_mini_sectors" in FEATURE_REGISTRY


def test_mini_sectors_applies_to_pair_and_lap():
    from features.base import FEATURE_REGISTRY
    from features.registry import discover_features
    FEATURE_REGISTRY.clear()
    discover_features()
    feat = FEATURE_REGISTRY["compare_mini_sectors"]
    assert "pair_of_drivers" in feat.applies_to
    assert "lap" in feat.applies_to


def test_mini_sectors_relevance_high_for_where_questions():
    from features.base import FEATURE_REGISTRY
    from features.registry import discover_features
    FEATURE_REGISTRY.clear()
    discover_features()
    feat = FEATURE_REGISTRY["compare_mini_sectors"]
    score_where = feat.is_relevant_for("Where did Norris gain time?", {})
    score_random = feat.is_relevant_for("What is F1?", {})
    assert score_where > score_random
    assert score_where >= 0.5  # above default threshold


def test_mini_sectors_relevance_high_for_qualifying_battle_mode():
    from features.base import FEATURE_REGISTRY
    from features.registry import discover_features
    FEATURE_REGISTRY.clear()
    discover_features()
    feat = FEATURE_REGISTRY["compare_mini_sectors"]
    score = feat.is_relevant_for(
        "Why was Norris faster?",
        {"analysis_mode": "qualifying_battle"},
    )
    assert score >= 0.5


def test_mini_sectors_should_show_widget_suppresses_tiny_delta():
    from features.base import FEATURE_REGISTRY
    from features.registry import discover_features
    FEATURE_REGISTRY.clear()
    discover_features()
    feat = FEATURE_REGISTRY["compare_mini_sectors"]
    assert feat.should_show_widget({"total_delta_s": 0.4}) is True
    assert feat.should_show_widget({"total_delta_s": 0.01}) is False
    assert feat.should_show_widget({}) is False


def test_mini_sectors_make_widget_passes_through_to_existing_builder():
    """The Feature's make_widget should produce the same widget shape
    as the existing _make_mini_sector_heatmap_widget in chat.py."""
    from features.base import FEATURE_REGISTRY
    from features.registry import discover_features
    import chat
    FEATURE_REGISTRY.clear()
    discover_features()
    feat = FEATURE_REGISTRY["compare_mini_sectors"]
    sample_result = {
        "available": True,
        "driver_a": "NOR", "driver_b": "PIA",
        "lap_number": 21, "round_number": 7, "session_type": "Q",
        "n_segments": 25, "weather_state": "dry",
        "segments": [],
        "cumulative_delta": [(0, 0)],
        "total_delta_s": 0.187,
        "segments_won_a": 14, "segments_won_b": 8, "segments_tied": 3,
        "drs_mix_warning": False,
    }
    via_feature = feat.make_widget(sample_result)
    via_chat = chat._make_mini_sector_heatmap_widget(sample_result)
    assert via_feature["type"] == "mini_sector_heatmap"
    assert via_feature["type"] == via_chat["type"]
    assert via_feature["driver_a"] == via_chat["driver_a"]
    assert via_feature["total_delta_s"] == via_chat["total_delta_s"]
```

- [ ] **Step 2: Verify red**

Expected: tests fail because `server/features/mini_sectors.py` doesn't exist.

- [ ] **Step 3: Create `server/features/mini_sectors.py`**

```python
"""Mini-sectors heatmap feature. Migrated from chat.py / tools.py / f1_data.py.

This is the pilot feature for the registry refactor. The underlying
analysis function stays in f1_data.py; this module wraps it with the
applies_to + is_relevant_for + make_widget + should_show_widget surface
the registry expects.
"""
from __future__ import annotations

import f1_data
from features.base import Feature, register_feature


_RELEVANT_KEYWORDS = (
    "where", "sector", "segment", "faster", "slower", "lose time",
    "gain time", "lost", "gained", "split", "lap-by-lap",
)

# Mode-based bonus — if the resolver puts us in qualifying_battle, mini-sectors
# are usually useful even when the question doesn't say "where".
_RELEVANT_MODES = frozenset({"qualifying_battle", "driver_comparison"})


@register_feature
class MiniSectorsFeature(Feature):
    name = "compare_mini_sectors"
    applies_to = ("pair_of_drivers", "lap")
    description = (
        "Compare two drivers across 25 equal-distance mini-sectors of a "
        "single lap. Returns per-segment delta + cumulative delta along "
        "distance, segments-won counts, DRS-mix warning."
    )
    required_args = ("driver_a", "driver_b", "lap_number", "round_number")
    tool_schema = {
        "type": "object",
        "properties": {
            "driver_a": {"type": "string"},
            "driver_b": {"type": "string"},
            "lap_number": {"type": "integer"},
            "round_number": {"type": "integer"},
            "session_type": {"type": "string", "default": "Q"},
            "n": {"type": "integer", "default": 25},
        },
        "required": list(required_args),
    }

    def is_relevant_for(self, question: str, resolved: dict | None) -> float:
        q = (question or "").lower()
        mode = (resolved or {}).get("analysis_mode")

        score = 0.0
        if mode in _RELEVANT_MODES:
            score = max(score, 0.7)
        if any(kw in q for kw in _RELEVANT_KEYWORDS):
            score = max(score, 0.8)
        return score

    def execute(self, **args) -> dict:
        return f1_data.compare_mini_sectors(
            driver_a=args["driver_a"],
            driver_b=args["driver_b"],
            lap_number=args["lap_number"],
            round_number=args["round_number"],
            session_type=args.get("session_type", "Q"),
            n=args.get("n", 25),
        )

    def make_widget(self, result: dict) -> dict:
        # Delegate to the existing chat.py builder to keep widget shape
        # identical. Once all features are migrated, the builder will move
        # here and the chat.py function will be removed.
        import chat
        return chat._make_mini_sector_heatmap_widget(result)

    def should_show_widget(self, result: dict) -> bool:
        if not result.get("available", True):
            return False  # availability=False → render-degraded path, but still emit widget? See note below
        total = result.get("total_delta_s")
        if total is None:
            return False
        return abs(total) >= 0.05
```

**Design note in the code:** the "available: False" case is intentionally NOT shown as a widget — the analyzer prompt will mention "data not available". The existing widget builder returns a `type: mini_sector_heatmap` with `available: False`, which the React widget renders as a friendly message. We keep that shape (the React widget already handles it) but the gate at this layer says "don't even attempt to render unless we have meaningful data." This is a deliberate change from current behaviour; the user can revert by changing the gate.

- [ ] **Step 4: Run tests + full suite**

```
cd server; python -m pytest tests/test_features_mini_sectors.py -v
cd server; python -m pytest tests/ -q 2>&1 | tail -3
```

Expected: 6 mini-sectors tests PASS. Full suite 508 passing (502 + 6 new).

- [ ] **Step 5: Commit**

```bash
git add server/features/mini_sectors.py server/tests/test_features_mini_sectors.py
git commit -m "feat(features): pilot — migrate compare_mini_sectors to feature registry

First feature migrated under the new pattern. The underlying analysis
function (f1_data.compare_mini_sectors) is unchanged; this module wraps
it with the Feature contract:
- applies_to: (pair_of_drivers, lap)
- is_relevant_for: scores 0.7 for qualifying_battle/driver_comparison mode;
  0.8 if question mentions where/sector/faster/etc; max of the two
- execute: passthrough to f1_data
- make_widget: delegates to chat._make_mini_sector_heatmap_widget (shape
  unchanged; will move into this file once all features migrate)
- should_show_widget: suppress if total_delta_s < 0.05s or unavailable

This is the PILOT — the rest of the codebase (chat.py dispatch,
tools.py executor, AnswerRenderer.jsx) is UNCHANGED. Validation in
Task 5 confirms the registry's view of the feature matches the
existing wiring's behaviour.

Plan: docs/superpowers/plans/2026-05-21-feature-registry-refactor.md Task 4"
```

---

## Task 5: Validation checkpoint — does it actually work end-to-end?

**Files:**
- No code changes; validation only.

This is the **decide whether to continue** gate. Before we migrate the remaining 24 features, prove the pattern works for mini_sectors in isolation.

- [ ] **Step 1: Confirm registry sees the pilot feature**

```bash
cd C:/Users/sanja/Documents/Nerd/F1Dash; python -c "
import sys; sys.path.insert(0, 'server')
from dotenv import load_dotenv; load_dotenv('.env')
from features.registry import discover_features
from features.base import FEATURE_REGISTRY
discover_features()
print(f'{len(FEATURE_REGISTRY)} feature(s) registered:')
for name, feat in FEATURE_REGISTRY.items():
    print(f'  - {name}  applies_to={feat.applies_to}')
"
```

Expected output:
```
1 feature(s) registered:
  - compare_mini_sectors  applies_to=('pair_of_drivers', 'lap')
```

- [ ] **Step 2: Smoke-test relevance scoring on real questions**

```bash
cd C:/Users/sanja/Documents/Nerd/F1Dash; python -c "
import sys; sys.path.insert(0, 'server')
from dotenv import load_dotenv; load_dotenv('.env')
from features.registry import discover_features, candidates_for, rank_by_relevance
discover_features()

# Question 1: clear mini-sectors question
resolved = {'drivers': [{'code': 'NOR'}, {'code': 'PIA'}], 'lap_number': 21,
            'session_type': 'Q', 'round_number': 7,
            'analysis_mode': 'qualifying_battle'}
cands = candidates_for(resolved)
ranked = rank_by_relevance('Where did Norris gain time vs Piastri?', resolved, cands)
print('Q1 (clear mini-sectors question):')
for f, s in ranked:
    print(f'  {f.name}: {s:.2f}')

# Question 2: unrelated to mini-sectors
ranked = rank_by_relevance('What is the weather forecast?', resolved, cands)
print()
print('Q2 (unrelated):')
for f, s in ranked:
    print(f'  {f.name}: {s:.2f}')

# Question 3: missing entities — should drop out at applies_to
resolved_thin = {'drivers': [], 'session_type': 'Q', 'round_number': 7}
cands = candidates_for(resolved_thin)
print()
print(f'Q3 (no drivers): {len(cands)} candidate(s)')
"
```

Expected:
- Q1 shows `compare_mini_sectors: 0.80` (keyword match wins)
- Q2 shows `compare_mini_sectors: 0.70` (mode bonus only — still fires)
- Q3 shows 0 candidates (no pair_of_drivers)

If Q2 fires too aggressively (the user complaint was features firing when not useful), the predicate may need tuning. Document the tuning decision and adjust.

- [ ] **Step 3: Run the full chat E2E with mini-sectors question**

Start uvicorn:
```bash
cd C:/Users/sanja/Documents/Nerd/F1Dash/server; python -m uvicorn main:app --reload --port 8000
```

In the chat: *"Compare Norris and Piastri's fastest 2024 Imola Q3 lap. Where did Piastri lose time?"*

Expected:
- The existing path runs (chat.py + tools.py wiring is unchanged for now — mini-sectors fires via the OLD path).
- The new feature module is registered but NOT YET wired into execute_tool dispatch — it's parallel infrastructure.
- The widget renders correctly via the existing path.

This is intentional. Task 6 wires the registry into the dispatch; Task 5 just confirms the parallel infrastructure works.

- [ ] **Step 4: Audit-log inspection**

```bash
cd C:/Users/sanja/Documents/Nerd/F1Dash; python -c "
import sys; sys.path.insert(0, 'server')
from dotenv import load_dotenv; load_dotenv('.env')
from features.registry import discover_features, candidates_for, rank_by_relevance
from features.base import audit_log, get_audit_log, clear_audit_log
discover_features()
clear_audit_log()

# Simulate one decision pass
resolved = {'drivers': [{'code': 'NOR'}, {'code': 'PIA'}], 'lap_number': 21,
            'session_type': 'Q', 'round_number': 7,
            'analysis_mode': 'qualifying_battle'}
cands = candidates_for(resolved)
for feat, score in rank_by_relevance('Where did Norris gain time?', resolved, cands):
    audit_log(
        feature_name=feat.name,
        question='Where did Norris gain time?',
        applies_to_passed=True,
        relevance_score=score,
        executed=score >= 0.5,
        widget_emitted=False,
        duration_ms=0,
    )

import json
for r in get_audit_log():
    print(json.dumps(r, default=str, indent=2))
"
```

Expected: one JSON record per feature, with relevance_score, executed flag, timestamp.

- [ ] **Step 5: Decision point**

Based on results so far, decide one of three paths:

1. **Continue migration.** Pattern works as expected. Migrate the remaining ~24 features in a follow-up plan (one-feature-per-PR or batched).
2. **Refine the contract.** Predicate scoring needs adjustment, or applies_to taxonomy needs more entity types. Iterate before continuing.
3. **Abandon and revert.** The pattern doesn't fit. Delete `server/features/` and `tests/test_feature_registry*.py`. The existing path is untouched, so reverting is free.

Write the decision in this commit message:

```bash
git commit --allow-empty -m "validation: pilot feature registry — DECISION: <continue/refine/abandon>

<paragraph explaining what you saw in the smoke tests and audit log,
and why you made that call>

Plan: docs/superpowers/plans/2026-05-21-feature-registry-refactor.md Task 5"
```

---

## Validation Checklist

- [ ] Full backend suite passes after each task (492 → 496 → 500 → 502 → 508).
- [ ] `discover_features()` finds `compare_mini_sectors` after Task 4.
- [ ] `candidates_for(resolved)` correctly drops mini_sectors when drivers/lap are missing.
- [ ] `rank_by_relevance` returns scores in [0, 1] and is sorted descending.
- [ ] The Task 5 smoke test shows the audit log populating with one record per feature decision.
- [ ] Live chat smoke test (Task 5 Step 3) still works — existing path is unaffected by parallel registry infrastructure.

---

## Risks and Open Questions

| Risk | Trigger | Proposed resolution | Decision needed by |
|---|---|---|---|
| **Predicate keyword matching too loose** — `"faster"` matches every quali question, so mini_sectors fires on every quali_battle whether useful or not | Task 5 smoke test | If audit shows mini_sectors firing on questions where it isn't useful, narrow the keyword list and/or raise the threshold from 0.5 to 0.6 | Task 5 decision |
| **Auto-discovery breaks at import time** if a feature module has an import error (e.g., circular import to f1_data) | Task 4 | `discover_features` already catches Exception and logs WARN; the broken feature simply doesn't register. Verify the warning surfaces in Task 5 smoke test | Task 5 |
| **Circular import: features.mini_sectors → chat (for make_widget) → ??? → features** | Task 4 | The `import chat` is inside `make_widget()`, not at module top level — lazy import sidesteps the cycle. Verify | Task 4 testing |
| **The pilot proves the pattern but later features (analyze_qualifying_battle, race_pace_battle) have richer composite shapes that the simple Feature contract doesn't fit** | When migrating later features | Add an optional `compose_with(other_features_results) -> result` hook on Feature for composite features; mini_sectors doesn't need it. Out of scope for this plan | Future plan |
| **The audit log grows unbounded in long-running uvicorn processes** | Production | Cap _AUDIT_LOG at last 1,000 entries; rotate or flush to JSONL daily. Add in Task 3 follow-up if it matters | Post-V1 |

---

## Non-Goals

- **Migration of remaining 24 features.** This plan migrates ONE pilot. Subsequent migrations are separate plans (decide in Task 5 whether to continue).
- **Replacing tools.py entirely.** tools.py's existing chain is untouched. The registry is parallel infrastructure for now.
- **Replacing _make_*_widget functions in chat.py.** Same — they stay until ALL features migrate.
- **Frontend widgetRegistry.** Stays as today for mini_sectors. Once all backend features migrate, the frontend follows in a separate plan.
- **Haiku adjudicator for ambiguous predicates.** Skipped per research recommendation; defer until audit log shows real ambiguity in production.
- **Persistent audit log (JSONL flush, rotation).** In-memory only for V1.

---

## References

- Codex's diagnosis (conversation, 2026-05-21): "The code does not need dynamic dependency planning; it needs metadata ownership."
- [Eclipse PDE Extensions and Extension Points](https://help.eclipse.org/latest/topic/org.eclipse.pde.doc.user/concepts/extension.htm) — 25-year-old precedent for the same split between declarative metadata and imperative execution.
- [MCP Specification 2025-11-25](https://modelcontextprotocol.io/specification/2025-11-25) — Anthropic's self-describing tool protocol.
- [Spring AI Agent Skills (Jan 2026)](https://spring.io/blog/2026/01/13/spring-ai-generic-agent-skills/) — closest published analog to our pattern.
- [EcoAct (NeurIPS 2024) — arXiv:2411.01643](https://arxiv.org/abs/2411.01643) — selective tool registration cuts compute >50% vs dumping all tools into context.
- [ToolGate (2026) — arXiv:2601.04688](https://arxiv.org/pdf/2601.04688) — formalizes preconditions/postconditions on tools.
- [SoK: Agentic Skills (2026) — arXiv:2602.20867](https://arxiv.org/html/2602.20867v1) — maps LLM skill systems to STRIPS/PDDL preconditions.
- Python plugin idiom — [packaging.python.org guide](https://packaging.python.org/en/latest/guides/creating-and-discovering-plugins/) — decorator + `pkgutil.iter_modules`.
