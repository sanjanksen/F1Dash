# Race-Strategy Analytical Features (F16, F18, F19, F20) Implementation Plan

> Status: not started. Estimated effort: Phase 1 (F16, F18, F19) ~2–3 weeks. Phase 3 (F20) ~2–3 months, deferred until F15 is shipped.

## Goal

Bring three quantitative race-strategy capabilities into F1Dash so the assistant can answer the canonical viewer question — *"Should X have pitted now?"* — and its variants without hand-waving. Specifically:

- **F16 — Undercut / overcut calculator.** A first-principles cost/benefit model that says whether the undercut (or overcut) was actually available at a given lap, with the crossover lap and a numeric recommendation.
- **F18 — Per-circuit safety-car probability prior.** A static lookup table the assistant can quote when discussing pit-window risk, plus a tool to surface the number on demand.
- **F19 — VSC vs full-SC differential pit-loss.** Two scaled pit-loss numbers (`vsc_pit_loss`, `sc_pit_loss`) that flow into the F16 calculator and into the F15 counterfactual simulator when an SC/VSC is active.
- **F20 — Learning-based strategy chooser (deferred).** A research-grade FFNN/LSTM model that, given a race state, returns ranked stop strategies. Builds on F15 (counterfactual) — F15 is the trainer for F20.

F15 (counterfactual simulation) and F17 (full Monte Carlo) are scoped in their own plans and are explicitly out of scope here. F16 and F19 produce inputs that F15's optional probabilistic phase (Phase 3 of that plan) will consume.

## Background

F1Dash currently answers strategy questions ("did the undercut work?") narratively, by quoting `analyze_race_pace_battle` or `get_pit_stop_strategy`. Those tools tell the user what happened, not whether the alternative was numerically available. The result is an assistant that sounds confident but stops short of the actionable answer.

The undercut math is well-understood by paddock strategists:

> The undercut works when fresh-tyre pace gained over N rejoin laps exceeds pit loss plus warm-up cost plus traffic cost.

Every term is derivable from FastF1 data already in the codebase. The missing piece is the calculator itself plus a tool surface for the LLM.

F18 and F19 are static knowledge that should have shipped with the original circuit profiles — Singapore and Monaco being ~100 % SC-likely and VSC pit-loss being roughly half of green-flag pit-loss are textbook facts the assistant currently has to infer from race-by-race telemetry. Both feed F16 (and later F15).

F20 is included to anchor the deferred roadmap. The Heilmeier 2020b "Virtual Strategy Engineer" (Applied Sciences 10:7805) and Fieni et al. 2025 (arXiv:2512.21570) MINLP+RL papers both require large volumes of simulated-race training data. F15's counterfactual engine is exactly that data source. We do not build F20 before F15 is producing usable training data.

## Architecture

```
Existing F1Dash:
  server/chat.py (agentic loop, widget builders, system prompt)
    → server/tools.py (tool registry)
       → server/f1_data.py (FastF1 wrappers — gets new helpers)
       → server/circuit_profiles.py (gets CIRCUIT_SC_PROBABILITY table)
       → server/strategy_math.py (NEW — undercut/overcut math, pure functions)
  client/src/components/chat-widgets/
    → UndercutOvercutWidget.jsx (NEW)
    → SafetyCarOutlookWidget.jsx (NEW, small)
  client/src/components/AnswerRenderer.jsx (NEW cases)
```

Module boundaries:

- **`server/strategy_math.py`** — new. Owns the pure-math layer: `compute_undercut_window()`, `compute_pit_loss_variants()` (returns green/VSC/SC variants). No FastF1 imports, no I/O. All inputs are plain dicts/numbers. Tests run in <50 ms with no fixtures.
- **`server/f1_data.py`** — small additions: `get_actual_pit_loss(round_number)` (median of in-race stops + pit-lane delta), `get_tyre_age_at_lap(driver_code, lap)`, `get_gap_to_driver(driver_code, target_code, lap)`. All three are thin wrappers around data the FastF1 session already exposes.
- **`server/circuit_profiles.py`** — add `CIRCUIT_SC_PROBABILITY` dict at module scope, plus `get_safety_car_prior(circuit_key)` accessor. Touch no existing keys.
- **`server/tools.py`** — two new tool definitions: `analyze_undercut_overcut`, `get_safety_car_outlook`. Wired into `execute_tool()`.
- **`server/chat.py`** — two new widget builders, system-prompt rule added to the strategy-questions block.
- **Frontend** — two new React components, two `AnswerRenderer` cases.

This is intentionally a thin slice. The math module is the only new file with non-trivial logic; everything else is glue.

## Cross-References

- **F15 counterfactual sim** (`2026-05-19-counterfactual-race-simulation.md`) — F16's `compute_undercut_window()` and F19's pit-loss variants are direct inputs to F15's Phase 3 probabilistic phase. The two plans share the `get_actual_pit_loss()` helper added here. Build F16 first so F15's Phase 1 has a tested pit-loss source.
- **F17 Monte Carlo** (separate plan) — F18's `CIRCUIT_SC_PROBABILITY` table becomes the prior distribution for F17's sampled SC timing. Same table, two consumers.
- **Tyre cliff detection** (`2026-05-15-tire-cliff-detection.md`, shipped) — F16's `Δfresh_tyre_pace` term depends on per-stint deg curves. When a cliff is detected, F16 uses the pre-cliff slope to project fresh-tyre pace and flags reduced confidence in the widget.
- **Data currency** (`2026-05-19-data-currency-coverage.md`) — independent. F18's circuit table should be cross-checked against F7's circuit-profile audit before ship.

---

## Phase 1 — F16 Undercut/Overcut Calculator (highest impact)

### Task 1 (F16) — Undercut/Overcut Math Module And Tool

Files:

- Create: `server/strategy_math.py`
- Modify: `server/f1_data.py` — add `get_actual_pit_loss()`, `get_tyre_age_at_lap()`, `get_gap_to_driver()` helpers
- Modify: `server/tools.py` — add `analyze_undercut_overcut` tool definition + dispatch
- Modify: `server/chat.py` — add `_make_undercut_overcut_widget()`, update system prompt
- Create: `client/src/components/chat-widgets/UndercutOvercutWidget.jsx`
- Modify: `client/src/components/AnswerRenderer.jsx` — add `undercut_overcut` case
- Tests: `server/tests/test_strategy_math.py` (new), `server/tests/test_f1_data.py`, `server/tests/test_chat.py`

#### The Math

The undercut/overcut decision is a comparison of two terms — *what you gain on fresh rubber* vs *what you pay to get there*. Every quantity here is a per-lap time in seconds; negative numbers mean "favourable to pitting now".

##### Core equation

```
Undercut_advantage(L) =
    [Δfresh_tyre_pace(L_decision) × N_laps_to_rejoin_ahead]
    -  Pit_loss
    -  Out_lap_warmup_penalty
    -  Traffic_cost
    -  Δfuel_pace_correction
```

If `Undercut_advantage(L) > 0`, the undercut is numerically available at lap `L`. If `< 0`, staying out (the overcut, or simply holding station) is the better deterministic call.

##### Term definitions

**1. `Δfresh_tyre_pace(L_decision)` — fresh-tyre pace gain, in s/lap.**

This is the *instantaneous* pace delta between the fresh new compound and the current worn compound on the focal driver's car, evaluated at the lap of decision.

```
Δfresh_tyre_pace = (
    base_pace_old_compound
      + deg_slope_old × current_tyre_age
)  -  (
    base_pace_new_compound
      + out_lap_compound_offset
)
```

- `deg_slope_old` comes from the existing `_fit_stint_degradation()` output. If a tyre cliff was detected for that stint, use `post_cliff_deg_rate_s_per_lap` once `current_tyre_age >= cliff_tyre_age`; otherwise use `pre_cliff_deg_rate_s_per_lap` or the simple `deg_rate_s_per_lap`.
- `base_pace_X` is the compound's fuel-corrected baseline lap time from the driver's first three clean laps on that compound this race. If unavailable (e.g. driver never ran the new compound), fall back to the field-median baseline from `_fit_stint_degradation()` aggregated across all drivers.
- `out_lap_compound_offset` is a per-compound constant captured in `strategy_math.py`: `{"SOFT": 0.6, "MEDIUM": 1.0, "HARD": 1.6}` seconds — the out-lap is always slower than steady-state on the new compound; harder compounds need more warm-up.

Typical realistic range: **1.5–2.5 s/lap** on a typical stint, growing as `current_tyre_age` increases.

**2. `N_laps_to_rejoin_ahead` — how many laps the fresh-tyre advantage compounds before rejoin.**

This is the number of laps between the pit-in lap and the lap on which the focal driver crosses the line ahead of the target driver. In practice we approximate it as 1 lap for the canonical "did the undercut work after one pit cycle" question.

For multi-lap undercut analysis (rare, but useful for stuck-behind-traffic scenarios), the calculator iterates `N` from 1 to 5 and returns the lap at which advantage first turns positive — the **crossover lap**.

**3. `Pit_loss` — wall-clock seconds lost vs staying out.**

```
Pit_loss = pit_lane_delta_time + median_stationary_time
```

Both terms come from FastF1 for the current race. `pit_lane_delta_time` is the difference between a normal-speed lap through the pit lane (including pit-entry braking and pit-exit acceleration) and a green-flag racing lap on the same circuit — usually 18–22 s. `median_stationary_time` is 2.0–2.8 s, computed as median across all stops in the session.

Circuit-typical range: **18–28 s total.** Monaco ~22 s, Spa ~21 s, Singapore ~28 s.

**4. `Out_lap_warmup_penalty` — extra seconds on the out-lap from cold tyres.**

Captured as a tiered constant in `strategy_math.py`:

```python
OUT_LAP_WARMUP = {
    "SOFT":   {"warm_track": 0.5, "cool_track": 1.0},
    "MEDIUM": {"warm_track": 0.8, "cool_track": 1.3},
    "HARD":   {"warm_track": 1.2, "cool_track": 2.0},
    "INTERMEDIATE": {"warm_track": 0.0, "cool_track": 0.0},  # wet already warm
    "WET":          {"warm_track": 0.0, "cool_track": 0.0},
}
```

Track-warmth gate is derived from `track_temp_c` in the FastF1 session weather data: `cool_track` if `track_temp_c < 30`, else `warm_track`.

**5. `Traffic_cost` — cumulative seconds lost behind slower cars on rejoin.**

```
Traffic_cost =
    sum over N rejoin laps of max(0, pace_of_car_ahead_on_old_tyres - clean_air_pace_on_new_tyres)
```

Practically: we look at the cars likely to be in the focal driver's rejoin window (estimated from the gap-at-decision-lap minus pit_loss). For each of those cars, if their predicted pace over the next N laps is more than 0.3 s/lap slower than the focal driver's fresh-tyre pace, add the deficit to `Traffic_cost`.

If rejoin is in clean air (no car within 1.5 s after pit cycle), `Traffic_cost = 0`.

**6. `Δfuel_pace_correction` — small adjustment for fuel-load difference.**

The pitting car spends one less lap burning fuel before crossing the line on its rejoin; the staying-out car burns one extra. Already factored into the fuel-corrected lap times we use for `base_pace`. Set to `0` unless the question spans multiple laps (`N >= 3`), in which case use `fuel_coeff × fuel_burn_per_lap × N` — typically 0.03 s/kg × 1.8 kg/lap × N.

##### Worked example — Singapore 2024, lap 25, Norris attempting to undercut Verstappen

Setup: Norris is 2.2 s behind Verstappen, both on Mediums, age 22 laps. Cooler than Bahrain, track temp 31 °C → `warm_track`.

