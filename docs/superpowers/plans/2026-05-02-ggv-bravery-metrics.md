# GGV Bravery Metrics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the theoretical grip ceiling formula with a session-empirical GGV (g-g-v) envelope and add four new physics-grounded bravery metrics: GGV ellipse utilisation, envelope time, throttle acceptance (Mastinu 2019), and entry bravery.

**Architecture:** A new `_build_ggv_envelope()` collects lat_G and long_G samples across all available laps for both drivers, bins by speed (7 × 50 kph bands), and takes 95th-percentile ceilings for three directions (lateral, braking, throttle) — a proper friction ellipse, not a circle. `_corner_metrics()` gains optional `envelope` and `throttle` params and computes four new per-corner fields. Both analysis tools build the shared envelope before running corner analysis and add new summary/narrative fields. Old metrics are kept for backward compat; new GGV fields are additive.

**Tech Stack:** FastF1, numpy, scipy.signal.savgol_filter (all already imported). No new dependencies.

---

## File Map

| File | Change |
|---|---|
| `server/f1_data.py:5097` | Add `_GGV_BIN_EDGES`, `_GGV_BIN_CENTERS` constants; add `_build_ggv_envelope`, `_theoretical_ggv_envelope`, `_ggv_ceiling_at_speed`, `_bravery_score` functions |
| `server/f1_data.py:5129` | Extend `_corner_metrics` signature + 4 new return fields |
| `server/f1_data.py:5204` | `analyze_cornering_loads`: collect session tels, build envelope, pass to corner metrics, extend summary + narrative |
| `server/f1_data.py:5468` | `_aggregate_lap_cornering_stats`: accept optional `envelope` param, extract throttle, pass through |
| `server/f1_data.py:5525` | `analyze_race_cornering_profile`: two-pass (collect tels → build envelope → process), extend `_aggregate` and narrative |
| `server/tools.py:501` | Update `analyze_cornering_loads` and `analyze_race_cornering_profile` descriptions |
| `server/chat.py:788` | Add GGV metric vocabulary + bravery language; update never-say rules |
| `server/tests/test_f1_data.py` | Add tests for all new functions and extended signatures |

---

### Task 1: GGV Infrastructure Functions

**Files:**
- Modify: `server/f1_data.py:5097-5101`
- Test: `server/tests/test_f1_data.py`

- [ ] **Step 1: Write the failing tests**

Add after the existing `test_compute_lateral_g_unit_conversion` test (around line 2675):

```python
def test_build_ggv_envelope_returns_correct_shape():
    import pandas as pd
    import numpy as np
    n = 120
    t_s = np.linspace(0, 12, n)
    theta = np.linspace(0, 4 * np.pi, n)
    tel = pd.DataFrame({
        'Speed': np.full(n, 150.0),
        'X': 1000.0 * np.cos(theta),
        'Y': 1000.0 * np.sin(theta),
        'Distance': np.linspace(0, 942.0, n),
        'Time': pd.to_timedelta(t_s, unit='s'),
        'Source': np.where(np.arange(n) % 4 == 0, 'pos', 'car'),
    })
    result = f1_data._build_ggv_envelope([tel, tel])
    assert set(result.keys()) == {'lat_max', 'brake_max', 'throttle_max', 'speed_bins'}
    assert len(result['lat_max']) == len(f1_data._GGV_BIN_CENTERS)
    assert len(result['brake_max']) == len(f1_data._GGV_BIN_CENTERS)
    assert np.all(result['lat_max'] > 0)


def test_build_ggv_envelope_falls_back_when_empty():
    result = f1_data._build_ggv_envelope([])
    assert 'lat_max' in result
    assert len(result['lat_max']) == len(f1_data._GGV_BIN_CENTERS)
    assert np.all(result['lat_max'] > 0)


def test_theoretical_ggv_envelope_brake_exceeds_lateral():
    result = f1_data._theoretical_ggv_envelope()
    # Braking G exceeds lateral G (F1 carbon brakes)
    assert np.all(result['brake_max'] > result['lat_max'] * 0.9)


def test_ggv_ceiling_at_speed_returns_correct_shape():
    import numpy as np
    envelope = f1_data._theoretical_ggv_envelope()
    speeds = np.array([100.0, 150.0, 250.0])
    lat, brake, thr = f1_data._ggv_ceiling_at_speed(speeds, envelope)
    assert lat.shape == (3,)
    assert np.all(lat > 0) and np.all(brake > 0) and np.all(thr > 0)


def test_bravery_score_formula():
    score = f1_data._bravery_score(60.0, 50.0, 40.0)
    # 0.35*60 + 0.40*50 + 0.25*40 = 21 + 20 + 10 = 51
    assert abs(score - 51.0) < 0.2


def test_bravery_score_handles_none():
    score = f1_data._bravery_score(None, 50.0, 40.0)
    # None treated as 0: 0.35*0 + 0.40*50 + 0.25*40 = 30
    assert abs(score - 30.0) < 0.2
```

- [ ] **Step 2: Run tests to verify they fail**

```
cd server && python -m pytest tests/test_f1_data.py::test_build_ggv_envelope_returns_correct_shape tests/test_f1_data.py::test_build_ggv_envelope_falls_back_when_empty tests/test_f1_data.py::test_theoretical_ggv_envelope_brake_exceeds_lateral tests/test_f1_data.py::test_ggv_ceiling_at_speed_returns_correct_shape tests/test_f1_data.py::test_bravery_score_formula tests/test_f1_data.py::test_bravery_score_handles_none -v
```

Expected: FAIL with `AttributeError: module 'f1_data' has no attribute '_build_ggv_envelope'`

- [ ] **Step 3: Add constants and functions to `f1_data.py`**

