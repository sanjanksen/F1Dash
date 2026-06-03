# Multi-Year + Regulation-Era Support Implementation Plan (rev. 5 — post 4th Codex review)

> **rev.5 fixes (4th Codex review — "Conditional Go" blockers):** F1 — **skip high-confidence preload for `cross_year`/multi-year** contexts (else a single current-year preload poisons the prompt) + preload itself sets the active season — A6/A8; F2 — deterministic circuit-profile builder passes the resolved `year` into `get_historical_circuit_performance` (round→circuit mapping + window) — A3/A8; F3+F7 — widget `year` is plumbed in **`_registry_widget`** (copy `year` into `result` before `make_widget`) and **embedded into the title/subtitle string** (not a bare field, so the frontend needs no change) — A8; F4 — editorial window spans **`resolved["years"]`** (`min(years)`…`max(years)+1`) for cross-year — B5c; F5 — **`_detect_analysis_mode(..., years=…)`** signature + call-site change made explicit — A7. Codex verified all rev.4 fixes landed.


> **rev.4 fixes (3rd Codex review):** same-entity cross-year now uses a **dedicated `cross_year` mode + single-entity per-year tools** (not two-driver battle tools fed `VER vs VER`) — A7b/A8; widgets carry `year` so paired widgets don't dedup-collapse — A8; `search_editorial_content` + `get_historical_circuit_performance` **excluded** from `year` injection (they have their own date/`years` handling) — A6; editorial `max_published` is a **required migration** — B5a; `build_resolver_subject_set` fixed to read the resolver's real keys (latent no-op bug) — B5; `ANALYSIS_SYSTEM_PROMPT` test updated — B3. Codex **verified clean**: the `execute_tool` rename, the `resolve_round` cycle break, and the ContextVar/`copy_context` ordering.


> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Checkbox (`- [ ]`) steps.

**Goal:** Answer about any FastF1 season (≈2018→present), **compare two seasons in one question** ("Verstappen 2024 vs 2025") — including the same driver across years — each analyzed with its own rulebook (2026 new regs vs 2022–2025 ground-effect).

**Architecture:** Ambient season `contextvars.ContextVar` (default `CURRENT_YEAR`), read by the data layer via `active_season()`. Season is set **per tool call** with **token-based** `set_season`/`reset_season` and an **immutable args copy**, wrapping the **registry-first** `execute_tool` dispatch. The parallel deterministic executor uses a **fresh `copy_context()` per future**. Rounds are resolved **per season**. Tool schemas get an optional `year` **injected centrally** into the registry→schema functions. The resolver detects the year(s) **before** entity extraction so rosters/calendars match. Era rulebook is selected by the analyzed year(s); multi-year canonicalization is bypassed (not collapsed).

**Codex reviews — every finding → task:**
| Finding | Sev | Task |
|---|---|---|
| Shared `copy_context()` across threads | 1 | A6 (per-future + token reset) |
| Same-driver cross-year never reaches deterministic builder | 1 | **A7 same-entity detection + A8** |
| Canonicalizers collapse paired calls to one year | 1 | **A8 (bypass canonicalize for multi-year)** |
| Event/round resolution current-season-only | 1 | A4 + A7 |
| Registry-backed schemas/dispatch: edit `TOOL_DEFINITIONS` misses most tools; `year` kwarg leak | 1 | **A6 (central schema inject + strip before registry dispatch)** |
| `get_season_schedule` can't take a year (empty schema, ignores args) | 2 | **A6b** |
| Entity extraction uses current roster before year work | 2 | **A7 (detect year first)** |
| `resolve_round` circular import | 2 | **A4 (lives in circuits_cache.py)** |
| RAG max-date post-filter can empty the set | 2 | **B5 (overfetch + bound)** |
| Static-audit test too narrow / false positives | 2 | **A3 (per-module + allowlists)** |
| Mixed-era single-year prompt | 2 | B3 |
| Unbounded session cache; cache read not LRU | 3 | **A2 (`_session_cache_get` move_to_end)** |
| Stale static style/car/RAG knowledge | 3 | B5 |
| ContextVar guardrails | 4 | A6/B6 |
| `args.pop` mutates shared dict | 2 | A6 (copy) |

