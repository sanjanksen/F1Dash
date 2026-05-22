# Feature Registry Full Migration Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate **every** F1Dash feature — tool definition, executor, widget builder, system prompt mention, frontend dispatch — into self-contained modules under `server/features/`. End state: `tools.py` is a thin registry shell, `chat.py` has no per-feature widget builders, `AnswerRenderer.jsx` is a single `widgetRegistry` map. Adding a feature becomes one new file + one widget component.

**Architecture:** Builds on the pilot landed on `features/2026-05-21-feature-registry-refactor` (see `docs/superpowers/plans/2026-05-21-feature-registry-refactor.md`). That plan delivered the `Feature` ABC + `@register_feature` decorator + `discover_features` + `candidates_for` + `rank_by_relevance` + audit log + one migrated feature (`compare_mini_sectors`), with predicate scoring tuned via Codex's "mode-as-eligibility-gate" pattern. This plan finishes the job.

**Tech Stack:** Pure Python on the backend (no new deps). React on the frontend (no new deps; replace if/else dispatch with a map).

---

## Background — What's Already Done (Phase A)

The pilot branch `features/2026-05-21-feature-registry-refactor` shipped:

| Module | Role | Status |
|---|---|---|
| `server/features/base.py` | `Feature` ABC + `@register_feature` + `FEATURE_REGISTRY` + audit log | Done |
| `server/features/registry.py` | `discover_features` + `candidates_for` + `rank_by_relevance` | Done |
| `server/features/mini_sectors.py` | Pilot feature wrapping `f1_data.compare_mini_sectors` | Done |
| `server/tests/test_feature_registry.py` | 11 tests | Done |
| `server/tests/test_features_mini_sectors.py` | 8 tests (incl. predicate-tuning tests) | Done |

**Critical property:** The pilot infrastructure is **dormant in production**. `chat.py` and `tools.py` do not import from `features/`. The pilot proved the pattern works; this plan wires it in.

Suite is at **511 passing**.

---

## Scope — What This Plan Covers

**In scope:**
- Wire the registry into the live chat path (so `compare_mini_sectors` runs through the registry, not the old executor)
- Unify the two orchestration paths (deterministic `_widgets_from_preloaded` + agentic `_widgets_from_analysis_evidence`) into one registry-driven path
- Migrate all **25 user-facing features** to their own modules under `server/features/`
- Migrate all **12 widget builders** from `chat.py` into their feature modules
- Replace `AnswerRenderer.jsx`'s if/else dispatch with a `widgetRegistry` map
- Delete the now-empty executor chain in `tools.py` (becomes a thin shell that exports schemas auto-derived from FEATURE_REGISTRY)
- JSONL persistence for the audit log (optional; gated on Phase E decision)

**Out of scope:**
- The 7 **agentic-only helpers** (`extract_corner_profiles`, `get_race_control_messages`, `get_intervals`, `get_live_position_timeline`, `get_team_radio`, `analyze_weather_pace_correlation`, `analyze_override_usage`). These are internal helpers called by other tools, not user-picked features. They stay as functions in `tools.py` or get moved to `f1_data.py` — but they do not become `Feature` subclasses.
- Changes to `f1_data.py` analysis functions. Each feature module imports from `f1_data.py` unchanged.
- Changes to `resolver.py`. The entity-resolution layer is unchanged.
- Changes to `circuit_profiles.py`, `driver_styles.py`, `team_car_profiles.py`, `energy_2026.py`. Static knowledge layers stay where they are; features that consume them just import them.

**Decision points (must answer before starting):**
1. **Do agentic-only helpers also migrate?** Plan default: **no** (they stay as private helpers, no schema, no widget). If you want them migrated for uniformity, add Phase D batch E.
2. **Keep the 5-min disk cache for sessions?** Plan default: **yes**, unchanged.
3. **Does the LLM see ALL registered features as tools, or a mode-filtered subset?** Plan default: **all** in the agentic loop; deterministic mode-classifier path uses `candidates_for` to narrow.

---

## File Structure (End State)

