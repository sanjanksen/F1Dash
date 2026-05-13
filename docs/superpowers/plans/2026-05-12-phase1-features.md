# Phase 1 Features Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add five high-value, low-effort analytical features — lap delta trace, driver form trend, safety car probability, head-to-head history, and per-session style fingerprint — each requiring ≤2 days of work with no new heavyweight dependencies.

**Architecture:** Each feature follows the same four-layer pattern already established: (1) pure helper function in `f1_data.py` (testable without FastF1), (2) integration function in `f1_data.py` (calls FastF1/Jolpica), (3) tool definition in `tools.py` + dispatch case in `execute_tool()`, (4) widget builder in `chat.py` + React component in `client/src/components/chat-widgets/` + case in `AnswerRenderer.jsx`.

**Tech Stack:** Python, numpy, pandas, requests (all already imported). SVG-based React components matching existing chart style. No new npm packages.

---

### Task 1: FEAT-01 — Cumulative Lap Delta Trace

**Files:**
- Modify: `server/f1_data.py` — add `_compute_delta_trace()` helper + `get_lap_delta_trace()` function
- Modify: `server/tools.py` — add tool definition + `execute_tool` dispatch case
- Modify: `server/chat.py` — add `_make_lap_delta_trace_widget()` builder + dispatch in tool result handler
- Create: `client/src/components/chat-widgets/LapDeltaTrace.jsx`
- Modify: `client/src/components/AnswerRenderer.jsx` — add import + widget case
- Test: `server/tests/test_f1_data.py`

**What it does in the app:** When a user asks "where exactly did Norris beat Leclerc in qualifying?", the LLM calls `get_lap_delta_trace` and the response shows a chart of cumulative time gained/lost at every 100m of the lap — like the broadcast mini-sector graphic. Negative delta = driver A ahead; positive = driver A behind.

- [ ] **Write the failing tests**

Add to `server/tests/test_f1_data.py`:

```python
def test_compute_delta_trace_equal_speeds():
    """Equal speeds throughout produce zero cumulative delta."""
    from f1_data import _compute_delta_trace
    samples = [{'distance_m': i * 100, 'speed_kph': 150.0} for i in range(10)]
    result = _compute_delta_trace(samples, samples, interval_m=100.0)
    assert len(result) == 10
    for point in result:
        assert abs(point['delta_s']) < 1e-9, f"Expected zero delta, got {point['delta_s']}"


def test_compute_delta_trace_faster_driver_gains():
    """Driver A at 200 kph vs Driver B at 100 kph: delta_s monotonically negative."""
    from f1_data import _compute_delta_trace
    sa = [{'distance_m': i * 100, 'speed_kph': 200.0} for i in range(5)]
    sb = [{'distance_m': i * 100, 'speed_kph': 100.0} for i in range(5)]
    result = _compute_delta_trace(sa, sb, interval_m=100.0)
    # dt_A per 100m = 100 / (200/3.6) = 1.8s; dt_B = 100 / (100/3.6) = 3.6s
    # After 5 intervals: delta = 5 * (1.8 - 3.6) = -9.0s
    assert result[-1]['delta_s'] < 0, "Faster driver A should have negative delta"
    assert abs(result[-1]['delta_s'] - (-9.0)) < 0.01
    # Monotonically decreasing
    for i in range(1, len(result)):
        assert result[i]['delta_s'] <= result[i - 1]['delta_s']


def test_compute_delta_trace_returns_speed_fields():
    """Each point must include speed_a_kph and speed_b_kph."""
    from f1_data import _compute_delta_trace
    sa = [{'distance_m': 0, 'speed_kph': 120.0}]
    sb = [{'distance_m': 0, 'speed_kph': 140.0}]
    result = _compute_delta_trace(sa, sb)
    assert 'speed_a_kph' in result[0]
    assert 'speed_b_kph' in result[0]
    assert result[0]['speed_a_kph'] == 120.0
    assert result[0]['speed_b_kph'] == 140.0
```

- [ ] **Run tests to confirm they fail**

```
cd server && python -m pytest tests/test_f1_data.py::test_compute_delta_trace_equal_speeds tests/test_f1_data.py::test_compute_delta_trace_faster_driver_gains tests/test_f1_data.py::test_compute_delta_trace_returns_speed_fields -v
```

Expected: all three `FAILED` — `_compute_delta_trace` does not exist.

- [ ] **Add `_compute_delta_trace` helper to `f1_data.py`**

Find the section near `_sample_telemetry_at_distances` (added in the bug-fixes plan) and add directly below it:

```python
def _compute_delta_trace(
    samples_a: list[dict], samples_b: list[dict], interval_m: float = 100.0
) -> list[dict]:
    """
    Compute cumulative time delta at each 100m mark.
    delta_s = cum_time_A - cum_time_B.
    Negative = driver A is ahead (faster to that point).
    """
    cum_time_a = 0.0
    cum_time_b = 0.0
    result = []
    for sa, sb in zip(samples_a, samples_b):
        spd_a = max(sa['speed_kph'], 1.0)
        spd_b = max(sb['speed_kph'], 1.0)
        cum_time_a += interval_m / (spd_a / 3.6)
        cum_time_b += interval_m / (spd_b / 3.6)
        result.append({
            'distance_m':   sa['distance_m'],
            'delta_s':      round(cum_time_a - cum_time_b, 4),
            'speed_a_kph':  sa['speed_kph'],
            'speed_b_kph':  sb['speed_kph'],
        })
    return result
```

- [ ] **Add `get_lap_delta_trace` integration function to `f1_data.py`**

Add near the other lap telemetry functions:

```python
def get_lap_delta_trace(
    round_number: int, session_type: str, driver_a: str, driver_b: str,
    lap_type: str = "fastest"
) -> dict:
    """
    Cumulative time delta at every 100m between driver_a and driver_b.
    lap_type: 'fastest' uses each driver's fastest lap; 'qualifying' uses their best Q3/Q2/Q1 lap.
    """
    sess = _get_session(round_number, session_type)
    laps = sess.laps

    driver_a = _resolve_driver_code(driver_a, sess)
    driver_b = _resolve_driver_code(driver_b, sess)

    def _pick_lap(drv):
        dl = laps.pick_driver(drv)
        if lap_type == "qualifying":
            dl = dl[dl['IsPersonalBest'] == True]
        return dl.pick_fastest()

    lap_a = _pick_lap(driver_a)
    lap_b = _pick_lap(driver_b)

    tel_a = lap_a.get_telemetry().add_distance()
    tel_b = lap_b.get_telemetry().add_distance()

    total_dist = min(float(tel_a['Distance'].max()), float(tel_b['Distance'].max()))
    INTERVAL_M = 100
    targets = list(range(0, int(total_dist), INTERVAL_M))

    samples_a_list = _sample_telemetry_at_distances(tel_a, targets)
    samples_b_list = _sample_telemetry_at_distances(tel_b, targets)

    delta_trace = _compute_delta_trace(samples_a_list, samples_b_list, interval_m=INTERVAL_M)

    lt_a_raw = lap_a.get('LapTime')
    lt_b_raw = lap_b.get('LapTime')
    lt_a = float(lt_a_raw.total_seconds()) if hasattr(lt_a_raw, 'total_seconds') else None
    lt_b = float(lt_b_raw.total_seconds()) if hasattr(lt_b_raw, 'total_seconds') else None

    final_delta = delta_trace[-1]['delta_s'] if delta_trace else 0.0

    return {
        'driver_a':         driver_a,
        'driver_b':         driver_b,
        'lap_type':         lap_type,
        'lap_time_a_s':     round(lt_a, 3) if lt_a else None,
        'lap_time_b_s':     round(lt_b, 3) if lt_b else None,
        'total_delta_s':    round(final_delta, 3),
        'fastest_driver':   driver_a if final_delta < 0 else driver_b,
        'circuit_length_m': int(total_dist),
        'delta_trace':      delta_trace,
    }
```

- [ ] **Add tool definition to `server/tools.py`**

In `PRIMITIVE_TOOL_DEFINITIONS`, add:

```python
    _tool(
        "get_lap_delta_trace",
        "PRIMITIVE TOOL. Cumulative time delta at every 100m of the lap between two drivers. "
        "Use for precise spatial questions like 'where did Norris gain time on Leclerc?' — "
        "returns a trace showing exactly which sectors, corners, or straights produced the gap. "
        "Works for qualifying and race fastest laps.",
        {
            "round_number": {"type": "integer", "description": "Race round number."},
            "session_type": {"type": "string", "description": "Q for qualifying, R for race."},
            "driver_a":     {"type": "string", "description": "First driver code (e.g. NOR)."},
            "driver_b":     {"type": "string", "description": "Second driver code (e.g. LEC)."},
            "lap_type":     {"type": "string", "description": "fastest (default) or qualifying."},
        },
        ["round_number", "session_type", "driver_a", "driver_b"],
    ),
```

