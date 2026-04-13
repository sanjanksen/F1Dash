# F1Dash Backend Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix ten backend issues in the F1Dash Python server: deprecated FastF1 API calls, dead code, resolver routing bugs, missing comparison phrases, team alias gaps, standings routing, agent round limits, CORS config, and raw exception leakage.

**Architecture:** All fixes are in-place edits to `server/` files. No new modules. Tests live in `server/tests/` and use `pytest` with `unittest.mock`. Each task is independently testable and committable.

**Tech Stack:** Python 3.11+, FastF1 3.8.2, FastAPI, pytest 8.3.3

---

## File Map

| File | Changes |
|------|---------|
| `server/f1_data.py` | Add `_pick_driver` helper (line ~178); replace 12 `pick_driver` call sites; remove dead code lines 254-257 |
| `server/resolver.py` | Expand circuit alias map; add `session_type` param to `_suggest_tool`; new comparison phrases; team alias; standings scope |
| `server/chat.py` | Bump `MAX_TOOL_ROUNDS` from 5 → 8 |
| `server/main.py` | Read CORS origins from env var; sanitize exception detail strings |
| `server/openf1.py` | Fix `get_intervals` to sample evenly across the race |
| `server/tests/test_f1_data.py` | Tests for `_pick_driver` helper |
| `server/tests/test_resolver.py` | Tests for circuit aliases, session_type routing, comparison phrases, standings routing |

---

### Task 1: Add `_pick_driver` helper and replace all deprecated call sites

FastF1 3.8.x deprecated `Laps.pick_driver(code)` → `Laps.pick_drivers([code])`. There are 12 call sites in `f1_data.py`. Add a single compatibility helper and replace all sites.

**Files:**
- Modify: `server/f1_data.py`
- Test: `server/tests/test_f1_data.py`

- [ ] **Step 1: Write the failing tests**

Add to `server/tests/test_f1_data.py`:

```python
from unittest.mock import MagicMock
import f1_data


def test_pick_driver_uses_pick_drivers_when_available():
    """3.8+ path: delegates to pick_drivers([code])."""
    mock_laps = MagicMock()
    mock_result = MagicMock()
    mock_laps.pick_drivers.return_value = mock_result
    result = f1_data._pick_driver(mock_laps, 'VER')
    mock_laps.pick_drivers.assert_called_once_with(['VER'])
    assert result is mock_result


def test_pick_driver_falls_back_to_pick_driver():
    """Pre-3.8 fallback: calls pick_driver(code) when pick_drivers absent."""
    mock_laps = MagicMock(spec=['pick_driver'])
    mock_result = MagicMock()
    mock_laps.pick_driver.return_value = mock_result
    result = f1_data._pick_driver(mock_laps, 'NOR')
    mock_laps.pick_driver.assert_called_once_with('NOR')
    assert result is mock_result


def test_pick_driver_coerces_code_to_string():
    """Code arg is always stringified before passing through."""
    mock_laps = MagicMock()
    f1_data._pick_driver(mock_laps, 44)  # int driver number
    mock_laps.pick_drivers.assert_called_once_with(['44'])
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd server && python -m pytest tests/test_f1_data.py::test_pick_driver_uses_pick_drivers_when_available tests/test_f1_data.py::test_pick_driver_falls_back_to_pick_driver tests/test_f1_data.py::test_pick_driver_coerces_code_to_string -v
```

Expected: `AttributeError: module 'f1_data' has no attribute '_pick_driver'`

- [ ] **Step 3: Add `_pick_driver` helper to `f1_data.py`**

Insert after `_pick_fastest_lap` (after line 340, before `_fetch_all_races`):

```python
def _pick_driver(laps, code: str):
    """Call pick_drivers([code]) (FastF1 3.8+) or fall back to pick_driver(code)."""
    pick = getattr(laps, 'pick_drivers', None)
    if callable(pick):
        return pick([str(code)])
    return laps.pick_driver(str(code))
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
cd server && python -m pytest tests/test_f1_data.py::test_pick_driver_uses_pick_drivers_when_available tests/test_f1_data.py::test_pick_driver_falls_back_to_pick_driver tests/test_f1_data.py::test_pick_driver_coerces_code_to_string -v
```

Expected: all 3 PASSED

