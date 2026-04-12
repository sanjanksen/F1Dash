# F1 Dashboard — Agentic Backend (Tool Use) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the static "pre-load context" chat pattern with a proper Anthropic tool-use agentic loop, so Claude dynamically calls exactly the data functions it needs — including granular per-lap sector times, speed traps, and raw telemetry — to answer questions like "why was Norris faster in S2 at Monaco qualifying?"

**Architecture:** Claude receives the user's question plus **11 tool definitions** spanning two data layers. Layer 1 (Jolpica REST API): standings, race results, qualifying, head-to-head. Layer 2 (FastF1 session data): per-lap sector times, speed traps (SpeedI1/I2/FL/ST), and full telemetry traces (speed/throttle/brake/gear/DRS sampled every 100m). Claude calls whichever tools it needs in as many rounds as necessary; the backend executes all tool calls in each round before continuing. A 5-round safety limit prevents infinite loops. The `get_f1_context` function is deleted — all data is fetched on-demand only.

**Tech Stack:** Anthropic Python SDK `messages.create` with `tools=` parameter, `stop_reason == "tool_use"` agentic loop, Jolpica-Ergast REST API, FastF1 3.x (laps + telemetry), pandas, pytest with `MagicMock`.

---

## How the Current Code Works (Background)

```
POST /api/chat  →  get_f1_context()          →  answer_f1_question(msg, context)
                   [always fetches top-10         [one Claude call, static context]
                    standings + next 3 races]
```

**Problems:** Fetches fixed data regardless of the question. No constructor standings. No race-by-race results. No head-to-head. No qualifying data. No sector times. No telemetry. Claude can't ask for more and can only give surface-level answers.

## How the New Code Works

```
POST /api/chat  →  answer_f1_question(msg)
                   │
                   ├── Round 1: Claude decides which tools to call
                   │   e.g. get_head_to_head + get_race_results
                   ├── Backend executes both tools
                   ├── Round 2: Claude reads results, may call more tools
                   └── Round N: Claude has enough → final text answer
```

---

## File Structure

```
server/
├── f1_data.py          # Modify: add _fetch_all_races helper, 4 Jolpica functions,
│                       #         4 FastF1 session functions, _fmt_td helper,
│                       #         remove get_f1_context
├── tools.py            # NEW: TOOL_DEFINITIONS (11 tools) + execute_tool dispatcher
├── chat.py             # Modify: replace with agentic loop (no f1_context param)
├── main.py             # Modify: remove get_f1_context import, simplify chat_endpoint
└── tests/
    ├── conftest.py     # Unchanged
    ├── test_f1_data.py # Modify: add tests for all 8 new data functions
    ├── test_tools.py   # NEW: test execute_tool dispatcher for all 11 tools
    ├── test_chat.py    # Replace: test agentic loop
    └── test_main.py    # Modify: remove get_f1_context patch
```

**New data functions in `f1_data.py`:**

*Jolpica REST API (Task 1):*
- `_fetch_all_races(driver_id)` — private: all race results for a driver (shared helper)
- `get_constructor_standings()` — team championship standings
- `get_race_results(round_number)` — full race finishing order for a specific round
- `get_qualifying_results(round_number)` — Q1/Q2/Q3 times for a specific round
- `get_head_to_head(driver_a, driver_b)` — side-by-side season comparison

*FastF1 session data (Task 2):*
- `_fmt_td(td)` — private: format `pd.Timedelta` → `"1:26.456"` string
- `get_session_fastest_laps(round_number, session_type)` — leaderboard with sector times + speed traps for every driver
- `get_driver_lap_times(round_number, session_type, driver_code)` — every lap a driver ran, with sector splits, speed traps, tyre data
- `get_sector_comparison(round_number, session_type, driver_a, driver_b)` — fastest-lap head-to-head with per-sector gap + speed trap deltas
- `get_lap_telemetry(round_number, session_type, driver_code, lap_number=None)` — speed/throttle/brake/gear/DRS sampled every 100m along the circuit

**`tools.py` exports:**
- `TOOL_DEFINITIONS` — list of **11** Anthropic tool schemas
- `execute_tool(name, args)` — dispatcher that calls the right `f1_data` function

---

## Task 1: Extend the F1 Data Layer

**Files:**
- Modify: `server/f1_data.py`
- Modify: `server/tests/test_f1_data.py`

- [ ] **Step 1: Write failing tests for the new data functions**

Open `server/tests/test_f1_data.py` and append these tests at the end of the file:

```python
# ─── Helpers ────────────────────────────────────────────────

def _make_constructor_standings_response():
    mock = MagicMock()
    mock.json.return_value = {
        "MRData": {
            "StandingsTable": {
                "StandingsLists": [{
                    "ConstructorStandings": [
                        {
                            "position": "1",
                            "points": "200",
                            "wins": "4",
                            "Constructor": {
                                "constructorId": "red_bull",
                                "name": "Red Bull Racing",
                                "nationality": "Austrian",
                            },
                        },
                        {
                            "position": "2",
                            "points": "160",
                            "wins": "2",
                            "Constructor": {
                                "constructorId": "mclaren",
                                "name": "McLaren",
                                "nationality": "British",
                            },
                        },
                    ]
                }]
            }
        }
    }
    mock.raise_for_status.return_value = None
    return mock


def _make_race_results_response():
    mock = MagicMock()
    mock.json.return_value = {
        "MRData": {
            "RaceTable": {
                "Races": [{
                    "raceName": "Bahrain Grand Prix",
                    "date": "2025-03-02",
                    "Circuit": {"circuitName": "Bahrain International Circuit"},
                    "Results": [
                        {
                            "position": "1",
                            "points": "25",
                            "status": "Finished",
                            "Driver": {
                                "driverId": "verstappen",
                                "givenName": "Max",
                                "familyName": "Verstappen",
                                "code": "VER",
                            },
                            "Constructor": {"name": "Red Bull Racing"},
                            "FastestLap": {"rank": "1"},
                        },
                        {
                            "position": "2",
                            "points": "18",
                            "status": "Finished",
                            "Driver": {
                                "driverId": "norris",
                                "givenName": "Lando",
                                "familyName": "Norris",
                                "code": "NOR",
                            },
                            "Constructor": {"name": "McLaren"},
                        },
                    ],
                }]
            }
        }
    }
    mock.raise_for_status.return_value = None
    return mock


def _make_qualifying_response():
    mock = MagicMock()
    mock.json.return_value = {
        "MRData": {
            "RaceTable": {
                "Races": [{
                    "raceName": "Bahrain Grand Prix",
                    "date": "2025-03-01",
                    "QualifyingResults": [
                        {
                            "position": "1",
                            "Driver": {
                                "driverId": "verstappen",
                                "givenName": "Max",
                                "familyName": "Verstappen",
                                "code": "VER",
                            },
                            "Constructor": {"name": "Red Bull Racing"},
                            "Q1": "1:29.832",
                            "Q2": "1:29.100",
                            "Q3": "1:28.658",
                        },
                        {
                            "position": "2",
                            "Driver": {
                                "driverId": "norris",
                                "givenName": "Lando",
                                "familyName": "Norris",
                                "code": "NOR",
                            },
                            "Constructor": {"name": "McLaren"},
                            "Q1": "1:29.900",
                            "Q2": "1:29.200",
                            "Q3": "1:28.900",
                        },
                    ],
                }]
            }
        }
    }
    mock.raise_for_status.return_value = None
    return mock


# ─── Tests ──────────────────────────────────────────────────

def test_get_constructor_standings():
    with patch('f1_data.requests.get', return_value=_make_constructor_standings_response()):
        import f1_data
        result = f1_data.get_constructor_standings()

    assert len(result) == 2
    assert result[0]['team'] == 'Red Bull Racing'
    assert result[0]['position'] == 1
    assert result[0]['points'] == 200.0
    assert result[0]['wins'] == 4
    assert result[0]['nationality'] == 'Austrian'
    assert result[1]['team'] == 'McLaren'


def test_get_constructor_standings_empty():
    mock = MagicMock()
    mock.json.return_value = {
        "MRData": {"StandingsTable": {"StandingsLists": []}}
    }
    mock.raise_for_status.return_value = None
    with patch('f1_data.requests.get', return_value=mock):
        import f1_data
        result = f1_data.get_constructor_standings()
    assert result == []


def test_get_race_results():
    with patch('f1_data.requests.get', return_value=_make_race_results_response()):
        import f1_data
        result = f1_data.get_race_results(1)

    assert result['race_name'] == 'Bahrain Grand Prix'
    assert result['date'] == '2025-03-02'
    assert result['circuit'] == 'Bahrain International Circuit'
    assert len(result['results']) == 2
    assert result['results'][0]['position'] == 1
    assert result['results'][0]['driver'] == 'Max Verstappen'
    assert result['results'][0]['code'] == 'VER'
    assert result['results'][0]['fastest_lap'] is True
    assert result['results'][1]['position'] == 2
    assert result['results'][1]['fastest_lap'] is False


def test_get_race_results_empty_round():
    mock = MagicMock()
    mock.json.return_value = {"MRData": {"RaceTable": {"Races": []}}}
    mock.raise_for_status.return_value = None
    with patch('f1_data.requests.get', return_value=mock):
        import f1_data
        result = f1_data.get_race_results(99)
    assert result == {}


def test_get_qualifying_results():
    with patch('f1_data.requests.get', return_value=_make_qualifying_response()):
        import f1_data
        result = f1_data.get_qualifying_results(1)

    assert result['race_name'] == 'Bahrain Grand Prix'
    assert len(result['results']) == 2
    assert result['results'][0]['position'] == 1
    assert result['results'][0]['driver'] == 'Max Verstappen'
    assert result['results'][0]['q3'] == '1:28.658'
    assert result['results'][1]['q3'] == '1:28.900'


def test_get_head_to_head():
    standings_mock = _make_standings_response()

    # Two separate results fetches — one per driver
    results_ver = _make_results_response('verstappen')
    results_nor = MagicMock()
    results_nor.raise_for_status.return_value = None
    results_nor.json.return_value = {
        "MRData": {
            "RaceTable": {
                "Races": [
                    {
                        "raceName": "Bahrain Grand Prix",
                        "Results": [{"position": "2", "points": "18",
                                     "Driver": {"driverId": "norris"}}]
                    },
                    {
                        "raceName": "Saudi Arabian Grand Prix",
                        "Results": [{"position": "1", "points": "25",
                                     "Driver": {"driverId": "norris"}}]
                    },
                ]
            }
        }
    }

    # Call order: standings, races_verstappen, standings, races_norris
    with patch('f1_data.requests.get',
               side_effect=[standings_mock, results_ver, standings_mock, results_nor]):
        import f1_data
        result = f1_data.get_head_to_head('verstappen', 'norris')

    assert result['driver_a'] == 'Max Verstappen'
    assert result['driver_b'] == 'Lando Norris'
    # Bahrain: VER P1 vs NOR P2 → VER ahead
    # Saudi: VER P3 vs NOR P1 → NOR ahead
    assert result['races_a_ahead'] == 1
    assert result['races_b_ahead'] == 1
    assert result['races_compared'] == 2


def test_get_head_to_head_driver_not_found():
    standings_mock = _make_standings_response()
    with patch('f1_data.requests.get', return_value=standings_mock):
        import f1_data
        with pytest.raises(ValueError, match="not found"):
            f1_data.get_head_to_head('nobody', 'verstappen')
```

