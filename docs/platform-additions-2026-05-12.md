# F1Dash: What Can Be Added — Feature Roadmap from Literature

**Date:** 2026-05-12  
**Companion to:** `docs/telemetry-critique-2026-05-12.md` (fixing what exists)  
**This doc:** New capabilities the platform doesn't have at all, grounded in specific papers and data sources.

The literature review found ~82 sources. Here is what they actually teach us to build.

---

## 1. Driver Skill Rating — Independent of Car

### What exists in literature
Three methodologically distinct approaches, each with different strengths:

#### 1a. Bayesian Multilevel Rank-Ordered Logit (Best Paper)
**Source:** van Kesteren & Bergkamp, *JQAS* 2023, arXiv:2203.08489. Full replication code at Zenodo.

**What it does:**  
Fits a Bayesian hierarchical model where each race result is a rank-ordered outcome. The model simultaneously estimates:
- `θ_driver`: latent driver skill (random effect per driver)  
- `θ_constructor_year`: constructor-year effect (captures car upgrade pace)  

Key result: **~88% of race result variance is explained by constructor**. Hamilton and Verstappen rank highest driver-adjusted.

**How to implement for F1Dash:**
1. Pull multi-season race results from Jolpica API (available from 2014 onward, compatible format)
2. Fit per season and compute driver posterior distributions
3. Pre-compute seasonally and cache — not a real-time call
4. Expose as `get_driver_skill_rating(driver_code)` → `{skill_estimate, constructor_adj_ranking, ci_low, ci_high, era}`

**What the LLM gains:**  
Can answer "how good is Norris independent of the McLaren?" with actual numbers. Currently this is answered with static knowledge from `driver_styles.py`.

**Implementation difficulty:** High (requires PyMC or Stan, multi-season data pipeline)  
**Data source:** Jolpica API — already used in `f1_data.py`

---

#### 1b. Elo-Based Driver Rating (Simpler, Real-Time Updatable)
**Sources:**  
- Matus (Santa Clara Univ.): round-robin Elo with Qualifying/Race/Global split  
- Holý & Černý, arXiv:2604.09143: Score-Driven (GAS) Elo — updates faster after upsets  
- SIAM preprint: Elo modified to separate car-year effect from driver rating

**What it does:**  
Treats each race as a series of pairwise matchups (driver A beats driver B → A gains Elo, B loses). Produces a continuously updated rating after every race.

The **GAS (score-driven) variant** is superior to classic Elo because it adapts the update step size based on the information content of each result — a surprise P1 from a midfield driver updates more than a routine P1 from the championship leader.

**How to implement:**
```python
# After each race: for each pair (i, j) where i finishes ahead of j
# Update: θ_i += K * (1 - P(i beats j)), θ_j -= K * (1 - P(i beats j))
# P(i beats j) = sigmoid(θ_i - θ_j)
# GAS variant: K is proportional to outcome surprise
```

Expose as `get_driver_elo_history(driver_code)` → time series of ratings by race  
Add `get_head_to_head_elo(driver_a, driver_b)` → probability A beats B on pure driver skill

**Implementation difficulty:** Medium (pure Python, Jolpica data)  
**Can be computed on the fly** for current season; pre-computed for history

---

#### 1c. RAPM — Regularized Adjusted Plus Minus (Basketball-Derived)
**Source:** arXiv:2508.00200, 2025

**What it does:**  
Adapts the basketball RAPM framework to F1. Uses ridge regression with time decay across the hybrid era (2014–2024). Finds constructors explain 64% of variance (lower than the Bayesian model — different methodology, complementary).

Advantage over Bayesian approach: **faster to compute**, no MCMC sampling, interpretable as a "points added over a median driver in a median car."

---

### Recommended implementation path
1. **Start with Elo** (2 days): simplest, updatable weekly, answers "who is stronger historically?"
2. **Add car-adjusted Elo** (3 days): include constructor-year term per SIAM paper
3. **Add RAPM** (1 week): ridge regression on Jolpica data, provides career-length stability ratings
4. **Bayesian multilevel** (3+ weeks): reserve for when you want publishable-quality estimates