```
server/
├── features/
│   ├── __init__.py
│   ├── base.py                     # Feature ABC + register_feature + FEATURE_REGISTRY + audit_log
│   ├── registry.py                 # discover_features + candidates_for + rank_by_relevance + run_pipeline (new)
│   ├── mini_sectors.py             # (already migrated)
│   ├── qualifying_battle.py        # NEW
│   ├── race_pace_battle.py         # NEW
│   ├── corner_profiles.py          # NEW
│   ├── stint_degradation.py        # NEW
│   ├── energy_management.py        # NEW
│   ├── active_aero.py              # NEW
│   ├── undercut_overcut.py         # NEW
│   ├── pit_stop_analysis.py        # NEW
│   ├── circuit_profile.py          # NEW
│   ├── circuit_corners.py          # NEW
│   ├── team_performance.py         # NEW (composite)
│   ├── driver_race_story.py        # NEW (composite)
│   ├── driver_weekend_overview.py  # NEW (composite)
│   ├── team_weekend_overview.py    # NEW (composite)
│   ├── race_report.py              # NEW (composite)
│   ├── head_to_head.py             # NEW
│   ├── team_circuit_fit.py         # NEW
│   ├── cornering_loads.py          # NEW
│   ├── race_cornering_profile.py   # NEW
│   ├── team_telemetry_traits.py    # NEW
│   ├── driver_style_profile.py     # NEW
│   ├── team_car_profile.py         # NEW
│   ├── historical_circuit_performance.py  # NEW
│   ├── search_editorial.py         # NEW
│   ├── safety_car_periods.py       # NEW
│   ├── session_weather.py          # NEW
│   ├── fp_summary.py               # NEW
│   └── lookups/                    # SUB-PACKAGE for pure-lookup features
│       ├── __init__.py
│       ├── standings.py            # NEW (driver + constructor + season_stats)
│       ├── results.py              # NEW (race, qualifying, sprint, sprint_q, session)
│       ├── schedule.py             # NEW (season_schedule)
│       ├── lap_data.py             # NEW (driver_lap_times, lap_telemetry, sector_comparison, telemetry_comparison)
│       ├── strategy.py             # NEW (driver_strategy)
│       ├── timing.py               # NEW (clean_pace, track_position, qualifying_progression, fastest_laps, speed_trap)
│       └── circuit_lookups.py      # NEW (circuit_details, circuit_track_map)
├── tools.py                        # SHRINKS to thin shell — exports auto-derived schemas
├── chat.py                         # SHRINKS — widget builders gone, orchestration generic
├── f1_data.py                      # UNCHANGED
└── ...

client/src/components/
├── AnswerRenderer.jsx              # SIMPLIFIED — widgetRegistry map dispatch
└── chat-widgets/
    ├── widgetRegistry.js           # NEW — single source of truth for widget-type → component
    └── (existing components unchanged)
```

---

## Migration Phases — PROGRESS

```
✅ Phase A   Pilot + 1 feature + predicate tuning            DONE
✅ Phase B   Wire registry into live path                    DONE (4 commits)
✅ Phase C   Unify orchestration                             DONE (3 commits)
✅ Phase D1  Pure lookups (21 features, 7 sub-modules)       DONE (8 commits)
⏳ Phase D2  Widget-bearing analyses (8 features)            NEXT
📋 Phase D3  Context & style (6 features)                    pending
📋 Phase D4  Cornering variants (2 features)                 pending
📋 Phase D5  Composites (4 features)                         pending
📋 Phase D6  Remaining (~5 features)                         pending
📋 Phase E   Cutover                                         pending
📋 Phase F   Frontend widgetRegistry                         pending
```

**Resume state (2026-05-21 checkpoint):**
- Branch: `features/2026-05-21-feature-registry-refactor` (not pushed)
- Latest commit: `130353f`
- Suite: **555 passing**
- Already-registered features (22): `compare_mini_sectors` + 21 lookups under `server/features/lookups/`
- Total commits on branch: 22

**To resume:** Read this plan doc top-to-bottom, then dispatch Phase D2 subagent following the migration template. The 8 features to migrate in D2 are documented in the "Phase D — Migrate the 25 Features in 6 Batches" section. Two of them (`analyze_qualifying_battle`, `compare_corner_profiles`) are CROSS-FEATURE and stay dormant — `chat.py`'s `_CROSS_FEATURE_TOOLS` set keeps the legacy composer handling them. The other 6 take the registry path automatically as soon as they're registered.

Total post-Phase-A original estimate: ~17 tasks, ~27 hours. Completed so far: 10 tasks (~9 hours). Remaining: ~7 tasks (~18 hours).

---

## Phase B — Wire Registry Into Live Chat Path

**Goal:** Make the pilot feature (`compare_mini_sectors`) actually run through `FEATURE_REGISTRY` in production requests. Old executor path stays as fallback. The audit log starts populating with real requests.

### Task B1: Auto-derive tool schemas from FEATURE_REGISTRY

**Files:**
- Modify: `server/tools.py`
- Modify: `server/conftest.py` (lift the autouse fixture from `test_features_mini_sectors.py`)
- Test: `server/tests/test_tools_registry_integration.py` (new)

- [ ] **Step 1: Lift the autouse-fixture to conftest.py**

Move the `_reset_feature_module` fixture from `server/tests/test_features_mini_sectors.py` into `server/conftest.py`, generalized to clear ALL `features.*` modules from `sys.modules`. This unblocks every future feature test from copy-pasting the dance.

```python
@pytest.fixture(autouse=False)
def reset_feature_registry():
    """Snapshot FEATURE_REGISTRY and clear cached features.* modules so
    discover_features() re-runs decorators. Opt-in (not autouse=True) so
    tests that don't touch the registry aren't slowed down."""
    from features.base import FEATURE_REGISTRY
    saved = dict(FEATURE_REGISTRY)
    FEATURE_REGISTRY.clear()
    cleared_mods = [m for m in list(sys.modules) if m.startswith("features.") and m not in ("features.base", "features.registry")]
    for m in cleared_mods:
        sys.modules.pop(m, None)
    yield
    FEATURE_REGISTRY.clear()
    FEATURE_REGISTRY.update(saved)
```

