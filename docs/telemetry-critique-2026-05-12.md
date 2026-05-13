# F1Dash Telemetry Intelligence: Brutal Technical Critique & Upgrade Roadmap

**Date:** 2026-05-12  
**Scope:** Full review of `f1_data.py`, `chat.py`, `driver_styles.py` against motorsport literature and industry practice.  
**Verdict:** The system is more sophisticated than most open-source F1 tools, but has specific algorithmic weaknesses that would make a race engineer wince. It is currently at "impressive demo" level. Getting to "professional analyst" level requires targeted fixes in 4 areas.

---

## 1. Overall Assessment

### What the system does well
- **GGV envelope is real physics.** Computing lateral G from curvature (κ = |x'y'' − y'x''| / denom^1.5, `f1_data.py:5010–5100`) with Savgol smoothing on GPS positions before differentiation is the correct approach. Most open-source tools skip this entirely and use raw speed comparisons.
- **Empirical 95th-percentile ceiling** (`_build_ggv_envelope`, line 5114) is substantially better than a universal constant. It adapts to the circuit and conditions.
- **Safety car filtering via TrackStatus** (codes 4/5/6, `_filter_clean_race_laps`) is correct. Most amateur analyses miss this entirely.
- **Compound-matched degradation alignment** (`_align_stints_by_compound`) correctly refuses to average deg rates across different compounds.
- **Fuel-correction direction is right** — adding back 0.04s per lap to later laps so the slope represents tyre loss, not fuel savings. Conceptually sound.
- **LLM prompt engineering** in `chat.py` actively prevents the model from saying metric names aloud ("Never say avg_ggv_util_pct") and forces character-language translation. This is the correct abstraction boundary.
- **Clipping/lift-and-coast inference** from speed/throttle patterns is a genuine attempt at ERS proxy analysis — not seen in other open-source tools.

### What would make a race engineer raise an eyebrow
Seven specific issues below. They are listed in order of analytical damage — how much wrong conclusions they produce.

---

## 2. Critical Weaknesses

### 2.1 Fuel Correction: Universal 0.04 s/lap (HIGH SEVERITY)

**The code:**
```python
def _fit_stint_degradation(clean_laps, fuel_correction_s_per_lap: float = 0.04):
    fuel_corrected = [
        t + fuel_correction_s_per_lap * (n - min_lap)
        for t, n in zip(raw_times, lap_nums)
    ]
```

**What's wrong:**  
0.04 s/lap is the right order of magnitude for medium-length circuits but is wrong for outliers. The fuel effect depends on circuit layout:

| Circuit | Estimated fuel effect |
|---|---|
| Monaco (3.337 km, heavy braking) | ~0.07–0.09 s/lap |
| Monza (5.793 km, mostly straight) | ~0.02–0.03 s/lap |
| Silverstone (5.891 km, medium) | ~0.04–0.05 s/lap |
| Singapore (4.940 km, slow) | ~0.06–0.08 s/lap |

Modern F1 cars start with ~110 kg of fuel and burn ~1.5–2 kg/lap. The lap time benefit of 10 kg lighter is roughly 0.3–0.35 s/lap (varies by circuit). At 1.7 kg/lap burn: ~0.05 s/lap at heavy circuits, ~0.025 at Monza.

**Consequence:** At Monaco the model **under-corrects** by ~0.04 s/lap, causing the regression to see apparent tyre improvement that is actually fuel burn. A 20-lap stint at Monaco produces a 0.8 s **fabricated** tyre improvement signal. At Monza, the model **over-corrects**, inflating the apparent degradation rate.

**Fix:**  
A circuit-specific correction table keyed on `session.event['EventName']` or circuit length. Use `session.event['CircuitLength']` (available from FastF1) to interpolate: `correction = 0.025 + 0.012 * (circuit_km - 3.3)` is a reasonable empirical proxy, or use a lookup table for the 24 circuits.

**Literature reference:** The "how_to_read_degradation" comment in the code acknowledges this issue but doesn't fix it. Todd et al. (ACM SAC 2025, arXiv:2501.04067) use Mercedes's actual per-lap fuel model as the upstream quantity — the correct approach when fuel data exists.

---

### 2.2 Linear Degradation: Physically Wrong Model (HIGH SEVERITY)