**New tool to add:** `get_driver_skill_rating(driver_code, method="elo"|"rapm"|"bayesian")` → structured dict with skill estimate, historical trend, car-adjusted ranking, head-to-head probabilities.

---

## 2. Qualifying Prediction from Practice Data

### What literature says
**Source:** AWS ML Blog — "Predicting Qualification Ranking Based on Practice Session Performance"

Hierarchical Bayesian model with varying intercepts per driver and circuit predicts qualifying rank from FP data. **Produces uncertainty intervals**, not point estimates.

**Source:** arXiv:2507.10966 — "Evaluating the Predictive Power of Qualifying Performance in Formula One Grand Prix"  
FP3 has the strongest correlation to final qualifying result (Rel Freq = 0.350). FP1 and FP2 are much weaker predictors.

### What to build
A `predict_qualifying_order(round_number)` tool that:
1. Pulls FP3 qualifying-sim lap times (already classified in `get_fp_summary`)
2. Applies circuit-specific correction factors for track evolution between FP3 and qualifying
3. Returns predicted grid order with confidence intervals
4. Flags drivers who ran no qualifying sim in FP3 (can't predict them reliably)

**LLM benefit:** Can answer "who should we expect to be on pole?" before qualifying with actual probabilistic reasoning, not just "Verstappen is usually fast."

**Implementation difficulty:** Medium  
**Data:** FastF1 FP session data — already in `f1_data.py`

---

## 3. Race Outcome Prediction

### What literature says
Consistent finding across 6+ papers: **starting grid position is the single strongest feature** (coefficient ~0.46 in some models). XGBoost and Random Forest outperform classical regression. Key features beyond grid: wet/dry conditions, circuit type, tyre strategy, historical head-to-head on this circuit.

**Sources:**  
- Aalto University thesis (2023): XGBoost best, grid position dominant  
- Preprints.org (April 2025): SVM/RF/ANN comparison  
- Springer hybrid RF+GNN (2025): relational driver interaction modeling

### What to build
A `predict_race_outcome(round_number)` tool:
1. Input: qualifying grid positions, historical pace at this circuit, current season form
2. Model: pre-trained XGBoost on 2014–2024 results (Jolpica + FastF1)
3. Output: probability distribution over finishing positions per driver
4. Real-time update: as race progresses, condition on current lap/position

**More tractable near-term version:**  
A "relative pace predictor" that answers "given qualifying, who is likely to gain/lose positions?" using circuit-specific overtaking statistics and strategy likelihood.

**Implementation difficulty:** Medium (pre-trained model, FastF1/Jolpica data)

---

## 4. Pit Stop Strategy Analysis & Optimization

### What literature says
This is the most active research area. Three approaches in the literature:

#### 4a. Probabilistic pit window prediction
**Source:** Frontiers in AI 2025 — Bi-LSTM achieves precision 0.77, recall 0.86 on FastF1 2020–2024 data. Open-access, fully replicable.  
**Source:** "From Data to Podium" thesis (2024) — probabilistic per-lap pit probability

These models predict "on which lap is a driver most likely to pit?" — useful for anticipating strategy before it happens.

#### 4b. Strategy optimization
**Source:** TUMFTM simulator (GitHub, ~500 stars) — 121 races from 2014–2019, full Python, open source  
**Source:** Aguad & Thraves, *European Journal of Operational Research* 2024 — Stackelberg game theory for optimal pit timing under competition

The key insight from the EJOR paper: **optimal pit stop timing is a function of the opponent's strategy**, not just your own tyre state. Pitting "when tyres are worn" ignores the strategic interaction.

#### 4c. Monte Carlo strategy simulation
**Source:** MDPI Applied Sciences 2020 (TUMFTM) — formalizes probabilistic modelling of SC phases, tyre failures, pit stop variance  
**Source:** "Simulating 20,000 F1 Races" (García, Medium) — accessible implementation using FastF1

### What to build
Two tiers:

**Tier 1 — Descriptive** (`analyze_pit_strategy_effectiveness`):  
Already partially exists. Add:
- Undercut window calculation: "could A have undercut B by pitting N laps earlier?"
- Pit stop duration vs. field average
- Net position delta from stop

**Tier 2 — Predictive** (`simulate_remaining_race_strategy`):  
1. Uses fitted degradation model from current stint
2. Monte Carlo simulation of remaining laps with tyre deg uncertainty
3. Enumerates top-3 pit timing options, returns expected finishing positions
4. This is the `FormulaGPT` / TUMFTM approach — doable in Python

**Implementation difficulty:** Tier 1 = Low. Tier 2 = High (requires race simulation engine)  
**Starting point:** Fork or adapt TUMFTM simulator (GitHub: TUMFTM/race-simulation)

---

## 5. Track Evolution & Rubber Modeling

### What literature says
Not directly addressed in academic papers but consistently mentioned as a confounder. Within a session, track "rubbers in" as cars lay down grip. The effect:
- FP1: 1.0–1.5s slower than final qualifying
- Q1 vs Q3: 0.3–0.8s improvement from rubber alone
- Race: track typically improves 0.2–0.4s from lap 1 to lap 10 then stabilizes

**Practical implementation:** Fit a simple exponential decay model to the session lap time trend of the entire field:

```python
track_gain(t) = A * (1 - exp(-t / τ))
```

where `t` is laps/session time since start, `A` is total track gain, `τ` is time constant. Fit A and τ from field-wide lap time progression. Subtract from individual laps before comparison.

**New tool:** `get_track_evolution_model(round_number, session_type)` → returns session-time lap time correction curve

**LLM benefit:** Can say "Norris's lap in Q1 was set 22 minutes into the session; accounting for track evolution, it was equivalent to X.XXXs in Q3 conditions."

**Implementation difficulty:** Medium

---

## 6. Weather-Adjusted Pace Analysis

### What literature says
Bell et al. (JQAS 2016): driver effects are larger in wet conditions — team advantage diminishes. Wet races are the best natural experiment for isolating driver skill from car performance.

**Practical modeling:** Track temperature correlates with lap time through tyre thermal behaviour:
- +10°C track temperature ≈ −0.2 to −0.4 s/lap (faster due to lower tyre overheating in cooler conditions for some compounds; slower in very cold conditions for cold-sensitive compounds)
- Rain: completely different regime — intermediate/wet tyres, driver skill variance massively increases

FastF1 exposes weather data: `session.load(weather=True)` → TrackTemp, AirTemp, Rainfall, WindSpeed per lap.

### What to build
`analyze_wet_weather_performance(driver_code, season)`:
1. Pull all wet/mixed-condition race results from Jolpica (Rainfall flag)
2. Compare driver finishing position vs. expected (grid-based) in wet vs. dry
3. Returns: "wet weather performance uplift" — how many positions gained/lost vs. expectation

This is the best proxy for raw driver skill available without a full Bayesian model.

**LLM benefit:** Can answer "is Verstappen actually better in the rain?" with data.

**Implementation difficulty:** Medium (Jolpica + FastF1 weather integration)

---

## 7. Overtaking & DRS Analysis

### What literature says
**Source:** de Groote (JSA 2021): Poisson regression on overtaking data 2011–2018. 50% of overtaking decline attributable to aerodynamics, 20–30% to field size, 20% to strategy uniformity.  
**Source:** de Groote (JQAS 2025): Long-horizon (1983–2010) — historical baseline.

**Practical implication:** DRS zones have diminishing returns as the field becomes more homogeneous. Overtaking probability at a specific circuit and corner combination can be estimated from historical data.

### What to build
`get_overtaking_analysis(round_number)`:
1. Count overtaking events during the race using position change data
2. Attribute to DRS zone, non-DRS zone, pit strategy, retirements
3. Compare to circuit historical average
4. Flag circuits where overtaking is structurally difficult (Monaco, Hungaroring)

OpenF1 position data (3.7 Hz) allows detecting overtakes by tracking position changes with timestamp.

**LLM benefit:** Can answer "why didn't Norris pass Leclerc in the middle stint?" with circuit-specific overtaking difficulty context.

**Implementation difficulty:** Medium (OpenF1 position data parsing)

---

## 8. Safety Car & Virtual Safety Car Prediction

### What literature says
Not directly modeled in the surveyed papers, but Monte Carlo strategy models (TUMFTM) treat SC probability as a Poisson process — typically 1 SC event per 3–4 races on average circuits, higher on street circuits (Monaco ~60% SC probability per race).

### What to build
`get_safety_car_probability(round_number)`:
- Historical SC frequency at this circuit from Jolpica race data
- Current race SC incidents from OpenF1 race control messages
- Remaining distance to end: Poisson-process probability of at least one more SC

**LLM benefit:** Strategy analysis can include "given this circuit's 45% SC probability, a 3-stop strategy becomes viable."

**Implementation difficulty:** Low (Jolpica historical + OpenF1 race control)

---

## 9. Mini-Sector & Corner-by-Corner Lap Delta

### What literature says
**Source:** "Towards Formula 1 Analysis" (Medium series) — practitioner implementation  
**Source:** FastF1 Playbook 2026 (García) — mini-sector methodology using FastF1

**Current state:** The system computes sector times (S1/S2/S3) and corner profiles, but doesn't do proper mini-sector analysis — splitting the lap into 25–30 equal-distance zones and computing the cumulative lap delta at each zone boundary.

### What to build
`get_lap_delta_trace(round_number, session_type, driver_a, driver_b)`:
- Returns cumulative time delta at every 100m of the lap
- Positive = driver A ahead at that point, negative = behind
- Exposes exactly WHERE on the circuit each driver gains/loses time
- Different from current speed trace: this shows time delta, not speed

This is what broadcasters show in the "mini-sector timing" graphic. Race engineers look at this before anything else.

**Implementation difficulty:** Low — FastF1 already provides the data; it's a computation change on top of existing telemetry functions. The `get_lap_telemetry` function already samples at 100m; adding a running time integral is trivial.

**LLM benefit:** Can say "Norris gained 0.08s through the chicane (150m–400m) but gave back 0.12s on the back straight acceleration (1200m–1800m)" — precise location-specific reasoning.

---

## 10. Cross-Race Driver Form Analysis

### What literature says
**Source:** "Benchmarking F1 Results Using a Normal Model" (arXiv:2603.15192, 2026) — applies statistical benchmarks to the 2025 season  
**Source:** "Competitiveness" paper (arXiv:2501.00126) — season-to-season stability metrics

### What to build
`get_driver_form_curve(driver_code, last_n_races)`:
1. Pulls last N race results from Jolpica
2. Computes: average finish vs. expected finish (by grid position), trend over recent races
3. Detects: "on a hot streak" (consistent improvement), "form dip" (underperforming vs grid), "car upgrade moment" (sudden step change)

This feeds into race prediction and into LLM answers to "is [driver] currently in form?"

**Implementation difficulty:** Low–Medium (Jolpica data, statistical smoothing)

---

## 11. Computer Vision — Livery/Car Detection (Long Term)

### What literature says
**Source:** f1-racing-cars-tracking (GitHub, andrea-gasparini) — Faster R-CNN achieves 97% precision / 99% recall  
**Source:** "Decoding the Grid" (Medium) — YOLO for livery classification

### What to build (long term)
`analyze_broadcast_footage(video_url)`:
- Detect cars in broadcast video
- Classify by team/driver from livery
- Extract on-track position, gap to car ahead
- Feed into real-time analysis pipeline

This is out of scope for the current architecture (FastF1 + OpenF1 data) but is the frontier for live race intelligence.

**Implementation difficulty:** Very High (requires video ingestion pipeline, model training)

---

## 12. LLM-as-Strategist Mode

### What literature says
**Source:** FormulaGPT (GitHub, dawid-maj) — LLM acts as team strategist making pit/tyre decisions  
**Source:** Todd et al. (ACM SAC 2025) — explainable RL for strategy with human-readable justifications

### What to build
A conversational strategy mode where the user poses mid-race scenarios:
> "We're on lap 35/56, Norris is P3 on lap 22 Mediums, Verstappen is P2 on lap 8 Hards. Should we pit?"

The system would:
1. Run degradation projection for both drivers to race end
2. Estimate Verstappen's pace advantage on fresher rubber
3. Calculate undercut window
4. Return: "pit now — Norris has ~8 laps of viable pace left; Verstappen's Hards will be worn by lap 45; undercut window opens around lap 38"

This ties together: degradation model + race pace model + gap analysis + strategy simulation.

**Implementation difficulty:** High (requires race simulation + improved deg model first)

---

## Summary: What to Build and When

### Now (1–2 weeks, high leverage, limited scope)
| Feature | Tool name | Core dependency |
|---|---|---|
| Cumulative lap delta trace | `get_lap_delta_trace` | Existing telemetry |
| Pit stop effectiveness | `analyze_pit_window` | Existing data |
| Safety car probability | `get_sc_probability` | Jolpica + OpenF1 |
| Weather-adjusted form | `analyze_wet_performance` | Jolpica + FastF1 weather |

### Soon (2–4 weeks, moderate new code)
| Feature | Tool name | Core dependency |
|---|---|---|
| Elo driver rating | `get_driver_elo_rating` | Jolpica multi-season |
| Car-adjusted Elo | `get_driver_skill_estimate` | Jolpica multi-season |
| Overtaking analysis | `get_overtaking_analysis` | OpenF1 position data |
| Track evolution model | `get_track_evolution` | FastF1 weather/lap data |
| FP3 → qualifying prediction | `predict_qualifying_order` | FastF1 FP session |

### Later (1–3 months, significant investment)
| Feature | Tool name | Core dependency |
|---|---|---|
| Race outcome prediction | `predict_race_outcome` | Pre-trained XGBoost |
| Monte Carlo strategy sim | `simulate_race_strategy` | Improved deg model + sim engine |
| Bayesian driver rating | `get_driver_bayesian_rating` | PyMC + multi-season pipeline |
| Driver form trend | `get_driver_form_curve` | Jolpica multi-season |
| LLM strategist mode | (conversational) | Strategy sim + improved deg |

---

## Driver Skill Rating: Recommended Implementation Plan

Given the research, here is the concrete implementation path from easiest to most rigorous:

**Step 1 — Elo (1 day):**
```python
# For each season's race results (Jolpica):
# Treat each race as pairwise matchups
# Elo update: winner gains K*(1-P(win)), loser loses same
# P(A beats B) = 1 / (1 + 10^((θ_B - θ_A)/400))
# GAS variant: K adapts based on surprise factor
```
Returns: current Elo rating per driver, historical trend.

**Step 2 — Car-adjusted Elo (2 days):**
```python
# Add constructor-year term: θ_i_effective = θ_driver_i + θ_constructor_year
# Optimize jointly via gradient descent on ranking loss
# Or: fit constructor effect from teammates' relative performance
```
Returns: driver Elo stripped of car effect.

**Step 3 — RAPM (3 days):**
```python
# Design matrix X: rows = race results, columns = driver + constructor indicators
# Target y: finishing position delta from grid (positions gained/lost)
# Ridge regression: β = (X'X + λI)^-1 X'y with time decay weighting
```
Returns: driver "points added" over median in median car.

**Step 4 — Full Bayesian (weeks):**
Uses PyMC, Jolpica API for 2014–2024 data, outputs full posterior over driver skill with uncertainty. Directly replicates van Kesteren & Bergkamp (2023) — replication code at Zenodo.

---

*Assumptions: All feature difficulty estimates assume existing FastAPI/FastF1 architecture. Jolpica API access confirmed already used in f1_data.py. OpenF1 position data at 3.7Hz is available from 2023 onward — overtaking analysis limited to 2023+ without alternative source.*
