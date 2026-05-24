# Time-Gained Everywhere — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** Replace (or augment) raw km/h-delta framings across every analytical widget and prose narration with **time-gained-or-lost in seconds**. Users understand "Leclerc gained 0.19s at this apex" far better than "Leclerc was 13 km/h faster at this apex."

**Architecture:** Reuse the time-contribution physics introduced in `_pick_speed_trace_markers` (commit `42469a2`). For per-point markers we already have `time_contribution_s`. For per-corner / per-segment comparisons, compute analogous integrated time deltas in the underlying tools. Surface the values in widget payloads, render them in React components, instruct the analyzer to mention them in prose.

**Tech Stack:** Python (numpy already in use), React (no new deps). Tests in `server/tests/` and frontend smoke via `npm run build`.

---

## Scope Audit — Which widgets need work (REVISED per Codex review)

Most F1Dash widgets are already time-native. Per-widget audit:

| Widget | Current delta unit | Needs work? |
|---|---|---|
| `qualifying_battle` (incl. speed-trace markers + `SpeedTraceChart` sub-component) | km/h on markers, time on sectors | **YES** — markers need time labels with "% of sector gap" context; analyzer prose currently emphasizes km/h |
| `mini_sector_heatmap` | per-segment time delta (s) | Label audit only. Verify "ms" / "s" units are explicit. |
| `corner_comparison` | per-corner speed deltas (km/h) | **YES** — compute per-corner time gained (mark as approximate) |
| `corner_analysis` (grip_commitment) | mid-corner speed delta (km/h) | **YES** — compute corner-length-weighted time gained |
| `race_pace_battle` | pace delta (s/lap), deg rate (s/lap) | Already time. |
| `circuit_profile` | context only, no comparison | N/A |
| `pit_stop_strategy` | pit duration (s) | Already time. |
| `deg_trend_chart` | deg rate (s/lap) | Already time. |
| `energy_management` | clipping (s) + speed trace km/h fades | **YES** — surface time-loss for the km/h fade callouts (per Codex audit) |
| `active_aero` | estimated_lap_time_delta_s + per-segment peak_speed_kph | **YES** — per-segment labels still show km/h headline (per Codex audit) |
| `undercut_overcut` | advantage (s) | Already time. |
| `race_story`, lookups, data_table | varies | N/A — no comparison framing. |

**Net scope: 5 widgets need backend changes** (qualifying_battle, corner_comparison, corner_analysis, energy_management fade callouts, active_aero per-segment labels); **3 more need label/prose audits** (mini_sectors, race_pace_battle, deg_trend_chart).

---

## File Structure

| File | Status | Role |
|---|---|---|
| `server/f1_data.py` | Modify | Add `_compute_time_gained_over_window` helper; emit `time_gained_s` on per-corner / per-marker / per-grip-commitment records |
| `server/features/qualifying_battle.py` | Modify | Surface `time_gained_s` per marker in the widget payload |
| `server/features/corner_profiles.py` | Modify | Surface per-corner `time_gained_s` in the widget payload |
| `server/features/cornering_loads.py` | Modify | Surface mid-corner `time_gained_s` in the grip_commitment payload |
| `server/features/energy_management.py` | Modify | If clipping fade has a measurable laptime impact, surface it |
| `server/chat.py` | Modify | Update `ANALYSIS_SYSTEM_PROMPT` to instruct the analyzer to mention time gained per mechanism, with km/h as parenthetical |
| `client/src/components/chat-widgets/QualifyingBattleWidget.jsx` | Modify | Render `time_gained_s` on each speed-trace marker card |
| `client/src/components/chat-widgets/CornerComparisonWidget.jsx` | Modify | Render per-corner time gained |
| `client/src/components/chat-widgets/CornerAnalysisWidget.jsx` | Modify | Render mid-corner time gained (or per-corner) |
| `client/src/components/chat-widgets/EnergyManagementWidget.jsx` | Modify | Add time-loss framing to clipping callouts |
| Tests | Modify | Tests per feature module to assert `time_gained_s` is in payload |

---

## The Physics (REVISED per Codex review)

Two methods, prefer #1 when telemetry samples are available:

### Method 1 (preferred) — Per-sample integration

Reuses the existing logic in `_pick_speed_trace_markers`:

```
per_meter_delta[i] = 1/v_loser_ms[i] - 1/v_winner_ms[i]
step[i] = distance[i] - distance[i-1]
time_gained_s = sum(per_meter_delta[i] * step[i])  # over samples in the window
```

This is what's already wired up for speed-trace markers (each marker's `time_contribution_s` is computed this way). **For Tasks 2-3, REUSE this pattern by extracting the inner loop into a helper that accepts arrays + a window range.**

### Method 2 (fallback) — Two-point constant-speed approximation

When per-sample telemetry isn't available (per-corner summaries that only carry entry/apex/exit speeds):

```
time_gained_s = (1/v_loser_ms - 1/v_winner_ms) * approximate_distance_m
```

This assumes constant speed differential over the window. It's an APPROXIMATION. Records using Method 2 carry `time_gained_estimate: true` so downstream consumers know.

### Window choices

- **Speed-trace markers** — already integrate per-sample (Method 1). Existing `_pick_speed_trace_markers` already does this. No change to the math; just expose the value.
- **Per-corner** — use Method 1 over the corner's entry-to-exit sample range IF the underlying analysis function has access to that range. If only summary speeds are available, use Method 2 with `corner_length_m * 0.4` as the approximate window, AND mark the record as `time_gained_estimate=True`. Document the 0.4 heuristic in the code comment.
- **Grip commitment** — same as per-corner. Reference specific corners' lengths.

---

## Tasks

### Task 1: Add `_compute_time_gained_over_window` helper to f1_data.py

**Files:**
- Modify: `server/f1_data.py` — add helper near `_pick_speed_trace_markers`
- Test: `server/tests/test_f1_data.py`

- [ ] **Step 1: Write the failing test**

```python
def test_compute_time_gained_over_window_apex_vs_straight():
    """A 13 km/h delta at low speed (apex) yields more time gained
    over the same distance than a 16 km/h delta at high speed."""
    from f1_data import _compute_time_gained_over_window

    apex = _compute_time_gained_over_window(
        v_winner_kph=117.0, v_loser_kph=104.0, window_distance_m=50.0,
    )
    straight = _compute_time_gained_over_window(
        v_winner_kph=337.0, v_loser_kph=321.0, window_distance_m=50.0,
    )
    assert apex > straight, "Apex delta should yield more time over same distance"
    # Sanity-check magnitudes (apex ~0.19s, straight ~0.026s):
    assert 0.10 < apex < 0.30
    assert 0.01 < straight < 0.05


def test_compute_time_gained_over_window_zero_when_speeds_equal():
    from f1_data import _compute_time_gained_over_window
    assert _compute_time_gained_over_window(
        v_winner_kph=200, v_loser_kph=200, window_distance_m=100,
    ) == 0.0


def test_compute_time_gained_over_window_handles_zero_speed_safely():
    """Avoid divide-by-zero when one driver has speed 0."""
    from f1_data import _compute_time_gained_over_window
    result = _compute_time_gained_over_window(
        v_winner_kph=200, v_loser_kph=0, window_distance_m=100,
    )
    assert result is None or result == 0.0  # whatever the helper decides
```

- [ ] **Step 2: Run red**

```
cd server; python -m pytest tests/test_f1_data.py -k "compute_time_gained" -v
```

- [ ] **Step 3: Implement**

```python
def _compute_time_gained_over_window(
    v_winner_kph: float,
    v_loser_kph: float,
    window_distance_m: float,
) -> float | None:
    """Time the winner gains over the loser by holding `v_winner_kph` vs
    `v_loser_kph` over `window_distance_m` of distance.

    Returns seconds. Returns None when either speed is non-positive or
    too low to be meaningful (< 30 km/h treated as zero).
    """
    SAFE_MIN_KPH = 30.0
    if (v_winner_kph is None or v_loser_kph is None
            or v_winner_kph < SAFE_MIN_KPH or v_loser_kph < SAFE_MIN_KPH
            or window_distance_m <= 0):
        return None
    v_a = v_winner_kph / 3.6
    v_b = v_loser_kph / 3.6
    return (1.0 / v_b - 1.0 / v_a) * float(window_distance_m)
```

- [ ] **Step 4: Run green + commit**

---

### Task 2: Surface `time_gained_s` on speed-trace markers

**Files:**
- Modify: `server/f1_data.py` (`_summarize_telemetry_battle`)
- Modify: `server/features/qualifying_battle.py`
- Test: `server/tests/test_features_qualifying_battle.py`

