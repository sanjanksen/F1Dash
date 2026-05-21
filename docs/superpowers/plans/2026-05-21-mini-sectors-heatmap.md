# Mini-Sectors Heatmap (F22) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add 25-segment per-lap mini-sector analysis to F1Dash. Given two drivers and a lap, compute equal-distance segments, per-segment time deltas, and cumulative delta along distance — rendered as a colored track map (per-segment winner) plus a delta-vs-distance line chart. Localizes "where on the lap a driver gained/lost time" to ~200m resolution instead of the 3-sector coarse default.

**Architecture:** New `compute_mini_sectors(lap, n=25)` helper in `server/f1_data.py` that slices telemetry by cumulative distance. New `compare_mini_sectors(...)` builds the comparison. New primitive tool `compare_mini_sectors` registered in `tools.py`. Widget builder in `chat.py`. New React widget that reuses the existing `TrackMap.jsx` component as a base and overlays per-segment coloring. System prompt rule added so the LLM invokes the tool for "where on the lap" questions.

**Tech Stack:** Existing FastF1 telemetry (`lap.get_car_data().add_distance()`), existing track-map sampling infrastructure, React. No new dependencies.

---

## Background

The current `get_sector_comparison` returns the official 3 FIA sectors per lap. That's too coarse — sector 2 alone can be 30+ seconds long, and "Norris was 0.1s faster in S2" doesn't tell you whether he was faster through the high-speed sweeper or the chicane.

MultiViewer F1, the broadcast graphics, and every serious telemetry tool use **25 equal-distance mini-sectors per lap**. F22 brings F1Dash to parity.

The heavy lifting (telemetry fetch, track-map sampling, lap loading) already exists. This task is mostly:
1. A slicing function over telemetry by cumulative distance
2. A comparison wrapper
3. A widget that reuses TrackMap.jsx

DRS-mix warning is built in: if driver A had DRS open in segment k and driver B didn't, the segment's delta is contaminated by DRS state — flag this on the widget so the user knows not to attribute it to pace.

---

## File Structure

| File | Responsibility | Status |
|---|---|---|
| `server/f1_data.py` | Add `compute_mini_sectors(lap, n=25)` and `compare_mini_sectors(...)` | **Modify** |
| `server/tools.py` | Register `compare_mini_sectors` primitive tool | **Modify** |
| `server/chat.py` | `_make_mini_sector_heatmap_widget()` + agentic-loop dispatch + SYSTEM_PROMPT rule | **Modify** |
| `client/src/components/chat-widgets/MiniSectorHeatmapWidget.jsx` | Track-map heatmap + delta-by-distance chart | **Create** |
| `client/src/components/AnswerRenderer.jsx` | Add `mini_sector_heatmap` widget-type case | **Modify** |
| `server/tests/test_f1_data.py` | `TestMiniSectors` class | **Modify** |
| `server/tests/test_chat.py` | Widget builder unit test | **Modify** |
| `server/tests/test_tools.py` | Tool dispatch + arg validation | **Modify** |

---

## Task 1: `compute_mini_sectors` — slice a single lap

**Files:**
- Modify: `server/f1_data.py`
- Test: `server/tests/test_f1_data.py`

- [ ] **Step 1: Write the failing test**

Append to `server/tests/test_f1_data.py`:

```python
class TestMiniSectors:
    def test_compute_mini_sectors_returns_n_segments(self):
        """25 segments whose end_m - start_m sums within 1 m of total lap distance."""
        from f1_data import compute_mini_sectors
        import pandas as pd

        # Synthesise a lap with 500 evenly-spaced samples covering 5000 m of distance
        n_samples = 500
        total_dist = 5000.0
        distance = pd.Series([i * total_dist / (n_samples - 1) for i in range(n_samples)])
        time_s = pd.Series([i * 90.0 / (n_samples - 1) for i in range(n_samples)])  # 90s lap
        speed = pd.Series([200.0] * n_samples)
        throttle = pd.Series([100.0] * n_samples)
        drs = pd.Series([0] * n_samples)

        # Lap stub: just needs .get_car_data().add_distance() to return a DataFrame
        class _FakeTelemetry:
            def __init__(self, df): self._df = df
            def add_distance(self): return self._df

        class _FakeLap:
            def get_car_data(self_):
                return _FakeTelemetry(pd.DataFrame({
                    "Distance": distance, "Time": time_s, "Speed": speed,
                    "Throttle": throttle, "DRS": drs,
                }))

        segments = compute_mini_sectors(_FakeLap(), n=25)
        assert len(segments) == 25
        # End_m of last segment within 1 m of total_dist
        assert abs(segments[-1]["end_m"] - total_dist) < 1.0
        # Start_m of segment 0 is 0
        assert segments[0]["start_m"] == 0.0
        # Sum of segment spans ≈ total
        spans = sum(s["end_m"] - s["start_m"] for s in segments)
        assert abs(spans - total_dist) < 1.0

    def test_compute_mini_sectors_times_sum_to_lap_time(self):
        """Segment time_s values sum within 5 ms of the lap's total time."""
        from f1_data import compute_mini_sectors
        import pandas as pd

        n_samples = 500
        total_dist = 5000.0
        total_time = 90.0
        distance = pd.Series([i * total_dist / (n_samples - 1) for i in range(n_samples)])
        time_s = pd.Series([i * total_time / (n_samples - 1) for i in range(n_samples)])
        speed = pd.Series([200.0] * n_samples)
        throttle = pd.Series([100.0] * n_samples)
        drs = pd.Series([0] * n_samples)

        class _FakeTelemetry:
            def __init__(self, df): self._df = df
            def add_distance(self): return self._df

        class _FakeLap:
            def get_car_data(self_):
                return _FakeTelemetry(pd.DataFrame({
                    "Distance": distance, "Time": time_s, "Speed": speed,
                    "Throttle": throttle, "DRS": drs,
                }))

        segments = compute_mini_sectors(_FakeLap(), n=25)
        total = sum(s["time_s"] for s in segments)
        assert abs(total - total_time) < 0.005

    def test_compute_mini_sectors_returns_speed_aggregates(self):
        """Each segment has avg_speed_kmh, min_speed_kmh, drs_active_pct."""
        from f1_data import compute_mini_sectors
        import pandas as pd

        n_samples = 250
        # Varying speeds so min < avg
        speeds = [180.0 + 20.0 * ((i % 50) / 50.0) for i in range(n_samples)]
        # DRS open on the first half, closed second half
        drs_vals = [10 if i < n_samples // 2 else 0 for i in range(n_samples)]
        df = pd.DataFrame({
            "Distance": [i * 20.0 for i in range(n_samples)],
            "Time": [i * 0.4 for i in range(n_samples)],
            "Speed": speeds,
            "Throttle": [100.0] * n_samples,
            "DRS": drs_vals,
        })

        class _FakeTelemetry:
            def __init__(self, df): self._df = df
            def add_distance(self): return self._df

        class _FakeLap:
            def get_car_data(self_):
                return _FakeTelemetry(df)

        segments = compute_mini_sectors(_FakeLap(), n=25)
        for s in segments:
            assert "avg_speed_kmh" in s
            assert "min_speed_kmh" in s
            assert "drs_active_pct" in s
            assert 0.0 <= s["drs_active_pct"] <= 100.0
            assert s["min_speed_kmh"] <= s["avg_speed_kmh"]
        # First few segments have DRS, last few don't
        assert segments[0]["drs_active_pct"] > 50.0
        assert segments[-1]["drs_active_pct"] < 50.0

    def test_compute_mini_sectors_handles_empty_telemetry(self):
        """Empty or too-short telemetry returns []."""
        from f1_data import compute_mini_sectors
        import pandas as pd

        class _FakeTelemetry:
            def __init__(self): self._df = pd.DataFrame({"Distance": [], "Time": [], "Speed": [], "Throttle": [], "DRS": []})
            def add_distance(self): return self._df

        class _FakeLap:
            def get_car_data(self_):
                return _FakeTelemetry()

        assert compute_mini_sectors(_FakeLap(), n=25) == []
```