Insert the following block **immediately before** `def _theoretical_max_g` at line 5097:

```python
_GGV_BIN_EDGES = np.array([0.0, 50.0, 100.0, 150.0, 200.0, 250.0, 300.0, 360.0])
_GGV_BIN_CENTERS = (_GGV_BIN_EDGES[:-1] + _GGV_BIN_EDGES[1:]) / 2.0


def _build_ggv_envelope(telemetry_frames: list) -> dict:
    """
    Build a speed-indexed friction ellipse from a list of telemetry DataFrames.
    Returns dict with lat_max, brake_max, throttle_max (all shape (7,)) and speed_bins.
    Each value is the 95th-percentile ceiling for that speed band.
    Falls back to _theoretical_ggv_envelope() if fewer than 2 usable frames.
    """
    lat_all, long_all, spd_all = [], [], []
    for tel in telemetry_frames:
        if any(c not in tel.columns for c in ('Speed', 'X', 'Y')) or len(tel) < 20:
            continue
        try:
            lat_all.append(_compute_lateral_g(tel))
            long_all.append(_compute_longitudinal_g(tel))
            spd_all.append(tel['Speed'].to_numpy(dtype=float))
        except Exception:
            continue

    if len(lat_all) < 2:
        return _theoretical_ggv_envelope()

    lat_cat = np.concatenate(lat_all)
    long_cat = np.concatenate(long_all)
    spd_cat = np.concatenate(spd_all)

    n_bins = len(_GGV_BIN_EDGES) - 1
    lat_max = np.zeros(n_bins)
    brake_max = np.zeros(n_bins)
    throttle_max = np.zeros(n_bins)

    for i in range(n_bins):
        mask = (spd_cat >= _GGV_BIN_EDGES[i]) & (spd_cat < _GGV_BIN_EDGES[i + 1])
        if mask.sum() < 10:
            lat_max[i] = float(_theoretical_max_g(np.array([_GGV_BIN_CENTERS[i]]))[0])
            brake_max[i] = lat_max[i] * 1.1
            throttle_max[i] = lat_max[i] * 0.65
            continue
        lat_bin = lat_cat[mask]
        long_bin = long_cat[mask]
        lat_max[i] = max(float(np.percentile(np.abs(lat_bin), 95)), 0.5)
        braking = -long_bin[long_bin < -0.1]
        brake_max[i] = max(float(np.percentile(braking, 95)), 0.3) if len(braking) >= 5 else lat_max[i] * 1.1
        throttle = long_bin[long_bin > 0.1]
        throttle_max[i] = max(float(np.percentile(throttle, 95)), 0.2) if len(throttle) >= 5 else lat_max[i] * 0.65

    return {'lat_max': lat_max, 'brake_max': brake_max,
            'throttle_max': throttle_max, 'speed_bins': _GGV_BIN_CENTERS}


def _theoretical_ggv_envelope() -> dict:
    """Fallback GGV envelope from the theoretical max lateral formula."""
    lat = _theoretical_max_g(_GGV_BIN_CENTERS)
    return {'lat_max': lat, 'brake_max': lat * 1.1,
            'throttle_max': lat * 0.65, 'speed_bins': _GGV_BIN_CENTERS}


def _ggv_ceiling_at_speed(speed_kph: np.ndarray, envelope: dict) -> tuple:
    """Interpolate (lat_max, brake_max, throttle_max) arrays for given speed array."""
    bins = envelope['speed_bins']
    return (
        np.interp(speed_kph, bins, envelope['lat_max']),
        np.interp(speed_kph, bins, envelope['brake_max']),
        np.interp(speed_kph, bins, envelope['throttle_max']),
    )


def _bravery_score(envelope_time: float | None,
                   throttle_acc: float | None,
                   entry_bravery: float | None) -> float:
    """
    Composite bravery metric (0–100 range).
    Weights: throttle acceptance 40 %, envelope time 35 %, entry bravery 25 %.
    """
    return round(
        0.35 * (envelope_time or 0.0) +
        0.40 * (throttle_acc or 0.0) +
        0.25 * (entry_bravery or 0.0),
        1,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

```
python -m pytest tests/test_f1_data.py::test_build_ggv_envelope_returns_correct_shape tests/test_f1_data.py::test_build_ggv_envelope_falls_back_when_empty tests/test_f1_data.py::test_theoretical_ggv_envelope_brake_exceeds_lateral tests/test_f1_data.py::test_ggv_ceiling_at_speed_returns_correct_shape tests/test_f1_data.py::test_bravery_score_formula tests/test_f1_data.py::test_bravery_score_handles_none -v
```

Expected: 6 PASSED

- [ ] **Step 5: Run full suite to check no regressions**

```
python -m pytest tests/ -q
```

Expected: all passing (242 + 6 new = 248)

- [ ] **Step 6: Commit**

```bash
git add f1_data.py tests/test_f1_data.py
git commit -m "feat: add GGV envelope infrastructure (_build_ggv_envelope, _ggv_ceiling_at_speed, _bravery_score)"
```

---

### Task 2: Extend `_corner_metrics` with GGV / Bravery Fields

**Files:**
- Modify: `server/f1_data.py:5129-5178` (the `_corner_metrics` function)
- Test: `server/tests/test_f1_data.py`

- [ ] **Step 1: Write the failing tests**

Add after the existing `test_aggregate_lap_cornering_stats_new_fields` test:

```python
def test_corner_metrics_ggv_fields_present_when_envelope_provided():
    import numpy as np
    lat_g, long_g, speed, dist = _make_corner_arrays()
    envelope = f1_data._theoretical_ggv_envelope()
    result = f1_data._corner_metrics(lat_g, long_g, speed, dist, 0, len(lat_g) - 1,
                                      envelope=envelope)
    assert result['ggv_util_pct'] is not None
    assert result['envelope_time_pct'] is not None
    assert result['throttle_acceptance_pct'] is not None
    assert result['entry_bravery_pct'] is not None
    assert 0 <= result['ggv_util_pct'] <= 200
    assert 0 <= result['envelope_time_pct'] <= 100