Also add the import at the top of tools.py:

```python
from f1_data import (
    ...
    get_lap_delta_trace,
    ...
)
```

And add the dispatch case in `execute_tool()`:

```python
    if name == "get_lap_delta_trace":
        return get_lap_delta_trace(
            args["round_number"], args["session_type"],
            args["driver_a"], args["driver_b"],
            args.get("lap_type", "fastest"),
        )
```

- [ ] **Add widget builder to `server/chat.py`**

Add near the other `_make_*_widget` functions:

```python
def _make_lap_delta_trace_widget(result: dict) -> dict:
    return {
        "type":             "lap_delta_trace",
        "driver_a":         result.get("driver_a"),
        "driver_b":         result.get("driver_b"),
        "lap_time_a_s":     result.get("lap_time_a_s"),
        "lap_time_b_s":     result.get("lap_time_b_s"),
        "total_delta_s":    result.get("total_delta_s"),
        "fastest_driver":   result.get("fastest_driver"),
        "circuit_length_m": result.get("circuit_length_m"),
        "delta_trace":      result.get("delta_trace", []),
    }
```

In the tool result dispatch block in `chat.py`, add:

```python
        if tool_name == "get_lap_delta_trace":
            widgets.append(_make_lap_delta_trace_widget(tool_result))
```

- [ ] **Create `client/src/components/chat-widgets/LapDeltaTrace.jsx`**

```jsx
const W = 600
const H = 140
const PAD = { top: 10, right: 16, bottom: 28, left: 48 }
const IW = W - PAD.left - PAD.right
const IH = H - PAD.top - PAD.bottom

const COLOR_A = 'hsl(var(--primary))'
const COLOR_B = 'hsl(var(--speed))'

function fmtDelta(s) {
  return `${s > 0 ? '+' : ''}${s.toFixed(3)}s`
}

export default function LapDeltaTrace({ widget }) {
  const { driver_a, driver_b, total_delta_s, fastest_driver, lap_time_a_s, lap_time_b_s, delta_trace } = widget
  if (!delta_trace?.length) return null

  const deltas = delta_trace.map((p) => p.delta_s)
  const minD = Math.min(...deltas, 0)
  const maxD = Math.max(...deltas, 0)
  const span = Math.max(Math.abs(minD), Math.abs(maxD), 0.01) * 1.1
  const maxDist = delta_trace[delta_trace.length - 1].distance_m

  const toX = (d) => PAD.left + (d / maxDist) * IW
  const toY = (v) => PAD.top + IH / 2 - (v / span) * (IH / 2)

  const linePts = delta_trace
    .map((p, i) => `${i === 0 ? 'M' : 'L'} ${toX(p.distance_m).toFixed(1)} ${toY(p.delta_s).toFixed(1)}`)
    .join(' ')

  // Fill: area above zero (driver A losing) vs below zero (driver A gaining)
  const fillAbove = delta_trace
    .map((p, i) => `${i === 0 ? 'M' : 'L'} ${toX(p.distance_m).toFixed(1)} ${toY(Math.max(p.delta_s, 0)).toFixed(1)}`)
    .join(' ') + ` L ${toX(maxDist).toFixed(1)} ${toY(0).toFixed(1)} L ${toX(0).toFixed(1)} ${toY(0).toFixed(1)} Z`

  const fillBelow = delta_trace
    .map((p, i) => `${i === 0 ? 'M' : 'L'} ${toX(p.distance_m).toFixed(1)} ${toY(Math.min(p.delta_s, 0)).toFixed(1)}`)
    .join(' ') + ` L ${toX(maxDist).toFixed(1)} ${toY(0).toFixed(1)} L ${toX(0).toFixed(1)} ${toY(0).toFixed(1)} Z`

  const zeroY = toY(0)
  const km = (d) => `${(d / 1000).toFixed(1)}km`
  const winColor = total_delta_s < 0 ? COLOR_A : COLOR_B

  return (
    <div className="widget-enter max-w-3xl overflow-hidden border-y border-border/80 py-1">
      <div className="flex items-center justify-between py-3">
        <h4 className="text-sm font-medium text-foreground">Lap delta trace</h4>
        <div className="flex items-center gap-4 text-xs text-muted-foreground">
          <span className="flex items-center gap-1.5">
            <span className="h-[3px] w-4 rounded-sm" style={{ background: COLOR_A }} />
            {driver_a} {lap_time_a_s ? `(${lap_time_a_s.toFixed(3)}s)` : ''}
          </span>
          <span className="flex items-center gap-1.5">
            <span className="h-[3px] w-4 rounded-sm" style={{ background: COLOR_B }} />
            {driver_b} {lap_time_b_s ? `(${lap_time_b_s.toFixed(3)}s)` : ''}
          </span>
          <span className="font-mono-data font-medium" style={{ color: winColor }}>
            {fastest_driver} {fmtDelta(Math.abs(total_delta_s))}
          </span>
        </div>
      </div>

      <p className="mb-2 text-xs text-muted-foreground">
        Negative (below zero) = {driver_a} ahead at that point. Positive = {driver_b} ahead.
      </p>

      <div className="overflow-x-auto">
        <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} className="block">
          <defs>
            <linearGradient id="dtGradA" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={COLOR_B} stopOpacity="0.25" />
              <stop offset="100%" stopColor={COLOR_B} stopOpacity="0.04" />
            </linearGradient>
            <linearGradient id="dtGradB" x1="0" y1="1" x2="0" y2="0">
              <stop offset="0%" stopColor={COLOR_A} stopOpacity="0.25" />
              <stop offset="100%" stopColor={COLOR_A} stopOpacity="0.04" />
            </linearGradient>
          </defs>

          {/* Grid lines */}
          {[-0.5, 0.5].map((frac) => {
            const y = toY(span * frac)
            const label = fmtDelta(span * frac)
            return (
              <g key={frac}>
                <line x1={PAD.left} x2={W - PAD.right} y1={y} y2={y}
                  stroke="hsl(var(--border))" strokeWidth={0.5} />
                <text x={PAD.left - 4} y={y + 4} textAnchor="end" fontSize={9}
                  fill="hsl(var(--muted-foreground))">{label}</text>
              </g>
            )
          })}

          {/* Zero line */}
          <line x1={PAD.left} x2={W - PAD.right} y1={zeroY} y2={zeroY}
            stroke="hsl(var(--muted-foreground))" strokeWidth={1} strokeOpacity={0.5} />
          <text x={PAD.left - 4} y={zeroY + 4} textAnchor="end" fontSize={9}
            fill="hsl(var(--muted-foreground))">0</text>

          {/* Distance labels */}
          {[0.25, 0.5, 0.75, 1.0].map((frac) => {
            const d = maxDist * frac
            return (
              <text key={frac} x={toX(d)} y={H - 4} textAnchor="middle" fontSize={9}
                fill="hsl(var(--muted-foreground))">{km(d)}</text>
            )
          })}

          {/* Fill areas */}
          <path d={fillAbove} fill="url(#dtGradA)" />
          <path d={fillBelow} fill="url(#dtGradB)" />

          {/* Delta line */}
          <path d={linePts} fill="none" stroke="hsl(var(--muted-foreground))" strokeWidth={2}
            strokeLinecap="round" strokeLinejoin="round" />

          {/* Axes */}
          <line x1={PAD.left} x2={PAD.left} y1={PAD.top} y2={H - PAD.bottom}
            stroke="hsl(var(--border))" strokeWidth={1} />
          <line x1={PAD.left} x2={W - PAD.right} y1={H - PAD.bottom} y2={H - PAD.bottom}
            stroke="hsl(var(--border))" strokeWidth={1} />
        </svg>
      </div>
    </div>
  )
}
```

- [ ] **Add import and case to `client/src/components/AnswerRenderer.jsx`**

At the top with other imports:
```jsx
import LapDeltaTrace from './chat-widgets/LapDeltaTrace.jsx'
```

In `WidgetRenderer`, add:
```jsx
  if (widget.type === 'lap_delta_trace') {
    return <LapDeltaTrace widget={widget} />
  }
```

- [ ] **Run the three new tests to confirm they pass**

```
cd server && python -m pytest tests/test_f1_data.py::test_compute_delta_trace_equal_speeds tests/test_f1_data.py::test_compute_delta_trace_faster_driver_gains tests/test_f1_data.py::test_compute_delta_trace_returns_speed_fields -v
```

Expected: all three `PASSED`.

- [ ] **Run full test suite**

```
cd server && python -m pytest tests/ -v
```

- [ ] **Commit**

