# Quali Marker Time-Contribution Refactor

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** Make `analyze_qualifying_battle`'s telemetry markers and decisive-sector narrative agree by replacing km/h-magnitude marker ranking with time-contribution ranking, adding a 15% relevance threshold, and detecting split-sector laps where no single sector is decisive.

**Architecture:** Single source of truth — time. Sector gaps already measure time (kept as the prose label for decisive sector). Markers switch from `|speed_a - speed_b|` ranking to integrated `1/speed_a - 1/speed_b` ranking (the actual time loss per point). When no sector owns >55% of total gap, prose says "built across all three sectors" instead of fabricating a decisive one.

**Tech Stack:** Python, pandas/numpy already in use. No new dependencies. Tests in `server/tests/test_f1_data.py` + downstream `server/tests/test_features_qualifying_battle.py`.

---

## Background

The widget today picks markers by raw km/h delta magnitude. This routinely highlights flashy late-straight ERS events even when the lap was actually won at a quiet mid-corner apex — because km/h delta isn't the same as time loss. Per Codex (conversation 2026-05-22), the fix is to rank markers by integrated time contribution, with sector gaps staying as the prose label.

Concrete failure case: Leclerc beat Norris 0.040s. S1=+0.131s for LEC, S2/S3 net = -0.091s for NOR. The lap was won in S1 at a 1500m apex (13 km/h delta at ~110 km/h apex speed = ~0.2s gained). But the markers picked by km/h magnitude pointed at S3 events at 330 km/h — bigger km/h delta, but ~3x less time per meter. Prose said "decisive in S1" but listed S3 mechanisms.

---

## File Structure

| File | Status | Role |
|---|---|---|
| `server/f1_data.py` | Modify | Marker picker function inside `analyze_qualifying_battle`; sector-gap → decisive-sector logic; result dict shape additions |
| `server/tests/test_f1_data.py` | Modify | Unit tests for the new picker on synthetic speed-trace fixtures |
| `server/features/qualifying_battle.py` | Possibly modify | If the widget's `make_widget` reads marker fields that need new shape |
| `server/tests/test_features_qualifying_battle.py` | Possibly modify | Update sample dicts if widget shape changes |

---

## Inventory step (READ BEFORE TASKS)

The implementer's FIRST move is reading `server/f1_data.py`'s `analyze_qualifying_battle` end-to-end to find:
- Where speed-trace markers are computed (probably a `_pick_speed_trace_markers` or similar helper).
- The current marker output shape (likely `primary`, `secondary`, `tertiary` keys with distance/speed_a/speed_b/delta/category fields).
- Where `decisive_sector` is set in the result dict.
- Where the sector gaps are computed (`s1_gap_s`, `s2_gap_s`, `s3_gap_s` or similar).
- The downstream consumers of these fields in `server/features/qualifying_battle.py` (its `_build_qualifying_battle_widget` helper).

Without that inventory the implementer can't write accurate tests. The plan assumes these structures exist; the inventory confirms exact names.

---

## Task 1: Time-contribution metric for marker ranking

**Files:**
- Modify: `server/f1_data.py` — the speed-trace marker picker helper
- Test: `server/tests/test_f1_data.py`

- [ ] **Step 1: Inventory the current picker**

Grep `server/f1_data.py` for the helper that produces speed-trace markers. Likely names: `_pick_speed_trace_markers`, `_pick_quali_markers`, `_speed_trace_callouts`. Note its signature, what it returns, and where it's called from inside `analyze_qualifying_battle`.

Write the inventory at the top of the new test file as a comment block so you don't have to re-discover it.

- [ ] **Step 2: Write failing tests**

Append to `server/tests/test_f1_data.py`:

```python
def test_marker_picker_prefers_low_speed_time_loss_over_high_speed_kmh_delta():
    """A 13 km/h delta at 110 km/h apex must outrank a 16 km/h delta at
    330 km/h straight because the apex point costs more time per meter."""
    from f1_data import _pick_speed_trace_markers  # adjust to actual function name

    # Synthetic trace: 200 points, speed_a > speed_b at the apex and again at
    # the late straight. Apex window costs more time despite smaller km/h delta.
    import numpy as np
    distance = np.linspace(0, 5000, 200)

    # Driver A baseline: 200 km/h cruise, slows to 117 km/h mid-corner around
    # index 60, full speed 337 km/h late at index 180
    speed_a = np.full(200, 200.0)
    speed_a[55:65] = 117  # apex section
    speed_a[175:185] = 337  # top speed section

    # Driver B: same shape but slower at both — 13 km/h at apex, 16 km/h on straight
    speed_b = np.full(200, 200.0)
    speed_b[55:65] = 104  # 13 km/h slower at apex
    speed_b[175:185] = 321  # 16 km/h slower at top end

    markers = _pick_speed_trace_markers(distance, speed_a, speed_b, max_markers=2)
    # Primary marker should be the apex (around distance 1500m / index 60), not
    # the late straight (around 4500m / index 180).
    assert markers, "Expected at least one marker"
    primary = markers[0]
    assert primary["distance_m"] < 2000, (
        f"Expected primary marker in low-speed apex region; got distance "
        f"{primary['distance_m']}m"
    )


def test_marker_picker_drops_markers_below_15_percent_contribution():
    """A point with negligible time contribution (<15% of total lap delta)
    must NOT be returned even if up to 3 marker slots remain."""
    from f1_data import _pick_speed_trace_markers
    import numpy as np

    distance = np.linspace(0, 5000, 200)
    speed_a = np.full(200, 200.0)
    speed_b = np.full(200, 200.0)
    speed_a[55:65] = 117
    speed_b[55:65] = 104  # one strong event
    # Tiny event elsewhere: 1 km/h delta over 5 samples
    speed_a[150:155] = 250.0
    speed_b[150:155] = 249.0

    markers = _pick_speed_trace_markers(distance, speed_a, speed_b, max_markers=3)
    # Only one strong contribution — picker should return 1 marker, not 3.
    assert len(markers) == 1, (
        f"Expected picker to drop sub-threshold events; got {len(markers)} markers"
    )


def test_marker_picker_returns_empty_when_no_meaningful_delta():
    """If speeds are nearly identical everywhere, no markers should be returned."""
    from f1_data import _pick_speed_trace_markers
    import numpy as np

    distance = np.linspace(0, 5000, 200)
    speed_a = np.full(200, 200.0)
    speed_b = np.full(200, 200.0) + np.random.RandomState(42).normal(0, 0.5, 200)
    markers = _pick_speed_trace_markers(distance, speed_a, speed_b, max_markers=3)
    assert markers == []
```

If the actual function name differs from `_pick_speed_trace_markers`, update the imports. If the signature differs (e.g. takes a pandas DataFrame instead of arrays), adapt the test fixtures. The CORE assertions stay: apex must rank above late straight; sub-threshold markers must be dropped; flat traces give zero markers.

- [ ] **Step 3: Run to verify red**

```
cd server; python -m pytest tests/test_f1_data.py -k "marker_picker" -v
```

Expect FAILs (current picker uses km/h magnitude).

- [ ] **Step 4: Implement time-contribution ranking**

In the picker function:

```python
def _pick_speed_trace_markers(
    distance: np.ndarray,
    speed_a: np.ndarray,
    speed_b: np.ndarray,
    max_markers: int = 3,
    min_contribution_fraction: float = 0.15,
) -> list[dict]:
    """Pick up to max_markers points where driver A gained the most time over B.

    Ranks candidate points by integrated time contribution:
        contribution_i = (1/speed_a[i] - 1/speed_b[i]) * window_distance_m

    where window_distance_m is the local arc length around point i. Markers
    are returned in descending order of contribution. Drops any marker whose
    contribution is < min_contribution_fraction of the sum of all positive
    contributions. Returns [] if no points clear the threshold.
    """
    # Convert km/h to m/s for time math. Guard against zero/near-zero speeds.
    SAFE_MIN_SPEED_KPH = 30.0
    sa = np.clip(speed_a, SAFE_MIN_SPEED_KPH, None) / 3.6
    sb = np.clip(speed_b, SAFE_MIN_SPEED_KPH, None) / 3.6

    # Per-meter time delta. Positive = B is slower than A here = A gains time.
    per_meter_delta = (1.0 / sb) - (1.0 / sa)

    # Window length around each point — use the distance between adjacent samples.
    # First and last samples get the same step as their neighbour.
    if len(distance) < 2:
        return []
    steps = np.diff(distance, prepend=distance[0] - (distance[1] - distance[0]))

    contributions = per_meter_delta * np.abs(steps)
    total_positive = contributions[contributions > 0].sum()
    if total_positive <= 0:
        return []
    threshold = min_contribution_fraction * total_positive

    # Find local maxima of contribution (so we don't pick adjacent samples
    # describing the same event). Simple approach: take the top max_markers
    # candidates, but enforce a minimum spacing between picks.
    MIN_SPACING_M = 200.0
    order = np.argsort(-contributions)
    picked: list[int] = []
    for idx in order:
        if contributions[idx] < threshold:
            break
        if any(abs(distance[idx] - distance[p]) < MIN_SPACING_M for p in picked):
            continue
        picked.append(int(idx))
        if len(picked) >= max_markers:
            break

    out: list[dict] = []
    for idx in picked:
        out.append({
            "distance_m": float(distance[idx]),
            "speed_a": float(speed_a[idx]),
            "speed_b": float(speed_b[idx]),
            "delta_kph": float(speed_a[idx] - speed_b[idx]),
            "time_contribution_s": float(contributions[idx]),
            # Preserve any category-label logic the existing picker has (e.g.
            # "straight_line", "corner_exit", "min_speed"). Map from distance
            # to lap-position label via existing helper if present.
        })
    return out
```

The key change vs. before:
- OLD: candidates ranked by `abs(speed_a - speed_b)`
- NEW: candidates ranked by `contributions[i]`, which is time per meter × window length

The 15% threshold ensures sub-significant points don't fill the marker slots. The 200m minimum spacing prevents adjacent samples from describing the same event.

If the existing picker has category-label logic (e.g. "min_speed", "straight_line", "corner_exit"), preserve it — adapt to the new ranking but keep the labels.

- [ ] **Step 5: Run to verify green**

```
cd server; python -m pytest tests/test_f1_data.py -k "marker_picker" -v
```

Expect 3 PASS.

- [ ] **Step 6: Full suite**

```
cd server; python -m pytest tests/ -q 2>&1 | tail -3
```

Some pre-existing tests may break because they asserted specific marker output for fixtures where the OLD ranking picked different points. UPDATE those fixtures (or expected markers) to reflect the new time-contribution truth. Do NOT loosen the new gate. If a test fixture is too thin to support time-contribution math, expand it.

- [ ] **Step 7: Commit**

```bash
git add server/f1_data.py server/tests/test_f1_data.py
git commit -m "feat(f1_data): rank quali markers by time contribution, not km/h delta

A 13 km/h delta at 110 km/h apex builds 2-3x more time per meter than
a 16 km/h delta at 330 km/h straight. The old picker ranked by km/h
magnitude, so flashy high-speed events outranked the actual time-loss
events at slower corners.

New picker:
- Computes per-point time contribution as (1/v_b - 1/v_a) * step_distance
- Ranks candidates by integrated contribution
- Drops candidates below 15% of total positive contribution
- Enforces 200m minimum spacing between picks
- Returns up to max_markers (default 3); may return fewer if signal is thin

This is the Codex Option 2 recommendation: one source of truth (time)
across both subsystems. Decisive-sector prose label stays unchanged
(Task 2 of plan).

Plan: docs/superpowers/plans/2026-05-22-quali-marker-time-contribution.md Task 1"
```

---

## Task 2: Split-sector detection (no fabricated decisive sector)

**Files:**
- Modify: `server/f1_data.py` — wherever `decisive_sector` is set in `analyze_qualifying_battle`'s return dict
- Test: `server/tests/test_f1_data.py`

- [ ] **Step 1: Locate the decisive-sector logic**

Grep `server/f1_data.py` for `decisive_sector`. It's most likely set inside `analyze_qualifying_battle` near where sector gaps are computed. Note the exact field name and the algorithm — probably "max by absolute sector gap."

