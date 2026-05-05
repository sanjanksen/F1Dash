# Combined Grip Metrics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add combined grip utilisation, trail brake %, and circle fullness % to the cornering analysis tools so the LLM can describe a driver's total tyre commitment (not just lateral).

**Architecture:** Add `_compute_longitudinal_g()` alongside existing `_compute_lateral_g()`. Extend `_corner_metrics()` signature to accept long_g. Thread the new metrics through both cornering tools (`compare_cornering_loads` and `analyze_race_cornering_profile`). Add LLM vocabulary in `chat.py` and update tool descriptions in `tools.py`. All new fields are additive — nothing removed.

**Tech Stack:** Python, NumPy, scipy.signal.savgol_filter, FastF1, pytest

---

## Files Modified

- `server/f1_data.py` — new `_compute_longitudinal_g`, updated `_corner_metrics`, `compare_cornering_loads`, `_aggregate_lap_cornering_stats`, `analyze_race_cornering_profile`
- `server/chat.py` — extended system prompt vocabulary section
- `server/tools.py` — updated tool descriptions
- `server/tests/test_f1_data.py` — new unit tests

---

## Task 1: Add `_compute_longitudinal_g` and tests

**Files:**
- Modify: `server/f1_data.py` (after `_compute_lateral_g`, around line 5060)
- Modify: `server/tests/test_f1_data.py`

- [ ] **Step 1: Write the failing tests**

Add to `server/tests/test_f1_data.py`:

```python
def _make_tel_df(speeds_kph, times_s=None):
    """Helper: build a minimal telemetry DataFrame with Speed and Time."""
    import pandas as pd
    import numpy as np
    n = len(speeds_kph)
    if times_s is None:
        times_s = np.arange(n, dtype=float) * 0.1  # 100ms intervals
    return pd.DataFrame({
        'Speed': speeds_kph,
        'Time': pd.to_timedelta(times_s, unit='s'),
        'X': np.zeros(n),
        'Y': np.zeros(n),
        'Distance': np.arange(n, dtype=float),
    })


def test_compute_longitudinal_g_output_shape():
    import numpy as np
    speeds = np.ones(100) * 200.0
    tel = _make_tel_df(speeds)
    result = f1_data._compute_longitudinal_g(tel)
    assert result.shape == (100,)


def test_compute_longitudinal_g_braking_is_negative():
    import numpy as np
    # Linearly decelerating from 200 to 100 kph over 1 second
    speeds = np.linspace(200.0, 100.0, 50)
    times_s = np.linspace(0.0, 1.0, 50)
    tel = _make_tel_df(speeds, times_s)
    result = f1_data._compute_longitudinal_g(tel)
    # Most samples should be negative (braking)
    assert np.mean(result) < -0.5


def test_compute_longitudinal_g_acceleration_is_positive():
    import numpy as np
    # Linearly accelerating from 100 to 200 kph over 1 second
    speeds = np.linspace(100.0, 200.0, 50)
    times_s = np.linspace(0.0, 1.0, 50)
    tel = _make_tel_df(speeds, times_s)
    result = f1_data._compute_longitudinal_g(tel)
    assert np.mean(result) > 0.5


def test_compute_longitudinal_g_missing_time_returns_zeros():
    import numpy as np
    import pandas as pd
    # DataFrame with no Time column
    tel = pd.DataFrame({'Speed': np.ones(50) * 150.0})
    result = f1_data._compute_longitudinal_g(tel)
    assert np.all(result == 0.0)
    assert result.shape == (50,)
```

- [ ] **Step 2: Run tests to verify they fail**

```
cd server && python -m pytest tests/test_f1_data.py::test_compute_longitudinal_g_output_shape tests/test_f1_data.py::test_compute_longitudinal_g_braking_is_negative tests/test_f1_data.py::test_compute_longitudinal_g_acceleration_is_positive tests/test_f1_data.py::test_compute_longitudinal_g_missing_time_returns_zeros -v
```

Expected: FAIL — `AttributeError: module 'f1_data' has no attribute '_compute_longitudinal_g'`

- [ ] **Step 3: Implement `_compute_longitudinal_g`**

