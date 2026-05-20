# 2026-Regulation Telemetry Features (F31–F33) Implementation Plan

> Status: not started. Estimated effort: 2.5–3 weeks, phased.

## Goal

Build three telemetry analysis features that only exist because of the 2026 power-unit and aero regulations. Each feature surfaces an aspect of car behaviour with no pre-2026 analog that today's `f1_data.py` heuristics cannot recognise.

Scope:

- **F33 — Deployment-curve-aware clipping detection.** Identify the flat-throttle / flat-speed signature of a driver running out of MGU-K push between 290 and 355 km/h. Surfaces in `qualifying_battle` and energy widgets. *Ships first.*
- **F32 — Override-mode boost detection.** Identify the 1-second-gap-triggered extension of full 350 kW deployment from 290 to 337 km/h. Surfaces in race-story narratives.
- **F31 — Active aero (X-mode / Z-mode) analysis.** Detect Z-mode (low-drag) state per circuit on designated aero straights. New tool + widget. *Ships last.*

Out of scope: harvest tracking (already in `energy_2026.py`), battery SOC reconstruction (not derivable from FastF1), counterfactual clipping simulation (see `2026-05-19-counterfactual-race-simulation.md`).

## Prerequisite — REQUIRED Before Any F31/F32/F33 Code

**Depends on `2026-05-19-data-currency-coverage.md` Task 1 (F3).** That task fixes `server/energy_2026.py` to expose structured `deployment_curve`, `override_mode`, and `zone_caps` fields with **7 MJ/lap** recovery (not 8.5) and **290 / 337 / 355 km/h** thresholds. Every detector here reads those numbers as the single source of truth.

If F3 has not landed: F33 thresholds diverge from the editorial layer; F32 checks the wrong upper bound; `interpretation_rules` hedging contradicts the detector output. **Block this plan on F3.** F33 can fall back to hard-coded FIA constants if F3 is delayed, but the import path is strongly preferred so a future refinement updates both layers at once.

Primary sources: FIA 2026 Power Unit Technical Regulations PDF (cite version inline); Formula1.com Dec 2024 refinements article (recovery target ~8.5 → 7 MJ).

## Architecture

```
server/
  energy_2026.py          ← (prereq F3) source of truth for thresholds
  active_aero.py          ← NEW (F31) — Z-mode detection, per-circuit straight defs
  f1_data.py              ← (F32, F33) — detect_override_mode(), detect_clipping_signature()
  tools.py                ← F31: analyze_active_aero_usage  |  F32: analyze_override_usage
  chat.py                 ← widget builders, system-prompt updates
client/src/components/chat-widgets/
  ActiveAeroWidget.jsx    ← NEW (F31)
  EnergyManagementWidget.jsx  ← UPDATE (F33) — clipping segment overlay
  QualifyingBattle.jsx    ← UPDATE (F33) — clipping callout text
  SpeedTrace.jsx          ← UPDATE (F32) — optional override-segment overlay
client/src/components/AnswerRenderer.jsx  ← register active_aero widget type
```

- **`server/active_aero.py`** is new and self-contained. No imports from `f1_data.py` (would cycle).
- **`server/f1_data.py`** gains two public helpers (`detect_clipping_signature`, `detect_override_mode`) following the precedent of `_infer_clipping_windows()` at L236.
- Both new tools go in `PRIMITIVE_TOOL_DEFINITIONS` since they answer narrow factual questions; the agentic loop pairs them with existing composite recap tools.

---

## Data Availability — What FastF1 Does and Does Not Expose

**Reliable channels (today):** `Speed`, `Throttle`, `Brake`, `Gear`, `RPM`, `Distance`, and (pre-2026) `DRS`. In 2026 the `DRS` channel may persist vestigially, be repurposed for active-aero, or be removed — **probe at implementation time** via `session.laps.iloc[0].get_telemetry().columns` on a 2026 race session.

**Channels FastF1 does NOT expose (workarounds):**