- [ ] **Step 2: Run to verify all new tests fail**

```bash
cd server && python -m pytest tests/test_f1_data.py -v -k "constructor or race_results or qualifying or head_to_head"
```

Expected: All new tests FAIL with `AttributeError: module 'f1_data' has no attribute ...`

- [ ] **Step 3: Add `_fetch_all_races` helper and refactor `get_driver_stats`**

Open `server/f1_data.py`. Add this private helper after the `CURRENT_YEAR` constant and before `get_drivers()`:

```python
def _fetch_all_races(driver_id: str) -> list[dict]:
    """Fetch all 2025 race results for a driver. Used by get_driver_stats and get_head_to_head."""
    resp = requests.get(
        f"{JOLPICA_BASE}/{CURRENT_YEAR}/drivers/{driver_id}/results.json?limit=30",
        timeout=15,
    )
    resp.raise_for_status()
    races_data = resp.json()["MRData"]["RaceTable"]["Races"]
    results = []
    for race in races_data:
        r_list = race.get("Results", [])
        if not r_list:
            continue
        r = r_list[0]
        pos_str = r.get("position", "")
        pos = int(pos_str) if pos_str.isdigit() else None
        fl = r.get("FastestLap", {})
        results.append({
            "race": race.get("raceName", ""),
            "position": pos,
            "points": float(r.get("points", 0)),
            "fastest_lap": fl.get("rank") == "1",
        })
    return results
```

Then refactor `get_driver_stats` to use `_fetch_all_races` — replace the inline fetch loop with a call to the helper:

```python
def get_driver_stats(driver_name: str) -> dict | None:
    """Return wins, podiums, fastest laps, recent races for a driver."""
    all_drivers = get_drivers()
    matched = None
    needle = driver_name.lower()
    for d in all_drivers:
        if (
            needle in d["full_name"].lower()
            or needle == d["driver_id"].lower()
            or needle == d["code"].lower()
        ):
            matched = d
            break

    if matched is None:
        return None

    all_races = _fetch_all_races(matched["driver_id"])

    wins = sum(1 for r in all_races if r["position"] == 1)
    podiums = sum(1 for r in all_races if r["position"] is not None and 1 <= r["position"] <= 3)
    fastest_laps = sum(1 for r in all_races if r["fastest_lap"])

    return {
        "driver": matched["full_name"],
        "code": matched["code"],
        "team": matched["team"],
        "nationality": matched["nationality"],
        "wins": wins,
        "podiums": podiums,
        "fastest_laps": fastest_laps,
        "championship_position": matched["standing"],
        "points": matched["points"],
        "recent_races": all_races[-5:],
    }
```

- [ ] **Step 4: Add the 4 new data functions**