Update `test_features_mini_sectors.py` to use the shared fixture via `pytest.mark.usefixtures("reset_feature_registry")` or by removing the local copy and depending on the shared one with `autouse=True` in a module-level conftest.

- [ ] **Step 2: Write failing test**

Create `server/tests/test_tools_registry_integration.py`:

```python
import pytest

@pytest.fixture(autouse=True)
def _reset(reset_feature_registry):
    pass

def test_anthropic_tool_definitions_includes_registry_features():
    """TOOL_DEFINITIONS should auto-extend from FEATURE_REGISTRY."""
    from features.registry import discover_features
    discover_features()
    import tools
    names = {t["name"] for t in tools.TOOL_DEFINITIONS}
    assert "compare_mini_sectors" in names

def test_openai_tool_definitions_includes_registry_features():
    from features.registry import discover_features
    discover_features()
    import tools
    names = {t["function"]["name"] for t in tools.OPENAI_TOOL_DEFINITIONS}
    assert "compare_mini_sectors" in names

def test_execute_tool_dispatches_to_registered_feature():
    """If a tool name is in FEATURE_REGISTRY, execute_tool calls feature.execute()."""
    from features.registry import discover_features
    from features.base import FEATURE_REGISTRY
    discover_features()
    import tools
    # Stub the underlying f1_data call to avoid real telemetry
    import f1_data
    real = f1_data.compare_mini_sectors
    f1_data.compare_mini_sectors = lambda **kw: {"stub": True, "args_seen": kw}
    try:
        result = tools.execute_tool("compare_mini_sectors", {
            "driver_a": "NOR", "driver_b": "PIA",
            "lap_number": 21, "round_number": 7,
            "session_type": "Q", "n": 25,
        })
        assert result == {"stub": True, "args_seen": {
            "driver_a": "NOR", "driver_b": "PIA",
            "lap_number": 21, "round_number": 7,
            "session_type": "Q", "n": 25,
        }}
    finally:
        f1_data.compare_mini_sectors = real
```

- [ ] **Step 3: Implement schema auto-extension and registry-dispatch fallback**

In `tools.py`, at the end of the existing static `TOOL_DEFINITIONS` / `OPENAI_TOOL_DEFINITIONS` construction (and after the file has finished defining `execute_tool`):

```python
from features.registry import discover_features
from features.base import FEATURE_REGISTRY

# Discover all feature modules at import time and extend the static schemas.
discover_features()

def _feature_to_anthropic_schema(feat) -> dict:
    return {
        "name": feat.name,
        "description": feat.description or "",
        "input_schema": feat.tool_schema or {"type": "object", "properties": {}},
    }

def _feature_to_openai_schema(feat) -> dict:
    return {
        "type": "function",
        "function": {
            "name": feat.name,
            "description": feat.description or "",
            "parameters": feat.tool_schema or {"type": "object", "properties": {}},
        },
    }

# Extend in place — features replace any same-named static entry (registry wins).
_static_names = {t["name"] for t in TOOL_DEFINITIONS}
for name, feat in FEATURE_REGISTRY.items():
    if name in _static_names:
        TOOL_DEFINITIONS[:] = [t for t in TOOL_DEFINITIONS if t["name"] != name]
        OPENAI_TOOL_DEFINITIONS[:] = [t for t in OPENAI_TOOL_DEFINITIONS if t["function"]["name"] != name]
    TOOL_DEFINITIONS.append(_feature_to_anthropic_schema(feat))
    OPENAI_TOOL_DEFINITIONS.append(_feature_to_openai_schema(feat))
```

In `execute_tool`, add a registry-first dispatch at the top:

```python
def execute_tool(name: str, args: dict) -> dict:
    if name in FEATURE_REGISTRY:
        return FEATURE_REGISTRY[name].execute(**args)
    # ... existing if/elif chain stays as fallback for not-yet-migrated tools
```

- [ ] **Step 4: Run tests; expect green**

```
cd server; python -m pytest tests/test_tools_registry_integration.py tests/test_features_mini_sectors.py -v
cd server; python -m pytest tests/ -q 2>&1 | tail -3
```

Expected: 514 passing (511 + 3 new). If a pre-existing test asserts `"compare_mini_sectors" NOT in registered tools` or the like, fix it — that was old-world behavior.

- [ ] **Step 5: Commit**

```
fix(tools): auto-extend schemas from FEATURE_REGISTRY; execute_tool prefers registry

tools.TOOL_DEFINITIONS and tools.OPENAI_TOOL_DEFINITIONS now auto-extend
from FEATURE_REGISTRY at import time. execute_tool dispatches to
feature.execute() for any name in the registry; falls back to the legacy
if/elif chain for not-yet-migrated tools.

Lifted the autouse-fixture from test_features_mini_sectors.py into
conftest.py as a shared opt-in fixture (reset_feature_registry).
```

### Task B2: Build the `run_pipeline` helper

**Files:**
- Modify: `server/features/registry.py` (add `run_pipeline`)
- Test: extend `server/tests/test_feature_registry.py`

The pipeline collapses the candidates → rank → execute → widget gate sequence into one entry point. Other code calls one function.