| Signal | Workaround |
|---|---|
| MGU-K state of charge | Infer clipping from speed-trace flattening 290–355 km/h while throttle = 100 % (F33). |
| Deployment-map identifier | Cannot infer. Chat must hedge — never claim a specific deployment map caused a clipping event. |
| Override-mode active flag | Speed-trace shape + cumulative-timing gap-to-ahead < 1.0 s (F32). |
| Active-aero state (X / Z) | Prefer repurposed `DRS` channel if present; else infer from speed-slope on aero straights (F31). |
| Battery storage cap (4 MJ) | Out of scope — detectors operate on observed telemetry, not predicted state. |

**Schema-drift workaround:** probe columns at module import; log the set in a `# NOTE:` comment in `active_aero.py`; missing column → inference path. Every detector returns a degraded-but-valid result, never crashes. Test fixtures: extend `conftest.py` stubs with synthetic 2026-style frames covering (a) clipping, (b) override, (c) Z-mode.

---

## Calibration — Validating Detectors Against Real 2026 Data

### Calibration corpus

Curate from the first 8 rounds of 2026. Ground-truth sources: **team radio transcripts** (OpenF1, already in `server/openf1.py`) for "out of battery" / "no boost" / "no overtake"; **post-race technical analyses** (Sky F1, The Race, AMuS) naming specific laps; **FIA stewards' documents** when deployment-map issues are mentioned.

Store at `server/tests/fixtures/calibration_2026.json`:

```json
{
  "clipping_events": [
    {"round": 4, "driver": "NOR", "lap": 28, "straight": "kemmel", "source": "Sky F1 post-race 2026-04-21"}
  ],
  "override_events": [
    {"round": 6, "driver": "VER", "lap": 14, "target": "PIA", "straight": "main", "source": "F1 TV radio"}
  ],
  "z_mode_events": [
    {"round": 7, "driver": "LEC", "lap": 9, "straight": "back", "source": "AMuS 2026-05-12"}
  ]
}
```

### Calibration test

`cd server && python -m pytest tests/test_calibration.py -v -m "calibration_2026"`.

`tests/test_calibration.py` iterates the fixture, calls each detector against real session data, asserts the detector flags the same lap as the editorial source. **Acceptance: ≥ 70 % agreement before merge.** Below 70 %, raise detector thresholds (false-negative bias) until precision is acceptable. Record the result in the PR description.

**Small-corpus fallback** (< 3 reference events for a feature, likely in mid-2026): ship with `confidence: "low"`, force chat hedging (*"model suggests clipping consistent with the deployment curve, but the calibration sample is small as of mid-2026"*), schedule recalibration after round 13 (mid-July) and round 18 (September).

---

## Task 1 (F33) — Deployment-Curve-Aware Clipping Detection

**Ships first.** Reuses speed-trace and full-throttle-window infrastructure already in `f1_data.py` (`_find_full_throttle_straight_windows`, `_infer_clipping_windows` around L216–272).

### Files

- Modify: `server/f1_data.py` — new public `detect_clipping_signature()` and `compare_drivers_clipping()` helpers near the existing `_infer_clipping_windows()`.
- Modify: `server/chat.py` — pass clipping-segment data into `_make_qualifying_battle_widget()` and `_make_energy_management_widget()`.
- Modify: `server/tools.py` — extend `get_telemetry_comparison` tool description.
- Modify: `client/src/components/chat-widgets/EnergyManagementWidget.jsx` — clipping segment overlay.
- Modify: `client/src/components/chat-widgets/QualifyingBattle.jsx` — clipping callout text.
- Add tests: `server/tests/test_f1_data.py::TestDetectClippingSignature`.

### Helper signature