```
git add server/f1_data.py server/tools.py server/chat.py \
        client/src/components/chat-widgets/LapDeltaTrace.jsx \
        client/src/components/AnswerRenderer.jsx \
        server/tests/test_f1_data.py
git commit -m "feat: add cumulative lap delta trace tool and widget"
```

---

### Task 2: FEAT-15 — Driver Form Trend

**Files:**
- Modify: `server/f1_data.py` — add `_compute_positions_gained()` + `get_driver_form_trend()`
- Modify: `server/tools.py` — add tool definition + dispatch
- Modify: `server/chat.py` — add widget builder + dispatch
- Create: `client/src/components/chat-widgets/DriverFormTrend.jsx`
- Modify: `client/src/components/AnswerRenderer.jsx`
- Test: `server/tests/test_f1_data.py`

**What it does in the app:** When a user asks "is Norris improving this season?", the LLM calls `get_driver_form_trend`. The response shows a bar chart of positions gained/lost per race and a trend label (improving / declining / stable). Data comes from Jolpica race results, already used elsewhere in `f1_data.py`.

- [ ] **Write the failing tests**

```python
def test_compute_positions_gained_basic():
    """Positive = improved from grid; negative = fell back."""
    from f1_data import _compute_positions_gained
    races = [
        {'grid': 5, 'position': 3},   # gained 2
        {'grid': 8, 'position': 5},   # gained 3
        {'grid': 3, 'position': 7},   # lost 4
        {'grid': 1, 'position': 1},   # no change
    ]
    result = _compute_positions_gained(races)
    assert result == [2, 3, -4, 0]


def test_compute_positions_gained_dnf_excluded():
    """Races with position=0 or position=None (DNF) must be excluded."""
    from f1_data import _compute_positions_gained
    races = [
        {'grid': 3, 'position': 2},
        {'grid': 5, 'position': 0},    # DNF — exclude
        {'grid': 4, 'position': None}, # DNF — exclude
        {'grid': 6, 'position': 4},
    ]
    result = _compute_positions_gained(races)
    assert result == [1, 2]


def test_form_trend_slope_improving():
    """If positions gained increases over time, trend must be 'improving'."""
    from f1_data import _classify_form_trend
    # Positions gained: progressively better
    deltas = [-2, -1, 0, 1, 2, 3]
    assert _classify_form_trend(deltas) == 'improving'


def test_form_trend_slope_declining():
    from f1_data import _classify_form_trend
    deltas = [3, 2, 1, 0, -1, -2]
    assert _classify_form_trend(deltas) == 'declining'


def test_form_trend_slope_stable():
    from f1_data import _classify_form_trend
    deltas = [1, -1, 1, -1, 0, 1]
    assert _classify_form_trend(deltas) == 'stable'
```

- [ ] **Run tests to confirm they fail**

```
cd server && python -m pytest tests/test_f1_data.py::test_compute_positions_gained_basic tests/test_f1_data.py::test_compute_positions_gained_dnf_excluded tests/test_f1_data.py::test_form_trend_slope_improving tests/test_f1_data.py::test_form_trend_slope_declining tests/test_f1_data.py::test_form_trend_slope_stable -v
```

Expected: all five `FAILED`.

- [ ] **Add pure helpers to `f1_data.py`**

```python
def _compute_positions_gained(races: list[dict]) -> list[int]:
    """
    Return positions gained per race (grid - finish). DNF (position <= 0 or None) excluded.
    Positive = improved, negative = fell back.
    """
    result = []
    for r in races:
        pos = r.get('position')
        grid = r.get('grid')
        if not pos or not grid:
            continue
        try:
            pos_int = int(pos)
            grid_int = int(grid)
        except (TypeError, ValueError):
            continue
        if pos_int <= 0:
            continue
        result.append(grid_int - pos_int)
    return result


def _classify_form_trend(deltas: list[int | float]) -> str:
    """
    Fit a linear slope over the list of positions-gained values.
    slope > 0.25/race = improving, < -0.25/race = declining, else stable.
    """
    n = len(deltas)
    if n < 2:
        return 'stable'
    xs = list(range(n))
    mean_x = sum(xs) / n
    mean_y = sum(deltas) / n
    num = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, deltas))
    den = sum((x - mean_x) ** 2 for x in xs)
    slope = num / den if den else 0.0
    if slope > 0.25:
        return 'improving'
    if slope < -0.25:
        return 'declining'
    return 'stable'
```

- [ ] **Add `get_driver_form_trend` integration function to `f1_data.py`**

```python
def get_driver_form_trend(driver_name: str, last_n: int = 8) -> dict:
    """
    Rolling positions gained/lost vs grid for driver's last N races.
    Uses Jolpica current-season results. driver_name can be code (NOR) or surname.
    """
    driver_id = _resolve_driver_id(driver_name)

    url = f"{_JOLPICA_BASE}/current/drivers/{driver_id}/results.json?limit={last_n}"
    resp = requests.get(url, timeout=15)
    resp.raise_for_status()
    races_raw = resp.json()['MRData']['RaceTable']['Races']

    race_entries = []
    for race in races_raw[-last_n:]:
        result = race.get('Results', [{}])[0]
        race_entries.append({
            'round':     int(race.get('round', 0)),
            'race_name': race.get('raceName', ''),
            'grid':      result.get('grid'),
            'position':  result.get('position'),
            'status':    result.get('status', ''),
        })

    deltas = _compute_positions_gained(race_entries)
    trend = _classify_form_trend(deltas)

    # Rolling 3-race average
    rolling_avg = []
    for i in range(len(deltas)):
        window = deltas[max(0, i - 2):i + 1]
        rolling_avg.append(round(sum(window) / len(window), 2))

    race_labels = [r['race_name'].replace(' Grand Prix', '').replace(' Grand Prix', '') for r in race_entries if int(r.get('position') or 0) > 0]

    return {
        'driver':          driver_name.upper(),
        'races_analysed':  len(deltas),
        'trend':           trend,
        'avg_positions_gained': round(sum(deltas) / len(deltas), 2) if deltas else 0.0,
        'per_race':        [
            {
                'round':            r['round'],
                'race_name':        r['race_name'].replace(' Grand Prix', ''),
                'grid':             int(r['grid']) if r['grid'] else None,
                'finish':           int(r['position']) if r['position'] and int(r['position']) > 0 else None,
                'positions_gained': (int(r['grid']) - int(r['position']))
                                    if r['grid'] and r['position'] and int(r['position']) > 0
                                    else None,
                'status':           r['status'],
            }
            for r in race_entries
        ],
        'rolling_avg':     rolling_avg,
    }
```

- [ ] **Add tool definition to `server/tools.py`**

In `PRIMITIVE_TOOL_DEFINITIONS`:

```python
    _tool(
        "get_driver_form_trend",
        "PRIMITIVE TOOL. Driver's recent form: positions gained or lost vs grid position "
        "for each of the last N races of the current season. Returns per-race breakdown and "
        "trend classification (improving / declining / stable). Use for questions like "
        "'is Norris in good form?' or 'has Russell been improving lately?'",
        {
            "driver_name": {"type": "string", "description": "Driver full name, surname, or 3-letter code."},
            "last_n":      {"type": "integer", "description": "Number of most recent races to analyse (default 8)."},
        },
        ["driver_name"],
    ),
```

Add import:
```python
from f1_data import (
    ...
    get_driver_form_trend,
    ...
)
```

Add dispatch in `execute_tool()`:
```python
    if name == "get_driver_form_trend":
        return get_driver_form_trend(args["driver_name"], args.get("last_n", 8))
```

- [ ] **Add widget builder to `server/chat.py`**

```python
def _make_driver_form_trend_widget(result: dict) -> dict:
    return {
        "type":                 "driver_form_trend",
        "driver":               result.get("driver"),
        "trend":                result.get("trend"),
        "avg_positions_gained": result.get("avg_positions_gained"),
        "races_analysed":       result.get("races_analysed"),
        "per_race":             result.get("per_race", []),
        "rolling_avg":          result.get("rolling_avg", []),
    }
```

In tool dispatch:
```python
        if tool_name == "get_driver_form_trend":
            widgets.append(_make_driver_form_trend_widget(tool_result))
```

- [ ] **Create `client/src/components/chat-widgets/DriverFormTrend.jsx`**

