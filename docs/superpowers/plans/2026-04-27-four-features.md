# F1Dash: Four Feature Additions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add pit stop strategy tool + widget, degradation scatter chart widget, weather/pace diagnostic tool, and an energy management widget with quantified efficiency metrics.

**Architecture:** Each feature adds a backend function (f1_data.py or openf1.py), wires it into tools.py and chat.py, and (where applicable) adds a React widget. Features are independent — implement in order but each is self-contained.

**Tech Stack:** Python/FastAPI backend, FastF1 + OpenF1 APIs, React + raw SVG for charts (no Recharts — existing charts use manual SVG as in SpeedTraceChart.jsx), Tailwind CSS with CSS variables (`hsl(var(--primary))` etc.).

---

## Codebase orientation

- `server/f1_data.py` — all data functions. Add new functions at the end. Helper functions are prefixed `_`.
- `server/openf1.py` — OpenF1 HTTP helpers. **Imports from f1_data.py**, so f1_data.py must use local imports when calling openf1 functions to avoid circular dependency.
- `server/tools.py` — tool registry. Every new function needs: (1) an import at top, (2) a `_tool(...)` entry in the right DEFINITIONS list, (3) a dispatch branch in `execute_tool`.
- `server/chat.py` — widget builders. To auto-emit a widget when a tool is called: add a `_make_X_widget` function and a branch in `_widgets_from_analysis_evidence`.
- `client/src/components/AnswerRenderer.jsx` — widget router. Add an import and a `widget.type === 'X'` branch in `WidgetRenderer`.
- `client/src/components/chat-widgets/` — one file per widget type.
- Tests: `server/tests/`. Run with `cd server && python -m pytest tests/ -v`.

**Existing inference functions (read before touching energy code):**
- `_infer_lift_and_coast_samples(samples)` → list of `{distance_m, speed_kph, throttle_pct}`. Detects throttle-off events at speed before a braking zone.
- `_infer_clipping_windows(samples)` → list of `{start_distance_m, end_distance_m, start_speed_kph, end_speed_kph, mid_speed_kph, speed_gain_kph, late_straight_drop_kph}`. Detects full-throttle straights where speed gain is low or the car decelerates in the second half.
- `_find_full_throttle_straight_windows(samples)` → list of sample groups: throttle ≥ 95%, gear ≥ 6, no brake, ≥ 4 consecutive samples.

---

## File map

**Create:**
- `client/src/components/chat-widgets/PitStopStrategyWidget.jsx`
- `client/src/components/chat-widgets/DegTrendChart.jsx`
- `client/src/components/chat-widgets/EnergyManagementWidget.jsx`

**Modify:**
- `server/openf1.py` — add `get_pit_stops(round_number)`
- `server/f1_data.py` — add `get_pit_stop_analysis`, `analyze_weather_pace_correlation`, `_extract_major_straights`, `_compute_energy_metrics`, `_analyze_straights_energy`; extend `_fit_stint_degradation` with scatter data; extend `analyze_energy_management` with speed trace + metrics
- `server/tools.py` — import + tool definition + execute_tool dispatch for `get_pit_stop_analysis` and `analyze_weather_pace_correlation`
- `server/chat.py` — add `_make_pit_stop_strategy_widget`, `_make_deg_trend_chart_widget`, `_make_energy_management_widget`; wire all three into `_widgets_from_analysis_evidence`; update `ANSWER_WRITER_SYSTEM_PROMPT` for energy widget
- `client/src/components/AnswerRenderer.jsx` — import + dispatch for three new widget types

---

## Feature 1: Pit Stop Strategy

### Task 1: Add `get_pit_stops` to openf1.py

**Files:**
- Modify: `server/openf1.py` (append after line 175)
- Test: `server/tests/test_openf1.py`

- [ ] **Step 1: Write the failing test**

```python
# server/tests/test_openf1.py — add at end
def _make_openf1_session_row():
    return {"session_key": 9876, "date_start": "2026-04-06", "country_name": "Bahrain",
            "session_name": "Race", "circuit_short_name": "Bahrain"}

def _make_pit_rows():
    return [
        {"driver_number": 63, "lap_number": 14, "pit_duration": 2.41, "session_key": 9876},
        {"driver_number": 4,  "lap_number": 17, "pit_duration": 2.63, "session_key": 9876},
    ]

def test_get_pit_stops_returns_list():
    with patch.object(openf1, '_resolve_openf1_session', return_value=_make_openf1_session_row()), \
         patch.object(openf1, '_openf1_get', return_value=_make_pit_rows()):
        result = openf1.get_pit_stops(1)
    assert isinstance(result, list)
    assert result[0]["driver_number"] == 63
    assert result[0]["pit_duration_s"] == 2.41
    assert result[0]["lap_number"] == 14

def test_get_pit_stops_skips_rows_without_lap_number():
    rows = [{"driver_number": 63, "pit_duration": 2.41}]  # no lap_number
    with patch.object(openf1, '_resolve_openf1_session', return_value=_make_openf1_session_row()), \
         patch.object(openf1, '_openf1_get', return_value=rows):
        result = openf1.get_pit_stops(1)
    assert result == []
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd server && python -m pytest tests/test_openf1.py::test_get_pit_stops_returns_list tests/test_openf1.py::test_get_pit_stops_skips_rows_without_lap_number -v
```
Expected: FAIL with `AttributeError: module 'openf1' has no attribute 'get_pit_stops'`

- [ ] **Step 3: Implement `get_pit_stops`**

Append to `server/openf1.py` after line 175:

```python
def get_pit_stops(round_number: int) -> list[dict]:
    """
    Raw pit stop rows from OpenF1 for a race: driver_number, lap_number, pit_duration_s.
    Returns an empty list if OpenF1 has no data yet (race not happened).
    """
    session = _resolve_openf1_session(round_number, "R")
    rows = _openf1_get("pit", session_key=session["session_key"])
    return [
        {
            "driver_number": r.get("driver_number"),
            "lap_number": r.get("lap_number"),
            "pit_duration_s": round(float(r["pit_duration"]), 2) if r.get("pit_duration") is not None else None,
        }
        for r in rows
        if r.get("driver_number") is not None and r.get("lap_number") is not None
    ]
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd server && python -m pytest tests/test_openf1.py::test_get_pit_stops_returns_list tests/test_openf1.py::test_get_pit_stops_skips_rows_without_lap_number -v
```
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add server/openf1.py server/tests/test_openf1.py
git commit -m "feat: add get_pit_stops to openf1"
```

---

### Task 2: Add `get_pit_stop_analysis` to f1_data.py

**Files:**
- Modify: `server/f1_data.py` (append after `analyze_race_pace_battle`)
- Test: `server/tests/test_f1_data.py`

- [ ] **Step 1: Write the failing test**

```python
# server/tests/test_f1_data.py — add at end
def _make_fastf1_pit_laps():
    import pandas as pd
    return pd.DataFrame({
        "DriverNumber": ["63"] * 5,
        "Driver": ["RUS"] * 5,
        "LapNumber": [1, 2, 3, 4, 5],
        "Compound": ["MEDIUM", "MEDIUM", "HARD", "HARD", "HARD"],
        "PitInTime": [pd.NaT, pd.Timedelta("0:23:00"), pd.NaT, pd.NaT, pd.NaT],
        "PitOutTime": [pd.NaT, pd.NaT, pd.Timedelta("0:23:02.5"), pd.NaT, pd.NaT],
        "Position": [5, 5, 6, 6, 5],
    })

def test_get_pit_stop_analysis_structure():
    mock_session = MagicMock()
    mock_session.laps = _make_fastf1_pit_laps()
    mock_session.event = {"EventName": "Test GP"}

    with patch('f1_data._validate_session_availability'), \
         patch('f1_data._load_session', return_value=mock_session), \
         patch('f1_data.get_session_results', return_value={"results": [
             {"driver_number": "63", "abbreviation": "RUS", "position": 4}
         ]}), \
         patch('f1_data._openf1_pit_fetch', return_value={(63, 2): 2.41}):
        result = f1_data.get_pit_stop_analysis(4)

    assert result["event"] == "Test GP"
    assert isinstance(result["drivers"], list)
    rus = result["drivers"][0]
    assert rus["driver"] == "RUS"
    assert len(rus["stints"]) == 2
    assert rus["stints"][0]["compound"] == "MEDIUM"
    assert rus["stints"][1]["compound"] == "HARD"
    assert len(rus["pit_stops"]) == 1
    assert rus["pit_stops"][0]["lap"] == 2
    assert rus["pit_stops"][0]["duration_s"] == 2.41
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd server && python -m pytest tests/test_f1_data.py::test_get_pit_stop_analysis_structure -v
```
Expected: FAIL with `AttributeError: module 'f1_data' has no attribute 'get_pit_stop_analysis'`

- [ ] **Step 3: Implement `_openf1_pit_fetch` and `get_pit_stop_analysis`**

Append to `server/f1_data.py` (after `analyze_race_pace_battle`):

```python
def _openf1_pit_fetch(round_number: int) -> dict:
    """
    Returns {(driver_number_int, lap_number_int): pit_duration_s} from OpenF1.
    Falls back to empty dict on any error so the caller always gets valid data.
    Local import avoids circular dependency (openf1.py imports from f1_data.py).
    """
    try:
        from openf1 import get_pit_stops
        rows = get_pit_stops(round_number)
        return {
            (int(r["driver_number"]), int(r["lap_number"])): r["pit_duration_s"]
            for r in rows
            if r.get("driver_number") is not None and r.get("lap_number") is not None
        }
    except Exception:
        return {}


