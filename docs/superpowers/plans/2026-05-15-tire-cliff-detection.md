# Tire Cliff Detection Implementation Plan

> Status: implemented.

## Goal

Add tyre cliff detection to the existing stint degradation model so each race stint can report whether tyre performance moved from normal linear degradation into a materially worse phase, including the tyre age where that happened, the pre/post degradation rates, and enough confidence metadata for the assistant and chart to avoid overstating noisy data.

Render detected cliffs in the `DegTrendChart` widget with two regression segments and a cliff marker.

## Architecture

Keep the current no-new-dependencies approach:

- `server/f1_data.py`: add robust piecewise regression helpers, improve stint splitting, call cliff detection from `_fit_stint_degradation()`.
- `server/tests/test_f1_data.py`: add realistic tests for cliff detection, noisy non-cliffs, outliers, and tyre-age resets.
- `server/chat.py`: pass cliff fields through `_make_deg_trend_chart_widget()` and update assistant guidance so it only says "cliff" when the data says so.
- `server/tools.py`: update the `analyze_stint_degradation` tool description.
- `client/src/components/chat-widgets/DegTrendChart.jsx`: patch the existing component to render cliff-aware regression segments and a marker.

Do not replace whole files unless necessary. Keep patches scoped.

## Key Corrections Versus The Earlier Plan

- Do not use `_linear_regression()` inside `_detect_cliff()` for model selection. It rounds slope/intercept/R2, which can distort SSE, BIC, and breakpoint selection.
- Do not skip candidate breakpoints when SSE is nearly zero. Clamp SSE to a tiny epsilon for BIC instead.
- Split stints on tyre-age reset as well as compound change, or same-compound pit stops can be merged into one fake cliff.
- Treat cliff severity as both an absolute slope increase and an optional ratio. A ratio is not meaningful when the pre-cliff slope is near zero or negative.
- Add tests with noise and outliers, not only perfect synthetic lines.
- Keep the final checklist honest. This document is a plan until the code and tests are actually updated.

---

## Task 1: Add Unrounded Regression Helpers

Files:

- Modify: `server/f1_data.py`
- Test: `server/tests/test_f1_data.py`

Add helpers after `_linear_regression()`:

```python
def _linear_regression_raw(x_vals: list[float], y_vals: list[float]) -> tuple[float, float, float]:
    """Unrounded y = slope * x + intercept regression for internal model selection."""
    n = len(x_vals)
    if n < 2:
        return (0.0, y_vals[0] if y_vals else 0.0, 0.0)

    sum_x = sum(x_vals)
    sum_y = sum(y_vals)
    sum_xy = sum(x * y for x, y in zip(x_vals, y_vals))
    sum_xx = sum(x * x for x in x_vals)

    denom = n * sum_xx - sum_x ** 2
    if abs(denom) < 1e-10:
        return (0.0, sum_y / n, 0.0)

    slope = (n * sum_xy - sum_x * sum_y) / denom
    intercept = (sum_y - slope * sum_x) / n

    y_mean = sum_y / n
    ss_tot = sum((y - y_mean) ** 2 for y in y_vals)
    ss_res = sum((y - (slope * x + intercept)) ** 2 for x, y in zip(x_vals, y_vals))
    r_squared = 1.0 - ss_res / ss_tot if ss_tot > 1e-10 else 0.0
    return (slope, intercept, r_squared)


def _regression_sse(x_vals: list[float], y_vals: list[float], slope: float, intercept: float) -> float:
    return sum((y - (slope * x + intercept)) ** 2 for x, y in zip(x_vals, y_vals))
```

Acceptance:

- Existing `_linear_regression()` behavior is unchanged.
- New helpers are private and do not round.

---

## Task 2: Add `_detect_cliff()`

Files:

- Modify: `server/f1_data.py`
- Test: `server/tests/test_f1_data.py`

Algorithm:

- Input: tyre ages and fuel-corrected lap times for one physical tyre stint.
- Minimum total laps: 10.
- Minimum laps per segment: 5.
- Compare one-segment linear regression against all valid two-segment linear regressions.
- Use BIC:

```text
BIC = n * ln(max(SSE, epsilon) / n) + k * ln(n)
```

- One segment uses `k=2`.
- Two independent segments use `k=4`.
- Candidate cliff requires:
  - BIC improvement greater than `6.0`.
  - Post-cliff slope greater than pre-cliff slope.
  - Absolute slope increase at least `0.06 s/lap`, or ratio at least `2.5` when pre-cliff slope is meaningfully positive.
  - Sustained post-cliff degradation, not a single outlier.

Recommended signature:

```python
def _detect_cliff(
    tyre_ages: list[float],
    lap_times: list[float],
    min_segment_laps: int = 5,
    bic_threshold: float = 6.0,
    slope_ratio_threshold: float = 2.5,
    slope_abs_increase_threshold: float = 0.06,
    sse_epsilon: float = 1e-9,
) -> dict:
```

Return shape when no cliff:

```python
{"cliff_detected": False}
```

Return shape when detected:

```python
{
    "cliff_detected": True,
    "cliff_tyre_age": tyre_ages[best_k],
    "cliff_slope_increase_s_per_lap": round(s2 - s1, 4),
    "cliff_severity_ratio": round(ratio, 2) if ratio_is_meaningful else None,
    "pre_cliff_deg_rate_s_per_lap": round(s1, 4),
    "post_cliff_deg_rate_s_per_lap": round(s2, 4),
    "pre_cliff_lap_count": len(ages_pre),
    "post_cliff_lap_count": len(ages_post),
    "pre_cliff_regression_line": [...],
    "post_cliff_regression_line": [...],
    "bic_improvement": round(delta_bic, 2),
    "cliff_confidence": "moderate" or "high",
}
```

Notes:

- `cliff_severity_ratio` should be `None` when `pre_cliff_deg_rate_s_per_lap <= 0.01`; the absolute increase is the trustworthy value in that case.
- Use `cliff_slope_increase_s_per_lap` in assistant wording when the ratio is null.
- Keep `cliff_tyre_age` as the first post-cliff tyre age.

Tests to add:

- Too few laps returns no cliff.
- Linear degradation returns no cliff.
- Noisy linear degradation returns no cliff.
- One bad outlier returns no cliff.
- Clear sustained slope increase detects a cliff.
- Slope ratio below threshold and absolute increase below threshold returns no cliff.
- Flat/near-zero pre-cliff slope with strong post-cliff increase detects a cliff and has `cliff_severity_ratio is None`.
- Detected output includes all required keys and two-point regression lines.

Run:

```bash
cd server
python -m pytest tests/test_f1_data.py::TestDetectCliff -v
```

---

## Task 3: Fix Physical Stint Splitting In `_fit_stint_degradation()`

Files:

- Modify: `server/f1_data.py`
- Test: `server/tests/test_f1_data.py`

Current grouping only starts a new stint when compound changes. That is not enough. Start a new stint when any of these happen:

- Compound changes.
- `tyre_age` decreases or resets.
- There is explicit pit/tyre-set evidence in the lap data, if available.

Implementation guidance:

- Keep chronological order by `lap_number`.
- Use `lap.get("tyre_age")` when present.
- If tyre age is missing, preserve the current compound-block behavior.
- Do not split only because `lap_number` has a gap. Clean-lap filtering can remove laps from the middle of a physical stint.
- Do not merge two same-compound tyre sets.

Tests to add:

- `MEDIUM -> MEDIUM` with tyre age reset produces two stints, not one.
- Same compound with monotonically increasing tyre age remains one stint.
- The same-compound reset case must not produce `cliff_detected=True` merely because the second set is faster/slower.

Run:

```bash
cd server
python -m pytest tests/test_f1_data.py::TestFitStintDegradationStintSplitting -v
```

---

## Task 4: Wire Cliff Output Into `_fit_stint_degradation()`

Files:

- Modify: `server/f1_data.py`
- Test: `server/tests/test_f1_data.py`

After fuel-corrected regression is computed:

```python
cliff = _detect_cliff(tyre_ages, fuel_corrected)
```

Add these fields to each stint output:

```python
'cliff_detected': cliff.get('cliff_detected', False),
'cliff_tyre_age': cliff.get('cliff_tyre_age'),
'cliff_slope_increase_s_per_lap': cliff.get('cliff_slope_increase_s_per_lap'),
'cliff_severity_ratio': cliff.get('cliff_severity_ratio'),
'pre_cliff_deg_rate_s_per_lap': cliff.get('pre_cliff_deg_rate_s_per_lap'),
'post_cliff_deg_rate_s_per_lap': cliff.get('post_cliff_deg_rate_s_per_lap'),
'pre_cliff_lap_count': cliff.get('pre_cliff_lap_count'),
'post_cliff_lap_count': cliff.get('post_cliff_lap_count'),
'pre_cliff_regression_line': cliff.get('pre_cliff_regression_line') or [],
'post_cliff_regression_line': cliff.get('post_cliff_regression_line') or [],
'bic_improvement': cliff.get('bic_improvement'),
'cliff_confidence': cliff.get('cliff_confidence'),
```

Tests to add:

- Clear cliff stint includes the fields and sets `cliff_detected=True`.
- Linear stint includes `cliff_detected=False`.
- Existing regression output remains present for backward compatibility.

Run:

```bash
cd server
python -m pytest tests/test_f1_data.py::TestDetectCliff tests/test_f1_data.py::TestFitStintDegradationCliffFields -v
python -m pytest tests/ -v
```

---

## Task 5: Pass Fields Through Chat And Tool Metadata

Files:

- Modify: `server/chat.py`
- Modify: `server/tools.py`
- Test: `server/tests/test_chat.py`, `server/tests/test_tools.py`

In `_make_deg_trend_chart_widget()`, pass the new fields through:

```python
"cliff_detected": s.get("cliff_detected", False),
"cliff_tyre_age": s.get("cliff_tyre_age"),
"cliff_slope_increase_s_per_lap": s.get("cliff_slope_increase_s_per_lap"),
"cliff_severity_ratio": s.get("cliff_severity_ratio"),
"pre_cliff_deg_rate_s_per_lap": s.get("pre_cliff_deg_rate_s_per_lap"),
"post_cliff_deg_rate_s_per_lap": s.get("post_cliff_deg_rate_s_per_lap"),
"pre_cliff_regression_line": s.get("pre_cliff_regression_line") or [],
"post_cliff_regression_line": s.get("post_cliff_regression_line") or [],
"cliff_confidence": s.get("cliff_confidence"),
```

Update the `analyze_stint_degradation` tool description to include:

- `cliff_detected`
- `cliff_tyre_age`
- `cliff_slope_increase_s_per_lap`
- `cliff_severity_ratio`
- `pre_cliff_deg_rate_s_per_lap`
- `post_cliff_deg_rate_s_per_lap`
- `cliff_confidence`

Update the tyre guidance in `server/chat.py`:

- Only say "cliff" or "fell off a cliff" when `cliff_detected` is true.
- If `cliff_detected` is false, describe the trend as linear degradation/noisy degradation, not a cliff.
- Prefer plain language over field names.
- Mention confidence when it matters: "the model flags a moderate-confidence cliff around tyre age X."

Run:

```bash
cd server
python -m pytest tests/test_chat.py tests/test_tools.py -v
```

---

## Task 6: Patch `DegTrendChart.jsx`

Files:

- Modify: `client/src/components/chat-widgets/DegTrendChart.jsx`

Patch the existing component rather than replacing it wholesale.

Behavior:

- When `cliff_detected` is false, keep the current single dashed regression line.
- When `cliff_detected` is true and both segment lines are present:
  - Render pre-cliff regression in the compound color.
  - Render post-cliff regression in a warning color.
  - Render a vertical dashed marker at `cliff_tyre_age`.
  - Show concise stat text below the chart.

Frontend details:

- Prefer an existing warning/destructive CSS token if available. If none exists, use a restrained red such as `hsl(0 72% 51%)`.
- Do not add bulky explanatory copy. Keep the widget compact.
- Use `cliff_severity_ratio` only if it is not null. Otherwise show the absolute slope increase.
- Avoid `toFixed()` on nullable values.
- Keep the existing sizing, chart layout, and visual density.

Suggested stat text:

```jsx
{s.cliff_detected && (
  <span style={{ color: CLIFF_COLOR }}>
    {' '}cliff at age {s.cliff_tyre_age}
    {s.cliff_severity_ratio != null
      ? `, ${s.cliff_severity_ratio.toFixed(1)}x steeper`
      : s.cliff_slope_increase_s_per_lap != null
        ? `, +${s.cliff_slope_increase_s_per_lap.toFixed(3)}s/lap`
        : ''}
    {s.cliff_confidence ? `, ${s.cliff_confidence}` : ''}
  </span>
)}
```

Run:

```bash
cd client
npm run build
```

---

## Validation Checklist

- [x] `_linear_regression()` remains backward compatible.
- [x] `_detect_cliff()` uses unrounded regression parameters for BIC/SSE.
- [x] BIC uses epsilon-clamped SSE, not skipped zero-SSE candidates.
- [x] Stint splitting handles same-compound tyre-age resets.
- [x] Noisy linear data and single outliers do not trigger cliff detection.
- [x] Sustained post-cliff degradation does trigger detection.
- [x] `_fit_stint_degradation()` includes cliff fields on every returned stint.
- [x] `chat.py` and `tools.py` pass/explain the fields.
- [x] `DegTrendChart.jsx` preserves the existing visual style and only adds cliff visuals when data is present.
- [x] Server tests pass.
- [x] Client build passes.

## Commit Plan

Use small commits:

1. `feat: add robust tyre cliff detection helper`
2. `fix: split degradation stints on tyre age reset`
3. `feat: expose cliff fields in stint degradation output`
4. `feat: pass tyre cliff fields through chat widgets`
5. `feat: render tyre cliff markers in degradation chart`