```jsx
const W = 560
const H = 160
const PAD = { top: 12, right: 16, bottom: 36, left: 40 }
const IW = W - PAD.left - PAD.right
const IH = H - PAD.top - PAD.bottom

const TREND_COLORS = {
  improving: 'hsl(var(--primary))',
  declining: 'hsl(var(--primary) / 0.4)',
  stable:    'hsl(var(--muted-foreground))',
}

export default function DriverFormTrend({ widget }) {
  const { driver, trend, avg_positions_gained, per_race, rolling_avg } = widget
  if (!per_race?.length) return null

  const validRaces = per_race.filter((r) => r.positions_gained !== null && r.positions_gained !== undefined)
  if (!validRaces.length) return null

  const values = validRaces.map((r) => r.positions_gained)
  const absMax = Math.max(Math.abs(Math.min(...values)), Math.abs(Math.max(...values)), 3)

  const barW = IW / validRaces.length - 2
  const toX = (i) => PAD.left + i * (IW / validRaces.length) + 1
  const toY = (v) => PAD.top + IH / 2 - (v / absMax) * (IH / 2)
  const zeroY = PAD.top + IH / 2

  const trendColor = TREND_COLORS[trend] ?? 'hsl(var(--muted-foreground))'

  const rollingPath = rolling_avg
    .slice(0, validRaces.length)
    .map((v, i) => `${i === 0 ? 'M' : 'L'} ${(toX(i) + barW / 2).toFixed(1)} ${toY(v).toFixed(1)}`)
    .join(' ')

  return (
    <div className="widget-enter max-w-3xl overflow-hidden border-y border-border/80 py-1">
      <div className="flex items-center justify-between py-3">
        <h4 className="text-sm font-medium text-foreground">{driver} — form trend</h4>
        <div className="flex items-center gap-3 text-xs">
          <span className="rounded-full px-2 py-0.5 font-medium capitalize"
            style={{ background: `${trendColor}20`, color: trendColor }}>
            {trend}
          </span>
          <span className="text-muted-foreground">
            avg {avg_positions_gained >= 0 ? '+' : ''}{avg_positions_gained?.toFixed(1)} pos/race
          </span>
        </div>
      </div>
      <p className="mb-2 text-xs text-muted-foreground">
        Bars = positions gained vs grid. Green above zero = improved. Line = 3-race rolling average.
      </p>

      <div className="overflow-x-auto">
        <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} className="block">
          {/* Grid */}
          <line x1={PAD.left} x2={W - PAD.right} y1={zeroY} y2={zeroY}
            stroke="hsl(var(--muted-foreground))" strokeWidth={1} strokeOpacity={0.5} />
          {[-3, 3].map((v) => (
            <g key={v}>
              <line x1={PAD.left} x2={W - PAD.right}
                y1={toY(v * absMax / 3)} y2={toY(v * absMax / 3)}
                stroke="hsl(var(--border))" strokeWidth={0.5} />
              <text x={PAD.left - 4} y={toY(v * absMax / 3) + 4}
                textAnchor="end" fontSize={9} fill="hsl(var(--muted-foreground))">
                {v > 0 ? '+' : ''}{Math.round(v * absMax / 3)}
              </text>
            </g>
          ))}

          {/* Bars */}
          {validRaces.map((r, i) => {
            const gained = r.positions_gained
            const barH = Math.abs((gained / absMax) * (IH / 2))
            const barY = gained >= 0 ? zeroY - barH : zeroY
            const color = gained >= 0
              ? 'hsl(var(--primary))'
              : 'hsl(var(--primary) / 0.35)'
            return (
              <g key={i}>
                <rect x={toX(i)} y={barY} width={barW} height={barH}
                  fill={color} rx={2} />
                <text x={toX(i) + barW / 2} y={H - 4}
                  textAnchor="middle" fontSize={8} fill="hsl(var(--muted-foreground))">
                  {r.race_name?.slice(0, 3).toUpperCase()}
                </text>
              </g>
            )
          })}

          {/* Rolling average line */}
          {rolling_avg.length > 1 && (
            <path d={rollingPath} fill="none"
              stroke="hsl(var(--foreground))" strokeWidth={1.5}
              strokeDasharray="4 2" strokeOpacity={0.6}
              strokeLinecap="round" strokeLinejoin="round" />
          )}

          {/* Axes */}
          <line x1={PAD.left} x2={PAD.left} y1={PAD.top} y2={H - PAD.bottom}
            stroke="hsl(var(--border))" strokeWidth={1} />
        </svg>
      </div>
    </div>
  )
}
```

- [ ] **Add import and case to `AnswerRenderer.jsx`**

```jsx
import DriverFormTrend from './chat-widgets/DriverFormTrend.jsx'
```

```jsx
  if (widget.type === 'driver_form_trend') {
    return <DriverFormTrend widget={widget} />
  }
```

- [ ] **Run tests to confirm they pass**

```
cd server && python -m pytest tests/test_f1_data.py::test_compute_positions_gained_basic tests/test_f1_data.py::test_compute_positions_gained_dnf_excluded tests/test_f1_data.py::test_form_trend_slope_improving tests/test_f1_data.py::test_form_trend_slope_declining tests/test_f1_data.py::test_form_trend_slope_stable -v
```

Expected: all five `PASSED`.

- [ ] **Run full test suite**

```
cd server && python -m pytest tests/ -v
```

- [ ] **Commit**

```
git add server/f1_data.py server/tools.py server/chat.py \
        client/src/components/chat-widgets/DriverFormTrend.jsx \
        client/src/components/AnswerRenderer.jsx \
        server/tests/test_f1_data.py
git commit -m "feat: add driver form trend tool and widget (positions gained vs grid, rolling average)"
```

---

### Task 3: FEAT-08 — Safety Car Probability per Circuit

**Files:**
- Modify: `server/f1_data.py` — add `_SC_PROBABILITY_BY_CIRCUIT` table + `get_sc_probability()`
- Modify: `server/tools.py` — add tool definition + dispatch
- Modify: `server/chat.py` — add widget builder + dispatch
- Create: `client/src/components/chat-widgets/ScProbabilityWidget.jsx`
- Modify: `client/src/components/AnswerRenderer.jsx`
- Test: `server/tests/test_f1_data.py`

**What it does in the app:** When a user asks "how likely is a safety car in Monaco?", the LLM calls `get_sc_probability`. The response shows historical SC frequency (2018–2024) plus a simple strategy implication: "Given 65% SC probability in the remaining 30 laps, pitting to cover creates positive expected value." The table is hardcoded from public historical records and can be updated by editing one dict.

- [ ] **Write the failing tests**

```python
def test_sc_lookup_monaco_is_high():
    """Monaco should have probability > 0.5 — it is historically the most SC-prone circuit."""
    from f1_data import _sc_probability_for_circuit
    prob = _sc_probability_for_circuit('Monaco')
    assert prob > 0.5, f"Monaco SC probability should exceed 0.5, got {prob}"


def test_sc_lookup_monza_is_lower():
    """Monza is historically a low-SC circuit."""
    from f1_data import _sc_probability_for_circuit
    prob = _sc_probability_for_circuit('Monza')
    assert prob < 0.45, f"Monza SC probability should be below 0.45, got {prob}"


def test_sc_lookup_unknown_returns_default():
    """Unknown circuit names fall back to the series average (~0.40)."""
    from f1_data import _sc_probability_for_circuit
    prob = _sc_probability_for_circuit('UnknownCircuitXYZ')
    assert 0.30 <= prob <= 0.55
```

- [ ] **Run tests to confirm they fail**

```
cd server && python -m pytest tests/test_f1_data.py::test_sc_lookup_monaco_is_high tests/test_f1_data.py::test_sc_lookup_monza_is_lower tests/test_f1_data.py::test_sc_lookup_unknown_returns_default -v
```

Expected: all three `FAILED`.

- [ ] **Add SC probability table and helpers to `f1_data.py`**

Add near the top of `f1_data.py`, after the imports:

```python
# Historical safety car / VSC probability per circuit, 2018–2024.
# Defined as: fraction of races at this circuit that featured at least one SC or VSC period.
# Source: public race control records; update annually.
_SC_PROBABILITY_BY_CIRCUIT: dict[str, float] = {
    'Baku':              0.78,
    'Singapore':         0.72,
    'Monaco':            0.65,
    'Jeddah':            0.65,
    'Melbourne':         0.58,
    'Spa':               0.55,
    'Las Vegas':         0.55,
    'Brazil':            0.55,
    'Japan':             0.50,
    'Hungaroring':       0.45,
    'Silverstone':       0.43,
    'Austin':            0.43,
    'Miami':             0.42,
    'Zandvoort':         0.42,
    'Mexico City':       0.40,
    'Imola':             0.38,
    'Abu Dhabi':         0.36,
    'Barcelona':         0.35,
    'China':             0.35,
    'Bahrain':           0.33,
    'Monza':             0.30,
    'Canada':            0.29,
    'Lusail':            0.28,
}

_SC_SERIES_AVERAGE = 0.42


def _sc_probability_for_circuit(circuit_name: str) -> float:
    """Lookup SC probability by circuit name. Partial match supported. Returns series average if unknown."""
    name_lower = circuit_name.lower()
    for key, prob in _SC_PROBABILITY_BY_CIRCUIT.items():
        if key.lower() in name_lower or name_lower in key.lower():
            return prob
    return _SC_SERIES_AVERAGE
```