**The code:**
```python
slope, intercept, r_sq = _linear_regression(tyre_ages, fuel_corrected)
positive_deg = max(0.0, slope)
```

**What's wrong:**  
Real tyre degradation is **not linear**. It has three phases:
1. **Bedding-in** (laps 1–3): Temperature builds, grip often *improves*. A slope fitted through this phase will be flattened by laps 1–2 showing lower times than steady state.
2. **Stable phase** (laps 4–X): Near-linear degradation. This is what we want to measure.
3. **Cliff** (laps X+N): Sudden compound-specific degradation. A linear model cannot represent this at all.

`positive_deg = max(0.0, slope)` is particularly damaging. When a driver runs through bedding-in and into stable phase, the averaged slope may be near zero or negative (laps 1–3 improve faster than laps 4–N degrade), so `positive_deg` becomes 0.0. The system concludes the driver had **zero tyre degradation** when they actually had a normal degradation profile that was masked by the thermal build-up phase.

**Consequence for the LLM:** When the model sees `deg_rate = 0.000 s/lap, r_squared = 0.01` it will correctly flag low confidence, but may still assert "minimal degradation" when the reality is "noisy short stint."

**Fix:**
1. **Drop the first 2 laps of every stint** from the regression. These are cold-tyre laps and contaminate the fit.
2. **Use polynomial fit (degree 2)** as a minimum: `t = a + b*age + c*age²`. The quadratic term captures the acceleration of degradation in long stints.
3. **State-space model** (arXiv:2512.00640, "A State-Space Approach to Modeling Tire Degradation"): treat degradation as a latent Kalman process inferred from lap times. This propagates uncertainty correctly, handles the cliff, and gives probabilistic degradation estimates. Implementation difficulty: ~2 days. Impact: very high — changes the fundamental quality of every deg comparison.
4. **At minimum**: report `pace_at_age_3` (not age_1) as the representative pace, skipping the cold-tyre bias.

---

### 2.3 GGV Envelope: Compound-Blind, Session-Blind (MEDIUM-HIGH SEVERITY)

**The code:**
```python
def _build_ggv_envelope(telemetry_frames: list) -> dict:
    # 95th percentile across ALL frames passed in
    lat_max[i] = max(float(np.percentile(np.abs(lat_bin), 95)), 0.5)
```

**What's wrong:**  
The envelope is built from whatever laps are passed in. If those laps include mixed compounds and tyre ages, the 95th-percentile ceiling conflates:
- New Soft on a rubbered track (highest grip)
- 30-lap Hard on cold track (lowest grip)

A driver running new Softs is being judged against an envelope that includes their own performance on those Softs. Their `avg_ggv_util_pct` will be ~95% by definition — the ceiling is set by their best output.

A driver running 20-lap Hards is being judged against the same ceiling, so they appear to be "not using the car's grip ceiling" when in reality the ceiling was set by a different compound in a different thermal state.

**Consequence:** Cross-compound `ggv_util_pct` comparisons are statistically meaningless. Qualifying comparisons (where both drivers run the same fresh compound) are much more valid, but the code doesn't enforce this distinction.

**Fix:**
1. Build per-compound envelopes: `envelope_SOFT`, `envelope_MEDIUM`, `envelope_HARD`.
2. Only compare drivers against the envelope for their specific compound at similar tyre age.
3. Report `envelope_source_compound` in the output so the LLM knows what it's comparing against.
4. In qualifying (where compound is always the same), the current approach is nearly correct — just flag this.

**Theoretical model fallback:**
```python
def _theoretical_max_g(speed_kph):
    return 2.0 + speed_kph * 0.012
```
This is a physically reasonable linear approximation but has a problem: at 0 kph, it returns 2.0 G, implying 2G of cornering force at zero speed, which is nonsensical (no aero downforce at standstill). The mechanical grip floor (~1.2–1.4 G) is correct but the intercept is not interpretable as a physical quantity. At 300 kph it gives 5.6 G, which is plausible for a 2025 F1 car at full downforce. The formula is usable but should not be presented as a physics model — it's a heuristic.

---

### 2.4 Telemetry Sampling: Nearest-Neighbor Without Interpolation (MEDIUM SEVERITY)