- [ ] **Step 2: Run to verify red**

```
cd server; python -m pytest tests/test_f1_data.py::TestMiniSectors -v
```

Expected: 4 tests FAIL with `ImportError: cannot import name 'compute_mini_sectors'`.

- [ ] **Step 3: Implement `compute_mini_sectors` in `server/f1_data.py`**

Add the function near the existing `get_sector_comparison` helpers (around line 2325, but at the appropriate module-level position — read the surrounding code for placement):

```python
import numpy as np
import pandas as pd


def compute_mini_sectors(lap, n: int = 25) -> list[dict]:
    """Split a lap into n equal cumulative-distance segments.

    Returns a list of n dicts, each with:
        - index: 0-based segment number
        - start_m, end_m: distance bounds in meters
        - time_s: seconds spent in this segment
        - avg_speed_kmh, min_speed_kmh
        - drs_active_pct: % of samples in segment where DRS was active
                           (values 10/12/14 in FastF1's DRS column)

    Returns [] if telemetry is missing, empty, or has < n*2 samples.
    """
    try:
        tel = lap.get_car_data().add_distance()
    except Exception:
        return []

    if tel is None or len(tel) < n * 2:
        return []

    required = ("Distance", "Time", "Speed")
    if not all(col in tel.columns for col in required):
        return []

    distance = tel["Distance"].to_numpy(dtype=float)
    total_distance = float(distance[-1])
    if total_distance <= 0.0 or not np.isfinite(total_distance):
        return []

    # Time column may be timedelta — convert to seconds
    time_col = tel["Time"]
    if pd.api.types.is_timedelta64_dtype(time_col):
        time_s = time_col.dt.total_seconds().to_numpy(dtype=float)
    else:
        time_s = time_col.to_numpy(dtype=float)

    speed = tel["Speed"].to_numpy(dtype=float)
    drs = tel["DRS"].to_numpy() if "DRS" in tel.columns else None

    boundaries = np.linspace(0.0, total_distance, n + 1)
    segments: list[dict] = []

    for i in range(n):
        start_m = float(boundaries[i])
        end_m = float(boundaries[i + 1])
        # Inclusive on the lower bound, exclusive on the upper, except for the
        # last segment which must include the final sample.
        if i == n - 1:
            mask = (distance >= start_m) & (distance <= end_m)
        else:
            mask = (distance >= start_m) & (distance < end_m)

        if not mask.any():
            segments.append({
                "index": i,
                "start_m": round(start_m, 2),
                "end_m": round(end_m, 2),
                "time_s": 0.0,
                "avg_speed_kmh": 0.0,
                "min_speed_kmh": 0.0,
                "drs_active_pct": 0.0,
            })
            continue

        seg_times = time_s[mask]
        seg_speeds = speed[mask]
        seg_time = float(seg_times[-1] - seg_times[0]) if len(seg_times) >= 2 else 0.0

        if drs is not None:
            seg_drs = drs[mask]
            try:
                drs_active = float(np.mean([int(v) in (10, 12, 14) for v in seg_drs]) * 100.0)
            except Exception:
                drs_active = 0.0
        else:
            drs_active = 0.0

        segments.append({
            "index": i,
            "start_m": round(start_m, 2),
            "end_m": round(end_m, 2),
            "time_s": round(seg_time, 4),
            "avg_speed_kmh": round(float(np.mean(seg_speeds)), 2),
            "min_speed_kmh": round(float(np.min(seg_speeds)), 2),
            "drs_active_pct": round(drs_active, 1),
        })

    return segments
```

