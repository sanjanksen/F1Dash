# Backend Support-Module Bug Fixes Implementation Plan

> Status: not started. Estimated effort: 1.5–2 weeks of focused work.

## Goal

Fix a batch of bugs and stale-data issues across the backend support modules (`energy_2026.py`, `resolver.py`, `openf1.py`, `driver_styles.py`, `team_car_profiles.py`, `circuit_profiles.py`). These modules feed Claude verbatim context — when they go stale or inconsistent, the assistant produces confidently wrong answers, asymmetric driver comparisons, and 500s when external APIs blip.

This plan is the **minimum-viable correction** pass: enough to stop the active bleeding. A follow-up "data currency refresh" feature plan (not yet written) will do the long-form rebuild of editorial content (full 2026 driver profiles, all team cars, sourced telemetry traits). Where the two overlap, this plan stays conservative — stub entries marked `confidence: low` or `editorial: draft` — so the chat layer can hedge until the feature plan upgrades them. Items #8, #9, #10, #11 are the bug-plan side of that overlap.

## Architecture

All work is contained in `server/`. No client or test infrastructure changes beyond adding tests in `server/tests/`.

| Module | Change kind |
|---|---|
| `server/energy_2026.py` | Replace stale `known_facts`, add `deployment_curve`, `override_mode`, `battery_storage`. Preserve `get_energy_2026_knowledge()` dict shape. |
| `server/resolver.py` | Add 2026 driver aliases, TTL the circuit cache, tighten reference-language detection, delegate circuit matching to `circuit_profiles.py`. |
| `server/openf1.py` | Add timeout + retry helper. Delete the redundant `_cached_circuits()` and import from `resolver.py` (or shared module). |
| `server/driver_styles.py` | Add stub profiles for the missing 2026 grid drivers with `confidence: low`. |
| `server/team_car_profiles.py` | Add skeleton entries for McLaren, Alpine, Williams, RB/Racing Bulls, Audi. Confidence and source-date stamped. |
| `server/circuit_profiles.py` | Add `CALENDAR_YEAR = 2026`, replace substring matches with anchored matches, fix the Baku straight figure, expose a canonical match helper for the resolver to delegate to. |

Do not rewrite whole files. Keep patches scoped. No new external dependencies.

## Key Corrections vs Earlier Behaviour

- The `8.5 MJ/lap` recovery figure in `energy_2026.py:5` is the obsolete pre-late-2024 draft. Final 2026 FIA spec is **7 MJ/lap** with a documented deployment ramp curve, override mode, zone caps, and a 4 MJ stored-energy battery limit. The current module gives Claude none of this.
- `resolver.py:86-94` LLM alias prompt enumerates only 2024 drivers. As of 2026-05-19 the grid has rolled forward; missing alias coverage causes false negatives on first-name references for ~40% of the field.
- `resolver.py:17` and `openf1.py:6` both define `_circuits_cache`. They can diverge under load. Same goes for circuit-name matching logic in `resolver.py:_match_event` vs `circuit_profiles.py:get_circuit_profile` — two matchers, two outcomes.
- `openf1.py:_openf1_get` has timeout=20 but no retry. A single OpenF1 502 turns the whole `/api/chat` request into an uncaught 500.
- `circuit_profiles.py` Baku notes claim a "2.2 km main straight" — needs verification against FIA circuit specs (the circuit total length is ~6 km; the Turn 16 → Turn 1 straight is ~2.2 km but should be sanity-checked against the official 2026 spec).

---

## Phased Task Breakdown

Each task is shippable on its own and corresponds to one numbered scope item. Run server tests after each.

### Task 8: Refresh 2026 Energy Knowledge

Files:

- Modify: `server/energy_2026.py`
- Test: `server/tests/test_energy_2026.py` (new)

Change description:

- In `ENERGY_2026_KNOWLEDGE["known_facts"]` (`energy_2026.py:2`), replace the line at `:5` ("…about 8.5 MJ per lap of energy recuperation…") with the **final 2026 FIA spec**: roughly **7 MJ/lap** of recuperation, refined in the late-2024 FIA revision.
- Add three new top-level dict keys, preserving the existing shape so every current caller of `get_energy_2026_knowledge()` (deterministic analysis context injection in `chat.py`, agentic tool returns in `tools.py`) continues to work:
  - `"deployment_curve"`: list of dicts describing the standard MGU-K deployment ramp.
    - 350 kW (max) held flat up to ~290 km/h.
    - Ramps down to 0 kW at ~355 km/h.
    - Mid-point reference between the two anchors. Include speed (km/h) and kW values so Claude can interpolate.
  - `"override_mode"`: text + curve description.
    - 350 kW held flat up to ~337 km/h (vs 290 km/h standard).
    - Triggered by being within a 1-second gap to the car ahead.
    - Replaces the 2014–2025 "DRS" as the primary on-track overtaking aid.
  - `"zone_caps"`: dict.
    - `"key_acceleration_zones_kw": 350`
    - `"other_zones_kw": 250`
    - Free-text note that the zones are circuit-specific and FIA-published per round.
  - `"battery_storage"`: dict.
    - `"per_lap_recovery_mj": 7`
    - `"stored_energy_cap_mj": 4`
    - Note: stored cap is what is usable lap-to-lap; the per-lap recovery target is what the system is allowed to bring back through MGU-K under braking.