**The code:**
```python
INTERVAL_M = 100
while dist <= total_dist:
    idx = (tel['Distance'] - dist).abs().idxmin()
    row = tel.loc[idx]
```

**What's wrong:**  
FastF1 telemetry is time-sampled at ~3.7 Hz. At 300 kph, the car covers 83 m per second. Between 100m marks, there are typically 2–4 data points. The nearest-neighbor lookup picks the sample closest to the mark, which may be ±15–20 m away from the nominal position.

When comparing two drivers at "800m" — one driver's actual measurement may be at 793m and the other's at 808m. At a braking zone boundary, a 15m difference equals ~50 ms of braking time, which is a meaningful number in F1 analysis. The system will report a speed difference that is partly measurement noise.

**For the GGV computation**, the lateral G is computed on the raw FastF1 telemetry grid (not resampled), so this is less of an issue there. But for `get_lap_telemetry()` which drives the speed trace widget, the 100m nearest-neighbor is used and it will create jagged comparisons near braking/throttle transitions.

**Fix:** Replace nearest-neighbor with linear interpolation:
```python
speed_interp = np.interp(dist_targets, tel['Distance'].values, tel['Speed'].values)
throttle_interp = np.interp(dist_targets, tel['Distance'].values, tel['Throttle'].values)
```
This is a 5-line change that eliminates the sampling artifact entirely. Impact: medium — visually cleaner speed traces and more honest braking point comparisons.

---

### 2.5 Outlier Lap Filter: Median + 5.0s is Too Permissive (MEDIUM SEVERITY)

**The code:**
```python
sorted_times = sorted(r['lap_time_s'] for r in result)
median_time = sorted_times[mid]
result = [r for r in result if r['lap_time_s'] <= median_time + 5.0]
```

**What's wrong:**  
The filter keeps any lap within 5 seconds of the median. For most circuits this is reasonable (median race lap ~90s, so anything up to 95s is kept). But:

1. **Virtual Safety Car laps** that don't trigger TrackStatus 4/5/6 (they sometimes appear as status '2' which is Yellow Flag) will pass through. A VSC lap can be 10–15 seconds slower than racing pace, well within the 5s cut on some circuits.
2. **Out-laps on old tyres** after a pit stop where the pit stop itself is filtered but the first "racing" lap on cold tyres is kept. This first lap is often 2–3s slower than the stint average and contaminates the slope estimate.
3. **5.0s is circuit-agnostic.** On Monaco (lap ~78s), 5s is 6.4% above median — acceptable. On Monza (lap ~82s), 5s is 6.1%. But on some street circuits with unpredictable pace variance, this may include laps that were behind a slow car (track position battles).

**Fix:**
1. Filter using **IQR**: keep laps within Q1 - 1.5×IQR and Q3 + 1.5×IQR.
2. Separately, strip the first lap of each stint (cold tyre) from the degradation regression input while keeping it for race pace comparison.
3. Check for Yellow Flag status '2' (not just '4'/'5'/'6') and consider adding a configurable buffer.

---

### 2.6 Driver Style Profiles: Static, Hardcoded, Not Data-Derived (MEDIUM SEVERITY)

**The code (`driver_styles.py`):**
```python
# Curated driving style profiles for current F1 drivers.
# Sources: technical analyses, published telemetry comparisons, team/driver interviews.
```

**What's wrong:**  
These are hand-authored profiles, not computed from telemetry. The LLM is instructed to use these codes to frame technique explanations. This creates a **confirmation bias pipeline**: no matter what the telemetry shows, the LLM will frame it in terms of the pre-assigned style profile.

Real example of the problem: If Norris is labeled "late_aggressive" braker and in a specific race he brakes early to preserve tyres, the LLM will still frame any telemetry difference as "Norris' commitment character" rather than "Norris adapted his style." The telemetry data itself, available in the session, tells you the actual braking point — the static profile should be entirely replaced by computed metrics.

The system already **computes** trail_brake_pct, entry_bravery_pct, and throttle_acceptance_pct per corner. These are data-derived per-session metrics. The static driver_styles.py adds noise rather than signal.