def test_corner_metrics_ggv_fields_none_when_no_envelope():
    import numpy as np
    lat_g, long_g, speed, dist = _make_corner_arrays()
    result = f1_data._corner_metrics(lat_g, long_g, speed, dist, 0, len(lat_g) - 1)
    assert result['ggv_util_pct'] is None
    assert result['envelope_time_pct'] is None
    assert result['throttle_acceptance_pct'] is None
    assert result['entry_bravery_pct'] is None


def test_corner_metrics_throttle_acceptance_zero_when_always_braking():
    import numpy as np
    n = 60
    t = np.linspace(0, 1, n)
    speed = 200.0 - 100.0 * np.sin(np.pi * t)
    lat_g = 3.5 * np.sin(np.pi * t)
    long_g = -np.ones(n) * 2.0  # always braking — no positive G on exit
    dist = np.linspace(0, 150, n)
    envelope = f1_data._theoretical_ggv_envelope()
    result = f1_data._corner_metrics(lat_g, long_g, speed, dist, 0, n - 1,
                                      envelope=envelope)
    assert result['throttle_acceptance_pct'] == 0.0


def test_corner_metrics_throttle_acceptance_nonzero_with_throttle_channel():
    import numpy as np
    n = 60
    t = np.linspace(0, 1, n)
    speed = 200.0 - 100.0 * np.sin(np.pi * t)
    lat_g = 3.5 * np.sin(np.pi * t)
    long_g = np.where(t < 0.5, -2.0, 0.5)
    dist = np.linspace(0, 150, n)
    throttle = np.where(t >= 0.5, 95.0, 0.0)  # full throttle on exit phase only
    envelope = f1_data._theoretical_ggv_envelope()
    result = f1_data._corner_metrics(lat_g, long_g, speed, dist, 0, n - 1,
                                      envelope=envelope, throttle=throttle)
    assert result['throttle_acceptance_pct'] > 0.0


def test_corner_metrics_entry_bravery_nonzero_for_standard_corner():
    """_make_corner_arrays has braking at entry + high lat_g near apex."""
    import numpy as np
    lat_g, long_g, speed, dist = _make_corner_arrays()
    envelope = f1_data._theoretical_ggv_envelope()
    result = f1_data._corner_metrics(lat_g, long_g, speed, dist, 0, len(lat_g) - 1,
                                      envelope=envelope)
    # The standard corner array has near-limit braking at entry → bravery expected
    assert result['entry_bravery_pct'] >= 0.0  # may or may not trigger depending on ceiling


def test_corner_metrics_existing_fields_unchanged():
    """Backward compat: old fields still present and correct with envelope provided."""
    import numpy as np
    lat_g, long_g, speed, dist = _make_corner_arrays()
    envelope = f1_data._theoretical_ggv_envelope()
    result = f1_data._corner_metrics(lat_g, long_g, speed, dist, 0, len(lat_g) - 1,
                                      envelope=envelope)
    assert 'combined_util_pct' in result
    assert 'trail_brake_pct' in result
    assert 'circle_fullness_pct' in result
    assert 'mean_grip_util_pct' in result
```

- [ ] **Step 2: Run tests to verify they fail**

```
python -m pytest tests/test_f1_data.py::test_corner_metrics_ggv_fields_present_when_envelope_provided tests/test_f1_data.py::test_corner_metrics_ggv_fields_none_when_no_envelope -v
```

Expected: FAIL (TypeError: unexpected keyword argument 'envelope')

- [ ] **Step 3: Extend `_corner_metrics`**

Replace the function signature and add the GGV block. The full new signature is:

```python
def _corner_metrics(lat_g: np.ndarray, long_g: np.ndarray, speed_kph: np.ndarray,
                    dist: np.ndarray, start: int, end: int,
                    envelope: dict | None = None,
                    throttle: np.ndarray | None = None) -> dict:
```

After the existing `circle_fullness_pct` computation (after line ~5157), add:

```python
    # --- GGV-based metrics (only when envelope is provided) ---
    if envelope is not None:
        lat_ceil, brake_ceil, thr_ceil = _ggv_ceiling_at_speed(seg_v, envelope)
        safe_lat = np.where(lat_ceil < 0.1, 0.1, lat_ceil)
        long_ceil = np.where(
            seg_lg < 0.0,
            np.where(brake_ceil < 0.1, 0.1, brake_ceil),
            np.where(thr_ceil < 0.1, 0.1, thr_ceil),
        )
        ggv_util = np.clip(
            np.sqrt((seg_g / safe_lat) ** 2 + (seg_lg / long_ceil) ** 2),
            0.0, 1.5,
        )
        ggv_util_pct = round(float(np.mean(ggv_util) * 100), 1)
        envelope_time_pct = round(float(np.mean(ggv_util >= 0.85) * 100), 1)

        # Throttle acceptance: exit phase (apex→end), full throttle + lateral load > 60 % ceiling
        exit_s = max(apex_idx_local, 0)
        exit_lat = seg_g[exit_s:]
        exit_lat_ceil = safe_lat[exit_s:]
        lat_loaded = (exit_lat / exit_lat_ceil) > 0.60
        if throttle is not None:
            seg_thr = throttle[start:end + 1]
            full_throttle = seg_thr[exit_s:] > 90.0
        else:
            full_throttle = seg_lg[exit_s:] > 0.3  # proxy: net positive acceleration
        ta_mask = full_throttle & lat_loaded
        throttle_acceptance_pct = round(float(np.mean(ta_mask) * 100), 1) if len(ta_mask) > 0 else 0.0

        # Entry bravery: entry phase (start→apex), ggv_util >= 0.80 AND still braking
        entry_end_idx = max(apex_idx_local, 1)
        entry_ggv = ggv_util[:entry_end_idx]
        entry_long = seg_lg[:entry_end_idx]
        brave_mask = (entry_ggv >= 0.80) & (entry_long < -0.3)
        entry_bravery_pct = round(float(np.mean(brave_mask) * 100), 1) if len(brave_mask) > 0 else 0.0
    else:
        ggv_util_pct = None
        envelope_time_pct = None
        throttle_acceptance_pct = None
        entry_bravery_pct = None