- [ ] **Step 1: Write failing tests**

```python
def test_run_pipeline_executes_relevant_features_and_emits_widgets():
    """run_pipeline returns list of (feature, result, widget|None) tuples,
    where widget is None if should_show_widget returned False."""
    from features.base import FEATURE_REGISTRY, Feature, register_feature

    @register_feature
    class _Fires(Feature):
        name = "_fires"
        applies_to = ("pair_of_drivers",)
        def is_relevant_for(self, q, r): return 0.9
        def execute(self, **a): return {"ok": True}
        def make_widget(self, r): return {"type": "fires_widget"}
        def should_show_widget(self, r): return True

    @register_feature
    class _NotRelevant(Feature):
        name = "_not_relevant"
        applies_to = ("pair_of_drivers",)
        def is_relevant_for(self, q, r): return 0.1
        def execute(self, **a): raise AssertionError("must not execute")
        def make_widget(self, r): return {}
        def should_show_widget(self, r): return False

    resolved = {"drivers": [{"code": "A"}, {"code": "B"}]}
    from features.registry import run_pipeline
    results = run_pipeline("any q", resolved, args_by_feature={"_fires": {}})

    names = [f.name for f, _, _ in results]
    assert "_fires" in names
    assert "_not_relevant" not in names  # below threshold
    fires_entry = next(r for r in results if r[0].name == "_fires")
    assert fires_entry[2] == {"type": "fires_widget"}
```

- [ ] **Step 2: Implement `run_pipeline`**

```python
def run_pipeline(
    question: str,
    resolved: dict | None,
    args_by_feature: dict[str, dict] | None = None,
    threshold: float = 0.5,
) -> list[tuple[Feature, dict, dict | None]]:
    """End-to-end: candidates → rank → execute → widget gate → audit.

    Returns one (feature, execute_result, widget_or_none) per feature that
    cleared all gates. Audit log is populated as a side effect.
    """
    import time
    from features.base import audit_log
    args_by_feature = args_by_feature or {}
    out: list[tuple[Feature, dict, dict | None]] = []
    cands = candidates_for(resolved)
    for feat, score in rank_by_relevance(question, resolved, cands):
        executed = score >= threshold
        widget = None
        result: dict = {}
        if executed:
            args = args_by_feature.get(feat.name, {})
            t0 = time.time()
            try:
                result = feat.execute(**args)
            except Exception as e:
                logger.warning("feature %s execute() raised: %s", feat.name, type(e).__name__)
                result = {"available": False, "error": type(e).__name__}
            duration_ms = int((time.time() - t0) * 1000)
            if feat.should_show_widget(result):
                widget = feat.make_widget(result)
            audit_log(
                feature_name=feat.name, question=question,
                applies_to_passed=True, relevance_score=score,
                executed=True, widget_emitted=widget is not None,
                duration_ms=duration_ms,
            )
            out.append((feat, result, widget))
        else:
            audit_log(
                feature_name=feat.name, question=question,
                applies_to_passed=True, relevance_score=score,
                executed=False, widget_emitted=False, duration_ms=0,
            )
    return out
```

- [ ] **Step 3: Run tests; expect green. Commit.**

### Task B3: Smoke-test the pilot end-to-end

**Files:** None (validation only)

- [ ] **Step 1:** Start `uvicorn main:app --reload --port 8000` from `server/`. In the chat at `client/` (`npm run dev`), ask: "Compare Norris vs Piastri's fastest Q3 lap at Imola 2024 — where did Piastri lose time?"

