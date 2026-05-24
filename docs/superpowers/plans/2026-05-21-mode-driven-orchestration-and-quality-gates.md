# Mode-Driven Orchestration + Quality Gates Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish the feature-registry unification by (1) replacing chat.py's hardcoded mode→tools dict with a registry-driven lookup using each Feature's `triggered_by_modes` declaration, and (2) upgrading every Feature's `should_show_widget` from a liveness check into a real data-quality gate per Codex's per-widget criteria.

**Architecture:** Mode classifier (Claude Haiku, already in resolver.py) stays as the brain — it picks one of the 12 analysis modes. The planner asks the registry "give me features whose `triggered_by_modes` set contains this mode AND whose `applies_to` matches the resolved entities." Each Feature owns its own mode list; `_build_analysis_plan`'s if/elif tree disappears. After tools execute, `should_show_widget` looks at actual numerical thresholds (segment counts, deltas, R² values) to decide what surfaces to the user.

**Tech Stack:** Pure Python. No new dependencies. Tests in `server/tests/` via `pytest`. Branch: `features/2026-05-21-feature-registry-refactor` (already 76 commits ahead of main).

---

## Background — What's Already Done

The registry pattern landed across Phases A–F. 47 features live in `server/features/`, the tool dispatcher routes through `FEATURE_REGISTRY`, widget composers consult `_registry_widget`, and the frontend uses `widgetRegistry.js`. The gap this plan closes:

1. **Tool selection in the deterministic path is still hardcoded** in `_build_analysis_plan` (chat.py:1165–1410ish) with 12 elif branches that hand-curate a tool list per mode. Adding a feature still requires editing this dict to wire it into deterministic mode firing.
2. **`is_relevant_for` predicates are keyword-only** and brittle. "Why did Norris beat Leclerc in quali" doesn't match `analyze_cornering_loads`'s keyword list, so a relevant feature silently scores 0. Codex's recommendation: retire the keyword predicates from orchestration entirely; let the mode classifier (which is already semantic) be the only intent-reading layer.
3. **`should_show_widget` checks are mostly liveness** ("did the tool succeed") not quality ("is the data interesting"). A two-driver mini-sectors comparison with 0.06s delta and random segment wins is technically "available" but is noise, not signal.

This plan delivers all three fixes together because they're entangled: removing `is_relevant_for` from orchestration means the broad-cast set will be larger, which makes a strong `should_show_widget` more important.

---

## Codex's Per-Widget Quality Gates (Authoritative Reference)

Each Feature's new `should_show_widget` must implement the corresponding gate. Listed here once; referenced from each task.

| Feature | Concrete gate |
|---|---|
| `compare_mini_sectors` | `len(segments) >= 10` AND `segments_won_a + segments_won_b >= 3` AND `abs(total_delta_s) >= 0.05` |
| `analyze_qualifying_battle` | `abs(overall_gap_s) >= 0.03` AND `decisive_sector_gap_s >= 0.02` (one sector ≥ half the gap) |
| `analyze_race_pace_battle` | `lap_overlap >= 3` AND (`abs(overall_pace_delta_s) >= 0.15` OR `abs(deg_rate_delta) >= 0.05`) |
| `compare_corner_profiles` | `len(gain_location_summary) >= 1` AND (`abs(avg_straight_speed_a - avg_straight_speed_b) >= 2` OR `abs(braking_point_delta_m) >= 5`) |
| `get_circuit_profile` | `circuit_name`, `downforce_level`, `character` present, plus ≥ 2 of {`sector_1`, `sector_2`, `sector_3`, `tyre_challenge`, `style_verdict`} |
| `get_pit_stop_analysis` | `total_laps >= 10` AND `len(drivers) >= 3` AND at least 2 drivers differ in `compound` OR `stop_count` |
| `analyze_stint_degradation` | ≥ 1 stint with `lap_count >= 5`, `r_squared >= 0.25`, `abs(deg_rate_s_per_lap) >= 0.05` |
| `analyze_energy_management` | `len(speed_trace_a) >= 20` AND (`total_clipping_seconds_a >= 0.2` OR `abs(clipping_delta_a_minus_b) >= 0.1`) |
| `analyze_active_aero_usage` | `circuit_in_coverage == True` AND `total_z_mode_seconds >= 0.3` AND `estimated_lap_time_delta_s >= 0.02` |
| `analyze_undercut_overcut` | `pit_loss_s > 0` AND `len(advantage_by_rejoin_lap) >= 2` AND `abs(advantage_s) >= 0.5` |
| `analyze_cornering_loads` (standalone corner_analysis) | `corners_detected >= 4` per driver AND one of: `avg_ggv_util_delta >= 2%`, `avg_load_variance_delta >= 0.005`, `avg_corrections_per_corner_delta >= 0.5` |
| `get_driver_race_story` | `finish_position` OR `status` present AND ≥ 2 of {`story_points`, `pit_stops`, `interval_summary`, `radio_highlights`, `position_timeline_summary`} non-empty |
| Generic `data_table` (where widgets emit it) | `len(rows) >= 3` AND `2 <= len(columns) <= 8` AND reject if all values in any key column are identical |
| `get_head_to_head` | `shared_races >= 3` AND non-trivial win/points split (not 100-0) |

