# Tire Degradation Quality Improvements (F8–F14) Implementation Plan

> Status: not started. Estimated effort: Phase 1 ~2 weeks, Phase 2 ~3 weeks (optional, research-grade), Phase 3 ~3 weeks (optional, research-grade).

## Goal

Raise the quality of `_fit_stint_degradation()` in `server/f1_data.py` so the slope it returns is closer to the *true* tyre-degradation rate, not a contaminated mix of warm-up laps, safety-car laps, fuel-coefficient error, outliers, and dirty-air loss. The cliff-detection feature (2026-05-15 plan) is now landed; this plan builds quality on top of the same fit and adds two optional research-grade alternatives.

The deliverables fall into three phases:

- **Phase 1 (F8–F12)** — quality polish on the existing OLS path. No new heavy dependencies. Must improve real-stint accuracy without breaking cliff detection or any downstream chat widget.
- **Phase 2 (F13)** — Bayesian state-space alternative analyzer (research-grade, optional). New dependency. Exposes posterior uncertainty.
- **Phase 3 (F14)** — Bayesian Online Changepoint Detection for live cliff alerting (research-grade, optional). Pure NumPy. Would be novel published work in F1.

The first phase is the only one that ships by default. The other two are explicitly opt-in via a new analyzer flag and remain off the agentic system prompt until validated against real seasons.

## Architecture

Phase 1 stays inside `server/f1_data.py` and the existing widget chain. Phase 2 adds a sibling module. Phase 3 adds another sibling module plus one new tool.

| Phase | Module | Change kind |
|---|---|---|
| 1 | `server/f1_data.py` | New private helpers; modifications to `_fit_stint_degradation()` signature; new constants; pre-regression lap filtering. |
| 1 | `server/circuit_profiles.py` | New `CIRCUIT_FUEL_COEFFICIENT` table + lookup helper. |
| 1 | `server/chat.py` | Surface new fields (`traffic_loss_rate_s_per_lap`, `excluded_lap_count`, `sc_lap_count`) through `_make_deg_trend_chart_widget()`. Hedge wording when traffic dominates. |
| 1 | `server/tools.py` | Extend `analyze_stint_degradation` tool description. |
| 1 | `client/src/components/chat-widgets/DegTrendChart.jsx` | Minor label change when traffic loss is meaningful; show excluded-lap badge. |
| 2 | `server/deg_bayesian.py` (new) | Optional state-space analyzer. `pymc` or `numpyro` dependency. |
| 3 | `server/deg_bocpd.py` (new) | Online BOCPD changepoint detector. NumPy only. |
| 3 | `server/tools.py` | New tool `analyze_stint_cliff_live`. |

Do not rewrite the OLS fit. Wrap it. Cliff detection (`_detect_cliff`) keeps using unrounded raw OLS for BIC selection — Phase 1 changes only the *inputs* fed to it (cleaner laps).

## Key Corrections Versus The Current Code

- `_fit_stint_degradation()` at `f1_data.py:4456` currently treats every clean lap in a stint as a regression sample with equal weight. Out-laps, in-laps, and SC laps are not filtered. F8 + F9 fix this.
- The fuel-correction constant defaults to `0.04 s/lap` at the function signature (`f1_data.py:4456`) and is also used as a per-lap fuel-burn assumption (`fuel_burn_gain_assumption_s_per_lap`). Real per-circuit values range 0.025–0.040. F10 adds the table.
- `_linear_regression()` at `f1_data.py:4303` is plain OLS. A single 5-second pit-approach lap moves the slope. F11 adds Huber.
- The deg rate is currently confounded with traffic loss. A driver stuck in DRS-train loses 0.3–0.8 s/lap that the regression attributes to tyres. F12 adds a covariate.
- Cliff detection currently uses OLS BIC over the same (contaminated) inputs. After F8/F9 land, the BIC SSE is computed on cleaner samples — better cliff selection comes for free. Keep `_detect_cliff` itself on OLS to preserve the existing BIC math.

---

## Phase 1 — OLS Quality Polish (F8 through F12, ~2 weeks)

Each task is shippable on its own. Run `python -m pytest tests/test_f1_data.py -v` after each.

### Task F8 — Out-lap / In-lap Exclusion

Files:

- Modify: `server/f1_data.py`
- Test: `server/tests/test_f1_data.py`

Change description:

- Add module-level constants near the top of the deg section (before `_fit_stint_degradation`):

```python
EXCLUDE_FIRST_N_LAPS = 2          # tyres not at operating temperature
EXCLUDE_IN_LAP = True             # last lap of a stint contaminated by pit-lane approach
```

- Inside `_fit_stint_degradation()` at `f1_data.py:4490` (the inner per-stint loop), after the stint is split but before `lap_nums`/`raw_times` are extracted, drop laps that fail the warm-up or in-lap filter:
  - **Warm-up filter:** drop the first `EXCLUDE_FIRST_N_LAPS` laps of every stint (by tyre age, not by lap number — a stint may not start at age 1 if FastF1 reports a used set).
  - **In-lap filter:** if `EXCLUDE_IN_LAP` and the stint has a known terminating pit event (next stint starts with a fresh compound or tyre-age reset), drop the final lap of the current stint. If the stint is the last of the race (driver finished on the stint), do **not** drop the final lap.
- Track how many laps were excluded and surface in the stint output as `excluded_lap_count` (warm-up + in-lap combined). The deterministic chat layer needs this to hedge when very few laps survive.
- Minimum-laps-per-stint guard at `f1_data.py:4492` (currently `< 3`) should test the **post-exclusion** lap count, not pre-exclusion. Stints with `< 3` usable laps after filtering still get skipped.

Acceptance:

- A 25-lap stint produces a fit over 22 laps (drop first 2 warm-up + last in-lap).
- The last stint of the race (no pit on the end) drops only warm-up laps.
- A stint of 4 laps after exclusion still fits; a stint of 2 laps after exclusion is skipped.
- New field `excluded_lap_count` is present on every returned stint dict.
- Existing cliff-detection tests pass — `_detect_cliff` receives the filtered tyre-age/lap-time arrays.
- Snapshot test on a known race (Norris, Imola 2025) shows the deg slope changes in the expected direction (typically smaller `deg_rate_s_per_lap`, similar `positive_deg_rate_s_per_lap`).

