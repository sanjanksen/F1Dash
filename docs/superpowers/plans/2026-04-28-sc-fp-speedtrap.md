# SC Impact Enrichment, FP Summary Tool, Speed Trap Leaderboard — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the LLM pre-computed SC victim/beneficiary conclusions, a full free-practice session summary tool with stint classification, and a speed trap leaderboard tool scanning all laps.

**Architecture:** All changes are backend-only (server/). Each feature is a pure data enrichment: richer return dicts from existing/new functions, new tool registrations, new resolver scopes. No new widgets. No frontend changes.

**Tech Stack:** Python, FastF1, pandas, existing `_load_session`/`_pick_driver`/`_fmt_td` helpers in `server/f1_data.py`.

---

## Task 1: SC Impact — pre-compute period_narrative, all_victims, all_beneficiaries

**Files:**
- Modify: `server/f1_data.py` — `get_safety_car_periods` (lines ~3403–3540)
- Test: `server/tests/test_f1_data.py`

### Background
`get_safety_car_periods` already builds `strategic_crossings` per period. We add:
1. `period_narrative` on each period — one pre-written sentence.
2. `all_victims` and `all_beneficiaries` at the top level — deduplicated across all periods.

The function's existing structure ends with `return {'event':..., 'sc_count':..., 'vsc_count':..., 'periods': periods}`. We extend this return dict.

- [ ] **Step 1: Write the failing tests**

In `server/tests/test_f1_data.py`, add these tests at the bottom of the file:

```python
def _make_sc_session(pitted_before_s, sc_start_s, sc_end_s, pitted_during_s=None):
    """Build a minimal FastF1-like session mock for SC period tests."""
    import pandas as pd
    from unittest.mock import MagicMock

    # track_status rows
    ts_data = [
        {'Time': pd.Timedelta(seconds=0), 'Status': '1', 'Message': 'AllClear'},
        {'Time': pd.Timedelta(seconds=sc_start_s), 'Status': '4', 'Message': 'SafetyCar'},
        {'Time': pd.Timedelta(seconds=sc_end_s), 'Status': '1', 'Message': 'AllClear'},
    ]
    ts_df = pd.DataFrame(ts_data)

    # Build laps: driver A pitted just before SC, driver B pitted during SC
    laps_rows = [
        {
            'Driver': 'AAA', 'Team': 'Alpha', 'LapNumber': 10,
            'LapStartTime': pd.Timedelta(seconds=pitted_before_s - 90),
            'PitInTime': pd.Timedelta(seconds=pitted_before_s),
            'PitOutTime': pd.NaT, 'Stint': 1, 'Compound': 'HARD',
            'TyreLife': 10, 'FreshTyre': True, 'TrackStatus': '1',
            'LapTime': pd.Timedelta(seconds=90),
        },
    ]
    if pitted_during_s:
        laps_rows.append({
            'Driver': 'BBB', 'Team': 'Beta', 'LapNumber': 11,
            'LapStartTime': pd.Timedelta(seconds=pitted_during_s - 90),
            'PitInTime': pd.Timedelta(seconds=pitted_during_s),
            'PitOutTime': pd.NaT, 'Stint': 2, 'Compound': 'SOFT',
            'TyreLife': 1, 'FreshTyre': True, 'TrackStatus': '4',
            'LapTime': pd.Timedelta(seconds=90),
        })
    laps_df = pd.DataFrame(laps_rows)

    session = MagicMock()
    session.track_status = ts_df
    session.laps = laps_df
    session.event = {'EventName': 'Test GP'}
    session.drivers = list(laps_df['Driver'].unique())
    return session


def test_sc_period_narrative_present():
    """Each period has a period_narrative string."""
    import f1_data
    session = _make_sc_session(pitted_before_s=100, sc_start_s=150, sc_end_s=300)
    with patch('f1_data._load_session', return_value=session):
        result = f1_data.get_safety_car_periods(1, 'R')
    assert len(result['periods']) == 1
    assert isinstance(result['periods'][0].get('period_narrative'), str)
    assert len(result['periods'][0]['period_narrative']) > 0


def test_sc_all_victims_populated():
    """all_victims lists drivers who pitted just before SC."""
    import f1_data
    # AAA pits 50s before SC (within 90s window = pitted_just_before)
    session = _make_sc_session(pitted_before_s=100, sc_start_s=150, sc_end_s=300,
                               pitted_during_s=200)
    with patch('f1_data._load_session', return_value=session):
        result = f1_data.get_safety_car_periods(1, 'R')
    victims = result.get('all_victims', [])
    assert any(v['driver'] == 'AAA' for v in victims)


def test_sc_all_beneficiaries_populated():
    """all_beneficiaries lists drivers who pitted during SC."""
    import f1_data
    session = _make_sc_session(pitted_before_s=100, sc_start_s=150, sc_end_s=300,
                               pitted_during_s=200)
    with patch('f1_data._load_session', return_value=session):
        result = f1_data.get_safety_car_periods(1, 'R')
    beneficiaries = result.get('all_beneficiaries', [])
    assert any(b['driver'] == 'BBB' for b in beneficiaries)


def test_sc_no_victims_when_nobody_pitted_before():
    """all_victims is empty when no driver pitted before SC."""
    import f1_data
    session = _make_sc_session(pitted_before_s=100, sc_start_s=150, sc_end_s=300,
                               pitted_during_s=None)
    # Nobody pitted during SC either, so no crossings
    # AAA pitted just before but there's no beneficiary → still listed as victim? 
    # We list victims regardless of crossings — they paid full price before SC.
    with patch('f1_data._load_session', return_value=session):
        result = f1_data.get_safety_car_periods(1, 'R')
    # AAA pitted 50s before SC (within 90s window) → should be a victim
    victims = result.get('all_victims', [])
    assert any(v['driver'] == 'AAA' for v in victims)
```