- [ ] **Step 5: Replace all 12 `pick_driver` call sites in `f1_data.py`**

Run this grep to find all lines before editing:

```bash
grep -n "\.pick_driver(" server/f1_data.py
```

Make these replacements (use exact context to locate each, lines shown are approximate):

**Site 1 – line ~650** (clean pace loop):
```python
# OLD:
driver_laps = session.laps.pick_driver(driver_code)
# NEW:
driver_laps = _pick_driver(session.laps, driver_code)
```

**Site 2 – line ~694** (sector comparison):
```python
# OLD:
driver_laps = session.laps.pick_driver(driver_code.upper())
# NEW:
driver_laps = _pick_driver(session.laps, driver_code.upper())
```

**Site 3 – line ~733** (head-to-head summarize_driver):
```python
# OLD:
driver_laps = session.laps.pick_driver(code.upper())
# NEW:
driver_laps = _pick_driver(session.laps, code.upper())
```

**Site 4 – lines ~1362–1366** (live timeline guard + loop):
```python
# OLD:
drivers = getattr(laps, 'pick_driver', None)
if not callable(drivers):
    continue
for code in session.drivers:
    driver_laps = laps.pick_driver(code)
# NEW (remove the guard, just use helper):
for code in session.drivers:
    driver_laps = _pick_driver(laps, code)
```

**Site 5 – line ~1433** (driver race story laps):
```python
# OLD:
laps = session.laps.pick_driver(code)
# NEW:
laps = _pick_driver(session.laps, code)
```

**Site 6 – line ~1516** (lap telemetry fastest):
```python
# OLD:
laps = session.laps.pick_driver(code.upper())
# NEW:
laps = _pick_driver(session.laps, code.upper())
```

**Site 7 – line ~1601** (track position driver laps):
```python
# OLD:
driver_laps = session.laps.pick_driver(driver_code.upper())
# NEW:
driver_laps = _pick_driver(session.laps, driver_code.upper())
```

**Site 8 – line ~1673** (get lap telemetry driver laps):
```python
# OLD:
laps = session.laps.pick_driver(code.upper())
# NEW:
laps = _pick_driver(session.laps, code.upper())
```

**Site 9 – line ~1919** (qualifying battle segment laps):
```python
# OLD:
driver_laps = segment_laps.pick_driver(code.upper())
# NEW:
driver_laps = _pick_driver(segment_laps, code.upper())
```

**Site 10 – line ~2502** (pit stop loop):
```python
# OLD:
for _, lap in laps.pick_driver(str(driver_code)).iterrows():
# NEW:
for _, lap in _pick_driver(laps, str(driver_code)).iterrows():
```

**Site 11 – line ~2588** (track position comparison):
```python
# OLD:
laps = session.laps.pick_driver(code.upper())
# NEW:
laps = _pick_driver(session.laps, code.upper())
```

- [ ] **Step 6: Verify no remaining pick_driver calls**

```bash
grep -n "\.pick_driver(" server/f1_data.py
```

Expected: no output (zero matches)

- [ ] **Step 7: Run full test suite**

```bash
cd server && python -m pytest tests/ -v --tb=short 2>&1 | tail -20
```

Expected: all tests that were passing before still pass.

- [ ] **Step 8: Commit**

```bash
git add server/f1_data.py server/tests/test_f1_data.py
git commit -m "fix: replace deprecated pick_driver with pick_drivers (FastF1 3.8 compat)"
```

---

### Task 2: Remove dead code in `_infer_clipping_windows`

Lines 254-257 in `f1_data.py` are unreachable — they appear after `return windows` inside `_infer_clipping_windows`. They are an orphaned copy of the `_normalize_float` body. Delete them.

**Files:**
- Modify: `server/f1_data.py`

- [ ] **Step 1: Locate the dead code**

```bash
sed -n '250,260p' server/f1_data.py
```

You should see:
```
    return windows
    try:
        return round(float(value), 3)
    except (TypeError, ValueError):
        return None


def _safe_timedelta_seconds(value):
```

- [ ] **Step 2: Delete lines 254-257 (the 4 unreachable lines)**

In `server/f1_data.py`, find and remove these exact lines **inside** `_infer_clipping_windows`, immediately after `return windows`:

```python
    try:
        return round(float(value), 3)
    except (TypeError, ValueError):
        return None
```

The function should end cleanly as:
```python
def _infer_clipping_windows(samples: list[dict], speed_key: str = "speed_kph") -> list[dict]:
    windows = []
    for window in _find_full_throttle_straight_windows(samples):
        start = window[0]
        end = window[-1]
        start_speed = start.get(speed_key)
        end_speed = end.get(speed_key)
        if start_speed is None or end_speed is None:
            continue
        mid = window[len(window) // 2]
        mid_speed = mid.get(speed_key)
        gain = round(end_speed - start_speed, 1)
        if gain < 12 or (mid_speed is not None and end_speed < mid_speed):
            windows.append({
                "start_distance_m": start.get("distance_m"),
                "end_distance_m": end.get("distance_m"),
                "start_speed_kph": start_speed,
                "end_speed_kph": end_speed,
                "mid_speed_kph": mid_speed,
                "speed_gain_kph": gain,
                "late_straight_drop_kph": round(end_speed - mid_speed, 1) if mid_speed is not None else None,
            })
    return windows
```

- [ ] **Step 3: Run tests**

```bash
cd server && python -m pytest tests/ -v --tb=short 2>&1 | tail -10
```

Expected: all previously passing tests still pass.

- [ ] **Step 4: Commit**

```bash
git add server/f1_data.py
git commit -m "fix: remove unreachable dead code in _infer_clipping_windows"
```

---

### Task 3: Expand circuit alias map

`_match_event` in `resolver.py` has `alias_map` with only 9 entries. Common circuit nicknames like "Montreal", "Sakhir", "Budapest", and "Spielberg" fall through to token matching, which fails for names not present in any circuit field. Add the missing aliases.

**Files:**
- Modify: `server/resolver.py`
- Test: `server/tests/test_resolver.py`

- [ ] **Step 1: Write failing tests**

Add to `server/tests/test_resolver.py`:

```python
@patch('resolver.get_drivers')
@patch('resolver.get_circuits')
def test_match_event_montreal(mock_circuits, mock_drivers):
    mock_drivers.return_value = []
    mock_circuits.return_value = [
        {"round": 9, "event_name": "Canadian Grand Prix", "circuit_name": "Circuit Gilles Villeneuve", "country": "Canada"},
    ]
    result = resolver.resolve_query_context("What happened at Montreal this year?")
    assert result["round_number"] == 9


@patch('resolver.get_drivers')
@patch('resolver.get_circuits')
def test_match_event_sakhir(mock_circuits, mock_drivers):
    mock_drivers.return_value = []
    mock_circuits.return_value = [
        {"round": 1, "event_name": "Bahrain Grand Prix", "circuit_name": "Bahrain International Circuit", "country": "Bahrain"},
    ]
    result = resolver.resolve_query_context("Tell me about the Sakhir race")
    assert result["round_number"] == 1


@patch('resolver.get_drivers')
@patch('resolver.get_circuits')
def test_match_event_budapest(mock_circuits, mock_drivers):
    mock_drivers.return_value = []
    mock_circuits.return_value = [
        {"round": 13, "event_name": "Hungarian Grand Prix", "circuit_name": "Hungaroring", "country": "Hungary"},
    ]
    result = resolver.resolve_query_context("How was the race in Budapest?")
    assert result["round_number"] == 13


@patch('resolver.get_drivers')
@patch('resolver.get_circuits')
def test_match_event_spielberg(mock_circuits, mock_drivers):
    mock_drivers.return_value = []
    mock_circuits.return_value = [
        {"round": 11, "event_name": "Austrian Grand Prix", "circuit_name": "Red Bull Ring", "country": "Austria"},
    ]
    result = resolver.resolve_query_context("What happened at the Red Bull Ring in Spielberg?")
    assert result["round_number"] == 11
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd server && python -m pytest tests/test_resolver.py::test_match_event_montreal tests/test_resolver.py::test_match_event_sakhir tests/test_resolver.py::test_match_event_budapest tests/test_resolver.py::test_match_event_spielberg -v
```

Expected: all FAIL (round_number is None)

- [ ] **Step 3: Expand the alias_map in `resolver.py`**

Find the `alias_map` dict inside `_match_event` and replace it with:

```python
alias_map = {
    "suzuka": "japan",
    "japanese gp": "japan",
    "japanese grand prix": "japan",
    "monza": "italy",
    "spa": "belgium",
    "silverstone": "britain",
    "interlagos": "brazil",
    "yas marina": "abu dhabi",
    "cota": "united states",
    "imola": "emilia romagna",
    # Additional circuit nicknames
    "montreal": "canada",
    "villeneuve": "canada",
    "sakhir": "bahrain",
    "albert park": "australia",
    "budapest": "hungary",
    "spielberg": "austria",
    "red bull ring": "austria",
    "marina bay": "singapore",
    "lusail": "qatar",
    "baku": "azerbaijan",
    "jeddah": "saudi arabia",
    "las vegas": "las vegas",
    "mexico city": "mexico",
    "autodromo hermanos rodriguez": "mexico",
    "circuit de barcelona": "spain",
    "barcelona": "spain",
    "catalunya": "spain",
    "zandvoort": "netherlands",
}
```

- [ ] **Step 4: Run the new tests**

```bash
cd server && python -m pytest tests/test_resolver.py::test_match_event_montreal tests/test_resolver.py::test_match_event_sakhir tests/test_resolver.py::test_match_event_budapest tests/test_resolver.py::test_match_event_spielberg -v
```

Expected: all 4 PASSED

- [ ] **Step 5: Run full resolver tests**

```bash
cd server && python -m pytest tests/test_resolver.py -v --tb=short
```

Expected: all previously passing tests still pass.

- [ ] **Step 6: Commit**

```bash
git add server/resolver.py server/tests/test_resolver.py
git commit -m "fix: expand circuit alias map with 18 additional venue nicknames"
```

---

### Task 4: Fix `_suggest_tool` to respect qualifying session type

When `session_type == "Q"` but `scope == "strategy"` or `scope == "safety_car"`, `_suggest_tool` currently returns `get_driver_race_story` — a race-only tool. The fix: pass `session_type` into `_suggest_tool` and prefer `get_driver_weekend_overview` for qualifying queries.

**Files:**
- Modify: `server/resolver.py`
- Test: `server/tests/test_resolver.py`

- [ ] **Step 1: Write the failing test**

Add to `server/tests/test_resolver.py`:

```python
@patch('resolver.get_drivers')
@patch('resolver.get_circuits')
def test_suggest_tool_qualifying_strategy_not_race_story(mock_circuits, mock_drivers):
    """Qualifying scope with 'strategy' keyword must NOT route to get_driver_race_story."""
    mock_drivers.return_value = [
        {"full_name": "Lewis Hamilton", "code": "HAM", "driver_id": "hamilton", "team": "Ferrari"},
    ]
    mock_circuits.return_value = [
        {"round": 3, "event_name": "Japanese Grand Prix", "circuit_name": "Suzuka", "country": "Japan"},
    ]
    result = resolver.resolve_query_context("What was Hamilton's qualifying strategy at Suzuka?")
    assert result["session_type"] == "Q"
    assert result["suggested_tool"] != "get_driver_race_story"
```

- [ ] **Step 2: Run test to confirm it fails**

```bash
cd server && python -m pytest tests/test_resolver.py::test_suggest_tool_qualifying_strategy_not_race_story -v
```

Expected: FAIL — `suggested_tool` is currently `get_driver_race_story`

- [ ] **Step 3: Update `_suggest_tool` to accept and use `session_type`**

Replace the entire `_suggest_tool` function in `resolver.py`:

```python
def _suggest_tool(entity_type: str | None, scope: str | None, session_type: str | None = None) -> str | None:
    if scope == "radio":
        return "get_team_radio"
    if scope == "energy":
        return "analyze_energy_management"
    # Note: scope == "standings" is handled inline in _base_context (Task 7) because
    # it needs the raw normalized message to distinguish driver vs constructor.
    if entity_type == "driver":
        # Qualifying questions must not route to race-only tools
        if session_type == "Q":
            return "get_driver_weekend_overview"
        if scope in ("overview", "strategy", "safety_car"):
            return "get_driver_race_story"
        return "get_driver_weekend_overview"
    if entity_type == "team":
        return "get_team_weekend_overview"
    if scope == "race_report":
        return "get_race_report"
    if scope == "safety_car":
        return "get_safety_car_periods"
    return None
```