- [ ] **Step 1: Find `top_causes` in `_summarize_telemetry_battle`**

It already attaches `magnitude` (km/h) and `delta_speed_kph` per cause. Each cause has an approximate distance / sample range. Compute `time_gained_s` from `_compute_time_gained_over_window` using a 200m window centered on the cause's distance.

- [ ] **Step 2: Write failing test**

```python
def test_qualifying_battle_markers_carry_time_gained_s():
    from features.base import FEATURE_REGISTRY
    from features.registry import discover_features
    discover_features()
    feat = FEATURE_REGISTRY["analyze_qualifying_battle"]

    # Stub f1_data.analyze_qualifying_battle to return a known result with
    # a top_causes entry whose distance + speeds let us check the math.
    import f1_data
    original = f1_data.analyze_qualifying_battle
    f1_data.analyze_qualifying_battle = lambda **kw: {
        "available": True,
        "overall_gap_s": 0.04,
        "decisive_sector": "Sector 1",
        "decisive_sector_gap_s": 0.131,
        "split_sector_lap": False,
        "s1_gap_s": 0.131, "s2_gap_s": -0.081, "s3_gap_s": -0.010,
        "top_causes": [
            {
                "cause_type": "minimum_speed",
                "distance_m": 1500,
                "speed_a": 117.8, "speed_b": 104.8,
                "magnitude_kph": 13.0,
                "time_gained_s": 0.18,  # <-- the field we want
            },
        ],
        "lap_time_a": "1:28.143", "lap_time_b": "1:28.183",
    }
    try:
        result = feat.execute(
            driver_a="LEC", driver_b="NOR", round_number=7, session_type="Q",
        )
        widget = feat.make_widget(result)
    finally:
        f1_data.analyze_qualifying_battle = original

    # The widget should carry time_gained_s through (in whatever shape it
    # exposes top_causes / markers).
    markers = widget.get("top_causes") or widget.get("markers") or []
    assert any("time_gained_s" in m for m in markers), (
        "Expected at least one marker to expose time_gained_s"
    )
    primary = markers[0]
    assert primary["time_gained_s"] == 0.18
```

- [ ] **Step 3: Update `_summarize_telemetry_battle` to compute time_gained_s on each cause**

Add `time_gained_s = _compute_time_gained_over_window(speed_a, speed_b, 200)` to each cause dict before returning.

- [ ] **Step 4: Update `_build_qualifying_battle_widget` in `features/qualifying_battle.py` to pass `time_gained_s` through**

If the widget already passes `top_causes`, just confirm the field is in the dict. If it strips fields, add `time_gained_s` to the kept list.

- [ ] **Step 5: Run + commit**

---

### Task 3: Surface per-corner `time_gained_s` for `compare_corner_profiles`

**Files:**
- Modify: `server/f1_data.py` (`compare_corner_profiles`)
- Modify: `server/features/corner_profiles.py`
- Test: `server/tests/test_features_corner_profiles.py`

- [ ] **Step 1: Audit `compare_corner_profiles` return shape**

Read the function. Note whether per-corner records include `corner_length_m`, `entry_speed`, `mid_corner_speed`, `exit_speed`, and a "winner per corner" flag.

- [ ] **Step 2: Compute per-corner time gained**

For each corner where one driver is faster (e.g., higher mid_corner_speed): compute time_gained_s using the corner length and the speed differential at the most-decisive point (apex by default). If corner length isn't available, fall back to a flat 80m default (typical low/mid-speed corner length).

```python
weight_factor = 0.4  # speed differential typically sustained over ~40% of corner length
time_gained_s = _compute_time_gained_over_window(
    v_winner_kph=max(speed_a, speed_b),
    v_loser_kph=min(speed_a, speed_b),
    window_distance_m=corner_length_m * weight_factor,
)
```

Document the 0.4 weight factor as a heuristic in the code comment.

- [ ] **Step 3: Surface in widget**

Add `time_gained_s` to each per-corner record in the widget payload. Add a `total_time_gained_s` aggregate at the widget root.

- [ ] **Step 4: Write tests + commit**

---

### Task 4: Surface mid-corner `time_gained_s` in `analyze_cornering_loads`

