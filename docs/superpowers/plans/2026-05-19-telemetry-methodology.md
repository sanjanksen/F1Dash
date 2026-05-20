# Telemetry Methodology Refresh (F21–F30) Implementation Plan

> Status: not started. Estimated effort: ~8 weeks across three phases.
> Today: **2026-05-20**.

## Goal

Bring F1Dash's telemetry-analysis backbone to parity with industry tooling (MoTeC i2, McLaren Applied ATLAS, F1-Tempo, MultiViewer F1). Today the codebase ships several telemetry tools that mix DRS-on and DRS-off samples, ignore mini-sectors, treat each corner as one indivisible blob, and report a "commitment index" without the canonical g-g / friction-circle and trail-brake metrics race engineers reach for first. Phase 1 fixes correctness bugs in current output. Phase 2 adds analytical depth. Phase 3 derives a per-event style fingerprint from telemetry.

Scope (ten features):

- **F21** — DRS-state awareness across speed-trap leaderboards and speed-trace overlays. *Correctness fix.*
- **F22** — ~25 mini-sectors per lap with heatmap and delta-by-distance plot.
- **F23** — Three-phase corner decomposition (entry braking / Vmin / exit drive).
- **F24** — Friction-circle / g-g diagram.
- **F25** — Trail-brake quantification (dP_brake / dδ_steer).
- **F26** — Understeer/oversteer balance index (expected vs measured yaw).
- **F27** — Tyre warm-up / peak / degradation partition per stint. *Correctness fix.*
- **F28** — Racing-line spatial deviation from optimal.
- **F29** — Wet-session handling: detection, refusal of dry heuristics, wet-tyre axis. *Correctness fix.*
- **F30** — Per-event data-derived driver style fingerprint.

Phase 1 (F21, F27, F29) is the most important block: it fixes outputs that are currently *wrong*, not just thin. The remaining features extend depth.

## Architecture

No new top-level modules until Phase 3. Everything below is an addition or surgical edit inside existing files:

```
server/f1_data.py
  ← new helpers: drs_active(), compute_mini_sectors(),
                 compute_friction_circle(), compute_trail_brake_metric(),
                 compute_balance_index(), compute_line_deviation(),
                 compute_warmup_partition(), is_wet_session()
  ← extended: analyze_cornering_loads(), compare_corner_profiles(),
              _fit_stint_degradation(), get_speed_trap_leaderboard(),
              get_lap_telemetry(), get_sector_comparison()
server/tools.py
  ← new tools: compare_mini_sectors, analyze_car_balance
  ← extended tool descriptions for the modified primitives
server/chat.py
  ← new widget builders: _make_mini_sector_heatmap_widget,
                         _make_friction_circle_widget,
                         _make_balance_widget,
                         _make_style_fingerprint_widget
  ← extended builders: _make_corner_comparison_widget,
                       _make_deg_trend_chart_widget,
                       _make_speed_trace_widget
  ← system-prompt additions for DRS, wet-session, three-phase corner language
client/src/components/chat-widgets/
  ← new: MiniSectorHeatmapWidget.jsx, FrictionCircleWidget.jsx,
         BalanceWidget.jsx, StyleFingerprintWidget.jsx
  ← edited: SpeedTraceWidget.jsx (DRS badges),
            CornerComparisonWidget.jsx (three sub-tables),
            DegTrendChart.jsx (stint segments)
client/src/components/AnswerRenderer.jsx
  ← new cases: mini_sector_heatmap, friction_circle, car_balance,
               style_fingerprint
server/driver_styles.py
  ← optional Phase 3 consumer: derived fingerprint augments static profile
```

Phase 3 introduces one new module — `server/style_fingerprint.py` — to keep the fingerprint logic isolated from per-tool helpers. Everything in Phases 1 and 2 lives inside `f1_data.py` to match the existing module layout.

---

## FastF1 Data Availability — Verify Before Implementation

Phase 1 / Phase 2 features depend on specific FastF1 channels. Confirm each is populated for a representative 2024 race and a 2026 race before writing code; channel coverage has historically varied year-by-year as the FIA data feed changed.

| Channel | FastF1 access | Used by | Known caveats |
|---|---|---|---|
| `DRS` | `lap.get_car_data()['DRS']` | F21 | Values `10`/`12`/`14` = active; `0`/`1`/`8` = off. Sampled at car-data cadence (~4 Hz), not lap. |
| `Speed`, `Throttle`, `Brake`, `nGear`, `RPM` | `lap.get_car_data()` | All telemetry | Always populated. |
| `X`, `Y` (track-map) | `lap.get_pos_data()` | F22, F24, F28 | GPS @ ~5 Hz; resampled by FastF1's `.add_distance()` helper. |
| `Distance` | derived via `add_distance()` | F22, F23, F28 | Cumulative lap distance; ground truth for mini-sectoring. |
| `weather_data` (TrackTemp, AirTemp, Rainfall, Humidity, WindSpeed) | `session.weather_data` (already used at f1_data.py:4002, :6164) | F29 | Sampled at ~1 min cadence; FastF1 fills missing via interpolation. |
| Lateral G | **derived only** — not raw IMU | F24, F26 | FastF1 computes `lat_g` numerically from `Speed` and track curvature. Noisy at low speeds and in pit lane. **Load-bearing risk for F26.** |
| Longitudinal G | **derived only** | F24 | Computed from dV/dt; sensitive to sample noise. |
| Steering angle (`Driver_Ahead`-style steering channel) | **NOT public.** FastF1 does not expose raw steering. | F25, F26, F30 | We must **proxy** steering from `X,Y` curvature (κ ≈ dθ/ds, θ = atan2(dY,dX)) or skip the feature. |
| Brake pressure | FastF1 only exposes `Brake` as **0/1 binary** in most years. | F23, F25 | Brake-onset/release times are recoverable; "peak brake pressure" is not. We must reformulate F23 and F25 in terms of timing rather than analog pressure. |
| Yaw rate | **NOT exposed.** | F26 | Must derive from heading-angle differences of (X, Y); see Risk #1. |

**Decision rule when a channel is missing:** the helper must return `None` (not zero, not a placeholder) and the widget must render a "channel unavailable" badge rather than silently graphing garbage. Every helper added below has this contract baked into its acceptance criteria.

---

# Phase 1 — Correctness fixes (~2 weeks)

These three features change the *meaning* of current output. They must ship before Phase 2.

## Task 1 (F21) — DRS-state-aware speed-trap & speed-trace

Files:

