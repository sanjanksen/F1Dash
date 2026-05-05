# Sprint Session Support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every layer of the stack — data fetching, tool definitions, routing, and the model's system prompt — correctly handle sprint races (`S`), sprint qualifying/shootout (`SQ`), regular qualifying (`Q`), and regular races (`R`).

**Architecture:** Add `get_sprint_results`/`get_sprint_qualifying_results` as data primitives; add `session_type` parameter to the four composite functions (`get_driver_race_story`, `get_driver_weekend_overview`, `get_team_weekend_overview`, `get_race_report`) and to `analyze_qualifying_battle`; propagate these through tool definitions, `execute_tool`, `_build_analysis_plan`, `_suggested_tool_args`, and `SYSTEM_PROMPT`. The resolver already detects sprint session types correctly — only `_suggest_tool` needs a small fix.

**Tech Stack:** Python/FastAPI backend only (no frontend changes needed — widgets already render session-agnostic data).

---

## File Map

| File | Changes |
|---|---|
| `server/f1_data.py` | Add `get_sprint_results`, `get_sprint_qualifying_results`; add `session_type` param to `_get_comparable_qualifying_laps`, `analyze_qualifying_battle`, `get_driver_weekend_overview`, `get_driver_race_story`, `get_team_weekend_overview`, `get_race_report` |
| `server/tools.py` | Add `session_type` to composite tool schemas; add `get_sprint_results`/`get_sprint_qualifying_results` primitive schemas; update `execute_tool` dispatcher |
| `server/chat.py` | Add sprint bullet-points to `SYSTEM_PROMPT`; update `_build_analysis_plan` driver_comparison + race_pace_comparison branches; update `_suggested_tool_args` |
| `server/resolver.py` | Update `_suggest_tool` for sprint session types |
| `server/tests/test_tools.py` | Tests for sprint tool dispatch |
| `server/tests/test_chat.py` | Tests for sprint routing in `_build_analysis_plan` and `_suggested_tool_args` |

---

## Task 1: Sprint data-fetch primitives in f1_data.py

**Files:**
- Modify: `server/f1_data.py` (after `get_qualifying_results`, around line 596)
- Test: `server/tests/test_f1_data.py`

- [ ] **Step 1: Write failing tests**

Add to `server/tests/test_f1_data.py`:

```python
def test_get_sprint_results_returns_expected_shape(requests_mock):
    import f1_data
    payload = {
        "MRData": {
            "RaceTable": {
                "Races": [{
                    "raceName": "Chinese Grand Prix",
                    "Circuit": {"circuitName": "Shanghai International Circuit"},
                    "date": "2025-03-22",
                    "SprintResults": [{
                        "position": "1",
                        "Driver": {"givenName": "Oscar", "familyName": "Piastri", "code": "PIA"},
                        "Constructor": {"name": "McLaren"},
                        "points": "8",
                        "status": "Finished",
                    }],
                }]
            }
        }
    }
    requests_mock.get(
        f"https://api.jolpi.ca/ergast/f1/{f1_data.CURRENT_YEAR}/5/sprint.json",
        json=payload,
    )
    result = f1_data.get_sprint_results(5)
    assert result["session"] == "S"
    assert result["results"][0]["code"] == "PIA"
    assert result["results"][0]["position"] == 1
    assert result["results"][0]["points"] == 8.0


def test_get_sprint_results_empty_when_no_races(requests_mock):
    import f1_data
    payload = {"MRData": {"RaceTable": {"Races": []}}}
    requests_mock.get(
        f"https://api.jolpi.ca/ergast/f1/{f1_data.CURRENT_YEAR}/5/sprint.json",
        json=payload,
    )
    result = f1_data.get_sprint_results(5)
    assert result == {}


def test_get_sprint_qualifying_results_returns_expected_shape():
    import f1_data
    from unittest.mock import patch, MagicMock
    import pandas as pd

    mock_session = MagicMock()
    mock_session.event = {"EventName": "Chinese Grand Prix"}
    mock_session.date = pd.Timestamp("2025-03-22")

    mock_row = {
        "Position": 1,
        "FullName": "Oscar Piastri",
        "FirstName": "Oscar",
        "LastName": "Piastri",
        "Abbreviation": "PIA",
        "TeamName": "McLaren",
        "Q1": pd.Timedelta(seconds=93.5),
        "Q2": pd.Timedelta(seconds=92.8),
        "Q3": pd.Timedelta(seconds=92.1),
    }

    with patch("f1_data._load_session", return_value=mock_session), \
         patch("f1_data._session_results_rows", return_value=[mock_row]):
        result = f1_data.get_sprint_qualifying_results(5)

    assert result["session"] == "SQ"
    assert result["results"][0]["code"] == "PIA"
    assert result["results"][0]["position"] == 1
    assert result["results"][0]["sq1"] is not None
```

- [ ] **Step 2: Run tests to verify they fail**