- [ ] **Step 4: Update all `_suggest_tool` call sites in `resolver.py` to pass `session_type`**

There are two call sites. Find and update both:

**In `_base_context`** — replace:
```python
"suggested_tool": _suggest_tool(entity_type, scope),
```
with:
```python
"suggested_tool": _suggest_tool(entity_type, scope, session_type),
```

**In `_merge_with_previous_context`** — replace:
```python
merged["suggested_tool"] = _suggest_tool(merged.get("entity_type"), merged.get("scope"))
```
with:
```python
merged["suggested_tool"] = _suggest_tool(merged.get("entity_type"), merged.get("scope"), merged.get("session_type"))
```

- [ ] **Step 5: Run all resolver tests**

```bash
cd server && python -m pytest tests/test_resolver.py -v --tb=short
```

Expected: all tests pass including the new one.

- [ ] **Step 6: Commit**

```bash
git add server/resolver.py server/tests/test_resolver.py
git commit -m "fix: pass session_type to _suggest_tool to prevent qualifying queries routing to race-only tools"
```

---

### Task 5: Add comparison phrases to `_detect_analysis_mode`

"outqualify", "outperform", "gap between", "time difference", and "how much did" are common comparison phrases that don't trigger the two-driver comparison path. Add them.

**Files:**
- Modify: `server/resolver.py`
- Test: `server/tests/test_resolver.py`

- [ ] **Step 1: Write failing tests**

Add to `server/tests/test_resolver.py`:

```python
@patch('resolver.get_drivers')
@patch('resolver.get_circuits')
def test_detect_analysis_mode_outqualify(mock_circuits, mock_drivers):
    mock_drivers.return_value = [
        {"full_name": "Lando Norris", "code": "NOR", "driver_id": "norris", "team": "McLaren"},
        {"full_name": "Charles Leclerc", "code": "LEC", "driver_id": "leclerc", "team": "Ferrari"},
    ]
    mock_circuits.return_value = [
        {"round": 3, "event_name": "Japanese Grand Prix", "circuit_name": "Suzuka", "country": "Japan"},
    ]
    result = resolver.resolve_query_context("How did Norris outqualify Leclerc at Suzuka?")
    assert result["analysis_mode"] == "driver_comparison"
    assert result["analysis_focus"] == "qualifying"


@patch('resolver.get_drivers')
@patch('resolver.get_circuits')
def test_detect_analysis_mode_gap_between(mock_circuits, mock_drivers):
    mock_drivers.return_value = [
        {"full_name": "Max Verstappen", "code": "VER", "driver_id": "verstappen", "team": "Red Bull"},
        {"full_name": "Lando Norris", "code": "NOR", "driver_id": "norris", "team": "McLaren"},
    ]
    mock_circuits.return_value = [
        {"round": 3, "event_name": "Japanese Grand Prix", "circuit_name": "Suzuka", "country": "Japan"},
    ]
    result = resolver.resolve_query_context("What was the gap between Verstappen and Norris in the race at Suzuka?")
    assert result["analysis_mode"] == "driver_comparison"
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd server && python -m pytest tests/test_resolver.py::test_detect_analysis_mode_outqualify tests/test_resolver.py::test_detect_analysis_mode_gap_between -v
```

Expected: FAIL — `analysis_mode` is None

- [ ] **Step 3: Add missing phrases to `_detect_analysis_mode`**

In `resolver.py`, find the `comparison_language` variable inside `_detect_analysis_mode` and replace it:

```python
comparison_language = any(phrase in normalized for phrase in (
    "compare", "compared", "comparison", "vs", "versus", "faster than", "slower than",
    "beat", "ahead of", "edge", "advantage", "where did", "how did", "why did",
    "gain time", "lose time", "quicker than", "better than",
    "outqualif", "outperform", "outpace", "outrun",
    "gap between", "difference between", "time difference", "delta between",
    "how much did", "which driver", "who was quicker", "who was faster",
))
```

- [ ] **Step 4: Run the new tests**

```bash
cd server && python -m pytest tests/test_resolver.py::test_detect_analysis_mode_outqualify tests/test_resolver.py::test_detect_analysis_mode_gap_between -v
```

Expected: both PASSED

