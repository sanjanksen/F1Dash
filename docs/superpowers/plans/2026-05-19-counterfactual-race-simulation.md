# Counterfactual Race Simulation (F15+) Implementation Plan

> Status: not started. Estimated effort: 5–6 weeks of focused work.

## Goal

Build a post-race counterfactual simulator that answers chat questions of the form *"What would have happened if driver X had pitted on lap Y?"* / *"What if X had switched to mediums instead of hards?"* / *"What if X had stayed out under the lap-30 VSC?"*

The output is a deterministic finishing-order projection plus an optional confidence band, derived from real race data with reactive rival behaviour. This is the **F15+** approach (counterfactual replay with reactive opponents), chosen explicitly over pure F15 (rivals frozen — gives wrong answers on big changes) and over full Monte Carlo F17 (overkill for a post-race tool, harder to explain in chat).

## Background

This plan was decided after a long conversation that established three viable approaches:

| Approach | Rivals react? | Uncertainty modeled? | Output | Verdict |
|---|---|---|---|---|
| F15 — pure counterfactual replay | No | No | One number | Rejected — misleading on any change a rival would have noticed. |
| **F15+ — reactive counterfactual** | Yes (rule-based) | No (or light: lap-time noise only) | One number, defensible; optional confidence band | **This plan.** |
| F17 — full Monte Carlo | Yes (rule-based) | Yes (SC timing, retirements, all sampled) | Distribution | Deferred. Build later if "was this lucky?" questions become common. |

Key insight: we are **not building a race simulator from scratch**. The canonical open-source engine is `TUMFTM/race-simulation` (Heilmeier et al., TU München, MIT-licensed on GitHub). It already implements lap-discretized simulation with reactive "ghost car" rivals, fuel + tire submodels, and an overtaking model. Our work is:

1. Adapt their predictive simulator into a **post-race counterfactual** wrapper (freeze knowns, vary one decision).
2. Feed it real race data from `FastF1` plus the per-stint deg curves the cliff-detection feature now produces.
3. Expose it via a new chat tool and widget.

## Architecture

```
Existing F1Dash:
  server/chat.py (agentic loop)
    → server/tools.py (tool registry)
       → server/f1_data.py (FastF1 wrappers, deg fitting, cliff detection)
       → server/race_sim.py (NEW — counterfactual simulator)
          → vendored or pip-installed TUMFTM/race-simulation (engine)
  client/src/components/chat-widgets/
    → CounterfactualWidget.jsx (NEW)
```

Module boundaries:

- **`server/race_sim.py`** — new. Owns the adapter layer. Pure Python, no FastAPI dependencies. Takes a `RaceSnapshot` + `Decision` change → returns a `CounterfactualResult`. All FastF1 access happens via injected functions so the module is testable with mocks.
- **`server/tools.py`** — add one new tool: `simulate_counterfactual`.
- **`server/chat.py`** — add `_make_counterfactual_widget()` builder; update `SYSTEM_PROMPT` with guidance on when to invoke the simulator and how to interpret results.
- **`server/f1_data.py`** — minor additions: build a `RaceSnapshot` from a session (extract pace baselines, gaps lap-by-lap, actual pit stops, SC events). Most logic already exists.
- **`client/src/components/chat-widgets/CounterfactualWidget.jsx`** — new widget. Position-over-time chart comparing actual vs counterfactual lines for affected drivers; results table; rival-reaction summary.
- **`client/src/components/AnswerRenderer.jsx`** — add `counterfactual` case.

No changes to the resolver are required at planning time; the LLM picks the new tool from the system prompt.

## Engine Decision: Vendor vs Wrap

`TUMFTM/race-simulation` is a research codebase. Two viable integration paths:

- **Path A — vendor a subset.** Copy the lap-time model, tire submodel, fuel submodel, and overtaking model into `server/race_sim_engine/`. Strip the strategy-search and Monte Carlo wrappers we don't need yet. Lower long-term maintenance risk; easier debugging; matches F1Dash's no-deep-dependencies style.
- **Path B — pip install or git submodule.** Use as-is.