def get_pit_stop_analysis(round_number: int) -> dict:
    """
    Pit stop strategy for all classified finishers in a race.
    Returns per-driver stints (compound, start_lap, end_lap, laps) and pit stops
    (lap, duration_s from OpenF1, compound_in, compound_out).
    Drivers are sorted by finish position.
    """
    _validate_session_availability(round_number, "R", telemetry=False)
    session = _load_session(round_number, "R", laps=True)

    session_results = get_session_results(round_number, "R")
    results_list = session_results.get("results", [])
    num_to_code = {
        int(r["driver_number"]): r["abbreviation"].upper()
        for r in results_list
        if r.get("driver_number") and r.get("abbreviation")
    }
    finish_order = {
        r["abbreviation"].upper(): _normalize_position(r.get("position")) or 99
        for r in results_list
        if r.get("abbreviation")
    }

    pit_durations = _openf1_pit_fetch(round_number)

    drivers_data = []
    all_codes = session.laps["Driver"].dropna().unique() if not session.laps.empty else []

    for code in all_codes:
        code = str(code).upper()
        driver_laps = _pick_driver(session.laps, code)
        if driver_laps.empty:
            continue

        driver_laps = driver_laps.sort_values("LapNumber")
        stints: list[dict] = []
        pit_stops: list[dict] = []
        current_compound: str | None = None
        stint_start: int | None = None
        driver_num_int = next((n for n, c in num_to_code.items() if c == code), None)

        for _, lap in driver_laps.iterrows():
            lap_num = int(lap["LapNumber"])
            compound = str(lap.get("Compound") or "UNKNOWN").upper()

            if current_compound is None:
                current_compound = compound
                stint_start = lap_num
            elif compound != current_compound:
                stints.append({
                    "compound": current_compound,
                    "start_lap": stint_start,
                    "end_lap": lap_num - 1,
                    "laps": lap_num - 1 - stint_start + 1,
                })
                duration = (
                    pit_durations.get((driver_num_int, lap_num - 1))
                    if driver_num_int is not None else None
                )
                pit_stops.append({
                    "lap": lap_num - 1,
                    "duration_s": duration,
                    "compound_in": current_compound,
                    "compound_out": compound,
                })
                current_compound = compound
                stint_start = lap_num

        if current_compound and stint_start is not None:
            max_lap = int(driver_laps["LapNumber"].max())
            stints.append({
                "compound": current_compound,
                "start_lap": stint_start,
                "end_lap": max_lap,
                "laps": max_lap - stint_start + 1,
            })

        if stints:
            drivers_data.append({
                "driver": code,
                "stints": stints,
                "pit_stops": pit_stops,
                "_finish": finish_order.get(code, 99),
            })

    drivers_data.sort(key=lambda d: d.pop("_finish"))
    total_laps = int(session.laps["LapNumber"].max()) if not session.laps.empty else None

    return {
        "event": session.event["EventName"],
        "session": "R",
        "total_laps": total_laps,
        "drivers": drivers_data,
    }
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd server && python -m pytest tests/test_f1_data.py::test_get_pit_stop_analysis_structure -v
```
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add server/f1_data.py server/tests/test_f1_data.py
git commit -m "feat: add get_pit_stop_analysis"
```

---

### Task 3: Wire `get_pit_stop_analysis` into tools.py

**Files:**
- Modify: `server/tools.py`

- [ ] **Step 1: Add import**

In the `from f1_data import (...)` block at top of `server/tools.py`, add:

```python
    get_pit_stop_analysis,
```

- [ ] **Step 2: Add tool definition**

In `PRIMITIVE_TOOL_DEFINITIONS` (before the closing `]`), add:

```python
    _tool(
        "get_pit_stop_analysis",
        "PRIMITIVE TOOL. Pit stop strategy for all classified finishers in a race. "
        "Returns per-driver stints (compound, start_lap, end_lap, laps), pit stop laps, "
        "pit durations from OpenF1, and compound changes. Drivers sorted by finish position. "
        "Use for 'who had the fastest pit stops?', 'show me the strategy', "
        "'did anyone undercut on the pit stop?'.",
        {
            "round_number": {"type": "integer", "description": "The 2026 season round number."},
        },
        ["round_number"],
    ),
```

- [ ] **Step 3: Add execute_tool dispatch**

Before the final `raise` at the bottom of `execute_tool`, add:

```python
    if name == "get_pit_stop_analysis":
        return get_pit_stop_analysis(args["round_number"])
```

- [ ] **Step 4: Run tool tests**

```bash
cd server && python -m pytest tests/test_tools.py -v
```
Expected: All existing tests PASS

- [ ] **Step 5: Commit**

```bash
git add server/tools.py
git commit -m "feat: wire get_pit_stop_analysis into tools"
```

---

### Task 4: Create `PitStopStrategyWidget.jsx`

**Files:**
- Create: `client/src/components/chat-widgets/PitStopStrategyWidget.jsx`

Horizontal timeline per driver, colored by compound. Pit durations shown on right, fastest pit highlighted green.

- [ ] **Step 1: Create the widget file**

```jsx
// client/src/components/chat-widgets/PitStopStrategyWidget.jsx
const COMPOUND_COLORS = {
  SOFT: 'hsl(var(--primary))',
  MEDIUM: 'hsl(var(--time))',
  HARD: 'hsl(var(--foreground) / 0.5)',
  INTERMEDIATE: 'hsl(var(--speed))',
  WET: 'hsl(210 80% 55%)',
  UNKNOWN: 'hsl(var(--muted-foreground))',
}
const COMPOUND_SHORT = { SOFT: 'S', MEDIUM: 'M', HARD: 'H', INTERMEDIATE: 'I', WET: 'W', UNKNOWN: '?' }

function StintBar({ stints, pitStops, totalLaps }) {
  if (!totalLaps || !stints?.length) return null
  return (
    <div className="relative h-5 w-full">
      {stints.map((stint, i) => {
        const left = ((stint.start_lap - 1) / totalLaps) * 100
        const width = (stint.laps / totalLaps) * 100
        return (
          <div
            key={i}
            className="absolute top-0 h-full rounded-[2px]"
            style={{
              left: `${left}%`,
              width: `${Math.max(width, 0.5)}%`,
              backgroundColor: COMPOUND_COLORS[stint.compound] ?? COMPOUND_COLORS.UNKNOWN,
              opacity: 0.85,
            }}
            title={`${stint.compound}: laps ${stint.start_lap}–${stint.end_lap}`}
          />
        )
      })}
      {pitStops?.map((pit, i) => (
        <div
          key={i}
          className="absolute top-0 h-full w-px bg-background/90"
          style={{ left: `${((pit.lap - 1) / totalLaps) * 100}%` }}
        />
      ))}
    </div>
  )
}

export default function PitStopStrategyWidget({ widget }) {
  const totalLaps = widget.total_laps
  const drivers = widget.drivers ?? []

  const allDurations = drivers.flatMap((d) => d.pit_stops ?? []).map((p) => p.duration_s).filter(Boolean)
  const fastestPit = allDurations.length ? Math.min(...allDurations) : null

  return (
    <div className="widget-enter max-w-3xl overflow-hidden border-y border-border/80 py-1">
      <div className="flex items-center justify-between py-3">
        <h4 className="text-sm font-medium text-foreground">{widget.event} — strategy</h4>
        <div className="flex gap-3 text-xs text-muted-foreground">
          {['SOFT', 'MEDIUM', 'HARD'].map((c) => (
            <span key={c} className="flex items-center gap-1">
              <span className="inline-block h-2.5 w-2.5 rounded-[2px]" style={{ backgroundColor: COMPOUND_COLORS[c] }} />
              {COMPOUND_SHORT[c]}
            </span>
          ))}
        </div>
      </div>

      <div className="divide-y divide-border/60">
        {drivers.map((d) => (
          <div key={d.driver} className="grid items-center gap-3 py-2 sm:grid-cols-[3.5rem_minmax(0,1fr)_7rem]">
            <div className="text-sm font-medium text-foreground">{d.driver}</div>
            <StintBar stints={d.stints} pitStops={d.pit_stops} totalLaps={totalLaps} />
            <div className="text-right text-xs text-muted-foreground">
              {d.pit_stops?.length
                ? d.pit_stops.map((p, i) => (
                    <span key={i} className="ml-2">
                      {p.duration_s != null ? (
                        <span className={p.duration_s === fastestPit ? 'font-medium text-[hsl(var(--speed))]' : ''}>
                          {p.duration_s.toFixed(2)}s
                        </span>
                      ) : `L${p.lap}`}
                    </span>
                  ))
                : '—'}
            </div>
          </div>
        ))}
      </div>

      <div className="flex gap-1 py-2 text-xs text-muted-foreground">
        <span>Lap 1</span>
        <span className="mx-1 flex-1 self-center border-t border-border/50" />
        <span>{totalLaps ? `Lap ${totalLaps}` : ''}</span>
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Commit**

```bash
git add client/src/components/chat-widgets/PitStopStrategyWidget.jsx
git commit -m "feat: add PitStopStrategyWidget"
```

---

### Task 5: Wire pit stop widget into chat.py and AnswerRenderer.jsx

**Files:**
- Modify: `server/chat.py`
- Modify: `client/src/components/AnswerRenderer.jsx`

- [ ] **Step 1: Add `_make_pit_stop_strategy_widget` to chat.py**

Add after `_make_circuit_profile_widget`:

```python
def _make_pit_stop_strategy_widget(result: dict) -> dict:
    return {
        "type": "pit_stop_strategy",
        "title": f"{result.get('event')} strategy",
        "event": result.get("event"),
        "session": result.get("session"),
        "total_laps": result.get("total_laps"),
        "drivers": result.get("drivers") or [],
    }