In `server/f1_data.py`, add this function directly after `_compute_lateral_g` (after line 5060, before `_theoretical_max_g`):

```python
def _compute_longitudinal_g(tel: pd.DataFrame) -> np.ndarray:
    """
    Derive longitudinal G from Speed channel: long_G = (dv/dt) / 9.81.
    Positive = accelerating, negative = braking.
    Falls back to zeros if Time column is missing.
    """
    n = len(tel)
    if 'Time' not in tel.columns or 'Speed' not in tel.columns or n < 3:
        return np.zeros(n)

    v_mps = tel['Speed'].to_numpy(dtype=float) / 3.6
    t_s = tel['Time'].dt.total_seconds().to_numpy(dtype=float)

    if not np.all(np.diff(t_s) >= 0):
        t_s = np.sort(t_s)

    long_g_raw = np.gradient(v_mps, t_s) / 9.81
    long_g_raw = np.clip(long_g_raw, -6.0, 4.0)

    wl = min(15, n if n % 2 == 1 else n - 1)
    wl = max(wl, 5)
    if wl % 2 == 0:
        wl -= 1
    if n >= wl:
        long_g = savgol_filter(long_g_raw, window_length=wl, polyorder=2)
    else:
        long_g = long_g_raw

    return np.clip(long_g, -6.0, 4.0)
```

- [ ] **Step 4: Run tests to verify they pass**

```
cd server && python -m pytest tests/test_f1_data.py::test_compute_longitudinal_g_output_shape tests/test_f1_data.py::test_compute_longitudinal_g_braking_is_negative tests/test_f1_data.py::test_compute_longitudinal_g_acceleration_is_positive tests/test_f1_data.py::test_compute_longitudinal_g_missing_time_returns_zeros -v
```

Expected: 4 PASSED

- [ ] **Step 5: Commit**

```
git add server/f1_data.py server/tests/test_f1_data.py
git commit -m "feat: add _compute_longitudinal_g from Speed dv/dt"
```

---

## Task 2: Extend `_corner_metrics` with three new fields

**Files:**
- Modify: `server/f1_data.py` (`_corner_metrics` function, lines 5095–5123)
- Modify: `server/tests/test_f1_data.py`

- [ ] **Step 1: Write the failing tests**

Add to `server/tests/test_f1_data.py`:

```python
def _make_corner_arrays(n=60):
    """
    Synthetic corner: speed dips from 200→100→200 kph (apex at midpoint),
    lat_g peaks at apex, long_g goes negative then positive (brake-then-throttle).
    """
    import numpy as np
    t = np.linspace(0, 1, n)
    speed = 200.0 - 100.0 * np.sin(np.pi * t)          # 200→100→200
    lat_g = 3.5 * np.sin(np.pi * t)                      # 0→3.5→0
    long_g = np.where(t < 0.5, -2.0 * (0.5 - t) * 4, 2.0 * (t - 0.5) * 4)  # braking then accel
    long_g = np.clip(long_g, -4.0, 4.0)
    dist = np.linspace(0, 150, n)
    return lat_g, long_g, speed, dist


def test_corner_metrics_new_fields_present():
    import numpy as np
    lat_g, long_g, speed, dist = _make_corner_arrays()
    result = f1_data._corner_metrics(lat_g, long_g, speed, dist, 0, len(lat_g) - 1)
    assert 'combined_util_pct' in result
    assert 'trail_brake_pct' in result
    assert 'circle_fullness_pct' in result


def test_corner_metrics_combined_util_gte_lateral():
    import numpy as np
    lat_g, long_g, speed, dist = _make_corner_arrays()
    result = f1_data._corner_metrics(lat_g, long_g, speed, dist, 0, len(lat_g) - 1)
    # Combined (lat+long vector) should be >= lateral-only util
    assert result['combined_util_pct'] >= result['mean_grip_util_pct'] - 0.1


def test_corner_metrics_trail_brake_zero_when_no_braking():
    import numpy as np
    n = 60
    lat_g = np.ones(n) * 2.0
    long_g = np.zeros(n)          # no braking whatsoever
    speed = np.ones(n) * 150.0
    dist = np.linspace(0, 150, n)
    result = f1_data._corner_metrics(lat_g, long_g, speed, dist, 0, n - 1)
    assert result['trail_brake_pct'] == 0.0


def test_corner_metrics_trail_brake_nonzero_when_braking_at_entry():
    import numpy as np
    n = 60
    apex = n // 2
    lat_g = np.ones(n) * 2.0
    # Braking hard in the entry phase only (before apex)
    long_g = np.where(np.arange(n) < apex, -2.0, 0.5)
    speed = np.linspace(200, 100, n // 2).tolist() + np.linspace(100, 200, n - n // 2).tolist()
    speed = np.array(speed)
    dist = np.linspace(0, 150, n)
    result = f1_data._corner_metrics(lat_g, long_g, speed, dist, 0, n - 1)
    assert result['trail_brake_pct'] > 50.0
```