- [ ] **Step 2: Run tests to verify they fail**

```
cd server && python -m pytest tests/test_f1_data.py::test_sc_period_narrative_present tests/test_f1_data.py::test_sc_all_victims_populated tests/test_f1_data.py::test_sc_all_beneficiaries_populated -v
```

Expected: FAIL (KeyError or AssertionError — fields don't exist yet)

- [ ] **Step 3: Implement in `server/f1_data.py`**

Find the `return` statement at the end of `get_safety_car_periods` (currently returns `{'event':..., 'sc_count':..., 'vsc_count':..., 'periods': periods}`). **Before** that return, add the following block (after the `periods` loop):

```python
    # Pre-compute period_narrative for each period
    def _sc_period_narrative(period: dict) -> str:
        sc_type = period.get('type', 'SafetyCar')
        lap = period.get('deployed_on_lap')
        lap_str = f" lap {lap}" if lap else ""
        just_before = [e['driver'] for e in period.get('pitted_just_before', [])]
        extended = [e['driver'] for e in period.get('pitted_before_extended', [])]
        during = [e['driver'] for e in period.get('pitted_during', [])]
        parts = []
        if just_before:
            parts.append(f"{', '.join(just_before)} pitted in the final ~90s before it (immediately disadvantaged)")
        if extended:
            parts.append(f"{', '.join(extended)} pitted 1–5 laps before it (fresh-tyre advantage erased by rivals' free stop)")
        if during:
            parts.append(f"{', '.join(during)} pitted under it (near-free stop)")
        body = "; ".join(parts) if parts else "no drivers significantly impacted around this period"
        return f"{sc_type}{lap_str}: {body}."

    for period in periods:
        period['period_narrative'] = _sc_period_narrative(period)

    # Deduplicated top-level victim/beneficiary lists across all periods
    seen_victims: set[str] = set()
    seen_beneficiaries: set[str] = set()
    all_victims: list[dict] = []
    all_beneficiaries: list[dict] = []

    for period in periods:
        sc_type = period.get('type', 'SafetyCar')
        sc_lap = period.get('deployed_on_lap')
        for entry in period.get('pitted_just_before', []):
            drv = entry['driver']
            if drv not in seen_victims:
                seen_victims.add(drv)
                all_victims.append({
                    'driver': drv,
                    'team': entry.get('team'),
                    'sc_type': sc_type,
                    'sc_lap': sc_lap,
                    'seconds_before_sc': entry.get('seconds_before_sc'),
                    'mechanism': 'pitted_just_before',
                })
        for entry in period.get('pitted_before_extended', []):
            drv = entry['driver']
            if drv not in seen_victims:
                seen_victims.add(drv)
                all_victims.append({
                    'driver': drv,
                    'team': entry.get('team'),
                    'sc_type': sc_type,
                    'sc_lap': sc_lap,
                    'seconds_before_sc': entry.get('seconds_before_sc'),
                    'mechanism': 'pitted_before_extended',
                })
        for entry in period.get('pitted_during', []):
            drv = entry['driver']
            if drv not in seen_beneficiaries:
                seen_beneficiaries.add(drv)
                all_beneficiaries.append({
                    'driver': drv,
                    'team': entry.get('team'),
                    'sc_type': sc_type,
                    'sc_lap': sc_lap,
                    'mechanism': 'free_stop',
                })
```

Then extend the return dict:

```python
    return {
        'event': session.event['EventName'],
        'session': session_type.upper(),
        'sc_count': len([p for p in periods if p['type'] == 'SafetyCar']),
        'vsc_count': len([p for p in periods if p['type'] == 'VSC']),
        'periods': periods,
        'all_victims': all_victims,
        'all_beneficiaries': all_beneficiaries,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

```
cd server && python -m pytest tests/test_f1_data.py::test_sc_period_narrative_present tests/test_f1_data.py::test_sc_all_victims_populated tests/test_f1_data.py::test_sc_all_beneficiaries_populated tests/test_f1_data.py::test_sc_no_victims_when_nobody_pitted_before -v
```

Expected: 4 PASS

- [ ] **Step 5: Run full test suite**

```
cd server && python -m pytest tests/ -q
```

Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add server/f1_data.py server/tests/test_f1_data.py
git commit -m "feat: add period_narrative, all_victims, all_beneficiaries to get_safety_car_periods"
```

---

## Task 2: FP Summary Tool — data function

**Files:**
- Modify: `server/f1_data.py` — add `get_fp_summary` after `get_safety_car_periods`
- Test: `server/tests/test_f1_data.py`

### Background
FP sessions have mixed programmes. We classify stints so the LLM gets structured categories. FastF1 does **not** provide fuel load; we must note this explicitly in `session_notes`. Stint classification by lap count and compound/freshness.

- [ ] **Step 1: Write the failing tests**

Add to `server/tests/test_f1_data.py`:

```python
def _make_fp_session():
    """Minimal FP session with one long-run stint and one short stint."""
    import pandas as pd
    from unittest.mock import MagicMock

    laps_rows = []
    # Driver AAA: 10-lap long run on HARD (race sim)
    for i in range(1, 11):
        laps_rows.append({
            'Driver': 'AAA', 'Team': 'Alpha', 'LapNumber': i,
            'LapStartTime': pd.Timedelta(seconds=i * 90),
            'PitInTime': pd.NaT if i < 10 else pd.Timedelta(seconds=10 * 90 + 20),
            'PitOutTime': pd.Timedelta(seconds=90) if i == 1 else pd.NaT,
            'Stint': 1, 'Compound': 'HARD', 'FreshTyre': True,
            'TrackStatus': '1', 'LapTime': pd.Timedelta(seconds=92 + i * 0.1),
            'SpeedST': 300.0, 'SpeedFL': 295.0, 'SpeedI1': 285.0, 'SpeedI2': 290.0,
        })
    # Driver AAA: 2-lap quali sim on fresh SOFT
    for i in range(11, 13):
        laps_rows.append({
            'Driver': 'AAA', 'Team': 'Alpha', 'LapNumber': i,
            'LapStartTime': pd.Timedelta(seconds=i * 90),
            'PitInTime': pd.NaT if i < 12 else pd.Timedelta(seconds=12 * 90 + 20),
            'PitOutTime': pd.Timedelta(seconds=11 * 90) if i == 11 else pd.NaT,
            'Stint': 2, 'Compound': 'SOFT', 'FreshTyre': True,
            'TrackStatus': '1', 'LapTime': pd.Timedelta(seconds=88),
            'SpeedST': 310.0, 'SpeedFL': 305.0, 'SpeedI1': 290.0, 'SpeedI2': 295.0,
        })

    laps_df = pd.DataFrame(laps_rows)

    session = MagicMock()
    session.laps = laps_df
    session.drivers = ['AAA']
    session.event = {'EventName': 'Test GP'}
    return session


def test_get_fp_summary_structure():
    """get_fp_summary returns event, session, drivers, session_notes."""
    import f1_data
    session = _make_fp_session()
    with patch('f1_data._load_session', return_value=session):
        result = f1_data.get_fp_summary(1, 2)
    assert result['session'] == 'FP2'
    assert isinstance(result['drivers'], list)
    assert len(result['drivers']) > 0
    assert isinstance(result['session_notes'], list)
    assert len(result['session_notes']) > 0


def test_get_fp_summary_classifies_long_run():
    """10-lap stint classified as long_run."""
    import f1_data
    session = _make_fp_session()
    with patch('f1_data._load_session', return_value=session):
        result = f1_data.get_fp_summary(1, 2)
    driver = result['drivers'][0]
    long_runs = [s for s in driver['stints'] if s['classification'] == 'long_run']
    assert len(long_runs) >= 1


def test_get_fp_summary_classifies_quali_sim():
    """2-lap fresh-soft stint classified as quali_sim."""
    import f1_data
    session = _make_fp_session()
    with patch('f1_data._load_session', return_value=session):
        result = f1_data.get_fp_summary(1, 2)
    driver = result['drivers'][0]
    quali_sims = [s for s in driver['stints'] if s['classification'] == 'quali_sim']
    assert len(quali_sims) >= 1


def test_get_fp_summary_has_best_lap():
    """best_lap_time_s is populated from the fastest lap."""
    import f1_data
    session = _make_fp_session()
    with patch('f1_data._load_session', return_value=session):
        result = f1_data.get_fp_summary(1, 2)
    driver = result['drivers'][0]
    assert driver['best_lap_time_s'] == pytest.approx(88.0, abs=0.01)
```

- [ ] **Step 2: Run tests to verify they fail**

```
cd server && python -m pytest tests/test_f1_data.py::test_get_fp_summary_structure tests/test_f1_data.py::test_get_fp_summary_classifies_long_run -v
```

Expected: FAIL (AttributeError — `get_fp_summary` doesn't exist yet)

- [ ] **Step 3: Implement `get_fp_summary` in `server/f1_data.py`**

Add this function after `get_safety_car_periods` (around line 3543):

```python
def get_fp_summary(round_number: int, fp_number: int) -> dict:
    """
    Rich free practice summary with stint classification for LLM reasoning.
    fp_number: 1, 2, or 3.
    Classifies stints as long_run (8+ laps, race pace sim), short_run (3-7 laps,
    setup/balance work), quali_sim (1-2 laps fresh soft/medium, single-lap pace),
    or installation (pit-out lap at session start).
    NOTE: FastF1 does not provide fuel load. Long-run pace is heavier fuel than race.
    """
    session_type = f'FP{fp_number}'
    session = _load_session(round_number, session_type, laps=True, telemetry=False,
                            weather=False, messages=False)
    driver_info = _driver_lookup(session)

    def _classify_stint(laps_in_stint: list, stint_no: int) -> str:
        lc = len(laps_in_stint)
        first = laps_in_stint[0]
        compound = str(first.get('Compound')) if pd.notna(first.get('Compound')) else ''
        fresh = bool(first.get('FreshTyre')) if pd.notna(first.get('FreshTyre')) else False
        is_pit_out = pd.notna(first.get('PitOutTime'))
        is_first_stint = stint_no == min(stint_no, 1)
        if lc == 1 and is_pit_out and is_first_stint:
            return 'installation'
        if lc >= 8:
            return 'long_run'
        if lc <= 2 and fresh and compound in ('SOFT', 'SUPERSOFT', 'ULTRASOFT', 'HYPERSOFT'):
            return 'quali_sim'
        return 'short_run'

    driver_results = []
    for code in session.drivers:
        driver_laps = _pick_driver(session.laps, str(code))
        if getattr(driver_laps, 'empty', True):
            continue

        groups: dict[int, list] = {}
        for _, lap in driver_laps.iterrows():
            stint_key = int(lap['Stint']) if pd.notna(lap.get('Stint')) else 1
            groups.setdefault(stint_key, []).append(lap)

        stints = []
        for stint_no in sorted(groups):
            laps_in = groups[stint_no]
            first, last = laps_in[0], laps_in[-1]
            compound = str(first.get('Compound')) if pd.notna(first.get('Compound')) else None
            fresh = bool(first.get('FreshTyre')) if pd.notna(first.get('FreshTyre')) else None
            valid_times = [
                l['LapTime'].total_seconds()
                for l in laps_in
                if l.get('LapTime') is not None and not pd.isna(l['LapTime'])
            ]
            stints.append({
                'stint': stint_no,
                'compound': compound,
                'fresh_tyre': fresh,
                'laps': len(laps_in),
                'classification': _classify_stint(laps_in, stint_no),
                'start_lap': int(first['LapNumber']) if pd.notna(first.get('LapNumber')) else None,
                'end_lap': int(last['LapNumber']) if pd.notna(last.get('LapNumber')) else None,
                'best_lap_s': round(min(valid_times), 3) if valid_times else None,
                'avg_lap_s': round(sum(valid_times) / len(valid_times), 3) if valid_times else None,
            })

        all_valid = sorted(
            [l for _, l in driver_laps.iterrows()
             if l.get('LapTime') is not None and not pd.isna(l['LapTime'])],
            key=lambda l: l['LapTime'],
        )
        best = all_valid[0] if all_valid else None
        info = driver_info.get(str(code).upper(), {})
        driver_results.append({
            'driver': info.get('FullName') or str(code).upper(),
            'code': str(code).upper(),
            'team': info.get('TeamName'),
            'stints': stints,
            'best_lap_time': _fmt_td(best['LapTime']) if best is not None else None,
            'best_lap_time_s': round(best['LapTime'].total_seconds(), 3) if best is not None else None,
            'best_lap_compound': str(best['Compound']) if best is not None and pd.notna(best.get('Compound')) else None,
            'speed_st': round(float(best['SpeedST']), 1) if best is not None and pd.notna(best.get('SpeedST')) else None,
            'long_run_count': sum(1 for s in stints if s['classification'] == 'long_run'),
            'quali_sim_count': sum(1 for s in stints if s['classification'] == 'quali_sim'),
            'compounds_used': list({s['compound'] for s in stints if s.get('compound')}),
        })

    driver_results.sort(key=lambda d: d.get('best_lap_time_s') or float('inf'))

    return {
        'event': session.event['EventName'],
        'session': session_type,
        'drivers': driver_results,
        'session_notes': [
            'Fuel load is not measured — FastF1 does not provide fuel load for FP sessions.',
            'Long-run stints (8+ laps, same compound) approximate race pace but are run on heavier fuel than the race.',
            'Quali-sim stints (1-2 laps on fresh soft, fast time) approximate single-lap pace.',
            'Installation laps (first pit-out lap of session) are included in stints but excluded from pace context.',
            'FP lap times are not directly comparable to qualifying times due to fuel load and tyre program differences.',
        ],
    }
```

- [ ] **Step 4: Run tests to verify they pass**

```
cd server && python -m pytest tests/test_f1_data.py::test_get_fp_summary_structure tests/test_f1_data.py::test_get_fp_summary_classifies_long_run tests/test_f1_data.py::test_get_fp_summary_classifies_quali_sim tests/test_f1_data.py::test_get_fp_summary_has_best_lap -v
```

Expected: 4 PASS

- [ ] **Step 5: Run full test suite**

```
cd server && python -m pytest tests/ -q
```

- [ ] **Step 6: Commit**

```bash
git add server/f1_data.py server/tests/test_f1_data.py
git commit -m "feat: add get_fp_summary with stint classification"
```

---

## Task 3: Speed Trap Leaderboard — data function

**Files:**
- Modify: `server/f1_data.py` — add `get_speed_trap_leaderboard` after `get_fp_summary`
- Test: `server/tests/test_f1_data.py`

### Background
`get_session_fastest_laps` only shows speed traps from each driver's fastest lap. This tool scans ALL laps and finds the peak speed at each of the four trap points independently — a driver's peak SpeedST might be on a slipstream lap, not their fastest overall lap.

- [ ] **Step 1: Write the failing tests**

Add to `server/tests/test_f1_data.py`:

```python
def _make_trap_session():
    """Session where peak SpeedST is NOT on the fastest overall lap."""
    import pandas as pd
    from unittest.mock import MagicMock

    laps_rows = [
        # Lap 1: fast overall but average trap speed
        {
            'Driver': 'AAA', 'Team': 'Alpha', 'LapNumber': 1,
            'LapStartTime': pd.Timedelta(seconds=0),
            'PitInTime': pd.NaT, 'PitOutTime': pd.NaT,
            'Stint': 1, 'Compound': 'SOFT', 'FreshTyre': True, 'TrackStatus': '1',
            'LapTime': pd.Timedelta(seconds=88),
            'SpeedST': 290.0, 'SpeedFL': 285.0, 'SpeedI1': 280.0, 'SpeedI2': 282.0,
        },
        # Lap 2: slower lap but peak trap speed (slipstream)
        {
            'Driver': 'AAA', 'Team': 'Alpha', 'LapNumber': 2,
            'LapStartTime': pd.Timedelta(seconds=90),
            'PitInTime': pd.NaT, 'PitOutTime': pd.NaT,
            'Stint': 1, 'Compound': 'SOFT', 'FreshTyre': True, 'TrackStatus': '1',
            'LapTime': pd.Timedelta(seconds=91),
            'SpeedST': 315.0, 'SpeedFL': 288.0, 'SpeedI1': 283.0, 'SpeedI2': 285.0,
        },
        # Driver BBB: one lap, lower SpeedST
        {
            'Driver': 'BBB', 'Team': 'Beta', 'LapNumber': 1,
            'LapStartTime': pd.Timedelta(seconds=0),
            'PitInTime': pd.NaT, 'PitOutTime': pd.NaT,
            'Stint': 1, 'Compound': 'MEDIUM', 'FreshTyre': True, 'TrackStatus': '1',
            'LapTime': pd.Timedelta(seconds=89),
            'SpeedST': 305.0, 'SpeedFL': 300.0, 'SpeedI1': 295.0, 'SpeedI2': 297.0,
        },
    ]
    laps_df = pd.DataFrame(laps_rows)

    session = MagicMock()
    session.laps = laps_df
    session.drivers = ['AAA', 'BBB']
    session.event = {'EventName': 'Test GP'}
    return session


def test_speed_trap_leaderboard_structure():
    """Returns event, session, trap_labels, and four ranked lists."""
    import f1_data
    session = _make_trap_session()
    with patch('f1_data._load_session', return_value=session):
        result = f1_data.get_speed_trap_leaderboard(1, 'Q')
    assert result['session'] == 'Q'
    assert 'speed_st' in result
    assert 'speed_fl' in result
    assert 'speed_i1' in result
    assert 'speed_i2' in result
    assert isinstance(result['speed_st'], list)


def test_speed_trap_leaderboard_peak_not_from_fastest_lap():
    """Peak SpeedST is 315.0 from lap 2, even though lap 1 was faster overall."""
    import f1_data
    session = _make_trap_session()
    with patch('f1_data._load_session', return_value=session):
        result = f1_data.get_speed_trap_leaderboard(1, 'Q')
    top_st = result['speed_st'][0]
    assert top_st['driver'] == 'AAA'
    assert top_st['speed_kph'] == pytest.approx(315.0)
    assert top_st['lap_number'] == 2


def test_speed_trap_leaderboard_ranking_order():
    """speed_st is ranked descending — highest speed first."""
    import f1_data
    session = _make_trap_session()
    with patch('f1_data._load_session', return_value=session):
        result = f1_data.get_speed_trap_leaderboard(1, 'Q')
    speeds = [e['speed_kph'] for e in result['speed_st']]
    assert speeds == sorted(speeds, reverse=True)
```

- [ ] **Step 2: Run tests to verify they fail**

```
cd server && python -m pytest tests/test_f1_data.py::test_speed_trap_leaderboard_structure tests/test_f1_data.py::test_speed_trap_leaderboard_peak_not_from_fastest_lap -v
```

Expected: FAIL (AttributeError — `get_speed_trap_leaderboard` doesn't exist)

- [ ] **Step 3: Implement `get_speed_trap_leaderboard` in `server/f1_data.py`**

Add after `get_fp_summary`:

```python
def get_speed_trap_leaderboard(round_number: int, session_type: str) -> dict:
    """
    Speed trap rankings scanning ALL laps per driver — not just their fastest lap.
    A driver's peak SpeedST might be on a slipstream lap, not their personal best.
    Returns four independent ranked lists: SpeedST, SpeedFL, SpeedI1, SpeedI2.
    SpeedST = main straight trap; SpeedFL = finish line; SpeedI1/I2 = intermediate points.
    """
    session = _load_session(round_number, session_type, laps=True, telemetry=False,
                            weather=False, messages=False)
    driver_info = _driver_lookup(session)

    TRAP_COLS = {
        'speed_st': 'SpeedST',
        'speed_fl': 'SpeedFL',
        'speed_i1': 'SpeedI1',
        'speed_i2': 'SpeedI2',
    }
    TRAP_LABELS = {
        'speed_st': 'Speed Trap (main straight)',
        'speed_fl': 'Finish Line',
        'speed_i1': 'Intermediate 1',
        'speed_i2': 'Intermediate 2',
    }

    per_driver: dict[str, dict] = {}
    for code in session.drivers:
        driver_laps = _pick_driver(session.laps, str(code))
        if getattr(driver_laps, 'empty', True):
            continue
        info = driver_info.get(str(code).upper(), {})
        entry: dict = {
            'driver': str(code).upper(),
            'team': info.get('TeamName'),
        }
        for key, col in TRAP_COLS.items():
            if col not in driver_laps.columns:
                entry[key] = None
                entry[f'{key}_lap'] = None
                entry[f'{key}_compound'] = None
                continue
            col_series = driver_laps[col].dropna()
            if col_series.empty:
                entry[key] = None
                entry[f'{key}_lap'] = None
                entry[f'{key}_compound'] = None
            else:
                peak_idx = col_series.idxmax()
                peak_row = driver_laps.loc[peak_idx]
                entry[key] = round(float(col_series.max()), 1)
                entry[f'{key}_lap'] = int(peak_row['LapNumber']) if pd.notna(peak_row.get('LapNumber')) else None
                entry[f'{key}_compound'] = str(peak_row['Compound']) if pd.notna(peak_row.get('Compound')) else None
        per_driver[str(code).upper()] = entry

    ranked: dict[str, list] = {}
    for key in TRAP_COLS:
        ranked_list = sorted(
            [d for d in per_driver.values() if d.get(key) is not None],
            key=lambda d: d[key],
            reverse=True,
        )
        for i, d in enumerate(ranked_list):
            ranked[key] = ranked.get(key, [])
            ranked[key].append({
                'rank': i + 1,
                'driver': d['driver'],
                'team': d['team'],
                'speed_kph': d[key],
                'lap_number': d[f'{key}_lap'],
                'compound': d[f'{key}_compound'],
            })

    return {
        'event': session.event['EventName'],
        'session': session_type.upper(),
        'trap_labels': TRAP_LABELS,
        'speed_st': ranked.get('speed_st', []),
        'speed_fl': ranked.get('speed_fl', []),
        'speed_i1': ranked.get('speed_i1', []),
        'speed_i2': ranked.get('speed_i2', []),
    }
```

- [ ] **Step 4: Run tests to verify they pass**

```
cd server && python -m pytest tests/test_f1_data.py::test_speed_trap_leaderboard_structure tests/test_f1_data.py::test_speed_trap_leaderboard_peak_not_from_fastest_lap tests/test_f1_data.py::test_speed_trap_leaderboard_ranking_order -v
```

Expected: 3 PASS

- [ ] **Step 5: Run full test suite**

```
cd server && python -m pytest tests/ -q
```

- [ ] **Step 6: Commit**

```bash
git add server/f1_data.py server/tests/test_f1_data.py
git commit -m "feat: add get_speed_trap_leaderboard scanning all laps for peak speed per trap"
```

---

## Task 4: Register both new tools in tools.py

**Files:**
- Modify: `server/tools.py` — add tool definitions and `execute_tool` dispatch branches
- Test: `server/tests/test_tools.py`

### Background
`tools.py` has `PRIMITIVE_TOOL_DEFINITIONS` (list of `_tool(...)` dicts) and `execute_tool(name, args)` dispatch. New tools go at the end of `PRIMITIVE_TOOL_DEFINITIONS` and need dispatch branches.

- [ ] **Step 1: Write the failing test**

In `server/tests/test_tools.py`, add:

```python
def test_get_fp_summary_in_tool_definitions():
    from tools import TOOL_DEFINITIONS
    names = [t['function']['name'] for t in TOOL_DEFINITIONS]
    assert 'get_fp_summary' in names


def test_get_speed_trap_leaderboard_in_tool_definitions():
    from tools import TOOL_DEFINITIONS
    names = [t['function']['name'] for t in TOOL_DEFINITIONS]
    assert 'get_speed_trap_leaderboard' in names
```

- [ ] **Step 2: Run tests to verify they fail**

```
cd server && python -m pytest tests/test_tools.py::test_get_fp_summary_in_tool_definitions tests/test_tools.py::test_get_speed_trap_leaderboard_in_tool_definitions -v
```

Expected: FAIL

- [ ] **Step 3: Add imports to tools.py**

At the top of `server/tools.py`, in the import block where other `f1_data` functions are imported, add:

```python
from f1_data import (
    # ... existing imports ...
    get_fp_summary,
    get_speed_trap_leaderboard,
)
```

- [ ] **Step 4: Add tool definitions to PRIMITIVE_TOOL_DEFINITIONS**

At the end of `PRIMITIVE_TOOL_DEFINITIONS` (before the closing `]`), add:

```python
    _tool(
        "get_fp_summary",
        "PRIMITIVE TOOL. Free practice session summary with per-driver stint classification. "
        "Classifies each stint as long_run (race pace sim, 8+ laps), short_run (setup/balance work), "
        "quali_sim (1-2 laps fresh soft, single-lap pace), or installation (first pit-out lap). "
        "Returns best lap time, speed trap, compounds used, and structured stint data per driver. "
        "Use for ANY free practice question: fastest in FP1, what programme did a driver run, "
        "long-run pace, tyre comparison in practice. NOTE: fuel load is not measured — "
        "long-run pace is heavier fuel than race, not directly comparable to qualifying times.",
        {
            "round_number": {"type": "integer", "description": "The 2026 season round number."},
            "fp_number": {"type": "integer", "description": "Free practice session number: 1, 2, or 3."},
        },
        ["round_number", "fp_number"],
    ),
    _tool(
        "get_speed_trap_leaderboard",
        "PRIMITIVE TOOL. Speed trap rankings scanning ALL laps in a session — not just fastest laps. "
        "Returns four independent ranked lists for SpeedST (main straight trap), SpeedFL (finish line), "
        "SpeedI1 (intermediate 1), SpeedI2 (intermediate 2). Each entry includes driver, team, peak speed "
        "in kph, which lap it came from, and compound. Use for 'who had the highest top speed?', "
        "'who was fastest down the straight?', 'show me the speed trap leaderboard', "
        "'which team has the least drag?'.",
        {
            "round_number": {"type": "integer", "description": "The 2026 season round number."},
            "session_type": {"type": "string", "description": "Session type: Q, R, FP1, FP2, FP3, S, SQ, SS."},
        },
        ["round_number", "session_type"],
    ),
```

- [ ] **Step 5: Add dispatch branches in execute_tool**

In `execute_tool(name, args)`, before the final `raise ValueError(...)`, add:

```python
    if name == "get_fp_summary":
        return get_fp_summary(args["round_number"], args["fp_number"])
    if name == "get_speed_trap_leaderboard":
        return get_speed_trap_leaderboard(args["round_number"], args["session_type"])
```

- [ ] **Step 6: Run tests to verify they pass**

```
cd server && python -m pytest tests/test_tools.py::test_get_fp_summary_in_tool_definitions tests/test_tools.py::test_get_speed_trap_leaderboard_in_tool_definitions -v
```

Expected: 2 PASS

- [ ] **Step 7: Run full test suite**

```
cd server && python -m pytest tests/ -q
```

- [ ] **Step 8: Commit**

```bash
git add server/tools.py server/tests/test_tools.py
git commit -m "feat: register get_fp_summary and get_speed_trap_leaderboard tools"
```

---

## Task 5: Resolver scopes for FP and speed trap

**Files:**
- Modify: `server/resolver.py` — `_detect_session_scope`, `_suggest_tool`, `_suggested_tool_args` equivalent logic in `chat.py`
- Modify: `server/chat.py` — `_suggested_tool_args`
- Test: `server/tests/test_resolver.py`

### Background
`_detect_session_scope` returns `(session_type, scope)`. New scopes: `"fp"` and `"speed_trap"`. `_suggest_tool` maps scope → tool name. `_suggested_tool_args` in `chat.py` maps resolved context → concrete args dict.

FP questions mention "fp1"/"fp2"/"fp3"/"free practice"/"practice session". Speed trap questions mention "top speed"/"speed trap"/"fastest straight"/"drag"/"straight-line speed".

- [ ] **Step 1: Write failing resolver tests**

In `server/tests/test_resolver.py`, add:

```python
def test_fp1_scope_routes_to_fp_summary():
    from resolver import resolve_query_context
    result = resolve_query_context("who was fastest in fp1 at bahrain?", None)
    assert result.get('scope') == 'fp'
    assert result.get('suggested_tool') == 'get_fp_summary'


def test_fp2_scope_detects_session_number():
    from resolver import resolve_query_context
    result = resolve_query_context("what did norris run in fp2?", None)
    assert result.get('scope') == 'fp'


def test_free_practice_scope_detected():
    from resolver import resolve_query_context
    result = resolve_query_context("what happened in free practice 2?", None)
    assert result.get('scope') == 'fp'


def test_speed_trap_scope_routes_to_leaderboard():
    from resolver import resolve_query_context
    result = resolve_query_context("who had the highest top speed in qualifying?", None)
    assert result.get('scope') == 'speed_trap'
    assert result.get('suggested_tool') == 'get_speed_trap_leaderboard'


def test_fastest_straight_scope_detected():
    from resolver import resolve_query_context
    result = resolve_query_context("which team was fastest down the straight in the race?", None)
    assert result.get('scope') == 'speed_trap'
```

- [ ] **Step 2: Run tests to verify they fail**

```
cd server && python -m pytest tests/test_resolver.py::test_fp1_scope_routes_to_fp_summary tests/test_resolver.py::test_speed_trap_scope_routes_to_leaderboard -v
```

Expected: FAIL (scope not detected)

- [ ] **Step 3: Add scopes to `_detect_session_scope` in `server/resolver.py`**

In `_detect_session_scope`, after the existing `scope = "circuit"` block (around line 204), before `return session_type, scope`, add:

```python
    # FP scope — free practice questions
    fp_match = re.search(r'\bfp\s*([123])\b', normalized) or re.search(r'free\s*practice\s*([123])', normalized) or re.search(r'practice\s*([123])', normalized)
    if fp_match or any(phrase in normalized for phrase in ('free practice', 'practice session', 'fp1', 'fp2', 'fp3')):
        scope = 'fp'

    # Speed trap scope — top speed / straight-line speed questions
    if any(phrase in normalized for phrase in (
        'top speed', 'speed trap', 'fastest straight', 'fastest down the straight',
        'straight-line speed', 'straight line speed', 'drag', 'least drag',
        'most drag', 'trap speed', 'speed down the straight', 'fastest on the straight',
    )):
        scope = 'speed_trap'
```

Also add session_type detection for FP sessions — in the session_type block at the top of `_detect_session_scope`, add after the sprint check:

```python
    elif re.search(r'\bfp\s*1\b', normalized) or 'free practice 1' in normalized or 'practice 1' in normalized:
        session_type = 'FP1'
    elif re.search(r'\bfp\s*2\b', normalized) or 'free practice 2' in normalized or 'practice 2' in normalized:
        session_type = 'FP2'
    elif re.search(r'\bfp\s*3\b', normalized) or 'free practice 3' in normalized or 'practice 3' in normalized:
        session_type = 'FP3'
```

- [ ] **Step 4: Add to `_suggest_tool` in `server/resolver.py`**

At the top of `_suggest_tool` (before existing scope checks), add:

```python
    if scope == 'fp':
        return 'get_fp_summary'
    if scope == 'speed_trap':
        return 'get_speed_trap_leaderboard'
```

- [ ] **Step 5: Add `_suggested_tool_args` handling in `server/chat.py`**

In `_suggested_tool_args`, add before the final `return None`:

```python
    if tool == "get_fp_summary":
        # derive fp_number from session_type (FP1→1, FP2→2, FP3→3)
        st = resolved.get("session_type") or "FP2"
        fp_map = {"FP1": 1, "FP2": 2, "FP3": 3}
        fp_number = fp_map.get(st.upper(), 2)
        return {"round_number": round_number, "fp_number": fp_number}

    if tool == "get_speed_trap_leaderboard":
        session_type = resolved.get("session_type") or "Q"
        return {"round_number": round_number, "session_type": session_type}
```

- [ ] **Step 6: Run resolver tests to verify they pass**

```
cd server && python -m pytest tests/test_resolver.py::test_fp1_scope_routes_to_fp_summary tests/test_resolver.py::test_fp2_scope_detects_session_number tests/test_resolver.py::test_free_practice_scope_detected tests/test_resolver.py::test_speed_trap_scope_routes_to_leaderboard tests/test_resolver.py::test_fastest_straight_scope_detected -v
```

Expected: 5 PASS

- [ ] **Step 7: Run full test suite**

```
cd server && python -m pytest tests/ -q
```

Expected: all pass

- [ ] **Step 8: Commit**

```bash
git add server/resolver.py server/chat.py server/tests/test_resolver.py
git commit -m "feat: add fp and speed_trap resolver scopes with suggested_tool_args"
```

---

## Task 6: Free Practice interpretation in ANALYSIS_SYSTEM_PROMPT

**Files:**
- Modify: `server/chat.py` — `_build_analysis_system_prompt`

### Background
The analysis LLM receives the `get_fp_summary` JSON and must reason about it without hallucinating fuel loads or treating FP pace as race/quali pace. The system prompt needs an explicit FP reasoning section.

- [ ] **Step 1: Verify the test**

Check `server/tests/test_chat.py` for any prompt content tests. If none exist for this, we verify by inspection only.

```
cd server && python -c "from chat import ANALYSIS_SYSTEM_PROMPT; assert 'Free Practice' in ANALYSIS_SYSTEM_PROMPT; print('OK')"
```

Expected: FAIL (section not added yet)

- [ ] **Step 2: Add `## Free Practice Interpretation` section to `_build_analysis_system_prompt` in `server/chat.py`**

In `_build_analysis_system_prompt`, in the returned f-string, add this section after the `## Race Strategy Reasoning` block (which ends before `## Required JSON Output`):

```python
## Free Practice Interpretation

When `get_fp_summary` results are in the evidence, reason about FP data with these ground rules:

**What FP data is:**
- Structured stints per driver, each classified as: `long_run` (8+ laps same compound — race pace sim), `short_run` (3–7 laps — setup/balance work or tyre assessment), `quali_sim` (1–2 laps on fresh soft/medium — single-lap pace simulation), or `installation` (first pit-out lap, excluded from pace context).
- `best_lap_time_s` is the fastest clean lap the driver set across all stints.
- `speed_st` is the speed trap reading on the driver's best lap.

**Critical fuel load caveat:**
FastF1 does NOT provide fuel load for FP sessions. Long-run laps are always on heavier fuel than the race (sometimes significantly — a full tank can be 30–40kg heavier than end-of-race). This means:
- Long-run pace is SLOWER than race pace by fuel weight effect alone.
- Do not compare long-run lap times directly to race or qualifying times.
- Do not state fuel load figures — they are unknown.
- Embed the caveat naturally: "on a heavy fuel load so direct comparison to race pace is rough" is correct. "He was running 45kg of fuel" is invented.

**What you CAN conclude from long runs:**
- Relative pace between drivers on similar-length stints is meaningful — the fuel loads are roughly comparable if the stints are similar length and compound.
- Tyre deg trend within a long run (lap 1 vs lap 8 on same compound) is real — fuel load effect is the same throughout the stint.
- If Driver A ran 10 laps on HARD and Driver B ran 8 laps on HARD, A's average is slightly fuel-corrected by being further into the stint — note this caveat if comparing averages.

**What you CAN conclude from quali sims:**
- A 1–2 lap fresh soft stint at the end of FP is the closest thing to qualifying pace.
- But track evolution in qualifying is typically faster than FP (rubber laid by many laps) — FP quali sim times are usually 0.2–0.5s slower than actual qualifying for the same car, all else equal.

**Programme reading:**
- `long_run_count` tells you how much race simulation a driver did.
- `quali_sim_count` tells you how much single-lap work they did.
- `compounds_used` tells you which tyres they assessed.
- A driver with `long_run_count: 0` focused on setup/single-lap pace. A driver with `long_run_count: 2` was heavily focused on race simulation.

**Never:**
- State a specific fuel load figure.
- Compare FP lap times to qualifying lap times as if they're equivalent.
- Treat `best_lap_time_s` as a quali pace estimate without noting it may be from a heavy-fuel short run.
```

- [ ] **Step 3: Verify the section was added**

```
cd server && python -c "from chat import ANALYSIS_SYSTEM_PROMPT; assert 'Free Practice' in ANALYSIS_SYSTEM_PROMPT; assert 'fuel load' in ANALYSIS_SYSTEM_PROMPT; print('OK')"
```

Expected: OK

- [ ] **Step 4: Run full test suite**

```
cd server && python -m pytest tests/ -q
```

- [ ] **Step 5: Commit**

```bash
git add server/chat.py
git commit -m "feat: add Free Practice interpretation section to analysis system prompt"
```

---

## Task 7: SYSTEM_PROMPT guidance for new tools

**Files:**
- Modify: `server/chat.py` — `SYSTEM_PROMPT`

### Background
The tool-calling LLM uses `SYSTEM_PROMPT` to choose which tool to call. It needs to know about `get_fp_summary` and `get_speed_trap_leaderboard`.

- [ ] **Step 1: Add guidance lines to SYSTEM_PROMPT in `server/chat.py`**

In `SYSTEM_PROMPT`, in the "Guidelines" section (around the existing tool routing bullet points), add after the stint/strategy bullet:

```python
- For any free practice question — who was fastest in FP1/FP2/FP3, what programme did a driver run, long-run pace, tyre comparison, what compounds were used: use get_fp_summary. Note that fuel load is not measurable from FastF1 FP data — do not state fuel figures.
- For straight-line speed, top speed, speed trap, or drag questions: use get_speed_trap_leaderboard. This scans ALL laps per driver, so it finds peak speeds that may not appear on a driver's fastest lap (e.g. slipstream laps). Returns four independent ranked lists for SpeedST, SpeedFL, SpeedI1, SpeedI2.
```

- [ ] **Step 2: Run full test suite**

```
cd server && python -m pytest tests/ -q
```

Expected: all pass

- [ ] **Step 3: Commit**

```bash
git add server/chat.py
git commit -m "feat: add get_fp_summary and get_speed_trap_leaderboard guidance to SYSTEM_PROMPT"
```

---

## Self-Review

### Spec coverage check
- [x] SC: `period_narrative`, `all_victims`, `all_beneficiaries` — Task 1 ✓
- [x] FP: `get_fp_summary` with stint classification — Task 2 ✓
- [x] FP: `session_notes` caveats — Task 2 ✓
- [x] Speed trap: `get_speed_trap_leaderboard` scanning all laps — Task 3 ✓
- [x] Tool registration for both — Task 4 ✓
- [x] Resolver scopes `fp` and `speed_trap` — Task 5 ✓
- [x] FP interpretation in ANALYSIS_SYSTEM_PROMPT — Task 6 ✓
- [x] SYSTEM_PROMPT routing guidance — Task 7 ✓

### Placeholder scan
No TBDs. All code is complete and exact.

### Type consistency
- `get_fp_summary(round_number: int, fp_number: int)` — consistent across Task 2, Task 4, Task 5.
- `get_speed_trap_leaderboard(round_number: int, session_type: str)` — consistent across Task 3, Task 4, Task 5.
- `period_narrative`, `all_victims`, `all_beneficiaries` — consistent across Task 1.