```

- [ ] **Step 2: Wire into `_widgets_from_analysis_evidence`**

Inside the `for item in evidence:` loop, after the last `elif tool ==` branch:

```python
        elif tool == "get_pit_stop_analysis":
            widgets.append(_make_pit_stop_strategy_widget(item["result"]))
```

- [ ] **Step 3: Wire into AnswerRenderer.jsx**

Add import at top:

```jsx
import PitStopStrategyWidget from './chat-widgets/PitStopStrategyWidget.jsx'
```

Add to `WidgetRenderer`:

```jsx
  if (widget.type === 'pit_stop_strategy') {
    return <PitStopStrategyWidget widget={widget} />
  }
```

- [ ] **Step 4: Run all server tests**

```bash
cd server && python -m pytest tests/ -v
```
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add server/chat.py client/src/components/AnswerRenderer.jsx
git commit -m "feat: wire pit stop strategy widget end-to-end"
```

---

## Feature 2: Degradation Trend Chart

### Task 6: Add scatter data to `_fit_stint_degradation`

**Files:**
- Modify: `server/f1_data.py` (`_fit_stint_degradation` function, around line 3794)
- Test: `server/tests/test_f1_data.py`

- [ ] **Step 1: Write the failing test**

```python
# server/tests/test_f1_data.py — add at end
def test_fit_stint_degradation_includes_scatter_data():
    laps = [
        {"lap_number": i, "lap_time_s": 82.0 + i * 0.01, "compound": "HARD", "tyre_age": i}
        for i in range(1, 8)
    ]
    result = f1_data._fit_stint_degradation(laps)
    assert len(result) == 1
    stint = result[0]
    assert "scatter_data" in stint, "scatter_data missing"
    assert "regression_line" in stint, "regression_line missing"
    assert len(stint["scatter_data"]) == 7
    assert all("tyre_age" in pt and "lap_time_s" in pt and "lap_number" in pt for pt in stint["scatter_data"])
    assert len(stint["regression_line"]) == 2
    assert stint["regression_line"][0]["tyre_age"] <= stint["regression_line"][1]["tyre_age"]
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd server && python -m pytest tests/test_f1_data.py::test_fit_stint_degradation_includes_scatter_data -v
```
Expected: FAIL with `AssertionError: scatter_data missing`

- [ ] **Step 3: Add scatter_data and regression_line inside `results.append({...})`**

In `_fit_stint_degradation`, find the `results.append({...})` block (around line 3794) and add these two keys:

```python
            'scatter_data': [
                {'tyre_age': ta, 'lap_time_s': round(fc, 3), 'lap_number': ln}
                for ta, fc, ln in zip(tyre_ages, fuel_corrected, lap_nums)
            ],
            'regression_line': [
                {'tyre_age': tyre_ages[0],  'lap_time_s': round(slope * tyre_ages[0]  + intercept, 3)},
                {'tyre_age': tyre_ages[-1], 'lap_time_s': round(slope * tyre_ages[-1] + intercept, 3)},
            ],
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd server && python -m pytest tests/test_f1_data.py::test_fit_stint_degradation_includes_scatter_data -v
```
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add server/f1_data.py server/tests/test_f1_data.py
git commit -m "feat: add scatter_data and regression_line to stint degradation output"
```

---

### Task 7: Create `DegTrendChart.jsx`

**Files:**
- Create: `client/src/components/chat-widgets/DegTrendChart.jsx`

SVG scatter plot with regression line per compound. Inverted convention: lower lap time = faster = better.

- [ ] **Step 1: Create the widget file**

```jsx
// client/src/components/chat-widgets/DegTrendChart.jsx
const COMPOUND_COLORS = {
  SOFT: 'hsl(var(--primary))',
  MEDIUM: 'hsl(var(--time))',
  HARD: 'hsl(var(--foreground) / 0.55)',
  INTERMEDIATE: 'hsl(var(--speed))',
  WET: 'hsl(210 80% 55%)',
}

const W = 600
const H = 180
const PAD = { top: 12, right: 16, bottom: 36, left: 52 }
const IW = W - PAD.left - PAD.right
const IH = H - PAD.top - PAD.bottom

function fmtTime(s) {
  const m = Math.floor(s / 60)
  const rem = (s % 60).toFixed(3).padStart(6, '0')
  return `${m}:${rem}`
}