- [ ] **Step 4: Run to verify green**

```
cd server; python -m pytest tests/test_f1_data.py::TestMiniSectors -v
```

Expected: 4 tests PASS.

Full suite:

```
cd server; python -m pytest tests/ -q 2>&1 | tail -3
```

Expected: 478 + 4 = 482 passing.

- [ ] **Step 5: Commit**

```
git add server/f1_data.py server/tests/test_f1_data.py
git commit -m "feat(telemetry): compute_mini_sectors slices a lap into 25 equal-distance segments

Each segment dict carries start_m / end_m / time_s / avg_speed_kmh /
min_speed_kmh / drs_active_pct. Equal cumulative-distance slicing via
np.linspace boundaries; segment time = last_time - first_time of samples
in the band; DRS active when value is in {10, 12, 14} per FastF1's
convention.

Returns [] on missing/empty/short telemetry — caller treats as 'cannot
mini-sector this lap'.

Plan: docs/superpowers/plans/2026-05-21-mini-sectors-heatmap.md Task 1"
```

---

## Task 2: `compare_mini_sectors` — diff two drivers' laps

**Files:**
- Modify: `server/f1_data.py`
- Test: `server/tests/test_f1_data.py`

- [ ] **Step 1: Append failing tests**

```python
    def test_compare_mini_sectors_returns_per_segment_delta(self):
        """Each segment has delta_s (a - b) and a winner."""
        from f1_data import compute_mini_sectors, _build_mini_sector_comparison

        a_segments = [
            {"index": i, "start_m": i * 200, "end_m": (i + 1) * 200,
             "time_s": 4.0, "avg_speed_kmh": 200.0, "min_speed_kmh": 180.0,
             "drs_active_pct": 0.0}
            for i in range(25)
        ]
        b_segments = [
            {"index": i, "start_m": i * 200, "end_m": (i + 1) * 200,
             "time_s": 4.05 if i < 12 else 3.95,  # A faster in first half, B faster in second
             "avg_speed_kmh": 198.0, "min_speed_kmh": 178.0, "drs_active_pct": 0.0}
            for i in range(25)
        ]

        out = _build_mini_sector_comparison("VER", "NOR", a_segments, b_segments)
        assert len(out["segments"]) == 25
        # Segment 0: a was 4.0, b was 4.05; delta_a-b = -0.05, A wins
        assert out["segments"][0]["delta_s"] == -0.05
        assert out["segments"][0]["winner"] == "A"
        # Segment 12: a was 4.0, b was 3.95; delta = +0.05, B wins
        assert out["segments"][12]["winner"] == "B"

    def test_compare_mini_sectors_cumulative_delta_grows(self):
        """Cumulative delta = sum of per-segment deltas along distance."""
        from f1_data import _build_mini_sector_comparison

        a_segments = [{"index": i, "start_m": i * 200, "end_m": (i + 1) * 200,
                       "time_s": 4.0, "avg_speed_kmh": 200.0, "min_speed_kmh": 180.0,
                       "drs_active_pct": 0.0} for i in range(5)]
        b_segments = [{"index": i, "start_m": i * 200, "end_m": (i + 1) * 200,
                       "time_s": 4.1, "avg_speed_kmh": 200.0, "min_speed_kmh": 180.0,
                       "drs_active_pct": 0.0} for i in range(5)]

        out = _build_mini_sector_comparison("VER", "NOR", a_segments, b_segments)
        # 5 segments, each delta = -0.1 (A faster); cumulative at end = -0.5
        cum = out["cumulative_delta"]
        assert abs(cum[-1][1] - (-0.5)) < 1e-6
        # Cumulative is monotonically decreasing here
        for i in range(1, len(cum)):
            assert cum[i][1] <= cum[i - 1][1] + 1e-9

    def test_compare_mini_sectors_flags_drs_mix(self):
        """When A had DRS open in a segment and B did not (or vice versa),
        drs_mix_warning is True."""
        from f1_data import _build_mini_sector_comparison

        a_segments = [{"index": 0, "start_m": 0, "end_m": 200, "time_s": 4.0,
                       "avg_speed_kmh": 200.0, "min_speed_kmh": 180.0,
                       "drs_active_pct": 80.0}]  # A had DRS
        b_segments = [{"index": 0, "start_m": 0, "end_m": 200, "time_s": 4.05,
                       "avg_speed_kmh": 200.0, "min_speed_kmh": 180.0,
                       "drs_active_pct": 0.0}]  # B did not

        out = _build_mini_sector_comparison("VER", "NOR", a_segments, b_segments)
        assert out["drs_mix_warning"] is True

    def test_compare_mini_sectors_no_drs_mix_when_both_open_or_closed(self):
        from f1_data import _build_mini_sector_comparison

        # Both have DRS in segment 0, neither in segment 1
        a_segments = [
            {"index": 0, "start_m": 0, "end_m": 200, "time_s": 4.0,
             "avg_speed_kmh": 200.0, "min_speed_kmh": 180.0, "drs_active_pct": 90.0},
            {"index": 1, "start_m": 200, "end_m": 400, "time_s": 4.0,
             "avg_speed_kmh": 200.0, "min_speed_kmh": 180.0, "drs_active_pct": 0.0},
        ]
        b_segments = [
            {"index": 0, "start_m": 0, "end_m": 200, "time_s": 4.0,
             "avg_speed_kmh": 200.0, "min_speed_kmh": 180.0, "drs_active_pct": 85.0},
            {"index": 1, "start_m": 200, "end_m": 400, "time_s": 4.0,
             "avg_speed_kmh": 200.0, "min_speed_kmh": 180.0, "drs_active_pct": 0.0},
        ]

        out = _build_mini_sector_comparison("VER", "NOR", a_segments, b_segments)
        assert out["drs_mix_warning"] is False

    def test_compare_mini_sectors_assigns_tie_for_tiny_deltas(self):
        """Per-segment winner is 'tie' when |delta_s| < 0.005."""
        from f1_data import _build_mini_sector_comparison

        a_segments = [{"index": 0, "start_m": 0, "end_m": 200, "time_s": 4.000,
                       "avg_speed_kmh": 200.0, "min_speed_kmh": 180.0,
                       "drs_active_pct": 0.0}]
        b_segments = [{"index": 0, "start_m": 0, "end_m": 200, "time_s": 4.003,
                       "avg_speed_kmh": 200.0, "min_speed_kmh": 180.0,
                       "drs_active_pct": 0.0}]

        out = _build_mini_sector_comparison("VER", "NOR", a_segments, b_segments)
        assert out["segments"][0]["winner"] == "tie"
```