```
cd server && python -m pytest tests/test_f1_data.py::test_get_sprint_results_returns_expected_shape tests/test_f1_data.py::test_get_sprint_results_empty_when_no_races tests/test_f1_data.py::test_get_sprint_qualifying_results_returns_expected_shape -v
```
Expected: FAIL with AttributeError or ImportError (functions don't exist yet).

- [ ] **Step 3: Implement the two functions**

Add both functions to `server/f1_data.py` immediately after `get_qualifying_results` (around line 596):

```python
def get_sprint_results(round_number: int) -> dict:
    """Return the full finishing order for a sprint race."""
    resp = requests.get(
        f"{JOLPICA_BASE}/{CURRENT_YEAR}/{round_number}/sprint.json?limit=30",
        timeout=15,
    )
    resp.raise_for_status()
    races = resp.json()["MRData"]["RaceTable"]["Races"]
    if not races:
        return {}
    race = races[0]
    return {
        "race_name": race["raceName"],
        "circuit": race["Circuit"]["circuitName"],
        "date": race.get("date", ""),
        "session": "S",
        "results": [
            {
                "position": int(r["position"]) if r["position"].isdigit() else None,
                "driver": f"{r['Driver']['givenName']} {r['Driver']['familyName']}",
                "code": r["Driver"].get("code", ""),
                "team": r["Constructor"]["name"],
                "points": float(r.get("points", 0)),
                "fastest_lap": r.get("FastestLap", {}).get("rank") == "1",
                "status": r.get("status", ""),
            }
            for r in race.get("SprintResults", [])
        ],
    }


def get_sprint_qualifying_results(round_number: int) -> dict:
    """Return sprint qualifying/shootout classification via FastF1."""
    try:
        session = _load_session(round_number, "SQ", laps=True, telemetry=False, weather=False, messages=False)
    except Exception as exc:
        raise ValueError(f"Sprint qualifying data unavailable for round {round_number}: {exc}") from exc
    rows = _session_results_rows(session)
    return {
        "race_name": session.event.get("EventName", f"Round {round_number}"),
        "date": str(session.date.date()) if session.date is not None else "",
        "session": "SQ",
        "results": [
            {
                "position": _normalize_position(row.get("Position")),
                "driver": row.get("FullName") or " ".join(
                    part for part in [row.get("FirstName"), row.get("LastName")] if part
                ).strip(),
                "code": row.get("Abbreviation", ""),
                "team": row.get("TeamName", ""),
                "sq1": _fmt_td(row.get("Q1")) if row.get("Q1") is not None else None,
                "sq2": _fmt_td(row.get("Q2")) if row.get("Q2") is not None else None,
                "sq3": _fmt_td(row.get("Q3")) if row.get("Q3") is not None else None,
            }
            for row in rows
        ],
    }
```

Also update the imports at the top of `f1_data.py` where `get_sprint_results` and `get_sprint_qualifying_results` are exported — they're auto-exported since there's no `__all__`. But update `tools.py` imports in Task 5.

- [ ] **Step 4: Run tests to verify they pass**

```
cd server && python -m pytest tests/test_f1_data.py::test_get_sprint_results_returns_expected_shape tests/test_f1_data.py::test_get_sprint_results_empty_when_no_races tests/test_f1_data.py::test_get_sprint_qualifying_results_returns_expected_shape -v
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add server/f1_data.py server/tests/test_f1_data.py
git commit -m "feat: add get_sprint_results and get_sprint_qualifying_results to f1_data"
```

---

## Task 2: Make `analyze_qualifying_battle` session-type aware

**Files:**
- Modify: `server/f1_data.py` — `_get_comparable_qualifying_laps` and `analyze_qualifying_battle`
- Test: `server/tests/test_f1_data.py`

The function `_get_comparable_qualifying_laps` hardcodes `'Q'`. Inside `analyze_qualifying_battle`, `get_telemetry_comparison` and `analyze_energy_management` also hardcode `'Q'`, and `sector["session"]` is hardcoded to `"Q"`.

- [ ] **Step 1: Write failing tests**

Add to `server/tests/test_f1_data.py`:

```python
def test_analyze_qualifying_battle_accepts_sq_session_type():
    import f1_data
    from unittest.mock import patch, MagicMock
    import pandas as pd

    mock_session = MagicMock()
    mock_session.event = {"EventName": "Chinese Grand Prix"}

    def make_lap(time_s, s1, s2, s3):
        lap = MagicMock()
        lap.__getitem__ = lambda self, key: {
            "LapTime": pd.Timedelta(seconds=time_s),
            "Sector1Time": pd.Timedelta(seconds=s1),
            "Sector2Time": pd.Timedelta(seconds=s2),
            "Sector3Time": pd.Timedelta(seconds=s3),
            "LapNumber": 3,
            "SpeedI1": 240.0,
            "SpeedI2": 230.0,
            "SpeedFL": 220.0,
            "SpeedST": 310.0,
        }.get(key, MagicMock())
        lap.get = lambda key, default=None: {
            "LapTime": pd.Timedelta(seconds=time_s),
            "Sector1Time": pd.Timedelta(seconds=s1),
            "Sector2Time": pd.Timedelta(seconds=s2),
            "Sector3Time": pd.Timedelta(seconds=s3),
            "LapNumber": 3,
            "SpeedI1": 240.0,
            "SpeedI2": 230.0,
            "SpeedFL": 220.0,
            "SpeedST": 310.0,
        }.get(key, default)
        return lap

    chosen_laps = {"NOR": make_lap(90.0, 29.0, 31.0, 30.0), "PIA": make_lap(90.3, 29.2, 31.1, 30.0)}

    with patch("f1_data._get_comparable_qualifying_laps", return_value=(mock_session, "SQ2", chosen_laps)), \
         patch("f1_data.get_telemetry_comparison", side_effect=Exception("no telemetry")), \
         patch("f1_data.analyze_energy_management", side_effect=Exception("no energy")), \
         patch("f1_data._resolve_driver", return_value={"team": "McLaren"}), \
         patch("f1_data.get_circuit_corners", side_effect=Exception("no corners")):
        result = f1_data.analyze_qualifying_battle(5, "NOR", "PIA", session_type="SQ")

    assert result["session"] == "SQ"
```

- [ ] **Step 2: Run tests to verify they fail**

```
cd server && python -m pytest tests/test_f1_data.py::test_analyze_qualifying_battle_accepts_sq_session_type -v
```
Expected: FAIL — `analyze_qualifying_battle` does not accept `session_type`.

- [ ] **Step 3: Implement the changes**

In `server/f1_data.py`, modify `_get_comparable_qualifying_laps`:

```python
def _get_comparable_qualifying_laps(round_number: int, driver_codes: list[str], session_type: str = "Q"):
    session = _load_session(round_number, session_type, laps=True, telemetry=False, weather=False, messages=True)
    try:
        split = session.laps.split_qualifying_sessions()
        segments = [("Q3", split[2]), ("Q2", split[1]), ("Q1", split[0])]
    except Exception:
        # SQ/SS sessions may not support split_qualifying_sessions; use all laps
        all_laps = session.laps
        chosen = {}
        for code in driver_codes:
            laps = _pick_driver(all_laps, code.upper())
            if laps.empty:
                raise ValueError(f"No laps for {code} in {session_type} session.")
            fastest = _pick_fastest_lap(laps)
            if pd.isna(fastest.get("LapTime")):
                raise ValueError(f"No valid timed lap for {code} in {session_type} session.")
            chosen[code.upper()] = fastest
        return session, session_type, chosen

    def _fastest_valid_lap(segment_laps, code: str):
        driver_laps = _pick_driver(segment_laps, code.upper())
        if driver_laps.empty:
            return None
        fastest = _pick_fastest_lap(driver_laps)
        if pd.isna(fastest.get('LapTime')):
            return None
        return fastest

    for segment_name, segment_laps in segments:
        if segment_laps is None:
            continue
        chosen = {}
        valid = True
        for code in driver_codes:
            lap = _fastest_valid_lap(segment_laps, code)
            if lap is None:
                valid = False
                break
            chosen[code.upper()] = lap
        if valid:
            return session, segment_name, chosen

    raise ValueError("No comparable qualifying segment found for both drivers.")
```

Then modify `analyze_qualifying_battle` — add `session_type: str = "Q"` parameter and fix the three hardcoded `'Q'` references:

```python
def analyze_qualifying_battle(round_number: int, driver_a: str, driver_b: str, session_type: str = "Q") -> dict:
    """
    Backend-derived causal summary for a qualifying battle.
    Explains where the time was gained and the most likely mechanism.
    """
    session, compared_segment, chosen_laps = _get_comparable_qualifying_laps(round_number, [driver_a, driver_b], session_type)
    lap_a = chosen_laps[driver_a.upper()]
    lap_b = chosen_laps[driver_b.upper()]
    # ... (all existing lap processing code unchanged) ...
    sector = {
        "event": session.event['EventName'],
        "session": session_type.upper(),   # was hardcoded "Q"
        "compared_segment": compared_segment,
        # ... rest unchanged ...
    }
    # ... existing code ...
    try:
        telemetry = get_telemetry_comparison(
            round_number,
            session_type,          # was hardcoded 'Q'
            driver_a,
            driver_b,
            lap_number_a=sector["lap_number_a"],
            lap_number_b=sector["lap_number_b"],
        )
    # ... existing except ...
    try:
        energy = analyze_energy_management(
            round_number,
            session_type,          # was hardcoded 'Q'
            driver_a,
            driver_b,
            lap_number_a=sector["lap_number_a"],
            lap_number_b=sector["lap_number_b"],
        )
    # ... rest of function unchanged ...
```

The actual edit is three targeted replacements:
1. Function signature line
2. `_get_comparable_qualifying_laps` call to pass `session_type`
3. `sector["session"] = "Q"` → `session_type.upper()`
4. Two `'Q'` strings in `get_telemetry_comparison` and `analyze_energy_management` calls

- [ ] **Step 4: Run tests to verify they pass**

```
cd server && python -m pytest tests/test_f1_data.py::test_analyze_qualifying_battle_accepts_sq_session_type -v
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add server/f1_data.py server/tests/test_f1_data.py
git commit -m "feat: add session_type param to _get_comparable_qualifying_laps and analyze_qualifying_battle"
```

---

## Task 3: Make `get_driver_weekend_overview` and `get_driver_race_story` sprint-aware

**Files:**
- Modify: `server/f1_data.py` — `get_driver_weekend_overview` and `get_driver_race_story`
- Test: `server/tests/test_f1_data.py`

`get_driver_weekend_overview` has many hardcoded session types internally. The approach: compute `race_session` and `quali_session` variables at the top, use them everywhere inside.

- [ ] **Step 1: Write failing tests**

Add to `server/tests/test_f1_data.py`:

```python
def test_get_driver_weekend_overview_uses_sprint_data_when_session_type_s():
    import f1_data
    from unittest.mock import patch

    sprint_results = {
        "race_name": "Chinese Grand Prix",
        "session": "S",
        "results": [{"position": 3, "driver": "Lando Norris", "code": "NOR",
                     "team": "McLaren", "points": 6.0, "status": "Finished", "fastest_lap": False}],
    }
    sq_results = {
        "race_name": "Chinese Grand Prix",
        "session": "SQ",
        "results": [{"position": 2, "driver": "Lando Norris", "code": "NOR",
                     "team": "McLaren", "sq1": "1:32.1", "sq2": "1:31.8", "sq3": "1:31.5"}],
    }
    mock_driver = {"full_name": "Lando Norris", "code": "NOR", "driver_id": "norris", "team": "McLaren"}

    with patch("f1_data._resolve_driver", return_value=mock_driver), \
         patch("f1_data.get_sprint_results", return_value=sprint_results), \
         patch("f1_data.get_sprint_qualifying_results", return_value=sq_results), \
         patch("f1_data.get_driver_strategy", side_effect=Exception("no data")), \
         patch("f1_data.get_safety_car_periods", side_effect=Exception("no data")), \
         patch("f1_data.get_session_results", side_effect=Exception("no data")), \
         patch("f1_data.analyze_energy_management", side_effect=Exception("no data")), \
         patch("f1_data.get_drivers", return_value=[mock_driver]):
        result = f1_data.get_driver_weekend_overview(5, "norris", session_type="S")

    assert result["race"]["finish_position"] == 3
    assert result["qualifying"]["position"] == 2


def test_get_driver_race_story_passes_session_type_to_overview():
    import f1_data
    from unittest.mock import patch, MagicMock

    mock_overview = {
        "driver": "Lando Norris", "code": "NOR", "team": "McLaren",
        "event": "Chinese Grand Prix", "round": 5,
        "qualifying": {"position": 2}, "race": {"finish_position": 3, "points": 6.0, "status": "Finished", "fastest_lap": False},
        "pit_stops": [], "strategy": None, "safety_car_impact": None, "teammate": {},
        "nearby_rivals": [], "openf1": {}, "energy_management": None,
    }

    with patch("f1_data.get_driver_weekend_overview", return_value=mock_overview) as mock_overview_fn, \
         patch("f1_data.get_session_results", side_effect=Exception("no data")), \
         patch("f1_data.get_race_control_messages", side_effect=Exception("no data")), \
         patch("f1_data.get_driver_strategy", side_effect=Exception("no data")), \
         patch("f1_data.get_safety_car_periods", side_effect=Exception("no data")):
        f1_data.get_driver_race_story(5, "norris", session_type="S")

    mock_overview_fn.assert_called_once_with(5, "norris", session_type="S")
```

- [ ] **Step 2: Run tests to verify they fail**

```
cd server && python -m pytest tests/test_f1_data.py::test_get_driver_weekend_overview_uses_sprint_data_when_session_type_s tests/test_f1_data.py::test_get_driver_race_story_passes_session_type_to_overview -v
```
Expected: FAIL — functions don't accept `session_type`.

- [ ] **Step 3: Implement `get_driver_weekend_overview` changes**

Change the signature and add session routing at the top of `get_driver_weekend_overview`:

```python
def get_driver_weekend_overview(round_number: int, driver_name: str, session_type: str = "R") -> dict:
    """
    High-level weekend overview for a driver: quali, finish, teammate, strategy,
    nearby rivals, and SC/VSC impact when available.
    """
    session_type = session_type.upper().strip()
    is_sprint = session_type == "S"
    race_session = "S" if is_sprint else "R"
    quali_session = "SQ" if is_sprint else "Q"

    matched = _resolve_driver(driver_name)
    if matched is None:
        raise ValueError(f"Driver not found: {driver_name!r}. Try surname or 3-letter code.")

    code = matched["code"] or matched["driver_id"].upper()

    if is_sprint:
        qualifying = get_sprint_qualifying_results(round_number)
        race = get_sprint_results(round_number)
    else:
        qualifying = get_qualifying_results(round_number)
        race = get_race_results(round_number)
```

Then replace every hardcoded `'R'` and `'Q'` inside the function body with `race_session` / `quali_session`:

- `get_driver_strategy(round_number, 'R', code)` → `get_driver_strategy(round_number, race_session, code)`
- `get_safety_car_periods(round_number, 'R')` → `get_safety_car_periods(round_number, race_session)`
- `get_session_results(round_number, 'R')` (both occurrences) → `get_session_results(round_number, race_session)`
- `preferred_session = 'Q' if driver_quali else 'R'` → `preferred_session = quali_session if driver_quali else race_session`
- `get_team_radio(round_number, 'Q', code, limit=6)` → `get_team_radio(round_number, quali_session, code, limit=6)`
- `get_live_position_timeline(round_number, 'R', code, limit=30)` → `get_live_position_timeline(round_number, race_session, code, limit=30)`
- `get_team_radio(round_number, 'R', code, limit=8)` → `get_team_radio(round_number, race_session, code, limit=8)`

Also update the qualifying data lookup. For sprint, driver_quali uses `sq1`/`sq2`/`sq3` fields. Normalize the return to use those keys when is_sprint. Change the `"qualifying"` block in the return dict from:

```python
"qualifying": {
    "position": driver_quali.get("position") if driver_quali else None,
    "q1": driver_quali.get("q1") if driver_quali else None,
    "q2": driver_quali.get("q2") if driver_quali else None,
    "q3": driver_quali.get("q3") if driver_quali else None,
},
```

to:

```python
"qualifying": {
    "position": driver_quali.get("position") if driver_quali else None,
    "q1": driver_quali.get("sq1" if is_sprint else "q1") if driver_quali else None,
    "q2": driver_quali.get("sq2" if is_sprint else "q2") if driver_quali else None,
    "q3": driver_quali.get("sq3" if is_sprint else "q3") if driver_quali else None,
},
```

This preserves the `q1/q2/q3` keys in the output so `get_driver_race_story` and callers don't break — the values just come from `sq1/sq2/sq3` fields when is_sprint.

Also update the `"event"` field in the return to fall back gracefully for sprint:
```python
"event": race.get("race_name") or qualifying.get("race_name"),
```
This already works for sprint since `get_sprint_results` and `get_sprint_qualifying_results` both return `race_name`.

- [ ] **Step 4: Implement `get_driver_race_story` changes**

Change the signature and fix internal hardcoded session types:

```python
def get_driver_race_story(round_number: int, driver_name: str, session_type: str = "R") -> dict:
    """
    Narrative-ready race overview for one driver with key race events and contextual comparisons.
    """
    session_type = session_type.upper().strip()
    race_session = "S" if session_type == "S" else "R"

    overview = get_driver_weekend_overview(round_number, driver_name, session_type=session_type)
    code = overview["code"]

    race_control = None
    try:
        session_results = get_session_results(round_number, race_session)
        driver_meta = next((r for r in session_results.get("results", []) if r.get("abbreviation", "").upper() == code.upper()), None)
        driver_number = driver_meta.get("driver_number") if driver_meta else None
        category = driver_number if driver_number else code.upper()
        race_control = get_race_control_messages(round_number, race_session, category=category, limit=20)
    except Exception:
        race_control = None
```

Then fix the two hardcoded 'R' in the lower body:
- `get_driver_strategy(round_number, 'R')` → `get_driver_strategy(round_number, race_session)`
- `get_safety_car_periods(round_number, 'R')` → `get_safety_car_periods(round_number, race_session)`

Also update the story_point text that says "qualifying":
```python
    if quali.get("position") is not None and race.get("finish_position") is not None:
        delta = quali["position"] - race["finish_position"]
        session_label = "sprint qualifying" if session_type == "S" else "qualifying"
        if delta > 0:
            summary_points.append(f"Gained {delta} place(s) from {session_label} to the finish.")
        elif delta < 0:
            summary_points.append(f"Lost {abs(delta)} place(s) from {session_label} to the finish.")
        else:
            summary_points.append("Finished where they broadly started.")
```

- [ ] **Step 5: Run tests to verify they pass**

```
cd server && python -m pytest tests/test_f1_data.py::test_get_driver_weekend_overview_uses_sprint_data_when_session_type_s tests/test_f1_data.py::test_get_driver_race_story_passes_session_type_to_overview -v
```
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add server/f1_data.py server/tests/test_f1_data.py
git commit -m "feat: add session_type param to get_driver_weekend_overview and get_driver_race_story"
```

---

## Task 4: Make `get_team_weekend_overview` and `get_race_report` sprint-aware

**Files:**
- Modify: `server/f1_data.py`
- Test: `server/tests/test_f1_data.py`

- [ ] **Step 1: Write failing tests**

Add to `server/tests/test_f1_data.py`:

```python
def test_get_team_weekend_overview_uses_sprint_data_when_session_type_s():
    import f1_data
    from unittest.mock import patch

    sprint_results = {
        "race_name": "Chinese Grand Prix",
        "session": "S",
        "results": [
            {"position": 1, "driver": "Lando Norris", "code": "NOR", "team": "McLaren", "points": 8.0, "status": "Finished", "fastest_lap": False},
            {"position": 3, "driver": "Oscar Piastri", "code": "PIA", "team": "McLaren", "points": 6.0, "status": "Finished", "fastest_lap": False},
        ],
    }
    sq_results = {
        "race_name": "Chinese Grand Prix",
        "session": "SQ",
        "results": [
            {"position": 1, "driver": "Lando Norris", "code": "NOR", "team": "McLaren"},
            {"position": 2, "driver": "Oscar Piastri", "code": "PIA", "team": "McLaren"},
        ],
    }
    drivers = [
        {"full_name": "Lando Norris", "code": "NOR", "team": "McLaren", "driver_id": "norris"},
        {"full_name": "Oscar Piastri", "code": "PIA", "team": "McLaren", "driver_id": "piastri"},
    ]

    with patch("f1_data._resolve_team", return_value="McLaren"), \
         patch("f1_data.get_drivers", return_value=drivers), \
         patch("f1_data.get_sprint_results", return_value=sprint_results), \
         patch("f1_data.get_sprint_qualifying_results", return_value=sq_results), \
         patch("f1_data.get_driver_strategy", side_effect=Exception("no data")):
        result = f1_data.get_team_weekend_overview(5, "McLaren", session_type="S")

    assert result["team"] == "McLaren"
    assert any(d["code"] == "NOR" and d["finish_position"] == 1 for d in result["drivers"])


def test_get_race_report_uses_sprint_data_when_session_type_s():
    import f1_data
    from unittest.mock import patch

    sprint_results = {
        "race_name": "Chinese Grand Prix",
        "session": "S",
        "results": [
            {"position": 1, "driver": "Oscar Piastri", "code": "PIA", "team": "McLaren", "points": 8.0, "status": "Finished", "fastest_lap": True},
            {"position": 2, "driver": "Lando Norris", "code": "NOR", "team": "McLaren", "points": 7.0, "status": "Finished", "fastest_lap": False},
        ],
    }
    sq_results = {"race_name": "Chinese Grand Prix", "session": "SQ", "results": [
        {"position": 1, "driver": "Oscar Piastri", "code": "PIA", "team": "McLaren"},
        {"position": 2, "driver": "Lando Norris", "code": "NOR", "team": "McLaren"},
    ]}

    with patch("f1_data.get_sprint_results", return_value=sprint_results), \
         patch("f1_data.get_sprint_qualifying_results", return_value=sq_results), \
         patch("f1_data.get_safety_car_periods", side_effect=Exception("no data")), \
         patch("f1_data.get_driver_strategy", side_effect=Exception("no data")):
        result = f1_data.get_race_report(5, session_type="S")

    assert result["session"] == "S"
    assert result["podium"][0]["driver"] == "Oscar Piastri"
```

- [ ] **Step 2: Run tests to verify they fail**

```
cd server && python -m pytest tests/test_f1_data.py::test_get_team_weekend_overview_uses_sprint_data_when_session_type_s tests/test_f1_data.py::test_get_race_report_uses_sprint_data_when_session_type_s -v
```
Expected: FAIL.

- [ ] **Step 3: Implement `get_team_weekend_overview` changes**

Add `session_type: str = "R"` parameter. Add routing block at the top:

```python
def get_team_weekend_overview(round_number: int, team_name: str, session_type: str = "R") -> dict:
    """
    High-level weekend overview for a team across both drivers.
    """
    session_type = session_type.upper().strip()
    is_sprint = session_type == "S"
    race_session = "S" if is_sprint else "R"

    resolved_team = _resolve_team(team_name)
    if resolved_team is None:
        raise ValueError(f"Team not found: {team_name!r}. Try the current constructor name.")

    team_drivers = [d for d in get_drivers() if d.get("team") == resolved_team]
    if not team_drivers:
        raise ValueError(f"No current-season drivers found for team {resolved_team!r}.")

    if is_sprint:
        qualifying = get_sprint_qualifying_results(round_number)
        race = get_sprint_results(round_number)
    else:
        qualifying = get_qualifying_results(round_number)
        race = get_race_results(round_number)
```

Then replace `get_driver_strategy(round_number, 'R', code)` → `get_driver_strategy(round_number, race_session, code)`.

- [ ] **Step 4: Implement `get_race_report` changes**

Add `session_type: str = "R"` parameter. Add routing block at the top:

```python
def get_race_report(round_number: int, session_type: str = "R") -> dict:
    """
    Whole-race recap independent of driver/team.
    """
    session_type = session_type.upper().strip()
    is_sprint = session_type == "S"
    race_session = session_type

    if is_sprint:
        qualifying = get_sprint_qualifying_results(round_number)
        race = get_sprint_results(round_number)
    else:
        qualifying = get_qualifying_results(round_number)
        race = get_race_results(round_number)
```

Then replace:
- `get_safety_car_periods(round_number, 'R')` → `get_safety_car_periods(round_number, race_session)`
- `get_driver_strategy(round_number, 'R')` → only call when `not is_sprint` (sprints have no pit stops, strategy will error)

Add `"session": session_type` to the return dict (so callers know what session the report covers):

```python
    return {
        "session": session_type,
        "race_name": race.get("race_name") or qualifying.get("race_name"),
        "podium": podium,
        # ... rest unchanged ...
    }
```

Also need to extract `podium` and `dnfs` into local variables inside the function for the test assertions — check the current return structure and make sure `podium` is a named key. Looking at the existing code, the return dict has `"summary_points"`, `"podium"` etc. — confirm those keys exist and add `"session"`.

- [ ] **Step 5: Run tests to verify they pass**

```
cd server && python -m pytest tests/test_f1_data.py::test_get_team_weekend_overview_uses_sprint_data_when_session_type_s tests/test_f1_data.py::test_get_race_report_uses_sprint_data_when_session_type_s -v
```
Expected: PASS.

- [ ] **Step 6: Run full test suite to catch regressions**

```
cd server && python -m pytest tests/ -v
```
Expected: all passing.

- [ ] **Step 7: Commit**

```bash
git add server/f1_data.py server/tests/test_f1_data.py
git commit -m "feat: add session_type param to get_team_weekend_overview and get_race_report"
```

---

## Task 5: Update `tools.py` — schemas, imports, and `execute_tool`

**Files:**
- Modify: `server/tools.py`
- Test: `server/tests/test_tools.py`

- [ ] **Step 1: Write failing tests**

Add to `server/tests/test_tools.py`:

```python
def test_execute_tool_get_sprint_results():
    mock = {"session": "S", "race_name": "Chinese Grand Prix", "results": []}
    with patch('tools.get_sprint_results', return_value=mock):
        result = tools.execute_tool("get_sprint_results", {"round_number": 5})
    assert result["session"] == "S"


def test_execute_tool_get_sprint_qualifying_results():
    mock = {"session": "SQ", "race_name": "Chinese Grand Prix", "results": []}
    with patch('tools.get_sprint_qualifying_results', return_value=mock):
        result = tools.execute_tool("get_sprint_qualifying_results", {"round_number": 5})
    assert result["session"] == "SQ"


def test_execute_tool_get_driver_race_story_passes_session_type():
    mock = {"driver": "Lando Norris", "story_points": []}
    with patch('tools.get_driver_race_story', return_value=mock) as mock_fn:
        tools.execute_tool("get_driver_race_story", {"round_number": 5, "driver_name": "norris", "session_type": "S"})
    mock_fn.assert_called_once_with(5, "norris", session_type="S")


def test_execute_tool_get_driver_race_story_defaults_to_r():
    mock = {"driver": "Lando Norris", "story_points": []}
    with patch('tools.get_driver_race_story', return_value=mock) as mock_fn:
        tools.execute_tool("get_driver_race_story", {"round_number": 5, "driver_name": "norris"})
    mock_fn.assert_called_once_with(5, "norris", session_type="R")


def test_execute_tool_analyze_qualifying_battle_passes_session_type():
    mock = {"session": "SQ", "driver_a": "NOR", "driver_b": "PIA"}
    with patch('tools.analyze_qualifying_battle', return_value=mock) as mock_fn:
        tools.execute_tool("analyze_qualifying_battle", {"round_number": 5, "driver_a": "NOR", "driver_b": "PIA", "session_type": "SQ"})
    mock_fn.assert_called_once_with(5, "NOR", "PIA", session_type="SQ")
```

- [ ] **Step 2: Run tests to verify they fail**

```
cd server && python -m pytest tests/test_tools.py::test_execute_tool_get_sprint_results tests/test_tools.py::test_execute_tool_get_sprint_qualifying_results tests/test_tools.py::test_execute_tool_get_driver_race_story_passes_session_type tests/test_tools.py::test_execute_tool_get_driver_race_story_defaults_to_r tests/test_tools.py::test_execute_tool_analyze_qualifying_battle_passes_session_type -v
```
Expected: FAIL.

- [ ] **Step 3: Update imports in `tools.py`**

Add `get_sprint_results` and `get_sprint_qualifying_results` to the import from `f1_data`:

```python
from f1_data import (
    analyze_cornering_loads,
    # ... existing imports ...
    get_sprint_results,
    get_sprint_qualifying_results,
    # ... rest of existing imports ...
)
```

- [ ] **Step 4: Add `session_type` param to composite tool schemas**

In `COMPOSITE_TOOL_DEFINITIONS`, update each of the four composite tool defs to accept an optional `session_type`. For example, `get_driver_race_story`:

```python
_tool(
    "get_driver_race_story",
    "COMPOSITE RECAP TOOL. Narrative-ready race or sprint story for one driver in one round. "
    "Use this first for broad prompts like 'how did Russell's race go?' or 'how did Norris do in the sprint?'. "
    "Pass session_type='S' for a sprint race story, session_type='R' (default) for the main race.",
    {
        "round_number": {"type": "integer", "description": "The 2026 season round number."},
        "driver_name": {"type": "string", "description": "Driver full name, surname, or 3-letter code."},
        "session_type": {"type": "string", "description": "R (default, main race) or S (sprint race)."},
    },
    ["round_number", "driver_name"],
),
```

Apply the same pattern to `get_driver_weekend_overview`, `get_team_weekend_overview`, and `get_race_report`:
- `get_driver_weekend_overview`: `"session_type: R (default) or S (sprint)."`
- `get_team_weekend_overview`: `"session_type: R (default) or S (sprint)."`
- `get_race_report`: `"session_type: R (default) or S (sprint race recap)."`

Add `session_type` to `analyze_qualifying_battle` schema:

```python
_tool(
    "analyze_qualifying_battle",
    "... existing description ... Pass session_type='SQ' for sprint qualifying.",
    {
        "round_number": {"type": "integer", "description": "The 2026 season round number."},
        "driver_a": {"type": "string", "description": "First driver's 3-letter code."},
        "driver_b": {"type": "string", "description": "Second driver's 3-letter code."},
        "session_type": {"type": "string", "description": "Q (default, regular qualifying) or SQ (sprint qualifying/shootout)."},
    },
    ["round_number", "driver_a", "driver_b"],
),
```

- [ ] **Step 5: Add two new primitive tool schemas**

Add to `PRIMITIVE_TOOL_DEFINITIONS`:

```python
_tool(
    "get_sprint_results",
    "PRIMITIVE TOOL. Raw sprint race finishing order for one round. Use for sprint race results lookup.",
    {
        "round_number": {"type": "integer", "description": "The 2026 season round number."},
    },
    ["round_number"],
),
_tool(
    "get_sprint_qualifying_results",
    "PRIMITIVE TOOL. Sprint qualifying/shootout classification for one round (SQ1/SQ2/SQ3 segment times).",
    {
        "round_number": {"type": "integer", "description": "The 2026 season round number."},
    },
    ["round_number"],
),
```

- [ ] **Step 6: Update `execute_tool` dispatcher**

Add cases for the two new primitives and update the four composite tool dispatches and `analyze_qualifying_battle`:

```python
    if name == "get_sprint_results":
        return get_sprint_results(args["round_number"])
    if name == "get_sprint_qualifying_results":
        return get_sprint_qualifying_results(args["round_number"])
    if name == "get_driver_weekend_overview":
        return get_driver_weekend_overview(args["round_number"], args["driver_name"], session_type=args.get("session_type", "R"))
    if name == "get_driver_race_story":
        return get_driver_race_story(args["round_number"], args["driver_name"], session_type=args.get("session_type", "R"))
    if name == "get_team_weekend_overview":
        return get_team_weekend_overview(args["round_number"], args["team_name"], session_type=args.get("session_type", "R"))
    if name == "get_race_report":
        return get_race_report(args["round_number"], session_type=args.get("session_type", "R"))
    if name == "analyze_qualifying_battle":
        return analyze_qualifying_battle(args["round_number"], args["driver_a"], args["driver_b"], session_type=args.get("session_type", "Q"))
```

- [ ] **Step 7: Run tests to verify they pass**

```
cd server && python -m pytest tests/test_tools.py -v
```
Expected: all passing.

- [ ] **Step 8: Commit**

```bash
git add server/tools.py server/tests/test_tools.py
git commit -m "feat: add sprint tool schemas and update execute_tool for session_type pass-through"
```

---

## Task 6: Update `chat.py` — system prompt, `_build_analysis_plan`, `_suggested_tool_args`

**Files:**
- Modify: `server/chat.py`
- Test: `server/tests/test_chat.py`

- [ ] **Step 1: Write failing tests**

Add to `server/tests/test_chat.py`:

```python
def test_build_analysis_plan_sprint_qualifying_uses_sq_session():
    import chat

    resolved = {
        "analysis_mode": "driver_comparison",
        "analysis_focus": "qualifying",
        "round_number": 5,
        "entity_names": ["Lando Norris", "Oscar Piastri"],
        "entity_codes": ["NOR", "PIA"],
        "session_type": "SQ",
    }

    plan = chat._build_analysis_plan("Why was Norris faster than Piastri in sprint qualifying?", resolved)

    assert plan is not None
    tool_names = [t[0] for t in plan["tool_calls"]]
    assert "analyze_qualifying_battle" in tool_names
    sq_battle = next(t for t in plan["tool_calls"] if t[0] == "analyze_qualifying_battle")
    assert sq_battle[1]["session_type"] == "SQ"


def test_build_analysis_plan_sprint_race_uses_s_session_for_story():
    import chat

    resolved = {
        "analysis_mode": "driver_comparison",
        "analysis_focus": "race",
        "round_number": 5,
        "entity_names": ["Lando Norris", "Oscar Piastri"],
        "entity_codes": ["NOR", "PIA"],
        "session_type": "S",
    }

    plan = chat._build_analysis_plan("Compare Norris and Piastri in the sprint", resolved)

    assert plan is not None
    story_calls = [t for t in plan["tool_calls"] if t[0] == "get_driver_race_story"]
    assert all(t[1].get("session_type") == "S" for t in story_calls)


def test_suggested_tool_args_sprint_race_story():
    import chat

    resolved = {
        "suggested_tool": "get_driver_race_story",
        "round_number": 5,
        "entity_name": "Lando Norris",
        "session_type": "S",
    }

    args = chat._suggested_tool_args(resolved)

    assert args is not None
    assert args["session_type"] == "S"


def test_suggested_tool_args_sprint_qualifying():
    import chat

    resolved = {
        "suggested_tool": "get_sprint_qualifying_results",
        "round_number": 5,
        "session_type": "SQ",
    }

    args = chat._suggested_tool_args(resolved)

    assert args is not None
    assert args["round_number"] == 5
```

- [ ] **Step 2: Run tests to verify they fail**

```
cd server && python -m pytest tests/test_chat.py::test_build_analysis_plan_sprint_qualifying_uses_sq_session tests/test_chat.py::test_build_analysis_plan_sprint_race_uses_s_session_for_story tests/test_chat.py::test_suggested_tool_args_sprint_race_story tests/test_chat.py::test_suggested_tool_args_sprint_qualifying -v
```
Expected: FAIL.

- [ ] **Step 3: Add sprint guidance to `SYSTEM_PROMPT`**

In `chat.py`, find `SYSTEM_PROMPT` and add the following bullet-points after the qualifying guidance line (after the `"- For qualifying storylines..."` line):

```python
- For sprint race questions ('how did X do in the sprint?', 'recap the sprint race'): use get_driver_race_story or get_race_report with session_type='S'. Do NOT call these with the default session_type for sprint questions.
- For sprint qualifying/shootout questions ('who was fastest in sprint qualifying?', 'sprint shootout recap'): use get_sprint_qualifying_results for raw classification, or get_session_results with session_type='SQ'. For causal 'why was X faster than Y in sprint qualifying?' questions, use analyze_qualifying_battle with session_type='SQ'.
- For a driver's sprint weekend story: use get_driver_race_story with session_type='S'
- For a team's sprint result: use get_team_weekend_overview with session_type='S'
- Sprint weekends contain: FP1 (practice), Sprint Qualifying/Shootout (SQ), Sprint Race (S), Qualifying (Q), Race (R). Sprint and sprint qualifying are separate sessions from the main qualifying and race.
- Sprint races are ~17-24 laps with no mandatory pit stops. Tyre degradation and strategy reasoning is less relevant for sprint; focus on pace, position battles, and safety car impact.
```

- [ ] **Step 4: Update `_build_analysis_plan` — qualifying branch for SQ**

In the `driver_comparison` mode, `focus == "qualifying"` branch, change the hardcoded `"Q"` session types:

```python
    if focus == "qualifying":
        quali_session = resolved.get("session_type") or "Q"
        plan["tool_calls"] = [
            ("get_sprint_qualifying_results" if quali_session == "SQ" else "get_qualifying_results", {"round_number": round_number}),
            ("analyze_qualifying_battle", {
                "round_number": round_number,
                "driver_a": codes[0],
                "driver_b": codes[1],
                "session_type": quali_session,
            }),
            ("compare_corner_profiles", {
                "round_number": round_number,
                "session_type": quali_session,
                "driver_a": codes[0],
                "driver_b": codes[1],
            }),
            ("analyze_cornering_loads", {
                "round_number": round_number,
                "session_type": quali_session,
                "driver_a": codes[0],
                "driver_b": codes[1],
            }),
            ("get_team_radio", {
                "round_number": round_number,
                "session_type": quali_session,
                "driver_ref": codes[0],
                "limit": 6,
            }),
            ("get_team_radio", {
                "round_number": round_number,
                "session_type": quali_session,
                "driver_ref": codes[1],
                "limit": 6,
            }),
        ]
        return plan
```

- [ ] **Step 5: Update `_build_analysis_plan` — race branch for sprint**

In the `driver_comparison` mode, `focus in ("race", "session")` branch:

```python
    if focus in ("race", "session"):
        race_session = resolved.get("session_type") or "R"
        plan["tool_calls"] = [
            ("get_driver_race_story", {"round_number": round_number, "driver_name": names[0], "session_type": race_session}),
            ("get_driver_race_story", {"round_number": round_number, "driver_name": names[1], "session_type": race_session}),
            ("analyze_race_pace_battle", {
                "round_number": round_number,
                "driver_a": codes[0],
                "driver_b": codes[1],
                "session_type": race_session,
            }),
            ("get_safety_car_periods", {
                "round_number": round_number,
                "session_type": race_session,
            }),
        ]
        return plan
```

- [ ] **Step 6: Update `_suggested_tool_args` for sprint**

In `_suggested_tool_args`, update the `get_driver_race_story` / `get_driver_weekend_overview` cases to pass through `session_type`:

```python
    if tool in ("get_driver_race_story", "get_driver_weekend_overview"):
        if not resolved.get("entity_name"):
            return None
        return {
            "round_number": round_number,
            "driver_name": resolved["entity_name"],
            "session_type": resolved.get("session_type") or "R",
        }

    if tool == "get_team_weekend_overview":
        if not resolved.get("entity_name"):
            return None
        return {
            "round_number": round_number,
            "team_name": resolved["entity_name"],
            "session_type": resolved.get("session_type") or "R",
        }

    if tool == "get_race_report":
        return {
            "round_number": round_number,
            "session_type": resolved.get("session_type") or "R",
        }

    if tool == "get_sprint_qualifying_results":
        return {"round_number": round_number}
```

- [ ] **Step 7: Run tests to verify they pass**

```
cd server && python -m pytest tests/test_chat.py::test_build_analysis_plan_sprint_qualifying_uses_sq_session tests/test_chat.py::test_build_analysis_plan_sprint_race_uses_s_session_for_story tests/test_chat.py::test_suggested_tool_args_sprint_race_story tests/test_chat.py::test_suggested_tool_args_sprint_qualifying -v
```
Expected: PASS.

- [ ] **Step 8: Run full test suite**

```
cd server && python -m pytest tests/ -v
```
Expected: all passing.

- [ ] **Step 9: Commit**

```bash
git add server/chat.py server/tests/test_chat.py
git commit -m "feat: add sprint guidance to SYSTEM_PROMPT and sprint routing to _build_analysis_plan and _suggested_tool_args"
```

---

## Task 7: Update `resolver.py` — `_suggest_tool` for sprint sessions

**Files:**
- Modify: `server/resolver.py`
- Test: `server/tests/test_resolver.py`

`_suggest_tool` currently maps sprint session types to the same tools as regular race sessions. For `session_type == "SQ"`, it falls through to `entity_type == "driver"` and returns `get_driver_weekend_overview` — which is now sprint-capable, so that's acceptable. But for `session_type == "S"`, we should suggest `get_driver_race_story` (not `get_driver_weekend_overview`), and for broad sprint qualifying questions we should suggest `get_sprint_qualifying_results`.

- [ ] **Step 1: Write failing tests**

Add to `server/tests/test_resolver.py` (or create new file if it doesn't exist with the right imports):

```python
def test_suggest_tool_sprint_race_driver_entity():
    from resolver import _suggest_tool
    result = _suggest_tool("driver", "overview", "S")
    assert result == "get_driver_race_story"


def test_suggest_tool_sprint_qualifying_standalone():
    from resolver import _suggest_tool
    result = _suggest_tool(None, "qualifying", "SQ")
    assert result == "get_sprint_qualifying_results"


def test_suggest_tool_sprint_race_no_entity():
    from resolver import _suggest_tool
    result = _suggest_tool(None, "race_report", "S")
    assert result == "get_race_report"
```

- [ ] **Step 2: Run tests to verify they fail**

```
cd server && python -m pytest tests/test_resolver.py::test_suggest_tool_sprint_race_driver_entity tests/test_resolver.py::test_suggest_tool_sprint_qualifying_standalone tests/test_resolver.py::test_suggest_tool_sprint_race_no_entity -v
```
Expected: FAIL (or PASS for sprint race if already correct, but SQ qualifying won't be correct).

- [ ] **Step 3: Implement changes to `_suggest_tool`**

In `resolver.py`, modify `_suggest_tool`:

```python
def _suggest_tool(entity_type: str | None, scope: str | None, session_type: str | None = None) -> str | None:
    if scope == "fp":
        return "get_fp_summary"
    if scope == "speed_trap":
        return "get_speed_trap_leaderboard"
    if scope == "radio":
        return "get_team_radio"
    if scope == "energy":
        return "analyze_energy_management"
    if scope == "pit_strategy":
        return "get_pit_stop_analysis"
    if scope == "weather_pace":
        return "analyze_weather_pace_correlation"
    if scope == "degradation" and entity_type == "driver":
        return "analyze_stint_degradation"
    # Sprint qualifying: prefer raw classification
    if session_type == "SQ" and scope in ("qualifying", None) and entity_type is None:
        return "get_sprint_qualifying_results"
    if entity_type == "driver":
        if session_type in ("S", "SQ"):
            # Sprint: race story for S, weekend overview for SQ
            if session_type == "S":
                return "get_driver_race_story"
            return "get_driver_weekend_overview"
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

- [ ] **Step 4: Run tests to verify they pass**

```
cd server && python -m pytest tests/test_resolver.py::test_suggest_tool_sprint_race_driver_entity tests/test_resolver.py::test_suggest_tool_sprint_qualifying_standalone tests/test_resolver.py::test_suggest_tool_sprint_race_no_entity -v
```
Expected: PASS.

- [ ] **Step 5: Run full test suite**

```
cd server && python -m pytest tests/ -v
```
Expected: all passing.

- [ ] **Step 6: Commit**

```bash
git add server/resolver.py server/tests/test_resolver.py
git commit -m "feat: update _suggest_tool for sprint session types in resolver"
```

---

## Self-Review

**Spec coverage check:**

| Requirement | Covered by |
|---|---|
| Sprint race data fetching | Task 1 (`get_sprint_results`) |
| Sprint qualifying data fetching | Task 1 (`get_sprint_qualifying_results`) |
| `analyze_qualifying_battle` works for SQ | Task 2 |
| `get_driver_race_story/weekend_overview` work for sprint | Task 3 |
| `get_team_weekend_overview` works for sprint | Task 4 |
| `get_race_report` works for sprint | Task 4 |
| Tool schemas expose `session_type` to the model | Task 5 |
| `execute_tool` dispatches `session_type` correctly | Task 5 |
| Model knows what to do for sprint questions | Task 6 (SYSTEM_PROMPT) |
| Deterministic plan routing uses sprint session types | Task 6 (`_build_analysis_plan`) |
| High-confidence preload routing handles sprint | Task 6 (`_suggested_tool_args`) |
| Resolver suggests correct tools for sprint | Task 7 |

**Placeholder scan:** No TBD, TODO, or "similar to task N" references found.

**Type consistency:** 
- `session_type` is always `str` defaulting to `"R"` (race) or `"Q"` (qualifying).
- `get_sprint_results` / `get_sprint_qualifying_results` added to imports in Task 5.
- All `execute_tool` calls use `args.get("session_type", "R")` or `"Q"` with explicit defaults.
- `_suggested_tool_args` now returns `session_type` in args dicts for composite tools — matches new `execute_tool` expectations.
