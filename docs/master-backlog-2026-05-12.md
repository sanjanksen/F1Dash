# F1Dash Master Backlog

**Date:** 2026-05-12  
**Source:** Code review of `f1_data.py` + `chat.py` (~5500 lines) + 82-source literature survey.  
**Full detail docs:** `telemetry-critique-2026-05-12.md` (bugs) · `platform-additions-2026-05-12.md` (new features)

---

## BUGS & FIXES

### BUG-01 — Fuel correction hardcoded at 0.04 s/lap (HIGH)
**File:** `f1_data.py` · `_fit_stint_degradation()`  
**Problem:** Circuit-blind. Monaco needs ~0.08 s/lap; Monza ~0.025 s/lap. A 20-lap Monaco stint produces 0.8s of fabricated tyre improvement from under-correction alone.  
**Fix:** Circuit-specific lookup table keyed on `session.event['CircuitLength']`. Formula: `correction ≈ 0.025 + 0.012 * (circuit_km - 3.3)` as a starting point, or a hard-coded 24-circuit table.

### BUG-02 — Cold-tyre laps included in degradation regression (HIGH)
**File:** `f1_data.py` · `_fit_stint_degradation()`  
**Problem:** First 2–3 laps of any stint are thermal build-up (tyre is cold). Including them flattens the slope and can produce `positive_deg = 0.0` for stints where real degradation exists.  
**Fix:** Filter `tyre_age <= 2` before OLS fit. Keep those laps in all other outputs (raw data, scatter plot) but exclude from slope computation.

### BUG-03 — Linear OLS for tyre degradation (MEDIUM-HIGH)
**File:** `f1_data.py` · `_fit_stint_degradation()` + `_linear_regression()`  
**Problem:** Real tyre degradation is nonlinear — bedding-in, stable phase, then cliff. A linear model cannot detect the cliff. `positive_deg = max(0.0, slope)` clips genuinely negative slopes (bedding-in dominated stints) to zero, misleading LLM.  
**Fix:** Polynomial degree-2 fit using `numpy.polyfit(tyre_ages, fuel_corrected, 2)`. Report quadratic coefficient as "degradation acceleration." Detect cliff as where second derivative exceeds threshold. Literature: arXiv:2512.00640.

### BUG-04 — Nearest-neighbor 100m telemetry sampling (MEDIUM)
**File:** `f1_data.py` · `get_lap_telemetry()`  
**Problem:** `(tel['Distance'] - dist).abs().idxmin()` picks the nearest sample to each 100m mark. At 300kph that's ±15–20m positional error — equivalent to ~50ms braking time error at zone boundaries. Braking point comparisons between two drivers can be comparing measurements 30m apart.  
**Fix:** Replace with `np.interp()` across all channels (Speed, Throttle, Brake, Gear, DRS) to exact 100m marks. 5-line change.

### BUG-05 — Outlier lap filter: median+5s misses VSC laps (MEDIUM)
**File:** `f1_data.py` · `_filter_clean_race_laps()`  
**Problem:** TrackStatus filter removes codes 4/5/6 (Safety Car) but misses code '2' (Yellow Flag / VSC in some FastF1 versions). A VSC lap can be 8–15s slower and pass the median+5s threshold on long-lap circuits.  
**Fix:** (1) Add TrackStatus '2' to the exclusion list (verify against FastF1 docs for current mapping). (2) Replace median+5s with IQR filter: `Q1 - 1.5×IQR` to `Q3 + 1.5×IQR`. This adapts to each circuit's pace variance.

### BUG-06 — Representative pace at tyre age 1 (extrapolation outside training range) (MEDIUM)
**File:** `f1_data.py` · `_fit_stint_degradation()`  
**Problem:** `fuel_corrected_pace_at_age_1_s = slope * 1 + intercept` extrapolates the line fitted on ages 5–25 back to age 1 — which is cold-tyre territory and outside the training range. This is used as the weighted pace for cross-driver comparison in `analyze_race_pace_battle`, producing biased comparisons.  
**Fix:** Report `pace_at_age_10_s = slope * 10 + intercept` as primary representative pace (mid-stint stability). Keep age-1 as a secondary output for backwards compatibility.