- [ ] **Step 2: Run to verify red**

```
cd server; python -m pytest tests/test_f1_data.py::TestMiniSectors -v 2>&1 | tail -20
```

Expected: 5 new tests fail with ImportError on `_build_mini_sector_comparison`.

- [ ] **Step 3: Implement the comparison builder + a `compare_mini_sectors` entry point**

Append to `server/f1_data.py` near `compute_mini_sectors`:

```python
_DRS_ACTIVE_THRESHOLD_PCT = 30.0  # Segment counts as "DRS open" if >30% of samples had DRS active.
_MINI_SECTOR_TIE_THRESHOLD_S = 0.005  # Per-segment delta below this is a tie.


def _build_mini_sector_comparison(
    driver_a: str,
    driver_b: str,
    a_segments: list[dict],
    b_segments: list[dict],
) -> dict:
    """Build the comparison dict from two equal-length segment lists.
    
    Pure function — no telemetry I/O. Easy to unit test.
    """
    n = min(len(a_segments), len(b_segments))
    out_segments: list[dict] = []
    cumulative: list[tuple[float, float]] = [(0.0, 0.0)]
    cum = 0.0
    drs_mix = False

    for i in range(n):
        a = a_segments[i]
        b = b_segments[i]
        delta = round(a["time_s"] - b["time_s"], 4)
        if abs(delta) < _MINI_SECTOR_TIE_THRESHOLD_S:
            winner = "tie"
        elif delta < 0:
            winner = "A"
        else:
            winner = "B"

        a_drs = a.get("drs_active_pct", 0.0) >= _DRS_ACTIVE_THRESHOLD_PCT
        b_drs = b.get("drs_active_pct", 0.0) >= _DRS_ACTIVE_THRESHOLD_PCT
        if a_drs != b_drs:
            drs_mix = True

        cum = round(cum + delta, 4)
        cumulative.append((a["end_m"], cum))

        out_segments.append({
            "index": i,
            "start_m": a["start_m"],
            "end_m": a["end_m"],
            "delta_s": delta,
            "winner": winner,
            "drs_a_active": a_drs,
            "drs_b_active": b_drs,
        })

    return {
        "driver_a": driver_a,
        "driver_b": driver_b,
        "segments": out_segments,
        "cumulative_delta": cumulative,
        "total_delta_s": round(cum, 4),
        "segments_won_a": sum(1 for s in out_segments if s["winner"] == "A"),
        "segments_won_b": sum(1 for s in out_segments if s["winner"] == "B"),
        "segments_tied": sum(1 for s in out_segments if s["winner"] == "tie"),
        "drs_mix_warning": drs_mix,
    }


def compare_mini_sectors(
    driver_a: str,
    driver_b: str,
    lap_number: int,
    round_number: int,
    session_type: str = "Q",
    n: int = 25,
) -> dict:
    """Compute per-driver mini-sectors and build the comparison.
    
    Returns:
        {
            "available": True,
            "driver_a": str, "driver_b": str,
            "lap_number": int, "round_number": int, "session_type": str,
            "n_segments": int,
            "weather_state": "dry" | "wet" | "unknown",
            ... fields from _build_mini_sector_comparison ...
        }
        or {"available": False, "reason": ...} on failure.
    """
    try:
        session = _load_session(round_number, session_type)
    except FastF1Error:
        return _unavailable_payload(round_number, session_type)

    try:
        lap_a = session.laps.pick_drivers(driver_a).pick_laps(lap_number)
        lap_b = session.laps.pick_drivers(driver_b).pick_laps(lap_number)
    except Exception as e:
        logger.warning("compare_mini_sectors lap pick failed: %s", type(e).__name__)
        return {"available": False, "reason": "lap_not_found"}

    if lap_a is None or lap_b is None or len(lap_a) == 0 or len(lap_b) == 0:
        return {"available": False, "reason": "lap_not_found"}

    # pick_laps returns a Laps frame; take the first row
    lap_a_row = lap_a.iloc[0]
    lap_b_row = lap_b.iloc[0]

    a_segments = compute_mini_sectors(lap_a_row, n=n)
    b_segments = compute_mini_sectors(lap_b_row, n=n)

    if not a_segments or not b_segments:
        return {"available": False, "reason": "telemetry_empty"}

    # Weather state from session.weather_data — best-effort
    weather_state = "unknown"
    try:
        if hasattr(session, "weather_data") and session.weather_data is not None:
            rainfall = session.weather_data.get("Rainfall")
            if rainfall is not None:
                weather_state = "wet" if bool(rainfall.any()) else "dry"
    except Exception:
        pass

    comparison = _build_mini_sector_comparison(driver_a, driver_b, a_segments, b_segments)
    return {
        "available": True,
        "lap_number": lap_number,
        "round_number": round_number,
        "session_type": session_type,
        "n_segments": n,
        "weather_state": weather_state,
        **comparison,
    }
```