```python
def detect_clipping_signature(
    speed_trace: list[float],
    throttle_trace: list[float],
    distance_trace: list[float],
    *,
    drs_state: list[int] | None = None,
    full_power_below_kmh: float = 290.0,
    ramp_zero_at_kmh: float = 355.0,
    min_segment_length_m: float = 80.0,
    min_speed_flatten_kph: float = 8.0,
) -> dict:
    """Return clipping segments where speed flattens despite full throttle in the
    deployment-taper window (290–355 km/h). Defaults read from
    energy_2026.get_energy_2026_knowledge()['deployment_curve'] at module import time.
    """
```

Algorithm:

1. Identify full-throttle straight windows via `_find_full_throttle_straight_windows(samples)`.
2. Within each window, segment into deployment-taper sub-windows: contiguous samples where `290 ≤ speed ≤ 355` and `throttle ≥ 95`.
3. For each sub-window: compute observed speed slope (`d_speed / d_distance`); compare against reference slope from a hard-coded piecewise lookup of the FIA deployment curve.
4. If observed slope is ≥ 50 % below reference, classify the segment as clipping.
5. Aggregate clipping seconds across the lap.

Return shape:

```python
{
  "clipping_detected": bool,
  "segments": [
    {"start_distance_m": float, "end_distance_m": float,
     "start_speed_kph": float, "end_speed_kph": float,
     "observed_slope_kph_per_m": float, "reference_slope_kph_per_m": float,
     "duration_s": float, "severity": "mild" | "moderate" | "severe"},
  ],
  "total_clipping_seconds": float,
  "budget_status": "within" | "above",        # vs 2–4 s super-clip target
  "confidence": "low" | "moderate" | "high",
  "detector_version": "f33-v1",
}
```

Confidence: **high** ≥ 2 segments, each ≥ 50 m, slope deficit ≥ 60 %. **moderate** 1 strong segment, or 2+ marginal. **low** single short segment, or sample-to-sample variance > 10 km/h.

### Comparison helper

```python
def compare_drivers_clipping(
    driver_a_signature: dict, driver_b_signature: dict,
    driver_a_code: str, driver_b_code: str,
) -> dict | None:
    """Return chat-ready summary when one driver clips materially more.
    Threshold: difference ≥ 0.2 s/lap to be worth surfacing. Else None.
    """
```

Return (or `None`):

```python
{"faster_driver": "PIA", "clipping_driver": "NOR", "delta_seconds": 0.4,
 "phrase": "Norris clipped roughly 0.4 s/lap on the main straight; Piastri did not.",
 "segment_reference": {"start_distance_m": 1480, "end_distance_m": 1620}}
```

### Widget updates

- `EnergyManagementWidget.jsx`: semi-transparent red bands over the speed trace for each clipping segment. Legend chip: "Clipping (deployment taper)". `total_clipping_seconds` metric below the chart, styled by `budget_status` (gray within, amber above).
- `QualifyingBattle.jsx`: below the speed-trace overlay, append the `phrase` from `compare_drivers_clipping` when present. Render nothing when both drivers' clipping is within budget.

### Acceptance Criteria

- `detect_clipping_signature(clean_trace)` returns `clipping_detected=False`.
- `detect_clipping_signature(clipped_trace)` returns ≥ 1 segment with `severity ∈ {moderate, severe}` and `total_clipping_seconds > 0.3`.
- Thresholds are read from `energy_2026.get_energy_2026_knowledge()['deployment_curve']`; if F3 missing, tests fail loudly.
- `compare_drivers_clipping(matched_pair)` returns `None`; asymmetric pair returns dict with `delta_seconds ≥ 0.2`.
- Existing widget snapshots still render. Missing throttle channel → degraded but non-crashing render.
- Calibration: detector flags ≥ 70 % of `clipping_events` fixtures.
- Run: `cd server && python -m pytest tests/test_f1_data.py::TestDetectClippingSignature -v` and `cd client && npm run build`.

### References

- FIA 2026 Power Unit Technical Regulations (cite version inline).
- Formula1.com, *"2026 power unit refinements"*, December 2024.
- `2026-05-19-data-currency-coverage.md` Task 1.
- Precedent: `server/f1_data.py:236` (`_infer_clipping_windows`).