Append these functions to `server/f1_data.py` (before or after `get_circuits` — order doesn't matter):

```python
def get_constructor_standings() -> list[dict]:
    """Return all constructor (team) championship standings for 2025."""
    resp = requests.get(
        f"{JOLPICA_BASE}/{CURRENT_YEAR}/constructorStandings.json?limit=20",
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    standings_lists = data["MRData"]["StandingsTable"]["StandingsLists"]
    if not standings_lists:
        return []
    return [
        {
            "position": int(entry["position"]),
            "team": entry["Constructor"]["name"],
            "nationality": entry["Constructor"]["nationality"],
            "points": float(entry["points"]),
            "wins": int(entry["wins"]),
        }
        for entry in standings_lists[0]["ConstructorStandings"]
    ]


def get_race_results(round_number: int) -> dict:
    """Return the full finishing order for a specific 2025 Grand Prix round."""
    resp = requests.get(
        f"{JOLPICA_BASE}/{CURRENT_YEAR}/{round_number}/results.json?limit=30",
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
            for r in race.get("Results", [])
        ],
    }


def get_qualifying_results(round_number: int) -> dict:
    """Return Q1/Q2/Q3 times for all drivers at a specific 2025 Grand Prix round."""
    resp = requests.get(
        f"{JOLPICA_BASE}/{CURRENT_YEAR}/{round_number}/qualifying.json?limit=30",
        timeout=15,
    )
    resp.raise_for_status()
    races = resp.json()["MRData"]["RaceTable"]["Races"]
    if not races:
        return {}
    race = races[0]
    return {
        "race_name": race["raceName"],
        "date": race.get("date", ""),
        "results": [
            {
                "position": int(r["position"]),
                "driver": f"{r['Driver']['givenName']} {r['Driver']['familyName']}",
                "code": r["Driver"].get("code", ""),
                "team": r["Constructor"]["name"],
                "q1": r.get("Q1", ""),
                "q2": r.get("Q2", ""),
                "q3": r.get("Q3", ""),
            }
            for r in race.get("QualifyingResults", [])
        ],
    }


def get_head_to_head(driver_a_name: str, driver_b_name: str) -> dict:
    """Compare two drivers side-by-side across all 2025 races they both competed in."""
    all_drivers = get_drivers()

    def _find(name: str) -> dict | None:
        needle = name.lower()
        for d in all_drivers:
            if (
                needle in d["full_name"].lower()
                or needle == d["driver_id"].lower()
                or needle == d["code"].lower()
            ):
                return d
        return None

    matched_a = _find(driver_a_name)
    matched_b = _find(driver_b_name)

    if matched_a is None:
        raise ValueError(f"Driver not found: {driver_a_name}")
    if matched_b is None:
        raise ValueError(f"Driver not found: {driver_b_name}")

    races_a = _fetch_all_races(matched_a["driver_id"])
    races_b = _fetch_all_races(matched_b["driver_id"])

    lookup_b = {r["race"]: r for r in races_b}

    a_ahead = 0
    b_ahead = 0
    for ra in races_a:
        rb = lookup_b.get(ra["race"])
        if rb is None:
            continue
        pa, pb = ra["position"], rb["position"]
        if pa is not None and pb is not None:
            if pa < pb:
                a_ahead += 1
            elif pb < pa:
                b_ahead += 1

    return {
        "driver_a": matched_a["full_name"],
        "driver_b": matched_b["full_name"],
        "team_a": matched_a["team"],
        "team_b": matched_b["team"],
        "points_a": matched_a["points"],
        "points_b": matched_b["points"],
        "points_gap": round(matched_a["points"] - matched_b["points"], 1),
        "championship_position_a": matched_a["standing"],
        "championship_position_b": matched_b["standing"],
        "wins_a": matched_a["wins"],
        "wins_b": matched_b["wins"],
        "races_a_ahead": a_ahead,
        "races_b_ahead": b_ahead,
        "races_compared": a_ahead + b_ahead,
    }
```

- [ ] **Step 5: Delete `get_f1_context` from `f1_data.py`**

Delete the entire `get_f1_context` function (the last function in the file, ~20 lines including the docstring). It is replaced by the tool-use pattern.

Also remove the `from datetime import date` import if it was only used by `get_f1_context`. Verify the import is no longer needed:

```bash
grep -n "date" server/f1_data.py
```

If `date` only appears in the deleted function, remove the `from datetime import date` line.

- [ ] **Step 6: Run all f1_data tests**

```bash
cd server && python -m pytest tests/test_f1_data.py -v
```

Expected: All tests PASS including the pre-existing ones (which test `get_driver_stats` — verify the refactor didn't break anything).

- [ ] **Step 7: Commit**

```bash
git add server/f1_data.py server/tests/test_f1_data.py
git commit -m "feat: extend data layer — constructor standings, race/qualifying results, head-to-head, refactor to _fetch_all_races"
```

---

## Task 2: FastF1 Session Data Tools — Lap Times, Sector Splits, Telemetry

**Files:**
- Modify: `server/f1_data.py`
- Modify: `server/tests/test_f1_data.py`

This task adds the deep session data layer. FastF1 loads race/qualifying session data from the official F1 timing feed and exposes it as pandas DataFrames. The four new functions answer questions like "why was Norris 0.3s faster in S2?" and "what was Leclerc's speed through the high-speed section?"

**Key FastF1 facts:**
- `fastf1.get_session(year, round, session_type)` returns a Session object
- `session.load(laps=True, telemetry=False)` loads the laps DataFrame without heavy telemetry
- `session.laps.pick_driver("NOR")` returns a filtered Laps DataFrame
- `.pick_fastest()` returns a single `pd.Series` (one lap record)
- Laps have: `LapTime`, `Sector1Time`, `Sector2Time`, `Sector3Time` (all `pd.Timedelta`), `Compound`, `TyreLife`, `LapNumber`, `IsPersonalBest`, `SpeedI1`, `SpeedI2`, `SpeedFL`, `SpeedST` (speed trap km/h)
- `lap.get_telemetry().add_distance()` returns a DataFrame with `Distance` (m), `Speed` (km/h), `Throttle` (0-100), `Brake` (bool), `nGear`, `DRS`
- Valid `session_type` values: `'Q'`, `'R'`, `'FP1'`, `'FP2'`, `'FP3'`, `'S'`, `'SQ'`, `'SS'`
- `pd.isna()` / `pd.notna()` is required — timing columns can be NaT for laps with no data

- [ ] **Step 1: Write failing FastF1 tests**

Append to `server/tests/test_f1_data.py`:

```python
# ─── FastF1 session data tests ──────────────────────────────

import pandas as pd


def _make_mock_fastest_lap(driver="NOR", team="McLaren",
                            lap_time_s=86.456,
                            s1=28.123, s2=29.200, s3=29.133,
                            compound="SOFT", tyre_life=3, lap_num=12,
                            speed_i1=220.5, speed_i2=185.3,
                            speed_fl=295.0, speed_st=315.2):
    return pd.Series({
        'Driver': driver,
        'Team': team,
        'LapTime': pd.Timedelta(seconds=lap_time_s),
        'Sector1Time': pd.Timedelta(seconds=s1),
        'Sector2Time': pd.Timedelta(seconds=s2),
        'Sector3Time': pd.Timedelta(seconds=s3),
        'Compound': compound,
        'TyreLife': float(tyre_life),
        'LapNumber': float(lap_num),
        'IsPersonalBest': True,
        'SpeedI1': speed_i1,
        'SpeedI2': speed_i2,
        'SpeedFL': speed_fl,
        'SpeedST': speed_st,
        'PitInTime': pd.NaT,
        'PitOutTime': pd.NaT,
    })


def _make_mock_session(fastest_laps_by_driver: dict, event_name="Monaco Grand Prix"):
    """Build a mock FastF1 session given {driver_code: pd.Series}."""
    mock_session = MagicMock()
    mock_session.event = {'EventName': event_name}
    mock_session.drivers = list(fastest_laps_by_driver.keys())

    def pick_driver(code):
        if code not in fastest_laps_by_driver:
            mock_laps = MagicMock()
            mock_laps.empty = True
            return mock_laps
        fastest = fastest_laps_by_driver[code]
        # Build a 1-row DataFrame so iterrows() works too
        lap_df = pd.DataFrame([fastest])
        mock_laps = MagicMock()
        mock_laps.empty = False
        mock_laps.pick_fastest.return_value = fastest
        mock_laps.__iter__ = lambda self: iter([fastest])
        mock_laps.iterrows.return_value = iter(lap_df.iterrows())
        return mock_laps

    mock_session.laps.pick_driver.side_effect = pick_driver
    return mock_session


def _make_mock_telemetry(n_points=50, circuit_length_m=5000):
    distances = [i * circuit_length_m / n_points for i in range(n_points)]
    speeds = [150 + 150 * abs(i / n_points - 0.5) for i in range(n_points)]
    return pd.DataFrame({
        'Distance': distances,
        'Speed': speeds,
        'Throttle': [100.0 if i > 10 else 0.0 for i in range(n_points)],
        'Brake': [i <= 10 for i in range(n_points)],
        'nGear': [8 if i > 10 else 4 for i in range(n_points)],
        'DRS': [12 if i > 30 else 0 for i in range(n_points)],
    })


def test_get_session_fastest_laps():
    nor_lap = _make_mock_fastest_lap("NOR", lap_time_s=86.456)
    lec_lap = _make_mock_fastest_lap("LEC", "Ferrari", lap_time_s=86.712,
                                     s1=28.200, s2=29.400, s3=29.112,
                                     speed_i1=218.0, speed_st=312.0)
    mock_session = _make_mock_session({"NOR": nor_lap, "LEC": lec_lap})

    with patch('f1_data.fastf1.get_session', return_value=mock_session):
        import f1_data
        result = f1_data.get_session_fastest_laps(8, 'Q')

    assert len(result) == 2
    # Sorted fastest first
    assert result[0]['driver'] == 'NOR'
    assert result[0]['position'] == 1
    assert result[1]['driver'] == 'LEC'
    assert result[1]['position'] == 2
    assert result[0]['sector1'] == '0:28.123'
    assert result[0]['speed_st'] == 315.2
    assert result[0]['compound'] == 'SOFT'


def test_get_driver_lap_times():
    nor_lap = _make_mock_fastest_lap("NOR")
    mock_session = _make_mock_session({"NOR": nor_lap})

    with patch('f1_data.fastf1.get_session', return_value=mock_session):
        import f1_data
        result = f1_data.get_driver_lap_times(8, 'Q', 'NOR')

    assert result['driver'] == 'NOR'
    assert result['event'] == 'Monaco Grand Prix'
    assert result['session'] == 'Q'
    assert len(result['laps']) == 1
    assert result['laps'][0]['lap_number'] == 12
    assert result['laps'][0]['compound'] == 'SOFT'
    assert result['laps'][0]['speed_st'] == 315.2


def test_get_driver_lap_times_driver_not_found():
    mock_session = _make_mock_session({})

    with patch('f1_data.fastf1.get_session', return_value=mock_session):
        import f1_data
        with pytest.raises(ValueError, match="No data"):
            f1_data.get_driver_lap_times(8, 'Q', 'ZZZ')


def test_get_sector_comparison():
    nor_lap = _make_mock_fastest_lap("NOR", lap_time_s=86.456,
                                     s1=28.123, s2=29.200, s3=29.133,
                                     speed_i2=185.3)
    lec_lap = _make_mock_fastest_lap("LEC", "Ferrari", lap_time_s=86.712,
                                     s1=28.200, s2=29.400, s3=29.112,
                                     speed_i2=180.1)
    mock_session = _make_mock_session({"NOR": nor_lap, "LEC": lec_lap})

    with patch('f1_data.fastf1.get_session', return_value=mock_session):
        import f1_data
        result = f1_data.get_sector_comparison(8, 'Q', 'NOR', 'LEC')

    assert result['driver_a'] == 'NOR'
    assert result['driver_b'] == 'LEC'
    # NOR faster overall: gap should be negative (NOR - LEC < 0)
    assert result['overall_gap_s'] < 0
    # NOR faster in S2: gap_s negative
    assert result['sector2']['gap_s'] < 0
    # Speed I2 delta: NOR 185.3 - LEC 180.1 = positive (NOR faster through that point)
    assert result['sector2']['speed_i2_delta'] > 0


def test_get_lap_telemetry():
    nor_lap = _make_mock_fastest_lap("NOR")
    mock_session = _make_mock_session({"NOR": nor_lap})

    mock_tel = _make_mock_telemetry(n_points=50, circuit_length_m=3300)

    # The fastest lap Series needs get_telemetry().add_distance() to work
    # Since we use a real pd.Series for nor_lap, we need to make get_telemetry
    # work. In practice this is a FastF1 Lap method — we patch it at the module level.
    mock_lap_obj = MagicMock()
    mock_lap_obj.__getitem__.side_effect = lambda k: nor_lap[k]
    mock_lap_obj.get.side_effect = lambda k, d=None: nor_lap.get(k, d)
    mock_lap_obj.get_telemetry.return_value.add_distance.return_value = mock_tel

    def pick_driver_tel(code):
        mock_laps = MagicMock()
        mock_laps.empty = False
        mock_laps.pick_fastest.return_value = mock_lap_obj
        return mock_laps

    mock_session.laps.pick_driver.side_effect = pick_driver_tel

    with patch('f1_data.fastf1.get_session', return_value=mock_session):
        import f1_data
        result = f1_data.get_lap_telemetry(8, 'Q', 'NOR')

    assert result['driver'] == 'NOR'
    assert result['circuit_length_m'] > 0
    assert result['max_speed_kph'] > 0
    # Sampled every 100m — should have ~33 samples for a 3300m circuit
    assert len(result['telemetry']) > 0
    first = result['telemetry'][0]
    assert 'distance_m' in first
    assert 'speed_kph' in first
    assert 'throttle_pct' in first
    assert 'brake' in first
    assert 'gear' in first
    assert 'drs_open' in first
```

- [ ] **Step 2: Run to verify new tests fail**

```bash
cd server && python -m pytest tests/test_f1_data.py -v -k "session_fastest or driver_lap or sector_comp or lap_telemetry"
```

Expected: All 6 new tests FAIL with `AttributeError`.

- [ ] **Step 3: Add `_fmt_td` helper and `import pandas as pd` to `f1_data.py`**

At the top of `server/f1_data.py`, add `import pandas as pd` after the existing imports.

Then add this private helper function after the `CURRENT_YEAR` constant (before `_fetch_all_races`):

```python
def _fmt_td(td) -> str | None:
    """Format a pd.Timedelta to a lap-time string like '1:26.456' or '28.123s'."""
    if td is None or pd.isna(td):
        return None
    total = td.total_seconds()
    m = int(total // 60)
    s = total % 60
    return f"{m}:{s:06.3f}" if m > 0 else f"{s:.3f}s"
```

- [ ] **Step 4: Add `get_session_fastest_laps`**

Append to `server/f1_data.py`:

```python
def get_session_fastest_laps(round_number: int, session_type: str) -> list[dict]:
    """
    Leaderboard of fastest laps for every driver in a session.
    Includes sector times (S1/S2/S3) and speed trap values (SpeedI1/I2/FL/ST).
    session_type: 'Q', 'R', 'FP1', 'FP2', 'FP3', 'S', 'SQ', 'SS'
    """
    session = fastf1.get_session(CURRENT_YEAR, round_number, session_type)
    session.load(laps=True, telemetry=False, weather=False, messages=False)

    results = []
    for driver_code in session.drivers:
        driver_laps = session.laps.pick_driver(driver_code)
        if driver_laps.empty:
            continue
        fastest = driver_laps.pick_fastest()
        if pd.isna(fastest['LapTime']):
            continue
        results.append({
            "driver": str(fastest['Driver']),
            "team": str(fastest['Team']),
            "lap_time": _fmt_td(fastest['LapTime']),
            "lap_time_s": round(fastest['LapTime'].total_seconds(), 3),
            "sector1": _fmt_td(fastest['Sector1Time']),
            "sector2": _fmt_td(fastest['Sector2Time']),
            "sector3": _fmt_td(fastest['Sector3Time']),
            "speed_i1": round(float(fastest['SpeedI1']), 1) if pd.notna(fastest.get('SpeedI1')) else None,
            "speed_i2": round(float(fastest['SpeedI2']), 1) if pd.notna(fastest.get('SpeedI2')) else None,
            "speed_fl": round(float(fastest['SpeedFL']), 1) if pd.notna(fastest.get('SpeedFL')) else None,
            "speed_st": round(float(fastest['SpeedST']), 1) if pd.notna(fastest.get('SpeedST')) else None,
            "compound": str(fastest['Compound']) if pd.notna(fastest.get('Compound')) else None,
            "tyre_life": int(fastest['TyreLife']) if pd.notna(fastest.get('TyreLife')) else None,
            "lap_number": int(fastest['LapNumber']),
        })

    results.sort(key=lambda x: x['lap_time_s'])
    for i, r in enumerate(results):
        r['position'] = i + 1
    return results
```

- [ ] **Step 5: Add `get_driver_lap_times`**

Append to `server/f1_data.py`:

```python
def get_driver_lap_times(round_number: int, session_type: str, driver_code: str) -> dict:
    """
    All laps a driver completed in a session, with per-lap sector splits,
    speed traps, tyre compound, and pit stop flags.
    Answers: "how did Norris's pace evolve across his qualifying runs?"
    """
    session = fastf1.get_session(CURRENT_YEAR, round_number, session_type)
    session.load(laps=True, telemetry=False, weather=False, messages=False)

    driver_laps = session.laps.pick_driver(driver_code.upper())
    if driver_laps.empty:
        raise ValueError(f"No data for driver {driver_code!r} in round {round_number} {session_type}")

    laps = []
    for _, lap in driver_laps.iterrows():
        laps.append({
            "lap_number": int(lap['LapNumber']),
            "lap_time": _fmt_td(lap['LapTime']),
            "sector1": _fmt_td(lap['Sector1Time']),
            "sector2": _fmt_td(lap['Sector2Time']),
            "sector3": _fmt_td(lap['Sector3Time']),
            "speed_i1": round(float(lap['SpeedI1']), 1) if pd.notna(lap.get('SpeedI1')) else None,
            "speed_i2": round(float(lap['SpeedI2']), 1) if pd.notna(lap.get('SpeedI2')) else None,
            "speed_fl": round(float(lap['SpeedFL']), 1) if pd.notna(lap.get('SpeedFL')) else None,
            "speed_st": round(float(lap['SpeedST']), 1) if pd.notna(lap.get('SpeedST')) else None,
            "compound": str(lap['Compound']) if pd.notna(lap.get('Compound')) else None,
            "tyre_life": int(lap['TyreLife']) if pd.notna(lap.get('TyreLife')) else None,
            "pit_in": pd.notna(lap.get('PitInTime')),
            "pit_out": pd.notna(lap.get('PitOutTime')),
            "is_personal_best": bool(lap.get('IsPersonalBest', False)),
        })

    return {
        "driver": driver_code.upper(),
        "event": session.event['EventName'],
        "session": session_type.upper(),
        "laps": laps,
    }
```

- [ ] **Step 6: Add `get_sector_comparison`**

Append to `server/f1_data.py`:

```python
def get_sector_comparison(round_number: int, session_type: str,
                          driver_a: str, driver_b: str) -> dict:
    """
    Head-to-head fastest-lap comparison between two drivers.
    Shows time gap per sector AND speed trap deltas (SpeedI1/I2/FL/ST).
    Positive gap_s = driver_a is SLOWER. Positive speed_delta = driver_a is FASTER.
    Answers: "why was Norris 0.3s faster than Leclerc in sector 2?"
    """
    session = fastf1.get_session(CURRENT_YEAR, round_number, session_type)
    session.load(laps=True, telemetry=False, weather=False, messages=False)

    def _fastest(code: str):
        laps = session.laps.pick_driver(code.upper())
        if laps.empty:
            raise ValueError(f"No session data for driver {code!r}")
        fastest = laps.pick_fastest()
        if pd.isna(fastest['LapTime']):
            raise ValueError(f"No valid lap time found for {code!r}")
        return fastest

    lap_a = _fastest(driver_a)
    lap_b = _fastest(driver_b)

    def _s(td) -> float | None:
        return round(td.total_seconds(), 3) if pd.notna(td) else None

    def _gap(a, b) -> float | None:
        """Positive = a is slower than b."""
        return round(a - b, 3) if a is not None and b is not None else None

    def _spd(lap, key) -> float | None:
        v = lap.get(key)
        return round(float(v), 1) if v is not None and pd.notna(v) else None

    s1a, s1b = _s(lap_a['Sector1Time']), _s(lap_b['Sector1Time'])
    s2a, s2b = _s(lap_a['Sector2Time']), _s(lap_b['Sector2Time'])
    s3a, s3b = _s(lap_a['Sector3Time']), _s(lap_b['Sector3Time'])

    return {
        "event": session.event['EventName'],
        "session": session_type.upper(),
        "driver_a": driver_a.upper(),
        "driver_b": driver_b.upper(),
        "lap_time_a": _fmt_td(lap_a['LapTime']),
        "lap_time_b": _fmt_td(lap_b['LapTime']),
        "overall_gap_s": _gap(_s(lap_a['LapTime']), _s(lap_b['LapTime'])),
        "compound_a": str(lap_a['Compound']) if pd.notna(lap_a.get('Compound')) else None,
        "compound_b": str(lap_b['Compound']) if pd.notna(lap_b.get('Compound')) else None,
        "tyre_life_a": int(lap_a['TyreLife']) if pd.notna(lap_a.get('TyreLife')) else None,
        "tyre_life_b": int(lap_b['TyreLife']) if pd.notna(lap_b.get('TyreLife')) else None,
        "sector1": {
            "time_a": _fmt_td(lap_a['Sector1Time']),
            "time_b": _fmt_td(lap_b['Sector1Time']),
            "gap_s": _gap(s1a, s1b),
            "speed_i1_a": _spd(lap_a, 'SpeedI1'),
            "speed_i1_b": _spd(lap_b, 'SpeedI1'),
            "speed_i1_delta": _gap(_spd(lap_a, 'SpeedI1'), _spd(lap_b, 'SpeedI1')),
        },
        "sector2": {
            "time_a": _fmt_td(lap_a['Sector2Time']),
            "time_b": _fmt_td(lap_b['Sector2Time']),
            "gap_s": _gap(s2a, s2b),
            "speed_i2_a": _spd(lap_a, 'SpeedI2'),
            "speed_i2_b": _spd(lap_b, 'SpeedI2'),
            "speed_i2_delta": _gap(_spd(lap_a, 'SpeedI2'), _spd(lap_b, 'SpeedI2')),
        },
        "sector3": {
            "time_a": _fmt_td(lap_a['Sector3Time']),
            "time_b": _fmt_td(lap_b['Sector3Time']),
            "gap_s": _gap(s3a, s3b),
            "speed_fl_a": _spd(lap_a, 'SpeedFL'),
            "speed_fl_b": _spd(lap_b, 'SpeedFL'),
            "speed_fl_delta": _gap(_spd(lap_a, 'SpeedFL'), _spd(lap_b, 'SpeedFL')),
        },
        "speed_trap_a": _spd(lap_a, 'SpeedST'),
        "speed_trap_b": _spd(lap_b, 'SpeedST'),
        "speed_trap_delta": _gap(_spd(lap_a, 'SpeedST'), _spd(lap_b, 'SpeedST')),
    }
```

- [ ] **Step 7: Add `get_lap_telemetry`**

Append to `server/f1_data.py`:

```python
def get_lap_telemetry(round_number: int, session_type: str,
                      driver_code: str, lap_number: int | None = None) -> dict:
    """
    Full telemetry trace for a driver's lap (defaults to their fastest lap).
    Returns speed/throttle/brake/gear/DRS sampled every 100m along the circuit.
    This is the deepest data level — use it to explain corner-specific pace differences.
    Requires session.load(telemetry=True); first load is slow, subsequent are cached.
    """
    session = fastf1.get_session(CURRENT_YEAR, round_number, session_type)
    session.load(laps=True, telemetry=True, weather=False, messages=False)

    driver_laps = session.laps.pick_driver(driver_code.upper())
    if driver_laps.empty:
        raise ValueError(f"No data for driver {driver_code!r}")

    if lap_number is not None:
        matching = driver_laps[driver_laps['LapNumber'] == lap_number]
        if matching.empty:
            raise ValueError(f"Lap {lap_number} not found for {driver_code!r}")
        lap = matching.iloc[0]
    else:
        lap = driver_laps.pick_fastest()

    tel = lap.get_telemetry().add_distance()
    total_dist = float(tel['Distance'].max())

    INTERVAL_M = 100
    samples = []
    dist = 0.0
    while dist <= total_dist:
        idx = (tel['Distance'] - dist).abs().idxmin()
        row = tel.loc[idx]
        samples.append({
            "distance_m": int(dist),
            "speed_kph": round(float(row['Speed']), 1),
            "throttle_pct": round(float(row['Throttle']), 1),
            "brake": bool(row['Brake']),
            "gear": int(row['nGear']) if pd.notna(row['nGear']) else None,
            "drs_open": int(row['DRS']) >= 10 if pd.notna(row['DRS']) else False,
        })
        dist += INTERVAL_M

    return {
        "driver": driver_code.upper(),
        "event": session.event['EventName'],
        "session": session_type.upper(),
        "lap_number": int(lap['LapNumber']),
        "lap_time": _fmt_td(lap['LapTime']),
        "sector1": _fmt_td(lap['Sector1Time']),
        "sector2": _fmt_td(lap['Sector2Time']),
        "sector3": _fmt_td(lap['Sector3Time']),
        "compound": str(lap['Compound']) if pd.notna(lap.get('Compound')) else None,
        "tyre_life": int(lap['TyreLife']) if pd.notna(lap.get('TyreLife')) else None,
        "max_speed_kph": round(float(tel['Speed'].max()), 1),
        "min_speed_kph": round(float(tel['Speed'].min()), 1),
        "circuit_length_m": int(total_dist),
        "telemetry": samples,
    }
```

- [ ] **Step 8: Run all FastF1 tests**

```bash
cd server && python -m pytest tests/test_f1_data.py -v -k "session_fastest or driver_lap or sector_comp or lap_telemetry"
```

Expected: All 6 new tests PASS.

- [ ] **Step 9: Run full test suite to verify nothing broke**

```bash
cd server && python -m pytest tests/test_f1_data.py -v
```

Expected: All tests PASS.

- [ ] **Step 10: Commit**

```bash
git add server/f1_data.py server/tests/test_f1_data.py
git commit -m "feat: FastF1 session data tools — sector splits, speed traps, lap-by-lap, telemetry"
```

---

## Task 3: Build the Tool Definitions and Dispatcher

**Files:**
- Create: `server/tools.py`
- Create: `server/tests/test_tools.py`

This task creates the bridge between Claude's tool calls and the `f1_data` functions. There are two exports: `TOOL_DEFINITIONS` (the JSON schemas Claude reads to decide what to call) and `execute_tool` (the dispatcher that runs the actual function).

- [ ] **Step 1: Write failing tests for the tool dispatcher**

Create `server/tests/test_tools.py`:

```python
# server/tests/test_tools.py
import pytest
from unittest.mock import patch
import tools


def test_execute_tool_get_driver_standings_returns_sliced_list():
    mock_drivers = [
        {"full_name": "Max Verstappen", "team": "Red Bull", "standing": 1,
         "points": 150.0, "wins": 4, "code": "VER", "nationality": "Dutch",
         "driver_id": "verstappen"},
        {"full_name": "Lando Norris", "team": "McLaren", "standing": 2,
         "points": 120.0, "wins": 2, "code": "NOR", "nationality": "British",
         "driver_id": "norris"},
    ]
    with patch('tools.get_drivers', return_value=mock_drivers):
        result = tools.execute_tool("get_driver_standings", {"limit": 1})
    assert len(result) == 1
    assert result[0]["full_name"] == "Max Verstappen"


def test_execute_tool_get_driver_standings_default_limit():
    mock_drivers = [{"full_name": f"Driver {i}", "standing": i} for i in range(1, 22)]
    with patch('tools.get_drivers', return_value=mock_drivers):
        result = tools.execute_tool("get_driver_standings", {})
    assert len(result) == 20  # default limit


def test_execute_tool_get_constructor_standings():
    mock = [{"team": "Red Bull Racing", "position": 1, "points": 200.0, "wins": 4}]
    with patch('tools.get_constructor_standings', return_value=mock):
        result = tools.execute_tool("get_constructor_standings", {})
    assert result[0]["team"] == "Red Bull Racing"


def test_execute_tool_get_driver_season_stats_found():
    mock_stats = {"driver": "Lando Norris", "wins": 2, "podiums": 6, "points": 120.0}
    with patch('tools.get_driver_stats', return_value=mock_stats):
        result = tools.execute_tool("get_driver_season_stats", {"driver_name": "norris"})
    assert result["driver"] == "Lando Norris"


def test_execute_tool_get_driver_season_stats_not_found():
    with patch('tools.get_driver_stats', return_value=None):
        with pytest.raises(ValueError, match="not found"):
            tools.execute_tool("get_driver_season_stats", {"driver_name": "nobody"})


def test_execute_tool_get_race_results():
    mock = {"race_name": "Bahrain Grand Prix", "results": []}
    with patch('tools.get_race_results', return_value=mock):
        result = tools.execute_tool("get_race_results", {"round_number": 1})
    assert result["race_name"] == "Bahrain Grand Prix"


def test_execute_tool_get_qualifying_results():
    mock = {"race_name": "Bahrain Grand Prix", "results": []}
    with patch('tools.get_qualifying_results', return_value=mock):
        result = tools.execute_tool("get_qualifying_results", {"round_number": 1})
    assert result["race_name"] == "Bahrain Grand Prix"


def test_execute_tool_get_season_schedule():
    mock = [{"round": 1, "event_name": "Bahrain Grand Prix", "date": "2025-03-02"}]
    with patch('tools.get_circuits', return_value=mock):
        result = tools.execute_tool("get_season_schedule", {})
    assert result[0]["event_name"] == "Bahrain Grand Prix"


def test_execute_tool_get_head_to_head():
    mock = {"driver_a": "Max Verstappen", "driver_b": "Lando Norris",
            "points_gap": 30.0, "races_a_ahead": 5, "races_b_ahead": 3}
    with patch('tools.get_head_to_head', return_value=mock):
        result = tools.execute_tool("get_head_to_head",
                                    {"driver_a": "verstappen", "driver_b": "norris"})
    assert result["driver_a"] == "Max Verstappen"


def test_execute_tool_unknown_raises_value_error():
    with pytest.raises(ValueError, match="Unknown tool"):
        tools.execute_tool("launch_rocket", {})


def test_tool_definitions_are_valid_schemas():
    """Every tool definition must have name, description, and input_schema."""
    for tool in tools.TOOL_DEFINITIONS:
        assert "name" in tool
        assert "description" in tool
        assert len(tool["description"]) > 20, f"Tool {tool['name']} description too short"
        assert "input_schema" in tool
        assert tool["input_schema"]["type"] == "object"
```

- [ ] **Step 2: Run to verify tests fail**

```bash
cd server && python -m pytest tests/test_tools.py -v
```

Expected: `ModuleNotFoundError: No module named 'tools'`

- [ ] **Step 3: Create `server/tools.py`**

```python
# server/tools.py
"""
Tool definitions for the Anthropic tool-use agentic loop.

TOOL_DEFINITIONS — list of tool schemas passed to client.messages.create(tools=...)
execute_tool(name, args) — dispatcher that runs the matching f1_data function
"""
from f1_data import (
    get_drivers,
    get_constructor_standings,
    get_driver_stats,
    get_race_results,
    get_qualifying_results,
    get_circuits,
    get_head_to_head,
)

TOOL_DEFINITIONS = [
    {
        "name": "get_driver_standings",
        "description": (
            "Get the current 2025 Formula 1 driver championship standings. "
            "Returns position, points, wins, team, and nationality for each driver. "
            "Use this when the user asks who is leading the championship, how many "
            "points a driver has, or wants a general standings overview."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Number of drivers to return (1–20). Defaults to 20 for full standings.",
                }
            },
            "required": [],
        },
    },
    {
        "name": "get_constructor_standings",
        "description": (
            "Get the current 2025 Formula 1 constructor (team) championship standings. "
            "Returns position, team name, nationality, total points, and wins. "
            "Use this when the user asks about team standings, which team is winning, "
            "or how much a team leads by."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "get_driver_season_stats",
        "description": (
            "Get detailed 2025 season statistics for a specific driver: wins, podiums, "
            "fastest laps, championship position, points, and their last 5 race results. "
            "Use this when the user asks about a particular driver's performance, results, "
            "or season summary. Pass the driver's full name, surname, or 3-letter code "
            "(e.g. 'Verstappen', 'VER', 'norris')."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "driver_name": {
                    "type": "string",
                    "description": "Driver's full name, surname, or 3-letter code (case-insensitive).",
                }
            },
            "required": ["driver_name"],
        },
    },
    {
        "name": "get_race_results",
        "description": (
            "Get the full race classification for a specific 2025 Grand Prix. "
            "Returns finishing position, driver, team, points, fastest lap, and race status "
            "for every classified finisher. Use this when the user asks who won a race, "
            "what the results were for a specific round, or how a driver finished in a race."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "round_number": {
                    "type": "integer",
                    "description": "The round number in the 2025 season (1–24). Use get_season_schedule first if unsure of the round number.",
                }
            },
            "required": ["round_number"],
        },
    },
    {
        "name": "get_qualifying_results",
        "description": (
            "Get the qualifying session results (Q1, Q2, Q3 lap times) for a specific "
            "2025 Grand Prix round. Returns grid positions and times for all drivers. "
            "Use this when the user asks about pole position, qualifying pace, grid order, "
            "or time gaps in qualifying."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "round_number": {
                    "type": "integer",
                    "description": "The round number in the 2025 season (1–24). Use get_season_schedule first if unsure of the round number.",
                }
            },
            "required": ["round_number"],
        },
    },
    {
        "name": "get_season_schedule",
        "description": (
            "Get the complete 2025 Formula 1 season calendar: all 24 rounds with race names, "
            "circuit locations, countries, and dates. Use this when the user asks about "
            "upcoming races, which round a specific Grand Prix is, the season calendar, "
            "or before looking up race/qualifying results by round number."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "get_head_to_head",
        "description": (
            "Compare two drivers directly across all 2025 races they both competed in. "
            "Returns points totals, points gap, wins each, and a head-to-head race count "
            "(how many times each driver finished ahead of the other). "
            "Use this when the user wants to compare two drivers, asks who is faster, "
            "or wants to see a rivalry breakdown."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "driver_a": {
                    "type": "string",
                    "description": "First driver's full name, surname, or 3-letter code.",
                },
                "driver_b": {
                    "type": "string",
                    "description": "Second driver's full name, surname, or 3-letter code.",
                },
            },
            "required": ["driver_a", "driver_b"],
        },
    },
]


def execute_tool(name: str, args: dict):
    """
    Dispatch a tool call by name and return the result.

    Raises ValueError for unknown tool names or driver-not-found errors.
    All other exceptions from data functions propagate naturally so the
    agentic loop can catch them and set is_error=True in the tool_result.
    """
    if name == "get_driver_standings":
        limit = args.get("limit", 20)
        return get_drivers()[:limit]

    if name == "get_constructor_standings":
        return get_constructor_standings()

    if name == "get_driver_season_stats":
        stats = get_driver_stats(args["driver_name"])
        if stats is None:
            raise ValueError(f"Driver not found: {args['driver_name']!r}. "
                             "Try the driver's surname or 3-letter code.")
        return stats

    if name == "get_race_results":
        return get_race_results(args["round_number"])

    if name == "get_qualifying_results":
        return get_qualifying_results(args["round_number"])

    if name == "get_season_schedule":
        return get_circuits()

    if name == "get_head_to_head":
        return get_head_to_head(args["driver_a"], args["driver_b"])

    raise ValueError(f"Unknown tool: {name!r}")
```

- [ ] **Step 4: Run the tools tests**

```bash
cd server && python -m pytest tests/test_tools.py -v
```

Expected: All 11 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add server/tools.py server/tests/test_tools.py
git commit -m "feat: tool definitions and dispatcher — 7 F1 data tools for agentic loop"
```

---

## Task 3: Rewrite chat.py with the Agentic Loop

**Files:**
- Modify: `server/chat.py`
- Modify: `server/tests/test_chat.py`

This is the core change. `answer_f1_question` no longer takes `f1_context` — it starts the agentic loop, handles tool calls, and returns Claude's final text answer.

- [ ] **Step 1: Write the new chat tests**

Replace `server/tests/test_chat.py` entirely:

```python
# server/tests/test_chat.py
import json
import pytest
from unittest.mock import patch, MagicMock, call
import importlib


# ─── Helpers ────────────────────────────────────────────────

def _tool_use_response(tool_name="get_driver_standings", tool_id="toolu_01", tool_input=None):
    """Simulate Claude responding with a tool call."""
    block = MagicMock()
    block.type = "tool_use"
    block.id = tool_id
    block.name = tool_name
    block.input = tool_input or {}

    resp = MagicMock()
    resp.stop_reason = "tool_use"
    resp.content = [block]
    return resp


def _end_turn_response(text="Verstappen leads the championship."):
    """Simulate Claude responding with a final text answer."""
    block = MagicMock()
    block.type = "text"
    block.text = text

    resp = MagicMock()
    resp.stop_reason = "end_turn"
    resp.content = [block]
    return resp


def _two_tool_use_response():
    """Simulate Claude calling two tools in parallel in a single response."""
    block_a = MagicMock()
    block_a.type = "tool_use"
    block_a.id = "toolu_01"
    block_a.name = "get_driver_standings"
    block_a.input = {}

    block_b = MagicMock()
    block_b.type = "tool_use"
    block_b.id = "toolu_02"
    block_b.name = "get_constructor_standings"
    block_b.input = {}

    resp = MagicMock()
    resp.stop_reason = "tool_use"
    resp.content = [block_a, block_b]
    return resp


# ─── Tests ──────────────────────────────────────────────────

def test_answer_f1_question_direct_answer():
    """Claude answers without calling any tools."""
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _end_turn_response("F1 started in 1950.")

    with patch('chat.anthropic.Anthropic', return_value=mock_client):
        import chat
        importlib.reload(chat)
        result = chat.answer_f1_question("When did F1 start?")

    assert result == "F1 started in 1950."
    assert mock_client.messages.create.call_count == 1


def test_answer_f1_question_single_tool_call():
    """Claude calls one tool then produces the final answer."""
    mock_client = MagicMock()
    mock_client.messages.create.side_effect = [
        _tool_use_response("get_driver_standings"),
        _end_turn_response("Verstappen leads with 150 points."),
    ]

    with patch('chat.anthropic.Anthropic', return_value=mock_client), \
         patch('chat.execute_tool', return_value=[{"standing": 1, "full_name": "Max Verstappen"}]):
        import chat
        importlib.reload(chat)
        result = chat.answer_f1_question("Who leads the championship?")

    assert result == "Verstappen leads with 150 points."
    assert mock_client.messages.create.call_count == 2


def test_answer_f1_question_parallel_tool_calls():
    """Claude calls two tools in one round; both results are sent back together."""
    mock_client = MagicMock()
    mock_client.messages.create.side_effect = [
        _two_tool_use_response(),
        _end_turn_response("Verstappen leads drivers, Red Bull leads constructors."),
    ]

    execute_tool_results = {
        "get_driver_standings": [{"standing": 1, "full_name": "Max Verstappen"}],
        "get_constructor_standings": [{"position": 1, "team": "Red Bull Racing"}],
    }

    with patch('chat.anthropic.Anthropic', return_value=mock_client), \
         patch('chat.execute_tool', side_effect=lambda n, a: execute_tool_results[n]):
        import chat
        importlib.reload(chat)
        result = chat.answer_f1_question("Who leads drivers and constructors?")

    assert "Verstappen" in result
    # Both tool results must be sent in the SAME user message
    second_call_messages = mock_client.messages.create.call_args_list[1][1]["messages"]
    last_user_content = second_call_messages[-1]["content"]
    assert len(last_user_content) == 2  # two tool_result blocks
    assert last_user_content[0]["tool_use_id"] == "toolu_01"
    assert last_user_content[1]["tool_use_id"] == "toolu_02"


def test_answer_f1_question_tool_error_uses_is_error_flag():
    """When a tool raises, the loop sends is_error=True and continues."""
    mock_client = MagicMock()
    mock_client.messages.create.side_effect = [
        _tool_use_response("get_driver_season_stats", tool_input={"driver_name": "nobody"}),
        _end_turn_response("I couldn't find that driver."),
    ]

    with patch('chat.anthropic.Anthropic', return_value=mock_client), \
         patch('chat.execute_tool', side_effect=ValueError("Driver not found: 'nobody'")):
        import chat
        importlib.reload(chat)
        result = chat.answer_f1_question("Tell me about nobody")

    assert mock_client.messages.create.call_count == 2
    # Verify the tool_result sent back to Claude has is_error=True
    second_call_messages = mock_client.messages.create.call_args_list[1][1]["messages"]
    tool_result_block = second_call_messages[-1]["content"][0]
    assert tool_result_block["is_error"] is True


def test_answer_f1_question_exceeds_max_rounds():
    """Raises ValueError after MAX_TOOL_ROUNDS tool calls with no final answer."""
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _tool_use_response()

    with patch('chat.anthropic.Anthropic', return_value=mock_client), \
         patch('chat.execute_tool', return_value=[]):
        import chat
        importlib.reload(chat)
        with pytest.raises(ValueError, match="Exceeded"):
            chat.answer_f1_question("A question Claude never stops trying to answer")

    assert mock_client.messages.create.call_count == chat.MAX_TOOL_ROUNDS


def test_answer_f1_question_passes_system_prompt():
    """The system prompt is passed on every API call."""
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _end_turn_response("Answer.")

    with patch('chat.anthropic.Anthropic', return_value=mock_client):
        import chat
        importlib.reload(chat)
        chat.answer_f1_question("Any question")

    call_kwargs = mock_client.messages.create.call_args[1]
    assert "system" in call_kwargs
    assert len(call_kwargs["system"]) > 50  # not empty


def test_answer_f1_question_passes_tool_definitions():
    """TOOL_DEFINITIONS are passed to every API call."""
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _end_turn_response("Answer.")

    with patch('chat.anthropic.Anthropic', return_value=mock_client):
        import chat
        importlib.reload(chat)
        chat.answer_f1_question("Any question")

    call_kwargs = mock_client.messages.create.call_args[1]
    assert "tools" in call_kwargs
    assert len(call_kwargs["tools"]) == 7
```

- [ ] **Step 2: Run to verify all new tests fail**

```bash
cd server && python -m pytest tests/test_chat.py -v
```

Expected: Multiple FAILUREs — the current `answer_f1_question` still takes `f1_context`.

- [ ] **Step 3: Replace `server/chat.py` entirely**

```python
# server/chat.py
"""
Agentic chat loop using Anthropic tool use.

Claude calls tools to fetch F1 data dynamically, rather than receiving a
pre-built context string. The loop continues until Claude produces a final
text answer or the MAX_TOOL_ROUNDS safety limit is hit.
"""
import json
import os
import anthropic
from tools import TOOL_DEFINITIONS, execute_tool

_client: anthropic.Anthropic | None = None

MAX_TOOL_ROUNDS = 5

SYSTEM_PROMPT = """You are an expert Formula 1 analyst with access to real-time 2025 season data through tools.

Your job is to answer questions about the 2025 F1 season accurately, using the tools provided to fetch up-to-date data. Do not rely on your training knowledge for current standings, results, or points — always fetch the relevant data first.

Guidelines:
- For championship standings questions: use get_driver_standings or get_constructor_standings
- For questions about a specific driver: use get_driver_season_stats
- For comparing two drivers: use get_head_to_head (it's more efficient than two separate stats calls)
- For questions about a specific race result or winner: use get_race_results with the round number
- For qualifying or pole position questions: use get_qualifying_results
- For calendar or schedule questions: use get_season_schedule
- If you need the round number for a race but don't know it, call get_season_schedule first
- You may call multiple tools — use as many as needed to give a complete answer
- Be concise and specific. Lead with the key fact, then support with numbers from the data."""


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise EnvironmentError(
                "ANTHROPIC_API_KEY environment variable is not set. "
                "Add it to your .env file."
            )
        _client = anthropic.Anthropic(api_key=api_key)
    return _client


def answer_f1_question(message: str) -> str:
    """
    Answer an F1 question using Claude with dynamic tool calls.

    Runs an agentic loop: Claude decides which tools to call, the backend
    executes them, results are fed back, and the process repeats until Claude
    produces a final text answer.

    Raises ValueError if no answer is produced within MAX_TOOL_ROUNDS rounds.
    """
    client = _get_client()
    messages = [{"role": "user", "content": message}]

    for _ in range(MAX_TOOL_ROUNDS):
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            tools=TOOL_DEFINITIONS,
            messages=messages,
        )

        if response.stop_reason == "end_turn":
            for block in response.content:
                if hasattr(block, "text"):
                    return block.text
            raise ValueError("Claude returned end_turn but no text content block")

        if response.stop_reason == "tool_use":
            # Execute all tool calls from this response (may be parallel)
            tool_results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                try:
                    result = execute_tool(block.name, block.input)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(result, default=str),
                    })
                except Exception as exc:
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": str(exc),
                        "is_error": True,
                    })

            # Add the assistant's response and all tool results to message history
            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": tool_results})

        else:
            raise ValueError(f"Unexpected stop_reason from Claude: {response.stop_reason!r}")

    raise ValueError(
        f"Exceeded {MAX_TOOL_ROUNDS} tool-call rounds without a final answer. "
        "The question may require more context than the tools can provide."
    )