The remaining features (lookups, composites without widgets, search_editorial, etc.) keep their current minimal `should_show_widget` since they have no widget OR they're degenerate cases (e.g. season schedule).

**If a result dict doesn't have the field a gate references** (e.g. `lap_overlap` for race_pace_battle), check `f1_data.py` to see whether the function returns it. If NOT returned today, the gate's contract requires we add it. That's noted per-task and may require small additions to f1_data return shapes.

---

## File Structure

| File | Status | Role |
|---|---|---|
| `server/features/base.py` | Modify | Add `triggered_by_modes: frozenset[str]` class attribute to the `Feature` ABC with default `frozenset()` |
| `server/features/*.py` (each of 47) | Modify | Add `triggered_by_modes` per feature; rewrite `should_show_widget` per Codex gate; stub `is_relevant_for` to return 0.0 |
| `server/features/registry.py` | Modify | Add `features_for_mode(mode, resolved) -> list[Feature]` helper |
| `server/chat.py:1165-1410ish` | Modify | Replace `_build_analysis_plan`'s if/elif with a `features_for_mode` call |
| `server/tests/test_feature_registry.py` | Modify | Add tests for `features_for_mode` |
| `server/tests/test_features_*.py` (each) | Modify | Add `triggered_by_modes` registration tests + tighter `should_show_widget` tests per Codex gate |
| `server/tests/test_chat_plan_builder.py` | Create | Regression tests pinning `_build_analysis_plan`'s output before and after refactor for each mode |
| `server/f1_data.py` | Modify (minimal) | Add missing result fields where gates require them (`decisive_sector_gap_s`, `lap_overlap`, `r_squared`, `corners_detected`, etc.) — only if not already present |

---

## Migration Order (3 Phases)

```
Phase 1   Add triggered_by_modes everywhere + features_for_mode helper          [4 tasks]
Phase 2   Replace _build_analysis_plan with registry lookup + regression pin    [3 tasks]
Phase 3   Upgrade should_show_widget per Codex gates                            [N tasks, one per gated feature]
```

Phase 1 and Phase 3 can run in parallel after Phase 1 lands. Phase 2 depends on Phase 1.

---

## Phase 1: Add `triggered_by_modes` + registry helper

### Task 1.1: Add `triggered_by_modes` to Feature ABC

**Files:**
- Modify: `server/features/base.py`
- Test: `server/tests/test_feature_registry.py`

- [ ] **Step 1: Write the failing test**

Append to `server/tests/test_feature_registry.py`:

```python
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
```

- [ ] **Step 2: Run to verify red**

```
cd server; python -m pytest tests/test_feature_registry.py::test_feature_subclass_inherits_triggered_by_modes_default tests/test_feature_registry.py::test_feature_subclass_can_declare_triggered_by_modes -v
```

Expected: 2 FAIL with `AttributeError: 'Feature' object has no attribute 'triggered_by_modes'`.

- [ ] **Step 3: Add the class attribute to Feature**

In `server/features/base.py`, find the `Feature` ABC class. In the class body, near the other class attributes (`applies_to`, `tool_schema`, etc.), add:

```python
triggered_by_modes: frozenset[str] = frozenset()
```

Place it next to `applies_to` since they're conceptually similar (both narrow the candidate set).

- [ ] **Step 4: Run to verify green**

```
cd server; python -m pytest tests/test_feature_registry.py -v 2>&1 | tail -5
```

Expected: All previously-passing tests pass + 2 new tests pass.

- [ ] **Step 5: Full suite stays green**

```
cd server; python -m pytest tests/ -q 2>&1 | tail -3
```

- [ ] **Step 6: Commit**

```bash
git add server/features/base.py server/tests/test_feature_registry.py
git commit -m "feat(features): add triggered_by_modes class attribute to Feature ABC

Each Feature can now declare which analysis_modes it serves. Defaults
to empty frozenset (means: never fires from mode-driven path; can still
be picked agentically). Phase 2 of this plan replaces _build_analysis_plan's
hardcoded mode->tool mapping with a registry lookup using this attribute.

Plan: docs/superpowers/plans/2026-05-21-mode-driven-orchestration-and-quality-gates.md Task 1.1"
```

---

### Task 1.2: Implement `features_for_mode` registry helper

**Files:**
- Modify: `server/features/registry.py`
- Test: `server/tests/test_feature_registry.py`

- [ ] **Step 1: Write failing tests**

Append to `server/tests/test_feature_registry.py`:

```python
from features.registry import features_for_mode


def test_features_for_mode_filters_by_triggered_by_modes():
    """Returns only features whose triggered_by_modes set contains mode."""

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
    """A feature whose mode matches but whose applies_to doesn't match is excluded."""

    @register_feature
    class _NeedsTeam(_DummyFeature):
        name = "_needs_team"
        applies_to = ("team",)
        triggered_by_modes = frozenset({"qualifying_battle"})

    resolved = {"drivers": [{"code": "A"}, {"code": "B"}]}  # no team
    feats = features_for_mode("qualifying_battle", resolved)
    assert all(f.name != "_needs_team" for f in feats)


def test_features_for_mode_returns_empty_when_no_mode_matches():
    """Unknown or unmatched mode returns empty list."""
    feats = features_for_mode("nonexistent_mode", {"drivers": []})
    assert feats == []


def test_features_for_mode_with_none_resolved_treats_empty_entities():
    """Passing None for resolved is equivalent to passing {}."""
    feats = features_for_mode("qualifying_battle", None)
    assert isinstance(feats, list)
```

- [ ] **Step 2: Verify red**

```
cd server; python -m pytest tests/test_feature_registry.py::test_features_for_mode_filters_by_triggered_by_modes -v
```

Expected: FAIL with `ImportError: cannot import name 'features_for_mode'`.

- [ ] **Step 3: Implement `features_for_mode` in `server/features/registry.py`**

Append after the existing `candidates_for` function:

```python
def features_for_mode(mode: str | None, resolved: dict | None) -> list[Feature]:
    """Registry-driven mode→features lookup.

    Returns features whose `triggered_by_modes` contains `mode` AND whose
    `applies_to` is satisfied by the resolved entity types. Replaces the
    hardcoded mode→tools dict in chat.py's _build_analysis_plan.

    Returns empty list if mode is None, unknown, or no features match.
    Order: stable iteration of FEATURE_REGISTRY (insertion order).
    """
    if not mode:
        return []
    types = _resolved_entity_types(resolved)
    out: list[Feature] = []
    for feat in FEATURE_REGISTRY.values():
        if mode not in feat.triggered_by_modes:
            continue
        if feat.applies_to and not all(req in types for req in feat.applies_to):
            continue
        out.append(feat)
    return out
```

- [ ] **Step 4: Verify green**

```
cd server; python -m pytest tests/test_feature_registry.py -v 2>&1 | tail -10
```

Expected: 4 new tests pass.

- [ ] **Step 5: Full suite stays green**

```
cd server; python -m pytest tests/ -q 2>&1 | tail -3
```

- [ ] **Step 6: Commit**

```bash
git add server/features/registry.py server/tests/test_feature_registry.py
git commit -m "feat(features): features_for_mode registry helper

Given a mode string + resolved entities, returns features whose
triggered_by_modes set contains the mode AND whose applies_to is
satisfied by the entities present. This is the registry-side
replacement for _build_analysis_plan's hardcoded mode->tools dict.

Plan: ... Task 1.2"
```

---

### Task 1.3: Pin existing `_build_analysis_plan` output with regression tests

Goal: capture the current mode→tools mapping in tests BEFORE we change it, so Phase 2's refactor can prove it doesn't regress.

**Files:**
- Create: `server/tests/test_chat_plan_builder.py`

- [ ] **Step 1: Read `_build_analysis_plan` and inventory each mode**

Open `server/chat.py` around line 1165. For each `if analysis_mode == "..."` branch, note:
- the mode string
- the tool names it adds to the plan
- any side effects (e.g. setting `focus`, `emit_context_widget`, etc.)

You don't write code in this step — you produce a written inventory you'll reference in Step 2. Save the inventory as a comment block at the top of the new test file.

- [ ] **Step 2: Write regression tests pinning each mode's output**

Create `server/tests/test_chat_plan_builder.py`. For each mode you inventoried, write a test like:

```python
"""Regression tests for _build_analysis_plan.

These tests pin the current output shape so Phase 2's refactor (replacing
the hardcoded if/elif with features_for_mode) doesn't silently change which
tools fire for which mode.

Inventory of current behavior (as of pre-refactor):
- circuit_profile: tools=[get_circuit_profile, get_circuit_track_map], emit_context_widget=True
- team_performance: tools=[analyze_team_performance, get_circuit_profile], focus="team"
- ... (fill in for all 12 modes by reading chat.py:_build_analysis_plan)
"""
import pytest


def test_build_analysis_plan_circuit_profile_mode():
    from chat import _build_analysis_plan
    plan = _build_analysis_plan(
        "What kind of track is Imola?",
        {"analysis_mode": "circuit_profile", "round_number": 7},
    )
    assert plan is not None
    assert plan["analysis_mode"] == "circuit_profile"
    tools = {t["name"] for t in plan.get("tools", [])}
    assert "get_circuit_profile" in tools
    # ... include every tool name the current branch adds ...


def test_build_analysis_plan_qualifying_battle_mode():
    from chat import _build_analysis_plan
    plan = _build_analysis_plan(
        "Why did Norris beat Leclerc in quali at Imola?",
        {
            "analysis_mode": "qualifying_battle",
            "round_number": 7,
            "session_type": "Q",
            "drivers": [{"code": "NOR"}, {"code": "LEC"}],
        },
    )
    assert plan is not None
    tools = {t["name"] for t in plan.get("tools", [])}
    # Pin every tool name the current branch adds. Read chat.py:_build_analysis_plan to populate.
    assert "analyze_qualifying_battle" in tools
    # ... etc


# Repeat for each of the 12 modes:
# circuit_profile, team_performance, team_circuit_fit, grip_comparison,
# race_pace_comparison, driver_comparison, qualifying_battle, (any others
# present in chat.py — read and enumerate)
```