### BUG-07 — GGV envelope is compound-blind (MEDIUM)
**File:** `f1_data.py` · `_build_ggv_envelope()`  
**Problem:** The 95th-percentile ceiling is built from all laps passed in, regardless of tyre compound or age. A session with mixed Soft/Hard/Medium laps produces a ceiling set by the best-compound performance. Drivers on older compounds will appear to be "not using the car's capability" when they're simply on a slower tyre.  
**Fix:** Accept compound label per telemetry frame; return compound-separated envelopes `{SOFT: {…}, MEDIUM: {…}, HARD: {…}}`. Only compare drivers against the envelope for their specific compound. Tag output with `envelope_source_compound`.

### BUG-08 — Static driver style profiles used in LLM reasoning (MEDIUM)
**File:** `server/driver_styles.py` + `chat.py` system prompt  
**Problem:** Hand-authored profiles (Norris = "late_aggressive", etc.) are injected into LLM context and used to frame telemetry interpretation. This creates confirmation bias — if telemetry shows Norris braking early to save tyres, the LLM will still narrate it as "commitment character." The system already computes data-derived per-session cornering metrics (`trail_brake_pct`, `throttle_acceptance_pct`, `entry_bravery_pct`) that make the static profiles redundant.  
**Fix:** Make `driver_styles.py` injection conditional. When session telemetry is present, suppress static profiles from LLM context. Use computed session metrics as primary style evidence. Retain static profiles as "historical baseline" only, explicitly labeled as such.

### BUG-09 — Corner alignment uses 200m distance tolerance (greedy) (LOW-MEDIUM)
**File:** `f1_data.py` · `_align_corners()`  
**Problem:** Corners matched between drivers by entry distance with 200m greedy nearest-neighbor. On circuits with closely-spaced corners (chicanes, S-bends), the greedy algorithm can mis-pair corners — matching driver A's entry to chicane part 1 with driver B's entry to part 2. No verification that matched corners are the same corner.  
**Fix:** Add a secondary check: matched pairs must have similar apex speed (within 30 kph) and similar corner length. Reject pairs that fail both checks.

### BUG-10 — Theoretical GGV fallback has wrong physical intercept (LOW)
**File:** `f1_data.py` · `_theoretical_max_g()`  
**Problem:** `return 2.0 + speed_kph * 0.012` gives 2.0G at 0 kph, implying 2G of mechanical grip at standstill. The mechanical grip floor of a 2025 F1 car is ~1.2–1.4G. At 0 kph there is no aerodynamic downforce, so 2.0 is physically wrong.  
**Fix:** Clamp the formula: `max(1.3, 1.3 + speed_kph * 0.014)` — mechanical floor 1.3G, aerodynamic gain ~0.014G per kph, reaches ~5.5G at 300kph. Or use a published lookup table.

---

## NEW FEATURES

### FEAT-01 — Cumulative Lap Delta Trace (HIGH VALUE, LOW EFFORT)
**What it is:** At every 100m point of the lap, compute the running cumulative time delta between two drivers (driver A's integrated lap time vs driver B's). Shows exactly WHERE on the circuit each driver gains or loses time — the "mini-sector timing" graphic broadcasters use.  
**Why it matters:** Race engineers look at this before anything else. "Norris gained 0.08s through the chicane but gave back 0.12s on the back straight" is the kind of spatial reasoning the current system can only approximate.  
**How:** The 100m samples already exist in `get_lap_telemetry()`. Integrate speed to get distance-resolved time, compute delta as running sum. One new tool: `get_lap_delta_trace(round, session, driver_a, driver_b)`.  
**Difficulty:** Low (1–2 days)  
**Literature:** Standard in FastF1 practitioner tutorials; FastF1 Playbook 2026 (García).

