# Combined Grip Metrics — Design Spec
**Date:** 2026-05-02

## Problem

The current cornering analysis only measures **lateral G utilisation** — how hard a driver corners relative to a speed-dependent lateral ceiling (`2.0 + speed_kph * 0.012`). This misses the real picture: a tyre's total grip budget is shared between lateral (cornering) and longitudinal (braking/acceleration) forces simultaneously. A driver who trail-brakes deep into a corner is spending grip on both axes at once — the lateral-only metric understates their total commitment.

The industry standard is the **traction/friction circle**: `combined_G = sqrt(lat_G² + long_G²)`, where the circle radius is the theoretical grip ceiling. This paper spec adds three new metrics derived from this model.

---

## New Metrics

### 1. `combined_util_pct` — Combined grip utilisation
**What it is:** Mean of `sqrt(lat_G² + long_G²) / theoretical_max_G` across all samples within each corner, expressed as a percentage.

**Physical meaning:** The fraction of the tyre's *total* grip envelope being used — not just the lateral slice. Two drivers may show identical lateral utilisation but differ significantly on combined because one brakes later into the corner.

**How it reads:** "VER uses 89% of total tyre capability vs LEC's 84%"

### 2. `trail_brake_pct` — Trail brake signature
**What it is:** Within the **entry phase** of each corner (start → apex, where apex = min-speed sample), the percentage of samples where both:
- `lat_G > 0.4G` (meaningfully in the corner)
- `long_G < -0.3G` (still decelerating / on the brakes)

Averaged across all detected corners, expressed as a percentage.

**Physical meaning:** How much braking and cornering overlap at entry. High = the driver carries the brake deep into the corner, loading the front and rotating the car. Zero = the driver finishes braking before turning in.

**How it reads (A + C):** Raw percentage exposed to the LLM, which then says: "VER trail-brakes through 38% of corner entry — he's still on the brakes well past the turn-in point, using the brake to rotate the car. NOR finishes braking earlier, turning in on a clean throttle."

### 3. `circle_fullness_pct` — Circle fullness
**What it is:** Across **all** cornering-phase samples (the union of all detected corners), the percentage where `combined_util > 0.75` (i.e. within 25% of the theoretical grip ceiling on the combined vector).

**Physical meaning:** How consistently the driver operates near the *total* grip limit throughout a corner — not just at the peak, but across entry, apex, and exit. Rewards blending both dimensions continuously rather than touching the ceiling only at apex.

**How it reads:** "VER operates near the combined limit for 61% of cornering time — almost never backing off"

---

## Longitudinal G Derivation

FastF1 provides `Speed` (kph) and `Time` channels. Longitudinal G is:

```python
v_mps = Speed / 3.6
t_s   = Time.dt.total_seconds()
long_g = gradient(v_mps, t_s) / 9.81   # positive = accel, negative = braking
```

After a light Savitzky-Golay smooth (same window as lateral G). Clipped to `[-6, 4]` G.

---

## Integration Points

### `f1_data.py`

**New function:** `_compute_longitudinal_g(tel: pd.DataFrame) -> np.ndarray`
- Derives long G from Speed + Time via `np.gradient`
- Applies same light SG smoothing as `_compute_lateral_g`
- Clips to `[-6.0, 4.0]`

**Modified:** `_corner_metrics(lat_g, long_g, speed_kph, dist, start, end) -> dict`
- Accepts new `long_g` parameter
- Adds `combined_util_pct`, `trail_brake_pct`, `circle_fullness_pct` to returned dict
- Entry phase = samples `[start : apex_idx]` (apex = min-speed index within segment)
- Trail brake threshold: `lat_G > 0.4` AND `long_G < -0.3`
- Circle fullness threshold: combined_util > 0.75

**Modified:** `compare_cornering_loads(...)` (qualifying/single-lap tool)
- Computes `long_g_a`, `long_g_b` via `_compute_longitudinal_g`
- Passes to `_corner_metrics`
- `_summary()` inner function extended to aggregate all three new fields from `per_corner`
- Per-corner dicts gain `combined_util_delta`, `trail_brake_delta`, `circle_fullness_delta`
- Summary dict fields added: `avg_combined_util_pct`, `avg_trail_brake_pct`, `avg_circle_fullness_pct`
- Narrative updated to include combined util and trail brake comparison