- [ ] **Step 2: Run tests to verify they fail**

```
cd server && python -m pytest tests/test_f1_data.py::test_corner_metrics_new_fields_present tests/test_f1_data.py::test_corner_metrics_combined_util_gte_lateral tests/test_f1_data.py::test_corner_metrics_trail_brake_zero_when_no_braking tests/test_f1_data.py::test_corner_metrics_trail_brake_nonzero_when_braking_at_entry -v
```

Expected: FAIL — `TypeError: _corner_metrics() takes 5 positional arguments but 6 were given` (or similar)

- [ ] **Step 3: Update `_corner_metrics` signature and body**

Replace the current `_corner_metrics` function (lines 5095–5123) with:

```python
def _corner_metrics(lat_g: np.ndarray, long_g: np.ndarray, speed_kph: np.ndarray,
                    dist: np.ndarray, start: int, end: int) -> dict:
    seg_g = lat_g[start:end + 1]
    seg_lg = long_g[start:end + 1]
    seg_v = speed_kph[start:end + 1]
    seg_dist = dist[start:end + 1]
    n_seg = len(seg_g)

    apex_idx_local = int(np.argmin(seg_v))  # apex = min speed
    peak_idx_local = int(np.argmax(seg_g))

    g_max = _theoretical_max_g(seg_v)
    safe_gmax = np.where(g_max < 0.1, 0.1, g_max)

    # Lateral-only utilisation (kept for backward compat)
    util = np.clip(seg_g / safe_gmax, 0.0, 1.0)

    # Combined (vector) utilisation
    combined_g = np.sqrt(seg_g ** 2 + seg_lg ** 2)
    combined_util = np.clip(combined_g / safe_gmax, 0.0, 1.5)  # can exceed 1.0 briefly; cap at 1.5

    # Trail brake: % of entry phase (start→apex) where lat>0.4G AND long<-0.3G simultaneously
    entry_end = max(apex_idx_local, 1)
    entry_lat = seg_g[:entry_end]
    entry_long = seg_lg[:entry_end]
    trail_mask = (entry_lat > 0.4) & (entry_long < -0.3)
    trail_brake_pct = round(float(np.mean(trail_mask) * 100), 1) if len(trail_mask) > 0 else 0.0

    # Circle fullness: % of ALL corner samples where combined_util > 0.75
    circle_fullness_pct = round(float(np.mean(combined_util > 0.75) * 100), 1)

    # count sign changes in d(lat_g) as a proxy for steering corrections
    dlg = np.gradient(seg_g)
    sign_changes = int(np.sum(np.diff(np.sign(dlg)) != 0))

    return {
        "entry_g": round(float(seg_g[0]), 3),
        "apex_g": round(float(seg_g[apex_idx_local]), 3),
        "peak_g": round(float(seg_g[peak_idx_local]), 3),
        "exit_g": round(float(seg_g[-1]), 3),
        "mean_g": round(float(np.mean(seg_g)), 3),
        "load_variance": round(float(np.std(seg_g)), 3),
        "correction_count": sign_changes,
        "mean_grip_util_pct": round(float(np.mean(util) * 100), 1),
        "pct_time_above_90pct_grip": round(float(np.mean(util >= 0.9) * 100), 1),
        "combined_util_pct": round(float(np.mean(combined_util) * 100), 1),
        "trail_brake_pct": trail_brake_pct,
        "circle_fullness_pct": circle_fullness_pct,
        "entry_dist_m": round(float(seg_dist[0]), 0),
        "exit_dist_m": round(float(seg_dist[-1]), 0),
    }
```

