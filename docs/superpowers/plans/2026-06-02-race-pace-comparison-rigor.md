# Race-Pace Comparison Rigor

> Status: Phase 0 complete (committed `31a5e0b`). Phases 1–4 planned, not started.
> Phase 5 is a separate follow-up. Estimated effort: ~2–3 focused days for 1–4.

## Context

`analyze_race_pace_battle` (server/f1_data.py) compares two drivers' race pace
per tyre compound. A user-reported bug (Miami NOR vs ANT) exposed a phantom
~0.45 s/lap gap: the per-stint pace metric extrapolated each stint's OLS
regression line to **tyre age 1** (`fuel_corrected_pace_at_age_1_s`), which is
fragile on noisy/low-R² stints. Antonelli's scattered Medium stint (R²=0.07)
projected ~0.9s slow and dominated the lap-weighted headline.

**Phase 0 (done, committed):** replaced the comparison estimator with a
Theil-Sen robust fit of fuel-corrected pace vs tyre age, evaluated at the
**midpoint of the tyre-age range both drivers ran** (interpolation, not edge
extrapolation); headline delta is the lap-weighted mean of per-compound
common-age deltas. Miami NOR vs ANT: `-0.455 → +0.006 s/lap` (dead even).
The age-1 field is retained for the degradation chart, where it is valid.

This plan takes the comparison from "correct for similar-length stints" to the
genuine best for cross-driver per-compound pace, validated by a deep-research
pass and a Codex design review.

### Inputs that shaped this plan
- **Research** (deep-research, 102 agents): median is the practitioner *floor*;
  the ceiling is a fuel-corrected robust regression evaluated at a common
  in-range tyre age, with confidence/uncertainty surfaced.