**Files:**
- Modify: `server/f1_data.py` (`analyze_cornering_loads` and `_make_grip_commitment_summary` in chat.py)
- Modify: `server/features/cornering_loads.py` if it has fields that need updating
- Test: `server/tests/test_features_cornering_loads.py`

- [ ] **Step 1: Read `_make_grip_commitment_summary`**

Check what summary fields it produces. Likely includes mid_corner_speed_a / mid_corner_speed_b and a corner reference.

- [ ] **Step 2: Compute time gained per corner**

Same formula as Task 3, applied to corners referenced in the grip summary.

- [ ] **Step 3: Surface in the result dict**

Add `time_gained_s` per corner in the grip commitment summary. Surface in the qualifying_battle widget's `grip_commitment` field (which already gets merged in chat.py's cross-feature wiring).

- [ ] **Step 4: Test + commit**

---

### Task 5: Update analyzer prompt to mention time gained per mechanism

**Files:**
- Modify: `server/chat.py` — `ANALYSIS_SYSTEM_PROMPT` (built by `_build_analysis_system_prompt`)

- [ ] **Step 1: Find the section that talks about telemetry markers / mechanisms**

Likely a `qualifying_battle` block or generic telemetry guidance.

- [ ] **Step 2: Add instruction**

Insert a paragraph like:

```
When narrating telemetry mechanisms (speed-trace markers, corner deltas,
grip commitment differentials), prefer **time gained or lost in seconds**
as the primary unit. Each marker / corner / mechanism in the tool result
carries a `time_gained_s` field — surface that. Mention km/h as a
parenthetical or supporting detail, not as the headline. Example:

  GOOD: "Leclerc gained 0.19s at the 1500m apex (13 km/h faster
        through the mid-corner)."
  BAD:  "Leclerc was 13 km/h faster at the 1500m apex."

For decisive mechanisms, also reconcile with sector gaps: state that
this point's contribution alone was Xs out of the total Ys gap, when
the field is available.
```

- [ ] **Step 3: Commit (no automated test; prompt change verified via live smoke)**

---

### Task 6: Update React widget components (REVISED per Codex review)

**Files:**
- Modify: `client/src/components/chat-widgets/QualifyingBattleWidget.jsx`
- Modify: `client/src/components/chat-widgets/SpeedTraceChart.jsx` (sub-component)
- Modify: `client/src/components/chat-widgets/CornerComparisonWidget.jsx`
- Modify: `client/src/components/chat-widgets/CornerAnalysisWidget.jsx`
- Modify: `client/src/components/chat-widgets/EnergyManagementWidget.jsx`
- Modify: `client/src/components/chat-widgets/ActiveAeroWidget.jsx`
- Create: `client/src/components/chat-widgets/formatTimeDelta.js` (shared helper)

- [ ] **Step 1: Create `formatTimeDelta.js` helper**

```js
const NEAR_ZERO_THRESHOLD_S = 0.005;  // matches server-side _MINI_SECTOR_TIE_THRESHOLD_S

export function formatTimeDelta(seconds, { signed = true, approximate = false } = {}) {
  if (seconds == null || Number.isNaN(seconds)) return null;
  if (Math.abs(seconds) < NEAR_ZERO_THRESHOLD_S) return signed ? "≈0s" : "0s";
  const sign = signed ? (seconds >= 0 ? "+" : "−") : "";
  const magnitude = Math.abs(seconds);
  // Use 3 decimals under 0.1s, else 2 decimals
  const formatted = magnitude < 0.1 ? magnitude.toFixed(3) : magnitude.toFixed(2);
  return `${approximate ? "~" : ""}${sign}${formatted}s`;
}
```

- [ ] **Step 2: QualifyingBattleWidget — marker labels**

Currently each marker card shows the km/h delta as the headline number. Change to time-first:

```
0.18s gained
(13 km/h faster at the apex)
local contribution: 18% of S1 gap
```

Compute `% of sector gap` in JSX as `time_gained_s / abs(sector_gap_for_that_segment) * 100`. The marker's `distance_m` determines which sector it's in (s1/s2/s3 from the result).

Use `formatTimeDelta(time_gained_s)` for the headline. If `time_gained_estimate=true`, prefix with `~`.

- [ ] **Step 3: SpeedTraceChart — hover tooltip**

The hover tooltip on the speed trace currently shows km/h. Add time-gained-to-this-point as a secondary line: "Through this point: 0.18s gained."