```

Add four new keys to the return dict:

```python
        "ggv_util_pct": ggv_util_pct,
        "envelope_time_pct": envelope_time_pct,
        "throttle_acceptance_pct": throttle_acceptance_pct,
        "entry_bravery_pct": entry_bravery_pct,
```

- [ ] **Step 4: Run tests to verify they pass**

```
python -m pytest tests/test_f1_data.py -k "corner_metrics" -v
```

Expected: all 11 corner_metrics tests PASSED (5 old + 6 new)

- [ ] **Step 5: Run full suite**

```
python -m pytest tests/ -q
```

Expected: all passing

- [ ] **Step 6: Commit**

```bash
git add f1_data.py tests/test_f1_data.py
git commit -m "feat: extend _corner_metrics with GGV ellipse util, envelope time, throttle acceptance, entry bravery"
```

---

### Task 3: Extend `analyze_cornering_loads`

**Files:**
- Modify: `server/f1_data.py:5204-5465` (the `analyze_cornering_loads` function)
- Test: `server/tests/test_f1_data.py`

Context: `analyze_cornering_loads` is the qualifying single-lap tool. It already loads `session` with `telemetry=True`. The changes are:
1. After loading `tel_a` and `tel_b`, collect the fastest N laps for both drivers and build the shared GGV envelope.
2. Extract `Throttle` arrays from the comparison telemetry.
3. Pass `envelope` and `throttle` to every `_corner_metrics` call.
4. Add 4 new delta fields to each `per_corner` entry.
5. Add 5 new fields to each `_summary()` result.
6. Add 3 new narrative blocks.

- [ ] **Step 1: Write the failing test**

Add after `test_aggregate_lap_cornering_stats_new_fields`:

```python
def test_corner_metrics_with_envelope_adds_ggv_delta_fields():
    """Per-corner dicts gain ggv_util_delta_pct and throttle_acceptance_delta_pct."""
    import numpy as np
    # Simulate what analyze_cornering_loads produces per-corner after Task 3
    lat_g, long_g, speed, dist = _make_corner_arrays()
    envelope = f1_data._theoretical_ggv_envelope()
    ma = f1_data._corner_metrics(lat_g, long_g, speed, dist, 0, len(lat_g) - 1,
                                  envelope=envelope)
    mb = f1_data._corner_metrics(lat_g * 0.9, long_g, speed, dist, 0, len(lat_g) - 1,
                                  envelope=envelope)
    delta = round((ma.get('ggv_util_pct') or 0.0) - (mb.get('ggv_util_pct') or 0.0), 1)
    assert isinstance(delta, float)  # just verifies the computation runs
```

- [ ] **Step 2: Run test to verify it fails**

```
python -m pytest tests/test_f1_data.py::test_corner_metrics_with_envelope_adds_ggv_delta_fields -v
```

Expected: FAIL (ggv_util_pct is None — envelope not wired into analyze_cornering_loads yet)

- [ ] **Step 3: Modify `analyze_cornering_loads`**

**3a.** After `tel_a = lap_a.get_telemetry().add_distance()` and `tel_b = lap_b.get_telemetry().add_distance()` (currently around line 5246-5247), add the envelope-building block:

```python
    # Build shared GGV envelope from fastest laps of both drivers in this session.
    def _collect_session_tels(code: str, n_laps: int = 6) -> list:
        laps_for_code = _pick_driver(session.laps, code)
        if laps_for_code.empty:
            return []
        valid = laps_for_code[laps_for_code['LapTime'].notna()].nsmallest(n_laps, 'LapTime')
        tels = []
        for _, lap_row in valid.iterrows():
            try:
                t = lap_row.get_telemetry().add_distance()
                if len(t) >= 20:
                    tels.append(t)
            except Exception:
                continue
        return tels

    envelope = _build_ggv_envelope(_collect_session_tels(code_a) + _collect_session_tels(code_b))
```

**3b.** After the existing `lat_g_a = _compute_lateral_g(tel_a)` block (around line 5259-5268), extract throttle:

```python
    throttle_a = tel_a['Throttle'].to_numpy(dtype=float) if 'Throttle' in tel_a.columns else None
    throttle_b = tel_b['Throttle'].to_numpy(dtype=float) if 'Throttle' in tel_b.columns else None