---

## Task 2 (F32) — Override-Mode Boost Detection

Ships second. Adds gap-aware detection of the 290→337 km/h extension. Surfaces in race-story narratives.

### Files

- Modify: `server/f1_data.py` — new `detect_override_mode()` helper.
- Modify: `server/tools.py` — register `analyze_override_usage` primitive.
- Modify: `server/chat.py` — extend `get_driver_race_story` builder; update `SYSTEM_PROMPT`.
- Modify: `client/src/components/chat-widgets/SpeedTrace.jsx` — optional override-segment overlay.
- Add tests: `server/tests/test_f1_data.py::TestDetectOverrideMode`.

### Helper signature

```python
def detect_override_mode(
    lap_telemetry: list[dict],
    gap_to_ahead_trace: list[float],
    *,
    full_power_below_kmh: float = 290.0,
    override_extended_below_kmh: float = 337.0,
    gap_window_s: float = 1.0,
    min_segment_length_m: float = 60.0,
) -> dict:
    """Identify segments where override-mode boost (extended 350 kW above 290 km/h)
    was plausibly active. Defaults from energy_2026['override_mode'].
    """
```

Algorithm:

1. Candidate segments: contiguous samples where `290 ≤ speed ≤ 337`, `throttle ≥ 95`, `brake == 0`.
2. Gap-window check: `gap_to_ahead < 1.0 s` for ≥ 80 % of segment.
3. Slope vs reference: if observed slope is **steeper** than F33's deployment-taper reference (car still accelerating where it shouldn't be without override), flag.

Return shape:

```python
{
  "override_detected": bool,
  "segments": [
    {"start_distance_m": float, "end_distance_m": float,
     "peak_speed_kph": float, "gap_at_segment_s": float,
     "speed_gain_kph": float, "duration_s": float,
     "circuit_straight_label": str | None},
  ],
  "total_override_seconds": float,
  "confidence": "low" | "moderate" | "high",
  "detector_version": "f32-v1",
}
```

### Tool registration

`analyze_override_usage` (PRIMITIVE) — given `driver`, `round_number`, `session_type`, `lap_number`, returns per-segment distance, duration, peak speed, gap at trigger, total override seconds. Use for specific-lap questions; prefer `get_driver_race_story` for broad narratives. Mirror in `OPENAI_TOOL_DEFINITIONS`.

### Chat narrative integration

`get_driver_race_story` already builds a lap-by-lap narrative. After this task, when the story mentions an overtake, the builder calls `detect_override_mode` for the lap and threads the result:

> *"Verstappen overtook Piastri into Les Combes on lap 14 — the speed trace shows override boost active on the Kemmel straight, with the car still accelerating past 320 km/h while Piastri's trace flattens at 305."*

`SYSTEM_PROMPT` addition: *"When narrating 2026-season overtakes, mention override-mode use only when `total_override_seconds > 0.5` for the lap. Do not claim override use without that evidence — the 1-second-gap trigger is required."*

### Acceptance Criteria

- `detect_override_mode(override_speed_trace, gap_too_large)` returns `override_detected=False`.
- `detect_override_mode(override_speed_trace, gap_under_1s)` returns ≥ 1 segment with `peak_speed_kph > 310`.
- `analyze_override_usage` tool, called on a known 2026 overtake fixture, returns ≥ 1 segment for the attacker, 0 for the defender.
- `get_driver_race_story` narrative on a 2026 override lap mentions override boost in text.
- Calibration: ≥ 70 % of `override_events` fixtures flagged.
- Run: `cd server && python -m pytest tests/test_f1_data.py::TestDetectOverrideMode -v`.

### References

- FIA 2026 Power Unit Technical Regulations — override-mode definition.
- Formula1.com, *"2026 power unit refinements"*, December 2024 — confirms 337 km/h upper bound and 1-second proximity gate.
- `2026-05-19-data-currency-coverage.md` Task 1.
- Precedent: `server/f1_data.py:1864` (`get_telemetry_comparison`).