**Reading the existing code is the work.** You can't write these tests without inventorying chat.py's plan-builder branches. If a branch's tool list depends on a sub-condition (e.g. "if both drivers present, also add corner_profiles"), write multiple tests covering each branch path.

- [ ] **Step 3: Run tests, ensure all pass against CURRENT chat.py**

```
cd server; python -m pytest tests/test_chat_plan_builder.py -v
```

Expected: ALL PASS (we're pinning current behavior; no changes yet).

If any test FAILS, your inventory is wrong — go re-read the matching branch in chat.py and correct the test.

- [ ] **Step 4: Commit**

```bash
git add server/tests/test_chat_plan_builder.py
git commit -m "test(chat): pin _build_analysis_plan output per mode (regression baseline)

Captures the current mode->tools mapping for all 12 analysis modes
before Phase 2 replaces the hardcoded if/elif with features_for_mode.
Each test runs the existing planner with a minimal resolved dict and
asserts the expected tool set + plan flags.

These tests must continue to pass after Phase 2's refactor, proving
the registry-based plan-builder produces identical output.

Plan: ... Task 1.3"
```

---

### Task 1.4: Add `triggered_by_modes` declarations to all 47 features

Now we populate the new attribute on every Feature. The values come from inventorying chat.py's `_build_analysis_plan` (Task 1.3's reading work) — wherever a feature appears in a mode's tool list, that mode goes into the feature's `triggered_by_modes`.

**Files:**
- Modify: 47 files under `server/features/*.py` and `server/features/lookups/*.py`
- Test: extend existing `server/tests/test_features_*.py` files OR add focused tests asserting each Feature's `triggered_by_modes` content

- [ ] **Step 1: Build the mapping**

For each feature module, determine its `triggered_by_modes` set by inverting Task 1.3's inventory. Save this as a working table — for example:

| Feature name | triggered_by_modes |
|---|---|
| `analyze_qualifying_battle` | `{"qualifying_battle"}` |
| `compare_mini_sectors` | `{"qualifying_battle", "driver_comparison"}` |
| `compare_corner_profiles` | `{"qualifying_battle", "grip_comparison", "driver_comparison"}` |
| `analyze_cornering_loads` | `{"qualifying_battle", "grip_comparison"}` |
| `get_circuit_profile` | `{"circuit_profile", "team_circuit_fit", "team_performance"}` (any mode whose branch in chat.py adds this tool) |
| `analyze_team_performance` | `{"team_performance"}` |
| `analyze_team_circuit_fit` | `{"team_circuit_fit"}` |
| `analyze_race_pace_battle` | `{"race_pace_comparison"}` |
| `analyze_stint_degradation` | `{"race_pace_comparison"}` |
| `get_driver_race_story` | `{"driver_comparison"}` if branched, else `frozenset()` |
| `analyze_undercut_overcut` | `frozenset()` if never in a deterministic mode list |
| `get_circuit_track_map` (lookup) | `{"circuit_profile", "team_circuit_fit"}` |
| ... (fill out for all 47) |

**A feature whose name never appears in any mode's tool list gets `triggered_by_modes = frozenset()`** — that's correct; those features are agentic-only.

- [ ] **Step 2: Add the attribute to each feature module**

For each Feature class, add `triggered_by_modes = frozenset({...})` next to `applies_to`. Example for `server/features/qualifying_battle.py`:

```python
@register_feature
class QualifyingBattleFeature(Feature):
    name = "analyze_qualifying_battle"
    applies_to = ("pair_of_drivers", "quali_session")
    triggered_by_modes = frozenset({"qualifying_battle"})  # NEW
    ...
```

Edit one feature at a time, run its test file to confirm no regression, then move on. Do NOT batch all 47 edits before testing — if you mistyped a mode name, you want to catch it per-file.

- [ ] **Step 3: Add a registration test per feature**

In each `server/tests/test_features_<name>.py`, add:

```python
def test_<name>_declares_expected_triggered_by_modes():
    from features.base import FEATURE_REGISTRY
    from features.registry import discover_features
    discover_features()
    feat = FEATURE_REGISTRY["<tool_name>"]
    assert feat.triggered_by_modes == frozenset({"<expected_mode_1>", "<expected_mode_2>"})
```

Use the exact mode set from Step 1's table.

- [ ] **Step 4: Run the per-feature test file**

```
cd server; python -m pytest tests/test_features_<name>.py -v
```

Expected: All pass.

- [ ] **Step 5: After all 47 features done, run full suite**

```
cd server; python -m pytest tests/ -q 2>&1 | tail -3
```

Expected: 47 new tests pass; existing suite still green.

- [ ] **Step 6: Commit per logical group (4-6 commits)**

Group the 47 edits into commits by feature batch:
- `feat(features): declare triggered_by_modes for qualifying_battle-mode features` (qualifying_battle, mini_sectors, corner_profiles, cornering_loads)
- `feat(features): declare triggered_by_modes for race-mode features` (race_pace_battle, stint_degradation, race_cornering_profile, ...)
- `feat(features): declare triggered_by_modes for context features` (circuit_profile, team_performance, team_circuit_fit, ...)
- `feat(features): declare triggered_by_modes for composites and lookups`

Each commit ends with `Plan: ... Task 1.4`.

---

## Phase 2: Replace `_build_analysis_plan` with registry lookup

### Task 2.1: Rewrite `_build_analysis_plan` to use `features_for_mode`

**Files:**
- Modify: `server/chat.py` (function `_build_analysis_plan`, lines ~1165–1410)

- [ ] **Step 1: Read the function thoroughly**

Read `server/chat.py:1165–1410`. Understand:
- The function signature and return shape (`dict` with keys like `analysis_mode`, `tools`, `focus`, `emit_context_widget`, etc.)
- Which keys vary per mode beyond just the tools list — these are "plan flags" (e.g. `focus`, `emit_context_widget`)
- How callers use the return value (grep for `plan.get(...)` in chat.py)

- [ ] **Step 2: Confirm regression tests still pass against the CURRENT implementation**

```
cd server; python -m pytest tests/test_chat_plan_builder.py -v
```