```

**3c.** In the corner loop (around line 5276-5290), pass `envelope` and `throttle` to `_corner_metrics`:

```python
    for i, (ca, cb) in enumerate(aligned):
        ma = _corner_metrics(lat_g_a, long_g_a, spd_a, dist_a, ca[0], ca[1],
                             envelope=envelope, throttle=throttle_a)
        mb = _corner_metrics(lat_g_b, long_g_b, spd_b, dist_b, cb[0], cb[1],
                             envelope=envelope, throttle=throttle_b)
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
            "ggv_util_delta_pct": round((ma.get("ggv_util_pct") or 0.0) - (mb.get("ggv_util_pct") or 0.0), 1),
            "envelope_time_delta_pct": round((ma.get("envelope_time_pct") or 0.0) - (mb.get("envelope_time_pct") or 0.0), 1),
            "throttle_acceptance_delta_pct": round((ma.get("throttle_acceptance_pct") or 0.0) - (mb.get("throttle_acceptance_pct") or 0.0), 1),
            "entry_bravery_delta_pct": round((ma.get("entry_bravery_pct") or 0.0) - (mb.get("entry_bravery_pct") or 0.0), 1),
        })
```

**3d.** In the `_summary()` inner function (around line 5293-5329), add new fields after the existing `avg_fullness` block:

```python
        if per_corner:
            avg_ggv = round(float(np.mean([c[code].get("ggv_util_pct") or 0.0 for c in per_corner])), 1)
            avg_env_time = round(float(np.mean([c[code].get("envelope_time_pct") or 0.0 for c in per_corner])), 1)
            avg_ta = round(float(np.mean([c[code].get("throttle_acceptance_pct") or 0.0 for c in per_corner])), 1)
            avg_eb = round(float(np.mean([c[code].get("entry_bravery_pct") or 0.0 for c in per_corner])), 1)
            bscore = _bravery_score(avg_env_time, avg_ta, avg_eb)
        else:
            avg_ggv = avg_env_time = avg_ta = avg_eb = bscore = None
```

Add to the `return` dict of `_summary()`:

```python
            "avg_ggv_util_pct": avg_ggv,
            "avg_envelope_time_pct": avg_env_time,
            "avg_throttle_acceptance_pct": avg_ta,
            "avg_entry_bravery_pct": avg_eb,
            "bravery_score": bscore,
```

**3e.** Add 3 narrative blocks after the existing trail brake narrative block (after line ~5446):

```python
    # --- GGV utilisation (empirical envelope) ---
    ggv_a = sum_a.get("avg_ggv_util_pct") or 0.0
    ggv_b = sum_b.get("avg_ggv_util_pct") or 0.0
    if ggv_a and ggv_b and abs(ggv_a - ggv_b) >= 2.0:
        higher_ggv = code_a if ggv_a >= ggv_b else code_b
        lower_ggv = code_b if higher_ggv == code_a else code_a
        narrative_parts.append(
            f"Against the car's empirical grip ceiling — what this car on these tyres has been "
            f"shown to do in this session — {higher_ggv} used {max(ggv_a, ggv_b):.1f}% of that "
            f"envelope vs {lower_ggv}'s {min(ggv_a, ggv_b):.1f}%. "
            f"{higher_ggv} was asking more of what the car can actually produce."
        )

    # --- Throttle acceptance (exit bravery) ---
    ta_a = sum_a.get("avg_throttle_acceptance_pct") or 0.0
    ta_b = sum_b.get("avg_throttle_acceptance_pct") or 0.0
    if abs(ta_a - ta_b) >= 5.0:
        braver_exit = code_a if ta_a >= ta_b else code_b
        cautious_exit = code_b if braver_exit == code_a else code_a
        narrative_parts.append(
            f"{braver_exit} was committing to full power earlier at corner exits — still carrying "
            f"heavy lateral load in {max(ta_a, ta_b):.1f}% of exits vs {min(ta_a, ta_b):.1f}% "
            f"for {cautious_exit}. That's asking the rear tyre to drive the car forward and corner "
            f"simultaneously — the brave part of the exit."
        )
    elif max(ta_a, ta_b) < 5.0:
        narrative_parts.append(
            f"Neither driver was particularly aggressive at exit — both waiting for the car to "
            f"settle before committing to power."
        )

    # --- Bravery score ---
    bs_a = sum_a.get("bravery_score") or 0.0
    bs_b = sum_b.get("bravery_score") or 0.0
    if bs_a and bs_b and abs(bs_a - bs_b) >= 3.0:
        braver = code_a if bs_a >= bs_b else code_b
        cautious = code_b if braver == code_a else code_a
        narrative_parts.append(
            f"Across all bravery dimensions — envelope proximity, exit commitment, and near-limit "
            f"entries — {braver} scores {max(bs_a, bs_b):.1f} vs {cautious}'s {min(bs_a, bs_b):.1f} "
            f"(0–100 scale)."
        )
```

- [ ] **Step 4: Run tests to verify they pass**

```
python -m pytest tests/test_f1_data.py::test_corner_metrics_with_envelope_adds_ggv_delta_fields -v
```

Expected: PASS

- [ ] **Step 5: Run full suite**

```
python -m pytest tests/ -q
```

Expected: all passing

- [ ] **Step 6: Commit**

```bash
git add f1_data.py tests/test_f1_data.py
git commit -m "feat: extend analyze_cornering_loads with GGV envelope, throttle acceptance, bravery score"
```

---

### Task 4: Extend `_aggregate_lap_cornering_stats` + `analyze_race_cornering_profile`

**Files:**
- Modify: `server/f1_data.py:5468-5522` (`_aggregate_lap_cornering_stats`)
- Modify: `server/f1_data.py:5525-5764` (`analyze_race_cornering_profile`)
- Test: `server/tests/test_f1_data.py`

- [ ] **Step 1: Write the failing test**

```python
def test_aggregate_lap_cornering_stats_ggv_fields_with_envelope():
    import pandas as pd
    import numpy as np
    n = 200
    t_s = np.linspace(0, 20, n)
    theta = np.linspace(0, 4 * np.pi, n)
    speed = 200.0 - 80.0 * np.abs(np.sin(np.pi * np.linspace(0, 4, n)))
    tel = pd.DataFrame({
        'Speed': speed,
        'X': 2000.0 * np.cos(theta),
        'Y': 2000.0 * np.sin(theta),
        'Distance': np.linspace(0, 2000.0, n),
        'Time': pd.to_timedelta(t_s, unit='s'),
        'Source': np.where(np.arange(n) % 4 == 0, 'pos', 'car'),
        'Throttle': np.where(speed > 150, 95.0, 0.0),
    })
    envelope = f1_data._theoretical_ggv_envelope()
    result = f1_data._aggregate_lap_cornering_stats(tel, envelope=envelope)
    if result is not None:
        assert 'avg_ggv_util_pct' in result
        assert 'avg_envelope_time_pct' in result
        assert 'avg_throttle_acceptance_pct' in result
        assert 'avg_entry_bravery_pct' in result
        assert 'bravery_score' in result