- [ ] **Step 4: Run tests**

```
cd server; python -m pytest tests/test_f1_data.py::TestMiniSectors -v 2>&1 | tail -15
```

Expected: 9 mini-sector tests PASS.

```
cd server; python -m pytest tests/ -q 2>&1 | tail -3
```

Expected: 478 + 9 = 487 passing.

- [ ] **Step 5: Commit**

```
git add server/f1_data.py server/tests/test_f1_data.py
git commit -m "feat(telemetry): compare_mini_sectors with per-segment delta + DRS-mix warning

_build_mini_sector_comparison is the pure function (easy unit tests):
takes two equal-length segment lists, returns per-segment delta_s (a-b)
with winner (A / B / tie below 0.005s threshold), cumulative delta
along distance, segment-win counts, and a drs_mix_warning that fires
when one driver had DRS open and the other didn't.

compare_mini_sectors is the top-level entry: loads the session via
_load_session (FastF1Error-wrapped), picks lap_number for each driver,
runs compute_mini_sectors, and packages the result with weather_state
and round metadata.

Plan: docs/superpowers/plans/2026-05-21-mini-sectors-heatmap.md Task 2"
```

---

## Task 3: Register the `compare_mini_sectors` tool

**Files:**
- Modify: `server/tools.py`
- Test: `server/tests/test_tools.py`

- [ ] **Step 1: Write failing tests**

Append to `server/tests/test_tools.py`:

```python
def test_execute_tool_compare_mini_sectors_validates_args():
    """Missing required args raises ValueError."""
    from tools import execute_tool
    import pytest

    with pytest.raises(ValueError) as exc:
        execute_tool("compare_mini_sectors", {})
    msg = str(exc.value)
    assert "driver_a" in msg or "missing" in msg.lower()


def test_execute_tool_compare_mini_sectors_dispatches(monkeypatch):
    """execute_tool dispatches to f1_data.compare_mini_sectors with the right args."""
    from tools import execute_tool
    import f1_data

    captured = {}
    def _fake_compare(driver_a, driver_b, lap_number, round_number, session_type="Q", n=25):
        captured["args"] = (driver_a, driver_b, lap_number, round_number, session_type, n)
        return {"available": True, "segments": []}

    monkeypatch.setattr(f1_data, "compare_mini_sectors", _fake_compare)
    out = execute_tool("compare_mini_sectors", {
        "driver_a": "VER", "driver_b": "NOR",
        "lap_number": 21, "round_number": 11, "session_type": "Q",
    })
    assert out.get("available") is True
    assert captured["args"][0] == "VER"
    assert captured["args"][1] == "NOR"
    assert captured["args"][2] == 21
    assert captured["args"][3] == 11
```

- [ ] **Step 2: Run to verify red**

```
cd server; python -m pytest tests/test_tools.py -k "mini_sectors" -v
```

Expected: tests fail because the tool isn't registered.

- [ ] **Step 3: Register the tool definition in both Anthropic + OpenAI definitions**

In `server/tools.py`, find `TOOL_DEFINITIONS` (or `PRIMITIVE_TOOL_DEFINITIONS`). Add this entry alongside existing primitives:

```python
{
    "name": "compare_mini_sectors",
    "description": (
        "Compare two drivers across 25 equal-distance mini-sectors of a single lap. "
        "Returns per-segment time delta (driver_a - driver_b), cumulative delta along "
        "distance, segment-win counts, and a DRS-mix warning if one driver had DRS "
        "open in a segment and the other didn't. Use for 'where on the lap was X "
        "faster than Y' questions — mini-sectors localize gains to ~200m resolution "
        "vs the 3-sector coarse default. Prefer over get_sector_comparison when the "
        "user wants granular location-of-gain analysis."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "driver_a": {"type": "string", "description": "3-letter code"},
            "driver_b": {"type": "string"},
            "lap_number": {"type": "integer"},
            "round_number": {"type": "integer"},
            "session_type": {
                "type": "string",
                "description": "FastF1 session code: Q, R, FP1/2/3, SQ, S. Default Q.",
            },
            "n": {
                "type": "integer",
                "description": "Number of mini-sectors. Default 25.",
            },
        },
        "required": ["driver_a", "driver_b", "lap_number", "round_number"],
    },
},
```

Mirror the same entry into `OPENAI_TOOL_DEFINITIONS` if the file has a separate dict for it.

In the `execute_tool()` dispatcher, add a branch:

```python
if name == "compare_mini_sectors":
    _require_args(args, ["driver_a", "driver_b", "lap_number", "round_number"], name)
    return f1_data.compare_mini_sectors(
        driver_a=args["driver_a"],
        driver_b=args["driver_b"],
        lap_number=args["lap_number"],
        round_number=args["round_number"],
        session_type=args.get("session_type", "Q"),
        n=args.get("n", 25),
    )
```

- [ ] **Step 4: Run tests**

```
cd server; python -m pytest tests/test_tools.py -k "mini_sectors" -v
```

Expected: 2 new tests PASS.

```
cd server; python -m pytest tests/ -q 2>&1 | tail -3
```

Expected: 487 + 2 = 489 passing.

- [ ] **Step 5: Commit**

```
git add server/tools.py server/tests/test_tools.py
git commit -m "feat(tools): register compare_mini_sectors primitive

Visible to both Anthropic and OpenAI tool selection. Description nudges
the LLM to prefer mini-sectors over the coarse get_sector_comparison for
'where on the lap' questions.

_require_args validates the 4 required args (driver_a, driver_b,
lap_number, round_number); session_type and n are optional with sensible
defaults.

Plan: docs/superpowers/plans/2026-05-21-mini-sectors-heatmap.md Task 3"
```

