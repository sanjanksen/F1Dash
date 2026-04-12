# server/f1_data.py
import os
import fastf1
import requests
import pandas as pd

# Enable FastF1 disk cache
_CACHE_DIR = os.path.join(os.path.dirname(__file__), 'cache')
os.makedirs(_CACHE_DIR, exist_ok=True)
fastf1.Cache.enable_cache(_CACHE_DIR)

JOLPICA_BASE = "https://api.jolpi.ca/ergast/f1"
CURRENT_YEAR = 2025


def _fmt_td(td) -> str | None:
    """Format a pd.Timedelta to a lap-time string like '1:26.456' or '0:28.123'."""
    if td is None or pd.isna(td):
        return None
    total = td.total_seconds()
    m = int(total // 60)
    s = total % 60
    return f"{m}:{s:06.3f}"


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


def get_drivers() -> list[dict]:
    """Return all drivers in the current season with championship standings."""
    resp = requests.get(
        f"{JOLPICA_BASE}/{CURRENT_YEAR}/driverStandings.json?limit=30",
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()

    standings_lists = data["MRData"]["StandingsTable"]["StandingsLists"]
    if not standings_lists:
        return []

    drivers = []
    for entry in standings_lists[0]["DriverStandings"]:
        d = entry["Driver"]
        constructors = entry.get("Constructors", [{}])
        drivers.append({
            "driver_id": d["driverId"],
            "full_name": f"{d['givenName']} {d['familyName']}",
            "code": d.get("code", ""),
            "nationality": d.get("nationality", ""),
            "team": constructors[0].get("name", "") if constructors else "",
            "standing": int(entry["position"]),
            "points": float(entry["points"]),
            "wins": int(entry["wins"]),
        })
    return drivers


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


def get_circuits() -> list[dict]:
    """Return the full season race schedule."""
    schedule = fastf1.get_event_schedule(CURRENT_YEAR, include_testing=False)
    circuits = []
    for _, event in schedule.iterrows():
        circuits.append({
            "round": int(event["RoundNumber"]),
            "event_name": event["EventName"],
            "circuit_name": event["Location"],
            "country": event["Country"],
            "date": str(event["EventDate"].date()),
        })
    return circuits


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

    def _find_and_fetch(name: str) -> tuple[dict, list[dict]]:
        needle = name.lower()
        for d in get_drivers():
            if (
                needle in d["full_name"].lower()
                or needle == d["driver_id"].lower()
                or needle == d["code"].lower()
            ):
                return d, _fetch_all_races(d["driver_id"])
        raise ValueError(f"Driver not found: {name}")

    matched_a, races_a = _find_and_fetch(driver_a_name)
    matched_b, races_b = _find_and_fetch(driver_b_name)

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


def get_circuit_corners(round_number: int) -> list[dict]:
    """
    Corner positions (distance along track in metres) for a circuit.
    Use alongside telemetry tools to map speed/brake differences to named corners.
    """
    circuit_info = fastf1.get_circuit_info(CURRENT_YEAR, round_number)
    corners = []
    for _, row in circuit_info.corners.iterrows():
        raw_label = str(row.get('Letter', '')).strip()
        corners.append({
            "number": int(row['Number']),
            "label": raw_label if raw_label else None,
            "distance_m": int(float(row['Distance']) + 0.5),
        })
    return corners


def get_historical_circuit_performance(round_number: int,
                                        years: list[int] | None = None) -> dict:
    """
    Qualifying top-5 and race top-5 for the same circuit across multiple seasons.
    Reveals which teams/drivers historically perform well or poorly at this venue.
    Default years: [2023, 2024, 2025].
    """
    if years is None:
        years = [2023, 2024, 2025]

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