**Fix:**
1. Remove driver_styles.py from the LLM reasoning context for any question where session telemetry is available.
2. Use the computed per-session cornering metrics as the primary style signal.
3. The static profiles can remain as **historical baseline context** ("historically Norris tends to brake late") but should be explicitly labeled as background knowledge that the telemetry may contradict.
4. Add a per-session "style fingerprint" derived from the actual cornering data: `{trail_brake_pct, throttle_acceptance_pct, entry_bravery_pct}` averaged across all corners.

**Literature reference:** Bell et al. (JQAS 2016) and van Kesteren & Bergkamp (JQAS 2023) demonstrate that driver "style" in statistical models should be inferred from outcomes, not assigned a priori. Static style labels are the opposite of what those papers recommend.

---

### 2.7 Race Pace Battle: No Tyre-Age Normalization in Comparison (MEDIUM SEVERITY)

**The code:**
```python
def _weighted_pace(stints):
    total = sum(s['lap_count'] for s in stints)
    return sum(s['fuel_corrected_pace_at_age_1_s'] * s['lap_count'] for s in stints) / total
```

**What's wrong:**  
`fuel_corrected_pace_at_age_1_s` is the intercept of the regression — the extrapolated pace at tyre age 1. This is used as the representative pace for each stint.

Two problems:
1. **Age-1 is cold-tyre territory**. The intercept extrapolated from ages 5–25 back to age 1 will be biased low (since the model is linear and cold-tyre laps at age 1–3 are slower). You're extrapolating outside the training range.
2. **This compares "pace at tyre age 1" across different strategies**. If Driver A pits on lap 15 (tyres are age 16 to 47) and Driver B pits on lap 30 (tyres are age 1 to 30), their `pace_at_age_1` intercepts are not comparable because they're from different parts of the tyre life curve.

The more robust comparison is: **at the same tyre age**, what was each driver's predicted pace? Compare at age 10 (mid-stint stability), not at age 1.

**Fix:**
```python
REFERENCE_TYRE_AGE = 10  # compare at mid-stint stability
pace_at_ref = round(slope * REFERENCE_TYRE_AGE + intercept, 3)
```
And use this as the weighted pace for cross-driver comparison.

---

## 3. Missing Capabilities (Not Bugs — Genuine Gaps)

### 3.1 No Track Evolution Modeling
Track rubber buildup across a session improves lap times by 0.5–1.5s from session start to end (qualifying especially). Any comparison of laps from early vs. late in a session is confounded by this. There's no correction for session progression time. Impact on qualifying battle analysis is material.

### 3.2 No Aerodynamic Wake / Dirty Air Detection
When two cars are close on track, the following car runs in dirty air and loses 0.3–0.5 s/lap. The race pace battle analysis does not check whether the drivers were running in proximity. A "wheel-to-wheel" comparison where one driver was following is meaningless without a dirty air correction.

**Partial fix available:** OpenF1 intervals endpoint provides gap data at 3.7 Hz. Laps where `gap_to_leader_s < 1.0` for the following driver should be flagged or excluded from clean pace analysis.

### 3.3 No Tyre Thermal State
The first 2–3 laps of any stint have cold tyres. These laps appear as "slow" but are not evidence of degradation — they're thermal build-up. Laps where `tyre_age <= 3` should be excluded from degradation regression but included in full stint context.

### 3.4 No Weather Adjustment
Track temperature significantly affects lap times. A 10°C track temperature rise is worth ~0.3 s/lap (lower grip from rubber overheating). The weather data is available from FastF1 (`session.load(weather=True)`) but is not used in the pace or degradation models.

### 3.5 No Driver Skill / Car Decomposition
The system cannot answer "how good is this driver independent of the car?" Questions like "how would Norris perform at McLaren 2022 levels?" are currently handled with static knowledge. The literature has two approaches:
- **Bayesian multilevel model** (van Kesteren & Bergkamp, JQAS 2023): simultaneously estimates driver and constructor effects. Requires multi-season cross-team data.
- **RAPM (Regularized Adjusted Plus Minus)**: from basketball analytics, applied to F1 by arXiv:2508.00200. More tractable computationally.

Both require historical cross-constructor data (Jolpica API provides this) and a multi-week computation pass. This is not feasible as a real-time tool function but could be a pre-computed lookup updated weekly.