- [ ] **Step 4: Run tests to verify they pass**

```
cd server && python -m pytest tests/test_f1_data.py::test_corner_metrics_new_fields_present tests/test_f1_data.py::test_corner_metrics_combined_util_gte_lateral tests/test_f1_data.py::test_corner_metrics_trail_brake_zero_when_no_braking tests/test_f1_data.py::test_corner_metrics_trail_brake_nonzero_when_braking_at_entry -v
```

Expected: 4 PASSED

- [ ] **Step 5: Commit**

```
git add server/f1_data.py server/tests/test_f1_data.py
git commit -m "feat: extend _corner_metrics with combined_util, trail_brake, circle_fullness"
```

---

## Task 3: Wire new metrics through `compare_cornering_loads`

**Files:**
- Modify: `server/f1_data.py` (`compare_cornering_loads` function, lines ~5148–5366)

This is the qualifying/single-lap cornering tool. Three changes:
1. Compute `long_g_a`, `long_g_b` and pass to `_corner_metrics`
2. Add new fields to `_summary()`
3. Extend narrative with combined util and trail brake sentences

- [ ] **Step 1: Compute long_g and thread into `_corner_metrics` calls**

In `compare_cornering_loads`, after line 5205 (`lat_g_b = _compute_lateral_g(tel_b)`), add:

```python
    long_g_a = _compute_longitudinal_g(tel_a)
    long_g_b = _compute_longitudinal_g(tel_b)
```

Then update the two `_corner_metrics` calls inside the `for i, (ca, cb) in enumerate(aligned):` loop (currently ~line 5219–5220):

```python
        ma = _corner_metrics(lat_g_a, long_g_a, spd_a, dist_a, ca[0], ca[1])
        mb = _corner_metrics(lat_g_b, long_g_b, spd_b, dist_b, cb[0], cb[1])
```

- [ ] **Step 2: Add new fields to the per_corner delta dict**

In the same loop, the per_corner.append call (currently ~line 5221–5230), add three delta fields after `"corrections_delta"`:

```python
        per_corner.append({
            "corner_index": i + 1,
            "entry_dist_m": int(ma["entry_dist_m"]),
            code_a: ma,
            code_b: mb,
            "peak_g_delta": round(ma["peak_g"] - mb["peak_g"], 3),
            "mean_grip_util_delta_pct": round(ma["mean_grip_util_pct"] - mb["mean_grip_util_pct"], 1),
            "load_variance_delta": round(ma["load_variance"] - mb["load_variance"], 3),
            "corrections_delta": ma["correction_count"] - mb["correction_count"],
            "combined_util_delta_pct": round(ma["combined_util_pct"] - mb["combined_util_pct"], 1),
            "trail_brake_delta_pct": round(ma["trail_brake_pct"] - mb["trail_brake_pct"], 1),
            "circle_fullness_delta_pct": round(ma["circle_fullness_pct"] - mb["circle_fullness_pct"], 1),
        })
```

- [ ] **Step 3: Add new fields to `_summary()`**

Inside `compare_cornering_loads`, the `_summary()` inner function (currently ends ~line 5260). After the `avg_var` computation, add:

```python
        if per_corner:
            avg_combined = round(sum(c[code]["combined_util_pct"] for c in per_corner) / len(per_corner), 1)
            avg_trail = round(sum(c[code]["trail_brake_pct"] for c in per_corner) / len(per_corner), 1)
            avg_fullness = round(sum(c[code]["circle_fullness_pct"] for c in per_corner) / len(per_corner), 1)
        else:
            avg_combined = avg_trail = avg_fullness = None
```

And add them to the return dict:

```python
        return {
            "avg_grip_utilisation_pct": avg_util,
            "pct_time_above_90pct_grip": pct_above_90,
            "peak_lateral_g": peak_g,
            "corners_detected": len(corners),
            "avg_corrections_per_corner": avg_corr,
            "avg_load_variance": avg_var,
            "avg_combined_util_pct": avg_combined,
            "avg_trail_brake_pct": avg_trail,
            "avg_circle_fullness_pct": avg_fullness,
        }
```