### FEAT-02 — Car-Adjusted Elo Driver Rating (HIGH VALUE, MEDIUM EFFORT)
**What it is:** Continuously updated driver rating where each race is treated as pairwise matchups. A car-year term is added so the rating separates driver skill from constructor advantage. Updatable after every race.  
**Why it matters:** The #1 user question — "how good is this driver actually?" — is currently answered with hand-authored text. This replaces it with a data-derived number.  
**How:**  
- Pull multi-season race results from Jolpica (already in `f1_data.py`)  
- Standard Elo: `P(A beats B) = sigmoid((θ_A - θ_B) / 400)`; update K×(outcome - P)  
- Car-adjusted variant: `θ_effective = θ_driver + θ_constructor_year`, optimize jointly  
- GAS variant (Holý & Černý, arXiv:2604.09143): adaptive K based on outcome surprise  
- Expose as: `get_driver_elo_rating(driver_code)` → rating, historical trend, head-to-head probabilities  
**Difficulty:** Medium (3–5 days pure Python, Jolpica data)  
**Literature:** Matus (Santa Clara); Holý & Černý arXiv:2604.09143; SIAM car-adjusted Elo paper.

### FEAT-03 — RAPM Driver Skill Estimate (HIGH VALUE, MEDIUM EFFORT)
**What it is:** Regularized Adjusted Plus Minus (from basketball analytics) applied to F1. Ridge regression with driver + constructor indicators, target = positions gained vs. grid. Returns "positions added above median in a median car" per driver.  
**Why it matters:** Complementary to Elo — RAPM handles teammate comparisons well (two teammates share the same constructor term, so any difference is pure driver effect).  
**How:** Design matrix X (driver/constructor binary indicators), target y (grid → finish delta), ridge regression with time-decay weighting. 2014–2024 Jolpica data.  
**Difficulty:** Medium (3 days)  
**Literature:** arXiv:2508.00200 (2025) — direct F1 implementation with code.

### FEAT-04 — Bayesian Driver/Car Decomposition (HIGHEST VALUE, HIGH EFFORT)
**What it is:** Full Bayesian multilevel rank-ordered logit model simultaneously estimating driver skill (θ_driver) and constructor-year advantage (θ_constructor_year). Gold standard for answering "how good is this driver independent of the car?"  
**Why it matters:** The only approach that gives a full posterior distribution over driver skill, not just a point estimate. Can answer "Norris is 0.3–0.5s faster than a median driver, 90% credible interval."  
**How:** PyMC implementation of van Kesteren & Bergkamp (JQAS 2023). Replication code at Zenodo. Offline computation, cached weekly. Expose as `get_driver_bayesian_skill(driver_code)`.  
**Difficulty:** High (2–3 weeks including data pipeline)  
**Literature:** van Kesteren & Bergkamp arXiv:2203.08489, JQAS 2023. Full code at Zenodo.

### FEAT-05 — Track Evolution Model (HIGH VALUE, MEDIUM EFFORT)
**What it is:** Within a session, the track "rubbers in" as cars lay down grip. This improves lap times by 0.5–1.5s from session start to end. Any comparison of laps from different points in a session is confounded by this. Model it and subtract it.  
**Why it matters:** Qualifying lap comparisons between Q1 and Q3 attempts, FP analysis, and any within-session comparison are currently confounded by track evolution. This is larger than most degradation rates.  
**How:** Fit exponential decay model `track_gain(t) = A × (1 − exp(−t/τ))` to the field-wide lap time trend per session. Subtract from individual driver laps before any comparison or regression. New tool: `get_track_evolution_model(round, session)`.  
**Difficulty:** Medium (3–4 days)