export default function DegTrendChart({ widget }) {
  const stints = widget.stints ?? []
  if (!stints.length) return null

  const allPoints = stints.flatMap((s) => s.scatter_data ?? [])
  if (!allPoints.length) return null

  const allAges = allPoints.map((p) => p.tyre_age)
  const allTimes = allPoints.map((p) => p.lap_time_s)
  const minAge = Math.min(...allAges)
  const maxAge = Math.max(...allAges)
  const minTime = Math.min(...allTimes) - 0.3
  const maxTime = Math.max(...allTimes) + 0.3
  const ageSpan = maxAge - minAge || 1
  const timeSpan = maxTime - minTime || 1

  const toX = (age) => PAD.left + ((age - minAge) / ageSpan) * IW
  const toY = (t)   => PAD.top  + ((t - minTime) / timeSpan) * IH

  const tickStep = timeSpan > 4 ? 2 : timeSpan > 1.5 ? 0.5 : 0.2
  const yTicks = []
  let tick = Math.ceil(minTime / tickStep) * tickStep
  while (tick <= maxTime + 0.001) { yTicks.push(tick); tick = Math.round((tick + tickStep) * 1000) / 1000 }

  return (
    <div className="widget-enter max-w-3xl overflow-hidden border-y border-border/80 py-1">
      <div className="flex items-center justify-between py-3">
        <h4 className="text-sm font-medium text-foreground">{widget.title}</h4>
        <div className="flex gap-3">
          {stints.map((s) => (
            <span key={s.compound} className="flex items-center gap-1 text-xs text-muted-foreground">
              <span className="inline-block h-2 w-4 rounded-full"
                style={{ backgroundColor: COMPOUND_COLORS[s.compound] ?? 'hsl(var(--muted-foreground))' }} />
              {s.compound.charAt(0) + s.compound.slice(1).toLowerCase()}
            </span>
          ))}
        </div>
      </div>
      <p className="mb-2 text-xs text-muted-foreground">
        Fuel-corrected lap time vs tyre age — lower = faster. Dots are observed laps; dashed line is regression trend.
      </p>

      <div className="overflow-x-auto">
        <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} className="block">
          {yTicks.map((t) => (
            <g key={t}>
              <line x1={PAD.left} x2={W - PAD.right} y1={toY(t)} y2={toY(t)}
                stroke="hsl(var(--border))" strokeWidth={0.5} />
              <text x={PAD.left - 4} y={toY(t) + 4} textAnchor="end" fontSize={9}
                fill="hsl(var(--muted-foreground))">{fmtTime(t)}</text>
            </g>
          ))}
          <text x={PAD.left + IW / 2} y={H - 4} textAnchor="middle" fontSize={9}
            fill="hsl(var(--muted-foreground))">Tyre age (laps)</text>

          {stints.map((stint) => {
            const color = COMPOUND_COLORS[stint.compound] ?? 'hsl(var(--muted-foreground))'
            const pts = stint.scatter_data ?? []
            const reg = stint.regression_line ?? []
            return (
              <g key={stint.compound}>
                {pts.map((pt, i) => (
                  <circle key={i} cx={toX(pt.tyre_age)} cy={toY(pt.lap_time_s)}
                    r={3} fill={color} fillOpacity={0.7} />
                ))}
                {reg.length === 2 && (
                  <line
                    x1={toX(reg[0].tyre_age)} y1={toY(reg[0].lap_time_s)}
                    x2={toX(reg[1].tyre_age)} y2={toY(reg[1].lap_time_s)}
                    stroke={color} strokeWidth={1.5} strokeDasharray="4 2" strokeOpacity={0.9} />
                )}
              </g>
            )
          })}

          <line x1={PAD.left} x2={PAD.left} y1={PAD.top} y2={H - PAD.bottom}
            stroke="hsl(var(--border))" strokeWidth={1} />
          <line x1={PAD.left} x2={W - PAD.right} y1={H - PAD.bottom} y2={H - PAD.bottom}
            stroke="hsl(var(--border))" strokeWidth={1} />
        </svg>
      </div>

      {stints.map((s) => (
        <div key={s.compound} className="border-t border-border/60 py-2 text-xs text-muted-foreground">
          <span className="font-medium text-foreground">
            {s.compound.charAt(0) + s.compound.slice(1).toLowerCase()}
          </span>
          {' '}— {s.lap_count} laps · deg {s.deg_rate_s_per_lap >= 0 ? '+' : ''}{s.deg_rate_s_per_lap?.toFixed(3)}s/lap
          {s.r_squared != null ? ` · R²=${s.r_squared.toFixed(2)}` : ''}
        </div>
      ))}
    </div>
  )
}
```

- [ ] **Step 2: Commit**

```bash
git add client/src/components/chat-widgets/DegTrendChart.jsx
git commit -m "feat: add DegTrendChart widget"
```

---

### Task 8: Wire DegTrendChart into chat.py and AnswerRenderer.jsx

**Files:**
- Modify: `server/chat.py`
- Modify: `client/src/components/AnswerRenderer.jsx`

- [ ] **Step 1: Add `_make_deg_trend_chart_widget` to chat.py**

Add after `_make_pit_stop_strategy_widget`:

```python
def _make_deg_trend_chart_widget(result: dict) -> dict:
    return {
        "type": "deg_trend_chart",
        "title": f"{result.get('driver')} — {result.get('event')} tyre degradation",
        "driver": result.get("driver"),
        "event": result.get("event"),
        "stints": [
            {
                "compound": s.get("compound"),
                "lap_count": s.get("lap_count"),
                "deg_rate_s_per_lap": s.get("deg_rate_s_per_lap"),
                "r_squared": s.get("r_squared"),
                "scatter_data": s.get("scatter_data") or [],
                "regression_line": s.get("regression_line") or [],
            }
            for s in (result.get("stints") or [])
            if s.get("scatter_data") or s.get("regression_line")
        ],
    }
```

- [ ] **Step 2: Wire into `_widgets_from_analysis_evidence`**

In the `for item in evidence:` loop:

```python
        elif tool == "analyze_stint_degradation":
            w = _make_deg_trend_chart_widget(item["result"])
            if w.get("stints"):
                widgets.append(w)
```

- [ ] **Step 3: Wire into AnswerRenderer.jsx**

Add import:

```jsx
import DegTrendChart from './chat-widgets/DegTrendChart.jsx'
```

Add to `WidgetRenderer`:

```jsx
  if (widget.type === 'deg_trend_chart') {
    return <DegTrendChart widget={widget} />
  }
```

- [ ] **Step 4: Run all server tests**

```bash
cd server && python -m pytest tests/ -v
```
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add server/chat.py client/src/components/AnswerRenderer.jsx
git commit -m "feat: wire DegTrendChart end-to-end"
```

---

## Feature 3: Weather / Pace Diagnostic Tool

**Purpose:** Reactive diagnostic only — the LLM calls this when it needs to explain an anomaly (Q3 slower than Q2, pace fell off mid-race, etc.). No custom widget; the LLM uses the data to construct a text explanation or data_table.

### Task 9: Add `analyze_weather_pace_correlation` to f1_data.py

**Files:**
- Modify: `server/f1_data.py` (append after `get_pit_stop_analysis`)
- Test: `server/tests/test_f1_data.py`

- [ ] **Step 1: Write the failing test**

```python
# server/tests/test_f1_data.py — add at end
def _make_weather_df():
    import pandas as pd
    return pd.DataFrame({
        "Time": pd.to_timedelta(["0:05:00", "0:12:00", "0:18:00", "0:25:00", "0:32:00", "0:38:00"]),
        "TrackTemp": [38.0, 39.0, 40.0, 41.0, 42.0, 43.0],
        "AirTemp":   [28.0, 28.5, 29.0, 29.5, 30.0, 30.5],
        "Rainfall":  [False, False, False, False, False, False],
    })

def _make_quali_laps_weather():
    import pandas as pd
    rows = []
    for i, (seg, lt) in enumerate([
        ("Q1", 82.5), ("Q1", 82.3),
        ("Q2", 81.8), ("Q2", 81.6),
        ("Q3", 81.2), ("Q3", 81.0),
    ]):
        rows.append({
            "Driver": "RUS", "LapNumber": i + 1,
            "LapTime": pd.Timedelta(seconds=lt),
            "Session": seg,
            "Deleted": False,
            "Time": pd.Timedelta(seconds=(i + 1) * 400),
        })
    return pd.DataFrame(rows)

def test_analyze_weather_pace_correlation_qualifying():
    mock_session = MagicMock()
    mock_session.laps = _make_quali_laps_weather()
    mock_session.weather_data = _make_weather_df()
    mock_session.event = {"EventName": "Test GP"}

    with patch('f1_data._validate_session_availability'), \
         patch('f1_data._load_session', return_value=mock_session):
        result = f1_data.analyze_weather_pace_correlation(4, "Q")

    assert result["session"] == "Q"
    assert "segments" in result
    segs = result["segments"]
    assert len(segs) > 0
    for seg in segs:
        assert "avg_track_temp_c" in seg
        assert "best_lap_s" in seg
        assert "segment" in seg
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd server && python -m pytest tests/test_f1_data.py::test_analyze_weather_pace_correlation_qualifying -v
```
Expected: FAIL with `AttributeError: module 'f1_data' has no attribute 'analyze_weather_pace_correlation'`

- [ ] **Step 3: Implement `analyze_weather_pace_correlation`**

Append to `server/f1_data.py`:

```python
def analyze_weather_pace_correlation(round_number: int, session_type: str = "Q") -> dict:
    """
    Correlates track temperature with lap time evolution through the session.
    For qualifying: Q1/Q2/Q3 segments — temperature and best lap per segment.
    For race: 10-lap blocks — temperature and top-5 average pace per block.
    Primary use: explain anomalies (Q3 slower than Q2, pace drop mid-race).
    """
    _validate_session_availability(round_number, session_type, telemetry=False)
    session = _load_session(round_number, session_type, laps=True, weather=True)

    if session.weather_data is None or session.weather_data.empty:
        raise ValueError(f"No weather data available for round {round_number} {session_type}.")

    weather = session.weather_data.copy()
    laps = session.laps.copy()
    st = session_type.upper()

    def _nearest_weather(time_td):
        if weather.empty or time_td is None or pd.isna(time_td):
            return None, None
        diffs = (weather["Time"] - time_td).abs()
        row = weather.loc[diffs.idxmin()]
        return _normalize_float(row.get("TrackTemp")), _normalize_float(row.get("AirTemp"))

    segments = []

    if st == "Q":
        for q_seg in ["Q1", "Q2", "Q3"]:
            if "Session" in laps.columns:
                seg_laps = laps[laps["Session"] == q_seg]
            else:
                total = len(laps)
                thirds = [laps.iloc[:total//3], laps.iloc[total//3:2*total//3], laps.iloc[2*total//3:]]
                seg_laps = thirds[["Q1","Q2","Q3"].index(q_seg)]

            valid = seg_laps[
                seg_laps["LapTime"].notna()
                & ~seg_laps.get("Deleted", pd.Series(False, index=seg_laps.index))
            ]
            if valid.empty:
                continue

            lap_times_s = sorted([lt.total_seconds() for lt in valid["LapTime"] if pd.notna(lt)])
            best = round(lap_times_s[0], 3) if lap_times_s else None
            top5_avg = round(sum(lap_times_s[:5]) / min(5, len(lap_times_s)), 3) if lap_times_s else None
            mid_time = valid["Time"].median() if "Time" in valid.columns else None
            track_temp, air_temp = _nearest_weather(mid_time)

            segments.append({
                "segment": q_seg,
                "avg_track_temp_c": track_temp,
                "avg_air_temp_c": air_temp,
                "best_lap_s": best,
                "top5_avg_pace_s": top5_avg,
                "lap_count": len(valid),
            })
    else:
        max_lap = int(laps["LapNumber"].max()) if not laps.empty else 0
        for start in range(1, max_lap + 1, 10):
            end = min(start + 9, max_lap)
            block = laps[(laps["LapNumber"] >= start) & (laps["LapNumber"] <= end)]
            valid = block[block["LapTime"].notna()]
            if valid.empty:
                continue
            lap_times_s = sorted([
                lt.total_seconds() for lt in valid["LapTime"]
                if pd.notna(lt) and lt.total_seconds() < 200
            ])
            if not lap_times_s:
                continue
            mid_time = valid["Time"].median() if "Time" in valid.columns else None
            track_temp, air_temp = _nearest_weather(mid_time)
            segments.append({
                "segment": f"Laps {start}–{end}",
                "avg_track_temp_c": track_temp,
                "avg_air_temp_c": air_temp,
                "best_lap_s": round(lap_times_s[0], 3),
                "top5_avg_pace_s": round(sum(lap_times_s[:5]) / min(5, len(lap_times_s)), 3),
                "lap_count": len(valid),
            })

    first = next((s for s in segments if s["best_lap_s"]), None)
    last  = next((s for s in reversed(segments) if s["best_lap_s"]), None)
    track_evolution_s = (
        round(last["best_lap_s"] - first["best_lap_s"], 3)
        if first and last and first is not last else None
    )
    first_temp = first["avg_track_temp_c"] if first else None
    last_temp  = last["avg_track_temp_c"]  if last  else None
    temp_change_c = (
        round(last_temp - first_temp, 1)
        if first_temp is not None and last_temp is not None else None
    )
    rainfall = bool((weather.get("Rainfall") == True).any()) if not weather.empty else False

    return {
        "event": session.event["EventName"],
        "session": st,
        "segments": segments,
        "track_evolution_s": track_evolution_s,
        "temp_change_c": temp_change_c,
        "rainfall_recorded": rainfall,
        "how_to_read": (
            "track_evolution_s: negative = track got faster across the session. "
            "Use temp_change_c alongside track_evolution_s to separate rubber-laid grip from temperature effect. "
            "top5_avg_pace_s is more robust than best_lap_s when a single hotlap distorts the sample."
        ),
    }
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd server && python -m pytest tests/test_f1_data.py::test_analyze_weather_pace_correlation_qualifying -v
```
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add server/f1_data.py server/tests/test_f1_data.py
git commit -m "feat: add analyze_weather_pace_correlation"
```

---

### Task 10: Wire `analyze_weather_pace_correlation` into tools.py

**Files:**
- Modify: `server/tools.py`

- [ ] **Step 1: Add import** — add `analyze_weather_pace_correlation` to the `from f1_data import (...)` block.

- [ ] **Step 2: Add tool definition** in `DEEP_ANALYSIS_TOOL_DEFINITIONS`:

```python
    _tool(
        "analyze_weather_pace_correlation",
        "DEEP ANALYSIS PRIMITIVE. Correlates track temperature with lap time evolution. "
        "For qualifying: Q1/Q2/Q3 segments with temperature, best lap, and top-5 average. "
        "For race: 10-lap blocks with temperature and pace. "
        "Use reactively to explain anomalies: why Q3 was slower than Q2, why pace fell off mid-race, "
        "whether a track temperature drop or rainfall explains an unexpected result.",
        {
            "round_number": {"type": "integer", "description": "The 2026 season round number."},
            "session_type": {"type": "string", "description": "Q (default) or R."},
        },
        ["round_number"],
    ),
```

- [ ] **Step 3: Add execute_tool dispatch:**

```python
    if name == "analyze_weather_pace_correlation":
        return analyze_weather_pace_correlation(args["round_number"], args.get("session_type", "Q"))
```

- [ ] **Step 4: Run all tests**

```bash
cd server && python -m pytest tests/ -v
```
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add server/tools.py
git commit -m "feat: wire analyze_weather_pace_correlation into tools"
```

---

## Feature 4: Energy Management Widget with Efficiency Metrics

### Background: what the metrics mean

**Clipping** = MGU-K (motor) runs out of stored energy mid-straight. The car is flat on throttle but speed plateaus or drops. Detected by `_infer_clipping_windows` when a full-throttle window has < 12 kph speed gain, or speed drops from the midpoint to the end (`late_straight_drop_kph < 0`).

**Lift-and-coast** = driver lifts throttle 50–150m before the braking zone so the MGU-K harvests kinetic energy. Detected by `_infer_lift_and_coast_samples` at points where throttle ≤ 20%, speed ≥ 180 kph, and speed is decreasing.

**New computed metrics:**
- `clip_count`: how many clipping windows per lap
- `total_late_speed_drop_kph`: sum of `abs(late_straight_drop_kph)` across all clipping windows — total speed lost to ERS exhaustion
- `estimated_time_lost_to_clipping_s`: time penalty = Σ `(drop_m/s * half_window_m) / v_avg_m/s²`
- `lico_count`: how many lift-and-coast events per lap
- `total_harvest_distance_m`: total meters across all LiCo zones (consecutive LiCo events merged)
- `harvest_zones`: list of `{start_m, end_m, length_m}` for each harvest zone

**Per-straight breakdown:** For each major straight (speed > 275 kph for > 200m), compare peak speed, end speed, and whether each driver clipped.

### Task 11: Add helper functions and extend `analyze_energy_management`

**Files:**
- Modify: `server/f1_data.py` (add 3 helpers before `analyze_energy_management`; modify the function body)
- Test: `server/tests/test_f1_data.py`

- [ ] **Step 1: Write the failing tests**

```python
# server/tests/test_f1_data.py — add at end
def _make_speed_samples(n=30, base_speed=290, clip_at=15):
    """Simulate a straight where speed peaks then drops (clipping in second half)."""
    samples = []
    for i in range(n):
        speed = base_speed + i * 1.5 if i < clip_at else base_speed + clip_at * 1.5 - (i - clip_at) * 0.5
        samples.append({
            "distance_m": i * 20.0,
            "speed_kph": round(speed, 1),
            "throttle_pct": 100,
            "brake": False,
            "gear": 8,
            "rpm": 12000,
            "drs_open": True,
        })
    return samples

def test_compute_energy_metrics_clip_detection():
    samples = _make_speed_samples()
    clip_windows = f1_data._infer_clipping_windows(samples)
    lico_events = []
    metrics = f1_data._compute_energy_metrics(samples, lico_events, clip_windows)
    assert "clip_count" in metrics
    assert "estimated_time_lost_to_clipping_s" in metrics
    assert "lico_count" in metrics
    assert "total_harvest_distance_m" in metrics
    assert metrics["clip_count"] >= 0
    assert metrics["estimated_time_lost_to_clipping_s"] >= 0.0

def test_extract_major_straights_finds_high_speed_sections():
    samples = [{"distance_m": i * 10.0, "speed_kph": 290 if 20 <= i <= 50 else 150} for i in range(80)]
    straights = f1_data._extract_major_straights(samples, speed_threshold_kph=275, min_length_m=200)
    assert len(straights) == 1
    assert straights[0]["start_m"] == 200
    assert straights[0]["length_m"] >= 200

def test_analyze_energy_management_includes_speed_trace():
    mock_telemetry = {
        "event": "Test GP", "session": "Q", "driver": "NOR", "lap_number": 5,
        "telemetry": [
            {"distance_m": i * 5.0, "speed_kph": 200 + i, "throttle_pct": 80,
             "brake": False, "gear": 7, "rpm": 11000, "drs_open": False}
            for i in range(20)
        ]
    }
    with patch('f1_data.get_lap_telemetry', return_value=mock_telemetry), \
         patch('f1_data.get_energy_2026_knowledge', return_value={}):
        result = f1_data.analyze_energy_management(4, "Q", "NOR")
    assert "speed_trace_a" in result
    assert isinstance(result["speed_trace_a"], list)
    assert "energy_metrics_a" in result
    assert "clip_count" in result["energy_metrics_a"]
    assert "straight_breakdown" in result
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd server && python -m pytest tests/test_f1_data.py::test_compute_energy_metrics_clip_detection tests/test_f1_data.py::test_extract_major_straights_finds_high_speed_sections tests/test_f1_data.py::test_analyze_energy_management_includes_speed_trace -v
```
Expected: FAIL (functions not found)