- [ ] **Step 4: Add narrative sentences for combined util and trail brake**

At the end of the narrative block in `compare_cornering_loads`, after the `# --- Corner spread ---` block (before the `return {` statement), add:

```python
    # --- Combined grip commitment (lat + long vector) ---
    comb_a = sum_a.get("avg_combined_util_pct") or 0.0
    comb_b = sum_b.get("avg_combined_util_pct") or 0.0
    if comb_a and comb_b and abs(comb_a - comb_b) >= 1.0:
        higher_comb = code_a if comb_a >= comb_b else code_b
        lower_comb = code_b if higher_comb == code_a else code_a
        narrative_parts.append(
            f"Factoring braking in alongside cornering, {higher_comb} was using more of the total grip envelope — "
            f"{max(comb_a, comb_b):.1f}% of combined capability vs {min(comb_a, comb_b):.1f}% for {lower_comb}. "
            f"The braking load was doing real work on top of the cornering commitment."
        )

    # --- Trail braking signature ---
    tb_a = sum_a.get("avg_trail_brake_pct") or 0.0
    tb_b = sum_b.get("avg_trail_brake_pct") or 0.0
    if tb_a or tb_b:
        if abs(tb_a - tb_b) >= 5.0:
            higher_tb = code_a if tb_a >= tb_b else code_b
            lower_tb = code_b if higher_tb == code_a else code_a
            narrative_parts.append(
                f"{higher_tb} was carrying the brake deep into the corner — "
                f"still on the pedal at turn-in for {max(tb_a, tb_b):.1f}% of the entry phase, "
                f"using it to rotate the car. {lower_tb} finished braking earlier ({min(tb_a, tb_b):.1f}%), "
                f"turning in on a cleaner line."
            )
        elif max(tb_a, tb_b) < 5.0:
            narrative_parts.append(
                f"Neither driver was trail braking meaningfully — both finishing braking before turn-in."
            )
```

- [ ] **Step 5: Run the full test suite to confirm nothing broke**

```
cd server && python -m pytest tests/ -v
```

Expected: all existing tests PASS (new fields are purely additive)

- [ ] **Step 6: Commit**

```
git add server/f1_data.py
git commit -m "feat: thread combined_util, trail_brake, circle_fullness through compare_cornering_loads"
```

---

## Task 4: Wire new metrics through `_aggregate_lap_cornering_stats` and `analyze_race_cornering_profile`

**Files:**
- Modify: `server/f1_data.py` (`_aggregate_lap_cornering_stats` ~lines 5369–5414, `analyze_race_cornering_profile` ~lines 5417–5628)

- [ ] **Step 1: Write the failing test**

Add to `server/tests/test_f1_data.py`:

```python
def test_aggregate_lap_cornering_stats_new_fields():
    import numpy as np
    import pandas as pd
    from unittest.mock import patch

    n = 300
    t_s = np.linspace(0, 30, n)
    # Speed: oscillates to create corners
    speed = 200.0 - 80.0 * np.abs(np.sin(np.pi * np.linspace(0, 6, n)))
    # Simple circular track
    theta = np.linspace(0, 4 * np.pi, n)
    x = np.cos(theta) * 200.0
    y = np.sin(theta) * 200.0
    dist = np.linspace(0, 1000, n)

    tel = pd.DataFrame({
        'Speed': speed,
        'Time': pd.to_timedelta(t_s, unit='s'),
        'X': x,
        'Y': y,
        'Distance': dist,
    })

    result = f1_data._aggregate_lap_cornering_stats(tel)
    assert result is not None
    assert 'avg_combined_util_pct' in result
    assert 'avg_trail_brake_pct' in result
    assert 'avg_circle_fullness_pct' in result
    assert 0 <= result['avg_combined_util_pct'] <= 200
    assert 0 <= result['avg_trail_brake_pct'] <= 100
    assert 0 <= result['avg_circle_fullness_pct'] <= 100
```

- [ ] **Step 2: Run test to verify it fails**

```
cd server && python -m pytest tests/test_f1_data.py::test_aggregate_lap_cornering_stats_new_fields -v
```