### FEAT-06 — Dirty Air / Close-Running Lap Flagging (HIGH VALUE, MEDIUM EFFORT)
**What it is:** Flag laps where a driver was running within 1.0s of the car ahead. These laps lose 0.3–0.5s/lap to aerodynamic wake and should be excluded from clean pace analysis or noted with a penalty.  
**Why it matters:** Race pace comparisons between two drivers are meaningless if one was following the other in dirty air. Currently the system treats all laps as independent.  
**How:** OpenF1 intervals endpoint provides gap data at 3.7Hz. Cross-reference with clean lap list. Flag/exclude laps where `gap_to_car_ahead < 1.0s` for a sustained period. Add `dirty_air_laps_excluded` to race pace battle output.  
**Difficulty:** Medium (3 days — OpenF1 integration exists in `openf1.py`)  
**Literature:** de Groote JSA 2021 (aerodynamic wake quantification).

### FEAT-07 — Polynomial + Cliff Degradation Model (MEDIUM VALUE, MEDIUM EFFORT)
**What it is:** Replace linear OLS with a quadratic fit that captures non-linear tyre wear. Detect the "cliff" — the point where degradation accelerates sharply — as where the second derivative of the fitted curve exceeds a threshold.  
**Why it matters:** Linear models cannot represent the cliff. A driver with a gentle linear degradation and a driver with a late cliff have identical linear slopes but completely different race implications. This matters enormously for strategy.  
**How:** `numpy.polyfit(tyre_ages, fuel_corrected, 2)` gives `[c, b, a]` for `t = a + b*age + c*age²`. Report `c` as "degradation acceleration." Cliff lap = argmax of second derivative crossing threshold. Add to `_fit_stint_degradation()`.  
**Difficulty:** Medium (2–3 days)  
**Literature:** arXiv:2512.00640 (state-space model); Todd et al. ACM SAC 2025 (tyre energy prediction).

### FEAT-08 — Safety Car Probability per Circuit (MEDIUM VALUE, LOW EFFORT)
**What it is:** Historical frequency of Safety Car and Virtual Safety Car events per circuit, exposed as a probability estimate. Updated from Jolpica race data.  
**Why it matters:** SC probability fundamentally changes strategy analysis — at Monaco (~60% SC probability) a 3-stop strategy is undervalued by any model that ignores SC likelihood. "Given a 45% SC probability in the remaining 30 laps, pitting now has an expected gain of X seconds."  
**How:** Aggregate historical race control events from Jolpica per circuit. Compute per-race SC probability as Poisson process. New tool: `get_sc_probability(round_number)` → `{per_race_probability, remaining_race_probability}`.  
**Difficulty:** Low (1–2 days)  
**Literature:** TUMFTM Monte Carlo simulator (MDPI Applied Sciences 2020).

### FEAT-09 — Wet Weather Performance Analysis (MEDIUM VALUE, MEDIUM EFFORT)
**What it is:** Per-driver analysis of how they perform in wet/mixed conditions vs. their dry baseline. Computes "positions gained vs. expected" in wet races vs. dry races. Best proxy for raw driver skill isolation (team advantage is minimised in rain).  
**Why it matters:** Bell et al. (JQAS 2016) specifically found driver effects are larger in wet conditions. "Verstappen gained on average 2.3 positions vs. grid in wet races vs. 0.8 in dry" is a factual, data-derived statement the platform can't currently make.  
**How:** Jolpica race results + weather data flag. Historical wet race identification (Rainfall field in FastF1 weather data). Compute per-driver wet vs. dry position-delta statistics.  
**Difficulty:** Medium (3 days)  
**Literature:** Bell et al. JQAS 2016.

### FEAT-10 — FP → Qualifying Prediction (MEDIUM VALUE, MEDIUM EFFORT)
**What it is:** Given practice session lap times (especially FP3 qualifying sims), predict likely qualifying grid order with confidence intervals.  
**Why it matters:** Answers "who should we expect on pole?" before qualifying, with calibrated uncertainty.  
**How:** FP3 qualifying-sim lap times (already classified in `get_fp_summary()`). Apply circuit-specific track evolution correction (FP3 → qualifying surface improvement). Hierarchical Bayesian model with driver/circuit intercepts. Return predicted order + probability intervals.  
**Difficulty:** Medium (1 week)  
**Literature:** AWS ML Blog (hierarchical Bayesian FP→qualifying model); arXiv:2507.10966 (FP3 strongest predictor, Rel Freq 0.350).