- [ ] **Step 2: Write failing tests**

```python
def test_decisive_sector_set_when_one_sector_dominates():
    """If one sector contains >=55% of the total absolute gap, decisive_sector
    is set to that sector and split_sector_lap is False."""
    from f1_data import _classify_decisive_sector

    # Total absolute gap = 0.131 + 0.081 + 0.010 = 0.222
    # S1 dominates: 0.131 / 0.222 = 59% — above 55% threshold
    result = _classify_decisive_sector(
        s1_gap_s=0.131,
        s2_gap_s=-0.081,
        s3_gap_s=-0.010,
    )
    assert result["decisive_sector"] == "S1"
    assert result["split_sector_lap"] is False


def test_split_sector_lap_when_gap_distributed():
    """If no sector contains >=55% of the total absolute gap, decisive_sector
    is None and split_sector_lap is True."""
    from f1_data import _classify_decisive_sector

    # Total absolute gap = 0.05 + 0.05 + 0.04 = 0.14; max share = 0.05/0.14 = 36%
    result = _classify_decisive_sector(
        s1_gap_s=0.05,
        s2_gap_s=0.05,
        s3_gap_s=0.04,
    )
    assert result["decisive_sector"] is None
    assert result["split_sector_lap"] is True


def test_classify_decisive_sector_handles_zero_gap():
    """If total gap is ~0, both fields are None/False — no claim about decisive."""
    from f1_data import _classify_decisive_sector

    result = _classify_decisive_sector(s1_gap_s=0.0, s2_gap_s=0.0, s3_gap_s=0.0)
    assert result["decisive_sector"] is None
    assert result["split_sector_lap"] is False
```

- [ ] **Step 3: Run red**

```
cd server; python -m pytest tests/test_f1_data.py -k "decisive_sector or split_sector" -v
```

Expect 3 FAIL with ImportError.

- [ ] **Step 4: Implement `_classify_decisive_sector` and rewire `analyze_qualifying_battle`**

Add to `server/f1_data.py`:

```python
def _classify_decisive_sector(
    s1_gap_s: float,
    s2_gap_s: float,
    s3_gap_s: float,
    dominance_threshold: float = 0.55,
) -> dict:
    """Classify a lap's decisive sector by share of total absolute gap.

    Returns:
        {"decisive_sector": "S1" | "S2" | "S3" | None,
         "split_sector_lap": bool}

    decisive_sector is None when no sector owns >= dominance_threshold of the
    total absolute gap (split_sector_lap=True) OR when the lap was effectively
    identical (split_sector_lap=False because there's nothing to split).
    """
    abs_gaps = {"S1": abs(s1_gap_s), "S2": abs(s2_gap_s), "S3": abs(s3_gap_s)}
    total = sum(abs_gaps.values())
    if total < 1e-6:
        return {"decisive_sector": None, "split_sector_lap": False}
    dominant_sector, dominant_gap = max(abs_gaps.items(), key=lambda kv: kv[1])
    if dominant_gap / total >= dominance_threshold:
        return {"decisive_sector": dominant_sector, "split_sector_lap": False}
    return {"decisive_sector": None, "split_sector_lap": True}
```