Reference: Heilmeier 2018 (TUM); Sulsters 2018.

Risk:

- **Risk:** Excluding the in-lap when the stint actually ended in a retirement (mechanical, crash) loses a real data point.
- **Trigger:** Driver DNFs on the lap that would otherwise be classed as the in-lap.
- **Solutions:** (1) Treat any stint-terminator that is *not* followed by a compound change/tyre-age reset as a non-pit termination; keep the lap. (2) Inspect `Race Control` for the retirement lap. (3) Drop the lap anyway — DNF laps are noisy and the regression loses little.
- **Recommendation:** (1). The compound/age-reset check is already in the splitter; the absence of a downstream stint already encodes "no pit happened here."

Run:

```bash
cd server
python -m pytest tests/test_f1_data.py::TestFitStintDegradationLapFiltering -v
```

---

### Task F9 — Safety-Car / VSC Lap Flagging

Files:

- Modify: `server/f1_data.py`
- Test: `server/tests/test_f1_data.py`

Change description:

- SC and VSC laps are 20–40% slower than green-flag laps. One in a 10-lap stint dominates OLS. The `track_status` field is already extracted from FastF1 (`f1_data.py:1686`, `:4278`) but is not used by the regression.
- In the lap-cleaning pipeline upstream of `_fit_stint_degradation()`, add a `track_status` field to each lap dict if not already present. FastF1 values are single-character codes — `'1'` green, `'2'` yellow, `'4'` SC, `'5'` red, `'6'` VSC deploying, `'7'` VSC.
- Inside `_fit_stint_degradation()`, before fitting, drop any lap whose `track_status` is in the dropset `{"2", "4", "5", "6", "7"}`. Yellow laps are included in the dropset because mid-sector yellows distort the lap time even when the track returns to green at the line.
- Track the dropped count as `sc_lap_count` on the stint dict.
- If `sc_lap_count >= 0.4 * stint_total_laps`, set `deg_rate_confidence: "low"` on the stint output. The chat layer will use this to hedge.
- Lap-down weighting (mentioned in the spec) is **out of scope for Phase 1**. Drop-only is simpler and FastF1 already gives us a clean status code. If we ever need the dropped laps back (e.g. for a race-pace widget that *wants* SC laps), the upstream lap dict still carries the original `track_status`.

Acceptance:

- A stint of 12 laps with 2 SC laps fits over 10 laps and reports `sc_lap_count: 2`.
- `deg_rate_confidence` is `"low"` when ≥40% of the stint was non-green.
- `deg_rate_confidence` is `"high"` otherwise.
- An existing test that built synthetic clean data with `track_status='1'` continues to pass (no SC laps means no drops).
- New test using a 2024 race with a known SC period (e.g. Singapore lap 32–35) shows those laps excluded.

Reference: Heilmeier 2020a; Phillips 2014.

Risk:

- **Risk:** FastF1's `TrackStatus` is sometimes blank for older sessions or formation laps. A blank status would currently pass the dropset check.
- **Trigger:** Pre-2020 historical session, or first lap of a race.
- **Solutions:** (1) Treat blank/None as green (current behaviour after this change). (2) Cross-check against `session.race_control_messages` for SC/VSC messages and reconcile. (3) Mark the stint `deg_rate_confidence: "low"` whenever any lap has a blank status.
- **Recommendation:** (1). Race-control message reconciliation is a Phase 2 enhancement; for now, blank means green and we accept the rare false negative.

Run:

```bash
cd server
python -m pytest tests/test_f1_data.py::TestFitStintDegradationTrackStatus -v
```

---

### Task F10 — Per-Circuit Fuel Coefficient Table

Files:

- Modify: `server/circuit_profiles.py`
- Modify: `server/f1_data.py`
- Test: `server/tests/test_circuit_profiles.py`, `server/tests/test_f1_data.py`

Change description:

- Add to `server/circuit_profiles.py` (sibling of `_LOOKUP`):

```python
CIRCUIT_FUEL_COEFFICIENT: dict[str, float] = {
    # Estimated s/kg/lap fuel-mass effect. Published range 0.025-0.040.
    # Slow, low-energy circuits sit near the high end (more time spent
    # accelerating, mass cost amplified); fast power circuits near the low end.
    "monaco":         0.040,
    "singapore":      0.038,
    "hungary":        0.036,
    "azerbaijan":     0.030,
    "miami":          0.032,
    "abu_dhabi":      0.033,
    "qatar":          0.031,
    "japan":          0.029,
    "australia":      0.030,
    "canada":         0.030,
    "netherlands":    0.031,
    "spain":          0.030,
    "emilia_romagna": 0.031,
    "china":          0.030,
    "saudi_arabia":   0.028,
    "mexico":         0.029,
    "brazil":         0.029,
    "united_states":  0.029,
    "las_vegas":      0.028,
    "austria":        0.027,
    "britain":        0.026,
    "belgium":        0.025,
    "italy":          0.025,
    "bahrain":        0.030,
}

CIRCUIT_FUEL_COEFFICIENT_DEFAULT = 0.030

def get_circuit_fuel_coefficient(country: str, event_name: str = "") -> float:
    """Look up s/kg/lap fuel-burn coefficient by circuit. Fallback 0.030."""
    profile = get_circuit_profile(country, event_name)
    if profile and profile.get("_key") in CIRCUIT_FUEL_COEFFICIENT:
        return CIRCUIT_FUEL_COEFFICIENT[profile["_key"]]
    return CIRCUIT_FUEL_COEFFICIENT_DEFAULT
```

- `get_circuit_profile` may need a `_key` field added (the canonical key it matched against); if absent, do the lookup directly via the existing matcher and reuse the alias map. Either is fine — preserve the existing matcher behaviour.
- In `server/f1_data.py`, change the `_fit_stint_degradation()` signature so the caller can pass a per-stint coefficient. Default keeps the current 0.04 for backward compatibility *only when no circuit is known*:

```python
def _fit_stint_degradation(
    clean_laps: list[dict],
    fuel_correction_s_per_lap: float = 0.030,   # was 0.04
) -> list[dict]:
```

- At every call site of `_fit_stint_degradation()` (search for it — there are ~3 in `f1_data.py` plus paths in `chat.py`), look up the circuit and pass the per-circuit value. If no circuit context is reachable at the call site, use the default and emit `fuel_coefficient_source: "default"` in the output. Otherwise emit `fuel_coefficient_source: "monaco"` (etc.).
- Add `fuel_burn_gain_assumption_source` to the stint output dict alongside the existing `fuel_burn_gain_assumption_s_per_lap`. The renderer can use it to footnote the widget.

Acceptance:

- `get_circuit_fuel_coefficient("Monaco")` returns `0.040`.
- `get_circuit_fuel_coefficient("Belgium")` returns `0.025`.
- `get_circuit_fuel_coefficient("Unknown")` returns `0.030`.
- `_fit_stint_degradation()` called with Monaco context applies 0.040 to the fuel correction; called with no context applies 0.030.
- Stint output dict includes `fuel_burn_gain_assumption_s_per_lap` and `fuel_burn_gain_assumption_source`.
- Existing tests still pass (snapshots that pinned the old 0.04 default need to be updated — verify each).

Reference: Heilmeier 2018 Appendix A (fuel-mass coefficient is *not* a constant across circuits).

Risk:

- **Risk:** The published 0.025–0.040 range is a research approximation. Some circuits may sit outside this band, and the table above is hand-tuned from the literature rather than calibrated.
- **Trigger:** Any stint comparison across circuits where the deg rate is now subtly shifted by the new coefficient.
- **Solutions:** (1) Ship the hand-tuned table; flag in the widget that the coefficient is a per-circuit estimate. (2) Build a calibration script that fits the coefficient per circuit from historical full-stint data (Heilmeier 2018 method) — but this adds a heavy offline step. (3) Drop the table; keep the 0.030 default.
- **Recommendation:** (1). Calibration is the right long-term answer but is out of scope; flag the source field and let chat hedge.

Run:

```bash
cd server
python -m pytest tests/test_circuit_profiles.py::TestFuelCoefficient tests/test_f1_data.py -v
```

---

### Task F11 — Huber Robust Regression Replacing OLS (for race stints only)

Files:

- Modify: `server/f1_data.py`
- Test: `server/tests/test_f1_data.py`

Change description:

- Plain OLS minimises squared residuals; one outlier (lock-up costing 0.8 s, fuel-saving lap +0.5 s) drags the slope. Huber regression weights observations by `min(1, k/|residual|)` for residuals beyond a threshold, capping the influence of outliers without rejecting them.
- Add `_huber_regression()` next to `_linear_regression_raw()` at `f1_data.py:4332`. Pure-Python iteratively-reweighted least squares (IRLS), no new dependency:

```python
def _huber_regression(
    x_vals: list[float],
    y_vals: list[float],
    k: float = 1.345,
    max_iter: int = 20,
    tol: float = 1e-4,
) -> tuple[float, float, float]:
    """
    Huber-weighted linear regression. k=1.345 gives 95% efficiency under
    Gaussian residuals and bounded influence beyond ~1.35 MAD.
    Returns (slope, intercept, r_squared) over the weighted fit.
    """
    n = len(x_vals)
    if n < 3:
        return _linear_regression_raw(x_vals, y_vals)

    # Initialise with OLS
    slope, intercept, _ = _linear_regression_raw(x_vals, y_vals)
    weights = [1.0] * n

    for _ in range(max_iter):
        residuals = [y - (slope * x + intercept) for x, y in zip(x_vals, y_vals)]
        # MAD-based scale; floor to avoid division blow-ups on tight stints
        abs_r = sorted(abs(r) for r in residuals)
        mad = abs_r[n // 2] if n else 0.0
        scale = max(1.4826 * mad, 1e-3)

        new_weights = [
            1.0 if abs(r) <= k * scale else (k * scale / abs(r))
            for r in residuals
        ]

        # Weighted least squares closed form
        sw = sum(new_weights)
        sx = sum(w * x for w, x in zip(new_weights, x_vals))
        sy = sum(w * y for w, y in zip(new_weights, y_vals))
        sxx = sum(w * x * x for w, x in zip(new_weights, x_vals))
        sxy = sum(w * x * y for w, x, y in zip(new_weights, x_vals, y_vals))
        denom = sw * sxx - sx * sx
        if abs(denom) < 1e-10:
            break
        new_slope = (sw * sxy - sx * sy) / denom
        new_intercept = (sy - new_slope * sx) / sw

        if abs(new_slope - slope) < tol and abs(new_intercept - intercept) < tol:
            slope, intercept, weights = new_slope, new_intercept, new_weights
            break
        slope, intercept, weights = new_slope, new_intercept, new_weights

    # R^2 against weighted mean
    y_mean = sum(w * y for w, y in zip(weights, y_vals)) / max(sum(weights), 1e-10)
    ss_tot = sum(w * (y - y_mean) ** 2 for w, y in zip(weights, y_vals))
    ss_res = sum(w * (y - (slope * x + intercept)) ** 2 for w, x, y in zip(weights, x_vals, y_vals))
    r_squared = 1.0 - ss_res / ss_tot if ss_tot > 1e-10 else 0.0
    return (slope, intercept, r_squared)
```

- In `_fit_stint_degradation()` at `f1_data.py:4513`, replace the `slope, intercept, r_sq = _linear_regression(...)` call on `fuel_corrected` with `_huber_regression(...)`. Keep `raw_slope = _linear_regression(tyre_ages, raw_times)` as OLS — `raw_pace_trend_s_per_lap` is meant to be "what the stopwatch did," outliers and all.
- **Do not touch `_detect_cliff()`.** Cliff detection's BIC math is calibrated to OLS SSE; switching the inner fit silently to Huber would shift the BIC threshold. Cliff detection still uses `_linear_regression_raw` on its segments.
- Add a `regression_method` field to the stint output (`"huber"` for fuel-corrected deg, `"ols"` for raw pace trend).