---

## Task 4: Widget builder + system prompt rule

**Files:**
- Modify: `server/chat.py`
- Test: `server/tests/test_chat.py`

- [ ] **Step 1: Write failing test**

Append to `server/tests/test_chat.py`:

```python
def test_make_mini_sector_heatmap_widget_maps_all_fields():
    import chat
    result = {
        "available": True,
        "driver_a": "VER",
        "driver_b": "NOR",
        "lap_number": 21,
        "round_number": 11,
        "session_type": "Q",
        "n_segments": 25,
        "weather_state": "dry",
        "segments": [
            {"index": 0, "start_m": 0, "end_m": 200, "delta_s": -0.023,
             "winner": "A", "drs_a_active": False, "drs_b_active": False},
        ],
        "cumulative_delta": [(0.0, 0.0), (200.0, -0.023)],
        "total_delta_s": -0.213,
        "segments_won_a": 15,
        "segments_won_b": 10,
        "segments_tied": 0,
        "drs_mix_warning": False,
    }
    widget = chat._make_mini_sector_heatmap_widget(result)
    assert widget["type"] == "mini_sector_heatmap"
    assert widget["driver_a"] == "VER"
    assert widget["driver_b"] == "NOR"
    assert widget["lap_number"] == 21
    assert widget["total_delta_s"] == -0.213
    assert widget["drs_mix_warning"] is False
    assert len(widget["segments"]) == 1
    assert widget["cumulative_delta"] == [(0.0, 0.0), (200.0, -0.023)]


def test_make_mini_sector_heatmap_widget_returns_unavailable_shape():
    """When the tool returns available: False, the widget builder passes
    that through with type=mini_sector_heatmap so the renderer can show
    a friendly message."""
    import chat
    widget = chat._make_mini_sector_heatmap_widget({"available": False, "reason": "lap_not_found"})
    assert widget["type"] == "mini_sector_heatmap"
    assert widget.get("available") is False


def test_system_prompt_mentions_compare_mini_sectors():
    import chat
    assert "compare_mini_sectors" in chat.SYSTEM_PROMPT
```

- [ ] **Step 2: Run to verify red**

```
cd server; python -m pytest tests/test_chat.py -k "mini_sector" -v
```

Expected: tests fail.

- [ ] **Step 3: Add the widget builder + system-prompt rule**

In `server/chat.py`, find where other `_make_*_widget` functions live and add:

```python
def _make_mini_sector_heatmap_widget(result: dict) -> dict:
    """Map compare_mini_sectors output to the mini_sector_heatmap widget shape."""
    if not result.get("available", True):
        return {
            "type": "mini_sector_heatmap",
            "available": False,
            "reason": result.get("reason"),
        }
    return {
        "type": "mini_sector_heatmap",
        "available": True,
        "driver_a": result.get("driver_a"),
        "driver_b": result.get("driver_b"),
        "lap_number": result.get("lap_number"),
        "round_number": result.get("round_number"),
        "session_type": result.get("session_type"),
        "n_segments": result.get("n_segments"),
        "weather_state": result.get("weather_state"),
        "segments": result.get("segments") or [],
        "cumulative_delta": result.get("cumulative_delta") or [],
        "total_delta_s": result.get("total_delta_s"),
        "segments_won_a": result.get("segments_won_a"),
        "segments_won_b": result.get("segments_won_b"),
        "segments_tied": result.get("segments_tied"),
        "drs_mix_warning": result.get("drs_mix_warning", False),
    }
```

In the agentic-loop widget builder dispatch (grep for `_make_qualifying_battle_widget` to find the dispatch table), add:

```python
if tool_name == "compare_mini_sectors":
    return _make_mini_sector_heatmap_widget(result)
```

In `SYSTEM_PROMPT`, add this bullet to the tool-selection guidance block (find the cluster of bullets about when to invoke specific tools):

> *"For 'where on the lap' or 'which mini-sector' or 'localize the time gain' questions between two drivers, invoke `compare_mini_sectors` — it returns 25-segment time deltas at ~200 m resolution. Prefer over `get_sector_comparison` (which only has the 3 FIA sectors) when the user wants granular spatial localization of pace differences. If the tool returns `drs_mix_warning: true`, note that the gap in those segments is contaminated by DRS state, not just pace."*

- [ ] **Step 4: Run tests**

```
cd server; python -m pytest tests/test_chat.py -k "mini_sector or system_prompt" -v
cd server; python -m pytest tests/ -q 2>&1 | tail -3
```

Expected: 489 + 3 = 492 passing.

- [ ] **Step 5: Commit**

```
git add server/chat.py server/tests/test_chat.py
git commit -m "feat(chat): mini-sector heatmap widget builder + system prompt rule

_make_mini_sector_heatmap_widget packages the compare_mini_sectors output
for the React widget. Carries available=False through with the reason so
the frontend can show a friendly message instead of a broken chart.

SYSTEM_PROMPT bullet tells the LLM to prefer compare_mini_sectors over
get_sector_comparison for 'where on the lap' questions and to surface
drs_mix_warning when set.

Plan: docs/superpowers/plans/2026-05-21-mini-sectors-heatmap.md Task 4"
```

---

## Task 5: React widget — `MiniSectorHeatmapWidget.jsx`

**Files:**
- Create: `client/src/components/chat-widgets/MiniSectorHeatmapWidget.jsx`
- Modify: `client/src/components/AnswerRenderer.jsx`

- [ ] **Step 1: Inspect existing TrackMap component**

```bash
cat client/src/components/chat-widgets/TrackMap.jsx
```