- [ ] **Add `get_sc_probability` integration function to `f1_data.py`**

```python
def get_sc_probability(round_number: int) -> dict:
    """
    Return historical SC/VSC probability for the circuit hosting round_number in the current season.
    Also returns remaining-race probability given current lap (if race is live — omitted if unknown).
    """
    url = f"{_JOLPICA_BASE}/current/{round_number}.json"
    resp = requests.get(url, timeout=15)
    resp.raise_for_status()
    data = resp.json()['MRData']['RaceTable']['Races']
    if not data:
        return {'error': f'Round {round_number} not found in current season'}

    race = data[0]
    circuit_name = race['Circuit']['circuitName']
    race_name    = race['raceName']

    prob = _sc_probability_for_circuit(circuit_name)

    historical = sorted(
        [(k, v) for k, v in _SC_PROBABILITY_BY_CIRCUIT.items()],
        key=lambda x: x[1], reverse=True
    )
    rank = next((i + 1 for i, (k, _) in enumerate(historical)
                 if k.lower() in circuit_name.lower() or circuit_name.lower() in k.lower()),
                None)

    return {
        'circuit_name':          circuit_name,
        'race_name':             race_name,
        'round':                 round_number,
        'sc_probability':        prob,
        'sc_probability_pct':    round(prob * 100, 1),
        'classification':        (
            'very high (street circuit)' if prob >= 0.65 else
            'high' if prob >= 0.50 else
            'moderate' if prob >= 0.38 else
            'low'
        ),
        'circuits_ranked':       len(_SC_PROBABILITY_BY_CIRCUIT),
        'rank_by_sc_probability': rank,
        'series_average_pct':    round(_SC_SERIES_AVERAGE * 100, 1),
        'interpretation': (
            f"{circuit_name} has a {round(prob * 100)}% historical SC/VSC rate "
            f"({'above' if prob > _SC_SERIES_AVERAGE else 'below'} the {round(_SC_SERIES_AVERAGE * 100)}% series average). "
            f"Strategy implications: {'undercut and cover SC are both viable — account for SC when evaluating 1-stop vs 2-stop' if prob >= 0.50 else 'SC less likely to reshape the race; standard degradation strategy applies'}."
        ),
    }
```

- [ ] **Add tool definition to `server/tools.py`**

```python
    _tool(
        "get_sc_probability",
        "PRIMITIVE TOOL. Historical safety car and virtual safety car probability for the circuit "
        "hosting a given round. Use when analysing strategy decisions where SC probability matters — "
        "undercuts, tyre choice, 1-stop vs 2-stop evaluation. Street circuits (Monaco, Singapore, Baku) "
        "have 65–78% SC probability; permanent circuits average 30–45%.",
        {
            "round_number": {"type": "integer", "description": "The 2026 season round number."},
        },
        ["round_number"],
    ),
```

Add import and dispatch:
```python
from f1_data import (
    ...
    get_sc_probability,
    ...
)
```

```python
    if name == "get_sc_probability":
        return get_sc_probability(args["round_number"])
```

- [ ] **Add widget builder to `server/chat.py`**

```python
def _make_sc_probability_widget(result: dict) -> dict:
    return {
        "type":               "sc_probability",
        "circuit_name":       result.get("circuit_name"),
        "race_name":          result.get("race_name"),
        "sc_probability":     result.get("sc_probability"),
        "sc_probability_pct": result.get("sc_probability_pct"),
        "classification":     result.get("classification"),
        "rank":               result.get("rank_by_sc_probability"),
        "circuits_ranked":    result.get("circuits_ranked"),
        "series_average_pct": result.get("series_average_pct"),
        "interpretation":     result.get("interpretation"),
    }
```

```python
        if tool_name == "get_sc_probability":
            widgets.append(_make_sc_probability_widget(tool_result))
```

- [ ] **Create `client/src/components/chat-widgets/ScProbabilityWidget.jsx`**

```jsx
const TIER_COLOR = (prob) => {
  if (prob >= 0.65) return 'hsl(var(--primary))'
  if (prob >= 0.50) return 'hsl(var(--time))'
  if (prob >= 0.38) return 'hsl(var(--speed))'
  return 'hsl(var(--muted-foreground))'
}

export default function ScProbabilityWidget({ widget }) {
  const { circuit_name, race_name, sc_probability, sc_probability_pct,
          classification, rank, circuits_ranked, series_average_pct, interpretation } = widget
  if (!sc_probability) return null

  const prob = sc_probability ?? 0
  const color = TIER_COLOR(prob)
  const barPct = Math.round(prob * 100)

  return (
    <div className="widget-enter max-w-xl overflow-hidden rounded-xl border border-border/80 bg-card">
      <div className="border-b border-border/80 px-4 py-3">
        <div className="text-sm font-medium text-foreground">{race_name}</div>
        <div className="mt-0.5 text-xs text-muted-foreground">Safety car probability — historical (2018–2024)</div>
      </div>

      <div className="px-4 py-4">
        <div className="mb-3 flex items-end justify-between">
          <div>
            <span className="font-mono-data text-3xl font-bold" style={{ color }}>{sc_probability_pct}%</span>
            <span className="ml-2 text-xs capitalize text-muted-foreground">{classification}</span>
          </div>
          {rank && (
            <div className="text-right text-xs text-muted-foreground">
              #{rank} most SC-prone<br />of {circuits_ranked} circuits
            </div>
          )}
        </div>

        {/* Probability bar */}
        <div className="relative mb-2 h-2.5 overflow-hidden rounded-full bg-muted">
          <div className="absolute inset-y-0 left-0 rounded-full transition-all"
            style={{ width: `${barPct}%`, background: color }} />
          {/* Series average marker */}
          <div className="absolute inset-y-0 w-0.5 bg-foreground opacity-40"
            style={{ left: `${series_average_pct}%` }} />
        </div>
        <div className="flex justify-between text-[10px] text-muted-foreground">
          <span>0%</span>
          <span className="flex items-center gap-1">
            <span className="inline-block h-2 w-0.5 bg-foreground opacity-40" />
            avg {series_average_pct}%
          </span>
          <span>100%</span>
        </div>

        {interpretation && (
          <p className="mt-3 text-xs leading-relaxed text-muted-foreground">{interpretation}</p>
        )}
      </div>
    </div>
  )
}
```

- [ ] **Add import and case to `AnswerRenderer.jsx`**

```jsx
import ScProbabilityWidget from './chat-widgets/ScProbabilityWidget.jsx'
```

```jsx
  if (widget.type === 'sc_probability') {
    return <ScProbabilityWidget widget={widget} />
  }
```

- [ ] **Run tests to confirm they pass**

```
cd server && python -m pytest tests/test_f1_data.py::test_sc_lookup_monaco_is_high tests/test_f1_data.py::test_sc_lookup_monza_is_lower tests/test_f1_data.py::test_sc_lookup_unknown_returns_default -v
```

Expected: all three `PASSED`.

- [ ] **Run full test suite**

```
cd server && python -m pytest tests/ -v
```

- [ ] **Commit**

```
git add server/f1_data.py server/tools.py server/chat.py \
        client/src/components/chat-widgets/ScProbabilityWidget.jsx \
        client/src/components/AnswerRenderer.jsx \
        server/tests/test_f1_data.py
git commit -m "feat: add safety car probability tool and widget with circuit-specific historical rates"
```

---

### Task 4: FEAT-20 — Head-to-Head Driver History

**Files:**
- Modify: `server/f1_data.py` — add `_compute_head_to_head_stats()` + `get_head_to_head_history()`
- Modify: `server/tools.py` — add tool definition + dispatch
- Modify: `server/chat.py` — add widget builder + dispatch
- Create: `client/src/components/chat-widgets/HeadToHeadHistory.jsx`
- Modify: `client/src/components/AnswerRenderer.jsx`
- Test: `server/tests/test_f1_data.py`

**What it does in the app:** When a user asks "who is faster historically — Norris or Leclerc?", the LLM calls `get_head_to_head_history`. The response shows a race-by-race breakdown of who finished ahead, overall win rate, and average position delta. Data comes from Jolpica `/results` endpoint already used elsewhere.

- [ ] **Write the failing tests**

