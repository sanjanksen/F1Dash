# F1 Context Tools — Telemetry Comparison, Circuit Corners, Historical Performance

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add three tools that let Claude reason about *where* and *why* pace differences happen: a side-by-side telemetry overlay, a corner map to anchor distances to named corners, and multi-year circuit history to give car/team context.

**Architecture:** Two tasks. Task 1 adds three new functions to `f1_data.py` with full tests. Task 2 registers them in `tools.py` (growing the tool count from 11 to 14) and updates the existing tool-count test.

**Tech Stack:** FastF1 3.x (`get_circuit_info`, telemetry), Jolpica multi-year REST queries, pandas, pytest MagicMock.

---

## File Structure

```
server/
├── f1_data.py          # Modify: add get_telemetry_comparison, get_circuit_corners,
│                       #         get_historical_circuit_performance
├── tools.py            # Modify: add 3 TOOL_DEFINITIONS + 3 execute_tool branches
└── tests/
    ├── test_f1_data.py # Modify: append 4 new tests
    └── test_tools.py   # Modify: append 3 new dispatcher tests, update count assertion
```

**New functions in `f1_data.py`:**
- `get_telemetry_comparison(round_number, session_type, driver_a, driver_b, lap_number_a=None, lap_number_b=None)` — overlay both drivers' traces aligned by distance; returns `delta_speed` and `delta_throttle` at every 100m point
- `get_circuit_corners(round_number)` — corner number + distance for every corner via `fastf1.get_circuit_info`; used to map telemetry distances to named corners
- `get_historical_circuit_performance(round_number, years=[2023, 2024, 2025])` — qualifying top-5 and race top-5 for the same circuit across multiple seasons via Jolpica

---

## Task 1: Add Three New Data Functions

**Files:**
- Modify: `server/f1_data.py`
- Modify: `server/tests/test_f1_data.py`

- [ ] **Step 1: Append tests to `server/tests/test_f1_data.py`**

Append this entire block at the end of the file:

```python
# ─── Telemetry comparison + circuit context tests ───────────


def _make_tel_df(n_points=6, circuit_length_m=500,
                 base_speed=150.0, speed_boost=0.0):
    distances = [i * circuit_length_m / (n_points - 1) for i in range(n_points)]
    return pd.DataFrame({
        'Distance': distances,
        'Speed': [base_speed + speed_boost + i * 10 for i in range(n_points)],
        'Throttle': [50.0 + i * 5 for i in range(n_points)],
        'Brake': [i == 0 for i in range(n_points)],
        'nGear': [4 + min(i, 4) for i in range(n_points)],
        'DRS': [12 if i > 3 else 0 for i in range(n_points)],
    })


def test_get_telemetry_comparison():
    nor_lap_series = _make_mock_fastest_lap("NOR")
    lec_lap_series = _make_mock_fastest_lap("LEC", "Ferrari")

    tel_nor = _make_tel_df(base_speed=150.0, speed_boost=5.0)   # NOR 5 kph faster overall
    tel_lec = _make_tel_df(base_speed=150.0, speed_boost=0.0)

    mock_lap_nor = MagicMock()
    mock_lap_nor.__getitem__.side_effect = lambda k: nor_lap_series[k]
    mock_lap_nor.get.side_effect = lambda k, d=None: nor_lap_series.get(k, d)
    mock_lap_nor.get_telemetry.return_value.add_distance.return_value = tel_nor

    mock_lap_lec = MagicMock()
    mock_lap_lec.__getitem__.side_effect = lambda k: lec_lap_series[k]
    mock_lap_lec.get.side_effect = lambda k, d=None: lec_lap_series.get(k, d)
    mock_lap_lec.get_telemetry.return_value.add_distance.return_value = tel_lec

    def pick_driver_tel(code):
        mock_laps = MagicMock()
        mock_laps.empty = False
        mock_laps.pick_fastest.return_value = mock_lap_nor if code.upper() == "NOR" else mock_lap_lec
        return mock_laps

    mock_session = MagicMock()
    mock_session.event = {'EventName': 'Monaco Grand Prix'}
    mock_session.laps.pick_driver.side_effect = pick_driver_tel

    with patch('f1_data.fastf1.get_session', return_value=mock_session):
        import f1_data
        result = f1_data.get_telemetry_comparison(8, 'Q', 'NOR', 'LEC')

    assert result['driver_a'] == 'NOR'
    assert result['driver_b'] == 'LEC'
    assert result['circuit_length_m'] == 500
    assert len(result['comparison']) > 0
    # NOR has +5 kph speed boost → delta should be positive
    first = result['comparison'][0]
    assert first['delta_speed'] == pytest.approx(5.0, abs=0.5)
    assert 'brake_a' in first
    assert 'drs_a' in first
    assert 'gear_a' in first


def test_get_telemetry_comparison_driver_not_found():
    mock_session = MagicMock()
    mock_session.event = {'EventName': 'Monaco Grand Prix'}

    def pick_empty(code):
        m = MagicMock()
        m.empty = True
        return m

    mock_session.laps.pick_driver.side_effect = pick_empty

    with patch('f1_data.fastf1.get_session', return_value=mock_session):
        import f1_data
        with pytest.raises(ValueError, match="No data"):
            f1_data.get_telemetry_comparison(8, 'Q', 'NOR', 'ZZZ')


def test_get_circuit_corners():
    mock_corners_df = pd.DataFrame({
        'Number': [1, 2, 3],
        'Letter': ['', 'A', ''],
        'X': [100.0, 200.0, 300.0],
        'Y': [50.0, 60.0, 70.0],
        'Angle': [45.0, 90.0, 135.0],
        'Distance': [150.5, 800.2, 2200.7],
    })
    mock_circuit_info = MagicMock()
    mock_circuit_info.corners = mock_corners_df

    with patch('f1_data.fastf1.get_circuit_info', return_value=mock_circuit_info):
        import f1_data
        result = f1_data.get_circuit_corners(8)

    assert len(result) == 3
    assert result[0]['number'] == 1
    assert result[0]['distance_m'] == 151       # rounded from 150.5
    assert result[0]['label'] is None           # empty string → None
    assert result[1]['label'] == 'A'
    assert result[2]['number'] == 3
    assert result[2]['distance_m'] == 2201      # rounded from 2200.7


def test_get_historical_circuit_performance():
    # Call order:
    # 1. GET /{year}/{round}/results.json?limit=1  → get circuit_id
    # 2. For year 2024: GET /2024/circuits/monaco/qualifying.json
    # 3. For year 2024: GET /2024/circuits/monaco/results.json
    # 4. For year 2025: GET /2025/circuits/monaco/qualifying.json
    # 5. For year 2025: GET /2025/circuits/monaco/results.json

    def _circuit_lookup():
        m = MagicMock()
        m.raise_for_status.return_value = None
        m.json.return_value = {
            "MRData": {
                "RaceTable": {
                    "Races": [{
                        "raceName": "Monaco Grand Prix",
                        "Circuit": {
                            "circuitId": "monaco",
                            "circuitName": "Circuit de Monaco",
                        },
                        "Results": [],
                    }]
                }
            }
        }
        return m

    def _quali_resp():
        m = MagicMock()
        m.raise_for_status.return_value = None
        m.json.return_value = {
            "MRData": {
                "RaceTable": {
                    "Races": [{
                        "QualifyingResults": [
                            {
                                "position": "1",
                                "Driver": {"driverId": "norris", "givenName": "Lando",
                                           "familyName": "Norris", "code": "NOR"},
                                "Constructor": {"name": "McLaren"},
                                "Q1": "1:10.000", "Q2": "1:09.500", "Q3": "1:09.100",
                            },
                        ]
                    }]
                }
            }
        }
        return m

    def _race_resp():
        m = MagicMock()
        m.raise_for_status.return_value = None
        m.json.return_value = {
            "MRData": {
                "RaceTable": {
                    "Races": [{
                        "Results": [
                            {
                                "position": "1",
                                "Driver": {"driverId": "norris", "givenName": "Lando",
                                           "familyName": "Norris", "code": "NOR"},
                                "Constructor": {"name": "McLaren"},
                                "FastestLap": {"rank": "1"},
                            },
                        ]
                    }]
                }
            }
        }
        return m

    with patch('f1_data.requests.get', side_effect=[
        _circuit_lookup(),
        _quali_resp(), _race_resp(),   # 2024
        _quali_resp(), _race_resp(),   # 2025
    ]):
        import f1_data
        result = f1_data.get_historical_circuit_performance(8, years=[2024, 2025])

    assert result['circuit_id'] == 'monaco'
    assert result['circuit_name'] == 'Circuit de Monaco'
    assert len(result['history']) == 2
    assert result['history'][0]['year'] == 2024
    assert result['history'][0]['qualifying_top5'][0]['code'] == 'NOR'
    assert result['history'][0]['qualifying_top5'][0]['q3'] == '1:09.100'
    assert result['history'][0]['race_top5'][0]['fastest_lap'] is True
    assert result['history'][1]['year'] == 2025
```