### 3.6 No Confidence Intervals on Any Output
The system reports `r_squared` for degradation but doesn't propagate uncertainty. A stint with 4 laps and r²=0.3 is reported with the same confidence as a stint with 25 laps and r²=0.85. The LLM is told to use r² as a trust signal but has no structured uncertainty to reason over.

---

## 4. What the LLM Reasoning Does Well and Poorly

### Strengths
- **Abstraction layer is correct.** The LLM never sees raw metrics — it sees translated character descriptions from `chat.py`'s prompt sections. This is the right architecture.
- **Tool dispatch logic is sound.** The composite-before-primitive tool hierarchy prevents the LLM from jumping to low-level telemetry before establishing context.
- **FP interpretation guidance** (fuel load caveat, long_run vs quali_sim classification) correctly frames what practice lap times can and cannot tell you.

### Weaknesses
- **The LLM reasons over summary statistics, not waveforms.** It sees `avg_ggv_util_pct = 78%` and synthesizes prose about it. A race engineer sees the G-G diagram and interprets the *shape* — where in the corner the driver underperforms, whether it's entry vs. exit. The current architecture loses this spatial information entirely.
- **Static driver profiles contaminate data-driven reasoning.** If telemetry shows Verstappen braking 30m earlier than his profile suggests, the LLM doesn't flag the anomaly — it works within the static framing.
- **No causal reasoning between telemetry signals.** The LLM is given: deg_rate, corner metrics, braking points. It cannot reason about causality: "high ggv_util_pct with high deg_rate suggests the driver is overdriving the tyre, which causes the degradation." This requires explicit causal relationships to be exposed in the prompt.
- **No multi-race context.** Each question is answered against one session. A race engineer would ask "is this degradation typical for this driver on this compound, or anomalous?" — which requires historical comparison.

---

## 5. Comparison Against Literature

| Technique | Literature Standard | Current Implementation | Gap |
|---|---|---|---|
| Tyre deg model | State-space/Bayesian (arXiv:2512.00640) | Linear OLS + hardcoded fuel correction | Large |
| Driver skill isolation | Bayesian multilevel (JQAS 2023) | None — static profiles only | Very large |
| GGV analysis | Proper friction ellipse with compound separation | 7-bin empirical envelope, compound-blind | Medium |
| Lap time prediction | LSTM/sequence models (Tilburg thesis 2023) | No predictive model | Not applicable |
| Degradation patterns | Polynomial + thermal warm-up model | Linear, includes cold laps | Medium |
| Outlier filtering | IQR-based + stint-relative | Median + 5s flat threshold | Medium |
| Track evolution | Rubber model with session time index | Not modeled | Large |
| Dirty air correction | Gap-based pace penalty (inferred from intervals) | Not modeled | Large |
| Confidence intervals | Bootstrapped CI on all metrics | r² only | Large |
| Driver style | Data-derived per-session fingerprint | Static hardcoded profiles | Large |

---

## 6. Roadmap

### Level 1: "Good" (1–2 weeks, current codebase)
These are targeted fixes to existing functions. No new architecture.

1. **Replace 0.04 s/lap fuel correction with circuit-specific table** (`_fit_stint_degradation`)
   - Add `circuit_km` parameter from `session.event['CircuitLength']`
   - Interpolate correction from a 24-circuit lookup table
   - *Why it matters:* Eliminates fabricated degradation signals at Monaco/Singapore. *Difficulty: Low.*

2. **Drop first 2 laps of each stint from deg regression** (`_fit_stint_degradation`)
   - Filter `tyre_age <= 2` before regression
   - *Why it matters:* Cold-tyre bias inflates the apparent degradation baseline. *Difficulty: Trivial.*

3. **Replace nearest-neighbor sampling with interpolation** (`get_lap_telemetry`)
   - Use `np.interp()` for all channels to exact 100m marks
   - *Why it matters:* Cleaner speed traces, honest braking point comparisons. *Difficulty: Low.*

4. **Add IQR-based outlier filter** (`_filter_clean_race_laps`)
   - Keep only laps within Q1 − 1.5×IQR and Q3 + 1.5×IQR
   - *Why it matters:* Removes VSC laps that TrackStatus misses, removes formation laps that sneak through. *Difficulty: Low.*

