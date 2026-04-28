# SC Impact Enrichment, FP Summary Tool, Speed Trap Leaderboard — Design Spec

## Overview

Three independent backend features to give the LLM richer, pre-digested data for race strategy, free practice, and straight-line speed questions.

---

## Feature 1: SC/VSC Impact Enrichment

### Problem
`get_safety_car_periods` already captures three timing buckets (`pitted_just_before`, `pitted_before_extended`, `pitted_during`) and `strategic_crossings` pairs. But the LLM has to do arithmetic from raw seconds to conclude "Kimi was a victim." The victim/beneficiary conclusion should be pre-computed.

### Design

**Add to each period object:**
- `period_narrative: str` — one ready-to-use sentence summarising who was hurt and who benefited from this specific period. Example: `"SafetyCar lap 28: HAM pitted 18s before it; BOT and VER got free stops under it, directly disadvantaging HAM whose fresh-tyre gap was wiped out."`

**Add to top-level return dict:**
- `all_victims: list[dict]` — deduplicated list of every driver disadvantaged across all SC/VSC periods. Fields: `driver`, `sc_type`, `sc_lap`, `seconds_before_sc`, `mechanism` (`"pitted_just_before"` or `"pitted_before_extended"`).
- `all_beneficiaries: list[dict]` — deduplicated list of every driver who got a free or near-free stop. Fields: `driver`, `sc_type`, `sc_lap`, `mechanism` (`"free_stop"`).

**No new tool, no new route.** `get_safety_car_periods` already has a resolver scope (`safety_car`) and is baked into `get_driver_race_story` (as `safety_car_full`) and `get_race_report` (as `safety_car`). The LLM just reads the pre-computed fields instead of doing timing math.

---

## Feature 2: Free Practice Summary Tool

### Problem
FP sessions are mixed-program sessions: installation laps, setup/balance runs, long race-pace stints, and quali simulations all coexist in the same data. Raw lap times mean nothing without knowing what fuel load and programme type a driver was on. No FP-specific tool exists.

### Design

**New function:** `get_fp_summary(round_number: int, fp_number: int) -> dict`

`fp_number` is 1, 2, or 3. Maps to session_type `FP1`/`FP2`/`FP3`.

**Per-driver output:**
- `stints: list` — each stint has `classification`, `compound`, `fresh_tyre`, `laps`, `start_lap`, `end_lap`, `best_lap_s`, `avg_lap_s`
- `best_lap_time`, `best_lap_time_s`, `best_lap_compound` — overall fastest clean lap
- `speed_st` — speed trap on that best lap
- `long_run_count`, `quali_sim_count`, `compounds_used`

**Stint classification rules (applied in order):**
1. `installation` — first lap of stint when `PitOutTime` is set AND it's the first stint of the session (lap 1 area)
2. `long_run` — 8+ consecutive laps on the same compound with green track status → race pace sim
3. `quali_sim` — 1–2 laps on a fresh soft/medium tyre with the driver's fastest session time on that stint
4. `short_run` — everything else (setup work, balance runs, tyre assessment)

**Top-level `session_notes` array** — pre-written caveats the LLM must embed naturally:
- Fuel load is not measured by FastF1 — long runs are heavier fuel than race
- FP times not directly comparable to qualifying times
- Installation laps excluded from pace comparisons
- Quali-sim laps are the closest to single-lap pace

**New tool registered in `tools.py`:** `get_fp_summary` as a PRIMITIVE TOOL.

**Resolver scope:** `"fp"` scope — triggered by FP1/FP2/FP3/free practice keywords. Routes to `get_fp_summary`. Suggested tool args derive `fp_number` from the matched session token.

**System prompt addition:** A `## Free Practice interpretation` section in `ANALYSIS_SYSTEM_PROMPT` explaining how to read the classified stints and what conclusions can and cannot be drawn.

---

## Feature 3: Speed Trap Leaderboard

### Problem
Fans frequently ask "who had the highest top speed in qualifying?" FastF1 exposes four speed trap columns on every lap: `SpeedST` (main straight), `SpeedFL` (finish line), `SpeedI1` (intermediate 1), `SpeedI2` (intermediate 2). `get_session_fastest_laps` returns these only for each driver's fastest lap, missing cases where a driver's peak trap speed came on a different lap (e.g., with a slipstream, or an early push lap before track evolved).

### Design

**New function:** `get_speed_trap_leaderboard(round_number: int, session_type: str) -> dict`

Scans **all laps** for every driver. Finds peak speed at each trap independently (a driver's fastest SpeedST may be on lap 5, their fastest SpeedFL on lap 12). Returns four ranked lists, one per trap.

**Each entry:** `driver`, `team`, `speed_kph`, `lap_number`, `compound`, `rank`

**Return shape:**
```json
{
  "event": "...",
  "session": "Q",
  "trap_labels": {
    "speed_st": "Speed Trap (main straight)",
    "speed_fl": "Finish Line",
    "speed_i1": "Intermediate 1",
    "speed_i2": "Intermediate 2"
  },
  "speed_st": [...ranked by descending speed_kph],
  "speed_fl": [...],
  "speed_i1": [...],
  "speed_i2": [...]
}
```

**New tool registered in `tools.py`:** `get_speed_trap_leaderboard` as a PRIMITIVE TOOL.

**Resolver scope:** `"speed_trap"` scope — triggered by "top speed", "speed trap", "fastest straight", "drag", "straight-line speed", "speed down the straight" keywords. Routes deterministically to `get_speed_trap_leaderboard`.

---

## Files Modified

| File | Change |
|------|--------|
| `server/f1_data.py` | Add `period_narrative`, `all_victims`, `all_beneficiaries` to `get_safety_car_periods`; add `get_fp_summary`; add `get_speed_trap_leaderboard` |
| `server/tools.py` | Register `get_fp_summary` and `get_speed_trap_leaderboard`; add dispatch branches in `execute_tool` |
| `server/resolver.py` | Add `"fp"` scope (FP keywords → `get_fp_summary`); add `"speed_trap"` scope (top speed keywords → `get_speed_trap_leaderboard`); add `_suggested_tool_args` handling for both |
| `server/chat.py` | Add `## Free Practice interpretation` section to `ANALYSIS_SYSTEM_PROMPT`; update `_suggested_tool_args` for `get_fp_summary` and `get_speed_trap_leaderboard` |
| `server/tests/test_f1_data.py` | Tests for all three new behaviours |
| `server/tests/test_resolver.py` | Tests for new resolver scopes |