---

## Task 3 (F31) — Active Aero (X-mode / Z-mode) Analysis

Ships last. Builds new `active_aero.py` module, per-circuit aero-zone definitions, new tool, new widget. Highest editorial and data-availability risk.

### Files

- Add: `server/active_aero.py` — Z-mode detection, per-circuit aero-zone definitions.
- Modify: `server/tools.py` — register `analyze_active_aero_usage` primitive.
- Modify: `server/chat.py` — `_make_active_aero_widget()` builder.
- Add: `client/src/components/chat-widgets/ActiveAeroWidget.jsx`.
- Modify: `client/src/components/AnswerRenderer.jsx` — register `active_aero` widget type.
- Add tests: `server/tests/test_active_aero.py`.

### Module sketch

```python
# server/active_aero.py
"""2026 active-aero (X/Z) detection. X = high-drag default; Z = low-drag,
auto-activates on FIA-permitted straights. Heuristic — see is_z_mode() fallback."""

CIRCUIT_AERO_ZONES = {
    "spa-francorchamps": {
        "circuit_country": "Belgium",
        "zones": [
            {"label": "Kemmel",        "start_distance_m": 1900, "end_distance_m": 3100},
            {"label": "back_straight", "start_distance_m": 4800, "end_distance_m": 5600},
        ],
        "last_reviewed": "2026-05-19",
        "source": "<verify: FIA circuit map for 2026 Belgian GP>",
    },
    # ...one entry per 2026 calendar circuit (Monza, Madrid, Vegas, etc.).
}


def is_z_mode(
    speed_kph: float, distance_on_lap_m: float, circuit_slug: str,
    *, aero_state_channel: int | None = None,
) -> bool:
    """Path A (preferred) — if FastF1 surfaces an active-aero channel in 2026
    (likely repurposed DRS), pass aero_state_channel and return directly.
    Path B (fallback) — inside CIRCUIT_AERO_ZONES band, speed > 250 km/h, past
    the first 100 m of the zone (transition lag).
    """
```

Fallback will misfire on slow laps (false positives) and mid-zone lifts (false negatives). Widget must label inferred state when `aero_state_channel is None`.

### Tool registration

`analyze_active_aero_usage` (PRIMITIVE) — given `driver`, `round_number`, `session_type`, `lap_number`, returns Z-mode segments, total Z-mode seconds, estimated speed gain vs simulated X-mode, and `inferred: bool` when FastF1 doesn't expose the active-aero channel directly. Mirror in `OPENAI_TOOL_DEFINITIONS`.

### Widget

`ActiveAeroWidget.jsx`: overlay coloured spans on existing speed trace (green = Z-mode confirmed, amber = inferred). Sidebar: total Z-mode seconds, estimated lap-time delta vs full-X-mode, list of zones used. If `inferred=true`, prepend badge: *"inferred from speed-trace shape — active-aero channel not exposed by FastF1"*.

### Acceptance Criteria

- `is_z_mode(320, 2400, "spa-francorchamps")` returns `True`; `is_z_mode(120, 400, "monza")` returns `False`.
- `is_z_mode(300, 10, "spa-francorchamps", aero_state_channel=1)` returns `True` (Path A overrides).
- `CIRCUIT_AERO_ZONES` covers ≥ 80 % of 2026-calendar circuits (verify with `f1_data.get_circuits()`). Missing circuits → empty zones, detector returns `inferred=true` with zero confirmed zones — not an error.
- `analyze_active_aero_usage` returns dict with `total_z_mode_seconds`, `segments`, `inferred: bool`.
- New widget renders; `inferred` badge appears when expected.
- Calibration: ≥ 70 % of `z_mode_events` fixtures flagged.
- Run: `cd server && python -m pytest tests/test_active_aero.py -v` and `cd client && npm run build`.

### References