```
deg_slope_old           = 0.06 s/lap (from fitted stint)
current_tyre_age        = 22
base_pace_old_compound  = 95.20 s (Medium fuel-corrected baseline)
base_pace_new_compound  = 93.90 s (Hard fuel-corrected baseline)
out_lap_compound_offset = 1.6 s   (Hard)
Δfresh_tyre_pace        = (95.20 + 0.06 × 22) - (93.90 + 1.6) = 96.52 - 95.50 = 1.02 s/lap

N_laps_to_rejoin_ahead  = 1
Pit_loss                = 28.0 s (Singapore — long pit lane)
Out_lap_warmup_penalty  = 1.2 s   (Hard, warm track)
Traffic_cost            = 4.5 s   (cars between P5 and P9 within rejoin window, ~0.4 s/lap slower for 1 lap × ~4 cars × small overlap)
Δfuel_pace_correction   = 0.0

Undercut_advantage = (1.02 × 1) - 28.0 - 1.2 - 4.5 - 0.0 = -32.7 s
```

Verdict: **undercut not available.** Even with no traffic, the 1.02 s/lap fresh-tyre gain only nets back ~1 s/lap of the 28 s pit-loss bill — you'd need ~28 rejoin laps in clean air for the undercut to pay back. The widget should report: *"Undercut requires 28 laps to pay back vs ~5 remaining stint laps. Stay out."*

##### Worked example — Bahrain 2025, lap 18, Russell attempting to overcut Hamilton

Setup: Russell 0.4 s ahead of Hamilton, both on Softs, age 14. Track temp 38 °C → `warm_track`.

```
Δfresh_tyre_pace        = 1.8 s/lap (Medium replacement)
N_laps_to_rejoin_ahead  = 1
Pit_loss                = 22.0 s
Out_lap_warmup_penalty  = 0.8 s (Medium, warm)
Traffic_cost            = 0.0 (clean air on rejoin)
```

If Russell stays out instead while Hamilton pits, Russell continues at ~95.5 s/lap with deg ~0.08 s/lap, gaining 1.8 - 0.08 × 1 ≈ 1.72 s on Hamilton on the lap Hamilton pits, then losing 22 s on the next lap when Russell pits. **Overcut available iff** Russell extends the stint by ≥ 2 laps and finds clean air on rejoin. Widget reports: *"Overcut viable for 2-lap extension. Watch for traffic at rejoin."*

#### `strategy_math.py` — exact function signatures

```python
# Module-scope constants
OUT_LAP_COMPOUND_OFFSET = {"SOFT": 0.6, "MEDIUM": 1.0, "HARD": 1.6,
                            "INTERMEDIATE": 0.5, "WET": 0.5}
OUT_LAP_WARMUP = {  # see table above }
TRAFFIC_PACE_THRESHOLD_S_PER_LAP = 0.3
CLEAN_AIR_GAP_S = 1.5
COOL_TRACK_TEMP_C = 30.0

def compute_undercut_window(
    driver_code: str,
    current_lap: int,
    target_driver_code: str | None,
    snapshot: dict,         # built by f1_data; see below
    max_rejoin_laps: int = 5,
) -> dict:
    """
    Returns:
        {
            "undercut_available": bool,
            "overcut_available": bool,
            "advantage_s": float,            # Undercut_advantage at N=1
            "crossover_lap": int | None,      # lap at which advantage first turns >= 0, or None
            "pit_loss_s": float,
            "delta_fresh_pace_s_per_lap": float,
            "out_lap_warmup_s": float,
            "traffic_cost_s": float,
            "recommendation": str,            # "pit_now" | "stay_out" | "marginal"
            "confidence": str,                # "high" | "moderate" | "low"
            "rationale": list[str],           # human-readable bullets
            "inputs_summary": dict,           # echo back what we used
        }
    """

def compute_pit_loss_variants(green_pit_loss_s: float) -> dict:
    """
    F19 helper. Returns:
        {"green": x, "vsc": x * 0.55, "sc": x * 0.35}
    All in seconds. Coefficients are configurable module constants.
    """

VSC_PIT_LOSS_FRACTION = 0.55
SC_PIT_LOSS_FRACTION = 0.35
```

The `snapshot` dict is built by a new helper `_build_strategy_snapshot()` in `f1_data.py` and contains:

- `pit_loss_s` (from `get_actual_pit_loss(round_number)`)
- `track_temp_c` (from session weather)
- `driver`: `{compound, tyre_age, deg_slope, base_pace, has_cliff, pre_cliff_slope, post_cliff_slope, cliff_age}`
- `target`: same shape as `driver` (None if no target)
- `gap_to_target_s` (from `get_gap_to_driver`)
- `cars_in_rejoin_window`: list of `{code, predicted_pace, predicted_gap_after_pit}`
- `active_sc_state`: `"green" | "vsc" | "sc"` (from race-control messages, default green)

#### Tool definition (`tools.py`)

```python
{
    "name": "analyze_undercut_overcut",
    "description": (
        "Quantitative undercut/overcut calculator. Use whenever the user asks "
        "'should X have pitted', 'was the undercut on', 'would the overcut have worked', "
        "or any variant of 'should they pit now'. Returns advantage in seconds, "
        "crossover lap, and a pit_now/stay_out/marginal recommendation. "
        "Do NOT use this for general race-pace questions — use analyze_race_pace_battle."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "driver_code": {"type": "string"},
            "lap_number": {"type": "integer"},
            "target_driver_code": {"type": "string",
                                    "description": "Optional. The car the undercut is being attempted on. Omit for general 'should they pit' analysis."},
            "year": {"type": "integer"},
            "round_number": {"type": "integer"},
        },
        "required": ["driver_code", "lap_number"],
    },
}
```

`execute_tool()` builds the snapshot, calls `compute_undercut_window()`, and returns the dict.

#### System prompt rule (chat.py)

Add to the strategy-questions block:

> When the user asks whether a driver should have pitted, or whether the undercut/overcut was available, **invoke `analyze_undercut_overcut`** before answering. Never estimate undercut viability from race-pace data alone. If the tool reports `recommendation == "marginal"` or `confidence == "low"`, explicitly say so in the answer. If `active_sc_state` is `vsc` or `sc`, mention that pit-loss is reduced.

Forbidden: invoking this tool for general pace comparisons or for races where the user has not raised a strategy decision. Use `analyze_race_pace_battle` instead.

#### Widget (`UndercutOvercutWidget.jsx`)

Layout:

- Header: *"Undercut analysis — {driver} on lap {lap}"* with target sub-line if applicable.
- Big-number block: `advantage_s` formatted as `+1.2 s` or `-32.7 s` with a green/red colour.
- Recommendation pill: `PIT NOW` (green) / `STAY OUT` (red) / `MARGINAL` (amber).
- Breakdown table:

  | Term | Value |
  |---|---|
  | Fresh tyre gain | +1.02 s/lap |
  | Pit loss | -28.0 s |
  | Out-lap warm-up | -1.2 s |
  | Traffic cost | -4.5 s |
  | **Net advantage** | **-32.7 s** |

- Crossover lap line: *"Would pay back at lap N — but stint ends lap M"*, or *"Pays back this cycle"* when N ≤ 1.
- Confidence chip: `high`/`moderate`/`low`.
- Rationale bullets below.

Keep dense; no chart needed for V1.

#### Acceptance Criteria

- `compute_undercut_window()` returns the canonical structure for 10 hand-rolled scenarios in `test_strategy_math.py` covering: clear undercut, clear overcut, marginal, missing target, cliff-detected fresh compound, cool-track Hard out-lap, SC active, VSC active, traffic-bound rejoin, clean-air rejoin.
- `get_actual_pit_loss()` returns within ±1.0 s of the FastF1-derived median for at least three test races.
- The tool is invoked by the LLM in the integration test for the prompt *"Should Norris have pitted on lap 25 in Singapore 2024?"* and not invoked for *"Who had better race pace in Bahrain?"*.
- Widget renders for all three recommendation states; visual snapshot tests pass.
- All existing tests still pass.

#### References

- Bernie Collins (Sky F1) — undercut math primer, repeated across her 2023–2025 race-day commentary.
- Heilmeier 2018 (IEEE ITSC 8570012) — § III.B "Pit Stop Model" formalises pit-loss decomposition.
- Sulsters 2018 (VU Amsterdam MSc) — § 3.4 fresh-tyre-pace modelling.
- FastF1 docs — `session.laps`, `session.weather_data`, race-control messages API.

---

### Task 2 (F18) — Per-Circuit Safety-Car Probability Prior

Files:

- Modify: `server/circuit_profiles.py` — add `CIRCUIT_SC_PROBABILITY` dict + accessor
- Modify: `server/tools.py` — add `get_safety_car_outlook` tool
- Modify: `server/chat.py` — add `_make_safety_car_outlook_widget()`, update system prompt
- Create: `client/src/components/chat-widgets/SafetyCarOutlookWidget.jsx`
- Modify: `client/src/components/AnswerRenderer.jsx` — add `safety_car_outlook` case
- Tests: `server/tests/test_circuit_profiles.py` (new section), `server/tests/test_chat.py`

#### Change Description

Add a module-scope dict at the top of `circuit_profiles.py`:

```python
CIRCUIT_SC_PROBABILITY: dict[str, dict] = {
    # circuit_key: matches the existing CIRCUIT_PROFILES key
    "singapore": {
        "sc_probability": 1.00,
        "vsc_probability": 0.55,
        "expected_sc_duration_laps": 4,
        "expected_vsc_duration_laps": 2,
        "historical_sample_size": 14,   # 2008–2024 (excluding the abandoned 2009)
        "rationale": "Street, hot, long lap. SC has appeared in every running.",
        "source": "Sky F1 / Axiora historicals",
        "source_date": "2025-12",
    },
    "monaco":      {"sc_probability": 0.88, "vsc_probability": 0.40, "expected_sc_duration_laps": 5,
                    "expected_vsc_duration_laps": 2, "historical_sample_size": 20,
                    "rationale": "Street, narrow, almost zero overtaking; any incident becomes an SC."},
    "azerbaijan":  {"sc_probability": 0.85, "vsc_probability": 0.50, "expected_sc_duration_laps": 5,
                    "expected_vsc_duration_laps": 2, "historical_sample_size": 7,
                    "rationale": "Street, long straights, wall-line corners."},
    "saudi_arabia":{"sc_probability": 0.85, "vsc_probability": 0.50, "expected_sc_duration_laps": 4,
                    "expected_vsc_duration_laps": 2, "historical_sample_size": 4,
                    "rationale": "High-speed street, blind walls, debris-prone."},
    "imola":       {"sc_probability": 0.85, "vsc_probability": 0.40, "expected_sc_duration_laps": 4,
                    "expected_vsc_duration_laps": 2, "historical_sample_size": 12,
                    "rationale": "Narrow permanent circuit, gravel traps, weather-prone."},
    "las_vegas":   {"sc_probability": 0.85, "vsc_probability": 0.50, "expected_sc_duration_laps": 4,
                    "expected_vsc_duration_laps": 2, "historical_sample_size": 2,
                    "rationale": "Street, cold, debris risk. Small sample — high uncertainty."},
    "australia":   {"sc_probability": 0.70, "vsc_probability": 0.35, "expected_sc_duration_laps": 4,
                    "expected_vsc_duration_laps": 2, "historical_sample_size": 24,
                    "rationale": "Semi-permanent street circuit, gravel traps after 2022 layout change."},
    "canada":      {"sc_probability": 0.70, "vsc_probability": 0.40, "expected_sc_duration_laps": 4,
                    "expected_vsc_duration_laps": 2, "historical_sample_size": 18,
                    "rationale": "Wall of Champions, weather-prone, low grip."},
    "qatar":       {"sc_probability": 0.55, "vsc_probability": 0.30, "expected_sc_duration_laps": 3,
                    "expected_vsc_duration_laps": 2, "historical_sample_size": 3,
                    "rationale": "Permanent, but tyre-degradation extreme — sample too small to be confident."},
    "suzuka":      {"sc_probability": 0.45, "vsc_probability": 0.35, "expected_sc_duration_laps": 4,
                    "expected_vsc_duration_laps": 2, "historical_sample_size": 30,
                    "rationale": "Permanent, weather-prone (rain often triggers SC)."},
    "spa":         {"sc_probability": 0.40, "vsc_probability": 0.35, "expected_sc_duration_laps": 3,
                    "expected_vsc_duration_laps": 2, "historical_sample_size": 32,
                    "rationale": "Permanent, weather-prone, long lap — local yellows often suffice."},
    "hungary":     {"sc_probability": 0.30, "vsc_probability": 0.20, "expected_sc_duration_laps": 3,
                    "expected_vsc_duration_laps": 2, "historical_sample_size": 30,
                    "rationale": "Permanent, low-speed, low incident rate."},
    "silverstone": {"sc_probability": 0.30, "vsc_probability": 0.30, "expected_sc_duration_laps": 3,
                    "expected_vsc_duration_laps": 2, "historical_sample_size": 30,
                    "rationale": "Permanent, wide run-offs, weather-prone but most incidents stay local."},
    "barcelona":   {"sc_probability": 0.20, "vsc_probability": 0.15, "expected_sc_duration_laps": 3,
                    "expected_vsc_duration_laps": 2, "historical_sample_size": 30,
                    "rationale": "Wide run-offs, predictable, low incident rate."},
    "paul_ricard": {"sc_probability": 0.10, "vsc_probability": 0.15, "expected_sc_duration_laps": 3,
                    "expected_vsc_duration_laps": 2, "historical_sample_size": 8,
                    "rationale": "Massive run-offs, lowest historical SC rate. (Not on 2026 calendar; kept for historical queries.)"},
    # Remaining entries to populate at implementation time:
    # bahrain, miami, miami_2026, china, austria, netherlands, mexico, brazil, abu_dhabi,
    # plus any 2026-new venues. Use Axiora historical priors as starting point; the
    # F18 audit ships with whichever entries are sourced — missing keys cleanly fall
    # back to a conservative default in get_safety_car_prior().
}

DEFAULT_SC_PRIOR = {
    "sc_probability": 0.45,
    "vsc_probability": 0.30,
    "expected_sc_duration_laps": 3,
    "expected_vsc_duration_laps": 2,
    "historical_sample_size": 0,
    "rationale": "No circuit-specific prior available; using grid-wide median.",
    "source": "default",
    "source_date": None,
}

def get_safety_car_prior(circuit_key: str) -> dict:
    """Returns CIRCUIT_SC_PROBABILITY[circuit_key] or DEFAULT_SC_PRIOR with a 'fallback' flag."""
    if circuit_key in CIRCUIT_SC_PROBABILITY:
        return {**CIRCUIT_SC_PROBABILITY[circuit_key], "fallback": False}
    return {**DEFAULT_SC_PRIOR, "fallback": True, "circuit_key": circuit_key}
```

Tool definition:

```python
{
    "name": "get_safety_car_outlook",
    "description": (
        "Returns the historical safety-car and VSC probability prior for a given race. "
        "Use when the user asks about SC likelihood, pit-window risk, or 'how likely is "
        "a safety car here'. Returns probability, expected duration in laps, and sample "
        "size. Honest about uncertainty for small-sample venues."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "round_number": {"type": "integer"},
            "year": {"type": "integer"},
        },
        "required": ["round_number"],
    },
}
```

`execute_tool()` resolves `round_number` → circuit key via `get_circuit_profile()`'s existing logic, then calls `get_safety_car_prior()`.

#### Widget (`SafetyCarOutlookWidget.jsx`)

Tiny — header, a single bar showing SC probability, a small bar for VSC, expected duration line, sample-size caveat when `historical_sample_size < 5`.

#### System Prompt Rule

Add to the strategy block:

> When the user asks about SC likelihood, pit-window risk, or how likely a safety car is at a given race, invoke `get_safety_car_outlook`. When `historical_sample_size < 5` or `fallback == true`, explicitly state the prior is weak.

Also: when the assistant invokes `analyze_undercut_overcut` and `recommendation == "marginal"`, it should additionally call `get_safety_car_outlook` for that round and weave the SC probability into the answer.

#### Acceptance Criteria

- At least 15 circuits populated, with `source` and `source_date` fields on each.
- `get_safety_car_prior()` returns `fallback: True` for unknown circuit keys.
- Tool invoked for the prompt *"How likely is a safety car in Singapore?"*.
- Widget renders with sample-size warning for venues with `historical_sample_size < 5`.

#### References

- Bernie Collins (Sky F1) commentary, multiple races 2023–2025.
- Axiora racing analytics, historical-SC tables.
- Generally accepted F1 strategy lore — re-verified against the most recent five seasons.

---

### Task 3 (F19) — VSC vs Full-SC Differential Pit-Loss

Files:

- Modify: `server/strategy_math.py` — `compute_pit_loss_variants()`, constants `VSC_PIT_LOSS_FRACTION`, `SC_PIT_LOSS_FRACTION`
- Modify: `server/f1_data.py` — `_build_strategy_snapshot()` reads race-control messages for active SC/VSC state, calls `compute_pit_loss_variants()`
- Modify: `server/tests/test_strategy_math.py` — variants test
- Modify: `server/chat.py` — system prompt note on SC-reduced pit loss

#### Change Description

`compute_pit_loss_variants(green_pit_loss_s)` returns the three pit-loss flavours:

```python
VSC_PIT_LOSS_FRACTION = 0.55   # everyone slows ~40 %, you "save" ~45 % of normal pit-loss
SC_PIT_LOSS_FRACTION = 0.35    # full SC bunches the field, "saving" ~65 %

def compute_pit_loss_variants(green_pit_loss_s: float) -> dict:
    return {
        "green": round(green_pit_loss_s, 2),
        "vsc": round(green_pit_loss_s * VSC_PIT_LOSS_FRACTION, 2),
        "sc": round(green_pit_loss_s * SC_PIT_LOSS_FRACTION, 2),
    }
```

`_build_strategy_snapshot()` populates `active_sc_state` from FastF1 race-control messages by checking for `"VSC DEPLOYED"` / `"VIRTUAL SAFETY CAR"` / `"SAFETY CAR DEPLOYED"` between `Time` of `lap_number - 1` and `lap_number`. Defaults to `"green"`.

`compute_undercut_window()` selects the appropriate variant:

```python
pit_loss_s = pit_loss_variants[snapshot["active_sc_state"]]
```

So an undercut analysis run during a VSC reports `pit_loss_s ≈ 13 s` instead of `~22 s`, often flipping a `STAY_OUT` recommendation to `PIT NOW`.

Calibration note: the 0.55/0.35 fractions are starting values from public commentary (Bernie Collins, Sky F1 strategy explainers) and should be re-validated against actual historical race data once the F15 counterfactual sim ships and produces calibration outputs. They are module constants so re-tuning is one line.

#### Cross-Reference To F15

F15's Phase 3 probabilistic phase consumes `compute_pit_loss_variants()` directly. F15's `apply_decision()` for `decision_type == "stay_out_under_sc"` uses `pit_loss_variants["sc"]` to model the foregone pit-stop saving.

#### Acceptance Criteria

- `compute_pit_loss_variants(22.0)` returns `{"green": 22.0, "vsc": 12.1, "sc": 7.7}`.
- A unit test runs `compute_undercut_window()` with the same inputs and `active_sc_state` toggled between `"green"`, `"vsc"`, `"sc"` and verifies the recommendation flips in the expected direction.
- Race-control parser is tolerant of the four observed message phrasings (`"VSC DEPLOYED"`, `"VIRTUAL SAFETY CAR DEPLOYED"`, `"SAFETY CAR DEPLOYED"`, `"SC DEPLOYED"`).
- System prompt instructs the assistant to mention the SC/VSC discount when relevant.

#### References

- Bernie Collins (Sky F1), repeated commentary on VSC pit-loss math 2022–2025.
- Heilmeier 2020a (Applied Sciences 10:4229) — § IV.D models SC pit-loss as a fraction of green.

---

## Phase 3 — F20 Learning-Based Strategy Chooser (Deferred)

### Task 4 (F20) — Virtual Strategy Engineer (research-grade, do not start before F15 ships)

Files (at build time, not now):

- Create: `server/strategy_model/` package — `train.py`, `inference.py`, `dataset.py`, `model.py`
- Create: `server/strategy_model/trained_weights/` — checkpointed model files
- Modify: `server/tools.py` — add `recommend_strategy` tool
- Modify: `server/chat.py` — add `_make_strategy_recommendation_widget()`
- Create: `client/src/components/chat-widgets/StrategyRecommendationWidget.jsx`
- Modify: `client/src/components/AnswerRenderer.jsx`
- Tests: `server/tests/test_strategy_model.py`

#### Why Deferred

F20 is a supervised-learning model. It needs training data: tens of thousands of simulated race outcomes for each of the canonical race states (lap, position, gap to rivals, tyre age, remaining compounds, SC active y/n). The only realistic source for that data is F15's counterfactual simulator running batch jobs.

Build order:

1. F15 Phase 1 ships (Heilmeier engine vendored, MVP counterfactual working).
2. F15 Phase 3 ships (lap-time noise sampling — gives us probabilistic outcomes per simulated race).
3. We script a data-generation pipeline that runs F15 across ~50 historical races × ~1000 strategy variants × ~10 noise samples = ~500 000 (race-state, outcome) pairs.
4. Only then start F20.

Doing F20 before F15 has shipped means hand-curating training data, which is not a serious option for this volume.

#### Model Architecture (research-grade target)

Two-model ensemble, per Heilmeier 2020b:

- **FFNN** — feed-forward network on per-decision-point feature vector. Inputs: current lap, position, gap-to-leader, gap-to-trailer, tyre compound (one-hot), tyre age, remaining compounds available (multi-hot), `active_sc_state` (one-hot), circuit prior features (SC probability, pit-loss variants, deg slope). Output: predicted finishing position for each of N candidate strategies (defined as a tuple of remaining stop laps + compounds). Trained with MSE.
- **LSTM** — sequence model on lap-by-lap state of the focal driver's race. Captures path dependence — e.g. "tyres were managed gently early, so cliff is later than the deg curve suggests". Output: same.
- **Ensemble** — weighted average of FFNN and LSTM outputs; weights learned per-circuit on a validation set.

Output of the tool:

```python
{
    "candidates": [
        {"strategy": ["lap 22 → MEDIUM", "lap 45 → HARD"],
         "predicted_finish_pos": 2.3, "p10_finish": 1, "p90_finish": 4,
         "rank": 1, "delta_vs_status_quo": -1.8},  # 1.8 places better
        # ... more candidates
    ],
    "status_quo": {"predicted_finish_pos": 4.1, ...},
    "feature_attributions": {"tyre_age": 0.34, "gap_to_leader": 0.21, ...},
    "model_confidence": "moderate",
    "note": "Model trained on 487 000 simulated races. Live race conditions (weather, mid-race retirements) not modelled.",
}
```

#### Reference Implementation

The closest published baseline is Heilmeier 2020b (Applied Sciences 10:7805) "Virtual Strategy Engineer". Their architecture maps almost 1:1 to the above. Their training data is from the predictive `race-simulation` engine; ours will be from F15.