Acceptance:

- A synthetic stint of linear data + one severe outlier produces a Huber slope materially closer to the underlying truth than the OLS slope. Add a unit test asserting this gap.
- A clean linear stint produces a Huber slope within 1e-3 of OLS (Huber should degrade gracefully).
- `_detect_cliff` results on the same data are unchanged (regression method swap is scoped to deg rate, not cliff fit).
- Existing snapshot tests on synthetic deg data may need their pinned `deg_rate_s_per_lap` adjusted by ≤0.002. Update intentionally; document in the test diff.

Reference: Aguad & Thraves 2023; Huber 1964 (original); Heilmeier 2018 uses a robust-loss equivalent for tyre fits.

Risk:

- **Risk:** Huber's IRLS may not converge on degenerate stints (all points identical, or only 3 points). The fallback to `_linear_regression_raw` covers the `n < 3` case; the `denom < 1e-10` early-exit covers degenerate ones — verify both with tests.
- **Trigger:** A stint where all clean laps happen to have the same tyre age (unlikely) or the same lap time (also unlikely).
- **Solutions:** (1) Keep the current early exits. (2) Add a `max_iter` cap on top of the convergence check (already in the sketch). (3) Fall back to OLS if Huber returns a non-finite slope.
- **Recommendation:** (1) + (3). Belt and braces.

Open question:

- Should the chat layer expose `regression_method`? Probably no — it is engineering detail and surfacing it would add a footnote nobody asked for. Keep it in the dict for debugging; do not pipe to the widget.

Run:

```bash
cd server
python -m pytest tests/test_f1_data.py::TestHuberRegression -v
python -m pytest tests/test_f1_data.py -v
```

---

### Task F12 — Traffic / Dirty-Air Covariate

Files:

- Modify: `server/f1_data.py`
- Modify: `server/chat.py`
- Modify: `client/src/components/chat-widgets/DegTrendChart.jsx`
- Test: `server/tests/test_f1_data.py`, `server/tests/test_chat.py`

Change description:

- Stuck-in-a-DRS-train laps lose 0.3–0.8 s/lap without any extra tyre wear. OLS attributes the gap-induced loss to tyre age. Fix: add a traffic covariate to the deg model.
- Upstream of `_fit_stint_degradation()`, attach a `gap_ahead_seconds` value per lap. Source: `session.laps['GapAhead']`-equivalent — FastF1 exposes `GapToLeader` and lap-by-lap positions; the actual gap to the car ahead per lap is reconstructible via:
  - For each lap, find the car classified one position ahead at that lap.
  - Compute cumulative-lap-time delta between the two cars at the line.
- Build the per-lap `gap_ahead_seconds` once in the lap-cleaning pipeline so the per-driver fit can read it directly.
- Change `_fit_stint_degradation()` to fit a multivariate model when the gap data is available:

```
lap_time = base + α * (tyre_age - 1) + β * traffic_loss(gap_ahead) + γ * (lap_n - min_lap)
```

  - α is the deg rate (what we currently emit).
  - β captures dirty-air loss. Use `traffic_loss(gap) = max(0, 1 - gap/1.5)` so the covariate is 1.0 when bumper-to-bumper and 0.0 when the gap is ≥1.5 s. This is the "DRS-train zone" definition from Catapult RaceWatch.
  - γ is the fuel-burn coefficient. Already known per circuit (F10) — fix it instead of fitting it. Fitting all three simultaneously gets unstable on short stints.
- Two-stage fit:
  1. Pre-subtract fuel burn using the F10 per-circuit coefficient (already in `fuel_corrected` after F10 lands).
  2. Fit `lap_time_fuel_corrected = base + α * tyre_age + β * traffic_loss(gap_ahead)` via Huber-weighted least squares over the two-column design matrix.
- New output fields per stint:
  - `tyre_deg_rate_s_per_lap` (renamed from `deg_rate_s_per_lap`; keep the old key as an alias for backward compatibility).
  - `traffic_loss_rate_s_per_lap` (β, the per-unit-traffic-loss coefficient).
  - `avg_gap_ahead_s` (mean of the per-lap gap, for the widget).
  - `traffic_dominated`: `True` if `β * mean(traffic_loss)` exceeds `α * mean(tyre_age)` over the stint. The chat layer must say "traffic loss dominates" instead of "high deg rate."
- If `gap_ahead_seconds` is missing (data unavailable, e.g. early-race fast lap with nobody ahead), fall back to single-covariate Huber on tyre_age only (Phase 1 F11 behaviour) and emit `traffic_loss_rate_s_per_lap: None`.

`_make_deg_trend_chart_widget()` in `chat.py`:

- Pass `traffic_loss_rate_s_per_lap`, `avg_gap_ahead_s`, `traffic_dominated` through.
- In the tyre guidance prompt fragment, add: when `traffic_dominated` is true, describe the slope as primarily traffic loss not tyre wear; phrase as "stuck in dirty air, ~X s/lap of which is car ahead, not tyres."

`DegTrendChart.jsx`:

- Below the regression label, add a small `"traffic loss: N s/lap"` annotation when `traffic_loss_rate_s_per_lap > 0.05`. Avoid showing it when missing or near-zero (visual noise).

Acceptance:

- A synthetic stint with no traffic produces β ≈ 0 and α matches Phase 1 F11 within 1e-3.
- A synthetic stint with constant 0.5s traffic produces non-zero β and α closer to the true value than the F11 single-covariate fit.
- The `deg_rate_s_per_lap` field still exists (alias to `tyre_deg_rate_s_per_lap`) so the cliff widget and any other consumer keeps working.
- `traffic_dominated` is `True` on a clearly DRS-train stint (synthetic, gap ≤ 0.7 s on every lap, α ≈ 0).
- Chat snapshot test: when `traffic_dominated`, the answer text uses the word "traffic" or "dirty air" and does not lead with the deg rate.