- FIA 2026 Sporting & Technical Regulations — active-aero (X/Z) definitions, per-circuit zone declarations.
- Formula1.com, *"How 2026 active aero replaces DRS"*, 2025 (verify URL).
- Sky F1 / The Race / Autosport — per-circuit zone reporting at start of 2026.
- `server/circuit_profiles.py` — existing per-circuit metadata; cross-link in comments, do not duplicate.

---

## Phasing and Sequencing

| Phase | Task | Reason for order |
|---|---|---|
| Prereq | `data-currency-coverage` F3 | Single source of truth for thresholds. |
| 1 | **F33** clipping | Reuses speed-trace plumbing; largest calibration corpus; zero new modules. |
| 2 | **F32** override | Reuses F33's reference-slope lookup; new tool, no new widget file. |
| 3 | **F31** active aero | Highest data-availability risk; new module + widget. Best last so F33/F32 channel probing has already established what 2026 FastF1 exposes. |

Each phase is independently shippable. F31 widget renders even if F33 overlay hasn't landed; F32's tool registers without the widget changes. Do not bundle.

---

## Validation Checklist

- [ ] **Prereq** — `energy_2026.get_energy_2026_knowledge()['deployment_curve']` returns dict with `full_power_kw=350`, `full_power_below_kmh=290`, `ramp_zero_at_kmh=355`.
- [ ] **F33** — `detect_clipping_signature()` lives in `f1_data.py`, reads thresholds from `energy_2026`, returns documented shape.
- [ ] **F33** — Clean / clipped / noisy synthetic traces give expected verdicts.
- [ ] **F33** — `compare_drivers_clipping()`: `None` for matched pairs, populated dict for asymmetric pairs.
- [ ] **F33** — `EnergyManagementWidget.jsx` renders segment overlay; degraded data does not break the widget.
- [ ] **F33** — `QualifyingBattle.jsx` surfaces the phrase only when `delta_seconds ≥ 0.2`.
- [ ] **F33** — Calibration: ≥ 70 % of `clipping_events` flagged.
- [ ] **F32** — `detect_override_mode()` returns `False` when gap > 1.0 s, even for matching speed-trace shape.
- [ ] **F32** — `analyze_override_usage` registered in Anthropic + OpenAI tool definitions.
- [ ] **F32** — `get_driver_race_story` narrative mentions override on a 2026 fixture lap.
- [ ] **F32** — Calibration: ≥ 70 % of `override_events` flagged.
- [ ] **F31** — `active_aero.py` exists; `CIRCUIT_AERO_ZONES` covers ≥ 80 % of 2026 calendar.
- [ ] **F31** — `is_z_mode()` returns documented results for spec test inputs.
- [ ] **F31** — `analyze_active_aero_usage` registered.
- [ ] **F31** — `ActiveAeroWidget.jsx` renders; `inferred` badge appears when FastF1 doesn't expose the channel.
- [ ] **F31** — Calibration: ≥ 70 % of `z_mode_events` flagged.
- [ ] All existing server tests pass: `cd server && python -m pytest tests/ -v`.
- [ ] Client builds: `cd client && npm run build`.
- [ ] End-to-end smoke: a 2026 race question that should trigger override narrative produces text mentioning override boost.

---

## Risks