- **Codex design review** validated the core and raised: (a) fuel coefficient φ
  is **not identifiable** from a single stint (race-lap ≈ tyre-age collinear) —
  treat as a fixed assumption, sensitivity-test it; (b) contaminated-lap
  filtering is the real foundational gap; (c) **confidence gating** is the
  biggest missing piece; (d) cliff awareness must NOT be skipped (one line
  through a cliff is misspecification robust fitting can't fix); (e) the
  degradation *rate* output is still OLS and partly fragile.

## Goal

Fairly compare two drivers' representative per-lap race pace per compound,
correcting for fuel (across race phases), tyre degradation + tyre-age mismatch,
and outliers, and **surfacing how confident the comparison is**.

---

## Phase 1 — Audit & fix contaminated-lap filtering (foundational)

Robust fitting reduces but does not eliminate SC/VSC, pit in/out, and restart
laps. Confirm `_filter_clean_race_laps` removes them before any fit.

- [ ] Read `_filter_clean_race_laps`; enumerate exactly what it excludes.
- [ ] If SC/VSC laps are not excluded, add exclusion via FastF1 `TrackStatus`
      (status codes 4/6/7 = SC/VSC). Keep pit in/out exclusion.
- [ ] Test: synthetic stint containing an SC-flagged lap → that lap is dropped
      from the fit; a clean stint is unchanged.

Files: `server/f1_data.py`, `server/tests/test_f1_data.py`.

## Phase 2 — Race-wide fuel normalization (top correctness fix)

Per-stint fuel anchoring leaves a residual bias when two drivers run the same
compound in different race phases. Normalize every lap to one race-wide datum.

- [ ] Add helper `_fuel_corrected_time(raw_s, race_lap, total_laps, phi=0.03, m0=100.0)`
      → `raw_s - phi * m0 * (1 - (race_lap - 1) / total_laps)`.
- [ ] Thread `total_laps` (session total / max lap) and absolute `lap_number`
      into `_fit_stint_degradation`; replace the per-stint `0.04*(n-min_lap)`
      anchoring with the race-wide correction.
- [ ] φ stays a FIXED constant (Codex: not identifiable from one stint).
- [ ] Test: two drivers, same compound, **different race phases** (e.g. ages
      1–12 at race laps 2–13 vs race laps 35–46), identical true pace →
      common-age delta ~0. (Fails under per-stint anchoring, passes race-wide.)
- [ ] Sensitivity check (not a unit test): real Miami delta stays ~0 across
      φ ∈ [0.025, 0.05]; record the range in the commit message.

Files: `server/f1_data.py`, `server/tests/test_f1_data.py`.

## Phase 3 — Cliff-aware comparison (wiring, not new modelling)

Cliff detection already exists (`_detect_cliff`, BIC two-segment model) and
populates `cliff_detected`, `cliff_tyre_age`, pre/post deg rates per stint, but
the pace comparison ignores it.

- [ ] In `_align_stints_by_compound`: when either matched stint has
      `cliff_detected`, cap the common tyre-age range `hi` at the pre-cliff
      boundary `min(cliff_tyre_age_a, cliff_tyre_age_b) - 1`, and compare there.
- [ ] If the resulting pre-cliff overlap is too short (< ~4 laps), fall back to
      whole-stint robust pace and mark the comparison low-confidence (Phase 4).
- [ ] Test: two stints, one with a cliff at age 14 → comparison reference age
      ≤ 13.

Files: `server/f1_data.py`, `server/tests/test_f1_data.py`.

## Phase 4 — Confidence gating (Codex's biggest catch)

A delta from a 9-lap overlap with 2 contaminated laps and divergent slopes must
not be presented like a clean 20-lap overlap. Generalises the original bug's
lesson: don't present a shaky number as authoritative.

- [ ] Per matched compound, compute `pace_comparison_confidence`
      (high/med/low) from: shared-overlap lap count, excluded-lap count,
      slope divergence `|robust_slope_a - robust_slope_b|`, and cliff status.
- [ ] Add per-compound + overall confidence to the result payload.
- [ ] Surface in the analysis system prompt (`server/chat.py`) so the answer
      hedges low-confidence deltas explicitly.
- [ ] Test: short overlap + divergent slopes → "low"; clean 20-lap, aligned
      slopes → "high".

Files: `server/f1_data.py`, `server/chat.py`, `server/tests/test_f1_data.py`.

## Phase 5 — Robust degradation rate (separate follow-up)

Codex flagged that `deg_rate_s_per_lap` still comes from OLS, so the old
fragility survives in that output. Swap to Theil-Sen for consistency.

- [ ] Replace the OLS slope used for `deg_rate_s_per_lap` / `positive_deg_rate`
      with the Theil-Sen slope already computed in Phase 0.
- [ ] Reconcile the degradation chart + existing deg tests (larger blast radius
      — this is why it is a separate commit/PR).

Files: `server/f1_data.py`, deg-chart widget, `server/tests/test_f1_data.py`.

---

## Explicitly out of scope (rejected — confirmed by research + Codex)

- **Track-evolution term** — collinear with fuel/lap/tyre-age in race stints;
  not identifiable, degrades interpretability.
- **Bayesian state-space model** — overkill for short, strategy-censored,
  event-contaminated public data; needs per-track tuning to beat Theil-Sen.
- **Mean-gap-over-range vs midpoint** — identical for linear fits under uniform
  weighting; no gain.
- **Learning φ from data** — not identifiable per stint; keep fixed.

## Risks & caveats

- φ (≈0.03 s/kg) and M₀ (≈100 kg) are practitioner assumptions, not observable
  externally. A wrong φ leaks into the degradation slope (collinearity). Mitigate
  by sensitivity-testing, not by fitting φ.
- Cliff detection reliability is assumed (BIC-gated); Phase 3 trusts
  `cliff_tyre_age`. If detection is noisy, the low-confidence fallback covers it.
- Factors not cleanly observable from public FastF1 data (DRS trains, dirty air
  on non-outlier laps, damage, tyre history/scrubbed sets) are surfaced as
  *uncertainty* (Phase 4), never as corrections.

## Verification (every phase)

TDD: write the failing test first, watch it fail, implement, watch it pass.
Then run the full `server/tests/` suite (baseline: 24 pre-existing,
environment/pollution failures unrelated to this work — do not regress past
that count) and re-run the real Miami NOR-vs-ANT case to confirm the headline
stays sane. One commit per phase.