Expected: FAIL — `AssertionError: 'avg_combined_util_pct' not in result`

- [ ] **Step 3: Update `_aggregate_lap_cornering_stats`**

Replace the body of `_aggregate_lap_cornering_stats` (lines 5369–5414). The key changes: check for `Time` column, compute `long_g`, pass to `_corner_metrics`, collect new metric samples.

```python
def _aggregate_lap_cornering_stats(tel: pd.DataFrame) -> dict | None:
    """
    Compute aggregate cornering stats for a single lap's telemetry.
    All metrics are computed only within detected cornering segments (lat_G > 0.8G).
    Returns None if data is insufficient or missing required columns.
    """
    if any(c not in tel.columns for c in ('X', 'Y', 'Speed')):
        return None
    if len(tel) < 50:
        return None
    try:
        dist = tel['Distance'].to_numpy(dtype=float) if 'Distance' in tel.columns else np.arange(len(tel), dtype=float)
        spd = tel['Speed'].to_numpy(dtype=float)
        lat_g = _compute_lateral_g(tel)
        long_g = _compute_longitudinal_g(tel)
        corners = _detect_corners(lat_g, dist)
        if not corners:
            return None

        corner_util_samples = []
        corner_combined_util_samples = []
        corner_trail_brake_samples = []
        corner_fullness_samples = []
        corner_corrections = []
        corner_variances = []

        for c_start, c_end in corners:
            metrics = _corner_metrics(lat_g, long_g, spd, dist, c_start, c_end)
            seg_g = lat_g[c_start:c_end + 1]
            seg_v = spd[c_start:c_end + 1]
            seg_gmax = _theoretical_max_g(seg_v)
            seg_util = np.clip(seg_g / np.where(seg_gmax < 0.1, 0.1, seg_gmax), 0.0, 1.0)
            corner_util_samples.extend(seg_util.tolist())
            corner_combined_util_samples.append(metrics['combined_util_pct'])
            corner_trail_brake_samples.append(metrics['trail_brake_pct'])
            corner_fullness_samples.append(metrics['circle_fullness_pct'])
            corner_corrections.append(metrics['correction_count'])
            corner_variances.append(float(np.std(seg_g)))

        if not corner_util_samples:
            return None

        cu = np.array(corner_util_samples)
        return {
            "avg_corner_grip_util_pct": round(float(np.mean(cu) * 100), 1),
            "pct_above_90pct_grip": round(float(np.mean(cu >= 0.9) * 100), 1),
            "corners_detected": len(corners),
            "avg_corrections_per_corner": round(float(np.mean(corner_corrections)), 1),
            "avg_load_variance": round(float(np.mean(corner_variances)), 3),
            "avg_combined_util_pct": round(float(np.mean(corner_combined_util_samples)), 1),
            "avg_trail_brake_pct": round(float(np.mean(corner_trail_brake_samples)), 1),
            "avg_circle_fullness_pct": round(float(np.mean(corner_fullness_samples)), 1),
        }
    except Exception:
        return None
```

- [ ] **Step 4: Update `_aggregate()` inside `analyze_race_cornering_profile`**

The `_aggregate` inner function (around line 5485) currently averages 4 fields. Extend it to average the 3 new fields:

```python
    def _aggregate(laps_data: list[dict]) -> dict:
        if not laps_data:
            return {"laps_analyzed": 0}
        return {
            "laps_analyzed": len(laps_data),
            "avg_corner_grip_util_pct": round(float(np.mean([l["avg_corner_grip_util_pct"] for l in laps_data])), 1),
            "pct_above_90pct_grip": round(float(np.mean([l["pct_above_90pct_grip"] for l in laps_data])), 1),
            "avg_corrections_per_corner": round(float(np.mean([l["avg_corrections_per_corner"] for l in laps_data])), 1),
            "avg_load_variance": round(float(np.mean([l["avg_load_variance"] for l in laps_data])), 3),
            "avg_combined_util_pct": round(float(np.mean([l.get("avg_combined_util_pct", 0.0) for l in laps_data])), 1),
            "avg_trail_brake_pct": round(float(np.mean([l.get("avg_trail_brake_pct", 0.0) for l in laps_data])), 1),
            "avg_circle_fullness_pct": round(float(np.mean([l.get("avg_circle_fullness_pct", 0.0) for l in laps_data])), 1),
        }
```