| Risk | Trigger | Proposed solutions (ranked) | Recommendation |
|---|---|---|---|
| **Pre-2026 FastF1 schemas omit new 2026 channels** (active aero, override flag, deployment-map ID) | F31 column probe | (1) Inference-only fallback with `inferred=true`. (2) Block features behind schema-version check. (3) Skip F31 until FastF1 ships 2026-aware release. | **(1)** — every detector already has an inference path. Comment the probe result so future FastF1 releases can flip to direct reads. |
| **Calibration corpus too small** (< 3 events) | Feature whose editorial corpus is thin | (1) Ship with `confidence: "low"` and force chat hedging. (2) Defer until round 13 / 18 recalibration. (3) Ship without calibration. | **(1)** — `confidence` flag already in the detector return shape. |
| **F3 prereq not landed** | F33 day 1 | (1) Block all three features on F3. (2) Hard-code thresholds with `# TODO`. (3) Ship F3 inline (scope creep). | **(1)** — F3 is small and scoped elsewhere. Surface the dependency at planning time. |
| **Reference slope lookup is wrong** (FIA curve non-linear in reality) | F33 / F32 calibration < 70 % | (1) FIA piecewise approximation. (2) Empirically fit reference from "known clean" 2026 laps in the corpus. (3) Percentile detector — flag bottom-decile slopes in the deployment window. | **(1) then (2)** — start with FIA piecewise; fit empirically if still off. Percentile is last resort. |
| **Override detection misfires when DRS-replacement flag is reused for Z-mode** | F32 if FastF1 emits a 2026 `DRS`-style channel meaning "Z-mode active" | Probe-time disambiguation: if flag fires when gap > 5 s on a long straight, it's Z-mode not override. Add disambiguation logic in `detect_override_mode`. | Probe and disambiguate during F31; F32 reads the *disambiguated* channel. |
| **Per-circuit aero-zone definitions drift** | Mid-season layout changes (Madrid first running, Imola/Spa rotation) | Stamp each zone entry with `last_reviewed`; add `_audit_aero_zones()` mirroring `circuit_profiles._audit_calendar_drift()`. | Add audit helper in F31; schedule recheck at round 13 and 18. |
| **Override-narrative LLM hallucination** (mentions override on a lap where it didn't fire) | F32 chat phase | System prompt forbids mentioning override without `total_override_seconds > 0.5`; widget builder assertion strips the phrase if tool disagrees. | Belt and braces — both. |
| **DRS channel deprecation surprises** | F31 if FastF1 emits vestigial `DRS` flag with stale 2024 meaning | Probe at import; check whether values look 2024-like (DRS-zone on/off) or 2026-like (Z-mode on aero zones). Log verdict. | Do not silently trust. Inference path is the safer default until verification is recorded. |

---

## Commit Plan

1. *(prereq, separate plan)* `fix: correct 2026 energy recovery target to 7 MJ/lap and add deployment curve`.
2. `feat: add 2026 clipping-signature detector reading deployment curve` (F33 server).
3. `feat: surface clipping overlay in energy and qualifying widgets` (F33 client).
4. `feat: add 2026 override-mode boost detector` (F32 server).
5. `feat: thread override narrative into race-story and speed trace` (F32 chat + client).
6. `feat: add active_aero module with per-circuit Z-mode zones` (F31 server + tool).
7. `feat: render ActiveAeroWidget with inferred-state badge` (F31 client).
8. `chore: add calibration_2026.json fixture and test_calibration.py harness`.

Each commit independently passes `cd server && python -m pytest tests/ -v` and `cd client && npm run build`. Do not bundle.

---

## Refresh Cadence

- After round 13 (~mid-July 2026) — expand calibration fixture, re-run 70 % bar.
- After round 18 (~September 2026) — second recalibration; if any detector dropped below 70 %, treat as a bug.
- End-of-season — final pass; archive corpus as the 2026 reference.

Bump `detector_version` strings (`"f33-v1"`, etc.) on any algorithmic change so historical chat answers trace back to the detector version that produced them.

---

## Assumptions

- FastF1 will continue exposing `Speed`, `Throttle`, `Brake`, `Distance` on 2026 race sessions. If it does not, all three features are blocked — but the broader app is also broken, so it would already be a known emergency.
- 2026 active-aero state is either exposed as a repurposed `DRS` channel or as a new column. This plan documents the probe step but does not assume which.
- Per-circuit aero-zone definitions are publicly documented on FIA circuit maps for 2026 events; verification at implementation time sources them per circuit.
- Team-radio transcripts via OpenF1 remain available for 2026 races (already integrated in `server/openf1.py`).