### FEAT-11 — Overtaking Analysis by Zone (MEDIUM VALUE, MEDIUM EFFORT)
**What it is:** Count overtaking events per race, attribute them to DRS zones vs. non-DRS, pit strategy vs. on-track, and compare to circuit historical average. Expose overtaking difficulty per circuit.  
**Why it matters:** "Why didn't Norris pass Leclerc?" needs a circuit-difficulty answer. Currently the system has no overtaking data at all.  
**How:** OpenF1 position data (3.7Hz) — detect overtakes by tracking position swaps with timestamp. Cross-reference with DRS zone definitions (FastF1 circuit data). Historical baseline from Jolpica race-by-race results.  
**Difficulty:** Medium (4 days)  
**Literature:** de Groote JSA 2021; de Groote JQAS 2025.

### FEAT-12 — Race Outcome Prediction (MEDIUM VALUE, HIGH EFFORT)
**What it is:** ML model (XGBoost) predicting finishing position distribution per driver, given grid positions + circuit + current season form + compound strategy.  
**Why it matters:** Answers "who will win?" with calibrated probabilities, not speculation.  
**How:** Pre-trained XGBoost on 2014–2024 Jolpica data. Features: grid position (dominant, coeff ~0.46), circuit type (street/permanent), wet/dry, team season form (rolling). Update predictions as race progresses.  
**Difficulty:** High (1–2 weeks)  
**Literature:** Aalto University thesis 2023; Preprints.org April 2025; Springer hybrid RF+GNN 2025.

### FEAT-13 — Monte Carlo Race Strategy Simulator (HIGH VALUE, HIGH EFFORT)
**What it is:** Given current race state (lap, position, tyre age, deg model), simulate remaining race laps via Monte Carlo. Enumerate top-N pit timing options, return expected finishing position per option.  
**Why it matters:** The platform can currently diagnose what happened. This lets it prescribe what should happen. "Pit now vs. stay out 3 more laps: pit now gives expected P4.2, staying gives P4.8 due to undercut risk."  
**How:** Use fitted polynomial degradation model as the pace prediction engine. Simulate tyre deg uncertainty via sampling. Include SC probability (FEAT-08). Enumerate 2–3 pit options and compare via simulation. Reference: TUMFTM/race-simulation (GitHub) — open-source, Python, 121-race validated.  
**Difficulty:** High (2–3 weeks)  
**Literature:** TUMFTM simulator (MDPI Applied Sciences 2020, GitHub); Aguad & Thraves EJOR 2024.

### FEAT-14 — State-Space Kalman Tyre Degradation (HIGH VALUE, HIGH EFFORT)
**What it is:** Replace the linear OLS degradation model entirely with a Bayesian state-space Kalman filter. State = [current_pace, degradation_rate, cliff_proximity]. Handles VSC interruptions, warm-up phase, non-stationary degradation, and produces a degradation trajectory with an uncertainty tube — not just a single slope.  
**Why it matters:** Current model gives one number (deg_rate) with one quality flag (r²). Kalman gives a time-evolving estimate with uncertainty that properly widens when laps are noisy or interrupted. This is what real teams use.  
**Difficulty:** High (1–2 weeks)  
**Literature:** arXiv:2512.00640 — uses FastF1 data, open source, directly applicable.