- Modify: `server/f1_data.py` — `get_speed_trap_leaderboard()`, `get_lap_telemetry()`, `get_sector_comparison()`.
- Modify: `server/tools.py` — descriptions for `get_speed_trap_leaderboard`, `get_lap_telemetry`.
- Modify: `server/chat.py` — `_make_speed_trace_widget()`, system-prompt language.
- Modify: `client/src/components/chat-widgets/SpeedTraceWidget.jsx`.
- Test: `server/tests/test_f1_data.py` (new `TestDrsAwareness` class).

### Change description

Add a helper that classifies each car-data sample by DRS state:

```python
def drs_active(drs_value) -> bool:
    """FastF1 DRS channel: 10/12/14 = open and active, else closed."""
    try:
        return int(drs_value) in (10, 12, 14)
    except (TypeError, ValueError):
        return False
```

Annotate every speed-trap and speed-trace sample with DRS state. Concretely:

1. `get_lap_telemetry()` already returns samples roughly every 100 m. Add a `drs_active: bool` field to each sample (currently `drs` is sometimes raw int, sometimes missing).
2. `get_sector_comparison()` — for each per-sample comparison row, add `drs_a_active` and `drs_b_active` booleans. The numeric `drs` columns at f1_data.py:1918–1919 already exist; convert them via `drs_active()` and surface as booleans.
3. `get_speed_trap_leaderboard()` — compute the per-lap speed-trap reading only over samples taken **inside** a DRS zone with DRS *active*. If a driver never opened DRS into the trap on their reference lap, return their non-DRS top speed and **flag the row with `drs_open: false`**.
4. The leaderboard's top-line answer must **refuse** to rank drivers if some had DRS open and others didn't, unless the caller explicitly opts in:

```python
def get_speed_trap_leaderboard(round_number, session_type, allow_mixed_drs: bool = False) -> dict:
    ...
    has_drs_open = any(row["drs_open"] for row in rows)
    has_drs_closed = any(not row["drs_open"] for row in rows)
    if has_drs_open and has_drs_closed and not allow_mixed_drs:
        return {
            "refusal": (
                "Comparing DRS-open and DRS-closed top-speeds is misleading; "
                "the gap could be 6+ km/h purely from DRS state. "
                "Re-ask with allow_mixed_drs=True if you want the raw figures anyway."
            ),
            "rows": rows,  # still returned for inspection, with drs_open flag per row
        }
```

5. `_make_speed_trace_widget()` — pass a parallel `drs_states` array alongside `speeds` so the React widget can render a DRS band under the trace.
6. Frontend: add a small "DRS" badge next to lap rows where `drs_open` is true. Render a translucent green stripe under the speed trace covering the DRS-active samples (use track-map color if a CSS token exists; otherwise `hsl(120 60% 45% / 0.18)`).

### Acceptance criteria

- `drs_active(10)`, `drs_active(12)`, `drs_active(14)` all return `True`; `drs_active(0)`, `drs_active(8)`, `drs_active(None)`, `drs_active("x")` all return `False`.
- For a 2024 Spa qualifying session, `get_speed_trap_leaderboard()` with the default `allow_mixed_drs=False` returns a refusal payload because some Q3 laps had DRS open and others did not (typical mid-Q3 mixed-DRS scenario).
- With `allow_mixed_drs=True`, the same call returns ranked rows, each tagged with `drs_open: bool`.
- `get_lap_telemetry()` output: every sample has a boolean `drs_active`. A frontend snapshot test confirms the green DRS band renders for a known reference lap.
- System prompt now contains: *"When summarising speed-trap differences, always state whether the compared laps had DRS open. If they didn't, the gap is not a clean engine/aero comparison."*

### References

- FastF1 `Car_Data` schema: DRS channel encoding documented at https://docs.fastf1.dev/core.html#fastf1.core.Telemetry (values 10/12/14).
- MultiViewer F1 v1.x — speed-trap row carries DRS indicator next to top speed.

---

## Task 2 (F27) — Tyre warm-up / peak / degradation partition

Files:

- Modify: `server/f1_data.py` — `_fit_stint_degradation()` (at f1_data.py:4456).
- Modify: `server/chat.py` — `_make_deg_trend_chart_widget()` at line 302; tyre guidance language.
- Modify: `client/src/components/chat-widgets/DegTrendChart.jsx`.
- Test: `server/tests/test_f1_data.py` (`TestWarmupPartition`).

### Change description

A stint is currently treated as one regression (with an optional cliff break, per the 2026-05-15 plan). Real stints have three phases:

1. **Warm-up** — first N laps where the tyre is below operating window. Lap times drop (negative slope) as the tyre arrives.
2. **Peak** — middle laps; near-linear slow degradation or a brief plateau.
3. **Degradation** — late laps where the slope steepens (may or may not be a cliff).

Compound-specific default warm-up lengths (FIA tyre testing, Pirelli media briefings 2024–2026):

```python
DEFAULT_WARMUP_LAPS = {
    "soft": 1,
    "medium": 2,
    "hard": 3,
    "intermediate": 1,
    "wet": 1,
}
```

Algorithm in a new helper `compute_warmup_partition(lap_times, tyre_ages, compound, fuel_corrected)`:

1. Look up `default_warmup = DEFAULT_WARMUP_LAPS.get(compound.lower(), 2)`.
2. If stint length ≥ `default_warmup + 5`, fit a 2-line piecewise regression on `(tyre_age, fuel_corrected)` over candidate warm-up breakpoints in `range(1, default_warmup + 2)`. Pick the breakpoint that minimises SSE while keeping the warm-up segment slope ≤ 0 (lap times falling) and the peak segment slope ≥ 0 (lap times rising or flat).
3. If no candidate satisfies the sign constraint (e.g., a stint that starts already at peak — common on used tyres after a red flag restart), set `warmup_lap_count = 0` and label the entire stint `peak → degradation`.
4. For the degradation cut-off, **reuse** the existing `_detect_cliff()` if it fires; otherwise pick the lap where the rolling 3-lap slope first exceeds `1.5×` the peak-segment slope, with a minimum of `0.05 s/lap` absolute increase to avoid noise.
5. Output added to each stint dict:

```python
'warmup_lap_count': int,            # may be 0
'warmup_end_tyre_age': int | None,  # last tyre age still considered warm-up
'peak_lap_count': int,
'peak_slope_s_per_lap': float,
'degradation_start_tyre_age': int | None,  # first tyre age in degradation phase
'degradation_lap_count': int,
'degradation_slope_s_per_lap': float | None,
'phase_confidence': "low" | "moderate" | "high",
```

`phase_confidence` is "high" if all three phases have ≥ 4 laps each, "moderate" if any phase has 2–3 laps, "low" if a phase is collapsed to 0 or 1 lap.