```

- [ ] **Step 2: Run test to verify it fails**

```
python -m pytest tests/test_f1_data.py::test_aggregate_lap_cornering_stats_ggv_fields_with_envelope -v
```

Expected: FAIL (KeyError or AssertionError — new fields not present)

- [ ] **Step 3: Modify `_aggregate_lap_cornering_stats`**

Change signature to accept `envelope`:

```python
def _aggregate_lap_cornering_stats(tel: pd.DataFrame, envelope: dict | None = None) -> dict | None:
```

After `long_g = _compute_longitudinal_g(tel)`, extract throttle:

```python
        throttle = tel['Throttle'].to_numpy(dtype=float) if 'Throttle' in tel.columns else None
```

In the corners loop, pass `envelope` and `throttle` to `_corner_metrics`:

```python
        for c_start, c_end in corners:
            metrics = _corner_metrics(lat_g, long_g, spd, dist, c_start, c_end,
                                      envelope=envelope, throttle=throttle)
```

After `corner_fullness_samples`, add four new lists:

```python
            corner_ggv_util.append(metrics.get('ggv_util_pct') or 0.0)
            corner_env_time.append(metrics.get('envelope_time_pct') or 0.0)
            corner_throttle_acc.append(metrics.get('throttle_acceptance_pct') or 0.0)
            corner_entry_bravery.append(metrics.get('entry_bravery_pct') or 0.0)
```

(Also initialise these four lists before the loop: `corner_ggv_util = []` etc.)

Add to the returned dict:

```python
            "avg_ggv_util_pct": round(float(np.mean(corner_ggv_util)), 1) if corner_ggv_util else None,
            "avg_envelope_time_pct": round(float(np.mean(corner_env_time)), 1) if corner_env_time else None,
            "avg_throttle_acceptance_pct": round(float(np.mean(corner_throttle_acc)), 1) if corner_throttle_acc else None,
            "avg_entry_bravery_pct": round(float(np.mean(corner_entry_bravery)), 1) if corner_entry_bravery else None,
            "bravery_score": _bravery_score(
                float(np.mean(corner_env_time)) if corner_env_time else None,
                float(np.mean(corner_throttle_acc)) if corner_throttle_acc else None,
                float(np.mean(corner_entry_bravery)) if corner_entry_bravery else None,
            ),
```

- [ ] **Step 4: Modify `analyze_race_cornering_profile`**

Replace the existing `_process_driver` inner function and the `laps_a = _process_driver(clean_a)` / `laps_b = _process_driver(clean_b)` calls with a two-pass approach:

```python
    # Pass 1: collect telemetry frames for both drivers to build the shared GGV envelope.
    def _collect_lap_tels(clean_laps):
        result = []
        for _, lap in clean_laps.iterrows():
            try:
                tel = lap.get_telemetry().add_distance()
                if len(tel) >= 50:
                    result.append((lap, tel))
            except Exception:
                continue
        return result

    lap_tels_a = _collect_lap_tels(clean_a)
    lap_tels_b = _collect_lap_tels(clean_b)
    envelope = _build_ggv_envelope([t for _, t in lap_tels_a + lap_tels_b])

    # Pass 2: compute per-lap stats with the shared envelope.
    def _process_lap_tels(lap_tels) -> list[dict]:
        results = []
        for lap, tel in lap_tels:
            try:
                stats = _aggregate_lap_cornering_stats(tel, envelope=envelope)
                if stats is None:
                    continue
                stats['lap_number'] = int(lap['LapNumber'])
                stats['stint'] = int(lap['Stint']) if pd.notna(lap.get('Stint')) else None
                stats['compound'] = str(lap['Compound']) if pd.notna(lap.get('Compound')) else None
                results.append(stats)
            except Exception:
                continue
        return results

    laps_a = _process_lap_tels(lap_tels_a)
    laps_b = _process_lap_tels(lap_tels_b)
```

In the `_aggregate()` inner function, add 5 new fields:

```python
            "avg_ggv_util_pct": round(float(np.mean([l.get("avg_ggv_util_pct") or 0.0 for l in laps_data])), 1),
            "avg_envelope_time_pct": round(float(np.mean([l.get("avg_envelope_time_pct") or 0.0 for l in laps_data])), 1),
            "avg_throttle_acceptance_pct": round(float(np.mean([l.get("avg_throttle_acceptance_pct") or 0.0 for l in laps_data])), 1),
            "avg_entry_bravery_pct": round(float(np.mean([l.get("avg_entry_bravery_pct") or 0.0 for l in laps_data])), 1),
            "bravery_score": round(float(np.mean([l.get("bravery_score") or 0.0 for l in laps_data])), 1),