Expected: ALL PASS (we haven't changed anything yet). If any fail, fix the test first — they must accurately reflect current behavior before we refactor.

- [ ] **Step 3: Rewrite `_build_analysis_plan` to use `features_for_mode`**

The new implementation:

```python
def _build_analysis_plan(message: str, resolved: dict) -> dict | None:
    """Plan builder — registry-driven.

    Picks the features that fire for the resolver's analysis_mode by asking
    the registry. Plan flags (focus, emit_context_widget, etc.) come from
    a small mode-specific table here — these are orchestration concerns
    that don't belong on individual Features.
    """
    from features.registry import features_for_mode

    analysis_mode = resolved.get("analysis_mode")
    if not analysis_mode:
        return None

    feats = features_for_mode(analysis_mode, resolved)
    if not feats:
        return None

    tools = [_feature_to_plan_tool(feat, resolved) for feat in feats]

    plan: dict = {
        "analysis_mode": analysis_mode,
        "tools": tools,
    }

    # Mode-specific plan flags — small enough to keep here.
    # These are NOT tool-selection; they're orchestration knobs.
    if analysis_mode == "circuit_profile":
        plan["emit_context_widget"] = True
    if analysis_mode in ("qualifying_battle", "race_pace_comparison"):
        plan["focus"] = "qualifying" if analysis_mode == "qualifying_battle" else "race"
    if analysis_mode == "team_performance":
        plan["focus"] = "team"

    return plan


def _feature_to_plan_tool(feat, resolved: dict) -> dict:
    """Build the per-tool dict that _retrieve_analysis_evidence consumes.

    Resolves args from the entity resolver state, falling back to defaults
    declared on the Feature (required_args).
    """
    args = _tool_args_from_resolved(feat.name, resolved)
    return {"name": feat.name, "args": args}
```

Two implementation notes:
- `_tool_args_from_resolved(tool_name, resolved)` already exists in chat.py — use it.
- The mode-specific `plan["focus"]` / `plan["emit_context_widget"]` block stays inline; do NOT push these into Feature attributes (they're per-mode orchestration, not per-feature semantics).

- [ ] **Step 4: Run regression tests**

```
cd server; python -m pytest tests/test_chat_plan_builder.py -v
```

Expected: ALL 12 mode tests still pass. If any FAIL, the new implementation deviates from current behavior — either:
- `triggered_by_modes` is wrong on some feature (fix the feature module)
- A mode's plan flag isn't set in the new code (add it to the inline block)
- The current implementation has subtle logic the new one doesn't capture (capture it)

DO NOT loosen the regression test to make it pass. Fix the implementation.

- [ ] **Step 5: Full suite**

```
cd server; python -m pytest tests/ -q 2>&1 | tail -3
```

Expected: Still green.

- [ ] **Step 6: Commit**

```bash
git add server/chat.py
git commit -m "refactor(chat): _build_analysis_plan now uses features_for_mode

Replaces the 12-branch if/elif tree with a registry lookup. Each
Feature's triggered_by_modes attribute drives mode-to-tool selection.
Mode-specific plan flags (focus, emit_context_widget) stay inline as
they're orchestration concerns, not per-feature semantics.

Regression tests in test_chat_plan_builder.py confirm identical output
for all 12 modes pre- and post-refactor.

chat.py: ~245 lines deleted from _build_analysis_plan + replacement is ~35 lines.

Plan: ... Task 2.1"
```

---

### Task 2.2: Stub `is_relevant_for` to return 0.0

Per Codex's recommendation: keyword `is_relevant_for` is retired from the orchestration path. It's not called anywhere in production today (only by `run_pipeline` in tests), so stubbing it is safe.

**Files:**
- Modify: each `server/features/*.py` (47 files)
- Test: update test cases that assert specific `is_relevant_for` return values

- [ ] **Step 1: Find tests that assert specific `is_relevant_for` return values**

```
cd server; grep -rn "is_relevant_for" tests/
```

These are mostly in `test_features_*.py` files. Identify each test that asserts a NUMERIC score.

- [ ] **Step 2: Decide per-test: delete or update**

For each test like `test_<name>_relevance_high_for_<positive_case>`:
- If the test is named "relevance high for X" — the test will become a tautology after stubbing. DELETE it.
- If the test asserts mode-only-doesn't-fire / keyword-alone-fires — these tested a behavior we're removing. DELETE them.
- If a test asserts `is_relevant_for(...) == 0.0` for an unrelated question — that survives; keep it.

You should end up deleting ~40-50 tests across the suite. That's expected.

- [ ] **Step 3: Replace each Feature's `is_relevant_for` body with a stub**

For each `server/features/*.py`, replace the existing `is_relevant_for` body with:

```python
def is_relevant_for(self, question: str, resolved: dict | None) -> float:
    # Mode-driven orchestration replaced keyword predicates. The Feature
    # ABC still requires this method; agentic fallback paths can still
    # call it (returns 0 = "no opinion from keyword side").
    return 0.0
```

Also delete the module-level `_RELEVANT_KEYWORDS` and `_RELEVANT_MODES` constants — they're now unused.

- [ ] **Step 4: Run remaining tests**

```
cd server; python -m pytest tests/ -q 2>&1 | tail -3
```

Expected: still green (with the deleted-tests reduction in count).

- [ ] **Step 5: Commit**

```bash
git add server/features/ server/tests/
git commit -m "refactor(features): retire keyword is_relevant_for predicates

Per Codex's recommendation, keyword-based is_relevant_for is brittle
(false negatives on synonym-heavy phrasing). The mode classifier
(Haiku, in resolver.py) is now the only intent-reading layer; each
Feature declares triggered_by_modes instead.

is_relevant_for stubbed to return 0.0 to satisfy the Feature ABC.
Deleted ~45 tests that asserted keyword-scoring behavior we're no
longer relying on.

Plan: ... Task 2.2"
```

---

### Task 2.3: Wire `run_pipeline` for the agentic fallback (optional but recommended)

If the resolver doesn't classify into one of the 12 modes, the question still goes to the agentic loop. That loop doesn't currently consult the registry for tool RANKING — it just gives the LLM the full tool list. Wiring `run_pipeline` (which exists but is unused) gives the agentic path a cheap pre-narrowing step.

**Files:**
- Modify: `server/chat.py` (the `_answer_anthropic` and `_answer_openai` functions, where they construct the tool list for the LLM)

- [ ] **Step 1: Decide whether to narrow the agentic tool list**

Option A: Give the LLM the full TOOL_DEFINITIONS list (status quo). Pro: LLM has full optionality. Con: 47 tool schemas in every system prompt is a lot of tokens.

Option B: Use `candidates_for(resolved)` to narrow first, then pass only the candidates' schemas. Pro: less prompt overhead, agentic path benefits from the registry too. Con: if `applies_to` is too tight, LLM can't reach the right tool.

If you go with Option B:

```python
from features.registry import candidates_for
from features.base import FEATURE_REGISTRY

candidate_names = {f.name for f in candidates_for(resolved)}
# Include all agentic-only helpers (not in registry) too — they're not gated by entities
agentic_helpers = {"get_team_radio", "get_intervals", "get_live_position_timeline",
                   "analyze_weather_pace_correlation", "get_race_control_messages",
                   "extract_corner_profiles", "analyze_override_usage"}
allowed_names = candidate_names | agentic_helpers
narrowed_tool_definitions = [t for t in TOOL_DEFINITIONS if t["name"] in allowed_names]
```

If you go with Option A, this task is a no-op. Note your decision in the commit message either way.

- [ ] **Step 2: Test**

If Option B: write a test that asserts the narrowed tool list excludes features whose `applies_to` doesn't match the resolved entities.

If Option A: no test changes.

- [ ] **Step 3: Commit**

If a change was made:
```
refactor(chat): narrow agentic tool list via candidates_for

The LLM in the agentic loop now sees only features whose applies_to
matches the resolved entities (plus the 7 agentic-only helpers).
Saves ~N tokens per turn and reduces tool-selection ambiguity.

Plan: ... Task 2.3
```

If no change:
```
docs(chat): keep full TOOL_DEFINITIONS in agentic loop (decision recorded)

Considered narrowing the agentic LLM's tool list via candidates_for but
chose to keep the full list for now. <reason>.

Plan: ... Task 2.3 (no-op)
```

---

## Phase 3: Strengthen `should_show_widget` per Codex's gates

One task per gated feature. Each task is the same shape:

### Task 3.N: Strengthen `should_show_widget` for `<feature>`

For each row in the "Codex's Per-Widget Quality Gates" table at the top of this plan, follow this template. The variable parts are: the Feature module path, the gate fields/thresholds, and the test scenarios.

#### Template (apply per feature)

**Files:**
- Modify: `server/features/<name>.py`
- Test: `server/tests/test_features_<name>.py`
- Possibly modify: `server/f1_data.py` if a gate field isn't currently returned

- [ ] **Step 1: Audit the result dict shape**

Read the analysis function in `f1_data.py` (or wherever). What keys does the result dict contain? Compare against the gate's required fields.

- If all gate fields ARE returned → proceed.
- If a gate field is MISSING → add it to the function's return shape. Be conservative — only add the minimum needed.

Example: `analyze_race_pace_battle`'s gate needs `lap_overlap`. If the function doesn't return that today, add it (count the number of laps where both drivers had clean laps on comparable tyres).

- [ ] **Step 2: Write failing test for the new gate**

```python
def test_<name>_should_show_widget_meaningful_signal():
    from features.base import FEATURE_REGISTRY
    from features.registry import discover_features
    discover_features()
    feat = FEATURE_REGISTRY["<tool_name>"]

    # Result that SHOULD render (meets all gate criteria)
    meaningful = {
        # ... fields per the Codex gate ...
    }
    assert feat.should_show_widget(meaningful) is True


def test_<name>_should_show_widget_suppresses_negligible():
    from features.base import FEATURE_REGISTRY
    from features.registry import discover_features
    discover_features()
    feat = FEATURE_REGISTRY["<tool_name>"]

    # Result that should be SUPPRESSED for each gate field
    too_small_delta = {
        # ... copy meaningful but flip the threshold-determining field ...
    }
    assert feat.should_show_widget(too_small_delta) is False
```

Write one negative case per threshold the gate references. For mini_sectors that's three negative cases:
- `len(segments) < 10`
- `segments_won_a + segments_won_b < 3`
- `abs(total_delta_s) < 0.05`

- [ ] **Step 3: Verify red**

```
cd server; python -m pytest tests/test_features_<name>.py::test_<name>_should_show_widget_meaningful_signal tests/test_features_<name>.py::test_<name>_should_show_widget_suppresses_negligible -v
```

Some tests pass by accident (the current `should_show_widget` may already handle some cases) and some fail. Either way is informative.

- [ ] **Step 4: Implement the new gate**

In `server/features/<name>.py`:

```python
def should_show_widget(self, result: dict) -> bool:
    # Codex Phase-3 gate: <one-line description of signal>
    if not result.get("available", True):
        return False

    # <feature-specific gate, mirroring the Codex table>
    # Example for mini_sectors:
    segments = result.get("segments") or []
    if len(segments) < 10:
        return False
    won_a = result.get("segments_won_a") or 0
    won_b = result.get("segments_won_b") or 0
    if (won_a + won_b) < 3:
        return False
    total = result.get("total_delta_s")
    if total is None or abs(total) < 0.05:
        return False
    return True
```

Use the EXACT thresholds from the Codex table. Don't loosen or tighten.

- [ ] **Step 5: Verify green**

```
cd server; python -m pytest tests/test_features_<name>.py -v
```

Expected: All tests pass, including pre-existing ones.

If a pre-existing test breaks because the new gate is stricter (e.g. an old test used `{"total_delta_s": 0.4}` minimal sample and the new gate also requires `len(segments) >= 10`), update the test sample to satisfy the new gate.

- [ ] **Step 6: Commit**

```bash
git add server/features/<name>.py server/tests/test_features_<name>.py [server/f1_data.py if modified]
git commit -m "feat(features): strengthen should_show_widget for <tool_name>

Replaces the liveness check with a data-quality gate per Codex's
recommendation:
- <gate criterion 1>
- <gate criterion 2>
- <gate criterion 3>

<If f1_data was modified>: Adds <field_name> to <function_name>'s
return shape, needed for the new gate.

Plan: ... Task 3.N (<feature>)"
```

#### Feature-by-feature task list (one per row in Codex's table)

Apply the template above to each of these. They can be done in ANY order and in parallel.

- [ ] Task 3.1: `compare_mini_sectors`
- [ ] Task 3.2: `analyze_qualifying_battle` (gate may need `decisive_sector_gap_s` added to result)
- [ ] Task 3.3: `analyze_race_pace_battle` (gate needs `lap_overlap` and `deg_rate_delta` — verify)
- [ ] Task 3.4: `compare_corner_profiles` (gate needs `gain_location_summary`, straight-speed averages, braking_point_delta_m — verify)
- [ ] Task 3.5: `get_circuit_profile`
- [ ] Task 3.6: `get_pit_stop_analysis`
- [ ] Task 3.7: `analyze_stint_degradation` (gate needs per-stint `r_squared` — verify; add if missing)
- [ ] Task 3.8: `analyze_energy_management` (gate needs `total_clipping_seconds_a`, `clipping_delta_a_minus_b` — verify; add if missing)
- [ ] Task 3.9: `analyze_active_aero_usage` (gate needs `total_z_mode_seconds`, `estimated_lap_time_delta_s` — verify; add if missing)
- [ ] Task 3.10: `analyze_undercut_overcut`
- [ ] Task 3.11: `analyze_cornering_loads` standalone widget (gate needs `corners_detected`, `avg_ggv_util_delta`, etc. — verify)
- [ ] Task 3.12: `get_driver_race_story`
- [ ] Task 3.13: `get_head_to_head` (if widget activated)
- [ ] Task 3.14: Audit any other Feature that emits a `data_table` widget — apply the generic data_table gate

---

## Validation Checklist

- [ ] Phase 1 complete: every Feature has `triggered_by_modes` declared. `features_for_mode("qualifying_battle", resolved)` returns the right set.
- [ ] Phase 2 complete: `_build_analysis_plan` calls `features_for_mode` instead of if/elif. All 12 mode regression tests pass.
- [ ] Phase 2 complete: `is_relevant_for` returns 0.0 everywhere. No keyword constants left in feature modules.
- [ ] Phase 3 complete: each gated feature's `should_show_widget` matches the Codex table. Negative-case tests prove suppression works.
- [ ] Full suite passes — 653 baseline + ~50 new Phase 1 tests + ~20 new Phase 3 tests, minus ~45 deleted keyword-predicate tests = roughly 680.
- [ ] Live smoke test (manual): "Why did Norris beat Leclerc in quali at Imola?" produces a qualifying_battle widget AND a cornering_loads widget (the case Codex flagged as broken under keyword-only predicates).

---

## Risks & Open Questions

| Risk | Trigger | Resolution |
|---|---|---|
| **Gate fields not in result dict** — some Codex gates reference fields the f1_data function doesn't return today (e.g. `lap_overlap`, `r_squared`, `decisive_sector_gap_s`). | Task 3.X execution | Per-task Step 1 audits the shape. If missing, ADD the field. Don't loosen the gate to fit existing data. |
| **Mode mapping incomplete** — Task 1.4's table may miss edge cases where chat.py's plan-builder conditionally adds a tool. | Task 2.1 regression tests fail | The regression tests in `test_chat_plan_builder.py` will catch this. Update the Feature's `triggered_by_modes` until the test passes. |
| **Agentic path regression** — narrowing the tool list in Task 2.3 may exclude tools the LLM was relying on for unusual questions. | Live chat after merge | Default to Option A (no narrowing) unless prompt-token cost is a concern. If you do narrow, watch the audit log. |
| **Tighter `should_show_widget` suppresses widgets users expected** — a quality gate may be stricter than user intuition. | Live use | Audit log shows `widget_emitted=False` per feature. If users complain a meaningful widget didn't render, loosen that ONE gate, not all of them. |

---

## Non-Goals

- **Replacing the mode classifier** — Haiku stays.
- **LLM-based feature ranking** — Codex evaluated this and recommended against. Keyword predicates retired in favor of mode-classifier-as-brain.
- **Embedding-based feature retrieval** — same.
- **Changing the dual-LLM agentic loop** — analyzer + answer-writer LLMs are untouched.
- **Touching the frontend** — `widgetRegistry.js` and `AnswerRenderer.jsx` are stable.

---

## References

- Codex's per-widget gate criteria: captured in this plan's "Codex's Per-Widget Quality Gates" table.
- Codex's orchestration recommendation (Option 5 + decentralized `triggered_by_modes`): synthesized in conversation 2026-05-21, applied throughout Phase 1 + 2.
- Prior plan: `docs/superpowers/plans/2026-05-21-feature-registry-full-migration.md` (Phases A–F, completed).
- Current state of `_build_analysis_plan`: `server/chat.py:1165–1410ish` (the if/elif tree this plan replaces).