The new widget will reuse the `points`-based track-map sampling. Note the prop shape (likely `points: [{x, y, distance_m}]`).

- [ ] **Step 2: Create the widget file**

Create `client/src/components/chat-widgets/MiniSectorHeatmapWidget.jsx`:

```jsx
import React from 'react'

const COLOR_A = 'hsl(220 80% 55%)'
const COLOR_B = 'hsl(28 90% 55%)'
const COLOR_TIE = 'hsl(0 0% 60%)'

const CHART_W = 720
const CHART_H = 140
const PADDING = 24

function segmentColor(winner) {
  if (winner === 'A') return COLOR_A
  if (winner === 'B') return COLOR_B
  return COLOR_TIE
}

function CumulativeDeltaChart({ data, totalDelta }) {
  if (!data || data.length < 2) return null
  const maxDist = data[data.length - 1][0] || 1
  const ys = data.map(([, y]) => y)
  const minY = Math.min(...ys, 0)
  const maxY = Math.max(...ys, 0)
  const yRange = Math.max(maxY - minY, 0.01)

  const x = (m) => PADDING + (m / maxDist) * (CHART_W - PADDING * 2)
  const y = (s) => PADDING + ((maxY - s) / yRange) * (CHART_H - PADDING * 2)

  const path = data.map(([m, s], i) => `${i === 0 ? 'M' : 'L'} ${x(m).toFixed(1)} ${y(s).toFixed(1)}`).join(' ')

  return (
    <svg viewBox={`0 0 ${CHART_W} ${CHART_H}`} style={{ width: '100%', height: 140 }}>
      {/* zero line */}
      <line x1={PADDING} x2={CHART_W - PADDING} y1={y(0)} y2={y(0)}
            stroke="hsl(0 0% 70%)" strokeDasharray="3 4" />
      <path d={path} fill="none" stroke="hsl(220 60% 45%)" strokeWidth={2} />
      <text x={CHART_W - PADDING} y={20} textAnchor="end" fontSize={11} fill="hsl(0 0% 30%)">
        Cumulative Δ (s)
      </text>
      {totalDelta != null && (
        <text x={CHART_W - PADDING} y={CHART_H - 8} textAnchor="end" fontSize={11} fill="hsl(0 0% 30%)">
          end Δ: {totalDelta.toFixed(3)}s
        </text>
      )}
    </svg>
  )
}

function MiniSectorBar({ segments, driverA, driverB }) {
  if (!segments || segments.length === 0) return null
  return (
    <div style={{ display: 'flex', width: '100%', height: 18, marginTop: 8, borderRadius: 4, overflow: 'hidden' }}>
      {segments.map((seg) => (
        <div
          key={seg.index}
          title={`Seg ${seg.index + 1}: ${seg.start_m.toFixed(0)}-${seg.end_m.toFixed(0)} m, Δ ${seg.delta_s.toFixed(3)}s (${seg.winner === 'A' ? driverA : seg.winner === 'B' ? driverB : 'tie'})`}
          style={{
            flex: 1,
            background: segmentColor(seg.winner),
            borderRight: '1px solid hsl(0 0% 100% / 0.4)',
          }}
        />
      ))}
    </div>
  )
}

export default function MiniSectorHeatmapWidget({ widget }) {
  if (!widget) return null
  if (widget.available === false) {
    return (
      <div style={{ padding: 12, color: 'hsl(0 0% 40%)' }}>
        Mini-sector comparison unavailable
        {widget.reason ? ` (${widget.reason})` : ''}.
      </div>
    )
  }

  const {
    driver_a, driver_b, lap_number, segments,
    cumulative_delta, total_delta_s,
    segments_won_a, segments_won_b, segments_tied,
    drs_mix_warning, weather_state,
  } = widget

  return (
    <div style={{ padding: 12, border: '1px solid hsl(0 0% 90%)', borderRadius: 8 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
        <strong>Mini-sectors — Lap {lap_number}</strong>
        <span style={{ fontSize: 12, color: 'hsl(0 0% 40%)' }}>
          {weather_state && weather_state !== 'unknown' ? `${weather_state} · ` : ''}
          {segments?.length || 0} segments
        </span>
      </div>

      <div style={{ display: 'flex', gap: 12, marginTop: 8, fontSize: 13 }}>
        <span><span style={{ color: COLOR_A }}>■</span> {driver_a} ({segments_won_a || 0})</span>
        <span><span style={{ color: COLOR_B }}>■</span> {driver_b} ({segments_won_b || 0})</span>
        {segments_tied > 0 && (
          <span><span style={{ color: COLOR_TIE }}>■</span> tied ({segments_tied})</span>
        )}
      </div>

      <MiniSectorBar segments={segments} driverA={driver_a} driverB={driver_b} />

      {drs_mix_warning && (
        <div style={{ marginTop: 8, padding: 6, background: 'hsl(45 90% 92%)',
                      borderRadius: 4, fontSize: 12, color: 'hsl(30 70% 30%)' }}>
          ⚠ DRS-mix detected: one driver had DRS open in at least one segment where the other didn't.
          Gap in those segments is contaminated by DRS state, not pure pace.
        </div>
      )}

      <CumulativeDeltaChart data={cumulative_delta} totalDelta={total_delta_s} />

      <div style={{ marginTop: 6, fontSize: 11, color: 'hsl(0 0% 50%)' }}>
        Negative Δ = {driver_a} faster · Positive Δ = {driver_b} faster
      </div>
    </div>
  )
}
```

- [ ] **Step 3: Register in AnswerRenderer**

Open `client/src/components/AnswerRenderer.jsx`. Find the existing import block for widgets and add:

```jsx
import MiniSectorHeatmapWidget from './chat-widgets/MiniSectorHeatmapWidget.jsx'
```