- [ ] **Step 5: Add narrative sentences to `analyze_race_cornering_profile`**

After the `# --- Stint-level confidence shifts ---` block (before `return {`), add:

```python
    # --- Combined grip commitment across the race ---
    comb_a = overall_a.get("avg_combined_util_pct", 0.0)
    comb_b = overall_b.get("avg_combined_util_pct", 0.0)
    if comb_a and comb_b and abs(comb_a - comb_b) >= 1.0:
        higher_comb = code_a if comb_a >= comb_b else code_b
        lower_comb = code_b if higher_comb == code_a else code_a
        narrative_parts.append(
            f"Factoring in braking across {laps_a_count} laps for {code_a} and {laps_b_count} for {code_b}, "
            f"{higher_comb} was asking more of the total grip envelope — "
            f"{max(comb_a, comb_b):.1f}% combined vs {min(comb_a, comb_b):.1f}% for {lower_comb}. "
            f"That's braking commitment piling on top of the cornering load, lap after lap."
        )

    # --- Trail braking style across the race ---
    tb_a = overall_a.get("avg_trail_brake_pct", 0.0)
    tb_b = overall_b.get("avg_trail_brake_pct", 0.0)
    if abs(tb_a - tb_b) >= 5.0:
        higher_tb = code_a if tb_a >= tb_b else code_b
        lower_tb = code_b if higher_tb == code_a else code_a
        narrative_parts.append(
            f"{higher_tb} was the trail braker of the two — still on the brakes at turn-in "
            f"for {max(tb_a, tb_b):.1f}% of corner entry across the race vs {min(tb_a, tb_b):.1f}% for {lower_tb}. "
            f"Over a full race distance that front-tyre load difference adds up."
        )
```

- [ ] **Step 6: Run new test to verify it passes**

```
cd server && python -m pytest tests/test_f1_data.py::test_aggregate_lap_cornering_stats_new_fields -v
```

Expected: PASS

- [ ] **Step 7: Run full test suite**

```
cd server && python -m pytest tests/ -v
```

Expected: all tests PASS

- [ ] **Step 8: Commit**

```
git add server/f1_data.py server/tests/test_f1_data.py
git commit -m "feat: thread combined_util, trail_brake, circle_fullness through race cornering tool"
```

---

## Task 5: Update tool descriptions in `tools.py`

**Files:**
- Modify: `server/tools.py` (lines ~500–521)

- [ ] **Step 1: Update `analyze_cornering_loads` description**

Find the description string for `analyze_cornering_loads` (around line 501). Replace it with:

```python
        "DEEP ANALYSIS PRIMITIVE. Compute lateral G and grip utilisation for two drivers across all corners of their fastest laps, "
        "using curvature derived from X/Y position telemetry. Returns per-corner stats (peak G, apex G, load variance, "
        "steering correction count, % time above 90% theoretical grip) plus an overall summary and a human-readable narrative. "
        "Also returns: combined grip utilisation % (lat+long vector vs theoretical max), "
        "trail brake % at corner entry (% of entry where braking and cornering overlap), "
        "circle fullness % (% of cornering time near the combined grip ceiling). "
        "Use this for qualifying / single-lap grip style comparisons.",
```

- [ ] **Step 2: Update `analyze_race_cornering_profile` description**

Find the description string for `analyze_race_cornering_profile` (around line 518). Replace it with:

```python
        "DEEP ANALYSIS PRIMITIVE. Compute lateral G and grip utilisation aggregated across an ENTIRE RACE for two drivers. "
        "Processes every clean race lap (pit laps excluded) and returns overall summary stats plus a per-stint breakdown. "
        "Use this when asked about race-long grip usage, tyre stress, or who pushes harder through corners over a full race distance. "
        "Returns: avg corner grip utilisation %, % cornering time above 90% grip, corrections per corner, load variance per stint, "
        "combined grip utilisation % (lat+long vector), trail brake % at corner entry, circle fullness % per stint and overall.",
```