**Modified:** `_aggregate_lap_cornering_stats(tel)` (per-lap helper for race tool)
- Computes `long_g` via `_compute_longitudinal_g`
- Passes to `_corner_metrics` per corner
- Returns dict gains: `avg_combined_util_pct`, `avg_trail_brake_pct`, `avg_circle_fullness_pct`

**Modified:** `analyze_race_cornering_profile(...)` (race tool)
- `_aggregate()` averages the three new fields across laps
- `_aggregate_by_stint()` averages them per stint
- Narrative updated: combined util diff, trail brake comparison

### `tools.py`

**`analyze_cornering_loads` description** — append:
> "Also returns: combined grip utilisation % (lat+long vector vs theoretical max), trail brake % at corner entry, circle fullness % (time near combined grip ceiling)."

**`analyze_race_cornering_profile` description** — append:
> "Also returns: combined grip utilisation %, trail brake %, circle fullness % per stint and overall."

### `chat.py` — System prompt vocabulary extension

New section under **Cornering Load & Grip Utilisation Data**:

```
- **combined_util_pct** → Total tyre commitment (both cornering AND braking combined).
  Higher = the driver is asking more of the tyre across BOTH dimensions.
  Character language: "fully committed", "nothing left in reserve", "using every gram of rubber".
  Compare to avg_grip_util_pct: if combined is much higher than lateral, the driver is loading the tyre heavily under braking too — not just cornering.

- **trail_brake_pct** → % of corner entry spent simultaneously cornering AND braking.
  High (>35%): "carrying the brake deep", "loading the front to rotate", "still on the pedal at turn-in",
               "using the brake as a rotation tool", "trail-braking all the way to the apex".
  Low (<15%):  "finishes braking before the corner", "clean turn-in on neutral throttle",
               "a textbook entry, brake done, then commit".

- **circle_fullness_pct** → % of cornering time near the combined grip ceiling (>75% combined util).
  High (>55%): "barely eases off through the whole corner", "the tyre is working hard start to finish",
               "no coasting — every part of the corner is demanding something".
  Low (<35%):  "has a comfort margin mid-corner", "eases off at the apex", "keeps something in reserve".
```

Combined signal inferences (add to existing inference table):
- High combined_util + high trail_brake = *front-loading style* — loads entry, rotates with the brake. Single-lap weapon, hard on fronts over a stint.
- High combined_util + low trail_brake = *apex commitment* — finishes braking early, carries huge speed through the middle of the corner. Clean but demanding on rear.
- Low combined_util + high trail_brake = *defensive entry* — uses trail brake to rotate without committing fully. Protective style.

**New rule:** Never say "combined grip utilisation", "trail brake percentage", or "circle fullness percentage" in answers. Translate to the character vocabulary above.

---

## Tests

`test_f1_data.py`:
- `test_compute_longitudinal_g_shape` — output length matches input telemetry
- `test_compute_longitudinal_g_braking_is_negative` — decelerating segment produces negative values
- `test_corner_metrics_new_fields_present` — `combined_util_pct`, `trail_brake_pct`, `circle_fullness_pct` all present
- `test_corner_metrics_trail_brake_zero_when_no_overlap` — no overlap → 0%
- `test_aggregate_lap_cornering_stats_new_fields` — new fields survive round-trip through the lap aggregator

`test_chat.py`:
- Existing `test_qualifying_widget_includes_grip_commitment_from_cornering_loads` — ensure it still passes (new fields are additive, not replacing)

---

## What does NOT change

- `_theoretical_max_g` formula stays as-is — still used for lateral-only util (existing fields preserved)
- `mean_grip_util_pct` and `pct_time_above_90pct_grip` remain in all outputs for backward compat
- No new widget, no new tool, no schema changes — metrics are additive fields in existing tool outputs
- `_detect_corners` and `_align_corners` unchanged