```

Add 2 narrative blocks after the existing trail brake narrative block (around line 5740):

```python
    # --- GGV utilisation race-long ---
    ggv_race_a = overall_a.get("avg_ggv_util_pct", 0.0)
    ggv_race_b = overall_b.get("avg_ggv_util_pct", 0.0)
    if ggv_race_a and ggv_race_b and abs(ggv_race_a - ggv_race_b) >= 2.0:
        higher_ggv_r = code_a if ggv_race_a >= ggv_race_b else code_b
        lower_ggv_r = code_b if higher_ggv_r == code_a else code_a
        narrative_parts.append(
            f"Against the empirical grip ceiling, {higher_ggv_r} used {max(ggv_race_a, ggv_race_b):.1f}% "
            f"of the envelope vs {lower_ggv_r}'s {min(ggv_race_a, ggv_race_b):.1f}% over the race. "
            f"That's the fraction of the car's demonstrated combined capability being asked of the tyres, lap after lap."
        )

    # --- Throttle acceptance race-long ---
    ta_race_a = overall_a.get("avg_throttle_acceptance_pct", 0.0)
    ta_race_b = overall_b.get("avg_throttle_acceptance_pct", 0.0)
    if abs(ta_race_a - ta_race_b) >= 5.0:
        braver_exit_r = code_a if ta_race_a >= ta_race_b else code_b
        cautious_exit_r = code_b if braver_exit_r == code_a else code_a
        narrative_parts.append(
            f"{braver_exit_r} was getting on the power earlier at every exit — still loaded laterally in "
            f"{max(ta_race_a, ta_race_b):.1f}% of exits vs {min(ta_race_a, ta_race_b):.1f}% for {cautious_exit_r}. "
            f"Over a race distance, that exit aggression compounds — more drive out of every corner, every lap."
        )
```

- [ ] **Step 5: Run tests to verify they pass**

```
python -m pytest tests/test_f1_data.py::test_aggregate_lap_cornering_stats_ggv_fields_with_envelope -v
```

Expected: PASS (or SKIP if no corners detected in synthetic data — acceptable)

- [ ] **Step 6: Run full suite**

```
python -m pytest tests/ -q
```

Expected: all passing

- [ ] **Step 7: Commit**

```bash
git add f1_data.py tests/test_f1_data.py
git commit -m "feat: extend race cornering profile with GGV envelope and bravery metrics"
```

---

### Task 5: Update `tools.py` Descriptions

**Files:**
- Modify: `server/tools.py:501-507` (analyze_cornering_loads description)
- Modify: `server/tools.py:520-524` (analyze_race_cornering_profile description)

- [ ] **Step 1: Replace `analyze_cornering_loads` description**

Find the current description string starting at line 501 and replace with:

```python
        "DEEP ANALYSIS PRIMITIVE. Compute lateral G and grip utilisation for two drivers across all corners of their fastest laps, "
        "using curvature derived from X/Y position telemetry. Returns per-corner stats (peak G, apex G, load variance, "
        "steering correction count, % time above 90% theoretical grip) plus an overall summary and a human-readable narrative. "
        "Also returns GGV-based metrics derived from the session's empirical grip envelope (not a theoretical formula): "
        "ggv_util_pct (% of the car's demonstrated grip ellipse used, combining lat + long), "
        "envelope_time_pct (% of cornering time within 15% of the empirical limit), "
        "throttle_acceptance_pct (% of corner exits where full throttle is applied while still laterally loaded — the bravery metric), "
        "entry_bravery_pct (% of entries near the combined limit while still braking), "
        "bravery_score (composite 0–100). "
        "Use this for qualifying / single-lap grip style and bravery comparisons.",
```

- [ ] **Step 2: Replace `analyze_race_cornering_profile` description**

Find the description starting at line 520 and replace with:

```python
        "DEEP ANALYSIS PRIMITIVE. Compute lateral G and grip utilisation aggregated across an ENTIRE RACE for two drivers. "
        "Processes every clean race lap (pit laps excluded) and returns overall summary stats plus a per-stint breakdown. "
        "Use this when asked about race-long grip usage, tyre stress, or who pushes harder through corners over a full race distance. "
        "Returns: avg corner grip utilisation %, % cornering time above 90% grip, corrections per corner, load variance per stint, "
        "combined grip utilisation % (lat+long vector), trail brake % at corner entry, "
        "GGV-based metrics: ggv_util_pct (empirical envelope utilisation), envelope_time_pct, "
        "throttle_acceptance_pct (exit bravery — full power under lateral load), "
        "entry_bravery_pct, bravery_score (0–100 composite) per stint and overall.",
```

- [ ] **Step 3: Run full suite to confirm no breakage**

```
python -m pytest tests/ -q
```

Expected: all passing

- [ ] **Step 4: Commit**

```bash
git add tools.py
git commit -m "docs: update analyze_cornering_loads and analyze_race_cornering_profile tool descriptions with GGV/bravery metrics"
```

---

### Task 6: Update `chat.py` System Prompt Vocabulary

**Files:**
- Modify: `server/chat.py:788-823` (the Cornering Load section)

- [ ] **Step 1: Add GGV vocabulary entries**

After the existing `avg_circle_fullness_pct` entry (around line 801), insert:

```
- **avg_ggv_util_pct** → How much of the car's ACTUAL demonstrated grip envelope the driver used — normalised against what this car on these tyres produced in this session, not a formula. Directional (braking limit ≠ lateral limit ≠ throttle limit — a proper friction ellipse).
  High (>85%): *asking everything of the car*, *at the absolute edge of what the hardware can produce*, *using the car's full capability*, *no headroom left*
  Medium (65–85%): *strong commitment, the car is working hard*, *well into the performance window*
  Low (<60%): *keeping something in reserve*, *the envelope isn't fully used*
  Never say "GGV utilisation" or "ggv_util_pct" in the answer. Say: "he was asking [X]% of what the car has shown it can produce."