- [ ] **Step 5: Run full resolver test suite**

```bash
cd server && python -m pytest tests/test_resolver.py -v --tb=short
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add server/resolver.py server/tests/test_resolver.py
git commit -m "fix: add outqualify/gap between/difference between to comparison detection in resolver"
```

---

### Task 6: Add 2026 team alias for Audi / Sauber rebrand

The team alias map in `resolver.py` still lists "sauber" but not "audi". For 2026 the team rebranded. Add "audi" as an alias that resolves to whichever team name appears in the driver data.

**Files:**
- Modify: `server/resolver.py`

- [ ] **Step 1: Add `"audi"` to the aliases dict in `_match_team`**

Find the `aliases` dict in `_match_team` and add two entries:

```python
aliases = {
    "merc": "Mercedes",
    "mercedes": "Mercedes",
    "ferrari": "Ferrari",
    "mclaren": "McLaren",
    "red bull": "Red Bull",
    "rb": "RB",
    "aston": "Aston Martin",
    "alpine": "Alpine",
    "haas": "Haas F1 Team",
    "sauber": "Kick Sauber",
    "audi": "Audi",           # 2026 rebrand
    "kick sauber": "Kick Sauber",
    "williams": "Williams",
}
```

- [ ] **Step 2: Run tests**

```bash
cd server && python -m pytest tests/test_resolver.py -v --tb=short 2>&1 | tail -10
```

Expected: all tests pass.

- [ ] **Step 3: Commit**

```bash
git add server/resolver.py
git commit -m "fix: add Audi team alias for 2026 Sauber rebrand"
```

---

### Task 7: Add standings scope detection and routing

Questions like "who leads the championship?" and "show me the constructor standings" currently have no routing. Add a "standings" scope, detect it from keywords, and route to the correct standings tool.

**Files:**
- Modify: `server/resolver.py`
- Test: `server/tests/test_resolver.py`

- [ ] **Step 1: Write failing tests**

Add to `server/tests/test_resolver.py`:

```python
@patch('resolver.get_drivers')
@patch('resolver.get_circuits')
def test_standings_scope_driver(mock_circuits, mock_drivers):
    mock_drivers.return_value = []
    mock_circuits.return_value = []
    result = resolver.resolve_query_context("Who leads the championship?")
    assert result["scope"] == "standings"
    assert result["suggested_tool"] == "get_driver_standings"


@patch('resolver.get_drivers')
@patch('resolver.get_circuits')
def test_standings_scope_constructor(mock_circuits, mock_drivers):
    mock_drivers.return_value = []
    mock_circuits.return_value = []
    result = resolver.resolve_query_context("What are the constructor standings?")
    assert result["scope"] == "standings"
    assert result["suggested_tool"] == "get_constructor_standings"


@patch('resolver.get_drivers')
@patch('resolver.get_circuits')
def test_standings_scope_points_table(mock_circuits, mock_drivers):
    mock_drivers.return_value = []
    mock_circuits.return_value = []
    result = resolver.resolve_query_context("Show me the points table")
    assert result["scope"] == "standings"
    assert result["suggested_tool"] == "get_driver_standings"
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd server && python -m pytest tests/test_resolver.py::test_standings_scope_driver tests/test_resolver.py::test_standings_scope_constructor tests/test_resolver.py::test_standings_scope_points_table -v
```

Expected: all FAIL

- [ ] **Step 3: Add standings detection to `_detect_session_scope` in `resolver.py`**

At the end of the `scope` detection block in `_detect_session_scope`, after the radio detection, add:

```python
if any(phrase in normalized for phrase in (
    "standings", "championship", "who leads", "points table",
    "leaderboard", "points leader", "championship leader",
)):
    scope = "standings"
```

The full end of the scope detection block now looks like:
```python
if re.search(r"\bradio\b", normalized) or "team radio" in normalized or "on the radio" in normalized:
    scope = "radio"
if any(phrase in normalized for phrase in (
    "standings", "championship", "who leads", "points table",
    "leaderboard", "points leader", "championship leader",
)):
    scope = "standings"
```

- [ ] **Step 4: Add standings routing inline in `_base_context` in `resolver.py`**

`_suggest_tool` doesn't have access to the raw normalized message, which is needed to distinguish "driver standings" from "constructor standings". Handle this inline in `_base_context`.