- [ ] **Step 2: Run new tests to confirm they fail**

```bash
cd server && python -m pytest tests/test_f1_data.py -v -k "telemetry_comparison or circuit_corners or historical_circuit"
```

Expected: All 4 new tests FAIL with `AttributeError`.

- [ ] **Step 3: Add `get_telemetry_comparison` to `server/f1_data.py`**

Append to `server/f1_data.py`:

```python
def get_telemetry_comparison(round_number: int, session_type: str,
                              driver_a: str, driver_b: str,
                              lap_number_a: int | None = None,
                              lap_number_b: int | None = None) -> dict:
    """
    Overlay two drivers' telemetry traces aligned by distance.
    Returns delta_speed (positive = driver_a faster) and delta_throttle at every 100m.
    Use this to pinpoint exactly where and why one driver gains time over another.
    """
    session = fastf1.get_session(CURRENT_YEAR, round_number, session_type)
    session.load(laps=True, telemetry=True, weather=False, messages=False)

    def _get_lap(code: str, lap_num: int | None):
        laps = session.laps.pick_driver(code.upper())
        if laps.empty:
            raise ValueError(f"No data for driver {code!r}")
        if lap_num is not None:
            matching = laps[laps['LapNumber'] == lap_num]
            if matching.empty:
                raise ValueError(f"Lap {lap_num} not found for {code!r}")
            return matching.iloc[0]
        return laps.pick_fastest()

    lap_a = _get_lap(driver_a, lap_number_a)
    lap_b = _get_lap(driver_b, lap_number_b)

    tel_a = lap_a.get_telemetry().add_distance()
    tel_b = lap_b.get_telemetry().add_distance()

    total_dist = min(float(tel_a['Distance'].max()), float(tel_b['Distance'].max()))

    INTERVAL_M = 100
    samples = []
    dist = 0.0
    while dist <= total_dist:
        idx_a = (tel_a['Distance'] - dist).abs().idxmin()
        idx_b = (tel_b['Distance'] - dist).abs().idxmin()
        row_a = tel_a.loc[idx_a]
        row_b = tel_b.loc[idx_b]

        spd_a = round(float(row_a['Speed']), 1)
        spd_b = round(float(row_b['Speed']), 1)
        thr_a = round(float(row_a['Throttle']), 1)
        thr_b = round(float(row_b['Throttle']), 1)

        samples.append({
            "distance_m": int(dist),
            "speed_a": spd_a,
            "speed_b": spd_b,
            "delta_speed": round(spd_a - spd_b, 1),
            "throttle_a": thr_a,
            "throttle_b": thr_b,
            "delta_throttle": round(thr_a - thr_b, 1),
            "brake_a": bool(row_a['Brake']),
            "brake_b": bool(row_b['Brake']),
            "gear_a": int(row_a['nGear']) if pd.notna(row_a['nGear']) else None,
            "gear_b": int(row_b['nGear']) if pd.notna(row_b['nGear']) else None,
            "drs_a": int(row_a['DRS']) >= 10 if pd.notna(row_a['DRS']) else False,
            "drs_b": int(row_b['DRS']) >= 10 if pd.notna(row_b['DRS']) else False,
        })
        dist += INTERVAL_M

    return {
        "event": session.event['EventName'],
        "session": session_type.upper(),
        "driver_a": driver_a.upper(),
        "driver_b": driver_b.upper(),
        "lap_time_a": _fmt_td(lap_a['LapTime']),
        "lap_time_b": _fmt_td(lap_b['LapTime']),
        "lap_number_a": int(lap_a['LapNumber']),
        "lap_number_b": int(lap_b['LapNumber']),
        "circuit_length_m": int(total_dist),
        "comparison": samples,
    }
```