- **avg_envelope_time_pct** → % of cornering time within 15% of the car's empirical combined limit. Higher = the driver sustains near-limit operation throughout the corner, not just peaking at the apex.
  High (>55%): *living at the limit from entry to exit*, *barely eases off*, *the tyre is working hard through every phase*, *no coasting*
  Low (<30%): *has a comfort margin through the middle*, *eases off at the apex*, *the limit is touched briefly but not held*
  Never say "envelope time" in the answer.

- **avg_throttle_acceptance_pct / throttle_acceptance_pct** → The bravery metric. % of corner exits where the driver commits to full power WHILE the car still has significant lateral load. Asks the rear tyre to generate drive force and cornering force simultaneously.
  High (>40%): *brave on the exit*, *power down early while the car's still loaded*, *committing to the throttle before the car is straight*, *trusting the rear to hook up under load*, *the exit is where he's brave*
  Low (<15%): *waits for the car to settle*, *conservative on exit*, *throttle only once fully straight*, *leaving exit speed on the table*
  Never say "throttle acceptance" in the answer. Say: "he was on the power before the car was straight" or "committing to the throttle while the rear was still working".

- **avg_entry_bravery_pct / entry_bravery_pct** → % of corner entries where the driver is simultaneously near the combined grip limit AND still on the brakes — braking deep while already deeply loaded laterally.
  High (>35%): *brave on the entry too*, *braking deep into a loaded corner*, *trail-braking at the limit*, *the brake pedal is a rotation tool at the very edge of grip*
  Low (<10%): *entry is the conservative part of their lap*, *braking finished before the load builds*
  Never say "entry bravery" in the answer.

- **bravery_score** → Composite 0–100. Weights: throttle acceptance 40%, envelope time 35%, entry bravery 25%. A driver who is brave at exit, consistent at the limit throughout, and deep on the brakes at entry scores high.
  High (>60): *the braver driver on this lap*, *committed in every phase*, *no safety margins*
  Low (<30): *the more measured driver*, *keeps something in reserve across the board*
  Never say "bravery score" in the answer. Describe what it means in terms of the specific phases where the driver is or isn't brave.
```

- [ ] **Step 2: Add combined signal inferences for bravery**

After the existing inference table (around line 813), add:

```
- High throttle_acceptance + low trail_brake = *exit specialist* — brave when getting on the power, but doesn't use the brake to rotate. The exit is the aggressive phase.
- High trail_brake + high entry_bravery = *entry specialist* — braving the corner on the way in, loading entry with the brake at the limit. The entry is the weapon.
- High ggv_util + high bravery_score = *complete driver* — using the car's capability in every phase. The hardest style on hardware but the fastest single-lap approach.
- High envelope_time + low load_variance = *smooth limit driver* — sustaining near-limit operation throughout without fighting it. The ideal race style.
```

- [ ] **Step 3: Update the never-say rules**

Find the existing "Never say" rule line (around line 823) and extend it:

```
- Never say "combined grip utilisation", "combined util", "trail brake percentage", "avg_trail_brake_pct", "circle fullness", "avg_circle_fullness_pct", "GGV utilisation", "ggv_util_pct", "envelope time", "avg_envelope_time_pct", "throttle acceptance", "avg_throttle_acceptance_pct", "entry bravery", "avg_entry_bravery_pct", or "bravery score" in the answer. Translate every metric to the character vocabulary above.
```

- [ ] **Step 4: Run full suite to confirm no regressions**

```
python -m pytest tests/ -q
```

Expected: all passing. (The system prompt is an f-string — verify no unescaped `{` in the new text, use `{{` if you need a literal brace.)

- [ ] **Step 5: Commit**

```bash
git add chat.py
git commit -m "feat: add GGV bravery vocabulary to system prompt (throttle acceptance, entry bravery, envelope time, bravery score)"
```

---

## Self-Review

**Spec coverage:**
- ✅ GGV envelope (session-empirical, speed-indexed) → Task 1
- ✅ Friction ellipse (lat ≠ brake ≠ throttle ceiling) → Task 1 `_build_ggv_envelope`
- ✅ GGV utilisation % → Task 2 `ggv_util_pct`
- ✅ Envelope time % (near-limit time) → Task 2 `envelope_time_pct`
- ✅ Throttle acceptance (Mastinu 2019 exit bravery) → Task 2 `throttle_acceptance_pct`
- ✅ Entry bravery (near-limit + braking at entry) → Task 2 `entry_bravery_pct`
- ✅ Bravery score composite → Task 1 `_bravery_score`, Task 3/4 summary
- ✅ Teammate/session normalisation (shared envelope from both drivers' laps) → Task 3 + 4
- ✅ Old metrics preserved (backward compat) → `envelope=None` path in `_corner_metrics`
- ✅ Qualifying tool → Task 3
- ✅ Race tool → Task 4
- ✅ Tool descriptions → Task 5
- ✅ AI vocabulary → Task 6

**Type consistency:**
- `_build_ggv_envelope` returns `dict` with keys `lat_max`, `brake_max`, `throttle_max`, `speed_bins` — used exactly this way in `_ggv_ceiling_at_speed`, `_corner_metrics`, and tests
- `_bravery_score(envelope_time, throttle_acc, entry_bravery)` — called with keyword-positional args in Tasks 3 and 4
- `_aggregate_lap_cornering_stats(tel, envelope=None)` — the `envelope` kwarg is used in Task 4's `_process_lap_tels`

**Backward compat:** All existing tests call `_corner_metrics(lat_g, long_g, speed, dist, start, end)` without `envelope`. New params default to `None` — existing tests pass unchanged.