Replace the line:
```python
"suggested_tool": _suggest_tool(entity_type, scope, session_type),
```

with a two-step computation immediately before the return dict:
```python
if scope == "standings":
    _is_constructor = any(w in normalized for w in ("constructor", "team standings", "constructors"))
    _suggested_tool = "get_constructor_standings" if _is_constructor else "get_driver_standings"
else:
    _suggested_tool = _suggest_tool(entity_type, scope, session_type)
```

And in the return dict use `_suggested_tool`:
```python
"suggested_tool": _suggested_tool,
```

Also update `_merge_with_previous_context` to apply the same logic. Find:
```python
if merged.get("suggested_tool") is None:
    merged["suggested_tool"] = _suggest_tool(merged.get("entity_type"), merged.get("scope"))
```

Replace with:
```python
if merged.get("suggested_tool") is None:
    if merged.get("scope") == "standings":
        _is_constructor = any(w in (merged.get("normalized_message") or "") for w in ("constructor", "team standings", "constructors"))
        merged["suggested_tool"] = "get_constructor_standings" if _is_constructor else "get_driver_standings"
    else:
        merged["suggested_tool"] = _suggest_tool(merged.get("entity_type"), merged.get("scope"), merged.get("session_type"))
```

- [ ] **Step 5: Run the new tests**

```bash
cd server && python -m pytest tests/test_resolver.py::test_standings_scope_driver tests/test_resolver.py::test_standings_scope_constructor tests/test_resolver.py::test_standings_scope_points_table -v
```

Expected: all 3 PASSED

- [ ] **Step 6: Run full resolver suite**

```bash
cd server && python -m pytest tests/test_resolver.py -v --tb=short
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add server/resolver.py server/tests/test_resolver.py
git commit -m "feat: add standings scope detection and routing to driver/constructor standings tools"
```

---

### Task 8: Increase MAX_TOOL_ROUNDS from 5 to 8

Complex multi-step questions (e.g., "compare Hamilton and Norris at Suzuka") can exhaust the 5-round limit before the LLM finishes reasoning. Raise to 8.

**Files:**
- Modify: `server/chat.py`

- [ ] **Step 1: Change the constant**

In `server/chat.py` line 17, change:
```python
MAX_TOOL_ROUNDS = 5
```
to:
```python
MAX_TOOL_ROUNDS = 8
```

- [ ] **Step 2: Run chat tests**

```bash
cd server && python -m pytest tests/test_chat.py -v --tb=short 2>&1 | tail -10
```

Expected: all tests pass.

- [ ] **Step 3: Commit**

```bash
git add server/chat.py
git commit -m "fix: raise MAX_TOOL_ROUNDS from 5 to 8 for complex multi-tool questions"
```

---

### Task 9: CORS origins from environment variable

`main.py` hardcodes `["http://localhost:5173", "http://localhost:4173"]`. Add `CORS_ORIGINS` env var support so production deployments can configure allowed origins without code changes.

**Files:**
- Modify: `server/main.py`

- [ ] **Step 1: Update CORS middleware setup**

In `server/main.py`, replace:

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:4173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

with:

```python
_cors_env = os.getenv("CORS_ORIGINS", "http://localhost:5173,http://localhost:4173")
_cors_origins = [o.strip() for o in _cors_env.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

- [ ] **Step 2: Run health check to confirm server starts**

```bash
cd server && python -c "import main; print('CORS origins:', main._cors_origins)"
```

Expected: `CORS origins: ['http://localhost:5173', 'http://localhost:4173']`

- [ ] **Step 3: Commit**

```bash
git add server/main.py
git commit -m "feat: read CORS_ORIGINS from env var with localhost fallback"
```

---

### Task 10: Sanitize raw exception strings in API error responses

`main.py` currently does `detail=str(e)` in all except blocks, which leaks full Python exception messages (including stack details) to the frontend. Replace with a logging call and a user-friendly message. Keep `ValueError` messages (they're intentional user-facing errors like "Driver not found").

**Files:**
- Modify: `server/main.py`

- [ ] **Step 1: Add logger import and update exception handlers**

At the top of `server/main.py`, after the existing imports, add:

```python
import logging
logger = logging.getLogger(__name__)
```

Then replace each `except Exception as e: raise HTTPException(status_code=500, detail=str(e))` block. There are three:

**`/api/drivers` endpoint:**
```python
@app.get("/api/drivers")
async def drivers_endpoint():
    try:
        return get_drivers()
    except Exception as e:
        logger.exception("Error in GET /api/drivers")
        raise HTTPException(status_code=500, detail="Failed to fetch drivers.")