- [ ] **Step 3: Run test suite to confirm nothing broken**

```
cd server && python -m pytest tests/ -v
```

Expected: all PASSED

- [ ] **Step 4: Commit**

```
git add server/tools.py
git commit -m "feat: update tool descriptions with combined grip, trail brake, circle fullness"
```

---

## Task 6: Extend system prompt vocabulary in `chat.py`

**Files:**
- Modify: `server/chat.py` (system prompt section starting around line 775)

- [ ] **Step 1: Add new metric vocabulary after the existing metrics block**

In `chat.py`, find the line `**Rules:**` (around line 799) in the cornering section. Insert the following block **before** those rules:

```
- **avg_combined_util_pct** → Total tyre commitment across both cornering AND braking combined. Higher = the driver is asking more of the tyre across both dimensions simultaneously.
  High (>85%): *fully committed*, *nothing left in reserve*, *using every gram of rubber*, *the tyre is working in every dimension*
  Compare to avg_grip_utilisation_pct: if combined is noticeably higher than lateral, the driver loads the tyre heavily under braking too — it's not just the cornering.
  Never say "combined grip utilisation" or "combined util" in your answer. Say: "when you factor in braking on top of cornering, {driver} was using more of the tyre's total capability."

- **avg_trail_brake_pct** → % of corner entry spent simultaneously cornering AND braking. Exposed as a raw % for the LLM to characterise in words.
  High (>35%): *carrying the brake deep*, *loading the front to rotate*, *still on the pedal at turn-in*, *using the brake as a rotation tool*, *trail-braking all the way to the apex*
  Low (<10%): *finishes braking before the corner*, *clean turn-in on a neutral throttle*, *textbook entry — brake done, then commit*
  Never say "trail brake percentage" in your answer. Say: "{driver} was still on the brakes at turn-in for X% of the entry phase — using it to load the front and rotate."

- **avg_circle_fullness_pct** → % of cornering time where the driver is near the combined grip ceiling (using >75% of total theoretical grip across both lat and long). Rewards blending both dimensions continuously rather than touching the ceiling only at apex.
  High (>55%): *barely eases off through the whole corner*, *the tyre is working hard start to finish*, *no coasting — every phase of the corner is demanding something*, *living at the limit from entry to exit*
  Low (<30%): *has a comfort margin mid-corner*, *eases off at the apex*, *keeps something in reserve*, *the middle of the corner is where the time gets left*
  Never say "circle fullness" in your answer.
```

- [ ] **Step 2: Add combined signal inferences to the existing inference table**

Find the `**Inferences you can draw from combined signals:**` block (around line 788). Add these after the existing entries:

```
- High combined_util + high trail_brake = *front-loading style* — loads the entry with the brake to rotate, the front tyre working in both dimensions. Strong single-lap weapon but hard on front tyres over a stint.
- High combined_util + low trail_brake = *apex commitment* — finishes braking before turn-in but carries huge mid-corner speed. The load is clean but the tyre is working hard through the middle.
- Low combined_util + high trail_brake = *defensive rotation* — using trail brake to rotate without fully committing combined load. Protective entry style.
- High circle_fullness + low load_variance = *smooth limit driver* — operating near the total grip ceiling throughout the corner without fighting it. The ideal.
```

- [ ] **Step 3: Run test suite**

```
cd server && python -m pytest tests/ -v
```

Expected: all PASSED (chat.py is not tested directly for prompt content)

- [ ] **Step 4: Commit**

```
git add server/chat.py
git commit -m "feat: add combined_util, trail_brake, circle_fullness vocabulary to system prompt"
```

---

## Task 7: Final verification

- [ ] **Step 1: Run the full test suite one final time**

```
cd server && python -m pytest tests/ -v
```

Expected: all tests PASS, none skipped

- [ ] **Step 2: Verify the existing chat test still passes**

```
cd server && python -m pytest tests/test_chat.py::test_qualifying_widget_includes_grip_commitment_from_cornering_loads -v
```

Expected: PASS (new fields are additive, not replacing anything)

- [ ] **Step 3: Final commit if anything was missed**

```
git add -p
git commit -m "chore: final cleanup for combined grip metrics"
```