- Update the `known_facts` list so the MGU-K kW figure (350 kW) is consistent across entries.
- Update `interpretation_rules` and `answer_rules` only if they reference the obsolete 8.5 MJ number explicitly — they currently do not, so the change is contained to the `known_facts` line and the new keys.

Acceptance:

- `get_energy_2026_knowledge()` returns a dict whose existing keys (`known_facts`, `terms`, `interpretation_rules`, `limitations`, `answer_rules`) remain present with the same shape.
- The new keys `deployment_curve`, `override_mode`, `zone_caps`, `battery_storage` are reachable.
- A new test `test_energy_2026.py::test_known_facts_no_8_5_mj` asserts the obsolete figure is not present and `7` MJ/lap is.
- A new test `test_energy_2026.py::test_deployment_curve_shape` asserts the new keys exist and contain the expected kW/km/h anchors.
- All existing tests still pass.

Overlap note:

- This item mirrors what a long-form F3 entry in the future data-currency feature plan would do. The bug plan only fixes the specific numbers and adds the curves. The feature plan can later layer narrative paragraphs, override-mode tactical notes, and per-circuit zone tables on top without breaking the dict shape introduced here.

Run:

```bash
cd server
python -m pytest tests/test_energy_2026.py -v
python -m pytest tests/ -v
```

---

### Task 9: 2026 Grid Aliases In Resolver Prompt

Files:

- Modify: `server/resolver.py` (lines 86–94, inside `_extract_entities_llm` system prompt)
- Test: `server/tests/test_resolver.py`

Change description:

- The current alias block at `resolver.py:91-94` hardcodes Verstappen, Norris, Pérez, Sainz, Russell, Hamilton, Leclerc, Piastri, Alonso, Stroll. As of 2026-05-19 the grid has moved on. Audit each driver against `get_drivers()` (Jolpica/FastF1 at runtime) and add canonical first-name → code aliases for the **2026 movers/rookies**:
  - **ANT** — Kimi (Andrea Kimi) Antonelli → Mercedes
  - **BEA** — Oliver / Ollie Bearman → Haas
  - **LAW** — Liam Lawson → RB / Racing Bulls
  - **HAD** — Isack Hadjar → RB / Racing Bulls
  - **BOR** — Gabriel Bortoleto → Audi (Sauber rebrand)
  - **DOO** — Jack Doohan → Alpine
  - **TSU** — Yuki Tsunoda → Red Bull or RB (verify seat at build time via Jolpica)
  - **COL** — Franco Colapinto → Alpine
- Add these as new lines in the alias section of the system prompt. Do **not** drop any of the existing aliases — even if Pérez is no longer racing, the alias remains harmless for historical-question handling.
- Resolution path for ambiguous seats (e.g. Tsunoda RB vs RBR): leave the LLM to pick from the live driver list passed in via `driver_lines`. The alias only maps first-name → 3-letter code, never first-name → team.
- Where a first-name collision exists between current and historical drivers (e.g. "Liam" only — fine; "Carlos" → SAI may now be a different team), the alias points to the code; the driver list re-prints the canonical team next to that code.

Acceptance:

- The system-prompt string built at `resolver.py:72-95` contains the new alias lines.
- A new test `test_resolver.py::test_prompt_includes_2026_aliases` snapshots the system-prompt fragment and asserts each of the eight new aliases (`ANT`, `BEA`, `LAW`, `HAD`, `BOR`, `DOO`, `TSU`, `COL`) appears at least once.
- A new test `test_resolver.py::test_prompt_preserves_legacy_aliases` asserts each existing alias still appears (Mad Max, Lando, Checo, Carlos, George, Lewis, Charles, Oscar, Fernando, Lance).
- No live API call is made in the test — the system prompt is constructed via the existing path with `_cached_drivers()` and `_cached_circuits()` stubbed.

Risk to surface (already in CLAUDE.md risk protocol):

- **Risk:** Tsunoda's actual 2026 seat is ambiguous between Red Bull Racing and Racing Bulls. Hardcoding a team mapping in the prompt could mislead the LLM when the real seat differs.
- **Trigger:** Any chat question asking about Tsunoda + a specific 2026 race.
- **Solutions:** (1) Map alias to code only, never team — keep team resolution in the live driver list. (2) Add a Jolpica build-time check that flags drift between alias and seat. (3) Defer Tsunoda entirely until Jolpica confirms his round-1 entry list.
- **Recommendation:** (1). Keep the alias prompt code-only.

Overlap note:

- Mirrors F4 of the future data-currency feature plan. Bug plan keeps the patch in the system prompt only. Feature plan should later build a versioned alias registry with auto-rotation on driver-list changes.