Reference: Catapult RaceWatch white paper; Frontiers in Sports 2025 (Choudhury et al.) — multivariate deg fit with traffic covariate is standard in published work.

Risk:

- **Risk:** Reconstructing `gap_ahead_seconds` from FastF1 lap-by-lap data is expensive (O(laps × drivers)). Doing it per chat request would slow the deterministic path noticeably.
- **Trigger:** Any analyze_stint_degradation tool call.
- **Solutions:** (1) Compute the per-lap gap matrix once per session, cache to the same disk cache directory as FastF1 session data. (2) Compute only the focal driver's gap-ahead vector lazily on first use; cache in-memory. (3) Use FastF1's `add_relative_distance` helper if it gives the lap-by-lap gap directly — verify at implementation time.
- **Recommendation:** (3) if available, else (1). The deterministic path already pays the FastF1 session-load cost; this is incremental.

Open question:

- Should `traffic_loss_rate_s_per_lap` propagate into `_detect_cliff` as a *covariate* (so cliffs aren't triggered by getting stuck behind a slower car)? Probably yes, but the BIC threshold needs recalibration. Defer to a follow-up; for V1 the cliff detector keeps reading `fuel_corrected` and the user accepts that traffic-stuck cliffs may be false positives.

Run:

```bash
cd server
python -m pytest tests/test_f1_data.py::TestTrafficCovariate tests/test_chat.py::TestDegTrendWording -v
cd client && npm run build
```

---

## Phase 2 — Bayesian State-Space Deg Model (F13, research-grade, ~3 weeks, OPTIONAL)

> **Research-grade, opt-in only.** Adds a heavy dependency (`pymc` or `numpyro`). Disabled by default. Not exposed via the agentic system prompt until validated against ≥3 seasons of real data. The intent is to ship as an *alternative* analyzer that returns posterior uncertainty, alongside the existing OLS/Huber output.

### Task F13 — Bayesian State-Space Alternative Analyzer

Files:

- Add: `server/deg_bayesian.py` (new module)
- Modify: `server/f1_data.py` (one-line dispatch flag)
- Modify: `server/tools.py` (extend `analyze_stint_degradation` with `analyzer="bayesian"` parameter)
- Modify: `server/chat.py` (widget builder consumes posterior fields when present)
- Test: `server/tests/test_deg_bayesian.py` (new)
- Dependency: add `numpyro>=0.13` (preferred over `pymc` for cold-start time) to `server/requirements.txt`

Change description:

- Cappello & Hoegh 2025 (arXiv:2512.00640) is the only published F1-specific tyre-degradation paper using a state-space formulation. They model:

```
lap_time_n = base_pace + fuel_mass_effect_n + latent_tire_pace_n + ε_n
latent_tire_pace_n ~ Normal(latent_tire_pace_{n-1} + drift, σ_state)
ε_n ~ SkewedT(ν, μ_skew)
pit_stop ⇒ latent_tire_pace_n reset
```

  Beats ARIMA on the Hamilton 2025 Austrian GP case study. The latent state captures non-linear deg without forcing a linear or piecewise-linear shape, and the skewed-t noise handles the long-tail lap-time outliers natively (no separate outlier filter needed).
- `server/deg_bayesian.py` exposes one function:

```python
def fit_stint_bayesian(
    lap_times: list[float],
    tyre_ages: list[float],
    fuel_burned: list[float],
    pit_lap_indices: list[int] | None = None,
    num_samples: int = 1000,
    num_warmup: int = 500,
) -> dict:
    """
    Returns a dict with:
      latent_tire_pace_mean: list[float]    — posterior mean per lap
      latent_tire_pace_q05:  list[float]    — 5th percentile
      latent_tire_pace_q95:  list[float]    — 95th percentile
      deg_rate_posterior_mean: float        — average per-lap drift
      deg_rate_credible_interval: [lo, hi]  — 90% CI
      cliff_probability:    float           — P(latent jumps > threshold)
      effective_sample_size: float
      r_hat: float
    """
```

- Use NumPyro's NUTS sampler. Set `num_chains=2` for `r_hat` diagnostic. Default `num_samples=1000, num_warmup=500` keeps fit time under ~10 s for a 30-lap stint on a modern CPU; measure and adjust.
- Pit-stop state resets: implement by zeroing the latent state and re-initialising drift at the pit lap. The model's likelihood treats each stint as a fresh trajectory but shares the global drift hyperprior.
- `f1_data.py` dispatch:

```python
def analyze_stint_degradation(
    ...,
    analyzer: str = "ols",   # "ols" | "huber" | "bayesian"
) -> dict:
    if analyzer == "bayesian":
        from deg_bayesian import fit_stint_bayesian
        ...
    else:
        # existing Phase 1 path
        ...
```

- Tool definition in `tools.py`: add `analyzer` parameter, document the three options, default to `"huber"` (Phase 1 default after F11 lands). Document the Bayesian option as "use only when explicitly asked about uncertainty bounds." Keep it out of the assistant's default selection logic by *not* mentioning it in the composite-tool system prompt.
- Widget: when posterior fields are present (Bayesian path), `DegTrendChart.jsx` renders a shaded 90% credible band around the regression line. When absent (OLS/Huber path), renders the existing single regression line. The renderer should detect presence by checking for `latent_tire_pace_q05` rather than gating on `analyzer`.

Acceptance:

- `fit_stint_bayesian` on a synthetic linear-deg stint produces `deg_rate_posterior_mean` within ±0.005 of the true rate and `r_hat < 1.05`.
- `fit_stint_bayesian` on a cliff stint (linear-then-steep) shows the posterior latent_tire_pace bend after the cliff age, and `cliff_probability > 0.5`.
- The OLS analyzer path is unchanged when `analyzer="ols"`.
- Bayesian fit time for a 30-lap stint is under 15 s on the development machine. If it exceeds 30 s, reduce `num_samples` and revisit.
- The new dependency is gated: an `ImportError` in `deg_bayesian.py` raises a clear `RuntimeError("Bayesian analyzer requires numpyro — install with pip install numpyro")` at tool-call time rather than at module import. The Phase 1 path must still run on a machine without numpyro installed.

Reference: Cappello & Hoegh 2025 (arXiv:2512.00640); Phillips 2014 state-space treatment of lap times; Todd et al. Imperial arXiv:2501.04067.

Risk:

- **Risk:** Adding `numpyro` adds JAX as a transitive dependency. JAX is large (~150 MB) and has platform-specific wheels. Deployment cost goes up.
- **Trigger:** First time the server is built in CI or deployed to a fresh environment.
- **Solutions:** (1) Make `numpyro` an **optional extra**: `pip install f1dash[bayesian]`. Keep the import lazy. (2) Use `pymc` instead — pure NumPy/PyTensor, no JAX. Slower per-sample but smaller install. (3) Don't ship Phase 2. Treat it as an internal-research-only branch.
- **Recommendation:** (1). Optional extra; lazy import; clear error message when missing.

Risk:

- **Risk:** Exposing posterior uncertainty in chat creates a UX problem — Claude has no native way to verbalise "90% CI is 0.04–0.09 s/lap" without sounding academic.
- **Trigger:** First chat answer using the Bayesian analyzer.
- **Solutions:** (1) Translate credible interval into plain language in the chat tool result: `"deg rate is between 0.04 and 0.09 s/lap with high confidence (90%)."` Provide a `chat_phrasing` field pre-formatted in `deg_bayesian.py`. (2) Suppress the CI in chat; only show it on the widget. (3) Don't expose Bayesian to chat at all — keep it as a dashboard-only feature.
- **Recommendation:** (1). Pre-format the phrasing in the analyzer; both chat and widget read the same field.

Open question:

- Should Phase 2 *replace* `_detect_cliff` with `cliff_probability` from the Bayesian posterior when the Bayesian analyzer ran? Probably yes when both are present — but only after side-by-side validation on a back-test of every race weekend where the OLS path detected a cliff. Defer to a Phase 2.1 milestone.

Run:

```bash
cd server
python -m pytest tests/test_deg_bayesian.py -v --runslow
python -m pytest tests/ -v   # Phase 1 path must remain green
```

---

## Phase 3 — BOCPD Live Cliff Alerting (F14, research-grade, ~3 weeks, OPTIONAL)

> **Research-grade, opt-in only.** Pure NumPy — no heavy dependency. The current `_detect_cliff` is offline-retrospective: it can only flag a cliff after seeing the full stint. F14 implements Adams & MacKay 2007 Bayesian Online Changepoint Detection so a live race feed can fire a cliff alert *as the cliff is happening*. Would be novel published work in F1 — no prior literature pairs BOCPD with F1 tyres.

### Task F14 — `_detect_cliff_online()` and `analyze_stint_cliff_live` Tool

Files:

- Add: `server/deg_bocpd.py` (new)
- Modify: `server/tools.py` (new tool `analyze_stint_cliff_live`)
- Modify: `server/chat.py` (new widget builder `_make_live_cliff_widget`)
- Add: `client/src/components/chat-widgets/LiveCliffWidget.jsx` (new)
- Modify: `client/src/components/AnswerRenderer.jsx` (new case)
- Test: `server/tests/test_deg_bocpd.py` (new)

Change description:

- Adams & MacKay 2007 (arXiv:0710.3742) maintains a posterior over **run length** — the number of laps since the last changepoint — and updates it online with each new lap-time observation. After each lap:
  - `P(r_t | x_{1:t})` is updated via the standard BOCPD recursion.
  - A "growth" probability and a "changepoint" probability are computed.
  - If the changepoint probability exceeds a threshold *and* the post-CP segment has higher mean lap time / slope than pre-CP, fire a cliff alert.
- Hazard function: constant hazard `H(r) = 1/200` (one expected changepoint per ~200 laps of green-flag running; tyre-cliff prior).
- Predictive distribution: Normal with mean = base_pace + drift * run_length, variance σ². Update suffstats incrementally.
- Module API:

```python
class OnlineCliffDetector:
    def __init__(self, hazard: float = 1/200, cp_threshold: float = 0.5): ...
    def update(self, lap_time: float, tyre_age: float) -> dict:
        """
        Called once per new lap. Returns:
          run_length_posterior:    list[float]   — P(r_t | x_{1:t}) per run length
          changepoint_probability: float         — P(changepoint at t)
          cliff_alert:             bool          — cp_probability > threshold AND post slope > pre slope
          most_likely_run_length:  int
        """
```

- New tool `analyze_stint_cliff_live`:
  - Inputs: `driver`, `year`, `round`, optional `up_to_lap`.
  - Behaviour: replays the stint lap-by-lap through `OnlineCliffDetector`, returns the per-lap timeline of changepoint probabilities and the first lap (if any) where the alert fired.
  - Useful for: post-race "when *could* we have known the cliff was coming" forensics, plus the future live-telemetry-feed integration when/if F1Dash gets one.
- Widget: line chart of `changepoint_probability` over tyre age; vertical marker where the alert fired; comparison line showing the offline `_detect_cliff` result on the same data (for V1 sanity-check).

Acceptance:

- Synthetic test: clean linear stint produces `changepoint_probability < 0.1` at every lap.
- Synthetic test: clear cliff stint (linear-then-steep) produces `changepoint_probability > 0.5` within 2 laps of the true cliff onset.
- The online detector's flagged cliff lap is within ±2 laps of the offline `_detect_cliff` result on the same data for ≥80% of a 5-race back-test (Phase 3 validation gate).
- The tool is reachable from chat but **not advertised in the system prompt**. The assistant only calls it when the user asks "when could we have known," or similar.
- No new dependency. NumPy is already pulled in by FastF1.

Reference: Adams & MacKay 2007 (arXiv:0710.3742); van Erven et al. 2024 review of online changepoint methods.

Risk:

- **Risk:** BOCPD's online alert may fire spuriously when a single very fast lap (push lap, low-fuel lap at stint end) shifts the posterior toward a changepoint that isn't really there.
- **Trigger:** A driver setting a personal-best lap mid-stint on cooling tyres.
- **Solutions:** (1) Require the post-CP slope to exceed the pre-CP slope by the same `slope_abs_increase_threshold = 0.06` already used by offline detection. (2) Require alert sustained over 2 consecutive laps before emitting. (3) Combine BOCPD with Huber-weighted suffstats so single-lap outliers down-weight in the recursion.
- **Recommendation:** (1) + (2). Match the offline detector's slope-increase floor and require 2-lap sustainment. (3) is a Phase 3.1 enhancement.

Risk:

- **Risk:** BOCPD's recursion is O(t) memory and O(t) per-lap compute. A long stint (40+ laps) is fine; a full-race history (78 laps) is also fine; but if we ever apply it to a full season the memory grows.
- **Trigger:** Future feature that calls the detector on every driver's full season.
- **Solutions:** (1) Cap the run-length posterior at the most recent 50 entries (standard truncation). (2) Reset at each pit stop (already correct — each stint is its own BOCPD instance). (3) Stream-only API; don't store per-lap posteriors beyond the alert lap.
- **Recommendation:** (2) is already the design. Add (1) as a configurable safety cap.

Open question:

- Should `analyze_stint_cliff_live` be folded into `analyze_stint_degradation` as a `cliff_method="bocpd"` parameter, or stay a separate tool? Separate tool keeps the chat UX clean and the tool description short. Recommendation: separate tool.

Open question:

- Publishability: this is genuinely novel in F1 context. If the back-test validation passes, write a short methods paper and post to arXiv. Out of scope for this implementation plan, but worth flagging now so the implementation keeps clean records of the back-test runs.

Run:

```bash
cd server
python -m pytest tests/test_deg_bocpd.py -v
```

---

## Data Availability Requirements

Each task depends on specific FastF1 / OpenF1 fields. Confirm each is reachable before starting the task — some are already extracted, some need plumbing.

| Field | Source | Already extracted? | Used by |
|---|---|---|---|
| `lap_time_s` | `session.laps['LapTime']` | Yes (`f1_data.py:_extract_laps_from_session`) | F8–F14 |
| `tyre_age` | `session.laps['TyreLife']` | Yes | F8–F14 |
| `compound` | `session.laps['Compound']` | Yes | F8 (in-lap detection via compound change) |
| `track_status` | `session.laps['TrackStatus']` | Yes (`f1_data.py:1686`, `:4278`) — already on lap dict | F9 |
| `lap_number` | `session.laps['LapNumber']` | Yes | All |
| `is_in_lap` / pit indicator | Derived from next-stint compound or `session.laps['PitInTime']` | **Partial** — pit time is in raw FastF1 but not on the clean-lap dict. F8 needs a `pit_in_lap: bool` field added to the lap dict. | F8 |
| `gap_ahead_seconds` | Reconstructed from lap-by-lap positions + cumulative times | **No** — must be built in lap-cleaning pipeline | F12 |
| `position` | `session.laps['Position']` | Yes | F12 (gap reconstruction) |
| `fuel_burned_kg` | Estimated from `lap_number * fuel_per_lap_kg`; FastF1 has no fuel telemetry | Derived per lap; per-circuit coefficient (F10) replaces the per-lap-kg scaling | F10, F13 |
| Pit-stop lap indices | `session.laps['PitInTime']`/`PitOutTime` | Yes | F8 (in-lap), F13 (state reset) |
| Race control SC/VSC messages | `session.race_control_messages` | **No** — not currently consumed; F9 fallback only if `TrackStatus` proves unreliable | F9 (fallback) |

Pre-Phase-1 plumbing required:

- Add `pit_in_lap: bool` to the clean-lap dict in `_extract_laps_from_session` (derived from `PitInTime` not being NaT or compound changing on the next lap).
- Add `position: int` to the clean-lap dict (already in FastF1, may not be on the cleaned dict — verify).
- Add `gap_ahead_seconds: float | None` placeholder. F12 fills this in.

---

## Validation Checklist

Phase 1 (must all pass before Phase 1 ships):

- [ ] `EXCLUDE_FIRST_N_LAPS = 2` and `EXCLUDE_IN_LAP = True` constants exist and are respected by `_fit_stint_degradation()`.
- [ ] First two laps of every stint are dropped before regression.
- [ ] In-lap of stints that end at a pit stop is dropped; final lap of an unpitted final stint is kept.
- [ ] `excluded_lap_count` is present on every returned stint dict.
- [ ] Laps with `track_status` in `{"2","4","5","6","7"}` are dropped.
- [ ] `sc_lap_count` is present on every stint; `deg_rate_confidence` is `"low"` when ≥40% non-green.
- [ ] `CIRCUIT_FUEL_COEFFICIENT` table exists in `circuit_profiles.py` with entries for all 24 calendar circuits.
- [ ] `get_circuit_fuel_coefficient()` returns 0.040 for Monaco, 0.025 for Belgium, 0.030 fallback.
- [ ] `_fit_stint_degradation()` accepts a per-circuit coefficient and emits `fuel_burn_gain_assumption_source`.
- [ ] `_huber_regression()` exists, converges on clean data, beats OLS on data with one severe outlier.
- [ ] `_detect_cliff()` is unmodified and continues to use OLS internally.
- [ ] `_fit_stint_degradation()` fits a two-covariate model `(tyre_age, traffic_loss)` when `gap_ahead_seconds` is present per lap.
- [ ] `tyre_deg_rate_s_per_lap`, `traffic_loss_rate_s_per_lap`, `traffic_dominated` fields are present.
- [ ] `deg_rate_s_per_lap` remains as an alias for backward compatibility.
- [ ] `DegTrendChart.jsx` shows a "traffic loss: N s/lap" annotation when `traffic_loss_rate_s_per_lap > 0.05`.
- [ ] Chat tyre-deg phrasing distinguishes "stuck in dirty air" from "tyre cliff" when `traffic_dominated` is true.
- [ ] All existing server tests still pass.

Phase 2 (gate before Phase 2 ships):

- [ ] `numpyro` is an optional extra; Phase 1 path runs without it.
- [ ] `fit_stint_bayesian()` recovers true deg rate within ±0.005 on synthetic linear data.
- [ ] `r_hat < 1.05` and `effective_sample_size > 200` on the same.
- [ ] Bayesian widget renders 90% credible band; OLS/Huber widget unchanged.
- [ ] `chat_phrasing` field is pre-formatted in plain language.
- [ ] Bayesian analyzer is NOT advertised in the system prompt for default selection.

Phase 3 (gate before Phase 3 ships):

- [ ] BOCPD online detector matches offline `_detect_cliff` within ±2 laps on 80% of a 5-race back-test.
- [ ] Pure NumPy — no new dependency in `requirements.txt`.
- [ ] Alert requires both the slope-increase floor and 2-lap sustainment.
- [ ] `analyze_stint_cliff_live` tool exists but is NOT advertised in the default system prompt.

---

## Risks and Open Questions

Per CLAUDE.md risk-surfacing protocol, the cross-task risks that need decisions are below. Per-task risks are in each task block above.

| Risk | When it triggers | Proposed resolution | Decision needed by |
|---|---|---|---|
| F10 hand-tuned fuel-coefficient table is not calibrated against real data | F10 ships; any per-circuit deg comparison changes subtly | Ship the hand-tuned table; flag `fuel_coefficient_source` in widget; add a calibration script as Phase 1.5 follow-up. | F10 start |
| F11 Huber switch shifts pinned snapshot deg rates by up to 0.002 s/lap on existing tests | F11 lands | Update snapshots intentionally with a `diff-explainer` comment; do not pretend Huber is OLS. | F11 start |
| F12 gap-ahead reconstruction is O(laps × drivers) per session and slow on first chat request | F12 first deterministic invocation | Cache per-session matrix to FastF1 disk cache directory; reuse FastF1's `add_relative_distance` helper if available. | F12 start |
| F12 chat layer must hedge wording when `traffic_dominated` is true, otherwise the answer attributes traffic loss to tyres | F12 ships and any DRS-train stint is queried | Phrase explicitly: "X s/lap of which is dirty-air loss, not tyre wear." Add a system-prompt fragment for this. | F12 chat update |
| F13 `numpyro` dependency adds ~150 MB to install footprint | First deployment after Phase 2 | Optional extra (`pip install f1dash[bayesian]`); lazy import. | Phase 2 start |
| F13 posterior uncertainty surfaced as a credible interval reads as academic; Claude has no natural phrasing | First Bayesian chat answer | Pre-format a `chat_phrasing` plain-language string in `deg_bayesian.py`; widget and chat both read it. | F13 implementation |
| F14 BOCPD spurious alerts on push laps | First live-replay back-test | Require slope-increase floor (`>= 0.06`) and 2-lap sustainment before alert. Same thresholds as offline. | F14 implementation |
| F14 publishability — if back-test passes, this is novel in F1 | Phase 3 ships and validates | Record back-test results; write a short methods paper to arXiv. Out of scope for code, in scope for documentation. | Post-Phase-3 |
| Cliff detection is unchanged across all three phases, but new pre-filtering (F8/F9) changes the data feeding it | F8 and F9 ship | Re-run all `_detect_cliff` snapshot tests against filtered inputs; update intentionally; verify no real-race cliff that was previously detected is now lost. | F8 and F9 integration |
| Exposing `analyzer` parameter on `analyze_stint_degradation` tool creates a footgun if the agentic loop picks `"bayesian"` for routine questions | Phase 2 tool definition lands | Default `analyzer="huber"`; document the Bayesian option in the tool description as "only when the user asks about uncertainty"; keep Bayesian off the composite-tool selection guidance in the system prompt. | Phase 2 tool definition |
| Phase 1, 2, 3 share a single output dict shape; adding/aliasing fields across phases can drift | Any phase ships and the widget already consumes a field that gets renamed | Maintain backward-compatible aliases (e.g. `deg_rate_s_per_lap` → `tyre_deg_rate_s_per_lap` after F12); add a schema-shape test that pins every field name. | Each phase merge |

---

## Notes On Overlap With Other Plans

This plan extends the 2026-05-15 cliff-detection feature without modifying its detector internals. The cliff detector keeps its OLS BIC math; this plan only feeds it cleaner inputs.

This plan also partially overlaps with the counterfactual race simulation plan (2026-05-19). That plan consumes `_fit_stint_degradation()` output as one of its primary inputs. Phase 1 of *this* plan should ship before the counterfactual simulator begins integration, so the simulator gets the higher-quality deg slopes from day one. Phase 2 and Phase 3 are independent and do not block the simulator.

---

## Commit Plan

Phase 1 (one commit per task, ship as one PR):

1. `feat(deg): exclude out-laps and in-laps from stint regression (F8)`
2. `feat(deg): drop SC/VSC laps and flag low-confidence stints (F9)`
3. `feat(deg): per-circuit fuel coefficient table (F10)`
4. `feat(deg): Huber robust regression for fuel-corrected deg fit (F11)`
5. `feat(deg): traffic / dirty-air covariate via gap-ahead reconstruction (F12)`
6. `feat(chat): hedge tyre wording when traffic loss dominates`
7. `feat(client): traffic-loss annotation in DegTrendChart`

Phase 2 (separate PR, optional):

8. `feat(deg): Bayesian state-space analyzer via NumPyro (F13)`
9. `feat(chat): plain-language phrasing for posterior credible intervals`
10. `feat(client): credible-band overlay in DegTrendChart`

Phase 3 (separate PR, optional):

11. `feat(deg): online BOCPD cliff detector (F14)`
12. `feat(tools): analyze_stint_cliff_live tool`
13. `feat(client): LiveCliffWidget`