Find the widget-type dispatch (the cluster of `widget.type === 'X'` cases) and add:

```jsx
if (widget.type === 'mini_sector_heatmap') {
  return <MiniSectorHeatmapWidget widget={widget} />
}
```

- [ ] **Step 4: Run client build**

```
cd C:/Users/sanja/Documents/Nerd/F1Dash/client; npm run build 2>&1 | tail -6
```

Expected: clean build, no JSX errors.

- [ ] **Step 5: Commit**

```
git add client/src/components/chat-widgets/MiniSectorHeatmapWidget.jsx client/src/components/AnswerRenderer.jsx
git commit -m "feat(client): MiniSectorHeatmapWidget — bar heatmap + cumulative-delta chart

Bar segmented into 25 cells colored by per-segment winner (A blue, B orange,
tied gray). Cumulative-delta SVG chart below. DRS-mix warning banner when
the backend sets drs_mix_warning. Render-degraded path when available=false.

AnswerRenderer registers the mini_sector_heatmap widget type.

Plan: docs/superpowers/plans/2026-05-21-mini-sectors-heatmap.md Task 5"
```

---

## Task 6: End-to-end live smoke test

**Files:**
- Run command only — no code change.

After all tasks land, exercise the full pipeline against a real race.

- [ ] **Step 1: Start uvicorn**

```
cd C:/Users/sanja/Documents/Nerd/F1Dash/server; python -m uvicorn main:app --reload --port 8000
```

- [ ] **Step 2: Issue a real query**

Ask the chat: *"Compare Norris and Piastri mini-sectors on their fastest 2024 Imola Q3 lap. Where did Piastri lose time?"*

Expected:
- LLM picks `compare_mini_sectors` over `get_sector_comparison` (per the SYSTEM_PROMPT rule).
- A `mini_sector_heatmap` widget renders below the answer text, showing the colored bar + delta chart.
- The answer prose mentions specific mini-sector regions (e.g. "Piastri lost most time across segments 8–12, around 1600-2400 m of the lap — the Acque Minerali / Variante Alta section").

- [ ] **Step 3: Sanity-check the totals**

The widget's `total_delta_s` should be within ~50 ms of the gap between the two laps' `LapTime` values shown on F1's official site. Larger discrepancies indicate the segment-time computation has drift; investigate via the audit table or by inspecting the raw `compute_mini_sectors` output.

---

## Validation Checklist

- [ ] `cd server; python -m pytest tests/ -q` reports 492 passing (478 baseline + 14 new).
- [ ] `cd client; npm run build` succeeds with no JSX errors.
- [ ] Chat answer to a mini-sector question renders the new widget with 25 colored bars.
- [ ] `compute_mini_sectors` returns segments whose `end_m - start_m` sums within 1 m of total lap distance.
- [ ] Segment `time_s` values sum within 5 ms of the lap's `LapTime`.
- [ ] When one driver had DRS open in a segment and the other didn't, the widget shows the DRS-mix warning.
- [ ] When tools.py's `compare_mini_sectors` is called with missing args, the agentic loop receives a `ValueError` with the missing field name.

---

## Risks and Open Questions

| Risk | Trigger | Proposed resolution | Decision needed by |
|---|---|---|---|
| **`session.weather_data.Rainfall` shape varies across FastF1 versions.** Older versions emit floats, newer versions Booleans. | Live smoke test | Wrap the access in try/except; default `weather_state` to `"unknown"` on any error. Already handled in the implementation. | Already mitigated |
| **`pick_laps(lap_number)` may return zero rows if the driver did not record that lap** (e.g. crashed earlier). | Live use | Return `{"available": False, "reason": "lap_not_found"}`. Already handled. | Already mitigated |
| **25-segment compute per lap may be slow for many concurrent users.** Single-user hobby use it's fine, but the cron + multi-user case isn't. | Production scale | Memoise per `(round, session, driver, lap, n)` in an LRU cache. Out of scope for this plan. | Post-hobby |
| **The widget's bar visualization doesn't show track-map shape.** It's a linear bar, not a circuit overlay. | Always | The plan originally called for a track-map overlay, but reusing TrackMap.jsx with per-mini-sector coloring requires synchronizing track-map points to mini-sector boundaries by cumulative distance — adds complexity. The linear bar achieves the same "where on the lap" insight at lower cost. Track-map overlay is a follow-up. | Acceptable for V1 |
| **DRS state may be unreliable on 2026 telemetry** since DRS doesn't exist in 2026 regs. | 2026 races | The `drs_active_pct` returns 0.0 when DRS column is missing or all zero. Widget warning won't fire. Acceptable — 2026 hybrid analysis uses override-mode detection instead (F32, already shipped). | Already mitigated |

---

## Non-Goals

- **No track-map circuit overlay.** Linear bar achieves the same insight; circuit-overlay is a follow-up.
- **No memoisation / caching of compute_mini_sectors.** Single-user scale; add when needed.
- **No race-pace mini-sectors.** This is qualifying-focused (single representative lap). Race-pace mini-sectors over a stint is a separate feature.
- **No per-driver DRS overlay on the chart.** The DRS-mix warning is binary; we don't render per-driver DRS state inline.
- **No telemetry for laps beyond `lap_number`.** The tool compares exactly one lap per driver; multi-lap aggregation is a future feature.

---

## References

- **MultiViewer F1 1.13+** — visual reference for the per-segment colored heatmap.
- F1 broadcast graphics use 25-segment colored splits during qualifying replays.
- Existing `get_sector_comparison` in `server/f1_data.py:2325` — the 3-sector coarse version this replaces for granular queries.
- Existing `_downsample_track_map` in `server/f1_data.py:3295` — sampling pattern this could reuse for future track-overlay version.