5. **Use pace at tyre age 10 as representative, not age 1** (`_fit_stint_degradation`)
   - Report `pace_at_age_10_s` alongside existing `pace_at_age_1_s`
   - *Why it matters:* More stable estimate, avoids extrapolation outside training range. *Difficulty: Trivial.*

6. **Add `envelope_compound` to GGV output** (`_build_ggv_envelope`)
   - Tag which compound/session produced the envelope
   - Warn in LLM prompt when comparing across compounds
   - *Why it matters:* Prevents misleading cross-compound utilization comparisons. *Difficulty: Low.*

7. **Remove static driver styles from LLM reasoning when session telemetry is present**
   - In `chat.py` system prompt: make `driver_styles.py` context conditional
   - *Why it matters:* Eliminates confirmation bias in cornering analysis. *Difficulty: Low.*

---

### Level 2: "Very Strong" (2–4 weeks, moderate new code)

8. **Polynomial + thermal degradation model** (`_fit_stint_degradation`)
   - Fit `t = a + b*age + c*age²` using `numpy.polyfit(tyre_ages, fuel_corrected, 2)`
   - Report "cliff lap estimate": where the second derivative exceeds a threshold
   - Detect warm-up phase and stable phase separately
   - *Why it matters:* Captures the nonlinear reality of tyre wear. *Literature:* arXiv:2512.00640. *Difficulty: Medium.*

9. **Dirty air detection via OpenF1 intervals** (new `_flag_dirty_air_laps()`)
   - Fetch interval data for both drivers from OpenF1
   - Flag any lap where gap < 1.0s for the following driver
   - Exclude flagged laps from clean pace analysis, report count
   - *Why it matters:* A driver trailing by 0.5s loses ~0.3 s/lap to wake. Race pace comparisons are meaningless without this. *Difficulty: Medium.*

10. **Per-session driver style fingerprint** (new `_compute_style_fingerprint()`)
    - Average `trail_brake_pct`, `throttle_acceptance_pct`, `entry_bravery_pct` across all corners
    - Compare against historical session averages per driver (stored in cache)
    - Expose to LLM as "this session's technique" vs "historical baseline"
    - *Why it matters:* Replaces static profiles with data-derived, session-specific evidence. *Difficulty: Medium.*

11. **Bootstrap confidence intervals on degradation** (`_fit_stint_degradation`)
    - Bootstrap resample the stint laps 200 times, report 5th–95th percentile slope
    - Expose as `deg_rate_ci_low`, `deg_rate_ci_high` alongside `deg_rate_s_per_lap`
    - Update LLM prompt to use CI width as confidence signal
    - *Why it matters:* A 4-lap stint with wide CI is not the same as a 20-lap stint. *Difficulty: Medium.*

12. **Track evolution correction** (new `_track_evolution_correction()`)
    - Model lap time improvement within a session as `Δt = −α × (t − t_start)` where t is session time
    - Fit α from the lap time trend of the cleanest driver's data
    - Subtract from all laps before fitting degradation
    - *Why it matters:* Within-session pace improvement from rubber is 0.5–1.5s — larger than most degradation rates. *Difficulty: Medium-High.*

13. **Compound-separated GGV envelopes** (`_build_ggv_envelope`)
    - Accept compound label per telemetry frame
    - Return `{SOFT: envelope, MEDIUM: envelope, HARD: envelope}`
    - *Why it matters:* Compound-blind comparison is the single biggest validity issue in the GGV analysis. *Difficulty: Medium.*

---

### Level 3: "State of the Art" (1–2 months, significant new modules)

14. **Bayesian driver/car decomposition** (new `analyze_driver_skill_rating()`)
    - Multi-season Jolpica data: for each season, compute Bayesian hierarchical model
    - Simultaneously estimate driver effect + constructor effect per race
    - Returns: "this driver is X seconds faster than a median driver, car-adjusted"
    - *Literature:* van Kesteren & Bergkamp (JQAS 2023), arXiv:2203.08489. Full methodology and replication code at Zenodo.
    - *Implementation:* PyMC or Stan; requires ~1 season of race data; offline computation updated weekly.
    - *Why it matters:* The #1 question users ask — "how good is this driver really?" — cannot be answered without car/driver decomposition. *Difficulty: Very High.*