Run:

```bash
cd server
python -m pytest tests/test_resolver.py -v
```

---

### Task 10: Stub Driver Style Profiles For 2026 Rookies/Movers

Files:

- Modify: `server/driver_styles.py`
- Test: `server/tests/test_driver_styles.py`

Change description:

- `driver_styles.py:28` currently defines `DRIVER_STYLES` for ~15 drivers. Add **stub profiles** for the 2026 entries that are either fully missing or thinly profiled. Concretely, add (or upgrade) entries for: `BEA`, `LAW`, `HAD`, `BOR`, `DOO`, `COL` (and confirm `ANT` and `TSU`, which already exist, are still pointed at their correct teams).
- Stub schema (use the existing fields for compatibility with `get_comparison_framing`):
  - `full_name`: full driver name
  - `steering_style`, `corner_approach`, `braking_style`, `apex_style`, `throttle_style`, `car_preference`, `setup_preference` — best-guess from junior-formula coverage; OK to use "balanced" / "measured" / `null` for unknowns.
  - `corner_philosophy`: 1–2 sentence draft, NOT the rich 4–5 sentence treatment Verstappen/Hamilton/etc. get.
  - `key_traits`: 2–3 bullet items.
  - `telemetry_signature`: short. May say "limited F1 data — profile will firm up through 2026."
  - `weakness`, `wet_weather`: short. `wet_weather` may be `"Unknown — limited data."` per the existing ANT/BEA convention.
  - **New stub-only fields** (these are the safety valve):
    - `"confidence": "low"`
    - `"editorial": "draft"`
    - `"last_reviewed": "2026-05-19"`
- Update `get_comparison_framing()` at `driver_styles.py:456` to surface confidence when at least one of the two driver styles is `confidence: low`. The function already returns a dict; add a key:
  - `"style_confidence": "low"` when either profile is low confidence, else `"high"` (default).
- The chat layer (downstream in `chat.py`) uses `style_prediction` directly today. It can be updated separately to consult `style_confidence` — out of scope for this bug fix, but the field needs to be present so the future chat-side downgrade hook has data to read.

Acceptance:

- `DRIVER_STYLES` contains entries for every driver code returned by `get_drivers()` for the current 2026 season — verify by iterating `_cached_drivers()` in a test.
- Every stub entry has `confidence`, `editorial`, `last_reviewed` keys.
- `get_comparison_framing("HAM", "BEA")` returns a dict containing `style_confidence: "low"` (Bearman is a low-confidence stub).
- `get_comparison_framing("HAM", "VER")` returns `style_confidence: "high"` (both fully profiled).
- Existing tests for `get_driver_style` and `get_comparison_framing` continue to pass.

Risk:

- **Risk:** Stubs marked `confidence: low` may still flow into the deterministic chat path as authoritative-sounding context.
- **Trigger:** A user asks "compare Bearman and Hamilton at Imola."
- **Solutions:** (1) Add the `style_confidence` flag now, follow-up chat.py change to hedge wording. (2) Block the deterministic style-injection from running when any matched driver is a stub. (3) Do nothing and let the prose be wrong until the feature plan refreshes.
- **Recommendation:** (1). Flag now, chat layer hedges in a follow-up.

Overlap note:

- Mirrors F5 of the future data-currency feature plan. Bug plan ships stubs only; feature plan does the full editorial pass with telemetry-grounded paragraphs.

Run:

```bash
cd server
python -m pytest tests/test_driver_styles.py -v
```

---

### Task 11: Skeleton Entries For Missing Team Car Profiles

Files:

- Modify: `server/team_car_profiles.py`
- Test: `server/tests/test_team_car_profiles.py`

Change description:

- `team_car_profiles.py:8` defines `TEAM_CAR_PROFILES` for Ferrari, Mercedes, Aston Martin, Red Bull, Haas only. Add **skeleton entries** for the remaining 2026 constructors:
  - `mclaren` — **championship leader**, biggest current omission. Sourced from any 2025–2026 published race notes: Sky F1, The Race, F1.com pre-season analysis, Autosport. Note balanced car character; aerodynamic stability through high-speed sections; ongoing development.
  - `alpine` — 2025/2026 chassis direction notes from public Sky/The Race/Autosport coverage.
  - `williams` — Carlos Sainz arrival and chassis direction; published technical reviews.
  - `rb` / `racing_bulls` — RB rebrand notes; sister-team relationship with Red Bull Racing; published reporting on chassis differences.
  - `audi` — Sauber → Audi rebrand for 2026; new PU; published reporting on chassis identity. Mark heavily speculative until on-track data lands.
- Use the same schema as existing entries (`team`, `profile_type: "curated_editorial"`, `last_reviewed`, `confidence`, `summary`, `traits` list, `caveat`). For each new entry:
  - `confidence`: `"low"` for Audi (no race data yet); `"medium"` for McLaren, Alpine, Williams; `"low"` for RB/Racing Bulls (sister-team noise makes attribution shaky).
  - `last_reviewed: "2026-05-19"`.
  - Each `trait` entry should include `source` and `source_url` strings. Use a placeholder source when no public reporting URL is available yet (e.g. `source: "pending citation"`). The point is that the schema is right; the feature plan will backfill real URLs.