**Recommendation: Path A.** The Heilmeier code is well-documented MATLAB/Python, but it's optimised for *predictive* strategy search, not post-race forensics. Vendoring the bits we need and rewriting their `race()` wrapper as a counterfactual driver gives us cleaner control. We will preserve attribution headers and license notices per MIT terms.

**Open question to resolve in Phase 0:** verify TUMFTM/race-simulation's current license at integration time. If it has moved away from MIT, fall back to a clean-room implementation guided by the Heilmeier 2018 paper.

## Key Data Inputs (all derivable from existing code)

| Input | Source | Notes |
|---|---|---|
| Per-driver per-stint deg slope (and cliff fields) | `_fit_stint_degradation()` in `f1_data.py` | Already implemented. Cliff fields land with the 2026-05-15 plan. |
| Per-driver pace baseline | Median lap time of stint minus fuel & deg | Compute in `race_sim.py` setup. |
| Per-circuit fuel coefficient | New constant table, ~24 entries (0.025–0.040 s/kg) | See [F10 in audit roadmap]. If not built yet, fall back to 0.03 constant; flag in widget. |
| Pit-loss (this race) | Median of actual stop durations in session + pit-lane delta | Already available via OpenF1 / FastF1. |
| Lap-by-lap gaps | Cumulative lap times | Already available via FastF1. |
| SC / VSC events | Race control messages | Already in FastF1; minor extraction work. |
| Overtaking probability per lap | Per-circuit calibration table (Monaco ~0.05/lap, Spa ~0.8/lap for 1 s/lap pace delta) | New static table. Calibrate from 5 seasons of historical data. Acceptable to ship V1 with hand-tuned values per circuit. |

## Rival-Reaction Rules (Phase 1: deterministic)

Implemented in `race_sim.py` as a small rules engine. All thresholds are configurable.

- **Cover-undercut rule:** if a driver within 3.0 s of the focal driver pits, the focal driver pits on the next lap with probability 1.0. (Probability becomes a sampling target in Phase 3.)
- **Extend-overcut rule:** if the focal driver has > 5 laps of usable tyre life left and the rival behind has just pitted onto a colder tyre, focal driver stays out 2–3 additional laps.
- **Track-position priority:** on low-overtake circuits (`overtake_difficulty == "high"` in `circuit_profiles.py`), reactions are immediate (within 1 lap). On high-overtake circuits, allow a 2-lap delay.
- **Pit-window collision:** if pitting drops the focal driver into traffic ≥ 0.5 s/lap slower for ≥ 3 laps, delay one lap.
- **Don't double-cover:** if a rival has already pitted to cover within the last 3 laps, suppress further reactions.

These rules are the editorial heart of the simulator. They will be wrong some of the time. The widget must clearly state which rules fired, so the user can override them in a follow-up question ("ignore the cover rule").

## User-Facing Output (target)

Chat response:

> *"If Norris had pitted on lap 28 instead of lap 30, Russell would likely have reacted by lap 29 (within the 3 s cover-undercut window). Norris rejoins ahead of Russell. With the fresher tyres, his lap-30→45 stint averages 0.4 s/lap faster than reality. Net result: he finishes P2 instead of P3 — Piastri ahead is unaffected because the gap at the point of decision was 18 s."*

Widget: position-over-time chart with actual race as solid lines, counterfactual as dashed lines for affected drivers. Below the chart, a "rules fired" panel ("Cover-undercut: Russell pitted lap 29"). A small results table: actual finish → counterfactual finish per affected driver.

---

## Phased Task Breakdown

Each phase is shippable on its own. Phase 1 is the MVP. Phases 2–4 are progressive enhancements.

### Phase 0 — Engine integration (1 week)