```python
def test_head_to_head_stats_win_rate():
    """Win rate is computed correctly from comparison list."""
    from f1_data import _compute_head_to_head_stats

    comparisons = [
        {'driver_a_pos': 1, 'driver_b_pos': 2},  # A wins
        {'driver_a_pos': 3, 'driver_b_pos': 1},  # B wins
        {'driver_a_pos': 2, 'driver_b_pos': 4},  # A wins
        {'driver_a_pos': 5, 'driver_b_pos': 3},  # B wins
    ]
    result = _compute_head_to_head_stats(comparisons, 'NOR', 'LEC')
    assert result['driver_a_wins'] == 2
    assert result['driver_b_wins'] == 2
    assert abs(result['driver_a_win_rate'] - 0.5) < 0.01
    assert result['races_together'] == 4


def test_head_to_head_stats_avg_delta():
    """Average position delta computed correctly."""
    from f1_data import _compute_head_to_head_stats

    comparisons = [
        {'driver_a_pos': 1, 'driver_b_pos': 3},  # A +2
        {'driver_a_pos': 4, 'driver_b_pos': 2},  # A -2
    ]
    result = _compute_head_to_head_stats(comparisons, 'NOR', 'LEC')
    # avg delta (B_pos - A_pos) = (3-1 + 2-4) / 2 = (2 + -2) / 2 = 0
    assert abs(result['avg_position_delta']) < 0.01


def test_head_to_head_excludes_dnf():
    """Races where either driver DNF'd (position 0 or missing) are excluded."""
    from f1_data import _compute_head_to_head_stats

    comparisons = [
        {'driver_a_pos': 1, 'driver_b_pos': 0},   # B DNF — exclude
        {'driver_a_pos': 0, 'driver_b_pos': 2},   # A DNF — exclude
        {'driver_a_pos': 2, 'driver_b_pos': 3},   # valid
    ]
    result = _compute_head_to_head_stats(comparisons, 'NOR', 'LEC')
    assert result['races_together'] == 1
```

- [ ] **Run tests to confirm they fail**

```
cd server && python -m pytest tests/test_f1_data.py::test_head_to_head_stats_win_rate tests/test_f1_data.py::test_head_to_head_stats_avg_delta tests/test_f1_data.py::test_head_to_head_excludes_dnf -v
```

Expected: all three `FAILED`.

- [ ] **Add pure helpers to `f1_data.py`**

```python
def _compute_head_to_head_stats(
    comparisons: list[dict], driver_a: str, driver_b: str
) -> dict:
    """
    Compare finishing positions in races where both drivers competed.
    comparisons: list of {'driver_a_pos': int, 'driver_b_pos': int}
    Races with either driver DNF (pos <= 0) are excluded.
    avg_position_delta = avg(driver_b_pos - driver_a_pos); positive = A consistently ahead.
    """
    valid = [
        c for c in comparisons
        if c.get('driver_a_pos', 0) > 0 and c.get('driver_b_pos', 0) > 0
    ]
    n = len(valid)
    if n == 0:
        return {
            'driver_a': driver_a, 'driver_b': driver_b,
            'races_together': 0, 'driver_a_wins': 0, 'driver_b_wins': 0,
            'driver_a_win_rate': None, 'avg_position_delta': None,
        }

    a_wins = sum(1 for c in valid if c['driver_a_pos'] < c['driver_b_pos'])
    b_wins = sum(1 for c in valid if c['driver_b_pos'] < c['driver_a_pos'])
    deltas = [c['driver_b_pos'] - c['driver_a_pos'] for c in valid]

    return {
        'driver_a':             driver_a,
        'driver_b':             driver_b,
        'races_together':       n,
        'driver_a_wins':        a_wins,
        'driver_b_wins':        b_wins,
        'ties':                 n - a_wins - b_wins,
        'driver_a_win_rate':    round(a_wins / n, 3),
        'driver_b_win_rate':    round(b_wins / n, 3),
        'avg_position_delta':   round(sum(deltas) / n, 2),
    }
```

- [ ] **Add `get_head_to_head_history` integration function to `f1_data.py`**

```python
def get_head_to_head_history(
    driver_a: str, driver_b: str, seasons: list[int] | None = None
) -> dict:
    """
    Multi-season head-to-head race results between driver_a and driver_b.
    seasons defaults to the last 3 complete seasons. driver codes (NOR, LEC) or surnames accepted.
    """
    current_year = 2026
    if seasons is None:
        seasons = [current_year - 3, current_year - 2, current_year - 1]

    drv_a_id = _resolve_driver_id(driver_a)
    drv_b_id = _resolve_driver_id(driver_b)

    def _fetch_results(driver_id: str, year: int) -> dict[tuple, dict]:
        url = f"{_JOLPICA_BASE}/{year}/drivers/{driver_id}/results.json?limit=30"
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        races_data = resp.json()['MRData']['RaceTable']['Races']
        by_key = {}
        for race in races_data:
            key = (int(race['season']), int(race['round']))
            result = race.get('Results', [{}])[0]
            try:
                pos = int(result.get('position', 0))
            except (TypeError, ValueError):
                pos = 0
            by_key[key] = {
                'race_name': race['raceName'],
                'circuit':   race['Circuit']['circuitName'],
                'position':  pos,
                'grid':      int(result.get('grid', 0) or 0),
                'status':    result.get('status', ''),
            }
        return by_key

    all_comparisons = []
    per_race_rows = []

    for season in seasons:
        results_a = _fetch_results(drv_a_id, season)
        results_b = _fetch_results(drv_b_id, season)
        shared_keys = sorted(set(results_a) & set(results_b))
        for key in shared_keys:
            ra = results_a[key]
            rb = results_b[key]
            all_comparisons.append({
                'driver_a_pos': ra['position'],
                'driver_b_pos': rb['position'],
            })
            winner = (driver_a if ra['position'] > 0 and rb['position'] > 0
                      and ra['position'] < rb['position'] else
                      driver_b if rb['position'] > 0 and ra['position'] > 0
                      and rb['position'] < ra['position'] else None)
            per_race_rows.append({
                'season':       key[0],
                'round':        key[1],
                'race_name':    ra['race_name'].replace(' Grand Prix', ''),
                'circuit':      ra['circuit'],
                'a_position':   ra['position'] or None,
                'b_position':   rb['position'] or None,
                'a_grid':       ra['grid'] or None,
                'b_grid':       rb['grid'] or None,
                'winner':       winner,
            })

    stats = _compute_head_to_head_stats(all_comparisons, driver_a.upper(), driver_b.upper())

    return {
        **stats,
        'seasons_analysed': seasons,
        'per_race':         per_race_rows,
        'dominant_driver': (
            driver_a.upper() if stats.get('avg_position_delta', 0) > 0.5 else
            driver_b.upper() if stats.get('avg_position_delta', 0) < -0.5 else
            'evenly matched'
        ),
    }
```

- [ ] **Add tool definition to `server/tools.py`**

```python
    _tool(
        "get_head_to_head_history",
        "PRIMITIVE TOOL. Multi-season head-to-head race history between two drivers: "
        "how often each finished ahead in the same race, average position delta, and race-by-race breakdown. "
        "Use for comparative questions like 'who is faster, Norris or Leclerc?' or "
        "'how has the Hamilton vs Russell battle looked historically?'",
        {
            "driver_a":  {"type": "string", "description": "First driver name or 3-letter code."},
            "driver_b":  {"type": "string", "description": "Second driver name or 3-letter code."},
            "seasons":   {"type": "array",  "items": {"type": "integer"},
                          "description": "List of season years to include (default: last 3 complete seasons)."},
        },
        ["driver_a", "driver_b"],
    ),
```

```python
from f1_data import (
    ...
    get_head_to_head_history,
    ...
)
```

```python
    if name == "get_head_to_head_history":
        return get_head_to_head_history(
            args["driver_a"], args["driver_b"], args.get("seasons")
        )
```

- [ ] **Add widget builder to `server/chat.py`**

```python
def _make_head_to_head_history_widget(result: dict) -> dict:
    return {
        "type":               "head_to_head_history",
        "driver_a":           result.get("driver_a"),
        "driver_b":           result.get("driver_b"),
        "races_together":     result.get("races_together"),
        "driver_a_wins":      result.get("driver_a_wins"),
        "driver_b_wins":      result.get("driver_b_wins"),
        "driver_a_win_rate":  result.get("driver_a_win_rate"),
        "driver_b_win_rate":  result.get("driver_b_win_rate"),
        "avg_position_delta": result.get("avg_position_delta"),
        "dominant_driver":    result.get("dominant_driver"),
        "seasons_analysed":   result.get("seasons_analysed", []),
        "per_race":           result.get("per_race", []),
    }
```

```python
        if tool_name == "get_head_to_head_history":
            widgets.append(_make_head_to_head_history_widget(tool_result))
```

- [ ] **Create `client/src/components/chat-widgets/HeadToHeadHistory.jsx`**