- [ ] **Step 4: Add `get_circuit_corners` to `server/f1_data.py`**

Append to `server/f1_data.py`:

```python
def get_circuit_corners(round_number: int) -> list[dict]:
    """
    Corner positions (distance along track in metres) for a circuit.
    Use alongside telemetry tools to map speed/brake differences to named corners.
    e.g. if telemetry shows a delta at 1400m and corner 6 is at 1380m, that's the corner.
    """
    circuit_info = fastf1.get_circuit_info(CURRENT_YEAR, round_number)
    corners = []
    for _, row in circuit_info.corners.iterrows():
        raw_label = str(row.get('Letter', '')).strip()
        corners.append({
            "number": int(row['Number']),
            "label": raw_label if raw_label else None,
            "distance_m": int(round(float(row['Distance']), 0)),
        })
    return corners
```

- [ ] **Step 5: Add `get_historical_circuit_performance` to `server/f1_data.py`**

Append to `server/f1_data.py`:

```python
def get_historical_circuit_performance(round_number: int,
                                        years: list[int] | None = None) -> dict:
    """
    Qualifying top-5 and race top-5 for the same circuit across multiple seasons.
    Reveals which teams/drivers historically perform well or poorly at this venue.
    Default years: [2023, 2024, 2025].
    """
    if years is None:
        years = [2023, 2024, 2025]

    # Get circuit_id from the current season's round
    resp = requests.get(
        f"{JOLPICA_BASE}/{CURRENT_YEAR}/{round_number}/results.json?limit=1",
        timeout=15,
    )
    resp.raise_for_status()
    races = resp.json()["MRData"]["RaceTable"]["Races"]
    if not races:
        raise ValueError(f"Round {round_number} not found in {CURRENT_YEAR}")

    circuit_id = races[0]["Circuit"]["circuitId"]
    circuit_name = races[0]["Circuit"]["circuitName"]
    race_name = races[0]["raceName"]

    history = []
    for year in years:
        year_data: dict = {"year": year}

        # Qualifying top-5
        try:
            r = requests.get(
                f"{JOLPICA_BASE}/{year}/circuits/{circuit_id}/qualifying.json?limit=5",
                timeout=15,
            )
            r.raise_for_status()
            quali_races = r.json()["MRData"]["RaceTable"]["Races"]
            if quali_races:
                year_data["qualifying_top5"] = [
                    {
                        "position": int(q["position"]),
                        "driver": f"{q['Driver']['givenName']} {q['Driver']['familyName']}",
                        "code": q["Driver"].get("code", ""),
                        "team": q["Constructor"]["name"],
                        "q3": q.get("Q3") or q.get("Q2") or q.get("Q1", ""),
                    }
                    for q in quali_races[0].get("QualifyingResults", [])
                ]
            else:
                year_data["qualifying_top5"] = None
        except Exception:
            year_data["qualifying_top5"] = None

        # Race top-5
        try:
            r = requests.get(
                f"{JOLPICA_BASE}/{year}/circuits/{circuit_id}/results.json?limit=5",
                timeout=15,
            )
            r.raise_for_status()
            race_races = r.json()["MRData"]["RaceTable"]["Races"]
            if race_races:
                year_data["race_top5"] = [
                    {
                        "position": int(res["position"]) if res["position"].isdigit() else None,
                        "driver": f"{res['Driver']['givenName']} {res['Driver']['familyName']}",
                        "code": res["Driver"].get("code", ""),
                        "team": res["Constructor"]["name"],
                        "fastest_lap": res.get("FastestLap", {}).get("rank") == "1",
                    }
                    for res in race_races[0].get("Results", [])
                ]
            else:
                year_data["race_top5"] = None
        except Exception:
            year_data["race_top5"] = None

        history.append(year_data)

    return {
        "circuit_id": circuit_id,
        "circuit_name": circuit_name,
        "race_name": race_name,
        "history": history,
    }
```