- [ ] Read `TUMFTM/race-simulation` README and core modules; confirm current license.
- [ ] Decide vendor-vs-pip (default: vendor per Path A above).
- [ ] Create `server/race_sim_engine/` with vendored modules (`lap_time.py`, `tire_model.py`, `fuel_model.py`, `overtaking.py`, `ghost_car.py`). Include attribution + MIT license header.
- [ ] Smoke test: feed it a synthetic race and verify it produces sensible lap times.
- [ ] Acceptance: `python -m race_sim_engine.smoke` produces a 50-lap, 5-driver race in under 200 ms.

### Phase 1 — MVP counterfactual (2 weeks)

- [ ] New file `server/race_sim.py` with:
  - `build_race_snapshot(year, round, session_type) -> RaceSnapshot` — extracts pace baselines, deg curves, gaps, pit stops, SC events from FastF1.
  - `apply_decision(snapshot, decision) -> CounterfactualResult` — applies one change (different pit lap, different compound, skip-pit-under-SC) and runs the engine forward from that lap.
  - `ReactionRules` class implementing the five rules above; configurable thresholds.
- [ ] New tool definition `simulate_counterfactual` in `server/tools.py`:
  - Args: `driver_code`, `decision_type` (one of `pit_earlier`, `pit_later`, `swap_compound`, `stay_out_under_sc`), `decision_value` (lap number or compound name), optional `year`, `round`.
  - Returns: full `CounterfactualResult` dict.
- [ ] Executor branch in `execute_tool()`.
- [ ] Widget builder `_make_counterfactual_widget()` in `server/chat.py`.
- [ ] System prompt update: when to invoke the new tool, how to phrase results, mandatory inclusion of "rules fired" caveats.
- [ ] New React widget `CounterfactualWidget.jsx`:
  - Position-over-time chart (actual solid, counterfactual dashed).
  - Results table.
  - Rules-fired panel.
- [ ] `AnswerRenderer.jsx` case.
- [ ] Tests in `server/tests/test_race_sim.py`:
  - Snapshot extraction from a known race produces expected gaps and pit stops.
  - Pit-earlier decision triggers cover-undercut rule.
  - Pit-later decision on stale tyres widens the gap.
  - Same-compound swap does nothing useful (sanity).
  - Engine output is deterministic given fixed inputs.

**Acceptance:** chat question *"What if Piastri had pitted one lap later in the 2025 Hungarian GP?"* returns a CounterfactualWidget with a coherent narrative.

### Phase 2 — Quality polish (1 week)

- [ ] Per-circuit fuel coefficient table (~24 entries) replacing 0.03 constant.
- [ ] Per-circuit overtaking probability table calibrated against the last 5 seasons.
- [ ] Rule-firing transparency: every rule firing produces a human-readable line ("Russell pitted lap 29 to cover").
- [ ] User-overridable rules via natural language: *"What if Piastri had pitted lap 28 and Russell hadn't reacted?"* → resolver detects the constraint and disables `cover-undercut` for Russell.
- [ ] Widget improvements: highlight the decision point on the chart; tooltip on each line showing per-lap pace.

### Phase 3 — Lap-time noise (F17-light, 1 week)

- [ ] Add per-driver per-stint lap-time noise sampling (Gaussian, σ from observed stint residuals).
- [ ] Run 100 samples; report:
  - P50 counterfactual finish position
  - Range of finish positions (P10 → P90)
  - Probability of strategy improving finish vs reality
- [ ] Widget gets a small confidence band around the counterfactual lines.
- [ ] System prompt: how to phrase probabilistic results ("78% of sims have Norris finishing P2 or better").

**Acceptance:** chat question *"Was Norris's 2-stop the right call in Hungary?"* returns a comparison between actual and the 1-stop alternative with P50/P90 finishes for both.

### Phase 4 — Full F17 (deferred, 3+ weeks)

Only build if user feedback shows real demand for "was this lucky?" / "what's the optimal strategy in expectation" questions. Adds:

- [ ] Sampled SC timing per circuit (Poisson with per-circuit priors).
- [ ] Sampled retirement probability per driver.
- [ ] Sampled pit-stop duration (truncated normal).
- [ ] Probabilistic rival reactions instead of deterministic.
- [ ] 1000-sample runs with proper distribution outputs.