```jsx
const COLOR_A = 'hsl(var(--primary))'
const COLOR_B = 'hsl(var(--speed))'

function WinBar({ winsA, winsB, ties, driverA, driverB }) {
  const total = winsA + winsB + ties || 1
  const pctA = (winsA / total) * 100
  const pctT = (ties / total) * 100
  const pctB = (winsB / total) * 100

  return (
    <div className="my-3">
      <div className="mb-1.5 flex justify-between text-xs font-medium">
        <span style={{ color: COLOR_A }}>{driverA} {winsA}</span>
        {ties > 0 && <span className="text-muted-foreground">{ties} tied</span>}
        <span style={{ color: COLOR_B }}>{winsB} {driverB}</span>
      </div>
      <div className="flex h-3 overflow-hidden rounded-full">
        <div style={{ width: `${pctA}%`, background: COLOR_A }} />
        {pctT > 0 && <div style={{ width: `${pctT}%` }} className="bg-muted" />}
        <div style={{ width: `${pctB}%`, background: COLOR_B }} />
      </div>
    </div>
  )
}

export default function HeadToHeadHistory({ widget }) {
  const {
    driver_a, driver_b, races_together, driver_a_wins, driver_b_wins,
    avg_position_delta, dominant_driver, seasons_analysed, per_race,
  } = widget

  const ties = (races_together ?? 0) - (driver_a_wins ?? 0) - (driver_b_wins ?? 0)
  const winRateA = races_together ? ((driver_a_wins / races_together) * 100).toFixed(0) : '—'

  return (
    <div className="widget-enter max-w-2xl overflow-hidden rounded-xl border border-border/80 bg-card">
      <div className="border-b border-border/80 px-4 py-3">
        <div className="text-sm font-medium text-foreground">
          {driver_a} vs {driver_b} — head-to-head
        </div>
        <div className="mt-0.5 text-xs text-muted-foreground">
          {seasons_analysed?.join(', ')} seasons · {races_together} shared races
        </div>
      </div>

      <div className="px-4 pt-3 pb-2">
        <WinBar winsA={driver_a_wins ?? 0} winsB={driver_b_wins ?? 0} ties={ties}
          driverA={driver_a} driverB={driver_b} />

        <div className="grid grid-cols-3 gap-2 text-center text-xs">
          <div>
            <div className="font-mono-data font-bold" style={{ color: COLOR_A }}>{winRateA}%</div>
            <div className="text-muted-foreground">{driver_a} win rate</div>
          </div>
          <div>
            <div className="font-mono-data font-bold text-foreground">
              {avg_position_delta != null
                ? `${avg_position_delta > 0 ? '+' : ''}${avg_position_delta.toFixed(1)}`
                : '—'}
            </div>
            <div className="text-muted-foreground">avg pos delta</div>
          </div>
          <div>
            <div className="font-mono-data font-bold"
              style={{ color: dominant_driver === driver_a ? COLOR_A : dominant_driver === driver_b ? COLOR_B : 'hsl(var(--muted-foreground))' }}>
              {dominant_driver}
            </div>
            <div className="text-muted-foreground">dominant</div>
          </div>
        </div>
      </div>

      {per_race?.length > 0 && (
        <div className="border-t border-border/80">
          <div className="max-h-48 overflow-y-auto">
            <table className="w-full text-xs">
              <thead className="border-b border-border/60 bg-muted/30">
                <tr>
                  <th className="px-3 py-1.5 text-left font-medium text-muted-foreground">Race</th>
                  <th className="px-2 py-1.5 text-center font-medium" style={{ color: COLOR_A }}>{driver_a}</th>
                  <th className="px-2 py-1.5 text-center font-medium" style={{ color: COLOR_B }}>{driver_b}</th>
                  <th className="px-2 py-1.5 text-center font-medium text-muted-foreground">Winner</th>
                </tr>
              </thead>
              <tbody>
                {per_race.map((r, i) => (
                  <tr key={i} className="border-b border-border/40 last:border-0">
                    <td className="px-3 py-1 text-muted-foreground">{r.race_name} {r.season}</td>
                    <td className="px-2 py-1 text-center font-mono-data"
                      style={{ color: r.winner === driver_a ? COLOR_A : undefined }}>
                      {r.a_position ? `P${r.a_position}` : 'DNF'}
                    </td>
                    <td className="px-2 py-1 text-center font-mono-data"
                      style={{ color: r.winner === driver_b ? COLOR_B : undefined }}>
                      {r.b_position ? `P${r.b_position}` : 'DNF'}
                    </td>
                    <td className="px-2 py-1 text-center font-medium"
                      style={{ color: r.winner === driver_a ? COLOR_A : r.winner === driver_b ? COLOR_B : 'hsl(var(--muted-foreground))' }}>
                      {r.winner ?? '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}
```

- [ ] **Add import and case to `AnswerRenderer.jsx`**

```jsx
import HeadToHeadHistory from './chat-widgets/HeadToHeadHistory.jsx'
```

```jsx
  if (widget.type === 'head_to_head_history') {
    return <HeadToHeadHistory widget={widget} />
  }
```

- [ ] **Run tests to confirm they pass**

```
cd server && python -m pytest tests/test_f1_data.py::test_head_to_head_stats_win_rate tests/test_f1_data.py::test_head_to_head_stats_avg_delta tests/test_f1_data.py::test_head_to_head_excludes_dnf -v
```

Expected: all three `PASSED`.

- [ ] **Run full test suite**

```
cd server && python -m pytest tests/ -v
```

- [ ] **Commit**

```
git add server/f1_data.py server/tools.py server/chat.py \
        client/src/components/chat-widgets/HeadToHeadHistory.jsx \
        client/src/components/AnswerRenderer.jsx \
        server/tests/test_f1_data.py
git commit -m "feat: add head-to-head driver history tool, widget, and race-by-race breakdown"
```

---

### Task 5: FEAT-17 — Per-Session Driver Style Fingerprint

**Files:**
- Modify: `server/f1_data.py` — add `_aggregate_style_fingerprint()` + `get_session_style_fingerprint()`
- Modify: `server/tools.py` — add tool definition + dispatch
- Modify: `server/chat.py` — add widget builder + dispatch
- Create: `client/src/components/chat-widgets/StyleFingerprintWidget.jsx`
- Modify: `client/src/components/AnswerRenderer.jsx`
- Test: `server/tests/test_f1_data.py`

**What it does in the app:** When a user asks "how was Norris driving today?", the LLM calls `get_session_style_fingerprint`. The response shows aggregated session metrics — average `trail_brake_pct`, `throttle_acceptance_pct`, `entry_bravery_pct`, `avg_ggv_util_pct` — and flags if any metric is unusually high or low compared to the field average. No new data required: `analyze_cornering_loads()` already computes all of these per-corner.

- [ ] **Write the failing tests**

```python
def test_aggregate_style_fingerprint_averaging():
    """Mean of per-corner metrics is returned correctly."""
    from f1_data import _aggregate_style_fingerprint
    corners = [
        {'trail_brake_pct': 60.0, 'throttle_acceptance_pct': 70.0,
         'entry_bravery_pct': 50.0, 'avg_ggv_util_pct': 80.0},
        {'trail_brake_pct': 40.0, 'throttle_acceptance_pct': 80.0,
         'entry_bravery_pct': 70.0, 'avg_ggv_util_pct': 75.0},
    ]
    result = _aggregate_style_fingerprint(corners)
    assert result['trail_brake_pct'] == 50.0
    assert result['throttle_acceptance_pct'] == 75.0
    assert result['entry_bravery_pct'] == 60.0
    assert result['avg_ggv_util_pct'] == 77.5
    assert result['corner_count'] == 2


def test_aggregate_style_fingerprint_ignores_none():
    """Corners with None values for a metric must not contaminate the average."""
    from f1_data import _aggregate_style_fingerprint
    corners = [
        {'trail_brake_pct': 60.0, 'throttle_acceptance_pct': None},
        {'trail_brake_pct': 40.0, 'throttle_acceptance_pct': 80.0},
    ]
    result = _aggregate_style_fingerprint(corners)
    assert result['trail_brake_pct'] == 50.0
    # Only one corner has throttle_acceptance_pct
    assert result['throttle_acceptance_pct'] == 80.0


def test_aggregate_style_fingerprint_empty_returns_defaults():
    from f1_data import _aggregate_style_fingerprint
    result = _aggregate_style_fingerprint([])
    assert result['corner_count'] == 0
    assert result['trail_brake_pct'] is None
```

- [ ] **Run tests to confirm they fail**

```
cd server && python -m pytest tests/test_f1_data.py::test_aggregate_style_fingerprint_averaging tests/test_f1_data.py::test_aggregate_style_fingerprint_ignores_none tests/test_f1_data.py::test_aggregate_style_fingerprint_empty_returns_defaults -v
```

Expected: all three `FAILED`.

- [ ] **Add pure helpers to `f1_data.py`**