```

- [ ] **Step 4: Run the new chat tests**

```bash
cd server && python -m pytest tests/test_chat.py -v
```

Expected: All 7 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add server/chat.py server/tests/test_chat.py
git commit -m "feat: agentic chat loop — Claude calls F1 tools dynamically, 5-round safety limit"
```

---

## Task 4: Wire Up main.py and Update test_main.py

**Files:**
- Modify: `server/main.py`
- Modify: `server/tests/test_main.py`

`main.py` currently calls `get_f1_context(message)` before `answer_f1_question`. Both need to go. The chat endpoint becomes a one-liner.

- [ ] **Step 1: Write the updated test_main.py**

Replace `server/tests/test_main.py` entirely:

```python
# server/tests/test_main.py
import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def test_health_check():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_cors_header_present():
    response = client.options(
        "/api/drivers",
        headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"},
    )
    assert response.headers.get("access-control-allow-origin") == "http://localhost:5173"


def test_chat_endpoint_returns_response():
    # answer_f1_question now takes only message — no f1_context
    with patch('main.answer_f1_question', return_value="Verstappen leads."):
        response = client.post("/api/chat", json={"message": "Who is leading?"})

    assert response.status_code == 200
    assert response.json() == {"response": "Verstappen leads."}


def test_chat_endpoint_rejects_empty_message():
    response = client.post("/api/chat", json={"message": "   "})
    assert response.status_code == 400
```