This phase essentially mirrors Heilmeier 2020a (Applied Sciences 10:4229). Could become a real-time strategy advisor if expanded with live-data ingestion — but that's a different product positioning.

---

## Risks and Open Questions

These need answers before, during, or after the build. Surfacing per the user's risk-management protocol.

| Risk | When it triggers | Proposed resolution | Decision needed by |
|---|---|---|---|
| TUMFTM repo license has changed | Phase 0 | If not MIT-compatible, fall back to clean-room implementation from Heilmeier 2018 paper. ~2 extra weeks. | Phase 0 start |
| Rival reaction rules feel wrong to F1-literate users | After Phase 1 ships | Make rules user-overridable in chat (Phase 2). Document them in a `/about` view. | Post-Phase 1 |
| Overtaking model produces unrealistic results on specific circuits | After Phase 1 ships | Add circuit-specific overtaking calibration in Phase 2. Allow user to override via "no overtakes will happen" follow-up. | Post-Phase 1 |
| Deg curves from cliff-detection are too noisy to project forward 15+ laps | Phase 1 testing | Use cliff-pre slope when projecting beyond the cliff age is risky; flag in widget. Allow user to disable cliff in counterfactual. | Phase 1 |
| Phase 3 lap-time noise σ is mis-estimated | Phase 3 | Fall back to a conservative σ (~0.2 s/lap) and document the assumption. | Phase 3 |
| LLM mis-invokes the tool for non-counterfactual questions | Phase 1 | System prompt must be explicit: only invoke when user uses "what if", "would have", "had X", or counterfactual framing. Add deflection rule for predictive questions. | Phase 1 |
| Compute time per counterfactual exceeds chat-acceptable latency | Phase 1 | Target < 3 s per counterfactual. Heilmeier engine is fast (1000 sims in ~10 s); a single counterfactual should be < 100 ms. If not, profile and optimize. | Phase 1 |

---

## Validation Checklist

- [ ] Engine integration produces sensible lap times for a known historical race.
- [ ] `RaceSnapshot` extraction from FastF1 matches actual race results within ±0.5 s cumulative time across 50 laps.
- [ ] Reactive rules fire correctly in unit tests for each of the five rules.
- [ ] Counterfactual on a no-op decision (e.g., pit on the exact same lap) returns the actual race within tolerance.
- [ ] System prompt routes counterfactual questions to the new tool, not to `analyze_race_pace_battle` or `get_race_story`.
- [ ] Widget renders for at least 3 distinct decision types (`pit_earlier`, `pit_later`, `swap_compound`).
- [ ] User-overridable rules work via follow-up question phrasing.
- [ ] All existing tests still pass.
- [ ] Counterfactual response time is < 3 s end-to-end (chat → tool → engine → widget).
- [ ] Attribution and license headers preserved in vendored Heilmeier code.

## References

- Heilmeier, Graf, Lienkamp (2018). *A Race Simulation for Strategy Decisions in Circuit Motorsports.* IEEE ITSC 2018. DOI 10.1109/itsc.2018.8570012.
- Heilmeier, Graf, Betz, Lienkamp (2020). *Application of Monte Carlo Methods to Consider Probabilistic Effects in a Race Simulation for Circuit Motorsport.* Applied Sciences 10(12):4229.
- Heilmeier, Thomaser, Graf, Betz (2020). *Virtual Strategy Engineer: Using ANNs for Race Strategy Decisions.* Applied Sciences 10(21):7805.
- Sulsters (2018). *Simulating Formula One Race Strategies.* MSc Thesis, VU Amsterdam.
- Bekker, Lotz (2009). *Planning Formula One race strategies using discrete-event simulation.* J. Operational Research Society.
- Fieni et al. (2025). *Towards Learning-Based Formula 1 Race Strategies.* arXiv:2512.21570.
- `TUMFTM/race-simulation` — GitHub. Reference open-source implementation.
- Companion document: `2026-05-15-tire-cliff-detection.md` — produces the deg curves this simulator consumes.