Then update `analyze_qualifying_battle` to call this and put BOTH fields into the result dict (preserving any existing `decisive_sector_gap_s` field for downstream consumers — that's the absolute gap in the decisive sector, set to None when there is no decisive sector).

- [ ] **Step 5: Run green**

```
cd server; python -m pytest tests/test_f1_data.py -k "decisive_sector or split_sector" -v
```

3 PASS.

- [ ] **Step 6: Full suite**

```
cd server; python -m pytest tests/ -q 2>&1 | tail -3
```

If a downstream test asserts `decisive_sector == "S1"` for a fixture where the gap is now classified as split, update the fixture OR the assertion. The new behavior is the correct truth.

- [ ] **Step 7: Commit**

```bash
git add server/f1_data.py server/tests/test_f1_data.py
git commit -m "feat(f1_data): detect split-sector laps; don't fabricate decisive sector

A lap where no single sector owns >=55% of the total absolute gap is
classified as split_sector_lap=True with decisive_sector=None. Prevents
the prose from claiming 'decisive in S2' when the gap was actually
0.05/0.05/0.04 — that's a whole-lap-execution lap, not a sector lap.

Plan: docs/superpowers/plans/2026-05-22-quali-marker-time-contribution.md Task 2"
```

---

## Task 3: Update the qualifying_battle prose / widget consumer

**Files:**
- Modify: `server/features/qualifying_battle.py` — `_build_qualifying_battle_widget` helper
- Test: `server/tests/test_features_qualifying_battle.py`

- [ ] **Step 1: Read the widget builder**

Open `server/features/qualifying_battle.py` and find `_build_qualifying_battle_widget`. Note:
- Which result fields it reads (likely `decisive_sector`, `decisive_sector_gap_s`, and the speed-trace markers).
- Whether it formats prose itself or passes raw fields through to the React component.

- [ ] **Step 2: Write failing test**

```python
def test_qualifying_battle_widget_handles_split_sector_lap():
    """When decisive_sector is None and split_sector_lap is True, the widget
    must NOT claim a decisive sector. Either omits the field, or sets a
    'split-sector' indicator the React component can render appropriately."""
    from features.base import FEATURE_REGISTRY
    from features.registry import discover_features
    discover_features()
    feat = FEATURE_REGISTRY["analyze_qualifying_battle"]

    result = {
        "available": True,
        "driver_a": "LEC", "driver_b": "NOR",
        "lap_time_a": "1:28.143", "lap_time_b": "1:28.183",
        "overall_gap_s": 0.040,
        "s1_gap_s": 0.05, "s2_gap_s": 0.05, "s3_gap_s": 0.04,
        "decisive_sector": None,
        "decisive_sector_gap_s": None,
        "split_sector_lap": True,
        "markers": [],  # picker may return empty for this fixture
    }
    widget = feat.make_widget(result)
    assert widget["type"] == "qualifying_battle"
    assert widget.get("decisive_sector") is None
    assert widget.get("split_sector_lap") is True


def test_qualifying_battle_widget_passes_through_decisive_sector_when_set():
    from features.base import FEATURE_REGISTRY
    from features.registry import discover_features
    discover_features()
    feat = FEATURE_REGISTRY["analyze_qualifying_battle"]

    result = {
        "available": True,
        "driver_a": "LEC", "driver_b": "NOR",
        "lap_time_a": "1:28.143", "lap_time_b": "1:28.183",
        "overall_gap_s": 0.040,
        "s1_gap_s": 0.131, "s2_gap_s": -0.081, "s3_gap_s": -0.010,
        "decisive_sector": "S1",
        "decisive_sector_gap_s": 0.131,
        "split_sector_lap": False,
        "markers": [],
    }
    widget = feat.make_widget(result)
    assert widget.get("decisive_sector") == "S1"
    assert widget.get("split_sector_lap") is False
```

- [ ] **Step 3: Run red**

```
cd server; python -m pytest tests/test_features_qualifying_battle.py -k "split_sector or decisive_sector" -v
```

May FAIL with KeyError or AttributeError, depending on whether the existing builder ignores the new fields.

- [ ] **Step 4: Update the widget builder**

In `server/features/qualifying_battle.py`'s `_build_qualifying_battle_widget`:

```python
def _build_qualifying_battle_widget(result: dict) -> dict:
    # ... existing fields ...
    widget = {
        "type": "qualifying_battle",
        # ... existing keys ...
        "decisive_sector": result.get("decisive_sector"),  # may be None
        "decisive_sector_gap_s": result.get("decisive_sector_gap_s"),
        "split_sector_lap": bool(result.get("split_sector_lap")),
        # ... markers, etc. ...
    }
    return widget
```

If the existing widget already passes `decisive_sector` through, the only change is adding `split_sector_lap`.

- [ ] **Step 5: Run green + full suite**

```
cd server; python -m pytest tests/test_features_qualifying_battle.py -v
cd server; python -m pytest tests/ -q 2>&1 | tail -3
```

- [ ] **Step 6: Commit**

```bash
git add server/features/qualifying_battle.py server/tests/test_features_qualifying_battle.py
git commit -m "feat(features): qualifying_battle widget surfaces split_sector_lap flag

Pass split_sector_lap through to the widget so the React component can
render 'gap built across all three sectors' instead of forcing a
decisive-sector narrative on diffuse laps.

Plan: docs/superpowers/plans/2026-05-22-quali-marker-time-contribution.md Task 3"
```

---

## Task 4: Update the analysis prompt so the LLM doesn't fabricate a decisive sector

**Files:**
- Modify: `server/chat.py` — `ANALYSIS_SYSTEM_PROMPT` (around line ~934) and/or the qualifying-battle-specific instructions

- [ ] **Step 1: Find where the analyzer is told about decisive sector**

Grep `server/chat.py` for `decisive_sector` and for `qualifying_battle`. The analyzer prompt likely has guidance like "report the decisive sector and mechanism." Update to handle the split case.

- [ ] **Step 2: Add split-sector handling to the prompt**

Append a brief instruction to the relevant prompt section:

```
When analyzing a qualifying_battle result, check the `split_sector_lap`
field on the result. If `split_sector_lap` is True (i.e. no single sector
owns >=55% of the total absolute gap), DO NOT claim a decisive sector.
Instead, say the gap built across multiple sectors and describe the
mechanism using the speed-trace markers regardless of sector. When
`split_sector_lap` is False, `decisive_sector` is authoritative — use it
and tie the markers to that sector if possible.
```

- [ ] **Step 3: Manual smoke test (no automated test)**

Restart uvicorn (`python -m uvicorn main:app --reload --port 8000` from `server/`), then ask the chat a quali question for a lap where you know the sector gap is split, and confirm the prose doesn't claim a decisive sector. If you don't have a split-sector example handy, skip this verification — the field is wired correctly and the LLM can be evaluated in production.

- [ ] **Step 4: Commit**

```bash
git add server/chat.py
git commit -m "feat(chat): analysis prompt handles split_sector_lap

When split_sector_lap is True, the analyzer is instructed not to claim
a decisive sector — instead describe the gap as built across multiple
sectors. When False, decisive_sector is authoritative.

Plan: docs/superpowers/plans/2026-05-22-quali-marker-time-contribution.md Task 4"
```

---

## Validation Checklist

- [ ] `_pick_speed_trace_markers` ranks by time contribution, not km/h.
- [ ] Apex-vs-straight test passes (low-speed wins).
- [ ] Sub-15% events are dropped.
- [ ] Variable marker count works (1-3, may be fewer).
- [ ] `_classify_decisive_sector` returns None when no sector owns >=55%.
- [ ] `analyze_qualifying_battle` puts both `decisive_sector` and `split_sector_lap` in the result.
- [ ] Widget builder forwards `split_sector_lap`.
- [ ] Analyzer prompt handles split case.
- [ ] Full suite passes (or only documented breakages updated, not loosened).

---

## Risks

| Risk | Trigger | Resolution |
|---|---|---|
| **Pre-existing tests assert specific marker output for fixtures where the new ranking picks different points** | Task 1 Step 6 | Update fixtures to expanded ones that exercise the time-contribution math, or update expected marker positions to the new (correct) ones. Don't loosen the gate. |
| **15% threshold is too aggressive on tight battles** (e.g. a 0.01s lap where everything is below 15% of total) | Production | The threshold is currently a parameter (`min_contribution_fraction`). Lower the default if real laps systematically return zero markers — but check with audit log first. |
| **Split-sector boundary case** (one sector at 54% of total) | Production | 55% is a heuristic; tweak after observing real distributions. Document the value. |
| **Frontend doesn't know about `split_sector_lap`** | React widget rendering | Phase F frontend work isn't scoped here. The field is added to the widget payload; React component can ignore it (no rendering change) until someone updates QualifyingBattleWidget.jsx to surface the split case. Filed as a follow-up. |

---

## Non-Goals

- Reshape the entire speed-trace marker UI in React.
- Change anything other than `analyze_qualifying_battle` and its widget.
- Add a new database/storage layer for audit-log tuning.