- [ ] **Step 2: Run to verify the chat test fails (wrong signature)**

```bash
cd server && python -m pytest tests/test_main.py::test_chat_endpoint_returns_response -v
```

Expected: FAIL — `main.py` still imports and calls `get_f1_context`.

- [ ] **Step 3: Update `server/main.py`**

Replace `server/main.py` entirely:

```python
# server/main.py
import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '..', '.env'))

from f1_data import get_drivers, get_driver_stats, get_circuits
from chat import answer_f1_question

app = FastAPI(title="F1 Dashboard API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:4173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    message: str


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/api/drivers")
async def drivers_endpoint():
    try:
        return get_drivers()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/driver/{name}/stats")
async def driver_stats_endpoint(name: str):
    try:
        stats = get_driver_stats(name)
        if stats is None:
            raise HTTPException(status_code=404, detail=f"Driver '{name}' not found")
        return stats
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/circuits")
async def circuits_endpoint():
    try:
        return get_circuits()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/chat")
async def chat_endpoint(request: ChatRequest):
    if not request.message.strip():
        raise HTTPException(status_code=400, detail="message cannot be empty")
    try:
        response = answer_f1_question(request.message)
        return {"response": response}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
```

- [ ] **Step 4: Run all server tests**

```bash
cd server && python -m pytest tests/ -v
```