### Frontend touches

`DegTrendChart.jsx` currently shows one (or, post-cliff, two) regression segments. Extend to:

- Color the warm-up segment (lap-times falling) in a cool tone — e.g. `hsl(210 70% 50%)`.
- Color the peak segment in the existing compound color.
- Color the degradation segment in the warning color already used for cliffs.
- Add a one-line caption: *"Warm-up: 2 laps (-0.32 s/lap improvement) → Peak: 9 laps (+0.04 s/lap) → Deg: 5 laps (+0.18 s/lap)"*. Skip phases with `0` laps.

### Acceptance criteria

- A synthetic stint with `[+0.4, +0.2, 0.0, +0.05, +0.07, +0.20, +0.25]` improvements/regressions correctly returns `warmup_lap_count=2`, `peak_lap_count=3`, `degradation_lap_count=2`.
- A flat-from-the-start stint (used tyres after a red flag) returns `warmup_lap_count=0` without raising.
- A 6-lap short stint (below `default_warmup + 5`) returns `phase_confidence="low"` and skips partitioning.
- `_detect_cliff()` continues to work and its `cliff_tyre_age` aligns with `degradation_start_tyre_age` when both fire on the same stint.
- Tyre-guidance language in `chat.py` updated: *"Distinguish warm-up improvement, peak degradation, and the cliff. Don't call a slow first lap 'degradation' — it's normal warm-up."*

### References

- Pirelli pre-season tyre brief (2025) — compound warm-up windows.
- RaceWatch / Pirelli stint analysis methodology, public sample reports.

---

## Task 3 (F29) — Wet-session handling

Files:

- Modify: `server/f1_data.py` — new `is_wet_session()` helper; gating in `analyze_cornering_loads`, `_fit_stint_degradation`, and tyre-warmup partitioning.
- Modify: `server/chat.py` — refusal language in cornering and warmup widgets; pass `weather_state` through every widget that depends on grip.
- Modify: relevant React widgets to render a "WET SESSION" header banner.
- Test: `server/tests/test_f1_data.py` (`TestWetSessionDetection`).

### Change description

Add a helper:

```python
def is_wet_session(session) -> dict:
    """Classify a session as dry, intermediate, or full wet based on weather_data and tyre usage.

    Returns:
        {
            "state": "dry" | "damp" | "wet",
            "rainfall_observed": bool,
            "rainfall_fraction": float,   # 0..1, fraction of session minutes with Rainfall=True
            "wet_compounds_used": list[str],  # e.g. ["INTERMEDIATE", "WET"]
            "confidence": "low" | "moderate" | "high",
        }
    """
```

Decision logic:

1. `weather = session.weather_data` (already used at f1_data.py:6164). If empty → return `state="dry"`, `confidence="low"`.
2. `rainfall_fraction = sum(weather["Rainfall"]) / len(weather)`.
3. Pull stint compounds from `session.laps`; collect any in `{"INTERMEDIATE", "WET"}`.
4. Rules:
   - `rainfall_fraction > 0.4` OR `"WET" in wet_compounds_used` → `state="wet"`.
   - `0.1 < rainfall_fraction <= 0.4` OR `"INTERMEDIATE" in wet_compounds_used` → `state="damp"`.
   - else → `state="dry"`.
5. `confidence`: "high" if both signals agree, "moderate" if only one, "low" if `weather_data` was sparse (<10 samples).

### Where to gate

The following functions currently treat all sessions as dry. After this task, each must check `is_wet_session()` and either refuse, or annotate, or switch compound axes:

| Function | Wet behaviour |
|---|---|
| `analyze_cornering_loads()` | If `state="wet"`: **refuse** with explanation that lateral-G and Vmin heuristics calibrated for dry sessions don't transfer (driver is line-hunting, not commitment-hunting). Surface this as a `refusal` field. |
| `_fit_stint_degradation()` | If `state="wet"`: skip cliff detection and warm-up partitioning; emit a stint dict with `wet_session: True`, no phase fields. Cliff fields are misleading when grip is changing track-condition-driven, not tyre-age-driven. |
| `compute_warmup_partition()` | Switch `DEFAULT_WARMUP_LAPS` lookup table: `intermediate: 1`, `wet: 1`. (Both warm up fast; the wet compound is essentially always above operating temperature on a wet track.) |
| `get_speed_trap_leaderboard()` | Annotate `weather_state` on the response; DRS effect on top speed is dwarfed by wet braking limits at corner exits, so don't refuse but do flag. |

### Compound axis

`server/f1_data.py` should expose a small constant:

```python
WET_TYRE_COMPOUNDS = ("INTERMEDIATE", "WET")
DRY_TYRE_COMPOUNDS = ("SOFT", "MEDIUM", "HARD")
```

…and any widget that draws a compound legend must use the wet axis when `weather_state in ("damp", "wet")`.

### Frontend touches

Every widget that consumes `weather_state` should render a header pill:

```jsx
{state === "wet" && <Badge variant="warning">WET SESSION</Badge>}
{state === "damp" && <Badge variant="muted">DAMP CONDITIONS</Badge>}
```

The `CornerComparisonWidget` should display the refusal payload inline (use the existing refusal-card style from the `data_table` widget).

### Acceptance criteria

- `is_wet_session(mock_session)` returns `state="wet"` for a session whose mocked `weather_data` has `Rainfall=True` in > 40% of rows.
- `analyze_cornering_loads()` on a wet session returns `{"refusal": "..."}` not partial garbage.
- Spa 2021 race (or any synthesised wet-session fixture) produces a degradation-trend widget with `wet_session: True` and no cliff fields.
- Driver/team analysis prompts now hedge in wet conditions: *"This session was wet; standard dry-condition pace and cornering heuristics don't apply."*
- `server/tests/test_f1_data.py::TestWetSessionDetection` covers dry, damp, and wet fixtures.

### References

- FastF1 `weather_data` schema docs.
- Pirelli wet-tyre brief: Inter operating window ~10–40 mm of standing water; full wet > 25 mm.

---

# Phase 2 — Analytical depth (~3 weeks)

Six features that materially deepen what the assistant can answer. None of these change existing output's *correctness* the way Phase 1 does — they expand the *vocabulary*.

## Task 4 (F22) — Mini-sectors heatmap and delta-by-distance

Files:

- Modify: `server/f1_data.py` — add `compute_mini_sectors(lap, n=25)`.
- Modify: `server/tools.py` — add `compare_mini_sectors` tool.
- Modify: `server/chat.py` — `_make_mini_sector_heatmap_widget()`.
- New: `client/src/components/chat-widgets/MiniSectorHeatmapWidget.jsx`.
- Modify: `client/src/components/AnswerRenderer.jsx` (add `mini_sector_heatmap` case).
- Test: `server/tests/test_f1_data.py` (`TestMiniSectors`).

### Change description

```python
def compute_mini_sectors(lap, n: int = 25) -> list[dict]:
    """
    Split a lap into n equal cumulative-distance segments.

    Returns:
        [
          {
            "index": 0,
            "start_m": 0.0,
            "end_m": 211.4,
            "time_s": 4.183,
            "avg_speed_kmh": 182.5,
            "min_speed_kmh": 178.1,
            "drs_active_pct": 0.0,
          },
          ...
        ]
    """
```

Implementation:

1. Get telemetry via `lap.get_car_data().add_distance()`.
2. Compute `total_distance = telemetry["Distance"].iloc[-1]`.
3. `boundaries = np.linspace(0, total_distance, n + 1)`.
4. For each segment, slice by `Distance` between boundaries, integrate time (`Time` deltas) and compute aggregates.

Then add a tool `compare_mini_sectors(driver_a, driver_b, lap_number, round_number, session_type)`:

- Calls `compute_mini_sectors` on each driver's lap.
- Returns per-segment `delta_s` (A − B), cumulative delta along distance, and per-segment winner.

`_make_mini_sector_heatmap_widget()` packages:

```python
{
    "type": "mini_sector_heatmap",
    "driver_a": "VER",
    "driver_b": "NOR",
    "lap_number": 21,
    "segments": [
        {"index": 0, "start_m": 0, "end_m": 211, "delta_s": -0.023, "winner": "B"},
        ...
    ],
    "cumulative_delta": [(0, 0.0), (211, -0.023), (422, -0.041), ...],
    "total_delta_s": -0.213,
    "weather_state": "dry",
    "drs_mix_warning": bool,  # true if drivers' DRS use diverged in any segment
}
```

### Frontend touches

`MiniSectorHeatmapWidget.jsx`:

- Top: track map (use the existing `track_map` SVG renderer if possible). Each of the 25 segments colored by winner — driver A blue, driver B orange, gray for `|delta_s| < 0.005`.
- Bottom: delta-by-distance line chart. X = cumulative distance (m). Y = cumulative `delta_s`. Mark mini-sector boundaries as faint vertical ticks.
- Footer: total lap delta, segments won A vs B, and the DRS-mix warning if set.

Performance: see Risk #2. Mini-sector compute must memoise per `(round, session, driver, lap)`.

### Acceptance criteria

- `compute_mini_sectors(lap, n=25)` returns 25 segments whose `(end_m - start_m)` sums to within 1 m of total lap distance.
- Segment times sum to within 5 ms of the underlying `LapTime`.
- For VER vs NOR Q3 (any 2024 race fixture), `compare_mini_sectors` returns a `total_delta_s` that matches the lap-time gap to within 20 ms.
- Widget renders 25 colored segments on the track map.
- DRS mix warning fires when one driver had DRS open in segment k and the other did not.

### References

- MultiViewer F1 1.13+ mini-sector overlay (visual reference).
- Public F1 broadcast graphics — 25-sector colored splits used during qualifying replays.

---

## Task 5 (F23) — Three-phase corner decomposition

Files:

- Modify: `server/f1_data.py` — extend `analyze_cornering_loads()` (line 5465) and `compare_corner_profiles()` (line 4801).
- Modify: `server/chat.py` — `_make_corner_comparison_widget()` (line 251) — produce three sub-tables.
- Modify: `client/src/components/chat-widgets/CornerComparisonWidget.jsx`.
- Test: `server/tests/test_f1_data.py` (`TestCornerPhases`).

### Change description

For each corner in the corner table, decompose into three phases:

**Phase 1 — Entry braking:**

- `brake_onset_distance_m` — distance before the apex where `Brake` channel goes 0 → 1.
- `brake_release_distance_m` — distance where `Brake` returns to 0.
- `brake_zone_length_m` — `onset − release`.
- `brake_release_to_apex_m` — how far past brake release the car keeps decelerating (proxy for trail-braking depth).

> **Brake-pressure proxy.** FastF1 publishes `Brake` as a 0/1 binary in most years. We **cannot** report peak brake pressure. Replace the original spec's "peak brake pressure" with `brake_zone_length_m` and `brake_release_rate_m_per_s` (rate of distance covered after brake release relative to speed delta). Document this substitution in the tool docstring so the LLM doesn't claim "peak pressure".

**Phase 2 — Apex (Vmin):**

- `vmin_kmh` — minimum speed inside the corner.
- `vmin_distance_m` — where it occurred.
- `apex_vmin_std_kmh` — standard deviation of Vmin across the driver's session laps (consistency metric). Requires sampling all session laps; cache per session.
- `time_above_vmin_plus_5_pct_s` — quick-apex vs sustained-apex signature.

**Phase 3 — Exit drive:**

- `time_to_full_throttle_s` — seconds between Vmin sample and first sample with `Throttle == 100`.
- `exit_speed_plus_50m_kmh` — speed 50 m after the apex.
- `exit_speed_plus_150m_kmh` — speed 150 m after the apex (catches the "long exit" effect).

### Three sub-table widget

`CornerComparisonWidget.jsx` currently renders one composite table per corner. Replace with three stacked sub-tables labelled "Entry", "Apex", "Exit". Each sub-table shows driver A vs driver B for the metrics above. Color the row red if the deficit is > 0.05 s in time-equivalent terms (use the existing time-delta heuristic the widget already has).

### Acceptance criteria

- `analyze_cornering_loads()` returns three nested dicts per corner: `entry`, `apex`, `exit`.
- `apex.apex_vmin_std_kmh` is computed across all valid clean laps in the session, not just the reference lap.
- For Monaco T6 (slow hairpin), `entry.brake_zone_length_m` ranges roughly 50–80 m for top-team drivers; values outside [30, 120] flag a data-quality issue.
- The widget renders three sub-tables and the assistant text references "entry", "apex", "exit" phases when answering corner-comparison prompts.
- A test fixture of a synthetic lap with a 100-m brake zone, Vmin of 90 km/h, and full-throttle reached 1.4 s after apex recovers all three metrics to within 1% / 0.05 s.

### References

- MoTeC i2 / ATLAS corner-profile screenshots: standard three-phase split.
- Pure-grip corner studies (Vmin std as consistency metric) — F1Dash's own `corner_analysis` widget rationale doc.

---

## Task 6 (F24) — Friction-circle / g-g diagram

Files:

- Modify: `server/f1_data.py` — new `compute_friction_circle(lap)`.
- Modify: `server/chat.py` — `_make_friction_circle_widget()`.
- New: `client/src/components/chat-widgets/FrictionCircleWidget.jsx`.
- Modify: `client/src/components/AnswerRenderer.jsx`.
- Test: `server/tests/test_f1_data.py` (`TestFrictionCircle`).

### Change description

```python
def compute_friction_circle(lap) -> dict:
    """
    Returns array of (lat_g, long_g) tuples sampled along the lap, plus
    summary stats: max_lat_g, max_long_g_brake, max_long_g_accel.

    lat_g is derived by FastF1 from speed and track curvature.
    long_g is derived from dV/dt.
    Both are noisy at low speed; we filter out samples with speed < 60 km/h.
    """
```

Implementation:

1. `tel = lap.get_car_data().add_distance()`.
2. Convert `Speed` (km/h) to m/s.
3. `long_g = numpy.gradient(speed_ms, time_s) / 9.81`.
4. `lat_g` is provided by FastF1's derived telemetry — if missing, compute from `pos = lap.get_pos_data()` curvature: `kappa = |dθ/ds|` then `lat_g = v² · κ / 9.81`.
5. Filter samples with `Speed < 60 km/h` (pit lane and rolling starts dominate noise there).
6. Return the (lat, long) array plus summary stats.

Tool registration — add `get_friction_circle(driver, lap_number, round_number, session_type)` as a primitive in `tools.py`.

### Frontend touches

`FrictionCircleWidget.jsx`:

- Scatter plot — `lat_g` on X, `long_g` on Y. Positive Y = braking (convention varies; pick MoTeC's convention: +Y = braking, –Y = accelerating, ±X = lateral).
- Reference circles drawn at 1, 2, 3, 4 G with light gray strokes and labels.
- Color samples by speed (cool = low, warm = high) — gives the viewer a sense of where the highest combined loads occur.
- Optional hexbin density when sample count > 2000 (the scatter becomes a smear).
- Below the plot: peak lat/long stats and the "fraction of samples within 0.9 G of the limit envelope" — a single-number proxy for how aggressively the car was driven.

### Acceptance criteria

- `compute_friction_circle(synthetic_lap)` on a lap built from a constant-radius circle at 200 km/h reports `max_lat_g ≈ v²/(R·g)` within 5%.
- Scatter renders ≤ 5000 points (subsample if more); hexbin path triggers above that threshold.
- Reference circles render at exactly 1, 2, 3, 4 G.
- The widget surfaces the FastF1-derived caveat in a small footnote: *"Lateral and longitudinal G are derived (not raw IMU); treat absolute peaks ±5%."*

### References

- MoTeC i2 user guide § "g-g diagram".
- Heilmeier et al., *Race-simulation* paper (2018) — uses the same friction-ellipse abstraction.

---

## Task 7 (F25) — Trail-brake quantification

Files:

- Modify: `server/f1_data.py` — new `compute_trail_brake_metric(lap, corner_id)`.
- Modify: `analyze_cornering_loads()` — surface `trail_brake_index` per corner.
- Test: `server/tests/test_f1_data.py` (`TestTrailBrake`).

### Change description

The original spec calls for `dP_brake / dδ_steering` between brake-release-onset and steering-peak. **Both inputs are partially unavailable**:

- `P_brake` is a 0/1 binary; we cannot differentiate it.
- `δ_steering` is not exposed by FastF1; we must proxy it from `pos_data` heading curvature (`θ = atan2(dY, dX)`; steering proxy `δ ≈ d²θ/dt²` low-passed).

Re-formulate the metric:

```python
def compute_trail_brake_metric(lap, corner_id: int) -> dict:
    """
    Trail-brake proxy: fraction of the steering-input window during which the
    brake channel is still active.

    Specifically:
      - Identify the corner's brake-onset and brake-release samples.
      - Identify the corner's steering-rate peak from |d²θ/dt²| on pos_data.
      - Compute fraction = (samples with Brake=1 AND steering-rate > 50% of peak)
                          / (samples with steering-rate > 50% of peak)
      - Range 0..1. Higher = more aggressive trail-braker.

    Returns:
        {
            "trail_brake_index": float,        # 0..1, None if data unavailable
            "brake_release_into_apex_m": float,  # distance brake was released past steering onset
            "steering_proxy_used": True,       # always True until FastF1 exposes steering
            "confidence": "low" | "moderate",
        }
    """
```

`confidence = "low"` always until FastF1 exposes raw steering — make this contract explicit. The metric is **directional**, not absolute. Drivers can be ranked by this index for the *same* corner across the same session, but cross-circuit comparisons are not meaningful.

`analyze_cornering_loads()` adds per-corner `trail_brake_index`, with the LLM instructed to say *"trail-braking proxy"* not *"trail-braking metric"* whenever `steering_proxy_used` is true.

### Acceptance criteria

- Returns `None` and `confidence="low"` for laps with < 100 samples in the corner window.
- For a synthetic corner where brake releases exactly at steering peak, index ≈ 0.5 (half the steering window overlaps braking).
- For a synthetic late-trail-braker (brake holds until steering peak), index ≈ 1.0.
- For a synthetic threshold-brake-then-release-then-turn driver, index ≈ 0.0.
- `analyze_cornering_loads()` returns per-corner `trail_brake_index` and the assistant text uses "trail-braking proxy" phrasing.

### References

- McLaren Applied ATLAS "Brake/Steer overlay" — same diagnostic intent.
- F1Dash own `corner_analysis` widget — already discusses "commitment" and "technique"; this is the missing braking-side metric.

---

## Task 8 (F26) — Understeer / oversteer balance index

Files:

- Modify: `server/f1_data.py` — new `compute_balance_index(lap)`.
- Modify: `server/tools.py` — new tool `analyze_car_balance(driver, lap_number, round_number, session_type)`.
- Modify: `server/chat.py` — `_make_balance_widget()`.
- New: `client/src/components/chat-widgets/BalanceWidget.jsx`.
- Modify: `client/src/components/AnswerRenderer.jsx`.
- Test: `server/tests/test_f1_data.py` (`TestBalanceIndex`).

### Change description

Canonical formula:

```text
expected_yaw_rate = v · δ / (L · (1 + Kus · v²))
balance_residual = measured_yaw_rate − expected_yaw_rate
```

Where `L` is wheelbase (~3.6 m for current-era F1) and `Kus` is the understeer gradient (≈ 0.002 s²/m as a generic placeholder; teams tune per car). Positive residual = oversteer (car yawing faster than steering input commands); negative = understeer.

**Critical issue:** we have neither raw steering (`δ`) nor raw yaw rate. Both must be proxied:

- `δ` proxied as in F25 from `pos_data` heading angle.
- `yaw_rate` proxied as `dθ/dt` from `pos_data` heading.

This makes the formula **doubly derived** and the absolute residual numbers are not trustworthy. What *is* trustworthy is the **sign and relative magnitude** of the residual across corners on the same lap, because both proxies share the same noise floor and any constant calibration error cancels in cross-corner comparisons.

Implementation contract:

```python
def compute_balance_index(lap) -> dict:
    """
    Returns per-corner balance estimates.

    Output:
        {
            "global_signature": "neutral" | "understeer_bias" | "oversteer_bias",
            "wheelbase_m": 3.6,
            "kus_used": 0.002,
            "corners": [
                {
                    "corner_id": 5,
                    "vmin_kmh": 92,
                    "balance_residual": float,   # rad/s, raw
                    "label": "neutral" | "understeer" | "oversteer",
                    "confidence": "low",         # always "low" — both inputs proxied
                },
                ...
            ],
            "caveat": "Steering and yaw rate are derived from GPS heading; absolute values are not reliable.",
        }
    """
```

Decision thresholds for labels (calibrated against a couple of known-balance laps in test fixtures):

- `|residual| < 0.05 rad/s` → "neutral".
- `residual > +0.05` → "oversteer".
- `residual < −0.05` → "understeer".

Tool registration: `analyze_car_balance(driver, lap_number, round_number, session_type)` → returns the dict above.

### Widget

`BalanceWidget.jsx` — small table: one row per corner, columns `corner_id`, `Vmin`, `label` (chip with color), and a one-line `global_signature` at the top. No fancy time-series plot — the data is too noisy to be useful as a trace.

System-prompt line: *"When summarising car balance from `analyze_car_balance`, always say 'tendency' not 'measurement'. The steering and yaw inputs are derived from GPS, not raw IMU."*

### Acceptance criteria

- Returns `confidence="low"` on every corner — non-negotiable until FastF1 ships raw steering.
- Synthetic lap with constant-radius corner at constant speed (no yaw acceleration) labels every corner "neutral".
- Synthetic lap where heading angle leads steering input (proxied) by 0.1 rad labels at least one corner "oversteer".
- The widget renders a "PROXY — DIRECTIONAL ONLY" badge prominently.
- LLM responses do not produce phrases like "the car had 0.07 rad/s of oversteer"; only "the car showed an oversteer tendency in T3".

### References

- Milliken & Milliken, *Race Car Vehicle Dynamics* — § "Steady-state yaw response".
- Heilmeier et al., *Race-simulation* paper — same `Kus` parameterisation.
- Public McLaren engineering blog (2024) on balance diagnosis from telemetry.

---

## Task 9 (F28) — Racing-line spatial deviation from optimal

Files:

- Modify: `server/f1_data.py` — new `compute_line_deviation(lap, reference_lap)`.
- Modify: `compare_drivers()` and `compare_corner_profiles()` — surface deviation in output.
- Modify: existing comparison widgets — render a side-lane deviation trace.
- Test: `server/tests/test_f1_data.py` (`TestLineDeviation`).

### Change description

```python
def compute_line_deviation(lap, reference_lap) -> dict:
    """
    Per-mini-sector lateral offset (m) of `lap` from `reference_lap`.

    Algorithm:
      1. Resample reference lap's (X, Y) at uniform distance intervals (n=200).
      2. For each resampled reference point, find the nearest point on `lap`'s
         trajectory and compute signed lateral offset (sign = left/right of
         reference travel direction).
      3. Aggregate offsets into n=25 mini-sectors (mean and max within each).

    Returns:
        {
            "reference_driver": "VER",
            "reference_lap_number": 21,
            "comparator_driver": "NOR",
            "comparator_lap_number": 21,
            "segments": [
                {"index": 0, "mean_offset_m": -0.34, "max_offset_m": -1.12, "direction": "inside"},
                ...
            ],
            "max_deviation_m": float,
            "max_deviation_segment_index": int,
        }
```

Geometry helper: signed perpendicular distance from a point to the reference travel direction is `((p − r) × t̂)` where `t̂` is the unit tangent of the reference path.

### Surfacing

- `compare_drivers()` widget gets a new "Line deviation" row in its summary table.
- `compare_corner_profiles()` widget overlays the comparator driver's line on the existing track map (already used in `corner_comparison`) with the inside/outside color split.
- A new field `max_deviation_m > 1.5 m` triggers a comment in the assistant response: *"X took a noticeably different line through T7 — about 1.7 m inside Y's reference line."*

### Acceptance criteria

- Reference lap compared to itself returns `max_deviation_m < 0.1 m`.
- A synthetic comparator lap shifted 0.5 m to the right everywhere returns `mean_offset_m ≈ 0.5` in every segment.
- The track-map overlay in `corner_comparison` widget renders two distinct paths through high-deviation corners.
- The signed-offset convention (positive = right of reference) is documented in the helper docstring and consistent across all consumers.

### References

- MoTeC "Track Centre" template — same lateral-offset visualisation.
- Public ATLAS racing-line traces shown in 2024 broadcast graphics.

---

# Phase 3 — Research-grade fingerprinting (~3 weeks)

## Task 10 (F30) — Data-derived driver style fingerprint

Files:

- New: `server/style_fingerprint.py`.
- Modify: `server/tools.py` — add `get_driver_style_fingerprint` tool.
- Modify: `server/chat.py` — `_make_style_fingerprint_widget()`; tie fingerprint into existing driver-style narrative.
- Modify: `server/driver_styles.py` — optional consumer that augments the static profile with the derived fingerprint when present.
- New: `client/src/components/chat-widgets/StyleFingerprintWidget.jsx`.
- Modify: `client/src/components/AnswerRenderer.jsx`.
- Test: `server/tests/test_style_fingerprint.py` (new file).

### Change description

A per-event, per-driver style vector derived from session telemetry. The static `DRIVER_STYLES` dict gives editorial context; this is the empirical mirror.

Feature vector (per driver, per session, across all clean laps):

```python
{
    "brake_release_rate_normalised": float,   # how fast Brake channel falls — proxy via samples covered
    "throttle_onset_rate_pct_per_s": float,   # avg slope of throttle from 0 to 100% after each apex
    "vmin_std_kmh": float,                    # consistency: low = repeatable apex
    "mid_corner_steering_velocity": float,    # proxy steering-rate (rad/s) sampled at Vmin
    "exit_throttle_slope_s": float,           # time from Vmin to full throttle, averaged
    "brake_zone_length_std_m": float,         # consistency of brake-zone-length across laps
    "trail_brake_index_mean": float,          # from F25
    "balance_signature": str,                 # from F26 — "understeer_bias" / "neutral" / "oversteer_bias"
}
```

Aggregation rules:

- Drop the slowest 25% of clean laps per driver before computing.
- Drop outliers > 2σ in any single feature.
- Require ≥ 8 clean laps for "high" confidence, 4–7 for "moderate", < 4 for "low".

### Optional: cross-driver outlier flagging

Compute z-scores per feature across all drivers in the session. Flag drivers whose absolute z-score exceeds 2.0 in any feature:

```python
{
    "outliers": [
        {"driver": "HAM", "feature": "throttle_onset_rate_pct_per_s", "z": -2.4,
         "interpretation": "Throttle ramp 24% slower than session mean — patient exit signature."},
        ...
    ],
}
```

This is the "who's doing something unusual today?" signal — useful for race-recap narratives.

### Optional: clustering

K-means (k=3) across the standardised feature vectors, surfaced as cluster labels: *"smooth/measured cluster"*, *"aggressive/late-brake cluster"*, *"adaptive/inconsistent cluster"*. Use `sklearn.cluster.KMeans` if available; otherwise hand-roll a 3-centroid k-means in pure NumPy. Cluster labels are derived from the **dominant feature direction** of each centroid, not hardcoded names — log the dominant feature so the chat layer can describe it.

### Widget

`StyleFingerprintWidget.jsx`:

- Radar chart with one axis per feature (normalised to 0..1 by session-min/max).
- Two overlay options: the static `DRIVER_STYLES` editorial profile (where it has comparable fields) and the derived fingerprint. Visualises agreement or disagreement.
- Footer: outlier flags and cluster label.

### Driver-style hedging

When `chat.py` injects driver-style narrative and a fingerprint exists for the current session, the prompt prefers empirical claims and treats the static profile as background colour:

> *"Based on this session's telemetry, Norris's style fingerprint shows a measured throttle onset (slope 18%/s vs session mean 22%/s) and high apex repeatability (Vmin σ = 0.6 km/h). The editorial profile describes him as a smooth-style driver; the data agrees."*

When the static profile and fingerprint disagree, surface that explicitly:

> *"The editorial profile describes Hamilton as an aggressive late-braker, but this session's fingerprint shows an unusually long brake zone (+22% vs his career baseline). Possibly nursing rear tyres, brakes, or a setup compromise."*

### Acceptance criteria

- Fingerprint computation completes in < 5 s per driver per session on cached data.
- All features return non-`None` for a complete dry session with ≥ 8 clean laps.
- Outlier detection identifies a synthetic "throttle-stab" driver with 3σ on `throttle_onset_rate` as an outlier.
- Cluster assignment is stable: same input data → same cluster label across runs (use seed in k-means).
- Chat answers tagged as "based on this session's data" rather than "his usual style" when a fingerprint is present.
- Widget renders the radar chart and shows agreement/disagreement with static profile.

### References

- *Race Engineering Analytics* (DiResta et al., SAE 2019) — driver style clustering from telemetry.
- F1Dash own `driver_styles.py` — the qualitative profile this empirical fingerprint complements.

---

## FastF1 Data Availability Summary

| Feature | Required channels | Available today | Action |
|---|---|---|---|
| F21 DRS awareness | `DRS` | Yes | Implement. |
| F22 mini-sectors | `Distance`, `Speed`, `Time` | Yes | Implement. |
| F23 corner phases | `Brake` (binary), `Speed`, `Throttle`, `Distance` | Partial — peak pressure not available | Reformulate around brake-zone *length* instead of pressure. |
| F24 g-g diagram | derived `lat_g`, `long_g` | Yes (derived) | Document derived-data caveat. |
| F25 trail-brake | `Brake`, **steering** | Steering NOT exposed | Use heading-curvature proxy; confidence always "low". |
| F26 balance index | **steering**, **yaw rate** | Neither exposed | Doubly-proxied; report tendency only. |
| F27 warmup partition | lap times, compound, tyre age | Yes | Implement. |
| F28 line deviation | `X`, `Y`, `Distance` | Yes | Implement. |
| F29 wet detection | `weather_data`, compound list | Yes | Implement. |
| F30 fingerprint | aggregation over the above | Inherits caveats | Tag confidence aggressively. |

---

## Frontend Touches Summary

| File | Change |
|---|---|
| `SpeedTraceWidget.jsx` | DRS-active band; DRS badge on row. |
| `CornerComparisonWidget.jsx` | Three sub-tables (entry/apex/exit); line-deviation overlay. |
| `DegTrendChart.jsx` | Three-color phase segments; warm-up caption. |
| `MiniSectorHeatmapWidget.jsx` *(new)* | Track map heatmap + delta-by-distance line chart. |
| `FrictionCircleWidget.jsx` *(new)* | g-g scatter / hexbin with reference circles. |
| `BalanceWidget.jsx` *(new)* | Per-corner balance table with "PROXY" badge. |
| `StyleFingerprintWidget.jsx` *(new)* | Radar chart; static-vs-derived overlay. |
| `AnswerRenderer.jsx` | New widget-type cases: `mini_sector_heatmap`, `friction_circle`, `car_balance`, `style_fingerprint`. |
| All wet-affected widgets | Header "WET SESSION" / "DAMP CONDITIONS" badge. |

---

## Validation Checklist

Phase 1 — correctness:

- [ ] `drs_active()` correctly maps DRS channel encodings.
- [ ] `get_speed_trap_leaderboard()` refuses mixed-DRS comparisons by default.
- [ ] `get_lap_telemetry()` samples carry `drs_active: bool`.
- [ ] `SpeedTraceWidget` renders DRS band and badge.
- [ ] `compute_warmup_partition()` produces three phases on a normal stint, gracefully skips on short/anomalous stints.
- [ ] `DegTrendChart` shows three colored segments and caption.
- [ ] `is_wet_session()` returns the documented classification for dry / damp / wet fixtures.
- [ ] `analyze_cornering_loads()` refuses on wet sessions.
- [ ] `_fit_stint_degradation()` sets `wet_session: True` and omits phase fields on wet.

Phase 2 — depth:

- [ ] `compute_mini_sectors(n=25)` sums to lap distance within 1 m.
- [ ] `compare_mini_sectors` total delta matches lap-time delta within 20 ms.
- [ ] Corner output exposes `entry`, `apex`, `exit` sub-dicts on every corner.
- [ ] `apex_vmin_std_kmh` computed across all clean laps, not just reference.
- [ ] `compute_friction_circle()` returns max_lat_g within 5% on synthetic constant-radius lap.
- [ ] `trail_brake_index` always carries `steering_proxy_used: True` and `confidence: "low"`.
- [ ] `compute_balance_index()` labels neutral / understeer / oversteer; never emits absolute numbers in chat copy.
- [ ] `compute_line_deviation()` returns < 0.1 m on self-comparison; consistent sign convention.

Phase 3 — fingerprint:

- [ ] Fingerprint vector populated for every clean session with ≥ 8 clean laps per driver.
- [ ] Outlier detection flags synthetic 3σ outliers.
- [ ] Cluster assignment stable under fixed seed.
- [ ] Chat answers prefer empirical fingerprint over static profile when available.
- [ ] StyleFingerprintWidget renders radar chart with both overlays.

Cross-cutting:

- [ ] `python -m pytest server/tests/ -v` passes.
- [ ] `npm run build` passes.
- [ ] End-to-end chat smoke test for "compare VER and NOR through sector 2" returns a mini-sector widget.
- [ ] End-to-end chat smoke test for a 2021 Spa-style wet fixture surfaces wet-session banner and refusal where appropriate.

---

## Risks and Open Questions

| Risk | When it triggers | Proposed resolution | Decision needed by |
|---|---|---|---|
| **F26 yaw rate is not raw IMU; both inputs are derived from GPS heading.** Absolute residuals will be unreliable; only sign and cross-corner ranking is meaningful. | Every F26 invocation. | Make `confidence: "low"` non-negotiable; LLM language must say "tendency" not "measurement"; widget shows a "PROXY — DIRECTIONAL ONLY" badge. Consider deferring F26 to Phase 3 if reviewers find the proxy too weak. | Pre-implementation of F26. |
| **F22 performance: 25 mini-sectors × 20 drivers × 60 laps = 30,000 segment computations per request.** Cold cache could push response times over 10 s. | Whenever a chat question triggers `compare_mini_sectors` across more than 2 drivers, or a session-wide mini-sector heatmap is requested. | (a) Memoise per `(round, session, driver, lap)` keyed on `Distance`-resampled telemetry; (b) restrict the v1 tool signature to two-driver, single-lap comparisons; (c) precompute mini-sector tables for the reference (fastest) lap in `_warm_session_cache()` if it exists. **Recommend (b) for v1; add (a) and (c) as Phase 2 polish.** | F22 implementation. |
| **FastF1 may not expose `Brake` as analog in some 2026 sessions.** Already a known issue in 2024. | F23, F25 features. | Detect at call time: if `Brake` has > 5 distinct values, treat as analog (rare); otherwise fall back to binary-only metrics and surface a caveat. | F23 implementation. |
| **GPS-derived heading angle is noisy in slow corners (< 80 km/h).** F25 / F26 proxies degrade. | Monaco, hairpins, chicanes. | Skip the proxy on samples with `Speed < 60 km/h`; document the gap. | F25 / F26 implementation. |
| **`session.weather_data` can be sparse (early sessions or wet-on-wet sessions where rain is intermittent).** | F29. | Require ≥ 10 weather samples for `confidence != "low"`. If sparse, also inspect tyre compound usage as a secondary signal. | F29 implementation. |
| **The "default warm-up laps" table is hand-calibrated.** Pirelli compound nomenclature shifts year-to-year (C0–C6 range). | Every F27 invocation. | Use the FastF1 `Compound` field's tag (`SOFT` / `MEDIUM` / `HARD`) — these are the broadcast-level labels, stable across years. The C0–C6 mapping doesn't matter for the partition. | F27 implementation. |
| **F30 cluster labels are ad-hoc; risk of confidently mislabeling drivers.** | Phase 3. | Cluster labels derived from dominant feature direction of each centroid, **not hardcoded names**. Chat layer describes the dominant feature ("longer brake zones, lower throttle slope") rather than calling a driver "aggressive" or "smooth". | F30 implementation. |
| **DRS refusal might be over-eager.** A user comparing race-day pace might *want* the DRS-mixed top-speed comparison because both drivers were in race-trim. | F21. | The `allow_mixed_drs` flag exists. System-prompt guidance: refuse in qualifying contexts; allow in race contexts unless the user explicitly asks about engine/aero. | F21 implementation. |
| **F23 brake-pressure-equivalent metric is brake-zone *length*, not pressure.** A driver braking harder over a shorter distance looks identical to one braking softer over a longer distance with the same Vmin. | Every F23 use. | Document the limitation clearly. Augment with `time_above_vmin_plus_5_pct_s` and `vmin_distance_m` from Phase 2 so the LLM has multiple corner-character signals. | F23 implementation. |
| **F28 line deviation requires matched cumulative-distance markers between two laps.** Laps with different routes through chicanes (e.g., kerb-hopping) won't align cleanly. | Tracks with high kerb usage (Monza T1, Imola Variante Alta). | Nearest-neighbour matching in (X, Y) rather than cumulative-distance index; deal with the up-to-30 cm error this introduces in the docstring caveat. | F28 implementation. |
| **F30 outlier z-scores can mislead with small driver counts.** Only 4–5 drivers in P1 sessions; z-scores explode. | Practice sessions, sprint sessions. | Require ≥ 10 drivers in the session for outlier detection; below that, skip the outliers block entirely. | F30 implementation. |

### Refresh cadence

Re-verify FastF1 channel coverage at the start of each season; add a one-line check to `server/tests/test_f1_data.py` that imports a current-season fixture and asserts the expected channels are present. Update the FastF1 availability table above when channels change.

---

## Commit Plan

Phase 1 (small, focused commits — these change current output):

1. `fix: drs-state awareness for speed trap leaderboard and speed trace` (F21).
2. `feat: three-phase tyre warm-up / peak / degradation partition` (F27).
3. `feat: wet-session detection and gating across cornering and stint analysis` (F29).

Phase 2:

4. `feat: 25 mini-sector splits with delta-by-distance widget` (F22).
5. `feat: three-phase corner decomposition (entry/apex/exit)` (F23).
6. `feat: friction-circle / g-g diagram widget` (F24).
7. `feat: trail-brake proxy metric in cornering analysis` (F25).
8. `feat: car-balance tendency index (understeer/oversteer)` (F26).
9. `feat: racing-line spatial deviation against reference lap` (F28).

Phase 3:

10. `feat: per-event driver style fingerprint with outlier flagging` (F30).

Each commit independently passes `python -m pytest server/tests/ -v` and `npm run build`.