### FEAT-15 — Driver Form Trend (LOW-MEDIUM VALUE, LOW EFFORT)
**What it is:** Per-driver recent form analysis: last N races, compute positions gained/lost vs. grid expectation, detect trends (improving, declining, stable), flag anomalies (sudden step change suggesting car upgrade or car regression).  
**Why it matters:** Contextualises current performance. "Norris has gained an average of 2.1 positions vs. grid in the last 4 races" is useful framing for any race analysis question.  
**How:** Jolpica race results (already used). Rolling average of `finish_position - grid_position`. LOESS smoothing to detect trend vs. noise.  
**Difficulty:** Low (2 days)  
**Literature:** arXiv:2603.15192 (normal model benchmarking); arXiv:2501.00126 (competitive balance metrics).

### FEAT-16 — Bootstrap Confidence Intervals on All Analytical Outputs (MEDIUM VALUE, MEDIUM EFFORT)
**What it is:** Replace point estimates with confidence intervals on degradation rate, pace delta, GGV utilization, and bravery score. A 4-lap stint's deg rate has a much wider CI than a 20-lap stint's.  
**Why it matters:** The LLM currently has no principled way to know how much to trust a metric. A noisy r²=0.2 deg rate and a clean r²=0.85 rate are both reported as single numbers. Bootstrap CIs give the LLM a structured uncertainty signal.  
**How:** Bootstrap resample stint laps 500 times, compute slope distribution. Report 5th–95th percentile as `deg_rate_ci_low`, `deg_rate_ci_high`. Apply similarly to corner metrics (resample across corners) and pace comparisons (resample across laps).  
**Difficulty:** Medium (3–4 days, systemic change)

### FEAT-17 — Per-Session Driver Style Fingerprint (MEDIUM VALUE, LOW EFFORT)
**What it is:** Replace static driver profiles with a data-derived per-session summary: average `trail_brake_pct`, `throttle_acceptance_pct`, `entry_bravery_pct`, `avg_ggv_util_pct` across all corners of the session. Compare to previous sessions as a "style baseline."  
**Why it matters:** Captures how a driver actually drove today, not how they drove in general in 2023. Can detect style adaptations: "Norris was braking earlier than usual today — possible tyre management adaptation."  
**How:** `analyze_cornering_loads()` already computes all these per-corner. Aggregate across all corners in a lap → session fingerprint. Cache per driver per session. No new data required.  
**Difficulty:** Low (2 days — aggregation of existing computation)

### FEAT-18 — Weather-Adjusted Pace Analysis (MEDIUM VALUE, MEDIUM EFFORT)
**What it is:** Integrate FastF1 weather data (track temp, air temp, rainfall) into pace and degradation analysis. Apply temperature-based pace correction (roughly −0.03s per +1°C track temperature for heat-sensitive compounds). Flag rain sessions for separate treatment.  
**Why it matters:** A lap time on a 52°C track is not comparable to one on a 28°C track. Weather variation is a confound in all cross-session comparisons. Bell et al. (2016) found driver skill effects are larger in wet conditions — this is the most productive signal for driver isolation.  
**How:** `session.load(weather=True)` in FastF1 — already available. Merge weather per lap. Fit `Δt = β × ΔT_track` from field-wide data. Add temperature flag to LLM context.  
**Difficulty:** Medium (3–4 days)  
**Literature:** Bell et al. JQAS 2016 (wet race driver effect amplification).

### FEAT-19 — LLM Waveform Narrative (HIGH VALUE, HIGH EFFORT)
**What it is:** Instead of passing scalar summaries to the LLM (avg_ggv_util_pct = 78%), generate a spatial prose description of the G-trace shape: "Norris's lateral G ramps from 0.8G to 3.1G over the first 80m of turn 3 entry — 40m shorter than Leclerc's ramp. Norris peaks 0.4G higher at the apex, then drops 0.3G more steeply on exit." This is how race engineers read telemetry.  
**Why it matters:** Current LLM reasoning is limited to interpreting pre-computed scalars. Waveform narrative lets the LLM reason about shape, rate-of-change, and spatial patterns.  
**How:** New `_waveform_to_narrative(corner_id, driver_a_metrics, driver_b_metrics)` function generating structured spatial descriptions. Pass to LLM as part of the evidence block.  
**Difficulty:** High (2 weeks)