Expected: All tests PASS. Count should be higher than before (new tools tests + new f1_data tests).

- [ ] **Step 5: Commit**

```bash
git add server/main.py server/tests/test_main.py
git commit -m "feat: wire up agentic chat — remove get_f1_context, direct answer_f1_question call"
```

---

## Self-Review

### Spec Coverage

| Requirement | Task |
|---|---|
| Replace static context with tool-use loop | Task 3 |
| Claude decides which tools to call | Task 3 (agentic loop) |
| Parallel tool calls handled correctly | Task 3 (all tool_use blocks in one round) |
| Tool errors use `is_error=True` (not crashes) | Task 3 |
| Safety limit (max 5 rounds) | Task 3 (`MAX_TOOL_ROUNDS`) |
| `get_driver_standings` tool | Task 2 |
| `get_constructor_standings` tool | Tasks 1 + 2 |
| `get_driver_season_stats` tool | Task 2 |
| `get_race_results` tool | Tasks 1 + 2 |
| `get_qualifying_results` tool | Tasks 1 + 2 |
| `get_season_schedule` tool | Task 2 |
| `get_head_to_head` tool | Tasks 1 + 2 |
| `_fetch_all_races` shared helper | Task 1 |
| `get_f1_context` deleted | Task 1 |
| All existing REST endpoints unchanged | Task 4 |
| All tests updated to new signatures | Tasks 1, 3, 4 |

### Placeholder Scan

No TBDs or "similar to task N" references. All code blocks are complete.

### Type Consistency

- `execute_tool(name: str, args: dict)` defined in `tools.py` Task 2, called in `chat.py` Task 3 — consistent.
- `answer_f1_question(message: str) -> str` defined in `chat.py` Task 3, called in `main.py` Task 4 — consistent (no `f1_context` parameter anywhere).
- `get_head_to_head(driver_a_name: str, driver_b_name: str)` defined in `f1_data.py` Task 1, imported in `tools.py` Task 2 as `get_head_to_head` — consistent.
- `_fetch_all_races(driver_id: str)` defined in Task 1 and used internally by `get_driver_stats` and `get_head_to_head` — consistent.