Coverage: 2018→present data; 2022–2026 era rulebooks (pre-2022 = `legacy`, data-only, flagged).

---

# PART A — Multi-year data

## Task A1: Active-season primitive (token-based)
*(unchanged from rev.2)* `SEASON_MIN=2018`; `_ACTIVE_SEASON` ContextVar(default `CURRENT_YEAR`); `active_season()`, `set_season(year)->token`, `reset_season(token)`, `use_season(year)->token`. Token reset restores the exact prior value (safe nesting). Test set→reset round-trip. Commit `feat(f1_data): token-based active-season ContextVar`.

## Task A2: `_load_session` per-season + LRU cache (read + write paths)
**Files:** `server/f1_data.py:28,68,140`; Test `test_f1_data.py`
- [ ] **Tests:** (a) `use_season(2024)` → `fastf1.get_session` receives 2024; (b) over `_SESSION_CACHE_MAX=3`, the **least-recently-USED** key is evicted (insert 3, read key #1, insert a 4th → key #2 evicted, #1 survives).
- [ ] **Implement:** `_SESSION_CACHE = OrderedDict()`, `_SESSION_CACHE_MAX = 24`. Add **both**:
```python
def _session_cache_get(key):
    with _SESSION_CACHE_LOCK:
        e = _SESSION_CACHE.get(key)
        if e is not None: _SESSION_CACHE.move_to_end(key)   # true LRU (Codex Low)
        return e
def _session_cache_put(key, value):
    with _SESSION_CACHE_LOCK:
        _SESSION_CACHE[key] = value; _SESSION_CACHE.move_to_end(key)
        while len(_SESSION_CACHE) > _SESSION_CACHE_MAX:
            _SESSION_CACHE.popitem(last=False)
```
In `_load_session`: `season = active_season()`, `cache_key = (season, round_number, normalized_session)`, read via `_session_cache_get`, insert via `_session_cache_put`, `fastf1.get_session(season, …)`. Commit `feat(f1_data): per-season session cache with true-LRU eviction`.

## Task A3: Convert EVERY season-specific fetch + multi-module audit test
**Files:** `server/f1_data.py`, `server/openf1.py`; Test `test_f1_data.py`
- [ ] Convert `CURRENT_YEAR`→`active_season()` at all season-specific fetches: schedule (~181, 646, 1327), Jolpica (~1224, 1271, 1343, 1366, 1397, 1427), **`get_circuit_details` (~4831)**, **`get_circuit_track_map` (~4845)** (re-anchor its round validation + the `-1/-2/-3` fallback to `active_season()`).
- [ ] **`get_historical_circuit_performance` / `analyze_team_circuit_fit` (Codex F2 — partial-convert):** these walk a *window* of prior seasons, so distinguish two uses: (a) the **round→circuit identity anchor** (which circuit is round N — a season fetch) MUST become `active_season()`; (b) the **historical window** itself re-anchors to the active season (`[active_season()-2, active_season()-1, active_season()]`). So a 2024 circuit-profile query maps round→circuit in 2024 and looks at the 2022–2024 window. The deterministic **`_build_circuit_profile_tools`** caller passes the resolved `year` (so `execute_tool` sets the season for the call). Keep these out of the *generic* `year`-schema injection (they own a `years` array) but they DO honor `active_season()`. Allowlist only their genuinely-display/default lines in the audit, not the converted anchor.
- [ ] **Leave as current-season default (do NOT convert), ALLOWLIST:** the `CURRENT_YEAR` constant; `_session_year`; human-readable display strings.
- [ ] **Audit test (Codex Med — per-module, typed allowlist):**
```python
import re, pathlib, pytest
AUDIT = {
  "f1_data.py": {"fetch_ok": ("active_season(",),
                 "allow_lines": ("CURRENT_YEAR = ", "_session_year", "current-season",
                                 "def get_historical_circuit_performance", "def analyze_team_circuit_fit")},
  "openf1.py":  {"allow_lines": ("import",)},
}
@pytest.mark.parametrize("fname,rule", AUDIT.items())
def test_no_stray_current_year_fetch(fname, rule):
    # flag CURRENT_YEAR only when it's a fetch arg (get_session(/get_event_schedule(/JOLPICA url),
    # not prompt text / display / historical-window blocks
    src = pathlib.Path(fname).read_text().splitlines()
    bad = []
    in_allow_fn = False
    for i, ln in enumerate(src, 1):
        if any(a in ln for a in rule.get("allow_lines", ())):
            in_allow_fn = ln.strip().startswith("def "); continue
        if in_allow_fn and ln.strip() and not ln[0].isspace(): in_allow_fn = False
        if in_allow_fn: continue
        if "CURRENT_YEAR" in ln and re.search(r"get_session\(|get_event_schedule\(|JOLPICA_BASE\}/\{CURRENT_YEAR|year=CURRENT_YEAR", ln):
            bad.append(i)
    assert not bad, f"{fname}: un-converted season fetch at {bad}"
```
Commit `feat(f1_data,openf1): all season fetches honor active season (+typed audit test)`.

## Task A4: Season-keyed circuits + `resolve_round` (in circuits_cache.py — no cycle)
**Files:** `server/circuits_cache.py`, `server/f1_data.py` (`get_circuits(year)`, `get_drivers(year)`); Test `test_f1_data.py`
- [ ] **Tests:** `_cached_circuits(2024) != _cached_circuits(2026)`; `resolve_round(2024, country="Monaco")` reads the 2024 schedule.
- [ ] **Implement:** `get_circuits(year=None)` → `y = year or active_season()`. Season-keyed cache **and** `resolve_round` **both live in `circuits_cache.py`** (it already imports `f1_data` locally — keeps the cycle local; Codex Med):
```python
# circuits_cache.py
_by_year: dict[int, tuple[float, list[dict]]] = {}
def _cached_circuits(year: int | None = None) -> list[dict]:
    from f1_data import get_circuits, active_season
    y = year or active_season(); now = time.time(); hit = _by_year.get(y)
    if hit and now - hit[0] <= _CIRCUITS_CACHE_TTL: return hit[1]
    try: data = get_circuits(y); _by_year[y] = (now, data); return data
    except Exception: return hit[1] if hit else []
def clear_circuits_cache(): _by_year.clear()
def resolve_round(year: int, *, country: str | None = None, event_name: str | None = None) -> int | None:
    for c in _cached_circuits(year):
        if country and (c.get("country","").lower() == country.lower()): return c.get("round")
        if event_name and event_name.lower() in (c.get("event_name","").lower()): return c.get("round")
    return None
```
`f1_data` callers that need a round use `from circuits_cache import resolve_round` **inside the function** (local import). Commit `feat: season-keyed circuits cache + resolve_round (cycle-safe)`.

## Task A5: OpenF1 honors active season (query + circuit lookup)
*(rev.2)* `year=active_season()`; `_resolve_openf1_session` circuit lookup uses `_cached_circuits(active_season())`. Test + commit.

## Task A6: Per-call year — registry-aware dispatch + central schema injection  ← **Codex Sev-1**
**Files:** `server/tools.py` (`execute_tool` ~228, `_feature_to_anthropic_schema` ~323, `_feature_to_openai_schema` ~331), `server/chat.py`; Test `test_tools.py`, `test_chat.py`
- [ ] **Tests:**
```python
def test_execute_tool_season_per_call_immutable_args_registry(monkeypatch):
    import tools, f1_data
    seen = {}
    feat = tools._FEATURE_REGISTRY["analyze_qualifying_battle"]
    monkeypatch.setattr(feat, "execute", lambda **a: seen.update(season=f1_data.active_season(), got=dict(a)) or {"ok":1})
    args = {"round_number": 8, "driver_a":"VER", "driver_b":"NOR", "year": 2024}
    tools.execute_tool("analyze_qualifying_battle", args)
    assert seen["season"] == 2024 and "year" not in seen["got"]   # stripped before feat.execute (Codex High)
    assert f1_data.active_season() == f1_data.CURRENT_YEAR and "year" in args  # restored + not mutated

def test_season_tools_advertise_year_in_schema():
    import tools
    sch = next(t for t in tools.TOOL_DEFINITIONS if t["name"]=="analyze_qualifying_battle")
    assert "year" in sch["input_schema"]["properties"]
    sch2 = next(t for t in tools.TOOL_DEFINITIONS if t["name"]=="get_constructor_standings")
    assert "year" in sch2["input_schema"]["properties"]
```
- [ ] **Implement — `execute_tool` (registry-first, strip+season around BOTH paths):**
```python
def execute_tool(name: str, args: dict):
    from f1_data import set_season, reset_season
    args = args or {}
    year = args.get("year")
    call_args = {k: v for k, v in args.items() if k != "year"}   # copy; never mutate caller's dict
    token = set_season(year) if year is not None else None
    try:
        return _execute_tool_inner(name, call_args)   # the existing registry-first + legacy body
    finally:
        if token is not None: reset_season(token)
```
Rename the current body (registry dispatch at 233 + legacy if/elif) to `_execute_tool_inner(name, args)`. This wraps **both** the `feat.execute(**args)` path and the legacy path, and `year` is stripped so it never reaches `feat.execute` (Codex High).
- [ ] **Implement — central schema injection.** A tool gets `year` only if the ambient season actually changes its behavior. **Exclude** tools that read no season (pure static knowledge) OR that already have their own season/date handling (Codex Sev-1 — injecting `year` there is a silent no-op):
```python
_YEAR_NOT_INJECTED = {
    "get_driver_style_profile", "get_team_car_profile",      # pure static knowledge, no fetch
    "search_editorial_content",                              # has its own min_date/season window (B5)
    "get_historical_circuit_performance",                    # already takes an explicit `years` array
    "get_season_schedule",                                   # gets `year` via its own schema in A6b
}
```
In `_feature_to_anthropic_schema` / `_feature_to_openai_schema`, after building the schema, if `feat.name not in _YEAR_NOT_INJECTED`, inject:
```python
props = dict(schema_props); props.setdefault("year", {"type":"integer",
    "description": f"F1 season year ({SEASON_MIN}-{CURRENT_YEAR}); defaults to the season the question is about. Use different values in separate calls to compare seasons."})
```
Apply the same injection to the static `DEEP_ANALYSIS_TOOL_DEFINITIONS` / any non-registry `TOOL_DEFINITIONS` entries that are season-specific.
- [ ] **chat.py:** `answer_f1_payload`: `token = set_season(resolved.get("year") or CURRENT_YEAR)` … `finally: reset_season(token)`. `_execute_analysis_tool_calls`: **fresh `copy_context()` per future** — `executor.submit(contextvars.copy_context().run, _execute_analysis_tool_call, tn, a)`. **Preload season-safety (Codex F6):** `_preload_resolved_context` is also called directly from `_prepare_resolved_context_from_previous` (outside `answer_f1_payload`'s wrapper), so make it set/reset the season itself: `token = set_season(resolved.get("year") or CURRENT_YEAR)` around the suggested-tool call, `finally: reset_season(token)`. Concurrency test: two calls (2024/2025) → each its own season, no `RuntimeError`. Commit `feat: per-call season (registry-aware, immutable args, per-future context)`.

## Task A6b: `get_season_schedule` accepts a year  ← **Codex Sev-2**
**Files:** `server/features/lookups/schedule.py`; Test `test_features_lookups_schedule.py`
- [ ] **Test:** `SeasonScheduleFeature().execute(year=2024)` calls `f1_data.get_circuits(2024)`.
- [ ] **Implement:** `tool_schema.properties = {"year": {"type":"integer","description":"Season year; defaults to current."}}`; `def execute(self, **args): return f1_data.get_circuits(args.get("year"))`. (Now the agentic path can look up a past season's calendar/rounds, which A9's prompt instructs.) Commit `feat(features): get_season_schedule takes a year`.

## Task A7: Resolver — year(s) first, then year-aware entities + per-season round  ← **Codex Sev-1/2**
**Files:** `server/resolver.py`; Test `test_resolver.py`
- [ ] **Tests:** `_detect_years("verstappen 2024 vs 2025",2026)==[2024,2025]`; a 2024 query resolves the round against the 2024 schedule; a 2024 query's `_extract_entities_llm` receives the 2024 roster (mock `_cached_drivers(2024)`); single driver + two years sets `comparison_kind="same_entity_cross_year"`.
- [ ] **Implement (ORDER MATTERS — Codex Sev-2):** in `_base_context`, **detect `year`/`years` FIRST**, then call `_extract_entities_llm(message, year=primary_year)` and `_match_*` against `_cached_drivers(primary_year)` / `_cached_circuits(primary_year)` so historical rosters/calendars resolve. `_extract_entities_llm` gains a `year` param and builds its driver/circuit prompt from that season. Resolve `round_number` via `_cached_circuits(primary_year)`.
- [ ] **`_detect_analysis_mode` signature + call site (Codex F5):** change `_detect_analysis_mode(normalized, matched_drivers, session_type, matched_team=None)` → add `years: list[int] | None = None`; update its single call site in `_base_context` (~`resolver.py:512`) to pass `years=years` (computed just above by `_detect_years`). The `cross_year` branch lives inside `_detect_analysis_mode`, gated on `years` having two entries — so it needs the param.
- [ ] **Same-entity cross-year as a DEDICATED mode (Codex BLOCKER):** the existing `_detect_analysis_mode` returns `None` for `<2` distinct drivers and `_build_analysis_plan` bails on a null mode — so a single driver + two years has no path, and duplicating `entity_codes=[code,code]` would make battle tools do a `VER vs VER` *self-comparison within one season* (wrong). Instead, in `_detect_analysis_mode`, **before** the `< 2 matched_drivers` guard: if exactly **one** entity (driver or team) is matched AND `len(years) == 2`, return `analysis_mode = "cross_year"` (focus = single entity). Keep `entity_code`/`entity_name` SINGULAR (one driver), and carry `years=[y1,y2]`. The new `cross_year` mode drives a single-entity-per-year builder in A8 — never the two-driver battle tools.
- [ ] Merge: carry `year` forward only when `not year_explicit`. Commit `feat(resolver): detect season(s) first; year-aware entities; cross_year mode`.

## Task A8: `cross_year` builder — SINGLE-entity per-year tools + year-tagged widgets + bypass canonicalize  ← **Codex BLOCKER/HIGH**
**Files:** `server/chat.py` (`_build_analysis_plan` `cross_year` branch, `_try_deterministic_analysis`, `_widgets_from_analysis_evidence` + the affected `_make_*_widget`); Test `test_chat_plan_builder.py`, `test_chat.py`
- [ ] **Tests:** (a) a `cross_year` plan for one driver + `years=[2024,2025]` emits **single-entity** tool calls (`get_driver_season_stats` for a season scope, or `get_driver_race_story` per round for an event scope) — **two calls, one per year, same driver, distinct `year`** — and never a two-driver battle tool; (b) `_try_deterministic_analysis` skips `_canonicalize_qualifying_analysis`/`_canonicalize_race_pace_analysis` for a `cross_year` plan; (c) the two resulting widgets do **not** dedup-collapse (each carries its `year`).
- [ ] **Implement:**
  - New `_build_cross_year_plan(message, resolved)` branch in `_build_analysis_plan` (matched on `analysis_mode == "cross_year"`): for each `y in resolved["years"]`, emit single-entity tool calls with `year=y`:
    - season scope → `("get_driver_season_stats", {"driver_name": name, "year": y})`;
    - event scope (a circuit/country named) → `("get_driver_race_story", {"round_number": resolve_round(y, country=…/event_name=…), "driver_name": name, "session_type": session, "year": y})`.
    Resolve the round **per year** (rounds differ across calendars). Never duplicate the entity into battle tools.
  - In `_try_deterministic_analysis`: if `resolved.get("analysis_mode")=="cross_year"` (or any plan with ≥2 distinct `year`s in its tool_calls), **skip the canonicalizers** (they pick the first year via `_find_evidence_result`) and pass the full multi-year evidence to the answer writer. Add the analyzed `years` to the answer-writer/analysis input so it narrates both seasons.
  - **Widget de-dup fix — plumb at `_registry_widget`, embed in title (Codex F3/F7):** `_widgets_from_analysis_evidence` dedups on `(type, title, subtitle)`, and `_registry_widget(tool, result)` (`chat.py:234`) currently drops `item["args"]["year"]` before `feat.make_widget(result)`. Change `_widgets_from_analysis_evidence` to pass the evidence item's `args["year"]` into `_registry_widget`, which copies it onto `result` (e.g. `result = {**result, "_year": year}`) before `make_widget`. Each season-specific `make_widget` then **embeds the year in the existing `title`/`subtitle` STRING** (e.g. `"VER — 2024"`), NOT as a bare field — so dedup keeps both seasons and the **frontend needs no change** (it already renders title/subtitle). Add a test for the cross-year `get_driver_race_story` widget path producing two distinct-title widgets.
  - **Skip preload for multi-year (Codex F1 BLOCKER):** in `answer_f1_payload`/`_preload_resolved_context`, **return no preload** when `resolved.get("analysis_mode")=="cross_year"` or `len(resolved.get("years",[]))>1` — otherwise the single high-confidence `_suggested_tool_args` preload (no `year` support) injects one **current-year** result into the prompt and poisons the comparison. When falling through to the agentic loop, the system prompt (A9) already tells the model to call single-entity tools per-year with explicit `year`.
  - If a `cross_year` plan can't be built cleanly, **return None → agentic fallback** (the agentic loop calls single-entity tools per-year with explicit `year`; preferred over a wrong single-year answer).
- [ ] Commit `feat(chat): cross_year single-entity per-year analysis (year-tagged widgets, no single-year canonicalize)`.

## Task A9: Unsupported-season guard + multi-year prompt
*(rev.2)* Explicit out-of-range year → `needs_clarification="season_unsupported"`. `SYSTEM_PROMPT`: *"Answer about any season {SEASON_MIN}–{CURRENT_YEAR} (current {CURRENT_YEAR}). Pass `year` on tools to choose a season; use different `year` values in separate calls to compare seasons. Call get_season_schedule with a `year` to find that season's rounds. Telemetry starts {SEASON_MIN}."* Commit.

---

# PART B — Regulation-era awareness (2022–2026)

## Task B1: `regulations.py` era registry
*(rev.2)* `era_for_year`, `era_knowledge(year)`, `tool_applies(tool,year)` (gates `analyze_active_aero_usage`/`analyze_override_usage` to ≥2026). Commit.

## Task B2: `energy_ground_effect.py` (2022–2025)
*(rev.2)* Mirror `energy_2026`'s dict shape for the DRS/MGU-H/120 kW era. Commit.

## Task B3: Analysis prompt injects era(s) — mixed-era aware
*(rev.2)* `_build_analysis_system_prompt(years: list[int])`; single-year → that era (2026-only sections gated behind `era_for_year==NEW_REGS_2026`); two eras → per-year rulebook map + "qualify every regulation mechanism by season; never attribute a 2026 concept to a pre-2026 season". `ANALYSIS_SYSTEM_PROMPT` becomes a per-request build; thread `years` through `_run_*_analysis`. **Required test update (Codex LOW):** `server/tests/test_chat.py` (~1127-1128) asserts on the module constant `chat.ANALYSIS_SYSTEM_PROMPT`; keep a back-compat module-level `ANALYSIS_SYSTEM_PROMPT = _build_analysis_system_prompt([CURRENT_YEAR])` for default single-current-year use, and update that test to call `_build_analysis_system_prompt([2024])` / `([2025,2026])` for the era assertions. Commit.

## Task B4: Gate 2026-only tools + per-year roster
*(rev.2)* 2026-only fns short-circuit with `{"available":False,"guidance_for_model":"… is a 2026 regulation; not applicable to {year}."}` when `not tool_applies(name, active_season())`. `_cached_drivers()` keys by + fetches `active_season()`. Commit.

## Task B5: Season-scope editorial RAG + flag off-era static knowledge  ← **Codex Sev-2/3**
**Files:** `server/editorial/relevance.py`, `server/editorial/search.py`, `server/editorial/client.py`, `server/chat.py` (`_retrieve_analysis_evidence`); Test `test_editorial_relevance.py`, `test_chat.py`
- [ ] **B5a — `max_published` is a REQUIRED migration (Codex Med — NOT optional; sending an unknown RPC arg makes PostgREST return `[]`):** add a Supabase migration that recreates `match_article_chunks` with a `max_published timestamptz default null` filter symmetric to `min_published`; add `max_published` to `call_match_chunks` payload and `max_date` to `fts_search_articles` (`gte`+`lte`). Apply via `apply_migration`. The overfetch (`RETRIEVAL_LIMIT*3` then post-filter) stays as a **best-effort** belt-and-suspenders, explicitly NOT a substitute for the bound. Commit `feat(editorial): max_published bound in hybrid search RPC + client`.
- [ ] **B5b — fix the latent subject-filter no-op (Codex Med):** `build_resolver_subject_set` (`relevance.py:47`) reads `resolved["drivers"]`/`["team"]`/`["circuit_slug"]` — keys the resolver **never emits** (it emits `entity_codes`, `entity_type`/`entity_name`, `country`/`event_name`), so subject filtering is currently a silent no-op even pre-multi-year. Rewrite it to read the real keys: drivers from `entity_codes`, team from `entity_type=="team"`+`entity_name`, circuit from `country`/`event_name`. Add a test that a resolved driver query produces a non-empty subject set. Commit `fix(editorial): subject filter reads real resolver keys`.
- [ ] **B5c — season window (multi-year aware, Codex F4) + off-era static knowledge:** `gated_editorial_lookup(question, resolved, analysis_mode)` derives the window from **all** analyzed seasons: `ys = resolved.get("years") or [resolved.get("year") or CURRENT_YEAR]`; `min_date = f"{min(ys)}-01-01"`, `max_date = f"{max(ys)+1}-12-31"` (a presser early next year still discusses the prior season). A single window spanning `min(years)…max(years)+1` covers a 2024-vs-2025 comparison; passes both bounds to search. Tag injected `driver_style_comparison`/team-car/circuit-profile evidence with `season_validity` (e.g. `"current_era_only"`) + an analysis-prompt rule to weigh/omit them when the analyzed year is off-era (degrade to "no profile", never fabricate). Tests: a 2026-dated article is excluded from a 2024 query; style evidence carries `season_validity`. Commit `feat: season-scoped editorial RAG + off-era static-knowledge flag`.

## Task B6: Integration + concurrency smokes
*(rev.2)* INTEGRATION-gated: 2024 story = DRS not active-aero/override; 2024-vs-2025 returns both, correct round per year, era-correct; **two simultaneous different-year requests** through the threadpool → no leakage / no `RuntimeError`. Commit.

---

## Self-Review (vs both Codex reviews)
- **Every Sev-1 closed:** per-future `copy_context`+token reset (A6); same-entity cross-year detection (A7) → paired per-year deterministic calls (A8) → **canonicalizers bypassed for multi-year** (A8); per-season round resolution (A4/A7); **registry-aware** dispatch with `year` stripped before `feat.execute` + **central schema injection** (A6).
- **Sev-2 closed:** `get_season_schedule` year (A6b); year-detection-before-entity-extraction (A7); `resolve_round` placed in `circuits_cache.py` to avoid the cycle (A4); RAG overfetch+bound (B5); per-module typed audit allowlisting historical-window logic (A3); mixed-era prompt (B3); immutable args (A6).
- **Sev-3/4 closed:** true-LRU `_session_cache_get`/`_put` (A2); off-era static-knowledge flagging (B5); concurrency + audit tests (A6/A3/B6).
- **Sequencing:** Part A ships correct multi-year data + cross-year alone; Part B adds era-correct narration. Do A → B6 concurrency smoke → B.
- **Two landmines still called out loudest:** (1) one copied context **per future**, never shared; (2) `year` must be stripped before BOTH the registry `feat.execute(**args)` and the legacy dispatch, with a token-reset `finally`.