A more recent attempt — Fieni, Pivetta, Mongelluzzo (ETH Zürich, 2025, arXiv:2512.21570) — formulates strategy as a mixed-integer nonlinear program (MINLP) wrapped in a reinforcement-learning policy. More principled but heavier; recommended only as a Phase-2 enhancement to F20.

#### Effort Estimate

- 2 weeks: data-pipeline scripting (F15 batch runner, feature extraction, train/val/test split).
- 4 weeks: model training, hyperparameter sweep, validation against held-out historical races.
- 2 weeks: inference path, tool surface, widget, system prompt.
- 2 weeks: calibration, sanity-check against expert ground truth, documentation.

Total: ~2.5 months of focused work after F15 ships.

#### Acceptance Criteria (for the future build, not for this plan)

- Model predicts within ±1.5 finishing positions on 80 % of held-out historical race states.
- Tool invoked correctly for *"What's the best 2-stop strategy for Norris from lap 20?"* style questions.
- Widget shows top-3 strategies with predicted finishing positions and confidence ranges.
- System prompt prevents over-confident phrasing — must always include the training-data caveat.

#### References

- Heilmeier, Thomaser, Graf, Betz (2020). *Virtual Strategy Engineer: Using ANNs for Race Strategy Decisions.* Applied Sciences 10(21):7805.
- Fieni, Pivetta, Mongelluzzo et al. (2025). *Towards Learning-Based Formula 1 Race Strategies.* arXiv:2512.21570.
- Heilmeier, Graf, Betz, Lienkamp (2020). *Application of Monte Carlo Methods to Consider Probabilistic Effects in a Race Simulation for Circuit Motorsport.* Applied Sciences 10(12):4229. (F15's underlying paper — same engine we'd train against.)

---

## Validation Checklist

- [ ] `server/strategy_math.py` exists with `compute_undercut_window()` and `compute_pit_loss_variants()`.
- [ ] `compute_undercut_window()` passes 10 hand-rolled scenarios (undercut, overcut, marginal, no target, cliff active, cool track, SC active, VSC active, traffic-bound, clean air).
- [ ] `get_actual_pit_loss()` returns within ±1.0 s of FastF1 median for at least three test races.
- [ ] `analyze_undercut_overcut` tool dispatched correctly for *"should X have pitted"* prompts and **not** for *"who had better race pace"* prompts.
- [ ] `UndercutOvercutWidget.jsx` renders all three recommendation states (`pit_now`, `stay_out`, `marginal`).
- [ ] `CIRCUIT_SC_PROBABILITY` populated for at least 15 circuits with sources.
- [ ] `get_safety_car_prior()` falls back cleanly for unknown circuits.
- [ ] `get_safety_car_outlook` tool dispatched for SC-likelihood prompts.
- [ ] `SafetyCarOutlookWidget.jsx` shows sample-size warning when `historical_sample_size < 5`.
- [ ] `compute_pit_loss_variants(22.0)` returns the documented {12.1, 7.7} pair.
- [ ] An undercut-under-VSC integration test flips recommendation vs green-flag baseline.
- [ ] Race-control parser handles all four observed VSC/SC message phrasings.
- [ ] System prompt updated for both new tools — agentic loop tests confirm correct routing.
- [ ] No new external dependencies added (Phases 1).
- [ ] All existing tests still pass.
- [ ] F20 explicitly marked deferred in this plan and in `server/strategy_math.py` module docstring.

## Risks And Open Questions

Surfaced per the user's risk-management protocol. Decisions needed inline before continuing past each milestone.