15. **State-space tyre degradation** (new `_fit_degradation_kalman()`)
    - Kalman filter with state = [current_pace, degradation_rate, cliff_threshold]
    - Observation = lap time (noisy)
    - Handles non-stationary degradation, VSC interruptions, warm-up
    - Returns: degradation trajectory with uncertainty tube
    - *Literature:* arXiv:2512.00640 — uses FastF1 data, fully open source. *Difficulty: High.*

16. **LLM waveform reasoning** (new telemetry embedding approach)
    - Instead of passing scalar summaries, encode the speed/G waveforms as structured descriptions
    - "At 800m the lateral G profile for Norris rises 0.4G/100m faster than Leclerc over the next 200m, then Norris reaches peak G 180m before the apex — classic V-line commitment"
    - Requires a `_waveform_to_narrative()` function that generates spatial descriptions from the raw arrays
    - *Why it matters:* A race engineer reads the waveform shape. The LLM should too. *Difficulty: High.*

17. **Multi-race historical context engine** (new `analyze_driver_circuit_history()`)
    - Cache per-driver per-circuit degradation rates from previous seasons
    - Compare current stint performance against historical baseline: "Norris typically degrades at 0.06 s/lap at this circuit; today's 0.12 is anomalous"
    - *Why it matters:* Race engineers always contextualise against history. *Difficulty: High (data pipeline).*

18. **Race simulation with strategy optimization** (new `simulate_race_strategy()`)
    - Use fitted degradation model + pace model to simulate remaining race
    - Enumerate pit stop timing options, return expected finishing position delta
    - *Literature:* TUMFTM simulator (GitHub), Todd et al. (ACM SAC 2025). *Difficulty: Very High.*

---

## 7. Architecture Recommendations

### What to keep
- **Widget/tool architecture** — correct separation of concerns
- **Tool tier system** (composite before primitive) — good LLM guidance
- **Empirical GGV envelope** — better than any open-source alternative
- **FastF1 disk caching** — essential for any real-time use

### What to restructure

**Decouple `_fit_stint_degradation` from the hardcoded fuel correction.** Pass circuit metadata as a parameter so the correction is context-aware.

**Add a `TelemetrySignals` dataclass** as the canonical output of all telemetry processing functions. Currently each function returns different dict structures. A shared type would allow the LLM prompt to have a consistent vocabulary.

**Pre-compute per-session style fingerprints** as a cached artifact alongside session load. Don't recompute cornering metrics inside every tool call. The `analyze_cornering_loads` function is expensive — its output should be cached per session/driver pair.

**Separate the "evidence" layer from the "widget" layer** in `chat.py`. Currently `_make_*_widget` functions and the evidence-to-prose logic are intertwined. The evidence (structured telemetry facts) should be independently testable without involving LLM reasoning.

---

## 8. Answering the Core Diagnostic Questions

| Question | Current quality | Gap |
|---|---|---|
| "Why was Norris faster than Leclerc?" | Good — GGV + corner metrics give real evidence | Would improve with waveform narrative |
| "Where did Verstappen gain time?" | Good — sector decomposition + corner alignment | Needs interpolation fix for accuracy |
| "Who had better tyre management?" | Medium — deg rate exists but linear model is wrong | Polynomial deg + cold-tyre exclusion needed |
| "How good was this lap actually?" | Medium — GGV util pct is a real metric | Compound-blind ceiling is a validity problem |
| "How strong is this driver independent of the car?" | Poor — no decomposition, only static profiles | Needs Bayesian multi-season model |
| "How will this team perform next race?" | Poor — no predictive model, no historical pipeline | Out of scope for real-time tool |

---

**Overall:** For qualifying telemetry analysis, the system is already at a "senior analyst who knows their stuff" level. For race degradation analysis, it's at a "student who has the right ideas but wrong formulas" level. Fix issues 1–7 (Level 1) and you go from "impressive demo" to "analytically defensible." Fix 8–13 (Level 2) and you get to "a race engineer would use this as a cross-check." Level 3 is published-paper territory.

---

*Assumptions: All line number references are approximate (codebase is ~5500 lines). Fuel correction estimates are based on publicly available F1 engineering literature, not team data. Track evolution correction magnitude is from practitioner sources. Dirty air penalty range from de Groote (JSA 2021) for 2011–2018 era; modern ground-effect cars may differ significantly.*