- [ ] **Step 3: Add `_extract_major_straights` to f1_data.py**

Add before `analyze_energy_management` (around line 1826):

```python
def _extract_major_straights(
    samples: list[dict],
    speed_threshold_kph: float = 275,
    min_length_m: float = 200,
) -> list[dict]:
    """
    Find sections of track where speed >= threshold for >= min_length_m.
    Returns list of {start_m, end_m, length_m}, sorted by start_m.
    """
    straights: list[dict] = []
    in_straight = False
    start_m: float | None = None

    for s in samples:
        speed = s.get("speed_kph") or 0
        dist = s.get("distance_m") or 0
        if speed >= speed_threshold_kph and not in_straight:
            in_straight = True
            start_m = dist
        elif speed < speed_threshold_kph and in_straight:
            length = dist - (start_m or 0)
            if length >= min_length_m:
                straights.append({"start_m": round(start_m), "end_m": round(dist), "length_m": round(length)})
            in_straight = False

    if in_straight and start_m is not None and samples:
        end_m = samples[-1].get("distance_m") or 0
        length = end_m - start_m
        if length >= min_length_m:
            straights.append({"start_m": round(start_m), "end_m": round(end_m), "length_m": round(length)})

    return straights
```

- [ ] **Step 4: Add `_compute_energy_metrics` to f1_data.py**

Add after `_extract_major_straights`:

```python
def _compute_energy_metrics(
    samples: list[dict],
    lico_events: list[dict],
    clip_windows: list[dict],
) -> dict:
    """
    Quantify ERS energy management from inferred lift-and-coast and clipping signals.

    Clipping metrics: how often and how severely the MGU-K runs out.
    Harvest metrics: how aggressively the driver lifts before corners to recover energy.
    """
    # Clipping
    clip_count = len(clip_windows)
    total_clip_distance_m = sum(
        ((c.get("end_distance_m") or 0) - (c.get("start_distance_m") or 0))
        for c in clip_windows
    )
    total_late_drop_kph = sum(
        abs(c.get("late_straight_drop_kph") or 0)
        for c in clip_windows
        if (c.get("late_straight_drop_kph") or 0) < 0
    )

    # Time lost estimate: for each window with a late-straight speed drop,
    # time_lost ≈ (drop_m/s * half_window_m) / v_avg_m/s²
    est_time_lost = 0.0
    for c in clip_windows:
        drop_kph = c.get("late_straight_drop_kph") or 0
        if drop_kph >= 0:
            continue
        half_window_m = ((c.get("end_distance_m") or 0) - (c.get("start_distance_m") or 0)) / 2
        avg_speed_kph = c.get("mid_speed_kph") or 300
        avg_speed_ms = max(avg_speed_kph / 3.6, 1.0)
        drop_ms = abs(drop_kph) / 3.6
        est_time_lost += (drop_ms * half_window_m) / (avg_speed_ms ** 2)

    # Lift-and-coast — merge nearby detection points into zones
    lico_count = len(lico_events)
    harvest_zones: list[dict] = []
    if lico_events:
        zone_start = lico_events[0].get("distance_m") or 0
        zone_end = zone_start
        for ev in lico_events[1:]:
            d = ev.get("distance_m") or 0
            if d - zone_end < 50:
                zone_end = d
            else:
                harvest_zones.append({
                    "start_m": round(zone_start),
                    "end_m": round(zone_end),
                    "length_m": round(zone_end - zone_start),
                })
                zone_start = d
                zone_end = d
        harvest_zones.append({
            "start_m": round(zone_start),
            "end_m": round(zone_end),
            "length_m": round(zone_end - zone_start),
        })
    total_harvest_distance_m = sum(z["length_m"] for z in harvest_zones)

    return {
        "clip_count": clip_count,
        "total_clip_distance_m": round(total_clip_distance_m, 1),
        "total_late_speed_drop_kph": round(total_late_drop_kph, 2),
        "estimated_time_lost_to_clipping_s": round(est_time_lost, 3),
        "lico_count": lico_count,
        "total_harvest_distance_m": round(total_harvest_distance_m, 1),
        "harvest_zones": harvest_zones,
    }
```

- [ ] **Step 5: Add `_analyze_straights_energy` to f1_data.py**

Add after `_compute_energy_metrics`:

```python
def _analyze_straights_energy(
    samples_a: list[dict],
    samples_b: list[dict] | None,
    clip_a: list[dict],
    clip_b: list[dict] | None,
    driver_a: str,
    driver_b: str | None,
) -> list[dict]:
    """
    Per-major-straight comparison: peak speed, end speed, clipping for each driver.
    Straights detected from samples_a. Returns up to 6 straights.
    """
    straights = _extract_major_straights(samples_a)
    results: list[dict] = []

    for straight in straights[:6]:
        start_m, end_m = straight["start_m"], straight["end_m"]
        pts_a = [s for s in samples_a if start_m <= (s.get("distance_m") or -1) <= end_m]
        if not pts_a:
            continue

        speeds_a = [p["speed_kph"] for p in pts_a if p.get("speed_kph")]
        peak_a = max(speeds_a) if speeds_a else None
        end_kph_a = pts_a[-1].get("speed_kph")
        drs_a = any(p.get("drs_open") for p in pts_a)
        clipped_a = any(
            (c.get("start_distance_m") or 0) >= start_m and (c.get("start_distance_m") or 0) <= end_m
            for c in clip_a
        )

        row: dict = {
            "start_m": start_m,
            "length_m": straight["length_m"],
            "drs": drs_a,
            "driver_a": {
                "code": driver_a.upper(),
                "peak_kph": round(peak_a, 1) if peak_a else None,
                "end_kph": round(end_kph_a, 1) if end_kph_a else None,
                "clipped": clipped_a,
            },
        }

        if samples_b:
            pts_b = [s for s in samples_b if start_m <= (s.get("distance_m") or -1) <= end_m]
            if pts_b:
                speeds_b = [p["speed_kph"] for p in pts_b if p.get("speed_kph")]
                peak_b = max(speeds_b) if speeds_b else None
                end_kph_b = pts_b[-1].get("speed_kph")
                clipped_b = any(
                    (c.get("start_distance_m") or 0) >= start_m and (c.get("start_distance_m") or 0) <= end_m
                    for c in (clip_b or [])
                )
                row["driver_b"] = {
                    "code": driver_b.upper() if driver_b else None,
                    "peak_kph": round(peak_b, 1) if peak_b else None,
                    "end_kph": round(end_kph_b, 1) if end_kph_b else None,
                    "clipped": clipped_b,
                }

        results.append(row)

    return results
```

- [ ] **Step 6: Modify `analyze_energy_management` to include speed trace + metrics**

In `analyze_energy_management` in `server/f1_data.py`, make the following changes to BOTH the single-driver path and the comparison path.

**Single-driver path** (around line 1923, after `samples = telemetry["telemetry"]`):

Add after the existing `lico = ...` and `clip = ...` lines:

```python
    metrics_a = _compute_energy_metrics(samples, lico, clip)
    straight_breakdown = _analyze_straights_energy(samples, None, clip, None, driver_a, None)
    trace_a = [
        {
            "distance_m": s["distance_m"],
            "speed_kph": s["speed_kph"],
            "throttle_pct": s.get("throttle_pct"),
            "drs_open": s.get("drs_open"),
        }
        for s in samples[::5]
    ]
```

In the single-driver `return {...}`, add:

```python
        "speed_trace_a": trace_a,
        "speed_trace_b": None,
        "energy_metrics_a": metrics_a,
        "energy_metrics_b": None,
        "straight_breakdown": straight_breakdown,
```

**Comparison path** (around line 1863, after `lico_a`, `lico_b`, `clip_a`, `clip_b` are computed):

Add:

```python
        metrics_a = _compute_energy_metrics(driver_a_samples, lico_a, clip_a)
        metrics_b = _compute_energy_metrics(driver_b_samples, lico_b, clip_b)
        straight_breakdown = _analyze_straights_energy(
            driver_a_samples, driver_b_samples, clip_a, clip_b, driver_a, driver_b
        )
        trace_a = [
            {"distance_m": s["distance_m"], "speed_kph": s["speed_a"],
             "throttle_pct": s.get("throttle_a"), "drs_open": s.get("drs_a")}
            for s in samples[::5]
        ]
        trace_b = [
            {"distance_m": s["distance_m"], "speed_kph": s["speed_b"],
             "throttle_pct": s.get("throttle_b"), "drs_open": s.get("drs_b")}
            for s in samples[::5]
        ]
```

In the comparison `return {...}`, add:

```python
            "speed_trace_a": trace_a,
            "speed_trace_b": trace_b,
            "energy_metrics_a": metrics_a,
            "energy_metrics_b": metrics_b,
            "straight_breakdown": straight_breakdown,
```

- [ ] **Step 7: Run tests to verify they pass**

```bash
cd server && python -m pytest tests/test_f1_data.py::test_compute_energy_metrics_clip_detection tests/test_f1_data.py::test_extract_major_straights_finds_high_speed_sections tests/test_f1_data.py::test_analyze_energy_management_includes_speed_trace -v
```
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add server/f1_data.py server/tests/test_f1_data.py
git commit -m "feat: add energy metrics helpers and extend analyze_energy_management"
```

---

### Task 12: Create `EnergyManagementWidget.jsx`

**Files:**
- Create: `client/src/components/chat-widgets/EnergyManagementWidget.jsx`

Three sections: (1) speed trace with LiCo (amber) and clipping (red) zone overlays, (2) metrics comparison row, (3) per-straight breakdown table.

- [ ] **Step 1: Create the widget file**

```jsx
// client/src/components/chat-widgets/EnergyManagementWidget.jsx
const COLOR_A = 'hsl(var(--primary))'
const COLOR_B = 'hsl(var(--speed))'
const ZONE_LICO = 'hsl(var(--time) / 0.3)'
const ZONE_CLIP = 'hsl(var(--primary) / 0.22)'
const BORDER_LICO = 'hsl(var(--time))'
const BORDER_CLIP = 'hsl(var(--primary))'

const W = 640, H = 140
const PAD = { top: 10, right: 12, bottom: 28, left: 44 }
const IW = W - PAD.left - PAD.right
const IH = H - PAD.top - PAD.bottom

function SpeedPanel({ traceA, traceB, licoA, clipA, driverA, driverB }) {
  if (!traceA?.length) return null

  const all = [...traceA, ...(traceB ?? [])]
  const distances = all.map((p) => p.distance_m)
  const speeds    = all.map((p) => p.speed_kph)
  const minD = Math.min(...distances), maxD = Math.max(...distances)
  const minS = Math.min(...speeds) - 10, maxS = Math.max(...speeds) + 10
  const dSpan = maxD - minD || 1
  const sSpan = maxS - minS || 1

  const toX = (d) => PAD.left + ((d - minD) / dSpan) * IW
  const toY = (s) => PAD.top + IH - ((s - minS) / sSpan) * IH
  const poly = (pts) => pts.map((p) => `${toX(p.distance_m)},${toY(p.speed_kph)}`).join(' ')

  const step = sSpan > 150 ? 50 : sSpan > 80 ? 25 : 20
  const ticks = []
  let t = Math.ceil(minS / step) * step
  while (t <= maxS) { ticks.push(t); t += step }

  return (
    <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} className="block overflow-visible">
      {/* Harvest zones (LiCo) */}
      {(licoA ?? []).map((ev, i) => {
        const cx = toX(ev.distance_m ?? 0)
        return <rect key={i} x={cx - 15} y={PAD.top} width={30} height={IH}
          fill={ZONE_LICO} stroke={BORDER_LICO} strokeWidth={0.5} strokeOpacity={0.4} />
      })}
      {/* Clipping zones */}
      {(clipA ?? []).map((c, i) => {
        const x1 = toX(c.start_distance_m ?? 0)
        const x2 = toX(c.end_distance_m ?? 0)
        return <rect key={i} x={x1} y={PAD.top} width={Math.max(x2 - x1, 4)} height={IH}
          fill={ZONE_CLIP} stroke={BORDER_CLIP} strokeWidth={0.5} strokeOpacity={0.4} />
      })}
      {/* Grid */}
      {ticks.map((s) => (
        <g key={s}>
          <line x1={PAD.left} x2={W - PAD.right} y1={toY(s)} y2={toY(s)}
            stroke="hsl(var(--border))" strokeWidth={0.5} />
          <text x={PAD.left - 4} y={toY(s) + 3.5} textAnchor="end" fontSize={9}
            fill="hsl(var(--muted-foreground))">{s}</text>
        </g>
      ))}
      {/* Traces */}
      <polyline points={poly(traceA)} fill="none" stroke={COLOR_A} strokeWidth={1.5} strokeOpacity={0.9} />
      {traceB?.length > 0 && (
        <polyline points={poly(traceB)} fill="none" stroke={COLOR_B} strokeWidth={1.5} strokeOpacity={0.85} />
      )}
      {/* Driver labels */}
      {driverA && <text x={W - PAD.right} y={PAD.top + 10} textAnchor="end" fontSize={9} fill={COLOR_A} fontWeight="600">{driverA}</text>}
      {driverB && <text x={W - PAD.right} y={PAD.top + 22} textAnchor="end" fontSize={9} fill={COLOR_B} fontWeight="600">{driverB}</text>}
      {/* X label */}
      <text x={PAD.left + IW / 2} y={H - 4} textAnchor="middle" fontSize={9} fill="hsl(var(--muted-foreground))">Distance (m)</text>
      {/* Axes */}
      <line x1={PAD.left} x2={PAD.left} y1={PAD.top} y2={H - PAD.bottom} stroke="hsl(var(--border))" strokeWidth={1} />
      <line x1={PAD.left} x2={W - PAD.right} y1={H - PAD.bottom} y2={H - PAD.bottom} stroke="hsl(var(--border))" strokeWidth={1} />
    </svg>
  )
}

function MetricCell({ label, valueA, valueB, colorA = COLOR_A, colorB = COLOR_B, lowerIsBetter = true }) {
  const aNum = typeof valueA === 'number' ? valueA : null
  const bNum = typeof valueB === 'number' ? valueB : null
  const aWins = aNum !== null && bNum !== null && (lowerIsBetter ? aNum < bNum : aNum > bNum)
  const bWins = aNum !== null && bNum !== null && (lowerIsBetter ? bNum < aNum : bNum > aNum)
  return (
    <div className="bg-background py-3 sm:px-3">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="mt-1 flex gap-3 text-sm font-mono-data font-medium">
        <span style={{ color: aWins ? colorA : 'hsl(var(--foreground))' }}>{valueA ?? '—'}</span>
        {valueB !== undefined && (
          <span style={{ color: bWins ? colorB : 'hsl(var(--muted-foreground))' }}>{valueB ?? '—'}</span>
        )}
      </div>
    </div>
  )
}