- [ ] **Step 4: CornerComparisonWidget — per-corner rows**

Add a "time gained" column per row using `formatTimeDelta`. Add `Total time gained: +0.45s` row at the bottom (sum of positive contributions for the corners where the winner-driver is the faster one).

When `time_gained_estimate=true` on a row, render the value with `~` prefix and a tooltip explaining "approximate — derived from corner-zone speed differential."

- [ ] **Step 5: CornerAnalysisWidget — grip commitment**

Time gained leads, km/h supports. Same `~` marker for approximate.

- [ ] **Step 6: EnergyManagementWidget — fade callouts**

Where the widget currently surfaces km/h fade events, add time-gained equivalent using the same helper.

- [ ] **Step 7: ActiveAeroWidget — per-segment labels**

Each aero-mode segment currently labels with peak_speed_kph. Add time-gained-per-segment using `(estimated_lap_time_delta_s / total_z_mode_seconds) * segment_seconds` as an approximation, OR if the underlying analysis gives per-segment time deltas, use those directly.

- [ ] **Step 8: Sign convention — guard against contradictory signs**

When the backend `winner` driver disagrees with the sign of `time_gained_s` (e.g., due to rounding or estimation), the widget MUST display the driver derived from the FINAL signed time value, not the original kph sign. Apply the near-zero clamp consistently. Document in a JSX comment.

- [ ] **Step 9: `cd client; npm run build` — confirm clean**

- [ ] **Step 10: Commit (one commit, with all widgets + helper)**

---

### Task 7: Audit prose for residual km/h-headline framing

**Files:**
- Modify: `server/chat.py` if any other prompt section still says "km/h is the headline"
- Modify: feature-module test fixtures that assert km/h-only widget labels (update assertions to expect time too)

- [ ] **Step 1: Grep prompts for km/h / kph headline patterns**

```
cd C:/Users/sanja/Documents/Nerd/F1Dash; grep -rn "km/h\|kph" server/chat.py | grep -i "headline\|primary\|main"
```

- [ ] **Step 2: Update any patterns that promote km/h over time-gained**

- [ ] **Step 3: Run full suite + commit**

---

## Validation

- [ ] `_compute_time_gained_over_window` returns sensible values (apex > straight for same km/h delta).
- [ ] Every speed-trace marker carries `time_gained_s`.
- [ ] Every corner record in `compare_corner_profiles` carries `time_gained_s`.
- [ ] Every grip commitment record carries `time_gained_s`.
- [ ] Analyzer prompt instructs time-first prose.
- [ ] React widgets render time as the headline number, km/h as supporting.
- [ ] Full suite green.
- [ ] Live smoke test on the Leclerc-vs-Norris example: the apex marker (1500m) shows ~0.18s gained AS THE HEADLINE, not 13 km/h.

---

## Risks (REVISED per Codex review)

| Risk | Trigger | Resolution |
|---|---|---|
| **Time-gained values feel too small** (0.02s on the late straight looks like "nothing happened") | Production | This is the correct truth. The widget surfaces "% of sector gap" alongside to give context. |
| **Per-sample integration is the right physics but per-corner records may not have sample arrays** | Task 3 implementation | Method 2 (two-point approximation × 0.4 × corner_length) is the documented fallback. Records carry `time_gained_estimate: true` so the UI can prefix `~`. |
| **Per-corner time_gained_s sums won't equal the sector gap** | User confusion | Each marker shows "% of sector gap" as a sub-label. Widget reconciliation, not just prompt reconciliation. |
| **Contradictory signs** (kph delta says NOR faster, time_gained_s ends up barely positive or negative due to rounding) | Edge cases | Frontend derives winner-driver from FINAL signed time value, not from km/h sign. Near-zero clamp at 0.005s renders "≈0s." Same clamp as `_MINI_SECTOR_TIE_THRESHOLD_S`. |
| **`active_aero` per-segment time estimate is derived from total laptime delta / total Z-mode seconds × segment seconds** | Production | Mark as estimate. If users complain, push for per-segment time computation in `analyze_active_aero_usage`. |

---

## Non-Goals

- Doing per-sample telemetry integration for full-lap time-loss attribution. That's a separate, larger project (basically a custom lap-time decomposition engine).
- Reframing race-pace battle widgets — they already use time as the headline.
- Reframing pit_stop_strategy / undercut_overcut — already time.