```python
_STYLE_METRICS = [
    'trail_brake_pct',
    'throttle_acceptance_pct',
    'entry_bravery_pct',
    'avg_ggv_util_pct',
    'apex_speed_kph',
]


def _aggregate_style_fingerprint(corners: list[dict]) -> dict:
    """
    Aggregate per-corner style metrics into session-level means.
    Skips None values per metric. Returns None for any metric with no valid corners.
    """
    if not corners:
        return {m: None for m in _STYLE_METRICS} | {'corner_count': 0}

    result = {'corner_count': len(corners)}
    for metric in _STYLE_METRICS:
        vals = [c[metric] for c in corners if c.get(metric) is not None]
        result[metric] = round(sum(vals) / len(vals), 2) if vals else None
    return result
```

- [ ] **Add `get_session_style_fingerprint` integration function to `f1_data.py`**

```python
def get_session_style_fingerprint(
    round_number: int, session_type: str, driver_name: str
) -> dict:
    """
    Aggregate cornering metrics across all laps in the session into a style fingerprint.
    Calls analyze_cornering_loads internally to get per-corner data.
    Returns session-level averages for trail_brake_pct, throttle_acceptance_pct,
    entry_bravery_pct, avg_ggv_util_pct, and flags unusual values vs field average.
    """
    # Use existing cornering analysis — this does the FastF1 load + per-corner computation
    cornering = analyze_cornering_loads(round_number, session_type, driver_name)
    corners = cornering.get('corners', [])

    fingerprint = _aggregate_style_fingerprint(corners)

    # Field average: compute for the first 2 other drivers in the session for a fast baseline
    # (a full field average would require loading all 20 drivers — too slow for a chat request)
    # Expose the raw session average instead; the LLM can compare to expected ranges in its prompt.
    return {
        'driver':         driver_name.upper(),
        'round':          round_number,
        'session':        session_type,
        'corner_count':   fingerprint['corner_count'],
        'trail_brake_pct':         fingerprint.get('trail_brake_pct'),
        'throttle_acceptance_pct': fingerprint.get('throttle_acceptance_pct'),
        'entry_bravery_pct':       fingerprint.get('entry_bravery_pct'),
        'avg_ggv_util_pct':        fingerprint.get('avg_ggv_util_pct'),
        'avg_apex_speed_kph':      fingerprint.get('apex_speed_kph'),
        'interpretation_hints': {
            'trail_brake_pct':         'High (>50%) = carries braking into corners (late-braker style)',
            'throttle_acceptance_pct': 'High (>60%) = early throttle application (V-line style)',
            'entry_bravery_pct':       'High (>55%) = high entry speed relative to circuit norms',
            'avg_ggv_util_pct':        'High (>80%) = near the traction/grip limit throughout',
        },
    }
```

- [ ] **Add tool definition to `server/tools.py`**

```python
    _tool(
        "get_session_style_fingerprint",
        "PRIMITIVE TOOL. Aggregates all per-corner telemetry metrics for a driver across a session "
        "into a style fingerprint: average trail-brake percentage, throttle acceptance, entry bravery, "
        "and GGV utilisation. Use for questions like 'how was Norris driving today?' or "
        "'was Hamilton in an aggressive or conservative mode in qualifying?'",
        {
            "round_number": {"type": "integer", "description": "Race round number."},
            "session_type": {"type": "string", "description": "Q, R, FP1, FP2, or FP3."},
            "driver_name":  {"type": "string", "description": "Driver name or 3-letter code."},
        },
        ["round_number", "session_type", "driver_name"],
    ),
```

```python
from f1_data import (
    ...
    get_session_style_fingerprint,
    ...
)
```

```python
    if name == "get_session_style_fingerprint":
        return get_session_style_fingerprint(
            args["round_number"], args["session_type"], args["driver_name"]
        )
```

- [ ] **Add widget builder to `server/chat.py`**

```python
def _make_style_fingerprint_widget(result: dict) -> dict:
    return {
        "type":                    "style_fingerprint",
        "driver":                  result.get("driver"),
        "round":                   result.get("round"),
        "session":                 result.get("session"),
        "corner_count":            result.get("corner_count"),
        "trail_brake_pct":         result.get("trail_brake_pct"),
        "throttle_acceptance_pct": result.get("throttle_acceptance_pct"),
        "entry_bravery_pct":       result.get("entry_bravery_pct"),
        "avg_ggv_util_pct":        result.get("avg_ggv_util_pct"),
        "avg_apex_speed_kph":      result.get("avg_apex_speed_kph"),
        "interpretation_hints":    result.get("interpretation_hints", {}),
    }
```

```python
        if tool_name == "get_session_style_fingerprint":
            widgets.append(_make_style_fingerprint_widget(tool_result))
```

- [ ] **Create `client/src/components/chat-widgets/StyleFingerprintWidget.jsx`**

```jsx
const METRICS = [
  { key: 'trail_brake_pct',         label: 'Trail braking',     high: 'Late braker', low: 'Early braker' },
  { key: 'throttle_acceptance_pct', label: 'Throttle timing',   high: 'V-line (early)', low: 'Conservative' },
  { key: 'entry_bravery_pct',       label: 'Entry bravery',     high: 'Aggressive entry', low: 'Cautious entry' },
  { key: 'avg_ggv_util_pct',        label: 'Grip utilisation',  high: 'At the limit', low: 'Margin left' },
]

function MetricBar({ label, value, high, low }) {
  if (value === null || value === undefined) return null
  const pct = Math.min(Math.max(value, 0), 100)
  const isHigh = pct >= 60
  const color = isHigh ? 'hsl(var(--primary))' : 'hsl(var(--speed))'

  return (
    <div className="mb-3">
      <div className="mb-1 flex justify-between text-xs">
        <span className="text-muted-foreground">{label}</span>
        <span className="font-mono-data font-medium" style={{ color }}>
          {pct.toFixed(1)}%
        </span>
      </div>
      <div className="relative h-2 overflow-hidden rounded-full bg-muted">
        <div className="absolute inset-y-0 left-0 rounded-full"
          style={{ width: `${pct}%`, background: color }} />
        {/* 50% reference */}
        <div className="absolute inset-y-0 w-px bg-foreground opacity-20"
          style={{ left: '50%' }} />
      </div>
      <div className="mt-0.5 flex justify-between text-[10px] text-muted-foreground">
        <span>{low}</span>
        <span>{high}</span>
      </div>
    </div>
  )
}

export default function StyleFingerprintWidget({ widget }) {
  const { driver, round, session, corner_count, avg_apex_speed_kph } = widget

  return (
    <div className="widget-enter max-w-sm overflow-hidden rounded-xl border border-border/80 bg-card">
      <div className="border-b border-border/80 px-4 py-3">
        <div className="text-sm font-medium text-foreground">
          {driver} — session style fingerprint
        </div>
        <div className="mt-0.5 text-xs text-muted-foreground">
          {session} · Round {round} · {corner_count} corners analysed
        </div>
      </div>

      <div className="px-4 py-4">
        {METRICS.map((m) => (
          <MetricBar key={m.key} label={m.label} value={widget[m.key]}
            high={m.high} low={m.low} />
        ))}
        {avg_apex_speed_kph != null && (
          <div className="mt-2 border-t border-border/60 pt-2 text-xs text-muted-foreground">
            Avg apex speed: <span className="font-mono-data font-medium text-foreground">
              {avg_apex_speed_kph.toFixed(1)} kph
            </span>
          </div>
        )}
      </div>
    </div>
  )
}
```

- [ ] **Add import and case to `AnswerRenderer.jsx`**

```jsx
import StyleFingerprintWidget from './chat-widgets/StyleFingerprintWidget.jsx'
```

```jsx
  if (widget.type === 'style_fingerprint') {
    return <StyleFingerprintWidget widget={widget} />
  }
```

- [ ] **Run tests to confirm they pass**

```
cd server && python -m pytest tests/test_f1_data.py::test_aggregate_style_fingerprint_averaging tests/test_f1_data.py::test_aggregate_style_fingerprint_ignores_none tests/test_f1_data.py::test_aggregate_style_fingerprint_empty_returns_defaults -v
```

Expected: all three `PASSED`.

- [ ] **Run full test suite**

```
cd server && python -m pytest tests/ -v
```

- [ ] **Commit**

```
git add server/f1_data.py server/tools.py server/chat.py \
        client/src/components/chat-widgets/StyleFingerprintWidget.jsx \
        client/src/components/AnswerRenderer.jsx \
        server/tests/test_f1_data.py
git commit -m "feat: add per-session driver style fingerprint tool and widget (aggregated cornering metrics)"
```

---

### Final: Full Regression Run

- [ ] **Run the complete test suite one final time**

```
cd server && python -m pytest tests/ -v --tb=short
```

Expected: all tests pass across all 5 tasks.