- [ ] **Step 6: Run the new tests**

```bash
cd server && python -m pytest tests/test_f1_data.py -v -k "telemetry_comparison or circuit_corners or historical_circuit"
```

Expected: All 4 new tests PASS.

- [ ] **Step 7: Run the full test suite**

```bash
cd server && python -m pytest tests/test_f1_data.py -v
```

Expected: All tests PASS (17 existing + 4 new = 21 total).

- [ ] **Step 8: Commit**

Run from `C:\Users\Student\Documents\Sanjan\F1Dash`:
```bash
git add server/f1_data.py server/tests/test_f1_data.py
git commit -m "feat: telemetry comparison, circuit corners, historical circuit performance"
```

---

## Task 2: Register the 3 New Tools

**Files:**
- Modify: `server/tools.py`
- Modify: `server/tests/test_tools.py`

- [ ] **Step 1: Append new tests to `server/tests/test_tools.py`**

Append this block at the end of the file:

```python
def test_execute_tool_get_telemetry_comparison():
    mock = {"driver_a": "NOR", "driver_b": "LEC", "comparison": [{"distance_m": 0, "delta_speed": 5.0}]}
    with patch('tools.get_telemetry_comparison', return_value=mock):
        result = tools.execute_tool("get_telemetry_comparison", {
            "round_number": 8, "session_type": "Q",
            "driver_a": "NOR", "driver_b": "LEC"
        })
    assert result["driver_a"] == "NOR"
    assert result["comparison"][0]["delta_speed"] == 5.0


def test_execute_tool_get_circuit_corners():
    mock = [{"number": 1, "label": None, "distance_m": 150}]
    with patch('tools.get_circuit_corners', return_value=mock):
        result = tools.execute_tool("get_circuit_corners", {"round_number": 8})
    assert result[0]["number"] == 1


def test_execute_tool_get_historical_circuit_performance():
    mock = {"circuit_id": "monaco", "history": [{"year": 2024}]}
    with patch('tools.get_historical_circuit_performance', return_value=mock):
        result = tools.execute_tool("get_historical_circuit_performance", {"round_number": 8})
    assert result["circuit_id"] == "monaco"
```

Also **update the count assertion test** — find `test_tool_definitions_count` and change `== 11` to `== 14`:

```python
def test_tool_definitions_count():
    """Should have 14 tools — 7 Jolpica + 4 FastF1 + 3 context tools."""
    assert len(tools.TOOL_DEFINITIONS) == 14
```

- [ ] **Step 2: Run to verify new tests fail**

```bash
cd server && python -m pytest tests/test_tools.py -v -k "telemetry_comparison or circuit_corners or historical_circuit or definitions_count"
```

Expected: 4 FAILUREs.

- [ ] **Step 3: Add imports and TOOL_DEFINITIONS entries to `server/tools.py`**

In `server/tools.py`, add the 3 new imports at the top:

```python
from f1_data import (
    get_drivers,
    get_constructor_standings,
    get_driver_stats,
    get_race_results,
    get_qualifying_results,
    get_circuits,
    get_head_to_head,
    get_session_fastest_laps,
    get_driver_lap_times,
    get_sector_comparison,
    get_lap_telemetry,
    get_telemetry_comparison,   # new
    get_circuit_corners,         # new
    get_historical_circuit_performance,  # new
)
```

Append these 3 entries to `TOOL_DEFINITIONS`:

```python
    {
        "name": "get_telemetry_comparison",
        "description": (
            "Overlay two drivers' telemetry traces for the same session, aligned by distance. "
            "Returns speed, throttle, brake, gear, and DRS for both drivers at every 100m point, "
            "plus delta_speed (positive = driver_a faster) and delta_throttle. "
            "Use this to explain exactly where one driver gains or loses time — e.g. earlier "
            "braking into a corner, higher minimum speed, stronger traction on exit. "
            "Combine with get_circuit_corners to name the corners where differences occur."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "round_number": {
                    "type": "integer",
                    "description": "The 2025 season round number.",
                },
                "session_type": {
                    "type": "string",
                    "description": "Session type: 'Q', 'R', 'FP1', 'FP2', 'FP3', 'S', 'SQ', 'SS'.",
                },
                "driver_a": {
                    "type": "string",
                    "description": "First driver's 3-letter code (e.g. 'NOR').",
                },
                "driver_b": {
                    "type": "string",
                    "description": "Second driver's 3-letter code (e.g. 'LEC').",
                },
                "lap_number_a": {
                    "type": "integer",
                    "description": "Specific lap number for driver_a. If omitted, uses their fastest lap.",
                },
                "lap_number_b": {
                    "type": "integer",
                    "description": "Specific lap number for driver_b. If omitted, uses their fastest lap.",
                },
            },
            "required": ["round_number", "session_type", "driver_a", "driver_b"],
        },
    },
    {
        "name": "get_circuit_corners",
        "description": (
            "Get the corner map for a circuit: each corner's number, optional letter label, "
            "and distance along the lap in metres. "
            "Use this alongside get_telemetry_comparison or get_lap_telemetry to translate "
            "distance-based observations into corner names. "
            "e.g. 'at 1400m, NOR braked much later' + corner 6 at 1380m = 'NOR braked later into Turn 6'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "round_number": {
                    "type": "integer",
                    "description": "The 2025 season round number.",
                },
            },
            "required": ["round_number"],
        },
    },
    {
        "name": "get_historical_circuit_performance",
        "description": (
            "Qualifying top-5 and race top-5 for the same circuit across the last 2–3 seasons. "
            "Use this to give team/car context: which constructors have historically been strong "
            "or weak at this venue. e.g. 'Red Bull has qualified P1 here two years running, "
            "Mercedes has struggled to make Q3.' "
            "Default covers 2023, 2024, 2025. Pass years=[2024, 2025] for a shorter window."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "round_number": {
                    "type": "integer",
                    "description": "The 2025 season round number. The circuit is looked up automatically.",
                },
                "years": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "List of years to fetch. Defaults to [2023, 2024, 2025].",
                },
            },
            "required": ["round_number"],
        },
    },
```

- [ ] **Step 4: Add 3 new `execute_tool` branches to `server/tools.py`**

Before the final `raise ValueError(f"Unknown tool: {name!r}")` line, add:

```python
    if name == "get_telemetry_comparison":
        return get_telemetry_comparison(
            args["round_number"], args["session_type"],
            args["driver_a"], args["driver_b"],
            args.get("lap_number_a"), args.get("lap_number_b"),
        )

    if name == "get_circuit_corners":
        return get_circuit_corners(args["round_number"])

    if name == "get_historical_circuit_performance":
        return get_historical_circuit_performance(
            args["round_number"], args.get("years")
        )
```

- [ ] **Step 5: Run all tools tests**

```bash
cd server && python -m pytest tests/test_tools.py -v
```

Expected: All 19 tests PASS (16 existing + 3 new).

- [ ] **Step 6: Run the full server test suite**

```bash
cd server && python -m pytest tests/ -v
```

Expected: All tests PASS (44 existing + 7 new = 51 total).

- [ ] **Step 7: Commit**

Run from `C:\Users\Student\Documents\Sanjan\F1Dash`:
```bash
git add server/tools.py server/tests/test_tools.py
git commit -m "feat: register 3 context tools — telemetry comparison, circuit corners, historical performance"
```

---

## Self-Review

### Spec Coverage

| Requirement | Task |
|---|---|
| Speed trace comparison (delta per 100m) | Task 1 `get_telemetry_comparison` |
| Brake/throttle/DRS in comparison | Task 1 (all fields in each sample) |
| Corner names to anchor distance observations | Task 1 `get_circuit_corners` |
| Historical team/car context per circuit | Task 1 `get_historical_circuit_performance` |
| All 3 tools registered in tool dispatcher | Task 2 |
| Tool count updated to 14 | Task 2 |

### No Placeholders

All steps contain complete code. No TBD.

### Type Consistency

- `get_telemetry_comparison` → returns `dict` with `comparison: list[dict]`
- `get_circuit_corners` → returns `list[dict]`
- `get_historical_circuit_performance` → returns `dict` with `history: list[dict]`
- `execute_tool` branches match the function signatures exactly