| Risk | When it triggers | Proposed solutions (ranked) | Recommendation |
|---|---|---|---|
| **Tyre-pace decay curve fidelity** — `Δfresh_tyre_pace` depends on `deg_slope_old` × `current_tyre_age`. Existing `_fit_stint_degradation()` slopes are noisy on short stints (< 8 laps); extrapolating 5–10 laps further (as F16's crossover-lap search does) can swing the answer by 1–2 s/lap. | Phase 1 unit testing | (1) Use cliff-pre slope when stint is past cliff and we're projecting forward; flag confidence: low. (2) Floor minimum stint length for slope use at 6 laps; below that, fall back to compound-typical slope (constant table: Soft 0.10, Med 0.07, Hard 0.05). (3) Show a confidence band on the widget instead of a point estimate. | (1) + (2) for V1; (3) deferred to a polish task. Surface to user: "deg slope from < 6-lap stint is unreliable — we used the compound-typical fallback". |
| **Out-lap warm-up modelling** — the tiered constant (`SOFT/MEDIUM/HARD × warm/cool`) is editorial. Real warm-up depends on driver style, fuel load, ambient + track temp delta, and how aggressive the in-lap was. Wrong by ≥ 0.5 s on extreme cases. | Phase 1 | (1) Ship the tiered constant as documented; treat it as a known editorial approximation. (2) Derive a per-driver, per-compound warm-up cost from each driver's actual first-lap-after-pit pace this race (FastF1 already has the data). (3) Both — constant for unseen drivers/compounds, empirical for those we have data on. | (3) — drop in (1) for V1 ship; add (2) as a Phase 1.5 refinement before Phase 3 of F15 consumes this output. Surface to user before V1: "warm-up cost is a constant approximation; we'll empirically calibrate after V1." |
| **Traffic-cost estimation** is the messiest term. Predicting which cars the focal driver rejoins next to requires a forward-projection of gaps, which is itself uncertain. | Phase 1 testing | (1) Use the gap snapshot at decision lap minus a fixed pit_loss to estimate rejoin position; assume cars in that window stay there for the rejoin lap. (2) Run a small forward sim (Heilmeier engine, single lap, no overtakes) to project. (3) Hide the term and only report it if the LLM follow-up asks. | (1) for V1; flag widget when ≥ 2 cars are within ±2 s of the predicted rejoin position ("traffic outcome highly variable"). (2) is only viable once F15 Phase 1 ships and we can call its engine. Surface to user: "rejoin traffic is a snapshot — actual undercut outcome depends on whether those cars hold their pace; we report it as a single number but it's the noisiest input." |
| **F18 sample-size honesty** — circuits like Las Vegas (n=2) and Qatar (n=3) have priors that are essentially editorial guesses. Quoting them as probabilities risks false precision. | After ship | (1) Hard-flag any prior with `historical_sample_size < 5` as low-confidence in the widget. (2) Quote a range instead of a point (e.g. "0.70–1.00"). (3) Suppress small-sample priors from the tool output entirely and fall back to the default. | (1) for V1; (2) for V1.1 if user feedback shows the point estimate gets misread. Surface to user: "for venues with < 5 races of history we will say 'limited history' in the widget and the assistant should mirror that." |
| **VSC/SC pit-loss fractions** (0.55, 0.35) are editorial starting points, not measured. Wrong fractions invert undercut recommendations during SC. | Phase 1 testing | (1) Ship the fractions as documented module constants; recalibrate post-F15 against simulator output. (2) Calibrate now using historical races where we can compare actual SC pit-loss to actual green-flag pit-loss from the same circuit. (3) Make them per-circuit. | (2) is the right answer but requires non-trivial historical-race analysis we don't have time for in Phase 1. Ship (1); flag in the widget when SC/VSC is active: "SC pit-loss is an editorial approximation; recalibration scheduled for V1.1." Surface to user **now** rather than discovering it after a wrong recommendation. |
| **Tool over-invocation** — the LLM may call `analyze_undercut_overcut` for every strategy question, including ones where the user is just asking "what happened". | Phase 1 dogfood | (1) System prompt explicit deflection rule: only invoke when the user uses "should", "would have", "was the X available", or "now / on lap N". (2) Add an integration test for *"who pitted when"* (factual, not analytical) that asserts the tool is NOT invoked. (3) Add latency budget — if pit-loss extraction takes > 2 s, return a degraded result with a clear message. | All three. (1) and (2) ship in Phase 1; (3) ship if latency tests show issues. Surface to user post-ship if the tool gets invoked > 30 % of the time on non-strategy prompts. |
| **F20 training data sufficiency** — Heilmeier 2020b used ~500 k simulated races. Our F15 engine generates ~1 race/second; producing 500 k races is ~6 days of compute. Acceptable, but only if F15 is deterministic enough that scaling up doesn't compound noise. | Pre-F20 build | (1) Wait for F15 Phase 3 (lap-time noise) before generating data — gives us a richer distribution. (2) Generate from F15 Phase 1 (deterministic) and accept narrower coverage. (3) Hybrid — half deterministic, half noisy. | (1). F20 cannot start until F15 Phase 3 ships; this is the gating dependency. Surface to user when F15 Phase 3 ships: "F20 is now unblocked; do we want to start it?" |
| **F20 hyperparameter sweep cost** — full sweep across FFNN+LSTM ensemble is GPU-heavy; F1Dash has no GPU budget. | F20 build start | (1) Use a smaller architecture (single FFNN, no LSTM) and accept worse accuracy. (2) Use Colab/Kaggle free tier for training, ship checkpoint only. (3) Skip F20 entirely; keep F15 deterministic-only. | (2). Cloud-free-tier training is fine for a one-time model; weights ship in repo or via release artifact. Surface to user at F20 start: "training will happen on Colab/Kaggle; inference is CPU and fast." |

## Commit Plan (Phase 1)

Small commits, one task per commit on average:

1. `feat: add get_actual_pit_loss and strategy snapshot helpers in f1_data`
2. `feat: add strategy_math module with compute_undercut_window`
3. `feat: add analyze_undercut_overcut tool and chat widget builder`
4. `feat: add UndercutOvercutWidget React component and renderer case`
5. `feat: add CIRCUIT_SC_PROBABILITY table and get_safety_car_prior`
6. `feat: add get_safety_car_outlook tool and SafetyCarOutlookWidget`
7. `feat: add VSC/SC pit-loss variants in strategy_math`
8. `feat: wire active_sc_state into undercut snapshot via race-control messages`
9. `chore: update system prompt with strategy-question routing rules`
10. `test: add hand-rolled scenarios for undercut/overcut math`

F20 has no commits in this plan — it's deferred. Its commit plan ships with its own follow-up plan after F15 Phase 3.

## References (Consolidated)

- Heilmeier, Graf, Lienkamp (2018). *A Race Simulation for Strategy Decisions in Circuit Motorsports.* IEEE ITSC 2018. DOI 10.1109/itsc.2018.8570012. — Pit-stop model § III.B.
- Heilmeier, Graf, Betz, Lienkamp (2020a). *Application of Monte Carlo Methods to Consider Probabilistic Effects in a Race Simulation for Circuit Motorsport.* Applied Sciences 10(12):4229. — VSC/SC pit-loss fractions.
- Heilmeier, Thomaser, Graf, Betz (2020b). *Virtual Strategy Engineer: Using ANNs for Race Strategy Decisions.* Applied Sciences 10(21):7805. — F20 baseline architecture.
- Fieni, Pivetta, Mongelluzzo et al. (2025). *Towards Learning-Based Formula 1 Race Strategies.* arXiv:2512.21570. — F20 MINLP+RL extension.
- Sulsters (2018). *Simulating Formula One Race Strategies.* MSc Thesis, VU Amsterdam. — Fresh-tyre-pace modelling.
- Bernie Collins (Sky F1) — undercut math and SC pit-loss commentary 2023–2025.
- Axiora racing analytics — historical SC priors.
- Companion plan: `2026-05-19-counterfactual-race-simulation.md` — consumes F16's pit-loss and F19's variants in its Phase 3.
- Companion plan: `2026-05-15-tire-cliff-detection.md` — produces deg curves F16 consumes.
- Sibling plan: `2026-05-19-data-currency-coverage.md` — F18's circuit table should be cross-checked against F7's audit before ship.