export default function EnergyManagementWidget({ widget }) {
  const traceA   = widget.speed_trace_a ?? []
  const traceB   = widget.speed_trace_b
  const mA       = widget.energy_metrics_a ?? {}
  const mB       = widget.energy_metrics_b
  const driverA  = widget.driver_a
  const driverB  = widget.driver_b
  const licoA    = (widget.drivers?.[0]?.likely_lift_and_coast_events ?? []).slice(0, 10)
  const clipA    = (widget.drivers?.[0]?.possible_clipping_windows   ?? []).slice(0, 8)
  const straights = widget.straight_breakdown ?? []

  if (!traceA.length) return null

  return (
    <div className="widget-enter max-w-3xl overflow-hidden border-y border-border/80 py-1">
      {/* Header */}
      <div className="flex items-center justify-between py-3">
        <h4 className="text-sm font-medium text-foreground">{widget.title}</h4>
        <div className="flex gap-3 text-xs text-muted-foreground">
          <span className="flex items-center gap-1">
            <span className="inline-block h-2.5 w-4 rounded-sm opacity-60"
              style={{ background: ZONE_LICO, border: `1px solid ${BORDER_LICO}` }} />
            Lift &amp; coast
          </span>
          <span className="flex items-center gap-1">
            <span className="inline-block h-2.5 w-4 rounded-sm opacity-60"
              style={{ background: ZONE_CLIP, border: `1px solid ${BORDER_CLIP}` }} />
            Clipping
          </span>
        </div>
      </div>
      <p className="mb-2 text-xs text-muted-foreground">
        Speed trace with inferred ERS zones. Confidence: <span className="text-foreground">{widget.confidence ?? '—'}</span>.
        ERS state not directly measured — zones inferred from throttle/speed patterns.
      </p>

      {/* Speed trace */}
      <div className="overflow-x-auto">
        <SpeedPanel
          traceA={traceA} traceB={traceB}
          licoA={licoA} clipA={clipA}
          driverA={driverA} driverB={driverB}
        />
      </div>

      {/* Metrics comparison */}
      <div className="mt-1 grid gap-px bg-border/70 border-t border-border/70 sm:grid-cols-3">
        {driverA && (
          <div className="bg-background py-2 text-xs font-medium" style={{ color: COLOR_A }}>
            {driverA}{driverB ? <span style={{ color: COLOR_B }}> / {driverB}</span> : ''}
          </div>
        )}
      </div>
      <div className="grid gap-px bg-border/70 sm:grid-cols-3">
        <MetricCell
          label="Clips" valueA={mA.clip_count} valueB={mB?.clip_count} lowerIsBetter />
        <MetricCell
          label="Est. time lost (s)"
          valueA={mA.estimated_time_lost_to_clipping_s?.toFixed(3)}
          valueB={mB?.estimated_time_lost_to_clipping_s?.toFixed(3)}
          lowerIsBetter />
        <MetricCell
          label="Speed drop (kph)"
          valueA={mA.total_late_speed_drop_kph?.toFixed(1)}
          valueB={mB?.total_late_speed_drop_kph?.toFixed(1)}
          lowerIsBetter />
        <MetricCell
          label="Lifts (harvest)"
          valueA={mA.lico_count} valueB={mB?.lico_count}
          lowerIsBetter={false} />
        <MetricCell
          label="Harvest dist (m)"
          valueA={mA.total_harvest_distance_m?.toFixed(0)}
          valueB={mB?.total_harvest_distance_m?.toFixed(0)}
          lowerIsBetter={false} />
        <MetricCell
          label="Clip dist (m)"
          valueA={mA.total_clip_distance_m?.toFixed(0)}
          valueB={mB?.total_clip_distance_m?.toFixed(0)}
          lowerIsBetter />
      </div>

      {/* Per-straight breakdown */}
      {straights.length > 0 && (
        <div className="mt-1 border-t border-border/70">
          <div className="py-2 text-xs font-medium text-foreground">Straight-by-straight</div>
          <div className="overflow-x-auto">
            <table className="w-full border-collapse text-xs">
              <thead>
                <tr className="border-b border-border/70 text-muted-foreground">
                  <th className="py-1.5 pr-3 text-left">At (m)</th>
                  <th className="py-1.5 pr-3 text-left">Len</th>
                  <th className="py-1.5 pr-3 text-right">DRS</th>
                  <th className="py-1.5 pr-3 text-right" style={{ color: COLOR_A }}>{driverA} peak</th>
                  <th className="py-1.5 pr-3 text-right" style={{ color: COLOR_A }}>Clip</th>
                  {driverB && <>
                    <th className="py-1.5 pr-3 text-right" style={{ color: COLOR_B }}>{driverB} peak</th>
                    <th className="py-1.5 text-right" style={{ color: COLOR_B }}>Clip</th>
                  </>}
                </tr>
              </thead>
              <tbody>
                {straights.map((s, i) => (
                  <tr key={i} className="border-b border-border/50 last:border-0">
                    <td className="py-1.5 pr-3 font-mono-data text-muted-foreground">{s.start_m}</td>
                    <td className="py-1.5 pr-3 font-mono-data text-muted-foreground">{s.length_m}m</td>
                    <td className="py-1.5 pr-3 text-right text-muted-foreground">{s.drs ? 'Yes' : '—'}</td>
                    <td className="py-1.5 pr-3 text-right font-mono-data text-foreground">
                      {s.driver_a?.peak_kph ?? '—'}
                    </td>
                    <td className="py-1.5 pr-3 text-right" style={{ color: s.driver_a?.clipped ? 'hsl(var(--primary))' : 'hsl(var(--muted-foreground))' }}>
                      {s.driver_a?.clipped ? '●' : '○'}
                    </td>
                    {driverB && <>
                      <td className="py-1.5 pr-3 text-right font-mono-data text-foreground">
                        {s.driver_b?.peak_kph ?? '—'}
                      </td>
                      <td className="py-1.5 text-right" style={{ color: s.driver_b?.clipped ? 'hsl(var(--primary))' : 'hsl(var(--muted-foreground))' }}>
                        {s.driver_b?.clipped ? '●' : '○'}
                      </td>
                    </>}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Inference summary */}
      {widget.inference_summary?.length > 0 && (
        <div className="border-t border-border/60 py-3">
          {widget.inference_summary.map((line, i) => (
            <p key={i} className="text-sm leading-6 text-muted-foreground">{line}</p>
          ))}
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 2: Commit**

```bash
git add client/src/components/chat-widgets/EnergyManagementWidget.jsx
git commit -m "feat: add EnergyManagementWidget with metrics and straight breakdown"
```

---

### Task 13: Wire EnergyManagementWidget into chat.py and AnswerRenderer.jsx

**Files:**
- Modify: `server/chat.py`
- Modify: `client/src/components/AnswerRenderer.jsx`

- [ ] **Step 1: Add `_make_energy_management_widget` to chat.py**

Add after `_make_deg_trend_chart_widget`:

```python
def _make_energy_management_widget(result: dict) -> dict:
    drivers = result.get("drivers") or []
    driver_a = drivers[0].get("driver") if drivers else None
    driver_b = drivers[1].get("driver") if len(drivers) > 1 else None
    label = driver_a or "Energy"
    if driver_b:
        label = f"{driver_a} vs {driver_b}"
    return {
        "type": "energy_management",
        "title": f"{label} — {result.get('event')} energy management",
        "driver_a": driver_a,
        "driver_b": driver_b,
        "event": result.get("event"),
        "session": result.get("session"),
        "drivers": drivers,
        "speed_trace_a": result.get("speed_trace_a") or [],
        "speed_trace_b": result.get("speed_trace_b"),
        "energy_metrics_a": result.get("energy_metrics_a") or {},
        "energy_metrics_b": result.get("energy_metrics_b"),
        "straight_breakdown": result.get("straight_breakdown") or [],
        "confidence": result.get("confidence"),
        "inference_summary": result.get("inference_summary") or [],
    }
```

- [ ] **Step 2: Wire into `_widgets_from_analysis_evidence`**

In the `for item in evidence:` loop:

```python
        elif tool == "analyze_energy_management":
            w = _make_energy_management_widget(item["result"])
            if w.get("speed_trace_a"):
                widgets.append(w)
```

- [ ] **Step 3: Update `ANSWER_WRITER_SYSTEM_PROMPT` for energy responses**

After the circuit profile section, add:

```
## Energy management responses

When `analyze_energy_management` results are present, a widget already shows the speed trace with annotated lift-and-coast and clipping zones, the efficiency metrics, and the per-straight breakdown. Do NOT re-describe zone positions or list straight-by-straight numbers — the widget has all of that.

Write 2–3 sentences:
1. Who has the better energy balance — fewer clips or more efficient harvesting — and what the estimated time cost shows.
2. What the straight breakdown reveals: whether one driver is losing time specifically on DRS straights vs shorter sections.
3. Embed the confidence caveat naturally ("this is inferred from speed/throttle patterns — ERS state isn't directly measured").

Never say "lift_and_coast_events" or "clipping_windows". Use natural language: "runs out of deployment on the main straight", "lifts early before the chicane to harvest", "costs him roughly X seconds across the lap".
```

- [ ] **Step 4: Wire into AnswerRenderer.jsx**

Add import:

```jsx
import EnergyManagementWidget from './chat-widgets/EnergyManagementWidget.jsx'
```

Add to `WidgetRenderer`:

```jsx
  if (widget.type === 'energy_management') {
    return <EnergyManagementWidget widget={widget} />
  }
```

- [ ] **Step 5: Run all server tests**

```bash
cd server && python -m pytest tests/ -v
```
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add server/chat.py client/src/components/AnswerRenderer.jsx
git commit -m "feat: wire EnergyManagementWidget end-to-end"
```

---

## Self-review

**Spec coverage:**
- ✅ Feature 1 — pit stop tool + strategy timeline widget: Tasks 1–5
- ✅ Feature 2 — degradation scatter chart widget: Tasks 6–8
- ✅ Feature 3 — weather/pace diagnostic tool (reactive, no widget): Tasks 9–10
- ✅ Feature 4 — energy management widget with clip/harvest metrics + straight breakdown: Tasks 11–13

**Placeholder scan:** None. All code blocks are complete and self-contained.

**Type consistency:**
- `scatter_data[].{tyre_age, lap_time_s, lap_number}` added in Task 6, consumed in Tasks 7 and 8 — consistent.
- `energy_metrics_a.{clip_count, estimated_time_lost_to_clipping_s, total_late_speed_drop_kph, lico_count, total_harvest_distance_m}` added in Task 11, consumed in Tasks 12 and 13 — consistent.
- `straight_breakdown[].{start_m, length_m, drs, driver_a.{code,peak_kph,end_kph,clipped}, driver_b?}` added in Task 11, consumed in Task 12 — consistent.
- `widget.type` strings: `pit_stop_strategy`, `deg_trend_chart`, `energy_management` — each appears in exactly one widget file, one builder function, and one `AnswerRenderer` branch.
- `pit_stops[].duration_s` from Task 2 matches `p.duration_s` in Task 4 — consistent.