```

**`/api/driver/{name}/stats` endpoint** (keep ValueError for 404, sanitize the 500):
```python
@app.get("/api/driver/{name}/stats")
async def driver_stats_endpoint(name: str):
    try:
        stats = get_driver_stats(name)
        if stats is None:
            raise HTTPException(status_code=404, detail=f"Driver '{name}' not found")
        return stats
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.exception("Error in GET /api/driver/%s/stats", name)
        raise HTTPException(status_code=500, detail="Failed to fetch driver stats.")
```

**`/api/circuits` endpoint:**
```python
@app.get("/api/circuits")
async def circuits_endpoint():
    try:
        return get_circuits()
    except Exception as e:
        logger.exception("Error in GET /api/circuits")
        raise HTTPException(status_code=500, detail="Failed to fetch circuit schedule.")
```

**`/api/chat` endpoint:**
```python
@app.post("/api/chat")
async def chat_endpoint(request: ChatRequest):
    if not request.message.strip():
        raise HTTPException(status_code=400, detail="message cannot be empty")
    try:
        return answer_f1_payload(request.message, request.history)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Error in POST /api/chat")
        raise HTTPException(status_code=500, detail="Something went wrong processing your request.")
```

- [ ] **Step 2: Run all server tests**

```bash
cd server && python -m pytest tests/ -v --tb=short 2>&1 | tail -15
```

Expected: all tests pass.

- [ ] **Step 3: Commit**

```bash
git add server/main.py
git commit -m "fix: log exceptions server-side and return sanitized error messages to frontend"
```

---

### Task 11: Fix `get_intervals` to sample evenly across the race

`get_intervals` in `openf1.py` reverses-sorts all interval rows and takes only the first 25, discarding all early-race data. Fix: sort chronologically and sample evenly across the full race.

**Files:**
- Modify: `server/openf1.py`

- [ ] **Step 1: Locate and update `get_intervals`**

In `server/openf1.py`, find `get_intervals` (line ~101) and replace the rows processing:

```python
# OLD:
rows = sorted(rows, key=lambda row: row.get("date", ""), reverse=True)[:limit]

# NEW:
rows = sorted(rows, key=lambda row: row.get("date", ""))
if len(rows) > limit:
    step = max(1, len(rows) // limit)
    rows = rows[::step][:limit]
```

The full updated function:

```python
def get_intervals(round_number: int, driver_ref: str | None = None, limit: int = 25) -> dict:
    session = _resolve_openf1_session(round_number, "R")
    params = {"session_key": session["session_key"]}
    driver_number = None
    driver_name = None
    if driver_ref:
        driver_number = _driver_number_for_session(round_number, "R", driver_ref)
        matched = _resolve_driver(driver_ref)
        driver_name = matched["full_name"] if matched else driver_ref
        params["driver_number"] = driver_number

    rows = _openf1_get("intervals", **params)
    rows = sorted(rows, key=lambda row: row.get("date", ""))
    if len(rows) > limit:
        step = max(1, len(rows) // limit)
        rows = rows[::step][:limit]
    return {
        "event": session.get("session_name"),
        "country": session.get("country_name"),
        "circuit": session.get("circuit_short_name"),
        "session_key": session.get("session_key"),
        "driver_number": driver_number,
        "driver": driver_name,
        "intervals": [
            {
                "date": row.get("date"),
                "driver_number": row.get("driver_number"),
                "gap_to_leader": row.get("gap_to_leader"),
                "interval": row.get("interval"),
            }
            for row in rows
        ],
    }
```

- [ ] **Step 2: Run tests**

```bash
cd server && python -m pytest tests/ -v --tb=short 2>&1 | tail -10
```

Expected: all tests pass.

- [ ] **Step 3: Commit**

```bash
git add server/openf1.py
git commit -m "fix: get_intervals now samples evenly across the race instead of discarding early-race data"
```