- Update `get_team_car_profile` matching at `team_car_profiles.py:104` only if necessary. The current substring loop should handle `"mclaren"`, `"alpine"`, `"williams"` cleanly. For "RB" verify the substring match does not collide with "Red Bull" — if it does, add an explicit alias check (e.g. exact-match `"rb"` or `"racing bulls"` before the substring scan).

Acceptance:

- `TEAM_CAR_PROFILES` contains entries for all 10 2026 constructors as enumerated by the current driver list.
- `get_team_car_profile("McLaren")` returns a dict with `confidence: "medium"`.
- `get_team_car_profile("Racing Bulls")` returns the RB profile, NOT the Red Bull profile. Add a test that asserts this disambiguation.
- `get_team_car_profile("Audi")` returns the new Audi entry.
- All new entries have `last_reviewed: "2026-05-19"` and a non-empty `caveat` string.

Overlap note:

- Mirrors F6 of the future data-currency feature plan. Bug plan ships skeletons; feature plan replaces them with sourced, paragraph-length editorial summaries.

Run:

```bash
cd server
python -m pytest tests/test_team_car_profiles.py -v
```

---

### Task 12: TTL The Circuit Cache In Resolver

Files:

- Modify: `server/resolver.py`

Change description:

- At `resolver.py:16-17` add `_circuits_cache_time: float = 0.0` and `_CIRCUITS_CACHE_TTL = 3600` (one hour; circuits don't churn within a season but the cache should still rotate).
- Rewrite `_cached_circuits()` at `resolver.py:31-38` to mirror the `_cached_drivers()` TTL pattern at `:20-28`:

```python
def _cached_circuits() -> list[dict]:
    global _circuits_cache, _circuits_cache_time
    if not _circuits_cache or time.time() - _circuits_cache_time > _CIRCUITS_CACHE_TTL:
        try:
            _circuits_cache = get_circuits()
            _circuits_cache_time = time.time()
        except Exception:
            pass
    return _circuits_cache
```

Acceptance:

- Reading `_circuits_cache` twice within 3600 s makes one `get_circuits()` call.
- Reading after 3600 s triggers a refresh.
- A new test `test_resolver.py::test_circuits_cache_ttl` monkey-patches `time.time` and asserts the refresh boundary.
- Existing resolver tests pass.

Run:

```bash
cd server
python -m pytest tests/test_resolver.py -v
```

---

### Task 13: Retry + Timeout For OpenF1

Files:

- Modify: `server/openf1.py`
- Test: `server/tests/test_openf1.py`

Change description:

- At `openf1.py:26-29`, `_openf1_get()` already has `timeout=20`. Lower to **`timeout=10`** (the OpenF1 SLA is fast; 20 s is wasteful when a 3-attempt retry can replace it).
- Wrap the call in a small in-file retry helper with **exponential backoff (0.5 s, 1.5 s, 4.5 s)**. Three total attempts. Use a private helper function so the retry logic stays simple and visible:

```python
def _openf1_get(endpoint: str, **params):
    delays = [0.5, 1.5, 4.5]
    last_exc = None
    for i, delay in enumerate([0.0] + delays[:-1]):
        if delay:
            time.sleep(delay)
        try:
            response = requests.get(
                f"{OPENF1_BASE}/{endpoint}",
                params=params,
                timeout=10,
            )
            # 401/404 should not retry — they are deterministic
            if response.status_code in (401, 404):
                response.raise_for_status()
            # 5xx and connection errors should retry
            if response.status_code >= 500:
                last_exc = requests.HTTPError(
                    f"OpenF1 {response.status_code} for /{endpoint}",
                    response=response,
                )
                continue
            response.raise_for_status()
            return response.json()
        except (requests.Timeout, requests.ConnectionError) as exc:
            last_exc = exc
            continue
    raise last_exc if last_exc else RuntimeError("OpenF1 retry exhausted with no exception")
```

- Preserve `raise_for_status()` semantics so the `get_team_radio` 404 handling at `openf1.py:92-97` keeps working unchanged.
- Do **not** use `urllib3.util.retry.Retry` — it requires wiring an HTTPAdapter, which adds a moving part. The in-file helper above is the minimum.

Acceptance:

- A new test `test_openf1.py::test_get_retries_on_502` patches `requests.get` to raise a 502, then a 502, then return a 200 — `_openf1_get` returns the 200 payload.
- A new test `test_openf1.py::test_get_does_not_retry_404` patches a single 404 — `_openf1_get` raises immediately.
- A new test `test_openf1.py::test_get_does_not_retry_401` patches a single 401 — `_openf1_get` raises immediately.
- A new test `test_openf1.py::test_get_propagates_after_three_failures` patches three 503s — `_openf1_get` raises the last `HTTPError`.
- `get_team_radio` 404 path still returns `unavailable_reason` — covered by a regression test that patches `_openf1_get` to raise a 404 `HTTPError` directly (the retry helper is bypassed in this path because `_openf1_get` raised).

Risk:

- **Risk:** Retries inside `_openf1_get` extend worst-case latency by 6 s (0.5 + 1.5 + 4.5 = 6.5 s sleep + 3 × 10 s timeout = ~36 s).
- **Trigger:** OpenF1 fully down during a chat request.
- **Solutions:** (1) Accept the 36 s cap for now; user-facing 500s are worse than slow responses. (2) Drop retry count to 2 attempts (max ~25 s). (3) Add a circuit-breaker that disables OpenF1 for 60 s after 3 consecutive failures.
- **Recommendation:** (1). 36 s is rare; the 500 is the active bug.

Run:

```bash
cd server
python -m pytest tests/test_openf1.py -v
```

---

### Task 14: Calendar Year Stamp + Anchored Country Matching + Baku Straight Figure

Files:

- Modify: `server/circuit_profiles.py`
- Test: `server/tests/test_circuit_profiles.py`

Change description:

- Add at the top of `circuit_profiles.py` (just below the docstring):

```python
CALENDAR_YEAR = 2026
```

- The `_LOOKUP` table at `circuit_profiles.py:901-929` uses substring fragments like `("brit", "", "britain")`. This works today but is brittle: `"brit"` could match an ISO country fragment that ends up shorter in the future. Replace each fragment match with an **anchored / case-folded equality check** against the country plus a short alias table. Concretely, change `get_circuit_profile` at `:932-954` so the loop:
  - Casefolds `country` once.
  - Uses an exact-equality match first against a canonical-country alias table.
  - Falls back to substring only if no canonical match found.
- Canonical country aliases:

```python
_COUNTRY_ALIASES: dict[str, str] = {
    "bahrain": "bahrain",
    "saudi arabia": "saudi_arabia",
    "australia": "australia",
    "japan": "japan",
    "china": "china",
    "united states": "united_states",
    "emilia romagna": "emilia_romagna",
    "monaco": "monaco",
    "canada": "canada",
    "spain": "spain",
    "austria": "austria",
    "great britain": "britain",
    "united kingdom": "britain",
    "britain": "britain",
    "belgium": "belgium",
    "hungary": "hungary",
    "netherlands": "netherlands",
    "italy": "italy",
    "azerbaijan": "azerbaijan",
    "singapore": "singapore",
    "mexico": "mexico",
    "brazil": "brazil",
    "las vegas": "las_vegas",
    "qatar": "qatar",
    "abu dhabi": "abu_dhabi",
}
```

- For US-disambiguation (Miami vs COTA), keep the event-name check: if `country == "united states"` and `"miami" in event_name.casefold()`, return `miami`; else `united_states`.
- **Fix the Baku straight figure.** Examine `circuit_profiles.py:621-639`:
  - The current text says the Turn 16 → Turn 1 main straight is ~2.2 km. Verify this against the FIA 2026 circuit specification at integration time. If the true figure is different (the FIA-published main-straight length is the canonical source), update both `description` and `narrative` accordingly.
  - The total circuit length is ~6 km. The current text does NOT claim 2.2 km is the total — it says "main straight at 2.2 km" — but the prose juxtaposition with "longest in F1" is risky. Tighten the wording so it's unambiguous: "Turn 16 → Turn 1 start/finish straight, the longest full-throttle section in F1 at approximately 2.2 km."
  - If the FIA figure differs (some published sources cite ~2.1 km or ~1.9 km depending on measurement points), use the FIA value as the canonical figure and add a comment in the file noting the source date.

Acceptance:

- `CALENDAR_YEAR` is exported from `circuit_profiles.py`.
- `get_circuit_profile("Great Britain")` returns the Silverstone profile (the alias entry handles "Great Britain" without falling back to a substring match).
- `get_circuit_profile("United States", "Miami GP")` returns Miami; `get_circuit_profile("United States", "United States Grand Prix")` returns COTA.
- `get_circuit_profile("UNITED STATES", "")` (no event) still returns COTA (the fallback / lower-priority US entry).
- The Baku narrative no longer juxtaposes "2.2 km" against "longest in F1" without explicit "main straight" qualifier.
- A new test `test_circuit_profiles.py::test_calendar_year_constant` asserts `CALENDAR_YEAR == 2026`.
- A new test `test_circuit_profiles.py::test_baku_straight_qualifier` asserts the Baku `narrative` text contains the words "main straight" before the kilometre figure.

Risk:

- **Risk:** The actual FIA-published Baku main straight length is not 2.2 km.
- **Trigger:** Any chat question about Baku top speed or DRS strategy.
- **Solutions:** (1) Look up FIA 2026 Baku circuit spec at implementation time and use the canonical figure. (2) Drop the specific number and say "very long main straight (longest on calendar)" without km. (3) Note "~2 km" with a soft qualifier.
- **Recommendation:** (1). FIA-canonical or nothing.

Run:

```bash
cd server
python -m pytest tests/test_circuit_profiles.py -v
```

---

### Task 15: Tighten Reference-Language Detection

Files:

- Modify: `server/resolver.py`
- Test: `server/tests/test_resolver.py`

Change description:

- `_has_reference_language()` at `resolver.py:119-131` returns `True` when ANY single token from a 25-item list is found. Single pronouns like `"his"`, `"he"`, `"it"`, `"the"` fire constantly across unrelated queries. This produces false context carryover in `_merge_with_previous_context` at `:592-656` (the `reference_gated_fields` path).
- Replace the single-token-OR with a tighter heuristic that requires **at least one of**:
  - Two or more reference tokens from the existing list, OR
  - One explicit deictic phrase from a tightened list: `"that race"`, `"that weekend"`, `"that session"`, `"that gp"`, `"that grand prix"`, `"this race"`, `"this weekend"`, `"this session"`, `"this gp"`, `"the same driver"`, `"the same race"`, `"same weekend"`, `"last race"`, `"last weekend"`, `"teammate"`.
- The weak single-pronoun list (`"he"`, `"him"`, `"his"`, `"she"`, `"her"`, `"they"`, `"them"`, `"their"`, `"it"`, `"its"`, `"the"`, `"here"`, `"there"`, `"both"`) only contributes when at least two of them appear.

Implementation sketch:

```python
def _has_reference_language(normalized: str) -> bool:
    strong_phrases = (
        "that race", "that weekend", "that session", "that gp", "that grand prix",
        "this race", "this weekend", "this session", "this gp",
        "the same driver", "the same race", "same weekend",
        "last race", "last weekend",
        "teammate",
    )
    if any(re.search(rf"\b{re.escape(p)}\b", normalized) for p in strong_phrases):
        return True

    weak_tokens = (
        "he", "him", "his", "she", "her",
        "they", "them", "their",
        "it", "its",
        "the",
        "here", "there", "both",
    )
    hits = sum(
        1 for t in weak_tokens
        if re.search(rf"\b{re.escape(t)}\b", normalized)
    )
    return hits >= 2
```

Acceptance:

- A query like "what's the weather like today" (contains `the`) returns `False`.
- A query like "how was his race" (contains `his` only) returns `False`.
- A query like "how was his race that weekend" returns `True` via the deictic phrase.
- A query like "did he beat his teammate" returns `True` via `teammate`.
- A query like "did he and his car make it through" returns `True` (two weak tokens).
- New tests in `test_resolver.py::TestHasReferenceLanguage` cover each case.
- Existing context-merge tests pass — verify the bar is not now too high. If any existing test was implicitly depending on single-pronoun firing, update the test's input to use a deictic phrase instead.

Risk:

- **Risk:** Tightening the bar may suppress legitimate carryover for terse follow-up messages like "his race?" or "her weekend?".
- **Trigger:** User in chat sends a one-word follow-up after a fully-specified previous turn.
- **Solutions:** (1) Accept the tradeoff — terse messages already carry weak resolution_confidence. (2) Add a length-based bypass: if `len(normalized.split()) <= 3` and any weak token fires, treat as reference. (3) Surface to the user as a clarifying question via `_detect_clarification_needed`.
- **Recommendation:** (1). The current false-positive rate is the bigger bug.

Run:

```bash
cd server
python -m pytest tests/test_resolver.py -v
```

---

### Task 16: Consolidate Circuit Caches

Files:

- Modify: `server/openf1.py`
- Modify: `server/resolver.py` (export the cache)
- Test: `server/tests/test_openf1.py`

Change description:

- `resolver.py:16` and `openf1.py:6` both define `_circuits_cache`. They populate independently and can serve different lists if the underlying `get_circuits()` result mutates between the two first-fetches.
- Consolidate: `openf1.py` should not define its own `_circuits_cache`. Instead, import the TTL'd `_cached_circuits()` from `resolver.py` (Task 12 makes that function TTL-aware, so the consolidation lands cleanly).
- Delete `openf1.py:6` (`_circuits_cache: list[dict] = []`) and `openf1.py:32-36` (`_cached_circuits()`).
- Replace the call site at `openf1.py:40` (`circuit = next((row for row in _cached_circuits()...))`) with:

```python
from resolver import _cached_circuits  # at top of openf1.py
```

- **Circular import risk:** `resolver.py` already imports from `f1_data` (`from f1_data import get_circuits, get_drivers`). `openf1.py` already imports from `f1_data` (`from f1_data import CURRENT_YEAR, _resolve_driver, get_circuits, get_session_results`). Importing `resolver` from `openf1` is one-directional and acyclic — verify by import-tracing at implementation time. If a cycle does emerge, lift `_cached_circuits` into a small new module `server/circuits_cache.py` and have both `resolver.py` and `openf1.py` import from there.

Acceptance:

- `openf1.py` no longer defines `_circuits_cache` or `_cached_circuits`.
- `_resolve_openf1_session` uses the resolver's TTL'd cache.
- A new test `test_openf1.py::test_uses_shared_circuit_cache` patches `resolver._cached_circuits` and asserts the patched data flows into OpenF1.
- All existing OpenF1 tests pass.

Risk:

- **Risk:** Importing `resolver` from `openf1` creates a circular import the next time someone adds a `from openf1 import ...` to `resolver.py`.
- **Trigger:** Future refactor.
- **Solutions:** (1) Document the one-way dependency in `openf1.py` header comment. (2) Extract `_cached_circuits` into `circuits_cache.py` proactively. (3) Use a late/lazy import inside `_resolve_openf1_session`.
- **Recommendation:** (2). Small shared module is the cleanest long-term fix; (1) is acceptable as an interim if (2) is deferred.

Run:

```bash
cd server
python -m pytest tests/test_openf1.py tests/test_resolver.py -v
```

---

### Task 17: Single Circuit-Name Matcher

Files:

- Modify: `server/resolver.py`
- Modify: `server/circuit_profiles.py`
- Test: `server/tests/test_resolver.py`, `server/tests/test_circuit_profiles.py`

Change description:

- `resolver.py:_match_event` at `:318-395` and `circuit_profiles.py:get_circuit_profile` at `:932-954` both implement circuit matching from different inputs (resolver from a normalized free-text message; circuit_profiles from a country + event-name pair). They use different rules and can return different circuits for the same input.
- Canonical owner: `circuit_profiles.py`. Add a helper that takes the same free-text input the resolver consumes and returns a canonical circuit key:

```python
# in circuit_profiles.py

def match_circuit_from_text(normalized: str, circuits: list[dict]) -> dict | None:
    """
    Free-text circuit matcher used by the resolver. Tries:
    1. Canonical country alias match against each circuit's country field.
    2. Alias table (e.g. "suzuka" → "japan") then alias → canonical country.
    3. Fallback to substring scan over event_name / circuit_name / country.
    Returns the matching circuit dict from `circuits`, or None.
    """
    # ... implementation ...
```

- `_match_event` at `resolver.py:318` delegates to `match_circuit_from_text`. It keeps the `alias_map` it currently owns at `:319-348` but passes that map into the canonical matcher (or the canonical matcher absorbs the alias map directly — preferred, since the alias map is editorial knowledge that belongs next to circuit profiles).
- Move the alias map into `circuit_profiles.py` as a module-level constant `CIRCUIT_TEXT_ALIASES`. The resolver imports nothing extra; `_match_event` is reduced to a one-line delegation:

```python
def _match_event(normalized: str) -> dict | None:
    from circuit_profiles import match_circuit_from_text
    return match_circuit_from_text(normalized, _cached_circuits())
```

- Existing tests for `_match_event` should now pass against the canonical matcher.

Acceptance:

- `_match_event("did you see what happened at suzuka")` and `get_circuit_profile("japan")` agree on the Japanese GP for the equivalent inputs.
- A property-style test enumerates a fixed set of free-text inputs (`"suzuka"`, `"monza"`, `"spa"`, `"silverstone"`, `"interlagos"`, `"cota"`, `"imola"`, `"montreal"`, `"baku"`, `"jeddah"`, `"las vegas"`, `"mexico city"`, `"barcelona"`, `"zandvoort"`) and asserts both code paths produce the same canonical country.
- The resolver's alias map is gone from `resolver.py`; lives in `circuit_profiles.py`.
- No regression in existing resolver tests.

Risk:

- **Risk:** Moving the alias map into `circuit_profiles.py` creates a `resolver → circuit_profiles` import dependency. If anything later imports `resolver` from `circuit_profiles` it cycles.
- **Trigger:** Future refactor.
- **Solutions:** (1) Note in `circuit_profiles.py` header that it is a leaf module — must not import resolver. (2) Use a lazy import inside `_match_event`. (3) Extract the alias map to a third tiny module.
- **Recommendation:** (1) + (2). The lazy import inside `_match_event` is already in the sketch above for safety.

Run:

```bash
cd server
python -m pytest tests/test_resolver.py tests/test_circuit_profiles.py -v
```

---

## Validation Checklist

- [ ] `energy_2026.py` `known_facts` no longer contains "8.5 MJ".
- [ ] `energy_2026.py` exposes `deployment_curve`, `override_mode`, `zone_caps`, `battery_storage`.
- [ ] `get_energy_2026_knowledge()` callers in `chat.py` and `tools.py` continue to work without modification.
- [ ] `resolver.py` LLM alias prompt enumerates ANT, BEA, LAW, HAD, BOR, DOO, TSU, COL alongside existing aliases.
- [ ] `driver_styles.py` has profiles for every code returned by `_cached_drivers()`; stubs are marked `confidence: low`, `editorial: draft`.
- [ ] `team_car_profiles.py` has entries for McLaren, Alpine, Williams, RB / Racing Bulls, Audi.
- [ ] `get_team_car_profile("Racing Bulls")` does not return the Red Bull profile.
- [ ] `resolver.py` `_circuits_cache` has a TTL constant and a `_circuits_cache_time` variable.
- [ ] `openf1._openf1_get` retries on 5xx/timeout with 0.5/1.5/4.5 s backoff, does not retry on 401/404, uses `timeout=10`.
- [ ] `circuit_profiles.py` exposes `CALENDAR_YEAR = 2026`.
- [ ] Baku narrative qualifies the 2.2 km figure as the main straight, not the total circuit.
- [ ] `_has_reference_language` no longer fires on a single weak pronoun.
- [ ] Only one `_circuits_cache` exists in the codebase (resolver's, with TTL).
- [ ] Only one circuit-text matcher exists (in `circuit_profiles.py`); the resolver delegates.
- [ ] `python -m pytest server/tests/ -v` all pass.

## Risks and Open Questions

These need answers during or shortly after the build. Surfaced per CLAUDE.md risk-management protocol.

| Risk | When it triggers | Proposed resolution | Decision needed by |
|---|---|---|---|
| 2026 seat assignments for movers (Tsunoda, Lawson, Hadjar) ambiguous at build time | Task 9 | Map alias to driver code only; never alias to team. Verify each via Jolpica `get_drivers()` at startup; log a warning when alias and live seat disagree. | Task 9 start |
| FIA-published 2026 Baku main-straight length differs from the assumed 2.2 km | Task 14 | Use the FIA value as canonical; if unavailable at implementation time, soften the wording to "the longest full-throttle straight on the calendar" without a kilometre figure. | Task 14 start |
| OpenF1 retry latency cap of ~36 s feels user-hostile during a major outage | Task 13 | Accept the cap for V1. Add a circuit-breaker later if OpenF1 outages become frequent (per F-series feature plan). | Post-Task 13 |
| Consolidating the circuit cache via `from resolver import ...` creates a future circular import | Task 16 | Document the dependency direction in `openf1.py`; if a cycle emerges, extract `_cached_circuits` into a leaf module `circuits_cache.py`. | Task 16 |
| Stubs in `driver_styles.py` flow into chat as authoritative-sounding | Task 10 | Surface `style_confidence: "low"` from `get_comparison_framing`. Follow-up `chat.py` change hedges wording — out of scope for this bug plan but needed before the next release. | Post-Task 10 |
| Reference-language tightening suppresses legitimate terse follow-ups | Task 15 | Accept the tradeoff; if user reports of "the chat lost my context" come in, add a length-based bypass for messages ≤ 3 tokens. | Post-Task 15 |
| LLM alias prompt grows past Claude Haiku's preferred-context size for the entity extractor | Task 9 | Move the alias block into a compact table format (one alias per line, no prose); 8 extra entries should not push the prompt past Haiku's small-context optimal range. | Task 9 implementation |
| Energy curve numbers (350 kW @ 290 km/h, 0 kW @ 355 km/h, 350 kW @ 337 km/h override) come from the FIA 2026 PU regulations | Task 8 | At implementation time, cross-check against the published FIA technical regulations or a reputable secondary source (The Race technical analysis, F1 Technical Analysis, Motorsport.com regulation reviews). If any anchor differs, use the FIA-canonical figure and stamp the source date in a comment. | Task 8 start |

## Notes On Overlap With Future Data-Currency Feature Plan

Items #8, #9, #10, #11 each correspond to a planned feature-plan item (notionally F3, F4, F5, F6 — feature plan not yet written). The split is:

- **Bug plan (this plan):** minimum-viable corrections. New dict keys, stub profiles, skeleton entries, alias additions, numeric corrections. No new editorial paragraphs beyond what fits in a stub schema.
- **Feature plan (future):** long-form refresh. Paragraph-length sourced summaries, telemetry-grounded driving-style observations, per-circuit fuel coefficient tables, override-mode tactical guidance, season-to-season comparisons.

Both plans should be safe to ship in sequence. Bug plan never overwrites a fully-profiled entry (Verstappen, Hamilton, Ferrari, Mercedes etc.); it only adds new ones and fixes broken numbers. Feature plan can replace stub entries one-by-one without schema migration.

## Commit Plan

Use small commits, one per task:

1. `fix(energy_2026): replace stale 8.5 MJ figure; add deployment/override/storage`
2. `fix(resolver): add 2026 grid aliases to entity extractor prompt`
3. `feat(driver_styles): stub profiles for 2026 movers with low-confidence flag`
4. `feat(team_car_profiles): skeleton entries for McLaren, Alpine, Williams, RB, Audi`
5. `fix(resolver): TTL the circuits cache`
6. `fix(openf1): add 10s timeout and 3-attempt exponential backoff`
7. `fix(circuit_profiles): add CALENDAR_YEAR; anchor country matching; clarify Baku straight`
8. `fix(resolver): tighten reference-language detection`
9. `refactor: consolidate circuit cache between resolver and openf1`
10. `refactor: single canonical circuit-text matcher in circuit_profiles`
