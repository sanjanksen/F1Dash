# Data Currency & Coverage Refresh (F3–F7) Implementation Plan

> Status: not started. Estimated effort: 3–4 days of focused editorial + code work.

## Goal

Bring F1Dash's static reference data and editorial knowledge up to date for the **2026 season** so chat answers stop quoting wrong regulation numbers, missing drivers, missing teams, and stale calendar assumptions. Today is **2026-05-19**; the 2026 season is mid-way through (roughly 8 of ~24 rounds run), and most existing static data was written against the 2024/2025 grid.

Scope:

- **F3** — Fix `server/energy_2026.py` regulation numbers (8.5 → 7 MJ/lap recovery) and add structured deployment-curve fields.
- **F4** — Add 2026 rookies and seat-movers to the resolver's alias hint block.
- **F5** — Expand `server/driver_styles.py` to cover the full 2026 grid, with explicit confidence + source-date metadata on weakly-evidenced rookie entries.
- **F6** — Expand `server/team_car_profiles.py` to cover all 10 teams (currently 5).
- **F7** — Audit `server/circuit_profiles.py` against the 2026 calendar; add a version stamp.

This plan delivers the **long-form refresh**: re-sourced editorial content, structured metadata, and audit hooks for future re-verification. The companion plan `2026-05-19-backend-support-bugfixes.md` (items #8–11) ships the minimum-correctness patch for the same surfaces — that plan exists to unblock release-day chat answers; this plan replaces those patches with durable, well-sourced content.

## Architecture

No new modules, no schema changes. Five static dicts and one regex/alias hint block are edited in place. All consumers of the affected modules already accept partial data — adding new entries cannot break existing callers.

```
server/energy_2026.py        ← F3: rule numbers + new structured fields
server/resolver.py           ← F4: alias hint block in _extract_entities_llm()
server/driver_styles.py      ← F5: add ~8 rookie/mover profiles, confidence flags
server/team_car_profiles.py  ← F6: add 5 missing team profiles
server/circuit_profiles.py   ← F7: audit + CALENDAR_YEAR/LAST_VERIFIED stamps
```

Callers verified to be additive-safe:

- `get_energy_2026_knowledge()` returns the whole dict — new keys are passively forwarded; old callers ignore them.
- `DRIVER_STYLES.get(code)` returns `None` for unknown drivers — adding keys is strictly additive.
- `TEAM_CAR_PROFILES.get(team_name.lower())` likewise.
- The resolver's Haiku prompt is appended via f-string; new alias lines just become more hints for Haiku.

---

## Reference Data Verification — Do This At Implementation Time

Static F1 data ages fast. Before writing any code below, **re-verify the grid, calendar, and team list against three sources** in this order:

1. **Live FastF1 / Jolpica via existing code:**
   - `f1_data.get_drivers()` — pulls current-season driver list from FastF1; this is what the resolver itself caches.
   - `f1_data.get_circuits()` — pulls current-season calendar.
   - Run these from a Python shell inside `server/` (`python -c "from f1_data import get_drivers; print(get_drivers())"`) and **paste the output into the relevant code comment** so future maintainers can spot drift.
2. **Jolpica-Ergast as canonical reference:**
   - `GET http://api.jolpi.ca/ergast/f1/2026/drivers.json` — full driver list with constructors.
   - `GET http://api.jolpi.ca/ergast/f1/2026.json` — full 2026 race schedule.
   - Use these to confirm seat assignments where FastF1 lags (early-season substitutions, reserve-driver appearances).
3. **One editorial source per driver style / team profile entry:**
   - Acceptable: Sky F1 (skysports.com/f1), The Race (the-race.com), Autosport, RaceFans, BBC F1, Motorsport.com.
   - **Not acceptable as sole source:** Reddit, Wikipedia, fan forums.
   - Record the URL and access date in the profile entry's `source_url` / `source_date` field so reviewers can re-verify.

**Decision rule on conflicts:** if FastF1 disagrees with Jolpica on a seat assignment, prefer Jolpica (more frequently updated for in-season swaps) and add an inline comment noting the discrepancy.

**Open-question handling:** for any 2026 grid spot or calendar slot still labelled "TBC" or contradicted across sources at implementation time, add the profile with `confidence: "low"` and `notes: "unverified at 2026-05-19; recheck after round N"`. **Do not silently guess.**

---

## Task 1 (F3) — Fix `energy_2026.py` Regulation Numbers and Add Deployment Curve

Files:

- Modify: `server/energy_2026.py`
- Test: `server/tests/test_chat.py` (light — check `get_energy_2026_knowledge()` shape)

### Change Description

The current `known_facts` list quotes **"about 8.5 MJ per lap of energy recuperation"**. The finalised 2026 FIA spec — agreed in the December 2024 refinements — is **7 MJ/lap** recovery. Fix the number and the surrounding wording.

Then add a new structured field `deployment_curve` to the top-level `ENERGY_2026_KNOWLEDGE` dict, giving the assistant ready-to-quote numbers instead of forcing it to paraphrase prose:

```python
"deployment_curve": {
    "full_power_kw": 350,
    "full_power_below_kmh": 290,
    "ramp_zero_at_kmh": 355,
    "ramp_description": (
        "350 kW available up to 290 km/h, then linear ramp down to 0 kW at 355 km/h. "
        "Above 355 km/h the MGU-K contributes no propulsive power."
    ),
},
"override_mode": {
    "full_power_kw": 350,
    "extended_full_power_below_kmh": 337,
    "availability": "Only within 1.0 s of the car ahead (DRS-style proximity gate).",
    "description": (
        "Override mode raises the deployment-taper threshold from 290 to 337 km/h, "
        "extending full 350 kW deployment deeper into the straight."
    ),
},
"zone_caps": {
    "key_zone_kw": 350,
    "elsewhere_kw": 250,
    "key_zone_definition": "Corner-exit acceleration zones and designated overtake zones.",
    "notes": "Outside these zones the FIA-imposed deployment cap is 250 kW.",
},
"battery_storage_cap_mj": 4.0,
"super_clip_target": {
    "max_seconds_per_lap": (2, 4),
    "description": (
        "Teams target 2–4 s of super-clipping per lap as an upper budget; anything more "
        "implies undersized battery management or poor harvest planning."
    ),
},
```

Update `known_facts`:

- Change the 8.5 MJ/lap line to: *"The 2026 rules target about 7 MJ per lap of energy recuperation under braking (final FIA-agreed figure after late-2024 refinements; earlier drafts cited ~8.5 MJ)."*
- Add: *"MGU-K deployment is shaped by a defined power curve: 350 kW up to 290 km/h, ramping linearly to 0 kW at 355 km/h, with an override mode extending the 350 kW window up to 337 km/h when within 1 s of the car ahead."*
- Add: *"Outside designated key-acceleration / overtake zones, deployment is capped at 250 kW."*

Update `interpretation_rules` so clipping diagnosis references the curve:

- Add: *"A driver whose speed trace flattens between roughly 290 and 355 km/h is consistent with the normal deployment ramp, not necessarily a clipping problem — distinguish curve-driven taper from genuine super-clipping."*
- Add: *"Super-clipping shows up as a flattened trace **before** the 290 km/h threshold and/or as a fade that lasts longer than 2–4 s per lap."*

### Acceptance Criteria

- `python -c "from energy_2026 import get_energy_2026_knowledge as g; k = g(); print(k['deployment_curve']['full_power_kw'])"` prints `350`.
- Searching for the string `8.5 MJ` in `server/energy_2026.py` returns zero matches.
- `get_energy_2026_knowledge()` still returns a dict with the original keys (`known_facts`, `terms`, `interpretation_rules`, `limitations`, `answer_rules`) — adding new keys does not remove old ones.
- A chat question *"what's the energy recovery target for 2026?"* in the agentic loop should now answer **7 MJ/lap** with a one-line reference to the late-2024 refinement.

### Cross-Reference

The bugfix-plan item #8 only flips the 8.5 → 7 number. This task delivers the deployment-curve structure on top.

---

## Task 2 (F4) — Add 2026 Drivers/Movers to Resolver Alias Hints

Files:

- Modify: `server/resolver.py` — the alias hint block currently spanning lines 86–94 inside `_extract_entities_llm()`.

### Change Description

Add 2026 rookie and seat-mover aliases to the Haiku system prompt. **Verify every seat against `get_drivers()` and Jolpica at implementation time** (see Verification section). The names below are the assignments believed correct on **2026-05-19** — confirm before writing.

Replace the alias hint block with (subject to verification):

```text
Common aliases to resolve:
- Prancing Horse / Scuderia / SF-xx → Ferrari
- Silver Arrows / the stars / Brackley → Mercedes
- Milton Keynes / RB21 → Red Bull
- Woking / papaya → McLaren
- Enstone → Alpine    |  Grove → Williams    |  Faenza → RB / Racing Bulls
- Hinwil / Stake / Audi works team → Audi (Sauber rebrand for 2026)
- Max / Mad Max → VER  |  Lando → NOR  |  Yuki → TSU
- Carlos → SAI  |  George → RUS  |  Lewis → HAM (now at Ferrari)  |  Charles → LEC
- Oscar → PIA  |  Fernando / Alonso → ALO  |  Lance → STR
- Kimi (Antonelli, not Räikkönen) → ANT  |  Ollie / Bearman → BEA
- Liam / Lawson → LAW  |  Isack / Hadjar → HAD
- Gabriel / Bortoleto → BOR  |  Jack / Doohan → DOO
- Franco / Colapinto → COL
```

Notes:

- The "Lewis → HAM (now at Ferrari)" hint **must** be present so Haiku doesn't infer "Lewis = Mercedes" from training data.
- The "Kimi (Antonelli, not Räikkönen)" disambiguator is load-bearing: the LLM otherwise resolves "Kimi" to RAI from old context.
- "RB21" is the 2026 Red Bull chassis designation (verify — could be "RB22" depending on the team's numbering convention).

### Sweep For Hardcoded Outdated Seats

Grep the entire `server/` tree for stale driver/team pairings:

```bash
# from server/, expected: zero matches except in comments
rg -i "hamilton.*mercedes|lewis.*mercedes|mercedes.*hamilton" --type py
rg -i "perez|checo|PER" --type py
rg -i "sargeant|zhou|bottas|hulkenberg|magnussen|ricciardo" --type py
```

For any non-comment match, either delete (if the line is dead code) or update (if still live).

### Acceptance Criteria

- The resolver's alias hint contains all 8 new/changed drivers (ANT, BEA, LAW, HAD, BOR, DOO, COL, plus the corrected Lewis-at-Ferrari hint and the Kimi disambiguator).
- A test prompt *"How did Antonelli's race go?"* through `resolve_query()` extracts `drivers=["ANT"]` (assuming `get_drivers()` returns him).
- No occurrence of `Lewis → HAM` paired with "Mercedes" outside explicitly dated historical commentary.
- `rg "RB20" server/` returns zero matches in non-comment code (or all such matches are replaced with the current chassis designation).

### Cross-Reference

The bugfix-plan item #9 adds the 8 driver codes as the minimum patch. This task additionally sweeps for hardcoded Lewis-at-Mercedes references and tightens the Kimi disambiguator.

---

## Task 3 (F5) — Fill Out `driver_styles.py` for Full 2026 Grid

Files:

- Modify: `server/driver_styles.py`

### Change Description

For each driver in the verified 2026 grid (~20 drivers) not currently in `DRIVER_STYLES`, add a profile entry following the existing dict structure. Required keys per profile:

- `full_name`
- `steering_style` — `"smooth" | "measured" | "aggressive"`
- `corner_approach` — `"v_line" | "u_line" | "balanced"`
- `braking_style` — `"late_aggressive" | "early_settle" | "balanced"`
- `apex_style` — `"late" | "standard" | "early"`
- `throttle_style` — `"early_explosive" | "gradual" | "measured"`
- `car_preference` — `"oversteer" | "understeer" | "balanced"`
- `setup_preference` — short string
- `corner_philosophy` — 2–4 sentence narrative
- `key_traits` — list of 3–6 short bullets
- `telemetry_signature` — 1–2 sentence description of what their data looks like
- `weakness` — single sentence
- `wet_weather` — single sentence

### New Metadata Fields (all new entries, optional on existing entries)

Add two new fields used to gate downstream LLM language:

```python
"confidence": "low" | "medium" | "high",
"editorial_source_date": "2026-05-19",
"editorial_sources": [
    {"name": "Sky F1", "url": "...", "accessed": "2026-05-19"},
    {"name": "The Race", "url": "...", "accessed": "2026-05-19"},
],
```

Confidence guidance:

- **high** — driver has 2+ full F1 seasons; multiple published technical analyses exist (VER, NOR, HAM, LEC, etc. — leave existing entries unchanged, optionally tag them `confidence: "high"` for symmetry).
- **medium** — second-season driver or a first-year driver with at least 5 race weekends of run-publishable telemetry (likely ANT, BEA, LAW, HAD by 2026-05-19).
- **low** — rookies with limited data (likely BOR, DOO, COL depending on which seats are confirmed; verify).

### Chat Layer Integration Note

The chat layer (`server/chat.py`) currently injects driver-style profiles into the agentic context without confidence gating. After this task, **chat.py should hedge when `confidence == "low"`**:

> *"Limited data on this driver's style — based on F2 form and early 2026 weekends, …"*

That chat-layer hedge is a small follow-up edit, not part of this task. Flag it as a downstream change so the new confidence metadata is actually consumed.

### Skeleton Profile Template For Rookies

For a rookie with thin published telemetry, the minimum acceptable profile is:

```python
"BOR": {
    "full_name": "Gabriel Bortoleto",
    "steering_style": "smooth",       # F2 trait; recheck after 5 F1 weekends
    "corner_approach": "balanced",
    "braking_style": "balanced",
    "apex_style": "standard",
    "throttle_style": "measured",
    "car_preference": "balanced",
    "setup_preference": "stable_platform",  # placeholder until F1 telemetry sample exists
    "corner_philosophy": (
        "F2 2024 champion known for clean, low-error race craft and good tyre "
        "management. Early 2026 sessions suggest a measured approach typical of "
        "first-year drivers; specific F1-level style signatures still developing."
    ),
    "key_traits": [
        "Clean inputs, low error rate",
        "Strong tyre management in F2",
        "Early-2026 telemetry sample still small",
    ],
    "telemetry_signature": "Insufficient F1 data; treat any style claim cautiously.",
    "weakness": "Limited published F1 telemetry as of 2026-05-19.",
    "wet_weather": "F2 wet performances strong; F1 sample limited.",
    "confidence": "low",
    "editorial_source_date": "2026-05-19",
    "editorial_sources": [
        {"name": "<verify at implementation>", "url": "...", "accessed": "2026-05-19"},
    ],
},
```

### Acceptance Criteria

- `DRIVER_STYLES` contains an entry for every driver code returned by `f1_data.get_drivers()` on 2026-05-19. Verify with:

  ```python
  from f1_data import get_drivers
  from driver_styles import DRIVER_STYLES
  missing = [d["code"] for d in get_drivers() if d["code"] not in DRIVER_STYLES]
  assert missing == [], f"Missing style profiles: {missing}"
  ```

- Every new entry contains all required keys (validation can be a single-line schema check at module import; not mandatory, but useful).
- Every rookie/mover entry has `confidence != "high"` and a non-empty `editorial_sources` list with at least one URL.

### Cross-Reference

The bugfix-plan item #10 ships minimal placeholder stubs (1-line philosophies) for missing drivers. This task replaces those stubs with researched, sourced entries.

---

## Task 4 (F6) — Fill Out `team_car_profiles.py` for Missing Teams

Files:

- Modify: `server/team_car_profiles.py`

### Change Description

The current module covers Ferrari, Mercedes, Aston Martin, Red Bull, Haas. Add the five missing teams using the existing format (`team`, `profile_type`, `last_reviewed`, `confidence`, `summary`, `traits`, `caveat`).

Teams to add (verify each name against `get_drivers()` `team` field):

- **McLaren** — championship contender. Largest miss; deterministic team-circuit-fit analysis breaks without it.
- **Alpine** — Enstone outfit; verify driver lineup (DOO + COL/GAS?).
- **Williams** — Grove; SAI joined for 2025+.
- **RB / Racing Bulls** — Faenza junior team; LAW + HAD likely lineup.
- **Audi (Sauber rebrand)** — Hinwil; Audi works team from 2026; BOR likely + teammate.

For each, follow the existing structure:

```python
"mclaren": {
    "team": "McLaren",
    "profile_type": "curated_editorial",
    "last_reviewed": "2026-05-19",
    "confidence": "medium",
    "summary": "<1-2 sentence character — e.g., 'High-downforce reference platform with peerless slow- to medium-speed grip; recent reporting flags occasional tyre-overheating on long stints at high-energy circuits.'>",
    "traits": [
        {
            "trait": "<short_id_string>",
            "status": "reported_strength | reported_limitation | mixed | historical_tendency",
            "note": "<1-2 sentence excerpt or paraphrase, with attribution>",
            "source": "<publication>",
            "source_url": "<URL>",
        },
        # 2-4 traits ideal
    ],
    "caveat": "<one sentence reminder that this is dated editorial context>",
},
```

### Sourcing Rules

- At least one trait per team must come from a 2025–2026 published source (not pre-2024).
- For Audi specifically: clearly note this is the Sauber rebrand, and that the 2026 power unit is the team's debut Audi-built unit — early-season form may not reflect long-term competitiveness.
- Confidence:
  - **medium** for McLaren and Williams (established teams, current reporting plentiful).
  - **low** for Audi (rebrand year, limited 2026-specific reporting) and possibly Alpine if their 2026 form is volatile.

### Caveat Wording

The `caveat` field is what the chat layer surfaces alongside team analysis. Keep it crisp:

> *"Treat as dated editorial context. Verify against current telemetry — Audi's 2026 power-unit debut means early-season form is not yet predictive."*

### Acceptance Criteria

- `TEAM_CAR_PROFILES` contains lower-cased keys for all 10 current teams. Verify:

  ```python
  from f1_data import get_drivers
  from team_car_profiles import TEAM_CAR_PROFILES
  teams = {d["team"].lower() for d in get_drivers()}
  missing = teams - set(TEAM_CAR_PROFILES.keys())
  assert missing == set(), f"Missing team profiles: {missing}"
  ```

- Each new entry has ≥1 trait with a 2025-or-later `source_url`.
- The deterministic `team_circuit_fit` path (in `chat.py`) successfully injects a profile for every team — no silent fall-through to "no team profile available".

### Cross-Reference

Bugfix-plan item #11 ships single-trait stubs for the 5 missing teams. This task replaces those stubs with multi-trait sourced profiles.

---

## Task 5 (F7) — Audit `circuit_profiles.py` Against 2026 Calendar; Add Version Stamp

Files:

- Modify: `server/circuit_profiles.py`

### Change Description

Add at the top of the module (after the docstring, before `CIRCUIT_PROFILES`):

```python
CALENDAR_YEAR = 2026
LAST_VERIFIED = "2026-05-19"
```

Then audit `CIRCUIT_PROFILES` against the 2026 calendar from `f1_data.get_circuits()`. The nominal 2026 calendar is 24 races. Items to verify and reconcile:

| Circuit | 2025 status | 2026 expected | Action |
|---|---|---|---|
| Madrid (Madring) | Not on 2025 cal | **Confirmed for 2026** | Add new profile if missing. |
| Imola | Dropped 2025 | Uncertain 2026 (rotating?) | Verify against Jolpica; leave entry but mark `active_in_2026: false` if dropped. |
| Spa (Belgian GP) | On 2025 | **Rotating with Imola** — verify status | Add `rotation_partner: "imola"` field. |
| Shanghai (Chinese GP) | On 2025 | On 2026 — confirm | No action if present. |
| Zandvoort | On 2025 | Final-year contract — verify | Mark expected last year if confirmed. |
| Las Vegas / Miami / Austin | On 2025 | On 2026 | Confirm. |

### New Per-Profile Metadata Fields (Optional But Recommended)

For each existing profile, add:

```python
"last_reviewed": "2026-05-19",
"active_in_2026": True,   # or False if the circuit is off the calendar
"calendar_notes": "<optional, e.g. 'Rotating with Imola; runs in 2026 only.'>",
```

Drift detection (informational — not a hard test):

```python
# at module bottom
def _audit_calendar_drift():
    """Run manually; returns circuits in CIRCUIT_PROFILES not on the live 2026 calendar."""
    from f1_data import get_circuits
    live = {c["event_name"].lower() for c in get_circuits()}
    return [
        name for name, profile in CIRCUIT_PROFILES.items()
        if profile.get("active_in_2026") and name not in live
    ]
```

### Madrid Profile Skeleton (If Confirmed Present)

```python
"madrid": {
    "circuit_name": "Madring (IFEMA Madrid)",
    "character": "medium_speed_technical_with_street_section",
    # ... fill in sector_1/2/3 from FIA / promoter published track map
    "energy_profile": {
        "deployment_demand": "<verify>",
        "harvesting_opportunity": "<verify>",
        "clipping_risk": "<verify>",
        ...
    },
    "downforce_level": "<verify>",
    "narrative": "<2-3 sentences from Madring promoter / Sky F1 / The Race preview>",
    "last_reviewed": "2026-05-19",
    "active_in_2026": True,
    "calendar_notes": "First running in 2026.",
},
```

### Acceptance Criteria

- `CALENDAR_YEAR` and `LAST_VERIFIED` constants exported from `circuit_profiles.py`.
- `from circuit_profiles import CALENDAR_YEAR; assert CALENDAR_YEAR == 2026` passes.
- For every circuit on `get_circuits()`'s 2026 list, `CIRCUIT_PROFILES` has a key (case-insensitive match by event country or circuit slug).
- The `_audit_calendar_drift()` helper returns `[]` after the audit pass.

### Cross-Reference

This is **not** covered by the bugfix plan — F7 is exclusive to this long-form refresh.

---

## How To Verify 2026 Driver / Team / Calendar Data At Implementation Time

This section is operational. Run it before writing code for Tasks 2–5.

### Step 1 — Pull Live Data From The App's Own Sources

From `server/`:

```python
# verify_2026.py (throwaway script, do not commit)
from f1_data import get_drivers, get_circuits

print("=== Drivers (FastF1, 2026 season) ===")
for d in get_drivers():
    print(f"  {d.get('code'):4} {d.get('full_name'):28} {d.get('team')}")

print("\n=== Circuits (FastF1, 2026 season) ===")
for c in get_circuits():
    print(f"  R{c.get('round'):>2} {c.get('event_name'):32} {c.get('circuit_name')}  {c.get('country')}")
```

Run: `cd server && python verify_2026.py`. Save the output for reference while editing the static dicts.

### Step 2 — Cross-Reference With Jolpica-Ergast

```bash
curl -s "http://api.jolpi.ca/ergast/f1/2026/drivers.json" | python -m json.tool
curl -s "http://api.jolpi.ca/ergast/f1/2026.json"        | python -m json.tool
```

Note any **discrepancy** between FastF1 and Jolpica. Common causes:

- Reserve-driver substitutions (e.g., a one-race injury fill-in) — Jolpica updates faster.
- Sprint-format inclusion — both should agree, but verify if uncertain.

**Conflict rule:** prefer Jolpica; add an inline `# NOTE: FastF1 shows X, Jolpica shows Y — preferring Jolpica` comment in the static file.

### Step 3 — Editorial Source Per Style/Car Profile

For each new `driver_styles.py` and `team_car_profiles.py` entry, find **one** published 2025–2026 article and record:

- Publication name (Sky F1, The Race, Autosport, RaceFans, BBC F1, Motorsport.com)
- URL
- Access date (always `2026-05-19` for this batch)

Reject sources that are:

- Wikipedia (use only as a navigation hub, not a citation).
- Reddit / forums.
- Fan-blog speculation.
- Published before 2025-01-01 for current-season claims.

### Step 4 — Sanity Check By Spinning A Chat Question

End-to-end sanity check after editing:

```bash
cd server && uvicorn main:app --reload --port 8000
# in another shell:
curl -s -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Tell me about Antonelli'\''s driving style"}' | python -m json.tool
```

Expected: response mentions Mercedes (not "no team profile"), and either quotes the new style profile or hedges per the `confidence: "low"` flag.

---

## Validation Checklist

- [ ] **F3** — `server/energy_2026.py` no longer contains `8.5 MJ`; new `deployment_curve`, `override_mode`, `zone_caps`, `battery_storage_cap_mj`, `super_clip_target` keys are present and well-typed.
- [ ] **F3** — `interpretation_rules` references the 290 / 355 / 337 km/h thresholds.
- [ ] **F3** — `get_energy_2026_knowledge()` callers still work (existing tests pass).
- [ ] **F4** — All 8 new driver codes (ANT, BEA, LAW, HAD, BOR, DOO, COL, plus TSU at correct 2026 team) appear in the resolver's alias hint block.
- [ ] **F4** — `rg -i "lewis.*mercedes|mercedes.*lewis"` returns zero non-comment matches in `server/`.
- [ ] **F4** — `rg "RB20"` returns zero non-comment matches in `server/` (current chassis designation used instead).
- [ ] **F5** — `DRIVER_STYLES` covers every driver code returned by `get_drivers()`.
- [ ] **F5** — Every new style entry has `confidence`, `editorial_source_date`, and `editorial_sources` fields populated.
- [ ] **F6** — `TEAM_CAR_PROFILES` covers all 10 teams currently on the grid.
- [ ] **F6** — Every new team profile has ≥1 trait with a 2025-or-later `source_url`.
- [ ] **F7** — `CALENDAR_YEAR = 2026` and `LAST_VERIFIED = "2026-05-19"` exported.
- [ ] **F7** — `_audit_calendar_drift()` returns `[]`.
- [ ] **F7** — Madrid profile present if confirmed on 2026 calendar.
- [ ] All existing server tests pass: `cd server && python -m pytest tests/ -v`.
- [ ] One end-to-end chat smoke test for a rookie driver returns a coherent answer.

---

## Risks and Open Questions

| Risk | When it triggers | Proposed resolution | Decision needed by |
|---|---|---|---|
| **Mid-season transfer invalidates a freshly written profile** | Any time between this work and the next refresh | Stamp every entry with `editorial_source_date`; build the `_audit_calendar_drift()` and equivalent driver-drift helpers so a future "rerun the audit" task can spot stale entries in minutes. Surface the staleness explicitly in chat replies (`confidence: "low"`). | Pre-implementation |
| **Rookie style profiles will be wrong** | Throughout 2026 — rookie styles evolve as drivers gain experience | Tag rookies `confidence: "low"` and force the chat layer to hedge. Schedule a refresh after every ~5 rounds (next checkpoint: round 13, roughly 2026-07). | Pre-implementation |
| **FastF1 / Jolpica disagree on a seat** | Implementation time | Prefer Jolpica; add inline comment recording the disagreement. If both are unclear, mark profile `confidence: "low"` and skip until the next refresh. | Implementation |
| **Audi power-unit debut produces volatile form** | Any 2026 race | Tag Audi profile `confidence: "low"`; caveat explicitly mentions the PU debut year. Do not claim long-term competitiveness from sample of <8 races. | Pre-implementation |
| **Belgian GP / Imola rotation** | If 2026 calendar drops one mid-year | Add `rotation_partner` field on both profiles; the `_audit_calendar_drift()` helper accepts either as valid for 2026. | Implementation |
| **7 MJ/lap number turns out to be wrong** | If a late-2025 FIA regulation update revised it again | Source the number from the current FIA technical regulations PDF, not journalistic summaries. Record the regulation version in a comment. If the number changes again, the structured `deployment_curve` is the load-bearing claim — `known_facts` text is paraphrased context. | F3 implementation |
| **Chat layer doesn't yet read the new `confidence` field** | After F5/F6 ship | Out of scope here but flagged as a downstream follow-up: `chat.py` should hedge driver/team claims when `confidence == "low"`. Open a follow-up issue, do not block this PR. | Post-merge |
| **"Kimi" disambiguation regresses** | If Haiku still resolves "Kimi" to RAI | Verify the disambiguator works with a unit-test-style prompt during implementation: `resolve_query({"message": "Kimi's pace today"})` should return `ANT`, not `RAI`. | F4 implementation |
| **Reserve / sub-driver appearances mid-season** | Any race | Resolver alias block only carries primary drivers. Reserve-driver substitutions (e.g., injury fills) are not handled here; rely on `get_drivers()` runtime data for resolution accuracy. | Acceptance — known limitation |

### Refresh Cadence

Build a **simple operational habit** off the back of this plan: re-run the verification script (Step 1 above) every ~5 race weekends and bump `LAST_VERIFIED` in `circuit_profiles.py` plus `editorial_source_date` on any updated driver/team entries. Calendar checkpoints for 2026:

- After round 13 (~mid-July 2026)
- After round 18 (~September 2026)
- End-of-season post-Abu-Dhabi sweep (December 2026) — also stamp 2027 prep work.

---

## Commit Plan

Small, reviewable commits:

1. `fix: correct 2026 energy recovery target to 7 MJ/lap and add deployment curve` (F3)
2. `feat: add 2026 rookies and seat-movers to resolver alias hints` (F4)
3. `feat: expand driver_styles to cover full 2026 grid with confidence metadata` (F5)
4. `feat: expand team_car_profiles to cover all 10 2026 teams` (F6)
5. `feat: add CALENDAR_YEAR stamp and audit circuit_profiles against 2026 calendar` (F7)

Each commit independently passes `python -m pytest tests/ -v`. Do not bundle.