- [ ] **Step 2:** Confirm the mini_sectors widget renders. (It was already rendering through the old path; now it's running through `FEATURE_REGISTRY['compare_mini_sectors'].execute()`.)

- [ ] **Step 3:** Inspect the audit log via a debug print or REPL: `python -c "import sys; sys.path.insert(0,'server'); from features.base import get_audit_log; print(get_audit_log())"`. Expect a record per registered feature, with `executed=True` for `compare_mini_sectors` and the duration captured.

- [ ] **Step 4:** Empty commit recording the milestone.

---

## Phase C — Unify Orchestration (One Pipeline, Not Two)

**Goal:** Replace `_widgets_from_preloaded` (deterministic path) and `_widgets_from_analysis_evidence` (agentic path) with a single registry-driven pipeline. Both paths converge on `run_pipeline`.

This is the highest-leverage change in the whole plan — it's the moment "every feature" stops being two parallel implementations.

### Task C1: Replace `_widgets_from_preloaded`

**Files:**
- Modify: `server/chat.py` (delete `_widgets_from_preloaded`, replace call site with `run_pipeline`)
- Test: `server/tests/test_chat_pipeline.py` (new)

- [ ] **Step 1: Find the call site**

Grep `chat.py` for `_widgets_from_preloaded`. Identify what `preloaded_results` dict is keyed by (tool name) and how it composes widgets.

- [ ] **Step 2: Write a regression test pinning the OLD widget output**

For one known scenario (e.g. driver_comparison mode at a specific round), capture the current widget list produced by `_widgets_from_preloaded` against a fixed stubbed tool-result set. The new pipeline must produce the same list (or a known intentional difference).

- [ ] **Step 3: Replace the call site with `run_pipeline`**

The new flow:
1. Build `args_by_feature` dict mapping feature name → args (currently computed inline per-tool in `_widgets_from_preloaded`)
2. Call `run_pipeline(question, resolved, args_by_feature)`
3. Collect widgets: `widgets = [w for _, _, w in pipeline_results if w is not None]`

- [ ] **Step 4: Run regression test; expect green or one intentional diff**

If the diff is intentional (e.g. a widget that should never have rendered now correctly suppressed via `should_show_widget`), update the regression assertion to match the new behavior and document why.

- [ ] **Step 5: Commit**

### Task C2: Replace `_widgets_from_analysis_evidence`

Same pattern as C1, applied to the agentic-loop path.

- [ ] **Step 1:** Locate `_widgets_from_analysis_evidence` in `chat.py`. Capture its inputs (the LLM's analysis-mode plan JSON + the agentic tool-call results).

- [ ] **Step 2:** Write a regression test for the agentic path.

- [ ] **Step 3:** Replace with `run_pipeline`. The agentic loop's tool-call results become `args_by_feature` keyed by tool name; `question` and `resolved` flow through unchanged.

- [ ] **Step 4:** Update `ANALYSIS_SYSTEM_PROMPT` to remove per-feature instructions that the registry now owns (predicates, widget gates). Keep the prompt focused on output structure (free text + which tool calls to make).

- [ ] **Step 5:** Run regression; commit.

### Task C3: Delete `_build_analysis_plan` if redundant

**Files:**
- Modify: `server/chat.py`

After C1 and C2 land, `_build_analysis_plan` (the deterministic plan builder that picked which tools to call based on mode) is replaced by `candidates_for` + `rank_by_relevance` inside `run_pipeline`.

- [ ] **Step 1:** Check whether `_build_analysis_plan` has any callers outside the now-replaced widget composers. Grep for it.

- [ ] **Step 2:** If unused, delete it and its helpers. If still used (e.g. it shapes the tool-list shown to the LLM in non-analysis-mode flow), leave a comment marking it for deletion in Phase E.

- [ ] **Step 3:** Run full suite. Expect no regression. Commit.

---

## Phase D — Migrate the 25 Features in 6 Batches

**Goal:** Move each remaining feature into its own module under `server/features/` following the template below. After Phase D, `tools.py`'s if/elif executor chain is dead code (still present, but unreachable for registered features) and `chat.py`'s `_make_*_widget` functions are gone for migrated features.

### Migration Template — Per Feature

For each feature being migrated:

```
- [ ] Step 1: Identify the source code
       - Tool schema in tools.py (line range)
       - Executor branch in tools.py (line range)
       - Widget builder in chat.py (function name, line range, if applicable)
       - Any ANALYSIS_SYSTEM_PROMPT mentions (string literals)
       - F1 data function being called (file:function)

- [ ] Step 2: Write a test file `server/tests/test_features_<name>.py`
       Following the pattern of test_features_mini_sectors.py:
       - test_<name>_feature_registered_after_discover
       - test_<name>_applies_to_<entity_types>
       - test_<name>_relevance_high_for_<positive_case_question>
       - test_<name>_mode_only_does_not_fire (if mode applies)
       - test_<name>_keyword_alone_fires_without_mode
       - test_<name>_should_show_widget_<gate_condition>
       - test_<name>_make_widget_matches_existing_builder (if existing widget)

- [ ] Step 3: Run tests; expect red (module doesn't exist yet)

- [ ] Step 4: Create `server/features/<name>.py`
       Follow this template (DO NOT deviate without reason):

       """<one-line description>"""
       from __future__ import annotations

       import f1_data  # or whatever the analysis layer is
       from features.base import Feature, register_feature

       _RELEVANT_KEYWORDS = (...)
       _RELEVANT_MODES = frozenset({...})  # may be empty
       _REQUIRED_ARGS = (...)

       @register_feature
       class <Name>Feature(Feature):
           name = "<tool_name>"
           applies_to = (...)
           description = "<from tools.py>"
           required_args = _REQUIRED_ARGS
           tool_schema = {"type": "object", "properties": {...}, "required": list(_REQUIRED_ARGS)}

           def is_relevant_for(self, question, resolved):
               # Codex Option 4 scoring:
               # keyword+mode -> 0.85, keyword -> 0.65, mode -> 0.45, neither -> 0.0
               q = (question or "").lower()
               mode = (resolved or {}).get("analysis_mode")
               has_kw = any(kw in q for kw in _RELEVANT_KEYWORDS)
               has_mode = mode in _RELEVANT_MODES
               if has_kw and has_mode: return 0.85
               if has_kw: return 0.65
               if has_mode: return 0.45
               return 0.0

           def execute(self, **args):
               return f1_data.<func>(**{k: args.get(k, default) for k, default in [...]})

           def make_widget(self, result):
               # Initially: delegate to chat._make_X_widget. After all features migrate,
               # inline the builder here.
               import chat
               return chat._make_<name>_widget(result)

           def should_show_widget(self, result):
               # Feature-specific gate. Common patterns:
               # - return result.get("available", True) and <quality_threshold>
               return ...

- [ ] Step 5: Run tests; expect green

- [ ] Step 6: Full suite; expect prior count + N new tests

- [ ] Step 7: Commit

       feat(features): migrate <tool_name> to feature registry

       Wraps f1_data.<func> as a Feature. applies_to=<...>. Predicate
       follows Codex Option 4 scoring (keyword+mode=0.85, keyword=0.65,
       mode=0.45, neither=0). Widget builder still delegates to chat.py;
       will inline in Phase E cutover.

       Plan: docs/superpowers/plans/2026-05-21-feature-registry-full-migration.md Phase D <batch>
```

### Batch D1: Pure Lookups (Tier 1, ~20 features, low complexity)

These have no widget, no mode-specific relevance, no keyword scoring. They're just function dispatch. Group by domain into sub-modules under `server/features/lookups/`.

- [ ] Migrate `standings.py` — wraps: `get_driver_standings`, `get_constructor_standings`, `get_driver_season_stats`
- [ ] Migrate `results.py` — wraps: `get_race_results`, `get_qualifying_results`, `get_sprint_results`, `get_sprint_qualifying_results`, `get_session_results`
- [ ] Migrate `schedule.py` — wraps: `get_season_schedule`
- [ ] Migrate `lap_data.py` — wraps: `get_driver_lap_times`, `get_lap_telemetry`, `get_sector_comparison`, `get_telemetry_comparison`
- [ ] Migrate `strategy.py` — wraps: `get_driver_strategy`
- [ ] Migrate `timing.py` — wraps: `get_clean_pace_summary`, `get_track_position_comparison`, `get_qualifying_progression`, `get_session_fastest_laps`, `get_speed_trap_leaderboard`
- [ ] Migrate `circuit_lookups.py` — wraps: `get_circuit_details`, `get_circuit_track_map`, `get_circuit_corners`, `get_historical_circuit_performance`

Each sub-module file may define multiple Feature classes (one per tool). The `name`, `description`, `tool_schema`, and `execute` come from the corresponding `tools.py` entry. `is_relevant_for` is keyword-only: a small keyword list specific to that lookup. No widget, so `make_widget` returns `{}` and `should_show_widget` returns `False`.

Commit one sub-module at a time. Expected: ~20 commits, full suite +60 to +80 tests.

### Batch D2: Widget-Bearing Analyses (Tier 2-3, ~8 features)

- [ ] Migrate `qualifying_battle.py` — tool: `analyze_qualifying_battle`, widget: `qualifying_battle`
- [ ] Migrate `race_pace_battle.py` — tool: `analyze_race_pace_battle`, widget: `race_pace_battle`
- [ ] Migrate `corner_profiles.py` — tool: `compare_corner_profiles`, widget: `corner_comparison`
- [ ] Migrate `stint_degradation.py` — tool: `analyze_stint_degradation`, widget: `deg_trend_chart`
- [ ] Migrate `energy_management.py` — tool: `analyze_energy_management`, widget: `energy_management`
- [ ] Migrate `active_aero.py` — tool: `analyze_active_aero_usage`, widget: `active_aero`
- [ ] Migrate `undercut_overcut.py` — tool: `analyze_undercut_overcut`, widget: `undercut_overcut`
- [ ] Migrate `pit_stop_analysis.py` — tool: `get_pit_stop_analysis`, widget: `pit_stop_strategy`

Each follows the migration template. Each commit independently.

### Batch D3: Context & Style (Tier 2, ~6 features)

- [ ] Migrate `circuit_profile.py` — tool: `get_circuit_profile`, widget: `circuit_profile`
- [ ] Migrate `driver_style_profile.py` — tool: `get_driver_style_profile`, no widget
- [ ] Migrate `team_car_profile.py` — tool: `get_team_car_profile`, no widget
- [ ] Migrate `head_to_head.py` — tool: `get_head_to_head`, no widget
- [ ] Migrate `team_telemetry_traits.py` — tool: `analyze_team_telemetry_traits`, no widget
- [ ] Migrate `team_circuit_fit.py` — tool: `analyze_team_circuit_fit`, no widget

### Batch D4: Cornering Variants (Tier 2, 2 features)

- [ ] Migrate `cornering_loads.py` — tool: `analyze_cornering_loads`
- [ ] Migrate `race_cornering_profile.py` — tool: `analyze_race_cornering_profile`

### Batch D5: Composites (Tier 3, 4 features — highest complexity)

Composites internally orchestrate multiple primitive tools. The Feature's `execute` must call the composed primitives and assemble the narrative dict. Two approaches:

1. **Internal orchestration** — `execute` calls multiple `f1_data.*` functions and assembles the result.
2. **Pipeline orchestration** — `execute` calls `run_pipeline` recursively with a curated args dict, then composes.

Default: **approach 1** (matches current behavior; simpler). Approach 2 is for future refactoring.

- [ ] Migrate `driver_race_story.py` — tool: `get_driver_race_story`, widget: `race_story`. Composes: sector_comparison, lap_times, pit_stops, intervals.
- [ ] Migrate `driver_weekend_overview.py` — tool: `get_driver_weekend_overview`, no widget. Composes: race_results, qualifying_results, fp_summary, etc.
- [ ] Migrate `team_weekend_overview.py` — tool: `get_team_weekend_overview`, no widget. Per-driver composes.
- [ ] Migrate `race_report.py` — tool: `get_race_report`, no widget. Whole-race summary.
- [ ] Migrate `team_performance.py` — tool: `analyze_team_performance`, widget: `corner_comparison` (subkey extraction). NOTE: this returns a nested widget — `make_widget` extracts `result["corner_comparison"]` if present.

### Batch D6: Remaining (Tier 2, ~5 features)

- [ ] Migrate `safety_car_periods.py` — tool: `get_safety_car_periods`
- [ ] Migrate `session_weather.py` — tool: `get_session_weather`
- [ ] Migrate `fp_summary.py` — tool: `get_fp_summary`
- [ ] Migrate `search_editorial.py` — tool: `search_editorial_content`. Special case — editorial RAG already lives in `server/editorial/`. Feature wraps the existing search function.
- [ ] Migrate `historical_circuit_performance.py` — already covered in Batch D1 lookups.

---

## Phase E — Cutover & Cleanup

**Goal:** Delete the dead executor branches, inline the delegated widget builders, prune `tools.py` to a thin shell.

### Task E1: Inline widget builders

**Files:**
- Modify: `server/features/*.py` (each feature that delegates `make_widget` to `chat._make_*_widget`)
- Modify: `server/chat.py` (delete the now-unused builder functions)

- [ ] **Step 1:** For each feature module that still has `import chat; return chat._make_X_widget(result)` in its `make_widget`, copy the builder function body inline.

- [ ] **Step 2:** Delete the `_make_X_widget` function from `chat.py`.

- [ ] **Step 3:** Re-run full suite. Widget shape regression tests (added during Phase D) will catch any inlining bugs.

- [ ] **Step 4:** Commit per feature or in batches of 3-5.

### Task E2: Delete the executor if/elif chain

**Files:**
- Modify: `server/tools.py`

- [ ] **Step 1:** Audit `execute_tool`'s if/elif chain. Every branch should now be unreachable (registry dispatch handles registered features; the 7 agentic-only helpers are still routed here).

- [ ] **Step 2:** Delete the unreachable branches. Keep the 7 agentic-only helpers (or move them to `server/agentic_helpers.py` if you want `tools.py` even thinner — optional).

- [ ] **Step 3:** Delete the static `TOOL_DEFINITIONS` / `OPENAI_TOOL_DEFINITIONS` entries that have a same-named feature in the registry. Auto-extension from Phase B handles them now.

- [ ] **Step 4:** Run full suite. Expect green. Commit.

### Task E3: Clean up `ANALYSIS_SYSTEM_PROMPT`

**Files:**
- Modify: `server/chat.py`

- [ ] **Step 1:** Audit the prompt. Anything that named specific features ("use mini_sectors when X", "always call qualifying_battle for Y") is now redundant — the registry's predicates own that.

- [ ] **Step 2:** Rewrite the prompt to focus on output structure (the JSON shape it returns) and behavioral guidelines (when to ask clarifying questions, etc.).

- [ ] **Step 3:** Run E2E smoke test in the live chat. Confirm the LLM still picks reasonable tool sequences.

- [ ] **Step 4:** Commit.

---

## Phase F — Frontend `widgetRegistry`

**Goal:** Replace `AnswerRenderer.jsx`'s if/else dispatch with a single map.

### Task F1: Create `widgetRegistry.js`

**Files:**
- Create: `client/src/components/chat-widgets/widgetRegistry.js`

```js
import QualifyingBattleWidget from "./QualifyingBattleWidget";
import RaceStoryWidget from "./RaceStoryWidget";
import RacePaceBattleWidget from "./RacePaceBattleWidget";
import CornerComparisonWidget from "./CornerComparisonWidget";
import MiniSectorHeatmapWidget from "./MiniSectorHeatmapWidget";
import CircuitProfileWidget from "./CircuitProfileWidget";
import PitStopStrategyWidget from "./PitStopStrategyWidget";
import DegTrendChart from "./DegTrendChart";
import EnergyManagementWidget from "./EnergyManagementWidget";
import ActiveAeroWidget from "./ActiveAeroWidget";
import UndercutOvercutWidget from "./UndercutOvercutWidget";
import CornerAnalysisWidget from "./CornerAnalysisWidget";
import DataTableWidget from "./DataTableWidget";

export const widgetRegistry = {
  qualifying_battle: QualifyingBattleWidget,
  race_story: RaceStoryWidget,
  race_pace_battle: RacePaceBattleWidget,
  corner_comparison: CornerComparisonWidget,
  mini_sector_heatmap: MiniSectorHeatmapWidget,
  circuit_profile: CircuitProfileWidget,
  pit_stop_strategy: PitStopStrategyWidget,
  deg_trend_chart: DegTrendChart,
  energy_management: EnergyManagementWidget,
  active_aero: ActiveAeroWidget,
  undercut_overcut: UndercutOvercutWidget,
  corner_analysis: CornerAnalysisWidget,
  data_table: DataTableWidget,
};
```

### Task F2: Replace `AnswerRenderer.jsx` dispatch

**Files:**
- Modify: `client/src/components/AnswerRenderer.jsx`

- [ ] **Step 1:** Find the if/else widget-type dispatch (likely a `switch` or chained ternaries).

- [ ] **Step 2:** Replace with:

```jsx
import { widgetRegistry } from "./chat-widgets/widgetRegistry";

function renderWidget(widget) {
  const Component = widgetRegistry[widget.type];
  if (!Component) {
    console.warn(`Unknown widget type: ${widget.type}`);
    return null;
  }
  return <Component {...widget} />;
}
```

- [ ] **Step 3:** Smoke-test in browser. Run through the major widget types one by one (qualifying_battle, race_story, mini_sector_heatmap, circuit_profile, undercut_overcut, etc.).

- [ ] **Step 4:** Commit.

---

## Validation Checklist (End-to-End)

After all phases complete, verify:

- [ ] `tools.py` is < 300 lines (was 2150). Just imports the registry + holds the 7 agentic helpers.
- [ ] `chat.py` is < 1500 lines (was 2100). No `_make_*_widget` functions remain.
- [ ] `AnswerRenderer.jsx` has no widget-type if/else; uses `widgetRegistry`.
- [ ] Every user-facing tool exposed to the LLM lives in exactly one file under `server/features/`.
- [ ] Full test suite: ≥ 580 passing (511 baseline + ~70 new feature tests + ~10 new pipeline tests).
- [ ] Live chat smoke test passes for: qualifying battle question, race-pace question, undercut/overcut question, circuit profile question, mini-sectors question, standings lookup, race results lookup, composite "tell me about Norris's weekend" question.
- [ ] Audit log shows reasonable decisions: each request fires 1-3 features, no false positives from mode-only matches.

---

## Risks & Open Questions

| Risk | Trigger | Proposed Resolution | Decide Before |
|---|---|---|---|
| **Predicate tuning drift** — each migrated feature picks its own keyword list. Without consistency rules, false positives multiply. | Phase D progresses with no shared keyword taxonomy | Document a "predicate guide" in `server/features/PREDICATES.md` (allowed; explicit instruction-doc): list of keyword categories per question intent, predicate-tuning playbook. Per-feature reviews check against the guide. | Phase D Batch 2 |
| **Composite features break** — composites currently shape multiple tool calls into a narrative dict. The Feature contract assumes one `execute` → one result → one widget. | Phase D Batch D5 | Approach 1 (internal orchestration inside `execute`). If composites multiply, add a `compose_with(other_results)` hook on Feature. Out of scope for V1. | Phase D Batch D5 |
| **Circuit-profile auto-injection** — `_retrieve_analysis_evidence` auto-attaches circuit context if a country is resolved. Migrated `circuit_profile` Feature may or may not preserve this. | Phase D Batch D3 | Add `country` to circuit_profile's `applies_to`. If a country is resolved AND circuit_profile is a candidate, it auto-fires (low mode-only bar). Document. | Phase D Batch D3 |
| **Agentic-only helpers unclear** — 7 helpers (`extract_corner_profiles` etc.) called from inside other tools. Are they Feature-eligible? | Phase D | Default: NO. Keep them as private functions. If a clear user-facing intent emerges later, migrate ad-hoc. | Start of Phase D |
| **Live-chat regression invisible** — unit tests cover widget shape but not LLM behavior. A predicate tuning miss might only show up in chat. | Phase D + Phase E | Build a 20-question E2E smoke-test script (one curl per question, asserting widget types in response). Run it after each Phase D batch. Cheap (it's a shell script) and catches regressions early. | Phase D Batch D1 |
| **Audit-log unbounded growth in long uvicorn processes** | After Phase E | Cap `_AUDIT_LOG` at last 1,000 entries (FIFO eviction). Optional: periodic JSONL flush every 100 entries. Add as last task in Phase E if production observation warrants. | After Phase E ships |

---

## Non-Goals (Explicit)

- LLM-based predicate scoring (a tool-routing model that picks features from descriptions). Worth considering only after Phase F if keyword predicates prove insufficient.
- Per-feature dependency DAG (feature X requires feature Y's result). Composites handle this internally; no general mechanism needed.
- Semantic search over features for tool selection. Same reasoning as LLM scoring.
- Hot-reload of features in dev (clear sys.modules → re-discover). Possible but unnecessary; restart uvicorn.
- Versioning of feature schemas (v1, v2 endpoints). YAGNI.

---

## References

- Pilot plan: `docs/superpowers/plans/2026-05-21-feature-registry-refactor.md`
- Pilot branch: `features/2026-05-21-feature-registry-refactor`
- Codex Option 4 (mode-as-eligibility-gate predicate scoring): conversation 2026-05-21, applied in `server/features/mini_sectors.py`.
- Inventory report: this plan's "Background" + the Phase D batches map directly to the 56-tool inventory taken from `tools.py`, `chat.py`, `AnswerRenderer.jsx`.