### FEAT-20 — Head-to-Head Driver History (LOW VALUE, LOW EFFORT)
**What it is:** When asked "who is faster — Norris or Leclerc?", pull historical head-to-head race results from Jolpica (same race, compare finishing positions) and compute win rate, adjusted for grid position.  
**Why it matters:** Grounds LLM answers to head-to-head questions in multi-year data rather than general knowledge.  
**How:** Jolpica `/results` endpoint — already partially used. Filter for races where both drivers started; compute finish position delta. Aggregate across seasons.  
**Difficulty:** Low (1–2 days)  
**Literature:** van Kesteren & Bergkamp (JQAS 2023) — head-to-head comparisons methodology.

---

## PRIORITISED EXECUTION ORDER

### Phase 1 — Now (1–2 weeks total)
Bugs and quick features. No new architecture. All changes to existing files.

| # | Item | Type | Effort |
|---|---|---|---|
| 1 | BUG-04: interpolated telemetry sampling | Bug | 0.5 days |
| 2 | BUG-05: IQR outlier filter | Bug | 0.5 days |
| 3 | BUG-02: drop cold-tyre laps from deg regression | Bug | 0.5 days |
| 4 | BUG-06: representative pace at age 10, not age 1 | Bug | 0.5 days |
| 5 | BUG-01: circuit-specific fuel correction | Bug | 1 day |
| 6 | BUG-08: remove static driver styles from LLM when telemetry present | Bug | 1 day |
| 7 | FEAT-01: cumulative lap delta trace | Feature | 2 days |
| 8 | FEAT-15: driver form trend (Jolpica, rolling avg) | Feature | 2 days |
| 9 | FEAT-08: safety car probability per circuit | Feature | 2 days |
| 10 | FEAT-20: head-to-head driver history | Feature | 2 days |

### Phase 2 — Soon (2–4 weeks)
New analytical capabilities. Some new modules.

| # | Item | Type | Effort |
|---|---|---|---|
| 11 | BUG-03: polynomial degradation + cliff detection | Bug | 3 days |
| 12 | BUG-07: compound-separated GGV envelopes | Bug | 3 days |
| 13 | FEAT-17: per-session style fingerprint | Feature | 2 days |
| 14 | FEAT-06: dirty air detection via OpenF1 intervals | Feature | 3 days |
| 15 | FEAT-05: track evolution model | Feature | 4 days |
| 16 | FEAT-16: bootstrap confidence intervals | Feature | 4 days |
| 17 | FEAT-02: car-adjusted Elo driver rating | Feature | 5 days |
| 18 | FEAT-03: RAPM driver skill estimate | Feature | 3 days |
| 19 | FEAT-09: wet weather performance analysis | Feature | 3 days |
| 20 | FEAT-11: overtaking analysis by zone | Feature | 4 days |

### Phase 3 — Later (1–3 months)
Significant new systems. New data pipelines. Highest analytical value.

| # | Item | Type | Effort |
|---|---|---|---|
| 21 | FEAT-07: polynomial + state-space tyre degradation | Feature | 2 weeks |
| 22 | FEAT-10: FP → qualifying prediction | Feature | 1 week |
| 23 | FEAT-18: weather-adjusted pace analysis | Feature | 1 week |
| 24 | FEAT-12: race outcome prediction (XGBoost) | Feature | 2 weeks |
| 25 | FEAT-04: Bayesian driver/car decomposition | Feature | 3 weeks |
| 26 | FEAT-13: Monte Carlo race strategy simulator | Feature | 3 weeks |
| 27 | FEAT-14: state-space Kalman tyre degradation | Feature | 2 weeks |
| 28 | FEAT-19: LLM waveform narrative | Feature | 2 weeks |

---

*10 bugs total (7 confirmed from code review + 3 lower severity). 20 new features. Phase 1 can begin immediately — all in existing files, no new dependencies.*
