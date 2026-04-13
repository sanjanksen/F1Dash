# server/f1_data.py
import os
import logging
import threading
import numbers
import fastf1
import requests
import pandas as pd
from pandas.api.types import is_numeric_dtype
from energy_2026 import get_energy_2026_knowledge

# Enable FastF1 disk cache
_CACHE_DIR = os.path.join(os.path.dirname(__file__), 'cache')
os.makedirs(_CACHE_DIR, exist_ok=True)
fastf1.Cache.enable_cache(_CACHE_DIR)

JOLPICA_BASE = "https://api.jolpi.ca/ergast/f1"
CURRENT_YEAR = __import__('datetime').date.today().year
logger = logging.getLogger(__name__)

_SESSION_CACHE: dict[tuple[int, int, str], dict] = {}
_SESSION_CACHE_LOCK = threading.Lock()


def _fmt_td(td) -> str | None:
    """Format a pd.Timedelta to a lap-time string like '1:26.456' or '0:28.123'."""
    if td is None or pd.isna(td):
        return None
    total = td.total_seconds()
    m = int(total // 60)
    s = total % 60
    return f"{m}:{s:06.3f}"


def _load_session(round_number: int, session_type: str, *,
                  laps: bool = True, telemetry: bool = False,
                  weather: bool = False, messages: bool = False):
    _validate_session_availability(round_number, session_type, telemetry=telemetry or laps or messages)
    normalized_session = str(session_type).strip().upper()
    cache_key = (CURRENT_YEAR, round_number, normalized_session)

    with _SESSION_CACHE_LOCK:
        entry = _SESSION_CACHE.get(cache_key)
        if entry is None:
            entry = {
                "session": fastf1.get_session(CURRENT_YEAR, round_number, normalized_session),
                "laps": False,
                "telemetry": False,
                "weather": False,
                "messages": False,
                "lock": threading.Lock(),
            }
            _SESSION_CACHE[cache_key] = entry

    session = entry["session"]
    entry_lock = entry["lock"]

    with entry_lock:
        target_flags = {
            "laps": entry["laps"] or laps,
            "telemetry": entry["telemetry"] or telemetry,
            "weather": entry["weather"] or weather,
            "messages": entry["messages"] or messages,
        }
        needs_load = any(target_flags[name] and not entry[name] for name in target_flags)

        if not needs_load:
            logger.debug(
                "Reusing in-memory FastF1 session cache for round=%s session=%s",
                round_number,
                normalized_session,
            )
            return session

        session.load(
            laps=target_flags["laps"],
            telemetry=target_flags["telemetry"],
            weather=target_flags["weather"],
            messages=target_flags["messages"],
        )
        entry.update(target_flags)
        return session


def _clear_session_cache() -> None:
    with _SESSION_CACHE_LOCK:
        _SESSION_CACHE.clear()


def _normalize_session_name(session_type: str) -> set[str]:
    upper = str(session_type).strip().upper()
    mapping = {
        "FP1": {"FP1", "PRACTICE 1"},
        "FP2": {"FP2", "PRACTICE 2"},
        "FP3": {"FP3", "PRACTICE 3"},
        "Q": {"Q", "QUALIFYING"},
        "R": {"R", "RACE"},
        "S": {"S", "SPRINT"},
        "SQ": {"SQ", "SPRINT QUALIFYING"},
        "SS": {"SS", "SPRINT SHOOTOUT"},
    }
    return mapping.get(upper, {upper})


def _session_needs_race_control_messages(session_type: str) -> bool:
    return str(session_type).strip().upper() in {"Q", "SQ", "SS"}


def _find_session_column(event_row, session_type: str) -> tuple[str | None, pd.Timestamp | None]:
    aliases = _normalize_session_name(session_type)
    for idx in range(1, 6):
        name_key = f"Session{idx}"
        date_key = f"Session{idx}DateUtc"
        session_name = event_row.get(name_key)
        if session_name is None or pd.isna(session_name):
            continue
        normalized_name = str(session_name).strip().upper()
        if normalized_name in aliases:
            session_date = event_row.get(date_key)
            return normalized_name, session_date if session_date is not None and not pd.isna(session_date) else None
    return None, None


def _validate_session_availability(round_number: int, session_type: str, *, telemetry: bool) -> None:
    try:
        schedule = fastf1.get_event_schedule(CURRENT_YEAR, include_testing=False)
    except Exception:
        return
    matching = schedule[schedule["RoundNumber"] == round_number]
    if matching.empty:
        return

    event_row = matching.iloc[0]
    session_name, session_date = _find_session_column(event_row, session_type)
    event_name = event_row.get("EventName", f"Round {round_number}")

    if session_name is None:
        return

    if telemetry and "F1ApiSupport" in event_row and pd.notna(event_row.get("F1ApiSupport")) and not bool(event_row.get("F1ApiSupport")):
        raise ValueError(f"{event_name} does not have official F1 timing support for session {session_name}.")

    if session_date is not None:
        now_utc = pd.Timestamp.now(tz="UTC").tz_localize(None)
        session_date_utc = pd.Timestamp(session_date).tz_localize(None) if getattr(session_date, "tzinfo", None) is not None else pd.Timestamp(session_date)
        if session_date_utc > now_utc:
            raise ValueError(
                f"{event_name} {session_name.title()} has not happened yet. "
                f"It is scheduled for {session_date_utc.isoformat()} UTC."
            )


def _get_lap_attr(lap, key, default=None):
    getter = getattr(lap, "get", None)
    if callable(getter):
        return getter(key, default)
    try:
        value = lap[key]
    except Exception:
        return default
    return default if pd.isna(value) else value


def _normalize_position(value):
    if value is None or pd.isna(value):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        text = str(value).strip()
        return int(text) if text.isdigit() else None


def _normalize_float(value):
    if value is None or pd.isna(value):
        return None
    if isinstance(value, numbers.Real):
        return round(float(value), 3)
    if isinstance(value, str):
        try:
            return round(float(value), 3)
        except ValueError:
            return None
    try:
        return round(float(value), 3)
    except (TypeError, ValueError):
        return None


def _infer_lift_and_coast_samples(samples: list[dict]) -> list[dict]:
    events = []
    for idx in range(1, len(samples) - 1):
        sample = samples[idx]
        next_sample = samples[idx + 1]
        if sample.get("brake") or next_sample.get("brake"):
            continue
        throttle = sample.get("throttle_pct")
        speed = sample.get("speed_kph")
        next_speed = next_sample.get("speed_kph")
        if throttle is None or speed is None or next_speed is None:
            continue
        if throttle <= 20 and speed >= 180 and next_speed < speed:
            events.append({
                "distance_m": sample.get("distance_m"),
                "speed_kph": speed,
                "throttle_pct": throttle,
            })
    return events


def _find_full_throttle_straight_windows(samples: list[dict]) -> list[list[dict]]:
    windows = []
    current = []
    for sample in samples:
        gear = sample.get("gear")
        if (
            sample.get("brake") is False
            and (sample.get("throttle_pct") or 0) >= 95
            and (gear is None or gear >= 6)
        ):
            current.append(sample)
        else:
            if len(current) >= 4:
                windows.append(current)
            current = []
    if len(current) >= 4:
        windows.append(current)
    return windows


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


def _safe_timedelta_seconds(value):
    if value is None or pd.isna(value):
        return None
    if hasattr(value, "total_seconds"):
        return round(float(value.total_seconds()), 3)
    return _normalize_float(value)


def _session_results_rows(session) -> list[dict]:
    results = getattr(session, "results", None)
    if results is None:
        return []

    rows = []
    iterrows = getattr(results, "iterrows", None)
    if callable(iterrows):
        for _, row in iterrows():
            rows.append(dict(row))
        return rows

    if isinstance(results, list):
        return [dict(r) for r in results]

    return []


def _driver_lookup(session) -> dict[str, dict]:
    lookup = {}
    for row in _session_results_rows(session):
        abbr = str(row.get("Abbreviation", "")).upper()
        number = str(row.get("DriverNumber", "")).upper()
        if abbr:
            lookup[abbr] = row
        if number:
            lookup[number] = row
    return lookup


def _extract_track_markers(df) -> list[dict]:
    markers = []
    if df is None:
        return markers
    iterrows = getattr(df, "iterrows", None)
    if not callable(iterrows):
        return markers
    for _, row in iterrows():
        raw_letter = str(row.get('Letter', '')).strip()
        markers.append({
            "number": _normalize_position(row.get('Number')),
            "label": raw_letter if raw_letter else None,
            "x": _normalize_float(row.get('X')),
            "y": _normalize_float(row.get('Y')),
            "angle": _normalize_float(row.get('Angle')),
            "distance_m": _normalize_position(round(float(row['Distance']))) if pd.notna(row.get('Distance')) else None,
        })
    return markers


def _pick_representative_laps(laps, limit: int):
    if limit <= 0:
        return laps.iloc[0:0]
    if len(laps) <= limit:
        return laps
    indexed = []
    max_index = len(laps) - 1
    for i in range(limit):
        idx = round(i * max_index / (limit - 1)) if limit > 1 else 0
        indexed.append(idx)
    return laps.iloc[sorted(set(indexed))]


def _pick_fastest_lap(driver_laps):
    pick_fastest = getattr(driver_laps, "pick_fastest", None)
    if callable(pick_fastest):
        return pick_fastest()
    if hasattr(driver_laps, "sort_values"):
        lap_df = driver_laps.dropna(subset=['LapTime']).sort_values('LapTime')
        if lap_df.empty:
            raise ValueError("No valid lap time found")
        return lap_df.iloc[0]
    raise ValueError("No valid lap time found")


def _pick_driver(laps, code: str):
    """Call pick_drivers([code]) (FastF1 3.8+) or fall back to pick_driver(code)."""
    pick = getattr(laps, 'pick_drivers', None)
    if callable(pick):
        return pick([str(code)])
    return laps.pick_driver(str(code))


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


def _resolve_driver(driver_name: str) -> dict | None:
    needle = driver_name.lower()
    for d in get_drivers():
        if (
            needle in d["full_name"].lower()
            or needle == d["driver_id"].lower()
            or needle == d["code"].lower()
        ):
            return d
    return None


def _resolve_team(team_name: str) -> str | None:
    needle = team_name.lower()
    teams = {d.get("team", "") for d in get_drivers() if d.get("team")}
    for team in teams:
        if needle in team.lower() or team.lower() in needle:
            return team
    return None


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
    matched = _resolve_driver(driver_name)

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


def get_session_results(round_number: int, session_type: str) -> dict:
    """
    Rich session classification from FastF1 results metadata.
    Includes grid position, classified position, team color, and qualifying times when available.
    """
    session = _load_session(
        round_number,
        session_type,
        laps=True,
        telemetry=False,
        weather=False,
        messages=_session_needs_race_control_messages(session_type),
    )
    rows = _session_results_rows(session)
    return {
        "event": session.event['EventName'],
        "session": session_type.upper(),
        "total_laps": getattr(session, "total_laps", None),
        "results": [
            {
                "position": _normalize_position(row.get("Position")),
                "classified_position": row.get("ClassifiedPosition"),
                "grid_position": _normalize_position(row.get("GridPosition")),
                "status": row.get("Status"),
                "points": _normalize_float(row.get("Points")),
                "driver": row.get("FullName") or " ".join(
                    part for part in [row.get("FirstName"), row.get("LastName")] if part
                ).strip(),
                "broadcast_name": row.get("BroadcastName"),
                "abbreviation": row.get("Abbreviation"),
                "driver_number": str(row.get("DriverNumber")) if row.get("DriverNumber") is not None else None,
                "team": row.get("TeamName"),
                "team_color": row.get("TeamColor"),
                "country_code": row.get("CountryCode"),
                "headshot_url": row.get("HeadshotUrl"),
                "q1": _fmt_td(row.get("Q1")) if row.get("Q1") is not None else None,
                "q2": _fmt_td(row.get("Q2")) if row.get("Q2") is not None else None,
                "q3": _fmt_td(row.get("Q3")) if row.get("Q3") is not None else None,
            }
            for row in rows
        ],
    }


def get_head_to_head(driver_a_name: str, driver_b_name: str) -> dict:
    """Compare two drivers side-by-side across all 2025 races they both competed in."""

    def _find_and_fetch(name: str) -> tuple[dict, list[dict]]:
        matched = _resolve_driver(name)
        if matched is not None:
            return matched, _fetch_all_races(matched["driver_id"])
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
    session = _load_session(
        round_number,
        session_type,
        laps=True,
        telemetry=False,
        weather=False,
        messages=_session_needs_race_control_messages(session_type),
    )

    results = []
    for driver_code in session.drivers:
        driver_laps = _pick_driver(session.laps, driver_code)
        if driver_laps.empty:
            continue
        fastest = _pick_fastest_lap(driver_laps)
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
    session = _load_session(
        round_number,
        session_type,
        laps=True,
        telemetry=False,
        weather=False,
        messages=_session_needs_race_control_messages(session_type),
    )

    driver_laps = _pick_driver(session.laps, driver_code.upper())
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


def get_driver_strategy(round_number: int, session_type: str, driver_code: str | None = None) -> dict:
    """
    Summarize tyre strategy and stints for a driver or the full field.
    """
    session = _load_session(round_number, session_type, laps=True, telemetry=False, weather=False, messages=False)
    driver_info = _driver_lookup(session)

    def _summarize_driver(code: str) -> dict:
        driver_laps = _pick_driver(session.laps, code.upper())
        if driver_laps.empty:
            raise ValueError(f"No data for driver {code!r} in round {round_number} {session_type}")

        stints = []
        iterrows = getattr(driver_laps, "iterrows", None)
        if callable(iterrows):
            groups = {}
            for _, lap in iterrows():
                stint_key = int(lap['Stint']) if pd.notna(lap.get('Stint')) else len(groups) + 1
                groups.setdefault(stint_key, []).append(lap)
            for stint_no in sorted(groups):
                laps = groups[stint_no]
                first, last = laps[0], laps[-1]
                lap_count = len(laps)
                lap_times = [lt.total_seconds() for lt in (lap.get('LapTime') for lap in laps) if lt is not None and not pd.isna(lt)]
                positions = [int(p) for p in (lap.get('Position') for lap in laps) if p is not None and not pd.isna(p)]
                stints.append({
                    "stint": stint_no,
                    "compound": str(first.get('Compound')) if pd.notna(first.get('Compound')) else None,
                    "fresh_tyre": bool(first.get('FreshTyre')) if pd.notna(first.get('FreshTyre')) else None,
                    "start_lap": int(first['LapNumber']) if pd.notna(first.get('LapNumber')) else None,
                    "end_lap": int(last['LapNumber']) if pd.notna(last.get('LapNumber')) else None,
                    "laps": lap_count,
                    "avg_lap_time_s": round(sum(lap_times) / len(lap_times), 3) if lap_times else None,
                    "best_lap_time": _fmt_td(min((lap.get('LapTime') for lap in laps if lap.get('LapTime') is not None and not pd.isna(lap.get('LapTime'))), default=None)),
                    "tyre_life_start": _normalize_position(first.get('TyreLife')),
                    "tyre_life_end": _normalize_position(last.get('TyreLife')),
                    "position_start": min(positions) if positions else None,
                    "position_end": max(positions) if positions else None,
                    "ended_with_pit_in": pd.notna(last.get('PitInTime')),
                    "started_from_pit_out": pd.notna(first.get('PitOutTime')),
                })

        info = driver_info.get(code.upper(), {})
        return {
            "driver": info.get("FullName") or code.upper(),
            "abbreviation": code.upper(),
            "team": info.get("TeamName"),
            "grid_position": _normalize_position(info.get("GridPosition")),
            "finish_position": _normalize_position(info.get("Position")),
            "stints": stints,
            "pit_stop_count": max(0, len(stints) - 1),
        }

    if driver_code:
        return {
            "event": session.event['EventName'],
            "session": session_type.upper(),
            "drivers": [_summarize_driver(driver_code)],
        }

    return {
        "event": session.event['EventName'],
        "session": session_type.upper(),
        "drivers": [_summarize_driver(code) for code in session.drivers],
    }


def get_driver_weekend_overview(round_number: int, driver_name: str) -> dict:
    """
    High-level weekend overview for a driver: quali, finish, teammate, strategy,
    nearby rivals, and SC/VSC impact when available.
    """
    matched = _resolve_driver(driver_name)
    if matched is None:
        raise ValueError(f"Driver not found: {driver_name!r}. Try surname or 3-letter code.")

    code = matched["code"] or matched["driver_id"].upper()
    qualifying = get_qualifying_results(round_number)
    race = get_race_results(round_number)

    quali_results = qualifying.get("results", [])
    race_results = race.get("results", [])
    driver_quali = next((r for r in quali_results if r.get("code", "").upper() == code.upper()), None)
    driver_race = next((r for r in race_results if r.get("code", "").upper() == code.upper()), None)

    if driver_race is None and driver_quali is None:
        raise ValueError(f"No weekend data found for {matched['full_name']} in round {round_number}.")

    teammate_quali = None
    teammate_race = None
    if matched.get("team"):
        teammate_quali = next(
            (r for r in quali_results if r.get("team") == matched["team"] and r.get("code", "").upper() != code.upper()),
            None,
        )
        teammate_race = next(
            (r for r in race_results if r.get("team") == matched["team"] and r.get("code", "").upper() != code.upper()),
            None,
        )

    strategy_summary = None
    try:
        strategy = get_driver_strategy(round_number, 'R', code)
        strategy_summary = strategy["drivers"][0] if strategy.get("drivers") else None
    except Exception:
        strategy_summary = None

    safety_car_summary = None
    try:
        sc = get_safety_car_periods(round_number, 'R')
        driver_number = None
        try:
            session_results = get_session_results(round_number, 'R')
            driver_meta = next((r for r in session_results.get("results", []) if r.get("abbreviation", "").upper() == code.upper()), None)
            driver_number = driver_meta.get("driver_number") if driver_meta else None
        except Exception:
            driver_number = None

        impacted_before = []
        impacted_during = []
        for period in sc.get("periods", []):
            before = [p for p in period.get("pitted_just_before", []) if p.get("driver", "").upper() == code.upper()]
            during = [p for p in period.get("pitted_during", []) if p.get("driver", "").upper() == code.upper()]
            if before:
                impacted_before.append({
                    "type": period.get("type"),
                    "lap": period.get("deployed_on_lap"),
                    "seconds_before": before[0].get("seconds_before_sc"),
                })
            if during:
                impacted_during.append({
                    "type": period.get("type"),
                    "lap": period.get("deployed_on_lap"),
                })

        safety_car_summary = {
            "sc_count": sc.get("sc_count", 0),
            "vsc_count": sc.get("vsc_count", 0),
            "pitted_just_before_sc": impacted_before,
            "pitted_during_sc": impacted_during,
        }
    except Exception:
        safety_car_summary = None

    nearby_rivals = []
    if driver_race and driver_race.get("position") is not None:
        pos = driver_race["position"]
        nearby_rivals = [
            r for r in race_results
            if r.get("position") is not None
            and r.get("code", "").upper() != code.upper()
            and abs(r["position"] - pos) <= 2
        ]
        nearby_rivals.sort(key=lambda r: (abs(r["position"] - pos), r["position"]))

    pit_stops = []
    if strategy_summary:
        for stint in strategy_summary.get("stints", [])[1:]:
            pit_stops.append({
                "pit_window_after_lap": max((stint.get("start_lap") or 1) - 1, 0),
                "new_compound": stint.get("compound"),
                "fresh_tyre": stint.get("fresh_tyre"),
            })

    grid_position = None
    if driver_quali and driver_quali.get("position") is not None:
        grid_position = driver_quali["position"]
    elif driver_race and driver_race.get("position") is not None:
        try:
            session_results = get_session_results(round_number, 'R')
            meta = next((r for r in session_results.get("results", []) if r.get("abbreviation", "").upper() == code.upper()), None)
            grid_position = meta.get("grid_position") if meta else None
        except Exception:
            grid_position = None

    energy_management = None
    preferred_session = 'Q' if driver_quali else 'R'
    try:
        energy_management = analyze_energy_management(round_number, preferred_session, code)
    except Exception:
        energy_management = None

    openf1_qualifying_radio = None
    if driver_quali:
        try:
            from openf1 import get_team_radio
            openf1_qualifying_radio = get_team_radio(round_number, 'Q', code, limit=6)
        except Exception:
            openf1_qualifying_radio = None

    openf1_race_intervals = None
    openf1_race_positions = None
    openf1_race_radio = None
    if driver_race:
        try:
            from openf1 import get_intervals
            openf1_race_intervals = get_intervals(round_number, code, limit=20)
        except Exception:
            openf1_race_intervals = None
        try:
            from openf1 import get_live_position_timeline
            openf1_race_positions = get_live_position_timeline(round_number, 'R', code, limit=30)
        except Exception:
            openf1_race_positions = None
        try:
            from openf1 import get_team_radio
            openf1_race_radio = get_team_radio(round_number, 'R', code, limit=8)
        except Exception:
            openf1_race_radio = None

    return {
        "driver": matched["full_name"],
        "code": code.upper(),
        "team": matched.get("team"),
        "event": race.get("race_name") or qualifying.get("race_name"),
        "round": round_number,
        "qualifying": {
            "position": driver_quali.get("position") if driver_quali else None,
            "q1": driver_quali.get("q1") if driver_quali else None,
            "q2": driver_quali.get("q2") if driver_quali else None,
            "q3": driver_quali.get("q3") if driver_quali else None,
        },
        "race": {
            "grid_position": grid_position,
            "finish_position": driver_race.get("position") if driver_race else None,
            "points": driver_race.get("points") if driver_race else None,
            "status": driver_race.get("status") if driver_race else None,
            "fastest_lap": driver_race.get("fastest_lap") if driver_race else None,
        },
        "pit_stops": pit_stops,
        "strategy": strategy_summary,
        "energy_management": energy_management,
        "safety_car_impact": safety_car_summary,
        "openf1": {
            "qualifying_radio": openf1_qualifying_radio,
            "race_intervals": openf1_race_intervals,
            "race_positions": openf1_race_positions,
            "race_radio": openf1_race_radio,
        },
        "teammate": {
            "name": teammate_race.get("driver") if teammate_race else teammate_quali.get("driver") if teammate_quali else None,
            "qualifying_position": teammate_quali.get("position") if teammate_quali else None,
            "finish_position": teammate_race.get("position") if teammate_race else None,
            "status": teammate_race.get("status") if teammate_race else None,
        },
        "nearby_rivals": [
            {
                "position": r.get("position"),
                "driver": r.get("driver"),
                "code": r.get("code"),
                "team": r.get("team"),
                "status": r.get("status"),
            }
            for r in nearby_rivals
        ],
    }


def get_driver_race_story(round_number: int, driver_name: str) -> dict:
    """
    Narrative-ready race overview for one driver with key race events and contextual comparisons.
    """
    overview = get_driver_weekend_overview(round_number, driver_name)
    code = overview["code"]

    race_control = None
    try:
        session_results = get_session_results(round_number, 'R')
        driver_meta = next((r for r in session_results.get("results", []) if r.get("abbreviation", "").upper() == code.upper()), None)
        driver_number = driver_meta.get("driver_number") if driver_meta else None
        category = driver_number if driver_number else code.upper()
        race_control = get_race_control_messages(round_number, 'R', category=category, limit=20)
    except Exception:
        race_control = None

    summary_points = []
    race = overview.get("race", {})
    quali = overview.get("qualifying", {})

    if quali.get("position") is not None and race.get("finish_position") is not None:
        delta = quali["position"] - race["finish_position"]
        if delta > 0:
            summary_points.append(f"Gained {delta} place(s) from qualifying to the finish.")
        elif delta < 0:
            summary_points.append(f"Lost {abs(delta)} place(s) from qualifying to the finish.")
        else:
            summary_points.append("Finished where they broadly started.")

    if overview.get("pit_stops"):
        stop_text = ", ".join(
            f"after lap {p['pit_window_after_lap']} for {p['new_compound']}"
            for p in overview["pit_stops"]
        )
        summary_points.append(f"Pit strategy: {stop_text}.")

    sc = overview.get("safety_car_impact")
    if sc:
        if sc.get("pitted_during_sc"):
            periods = ", ".join(
                f"{p['type']} on lap {p['lap']}" for p in sc["pitted_during_sc"]
            )
            summary_points.append(f"Pitted under neutralisation: {periods}.")
        elif sc.get("pitted_just_before_sc"):
            periods = ", ".join(
                f"{p['type']} on lap {p['lap']} ({p['seconds_before']}s before)"
                for p in sc["pitted_just_before_sc"]
            )
            summary_points.append(f"Potentially unlucky timing before neutralisation: {periods}.")
        elif sc.get("sc_count", 0) == 0 and sc.get("vsc_count", 0) == 0:
            summary_points.append("No Safety Car or VSC interruptions affected the race.")

    energy = overview.get("energy_management")
    if energy:
        if energy.get("drivers"):
            driver_energy = energy["drivers"][0]
            clipping = driver_energy.get("possible_clipping_windows") or []
            lico = driver_energy.get("likely_lift_and_coast_events") or []
            if clipping:
                first = clipping[0]
                summary_points.append(
                    f"Possible energy limitation: late-straight clipping signal from {first.get('start_distance_m')}m to {first.get('end_distance_m')}m."
                )
            if lico:
                summary_points.append("There are telemetry signs of lift-and-coast style energy management on the representative lap.")

    teammate = overview.get("teammate", {})
    if teammate.get("name") and teammate.get("finish_position") is not None and race.get("finish_position") is not None:
        gap = teammate["finish_position"] - race["finish_position"]
        if gap > 0:
            summary_points.append(f"Finished ahead of teammate {teammate['name']}.")
        elif gap < 0:
            summary_points.append(f"Finished behind teammate {teammate['name']}.")
        else:
            summary_points.append(f"Finished level with teammate {teammate['name']} on classification position.")

    control_highlights = []
    if race_control and race_control.get("messages"):
        for message in race_control["messages"][:5]:
            text = message.get("message")
            if text:
                control_highlights.append({
                    "lap": message.get("lap"),
                    "category": message.get("category"),
                    "message": text,
                })

    rivalry_story = []
    for rival in overview.get("nearby_rivals", [])[:3]:
        rivalry_story.append(
            f"Finished near {rival['driver']} ({rival['team']}) in P{rival['position']}."
        )

    openf1 = overview.get("openf1") or {}
    radio_highlights = []
    race_radio = (openf1.get("race_radio") or {}).get("messages") or []
    for message in race_radio[:3]:
        url = message.get("recording_url")
        if url:
            radio_highlights.append({
                "date": message.get("date"),
                "recording_url": url,
            })

    interval_summary = None
    intervals = (openf1.get("race_intervals") or {}).get("intervals") or []
    if intervals:
        interval_summary = _summarize_openf1_intervals(intervals)
        if interval_summary:
            trend = interval_summary.get("trend")
            min_gap = interval_summary.get("min_gap_to_leader_s")
            if trend == "closing" and min_gap is not None:
                summary_points.append(
                    f"Race-shape signal: they closed to roughly +{min_gap:.1f}s to the leader at best."
                )
            elif trend == "dropping_back":
                latest_gap = interval_summary.get("latest_gap_to_leader_s")
                if latest_gap is not None:
                    summary_points.append(
                        f"Race-shape signal: their gap drifted out to about +{latest_gap:.1f}s to the leader."
                    )

    position_timeline_summary = None
    positions = (openf1.get("race_positions") or {}).get("positions") or []
    if positions:
        first_pos = positions[-1].get("position")
        latest_pos = positions[0].get("position")
        position_timeline_summary = {
            "latest_position": latest_pos,
            "earliest_sample_position": first_pos,
            "sample_count": len(positions),
        }

    return {
        "driver": overview["driver"],
        "code": overview["code"],
        "team": overview["team"],
        "event": overview["event"],
        "round": round_number,
        "qualifying": overview["qualifying"],
        "race": overview["race"],
        "pit_stops": overview["pit_stops"],
        "strategy": overview["strategy"],
        "safety_car_impact": overview["safety_car_impact"],
        "teammate": overview["teammate"],
        "nearby_rivals": overview["nearby_rivals"],
        "race_control_highlights": control_highlights,
        "radio_highlights": radio_highlights,
        "interval_summary": interval_summary,
        "position_timeline_summary": position_timeline_summary,
        "story_points": summary_points,
        "rivalry_story": rivalry_story,
    }


def get_team_weekend_overview(round_number: int, team_name: str) -> dict:
    """
    High-level weekend overview for a team across both drivers.
    """
    resolved_team = _resolve_team(team_name)
    if resolved_team is None:
        raise ValueError(f"Team not found: {team_name!r}. Try the current constructor name.")

    team_drivers = [d for d in get_drivers() if d.get("team") == resolved_team]
    if not team_drivers:
        raise ValueError(f"No current-season drivers found for team {resolved_team!r}.")

    qualifying = get_qualifying_results(round_number)
    race = get_race_results(round_number)
    quali_results = qualifying.get("results", [])
    race_results = race.get("results", [])

    driver_summaries = []
    for driver in team_drivers:
        code = driver.get("code", "").upper()
        quali_row = next((r for r in quali_results if r.get("code", "").upper() == code), None)
        race_row = next((r for r in race_results if r.get("code", "").upper() == code), None)

        strategy = None
        try:
            strat = get_driver_strategy(round_number, 'R', code)
            strategy = strat["drivers"][0] if strat.get("drivers") else None
        except Exception:
            strategy = None

        pit_stops = []
        if strategy:
            for stint in strategy.get("stints", [])[1:]:
                pit_stops.append({
                    "pit_window_after_lap": max((stint.get("start_lap") or 1) - 1, 0),
                    "new_compound": stint.get("compound"),
                })

        driver_summaries.append({
            "driver": driver["full_name"],
            "code": code,
            "qualifying_position": quali_row.get("position") if quali_row else None,
            "finish_position": race_row.get("position") if race_row else None,
            "points": race_row.get("points") if race_row else None,
            "status": race_row.get("status") if race_row else None,
            "fastest_lap": race_row.get("fastest_lap") if race_row else None,
            "positions_gained": (
                (quali_row.get("position") - race_row.get("position"))
                if quali_row and race_row and quali_row.get("position") is not None and race_row.get("position") is not None
                else None
            ),
            "pit_stops": pit_stops,
            "strategy": strategy,
        })

    sorted_finishers = sorted(
        [d for d in driver_summaries if d.get("finish_position") is not None],
        key=lambda d: d["finish_position"],
    )
    lead_driver = sorted_finishers[0]["driver"] if sorted_finishers else None
    total_points = round(sum(d.get("points", 0) or 0 for d in driver_summaries), 1)

    summary_points = []
    finish_positions = [d["finish_position"] for d in driver_summaries if d.get("finish_position") is not None]
    if len(finish_positions) == 2:
        summary_points.append(
            f"{resolved_team} finished P{finish_positions[0]} and P{finish_positions[1]}."
        )
    if total_points:
        summary_points.append(f"Scored {total_points} point(s) across both cars.")

    gains = [d for d in driver_summaries if d.get("positions_gained") is not None]
    if gains:
        biggest_gain = max(gains, key=lambda d: d["positions_gained"])
        if biggest_gain["positions_gained"] > 0:
            summary_points.append(
                f"{biggest_gain['driver']} made the most progress, gaining {biggest_gain['positions_gained']} place(s)."
            )

    return {
        "team": resolved_team,
        "event": race.get("race_name") or qualifying.get("race_name"),
        "round": round_number,
        "total_points": total_points,
        "lead_driver": lead_driver,
        "drivers": driver_summaries,
        "summary_points": summary_points,
    }


def get_race_report(round_number: int) -> dict:
    """
    Whole-race recap independent of driver/team.
    """
    qualifying = get_qualifying_results(round_number)
    race = get_race_results(round_number)
    results = race.get("results", [])
    quali_results = qualifying.get("results", [])
    openf1_intervals = {}
    safety_car = None
    try:
        safety_car = get_safety_car_periods(round_number, 'R')
    except Exception:
        safety_car = None
    try:
        from openf1 import get_intervals
        for row in results[:5]:
            code = row.get("code")
            if not code:
                continue
            interval_payload = get_intervals(round_number, code, limit=20)
            summary = _summarize_openf1_intervals(interval_payload.get("intervals") or [])
            if summary:
                openf1_intervals[code.upper()] = summary
    except Exception:
        openf1_intervals = {}

    by_code_quali = {row.get("code", "").upper(): row for row in quali_results}
    finishers = [row for row in results if row.get("position") is not None]
    finishers.sort(key=lambda row: row["position"])

    podium = finishers[:3]
    dnfs = [row for row in results if row.get("status") and row.get("status") != "Finished"]

    movers = []
    for row in finishers:
        code = row.get("code", "").upper()
        quali = by_code_quali.get(code)
        if quali and quali.get("position") is not None:
            delta = quali["position"] - row["position"]
            movers.append({
                "driver": row.get("driver"),
                "code": code,
                "team": row.get("team"),
                "qualified": quali["position"],
                "finished": row["position"],
                "positions_gained": delta,
            })
    biggest_gainer = max(movers, key=lambda item: item["positions_gained"], default=None)
    biggest_loser = min(movers, key=lambda item: item["positions_gained"], default=None)

    points_scoring = [row for row in finishers if (row.get("points") or 0) > 0]
    fastest_lap = next((row for row in results if row.get("fastest_lap")), None)

    summary_points = []
    if podium:
        summary_points.append(
            "Podium: " + ", ".join(f"P{idx + 1} {row['driver']}" for idx, row in enumerate(podium)) + "."
        )
        podium_interval_bits = []
        for row in podium:
            summary = openf1_intervals.get((row.get("code") or "").upper())
            if not summary:
                continue
            latest_gap = summary.get("latest_gap_to_leader")
            if row.get("position") == 1:
                podium_interval_bits.append(f"{row['driver']} controlled the lead")
            elif latest_gap:
                podium_interval_bits.append(f"{row['driver']} finished at {latest_gap}")
        if podium_interval_bits:
            summary_points.append("Race gaps: " + ", ".join(podium_interval_bits) + ".")
    if biggest_gainer and biggest_gainer["positions_gained"] > 0:
        summary_points.append(
            f"Biggest gainer: {biggest_gainer['driver']} gained {biggest_gainer['positions_gained']} place(s)."
        )
    if fastest_lap:
        summary_points.append(f"Fastest lap went to {fastest_lap['driver']}.")
    if safety_car:
        total_neutralisations = safety_car.get("sc_count", 0) + safety_car.get("vsc_count", 0)
        if total_neutralisations == 0:
            summary_points.append("No SC or VSC interruptions.")
        else:
            summary_points.append(
                f"Neutralisations: {safety_car.get('sc_count', 0)} SC and {safety_car.get('vsc_count', 0)} VSC period(s)."
            )

    return {
        "event": race.get("race_name") or qualifying.get("race_name"),
        "round": round_number,
        "circuit": race.get("circuit"),
        "date": race.get("date"),
        "podium": [
            {
                "position": row.get("position"),
                "driver": row.get("driver"),
                "code": row.get("code"),
                "team": row.get("team"),
            }
            for row in podium
        ],
        "fastest_lap": fastest_lap,
        "points_scoring_finishers": points_scoring,
        "openf1_intervals": openf1_intervals,
        "dnfs": [
            {
                "driver": row.get("driver"),
                "code": row.get("code"),
                "team": row.get("team"),
                "status": row.get("status"),
            }
            for row in dnfs
        ],
        "biggest_gainer": biggest_gainer,
        "biggest_loser": biggest_loser,
        "safety_car": safety_car,
        "summary_points": summary_points,
    }


def get_qualifying_progression(round_number: int) -> dict:
    """
    Split qualifying into Q1/Q2/Q3 and summarize progression and knockout state.
    """
    session = _load_session(round_number, 'Q', laps=True, telemetry=False, weather=False, messages=False)
    split = session.laps.split_qualifying_sessions()
    session_names = ['Q1', 'Q2', 'Q3']
    driver_info = _driver_lookup(session)
    by_driver = {}

    for index, laps in enumerate(split):
        segment_name = session_names[index]
        if laps is None:
            continue
        for code in session.drivers:
            driver_laps = _pick_driver(laps, code)
            if getattr(driver_laps, "empty", True):
                continue
            fastest = _pick_fastest_lap(driver_laps)
            if pd.isna(fastest['LapTime']):
                continue
            entry = by_driver.setdefault(code, {
                "driver": driver_info.get(code, {}).get("FullName") or code,
                "abbreviation": code,
                "team": driver_info.get(code, {}).get("TeamName"),
            })
            entry[segment_name.lower()] = {
                "lap_time": _fmt_td(fastest['LapTime']),
                "lap_time_s": round(fastest['LapTime'].total_seconds(), 3),
                "compound": str(fastest['Compound']) if pd.notna(fastest.get('Compound')) else None,
                "lap_number": int(fastest['LapNumber']) if pd.notna(fastest.get('LapNumber')) else None,
            }

    for entry in by_driver.values():
        q1 = entry.get("q1", {}).get("lap_time_s")
        q2 = entry.get("q2", {}).get("lap_time_s")
        q3 = entry.get("q3", {}).get("lap_time_s")
        entry["made_q2"] = q2 is not None
        entry["made_q3"] = q3 is not None
        entry["improvement_q1_to_q2_s"] = round(q2 - q1, 3) if q1 is not None and q2 is not None else None
        entry["improvement_q2_to_q3_s"] = round(q3 - q2, 3) if q2 is not None and q3 is not None else None
        entry["best_segment"] = min(
            ((segment, data["lap_time_s"]) for segment, data in entry.items() if segment in ("q1", "q2", "q3")),
            key=lambda item: item[1],
            default=(None, None),
        )[0]

    return {
        "event": session.event['EventName'],
        "session": "Q",
        "drivers": sorted(
            by_driver.values(),
            key=lambda d: (
                d.get("q3", {}).get("lap_time_s") is None,
                d.get("q3", {}).get("lap_time_s", float("inf")),
                d.get("q2", {}).get("lap_time_s", float("inf")),
                d.get("q1", {}).get("lap_time_s", float("inf")),
            ),
        ),
    }


def get_clean_pace_summary(round_number: int, session_type: str,
                           driver_codes: list[str] | None = None,
                           green_only: bool = True,
                           limit: int = 10) -> dict:
    """
    Compare representative clean laps only, excluding deleted, inaccurate and pit laps.
    """
    session = _load_session(
        round_number,
        session_type,
        laps=True,
        telemetry=False,
        weather=False,
        messages=_session_needs_race_control_messages(session_type),
    )
    driver_info = _driver_lookup(session)
    drivers = [code.upper() for code in driver_codes] if driver_codes else [str(code).upper() for code in session.drivers]
    summaries = []

    for code in drivers:
        laps = _pick_driver(session.laps, code)
        if getattr(laps, "empty", True):
            continue

        for method_name in ("pick_accurate", "pick_not_deleted", "pick_wo_box"):
            method = getattr(laps, method_name, None)
            if callable(method):
                laps = method()

        if green_only:
            pick_track_status = getattr(laps, "pick_track_status", None)
            if callable(pick_track_status):
                laps = pick_track_status('1')

        pick_quicklaps = getattr(laps, "pick_quicklaps", None)
        if callable(pick_quicklaps):
            laps = pick_quicklaps()

        if getattr(laps, "empty", True):
            continue

        lap_times = laps['LapTime'].dropna()
        if lap_times.empty:
            continue
        rep_laps = _pick_representative_laps(laps.sort_values('LapTime'), limit)
        compounds = rep_laps['Compound'].dropna().astype(str).value_counts().to_dict() if 'Compound' in rep_laps else {}
        summaries.append({
            "driver": driver_info.get(code, {}).get("FullName") or code,
            "abbreviation": code,
            "team": driver_info.get(code, {}).get("TeamName"),
            "lap_count": int(len(laps)),
            "best_lap_time": _fmt_td(lap_times.min()),
            "best_lap_time_s": round(lap_times.min().total_seconds(), 3),
            "avg_lap_time_s": round(lap_times.dt.total_seconds().mean(), 3),
            "median_lap_time_s": round(lap_times.dt.total_seconds().median(), 3),
            "lap_time_range_s": round(lap_times.dt.total_seconds().max() - lap_times.dt.total_seconds().min(), 3),
            "compounds": compounds,
            "sample_laps": [
                {
                    "lap_number": int(lap['LapNumber']) if pd.notna(lap.get('LapNumber')) else None,
                    "lap_time": _fmt_td(lap['LapTime']),
                    "compound": str(lap['Compound']) if pd.notna(lap.get('Compound')) else None,
                    "tyre_life": _normalize_position(lap.get('TyreLife')),
                    "track_status": str(lap.get('TrackStatus')) if pd.notna(lap.get('TrackStatus')) else None,
                }
                for _, lap in rep_laps.iterrows()
            ],
        })

    summaries.sort(key=lambda item: item['best_lap_time_s'])
    for idx, item in enumerate(summaries, start=1):
        item["rank"] = idx
        if idx > 1:
            item["gap_to_fastest_s"] = round(item['best_lap_time_s'] - summaries[0]['best_lap_time_s'], 3)
        else:
            item["gap_to_fastest_s"] = 0.0

    return {
        "event": session.event['EventName'],
        "session": session_type.upper(),
        "green_only": green_only,
        "drivers": summaries,
    }


def get_sector_comparison(round_number: int, session_type: str,
                          driver_a: str, driver_b: str) -> dict:
    """
    Head-to-head fastest-lap comparison between two drivers.
    Shows time gap per sector AND speed trap deltas (SpeedI1/I2/FL/ST).
    Positive gap_s = driver_a is SLOWER. Positive speed_delta = driver_a is FASTER.
    Answers: "why was Norris 0.3s faster than Leclerc in sector 2?"
    """
    session = _load_session(
        round_number,
        session_type,
        laps=True,
        telemetry=False,
        weather=False,
        messages=_session_needs_race_control_messages(session_type),
    )

    def _fastest(code: str):
        laps = _pick_driver(session.laps, code.upper())
        if laps.empty:
            raise ValueError(f"No session data for driver {code!r}")
        fastest = _pick_fastest_lap(laps)
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
    session = _load_session(
        round_number,
        session_type,
        laps=True,
        telemetry=True,
        weather=False,
        messages=_session_needs_race_control_messages(session_type),
    )

    driver_laps = _pick_driver(session.laps, driver_code.upper())
    if driver_laps.empty:
        raise ValueError(f"No data for driver {driver_code!r}")

    if lap_number is not None:
        matching = driver_laps[driver_laps['LapNumber'] == lap_number]
        if matching.empty:
            raise ValueError(f"Lap {lap_number} not found for {driver_code!r}")
        lap = matching.iloc[0]
    else:
        lap = _pick_fastest_lap(driver_laps)

    tel = lap.get_telemetry().add_distance()
    total_dist = float(tel['Distance'].max())

    INTERVAL_M = 100
    samples = []
    dist = 0.0
    while dist <= total_dist:
        idx = (tel['Distance'] - dist).abs().idxmin()
        row = tel.loc[idx]
        rpm = row.get('RPM')
        gear = row.get('nGear')
        drs = row.get('DRS')
        samples.append({
            "distance_m": int(dist),
            "speed_kph": round(float(row['Speed']), 1),
            "throttle_pct": round(float(row['Throttle']), 1),
            "brake": bool(row['Brake']),
            "gear": int(gear) if pd.notna(gear) else None,
            "rpm": int(rpm) if pd.notna(rpm) else None,
            "drs_open": int(drs) >= 10 if pd.notna(drs) else False,
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
    session = _load_session(
        round_number,
        session_type,
        laps=True,
        telemetry=True,
        weather=False,
        messages=_session_needs_race_control_messages(session_type),
    )

    def _get_lap(code: str, lap_num: int | None):
        laps = _pick_driver(session.laps, code.upper())
        if laps.empty:
            raise ValueError(f"No data for driver {code!r}")
        if lap_num is not None:
            matching = laps[laps['LapNumber'] == lap_num]
            if matching.empty:
                raise ValueError(f"Lap {lap_num} not found for {code!r}")
            return matching.iloc[0]
        return _pick_fastest_lap(laps)

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
        gear_a_raw = row_a.get('nGear')
        gear_b_raw = row_b.get('nGear')
        rpm_a_raw = row_a.get('RPM')
        rpm_b_raw = row_b.get('RPM')
        drs_a_raw = row_a.get('DRS')
        drs_b_raw = row_b.get('DRS')
        gear_a = int(gear_a_raw) if pd.notna(gear_a_raw) else None
        gear_b = int(gear_b_raw) if pd.notna(gear_b_raw) else None
        rpm_a = int(rpm_a_raw) if pd.notna(rpm_a_raw) else None
        rpm_b = int(rpm_b_raw) if pd.notna(rpm_b_raw) else None

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
            "gear_a": gear_a,
            "gear_b": gear_b,
            "delta_gear": (gear_a - gear_b) if gear_a is not None and gear_b is not None else None,
            "rpm_a": rpm_a,
            "rpm_b": rpm_b,
            "delta_rpm": (rpm_a - rpm_b) if rpm_a is not None and rpm_b is not None else None,
            "drs_a": int(drs_a_raw) >= 10 if pd.notna(drs_a_raw) else False,
            "drs_b": int(drs_b_raw) >= 10 if pd.notna(drs_b_raw) else False,
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


def analyze_energy_management(round_number: int, session_type: str,
                              driver_a: str,
                              driver_b: str | None = None,
                              lap_number_a: int | None = None,
                              lap_number_b: int | None = None) -> dict:
    """
    Analyze likely 2026-style energy management behavior.
    This does NOT measure ERS state directly. It infers likely lift-and-coast and
    possible late-straight clipping from FastF1 telemetry patterns.
    """
    knowledge = get_energy_2026_knowledge()

    if driver_b:
        comparison = get_telemetry_comparison(
            round_number, session_type, driver_a, driver_b, lap_number_a, lap_number_b
        )
        samples = comparison["comparison"]

        driver_a_samples = [{
            "distance_m": s["distance_m"],
            "speed_kph": s["speed_a"],
            "throttle_pct": s["throttle_a"],
            "brake": s["brake_a"],
            "gear": s["gear_a"],
            "rpm": s["rpm_a"],
            "drs_open": s["drs_a"],
        } for s in samples]
        driver_b_samples = [{
            "distance_m": s["distance_m"],
            "speed_kph": s["speed_b"],
            "throttle_pct": s["throttle_b"],
            "brake": s["brake_b"],
            "gear": s["gear_b"],
            "rpm": s["rpm_b"],
            "drs_open": s["drs_b"],
        } for s in samples]

        lico_a = _infer_lift_and_coast_samples(driver_a_samples)
        lico_b = _infer_lift_and_coast_samples(driver_b_samples)
        clip_a = _infer_clipping_windows(driver_a_samples)
        clip_b = _infer_clipping_windows(driver_b_samples)

        fade_candidates = []
        for sample in samples:
            if (
                (sample.get("throttle_a") or 0) >= 95
                and (sample.get("throttle_b") or 0) >= 95
                and not sample.get("brake_a")
                and not sample.get("brake_b")
                and abs((sample.get("delta_speed") or 0)) >= 8
            ):
                fade_candidates.append({
                    "distance_m": sample.get("distance_m"),
                    "delta_speed_kph": sample.get("delta_speed"),
                    "speed_a": sample.get("speed_a"),
                    "speed_b": sample.get("speed_b"),
                })

        strongest_fade = max(fade_candidates, key=lambda row: abs(row["delta_speed_kph"]), default=None)
        inferences = []
        if lico_a:
            inferences.append(f"{driver_a.upper()} shows likely lift-and-coast style early lifts before braking zones.")
        if lico_b:
            inferences.append(f"{driver_b.upper()} shows likely lift-and-coast style early lifts before braking zones.")
        if strongest_fade:
            slower = driver_a.upper() if strongest_fade["delta_speed_kph"] < 0 else driver_b.upper()
            inferences.append(
                f"Late-straight full-throttle speed fade is strongest around {strongest_fade['distance_m']}m, where {slower} is likely clipping earlier."
            )
        if not inferences:
            inferences.append("No strong energy-management signature stands out from the available telemetry window.")

        confidence = "medium" if strongest_fade or lico_a or lico_b else "low"
        harvest_inference = "indeterminate"
        if lico_a or lico_b:
            harvest_inference = "lift_and_coast_assisted_harvesting_likely"
        elif strongest_fade:
            harvest_inference = "deployment_taper_likely_but_harvest_type_indeterminate"
        return {
            "event": comparison["event"],
            "session": comparison["session"],
            "mode": "comparison",
            "knowledge": knowledge,
            "measured_channels": ["Speed", "RPM", "nGear", "Throttle", "Brake", "DRS"],
            "not_directly_measured": ["ERS state of charge", "deployment map", "harvest mode"],
            "drivers": [
                {
                    "driver": driver_a.upper(),
                    "lap_number": comparison["lap_number_a"],
                    "likely_lift_and_coast_events": lico_a[:5],
                    "possible_clipping_windows": clip_a[:5],
                },
                {
                    "driver": driver_b.upper(),
                    "lap_number": comparison["lap_number_b"],
                    "likely_lift_and_coast_events": lico_b[:5],
                    "possible_clipping_windows": clip_b[:5],
                },
            ],
            "comparative_signal": {
                "strongest_full_throttle_speed_fade": strongest_fade,
            },
            "harvesting_inference": harvest_inference,
            "inference_summary": inferences,
            "confidence": confidence,
        }

    telemetry = get_lap_telemetry(round_number, session_type, driver_a, lap_number_a)
    samples = telemetry["telemetry"]
    lico = _infer_lift_and_coast_samples(samples)
    clip = _infer_clipping_windows(samples)
    inferences = []
    if lico:
        inferences.append("There are likely lift-and-coast style early lifts before braking on this lap.")
    if clip:
        inferences.append("There are possible late-straight clipping windows where speed gain is muted despite sustained high throttle.")
    if not inferences:
        inferences.append("No strong lift-and-coast or clipping signature stands out on this lap from the available channels.")

    confidence = "medium" if lico or clip else "low"
    harvest_inference = "indeterminate"
    if lico:
        harvest_inference = "lift_and_coast_assisted_harvesting_likely"
    elif clip:
        harvest_inference = "deployment_taper_likely_but_harvest_type_indeterminate"
    return {
        "event": telemetry["event"],
        "session": telemetry["session"],
        "mode": "single_driver",
        "knowledge": knowledge,
        "measured_channels": ["Speed", "RPM", "nGear", "Throttle", "Brake", "DRS"],
        "not_directly_measured": ["ERS state of charge", "deployment map", "harvest mode"],
        "drivers": [
            {
                "driver": telemetry["driver"],
                "lap_number": telemetry["lap_number"],
                "likely_lift_and_coast_events": lico[:5],
                "possible_clipping_windows": clip[:5],
            }
        ],
        "harvesting_inference": harvest_inference,
        "inference_summary": inferences,
        "confidence": confidence,
    }


def _nearest_corner_label(round_number: int, distance_m: int | None) -> str | None:
    if distance_m is None:
        return None
    try:
        corners = get_circuit_corners(round_number)
    except Exception:
        return None
    valid_corners = [corner for corner in corners if corner.get("distance_m") is not None]
    if not valid_corners:
        return None
    nearest = min(valid_corners, key=lambda corner: abs(corner["distance_m"] - distance_m))
    label = f"Turn {nearest['number']}"
    if nearest.get("label"):
        label += nearest["label"]
    return label


def _get_comparable_qualifying_laps(round_number: int, driver_codes: list[str]):
    session = _load_session(round_number, 'Q', laps=True, telemetry=False, weather=False, messages=True)
    split = session.laps.split_qualifying_sessions()
    segments = [("Q3", split[2]), ("Q2", split[1]), ("Q1", split[0])]

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


def _summarize_telemetry_battle(samples: list[dict], faster_driver: str, driver_a: str, driver_b: str) -> dict | None:
    if not samples:
        return None

    faster_is_a = faster_driver == driver_a

    def sample_favors_faster(sample) -> bool:
        delta_speed = sample.get("delta_speed") or 0
        return (delta_speed > 0) if faster_is_a else (delta_speed < 0)

    speed_candidates = [s for s in samples if sample_favors_faster(s) and abs(s.get("delta_speed") or 0) >= 5]
    braking_candidates = [
        s for s in samples
        if sample_favors_faster(s)
        and (
            (faster_is_a and s.get("brake_b") and not s.get("brake_a"))
            or ((not faster_is_a) and s.get("brake_a") and not s.get("brake_b"))
        )
    ]
    min_speed_candidates = [
        s for s in samples
        if sample_favors_faster(s)
        and (
            ((s.get("throttle_a") or 0) < 40 and not s.get("brake_a"))
            or ((s.get("throttle_b") or 0) < 40 and not s.get("brake_b"))
        )
    ]
    traction_candidates = [
        s for s in samples
        if sample_favors_faster(s)
        and (
            ((s.get("throttle_a") or 0) >= 70 and not s.get("brake_a"))
            or ((s.get("throttle_b") or 0) >= 70 and not s.get("brake_b"))
        )
    ]

    strongest_speed = max(speed_candidates, key=lambda s: abs(s.get("delta_speed") or 0), default=None)
    strongest_braking = max(braking_candidates, key=lambda s: abs(s.get("delta_speed") or 0), default=None)
    strongest_min_speed = max(min_speed_candidates, key=lambda s: abs(s.get("delta_speed") or 0), default=None)
    strongest_traction = max(traction_candidates, key=lambda s: abs(s.get("delta_speed") or 0), default=None)

    best = None
    for cause_type, sample in (
        ("straight_line_speed", strongest_speed),
        ("braking", strongest_braking),
        ("minimum_speed", strongest_min_speed),
        ("traction", strongest_traction),
    ):
        if sample is None:
            continue
        magnitude = abs(sample.get("delta_speed") or 0)
        if best is None or magnitude > best["magnitude"]:
            best = {"cause_type": cause_type, "sample": sample, "magnitude": magnitude}

    if not best:
        return None

    sample = best["sample"]
    return {
        "cause_type": best["cause_type"],
        "distance_m": sample.get("distance_m"),
        "delta_speed_kph": sample.get("delta_speed"),
        "throttle_a": sample.get("throttle_a"),
        "throttle_b": sample.get("throttle_b"),
        "brake_a": sample.get("brake_a"),
        "brake_b": sample.get("brake_b"),
        "gear_a": sample.get("gear_a"),
        "gear_b": sample.get("gear_b"),
    }


def _downsample_speed_trace(samples: list[dict], *, step: int = 200) -> list[dict]:
    if not samples:
        return []
    reduced = []
    last_distance = None
    for sample in samples:
        distance = sample.get("distance_m")
        if distance is None:
            continue
        if last_distance is None or distance - last_distance >= step:
            reduced.append({
                "distance_m": distance,
                "speed_a": sample.get("speed_a"),
                "speed_b": sample.get("speed_b"),
                "delta_speed": sample.get("delta_speed"),
            })
            last_distance = distance
    if reduced and reduced[-1]["distance_m"] != samples[-1].get("distance_m"):
        final = samples[-1]
        reduced.append({
            "distance_m": final.get("distance_m"),
            "speed_a": final.get("speed_a"),
            "speed_b": final.get("speed_b"),
            "delta_speed": final.get("delta_speed"),
        })
    return reduced


def _summarize_openf1_intervals(intervals: list[dict]) -> dict | None:
    if not intervals:
        return None

    def _parse_gap(value):
        if value is None:
            return None
        text = str(value).strip().replace("+", "")
        try:
            return float(text)
        except ValueError:
            return None

    ordered = list(reversed(intervals))
    parsed = [_parse_gap(row.get("gap_to_leader")) for row in ordered]
    valid = [value for value in parsed if value is not None]
    if not valid:
        latest = intervals[0]
        return {
            "latest_gap_to_leader": latest.get("gap_to_leader"),
            "latest_interval": latest.get("interval"),
            "sample_count": len(intervals),
        }

    earliest_gap = valid[0]
    latest_gap = valid[-1]
    min_gap = min(valid)
    max_gap = max(valid)
    trend = "stable"
    if latest_gap < earliest_gap - 0.75:
        trend = "closing"
    elif latest_gap > earliest_gap + 0.75:
        trend = "dropping_back"

    return {
        "latest_gap_to_leader": intervals[0].get("gap_to_leader"),
        "latest_interval": intervals[0].get("interval"),
        "sample_count": len(intervals),
        "earliest_gap_to_leader_s": round(earliest_gap, 3),
        "latest_gap_to_leader_s": round(latest_gap, 3),
        "min_gap_to_leader_s": round(min_gap, 3),
        "max_gap_to_leader_s": round(max_gap, 3),
        "trend": trend,
    }


def analyze_qualifying_battle(round_number: int, driver_a: str, driver_b: str) -> dict:
    """
    Backend-derived causal summary for a qualifying battle.
    Explains where the time was gained and the most likely mechanism.
    """
    session, compared_segment, chosen_laps = _get_comparable_qualifying_laps(round_number, [driver_a, driver_b])
    lap_a = chosen_laps[driver_a.upper()]
    lap_b = chosen_laps[driver_b.upper()]

    def _s(td) -> float | None:
        return round(td.total_seconds(), 3) if pd.notna(td) else None

    def _gap(a, b) -> float | None:
        return round(a - b, 3) if a is not None and b is not None else None

    def _spd(lap, key) -> float | None:
        value = lap.get(key)
        return round(float(value), 1) if value is not None and pd.notna(value) else None

    sector = {
        "event": session.event['EventName'],
        "session": "Q",
        "compared_segment": compared_segment,
        "driver_a": driver_a.upper(),
        "driver_b": driver_b.upper(),
        "lap_time_a": _fmt_td(lap_a['LapTime']),
        "lap_time_b": _fmt_td(lap_b['LapTime']),
        "lap_number_a": int(lap_a['LapNumber']) if pd.notna(lap_a.get('LapNumber')) else None,
        "lap_number_b": int(lap_b['LapNumber']) if pd.notna(lap_b.get('LapNumber')) else None,
        "overall_gap_s": _gap(_s(lap_a['LapTime']), _s(lap_b['LapTime'])),
        "sector1": {
            "time_a": _fmt_td(lap_a['Sector1Time']),
            "time_b": _fmt_td(lap_b['Sector1Time']),
            "gap_s": _gap(_s(lap_a['Sector1Time']), _s(lap_b['Sector1Time'])),
            "speed_i1_a": _spd(lap_a, 'SpeedI1'),
            "speed_i1_b": _spd(lap_b, 'SpeedI1'),
            "speed_i1_delta": _gap(_spd(lap_a, 'SpeedI1'), _spd(lap_b, 'SpeedI1')),
        },
        "sector2": {
            "time_a": _fmt_td(lap_a['Sector2Time']),
            "time_b": _fmt_td(lap_b['Sector2Time']),
            "gap_s": _gap(_s(lap_a['Sector2Time']), _s(lap_b['Sector2Time'])),
            "speed_i2_a": _spd(lap_a, 'SpeedI2'),
            "speed_i2_b": _spd(lap_b, 'SpeedI2'),
            "speed_i2_delta": _gap(_spd(lap_a, 'SpeedI2'), _spd(lap_b, 'SpeedI2')),
        },
        "sector3": {
            "time_a": _fmt_td(lap_a['Sector3Time']),
            "time_b": _fmt_td(lap_b['Sector3Time']),
            "gap_s": _gap(_s(lap_a['Sector3Time']), _s(lap_b['Sector3Time'])),
            "speed_fl_a": _spd(lap_a, 'SpeedFL'),
            "speed_fl_b": _spd(lap_b, 'SpeedFL'),
            "speed_fl_delta": _gap(_spd(lap_a, 'SpeedFL'), _spd(lap_b, 'SpeedFL')),
        },
        "speed_trap_a": _spd(lap_a, 'SpeedST'),
        "speed_trap_b": _spd(lap_b, 'SpeedST'),
        "speed_trap_delta": _gap(_spd(lap_a, 'SpeedST'), _spd(lap_b, 'SpeedST')),
    }
    telemetry = None
    energy = None
    caveats = []
    try:
        telemetry = get_telemetry_comparison(
            round_number,
            'Q',
            driver_a,
            driver_b,
            lap_number_a=sector["lap_number_a"],
            lap_number_b=sector["lap_number_b"],
        )
    except Exception as exc:
        caveats.append(f"Telemetry comparison unavailable: {exc}")
    try:
        energy = analyze_energy_management(
            round_number,
            'Q',
            driver_a,
            driver_b,
            lap_number_a=sector["lap_number_a"],
            lap_number_b=sector["lap_number_b"],
        )
    except Exception as exc:
        caveats.append(f"Energy analysis unavailable: {exc}")

    overall_gap = sector.get("overall_gap_s")
    if overall_gap is None:
        raise ValueError("Overall qualifying gap is unavailable.")

    driver_a_code = sector["driver_a"]
    driver_b_code = sector["driver_b"]
    faster_driver = driver_a_code if overall_gap < 0 else driver_b_code
    slower_driver = driver_b_code if faster_driver == driver_a_code else driver_a_code

    sector_rows = [
        ("Sector 1", sector.get("sector1", {}).get("gap_s")),
        ("Sector 2", sector.get("sector2", {}).get("gap_s")),
        ("Sector 3", sector.get("sector3", {}).get("gap_s")),
    ]
    decisive_sector, decisive_sector_gap = max(
        sector_rows,
        key=lambda item: abs(item[1]) if item[1] is not None else -1,
    )

    comparison_samples = telemetry.get("comparison", []) if telemetry else []
    telemetry_summary = _summarize_telemetry_battle(comparison_samples, faster_driver, driver_a_code, driver_b_code)
    strongest_sample = None
    decisive_distance = telemetry_summary.get("distance_m") if telemetry_summary else None

    cause_type = "mixed"
    cause_explanation = "The gap comes from a blend of smaller advantages rather than one clean mechanism."

    if telemetry_summary:
        cause_type = telemetry_summary["cause_type"]
        strongest_sample = telemetry_summary
        if cause_type == "straight_line_speed":
            cause_explanation = (
                f"{faster_driver} is still carrying more speed at full throttle late in the straight, "
                f"so the lap-time gain opens before the braking zone."
            )
        elif cause_type == "braking":
            earlier_braker = driver_b_code if faster_driver == driver_a_code else driver_a_code
            cause_explanation = (
                f"The main gain comes on corner entry: {earlier_braker} is already on the brake while "
                f"{faster_driver} is still carrying speed into the zone."
            )
        elif cause_type == "minimum_speed":
            cause_explanation = (
                f"The gap looks like minimum-speed performance through the direction change, with {faster_driver} "
                f"giving up less speed mid-corner and exiting with more momentum."
            )
        elif cause_type == "traction":
            cause_explanation = (
                f"The gain looks like traction on exit: {faster_driver} gets back to speed earlier and carries "
                f"that advantage down the following section."
            )

    energy_relevant = False
    energy_reason = None
    energy_context_explanation = None
    strongest_fade = ((energy.get("comparative_signal") or {}) if energy else {}).get("strongest_full_throttle_speed_fade")
    if strongest_fade:
        delta_speed = strongest_fade.get("delta_speed_kph") or 0
        faded_driver = driver_a_code if delta_speed < 0 else driver_b_code
        if faded_driver == slower_driver:
            energy_relevant = True
            decisive_distance = strongest_fade.get("distance_m") or decisive_distance
            energy_reason = (
                f"{slower_driver} shows the strongest late-straight full-throttle speed fade around "
                f"{strongest_fade.get('distance_m')}m, which is consistent with clipping or running out of deployment earlier."
            )
            energy_context_explanation = (
                "Under the 2026 rules the electrical contribution is much larger, so if one car reaches the taper in deployment earlier, "
                "it can remain flat-out but stop accelerating as hard late on the straight."
            )
            if cause_type == "straight_line_speed":
                cause_type = "straight_line_speed_energy_limited"

    decisive_corner = _nearest_corner_label(round_number, decisive_distance)

    strongest_evidence = [
        f"Overall qualifying gap: {abs(overall_gap):.3f}s in favour of {faster_driver}.",
    ]
    if decisive_sector_gap is not None:
        strongest_evidence.append(f"{decisive_sector} accounts for {abs(decisive_sector_gap):.3f}s of the gap.")
    if strongest_sample and strongest_sample.get("delta_speed") is not None:
        strongest_evidence.append(
            f"Strongest speed separation is {abs(strongest_sample['delta_speed']):.1f} kph around {strongest_sample.get('distance_m')}m."
        )
    if energy_reason:
        strongest_evidence.append(energy_reason)
    if energy_context_explanation:
        strongest_evidence.append(energy_context_explanation)

    zone_summary = None
    if telemetry_summary:
        location_bits = []
        if decisive_sector:
            location_bits.append(decisive_sector)
        if decisive_corner:
            location_bits.append(f"near {decisive_corner}")
        elif decisive_distance is not None:
            location_bits.append(f"around {decisive_distance}m")
        zone_summary = (
            f"{' '.join(location_bits) if location_bits else 'Key zone'}: "
            f"{faster_driver} has a {abs(telemetry_summary['delta_speed_kph']):.1f} kph speed advantage "
            f"at roughly {telemetry_summary['distance_m']}m."
        )
        strongest_evidence.append(zone_summary)

    speed_trace = _downsample_speed_trace(comparison_samples, step=200) if comparison_samples else []
    focus_window = []
    if decisive_distance is not None and comparison_samples:
        focus_window = [
            {
                "distance_m": sample.get("distance_m"),
                "speed_a": sample.get("speed_a"),
                "speed_b": sample.get("speed_b"),
                "delta_speed": sample.get("delta_speed"),
            }
            for sample in comparison_samples
            if abs((sample.get("distance_m") or 0) - decisive_distance) <= 500
        ]

    return {
        "event": sector.get("event"),
        "session": "Q",
        "driver_a": driver_a_code,
        "driver_b": driver_b_code,
        "faster_driver": faster_driver,
        "slower_driver": slower_driver,
        "compared_segment": compared_segment,
        "overall_gap_s": overall_gap,
        "decisive_sector": decisive_sector,
        "decisive_sector_gap_s": decisive_sector_gap,
        "decisive_distance_m": decisive_distance,
        "decisive_corner": decisive_corner,
        "zone_summary": zone_summary,
        "cause_type": cause_type,
        "cause_explanation": cause_explanation,
        "telemetry_summary": telemetry_summary,
        "energy_relevant": energy_relevant,
        "energy_reason": energy_reason,
        "energy_context_explanation": energy_context_explanation,
        "telemetry_available": telemetry is not None,
        "energy_available": energy is not None,
        "caveats": caveats,
        "strongest_evidence": strongest_evidence,
        "speed_trace": speed_trace,
        "focus_window_trace": focus_window,
        "sector_comparison": sector,
        "energy_analysis": energy,
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


def get_circuit_details(round_number: int) -> dict:
    """
    Rich circuit metadata for map-based UI: corners, marshal lights, sectors, rotation.
    """
    try:
        session = _load_session(round_number, 'R', laps=False, telemetry=True, weather=False, messages=False)
        circuit_info = session.get_circuit_info()
    except Exception:
        circuit_info = fastf1.get_circuit_info(CURRENT_YEAR, round_number)

    return {
        "rotation": _normalize_float(getattr(circuit_info, "rotation", None)),
        "corners": _extract_track_markers(getattr(circuit_info, "corners", None)),
        "marshal_lights": _extract_track_markers(getattr(circuit_info, "marshal_lights", None)),
        "marshal_sectors": _extract_track_markers(getattr(circuit_info, "marshal_sectors", None)),
    }


def get_historical_circuit_performance(round_number: int,
                                        years: list[int] | None = None) -> dict:
    """
    Qualifying top-5 and race top-5 for the same circuit across multiple seasons.
    Reveals which teams/drivers historically perform well or poorly at this venue.
    Default years: [2023, 2024, 2025].
    """
    if years is None:
        years = [CURRENT_YEAR - 2, CURRENT_YEAR - 1, CURRENT_YEAR]

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


def get_safety_car_periods(round_number: int, session_type: str) -> dict:
    """
    Find all Safety Car and Virtual Safety Car periods in a session.
    For each period: when it was deployed (lap number + session time), duration,
    which drivers pitted just before it (got screwed — lost their gap),
    and which drivers pitted during it (got a free stop).
    """
    session = _load_session(round_number, session_type, laps=True, telemetry=False, weather=False, messages=False)

    ts = session.track_status  # columns: Time (Timedelta), Status (str), Message (str)
    laps = session.laps

    # Parse SC/VSC periods from status transitions
    # Status: '1'=clear, '2'=yellow, '4'=SC, '5'=red, '6'=VSC deployed, '7'=VSC ending
    periods = []
    active = None

    for _, row in ts.iterrows():
        status = str(row['Status'])
        t_s = round(row['Time'].total_seconds(), 1)

        if status == '4' and (active is None or active['type'] != 'SafetyCar'):
            if active is not None:
                active['end_time_s'] = t_s
                periods.append(active)
            active = {'type': 'SafetyCar', 'start_time_s': t_s, 'end_time_s': None}

        elif status == '6' and (active is None or active['type'] != 'VSC'):
            if active is not None:
                active['end_time_s'] = t_s
                periods.append(active)
            active = {'type': 'VSC', 'start_time_s': t_s, 'end_time_s': None}

        elif status in ('1', '2', '5') and active is not None:
            active['end_time_s'] = t_s
            periods.append(active)
            active = None

    if active is not None:
        periods.append(active)

    # Annotate each period with context
    for period in periods:
        start_s = period['start_time_s']
        end_s = period['end_time_s']
        period['duration_s'] = round(end_s - start_s, 1) if end_s else None

        # Approximate race lap: highest lap number that started before SC deployment
        if not laps.empty:
            sc_td = pd.Timedelta(seconds=start_s)
            laps_before = laps[laps['LapStartTime'] <= sc_td]
            period['deployed_on_lap'] = int(laps_before['LapNumber'].max()) if not laps_before.empty else None
        else:
            period['deployed_on_lap'] = None

        # Pit stop impact — who pitted in the 90s before SC (got screwed) vs during (free stop)
        pitted_just_before = []
        pitted_during = []
        LOOK_BACK_S = 90

        for driver_code in laps['Driver'].unique():
            for _, lap in _pick_driver(laps, str(driver_code)).iterrows():
                pit_in = lap.get('PitInTime')
                if pit_in is None or pd.isna(pit_in):
                    continue
                pit_s = pit_in.total_seconds()

                if (start_s - LOOK_BACK_S) <= pit_s < start_s:
                    pitted_just_before.append({
                        'driver': str(lap['Driver']),
                        'team': str(lap['Team']),
                        'lap': int(lap['LapNumber']),
                        'seconds_before_sc': round(start_s - pit_s, 1),
                    })
                elif end_s and start_s <= pit_s <= end_s:
                    pitted_during.append({
                        'driver': str(lap['Driver']),
                        'team': str(lap['Team']),
                        'lap': int(lap['LapNumber']),
                    })

        period['pitted_just_before'] = sorted(pitted_just_before, key=lambda x: x['seconds_before_sc'])
        period['pitted_during'] = pitted_during

    return {
        'event': session.event['EventName'],
        'session': session_type.upper(),
        'sc_count': len([p for p in periods if p['type'] == 'SafetyCar']),
        'vsc_count': len([p for p in periods if p['type'] == 'VSC']),
        'periods': periods,
    }


def get_race_control_messages(round_number: int, session_type: str,
                              category: str | None = None,
                              limit: int = 50) -> dict:
    """
    Return race control messages with optional category filtering.
    Useful for deleted lap reasons, incidents, flags and steward notes.
    """
    session = _load_session(round_number, session_type, laps=True, telemetry=False, weather=False, messages=True)
    messages = getattr(session, "race_control_messages", None)
    if messages is None or getattr(messages, "empty", False):
        return {"event": session.event['EventName'], "session": session_type.upper(), "messages": []}

    df = messages.copy()
    if category:
        category_lower = category.lower()
        mask = pd.Series(False, index=df.index)
        for col in ("Category", "Flag", "Message"):
            if col in df:
                mask = mask | df[col].astype(str).str.lower().str.contains(category_lower, na=False)
        df = df[mask]

    trimmed = df.head(limit)
    rows = []
    for _, row in trimmed.iterrows():
        rows.append({
            "category": row.get("Category"),
            "flag": row.get("Flag"),
            "scope": row.get("Scope"),
            "message": row.get("Message"),
            "status": row.get("Status"),
            "lap": _normalize_position(row.get("Lap")),
            "time": str(row.get("Time")) if row.get("Time") is not None and not pd.isna(row.get("Time")) else None,
            "driver_number": str(row.get("DriverNumber")) if row.get("DriverNumber") is not None and not pd.isna(row.get("DriverNumber")) else None,
        })

    return {
        "event": session.event['EventName'],
        "session": session_type.upper(),
        "category_filter": category,
        "messages": rows,
    }


def get_track_position_comparison(round_number: int, session_type: str,
                                  driver_a: str, driver_b: str,
                                  lap_number_a: int | None = None,
                                  lap_number_b: int | None = None) -> dict:
    """
    Compare two drivers using raw position and car telemetry sampled by distance.
    Best for track maps, racing lines, and locating gains/losses.
    """
    session = _load_session(round_number, session_type, laps=True, telemetry=True, weather=False, messages=False)

    def _get_driver_lap(code: str, lap_num: int | None):
        laps = _pick_driver(session.laps, code.upper())
        if laps.empty:
            raise ValueError(f"No data for driver {code!r}")
        if lap_num is not None:
            selected = laps[laps['LapNumber'] == lap_num]
            if selected.empty:
                raise ValueError(f"Lap {lap_num} not found for {code!r}")
            return selected.iloc[0]
        return _pick_fastest_lap(laps)

    lap_a = _get_driver_lap(driver_a, lap_number_a)
    lap_b = _get_driver_lap(driver_b, lap_number_b)
    pos_a = lap_a.get_pos_data().add_distance()
    pos_b = lap_b.get_pos_data().add_distance()
    car_a = lap_a.get_car_data().add_distance()
    car_b = lap_b.get_car_data().add_distance()

    total_dist = min(
        float(pos_a['Distance'].max()),
        float(pos_b['Distance'].max()),
        float(car_a['Distance'].max()),
        float(car_b['Distance'].max()),
    )

    samples = []
    dist = 0.0
    while dist <= total_dist:
        pos_idx_a = (pos_a['Distance'] - dist).abs().idxmin()
        pos_idx_b = (pos_b['Distance'] - dist).abs().idxmin()
        car_idx_a = (car_a['Distance'] - dist).abs().idxmin()
        car_idx_b = (car_b['Distance'] - dist).abs().idxmin()

        prow_a = pos_a.loc[pos_idx_a]
        prow_b = pos_b.loc[pos_idx_b]
        crow_a = car_a.loc[car_idx_a]
        crow_b = car_b.loc[car_idx_b]
        samples.append({
            "distance_m": int(dist),
            "x_a": _normalize_float(prow_a.get('X')),
            "y_a": _normalize_float(prow_a.get('Y')),
            "x_b": _normalize_float(prow_b.get('X')),
            "y_b": _normalize_float(prow_b.get('Y')),
            "status_a": prow_a.get('Status'),
            "status_b": prow_b.get('Status'),
            "speed_a": _normalize_float(crow_a.get('Speed')),
            "speed_b": _normalize_float(crow_b.get('Speed')),
            "delta_speed": round(float(crow_a['Speed']) - float(crow_b['Speed']), 1),
        })
        dist += 100.0

    return {
        "event": session.event['EventName'],
        "session": session_type.upper(),
        "driver_a": driver_a.upper(),
        "driver_b": driver_b.upper(),
        "lap_number_a": int(lap_a['LapNumber']),
        "lap_number_b": int(lap_b['LapNumber']),
        "circuit_length_m": int(total_dist),
        "rotation": _normalize_float(getattr(session.get_circuit_info(), "rotation", None)),
        "comparison": samples,
    }


def get_session_weather(round_number: int, session_type: str) -> dict:
    """
    Weather conditions throughout a session: air/track temperature, humidity,
    wind, and rainfall. Includes ~20 time-spaced samples showing how conditions
    evolved, and flags exactly when rain started/stopped.
    Useful for explaining pace anomalies, tyre choice, or lap time swings.
    """
    session = _load_session(round_number, session_type, laps=False, telemetry=False, weather=True, messages=False)

    weather = session.weather_data

    if weather is None or weather.empty:
        return {
            'event': session.event['EventName'],
            'session': session_type.upper(),
            'available': False,
        }

    had_rain = bool(weather['Rainfall'].any())

    result = {
        'event': session.event['EventName'],
        'session': session_type.upper(),
        'available': True,
        'had_rainfall': had_rain,
        'air_temp_c': {
            'min': round(float(weather['AirTemp'].min()), 1),
            'max': round(float(weather['AirTemp'].max()), 1),
            'avg': round(float(weather['AirTemp'].mean()), 1),
        },
        'track_temp_c': {
            'min': round(float(weather['TrackTemp'].min()), 1),
            'max': round(float(weather['TrackTemp'].max()), 1),
            'avg': round(float(weather['TrackTemp'].mean()), 1),
        },
        'humidity_pct_avg': round(float(weather['Humidity'].mean()), 1),
        'wind_speed_avg_ms': round(float(weather['WindSpeed'].mean()), 1),
    }

    if had_rain:
        rain_rows = weather[weather['Rainfall'] == True]
        result['rainfall_start_s'] = round(float(rain_rows['Time'].iloc[0].total_seconds()), 0)
        result['rainfall_end_s'] = round(float(rain_rows['Time'].iloc[-1].total_seconds()), 0)

    # ~20 evenly spaced samples showing how conditions evolved
    step = max(1, len(weather) // 20)
    result['samples'] = [
        {
            'time_s': round(float(row['Time'].total_seconds()), 0),
            'air_temp_c': round(float(row['AirTemp']), 1),
            'track_temp_c': round(float(row['TrackTemp']), 1),
            'rainfall': bool(row['Rainfall']),
            'wind_speed_ms': round(float(row['WindSpeed']), 1),
        }
        for _, row in weather.iloc[::step].iterrows()
    ]

    return result


# ─────────────────────────────────────────────────────────
# TELEMETRY PREPROCESSING — CORNER PROFILES & RACE PACE
# ─────────────────────────────────────────────────────────

def _assign_samples_to_zones(samples: list[dict], corners: list[dict]) -> list[str]:
    """
    For each sample, return 'corner_N' or 'straight'.
    Corner window: [corner_dist - 150m, corner_dist + 100m].
    When windows overlap, nearest corner center wins.
    """
    zones = []
    for s in samples:
        d = s.get('distance_m')
        if d is None:
            zones.append('straight')
            continue
        best_corner = None
        best_dist = float('inf')
        for c in corners:
            cd = c.get('distance_m')
            if cd is None:
                continue
            if cd - 150 <= d <= cd + 100:
                dist_to_center = abs(d - cd)
                if dist_to_center < best_dist:
                    best_dist = dist_to_center
                    best_corner = c
        if best_corner:
            num = best_corner.get('number', '?')
            label = best_corner.get('label') or ''
            zones.append(f"corner_{num}{label}")
        else:
            zones.append('straight')
    return zones


def _profile_corner_zone(zone_samples: list[dict]) -> dict:
    """
    Compute corner profile: entry/apex/exit speed, braking point,
    gear at apex, traction point.
    """
    if not zone_samples:
        return {}

    speeds = [s.get('speed_kph') for s in zone_samples if s.get('speed_kph') is not None]
    if not speeds:
        return {}

    entry_speed = round(float(zone_samples[0].get('speed_kph') or 0), 1)
    exit_speed = round(float(zone_samples[-1].get('speed_kph') or 0), 1)

    min_speed = min(speeds)
    apex_idx = next(
        (i for i, s in enumerate(zone_samples) if (s.get('speed_kph') or 999) == min_speed),
        len(zone_samples) // 2,
    )
    apex_speed = round(min_speed, 1)
    apex_sample = zone_samples[apex_idx]
    apex_gear_raw = apex_sample.get('gear')
    apex_gear = int(apex_gear_raw) if apex_gear_raw is not None else None

    braking_point_m = None
    for s in zone_samples[: apex_idx + 1]:
        if s.get('brake'):
            braking_point_m = s.get('distance_m')

    traction_point_m = None
    for s in zone_samples[apex_idx:]:
        if (s.get('throttle_pct') or 0) > 50 and not s.get('brake'):
            traction_point_m = s.get('distance_m')
            break

    return {
        'entry_speed_kph': entry_speed,
        'apex_speed_kph': apex_speed,
        'exit_speed_kph': exit_speed,
        'braking_point_m': braking_point_m,
        'apex_gear': apex_gear,
        'traction_point_m': traction_point_m,
    }


def _profile_straight_zone(zone_samples: list[dict]) -> dict:
    """
    Compute straight profile: max speed, DRS activation distance,
    acceleration rate, and clipping indicator.
    """
    if not zone_samples:
        return {}

    speeds = [s.get('speed_kph') for s in zone_samples if s.get('speed_kph') is not None]
    if not speeds:
        return {}

    max_speed = round(max(speeds), 1)
    start_dist = zone_samples[0].get('distance_m')
    end_dist = zone_samples[-1].get('distance_m')

    drs_activation_m = None
    for s in zone_samples:
        if s.get('drs_open'):
            drs_activation_m = s.get('distance_m')
            break

    cutoff = int(len(zone_samples) * 0.6)
    acc_samples = zone_samples[: max(cutoff, 2)]
    if len(acc_samples) >= 2:
        d_speed = (acc_samples[-1].get('speed_kph') or 0) - (acc_samples[0].get('speed_kph') or 0)
        d_dist = (acc_samples[-1].get('distance_m') or 0) - (acc_samples[0].get('distance_m') or 0)
        acc_rate = round(d_speed / d_dist, 3) if d_dist > 0 else None
    else:
        acc_rate = None

    clip_start = int(len(zone_samples) * 0.75)
    tail = zone_samples[clip_start:]
    clipping = False
    if len(tail) >= 3:
        tail_speeds = [s.get('speed_kph') or 0 for s in tail]
        tail_throttle = [s.get('throttle_pct') or 0 for s in tail]
        avg_thr = sum(tail_throttle) / len(tail_throttle)
        speed_spread = max(tail_speeds) - min(tail_speeds)
        if avg_thr >= 90 and speed_spread < 5:
            clipping = True

    return {
        'start_dist_m': start_dist,
        'end_dist_m': end_dist,
        'max_speed_kph': max_speed,
        'drs_activation_m': drs_activation_m,
        'acceleration_kph_per_m': acc_rate,
        'clipping_detected': clipping,
    }


def _compute_lap_zone_summary(samples: list[dict]) -> dict:
    """
    Whole-lap usage percentages: full throttle, braking, coasting,
    DRS open, and gear distribution.
    """
    if not samples:
        return {}

    total = len(samples)
    full_throttle = sum(1 for s in samples if (s.get('throttle_pct') or 0) >= 98)
    braking = sum(1 for s in samples if s.get('brake'))
    coasting = sum(1 for s in samples if (s.get('throttle_pct') or 0) < 10 and not s.get('brake'))
    drs_open = sum(1 for s in samples if s.get('drs_open'))

    gear_counts: dict[int, int] = {}
    for s in samples:
        g = s.get('gear')
        if g is not None:
            gear_counts[int(g)] = gear_counts.get(int(g), 0) + 1

    gear_distribution = {
        f"gear_{g}": round(count / total * 100, 1)
        for g, count in sorted(gear_counts.items())
    }

    return {
        'full_throttle_pct': round(full_throttle / total * 100, 1),
        'braking_pct': round(braking / total * 100, 1),
        'coasting_pct': round(coasting / total * 100, 1),
        'drs_pct': round(drs_open / total * 100, 1),
        'gear_distribution': gear_distribution,
    }


def _classify_corner_delta(profile_a: dict, profile_b: dict) -> str:
    """
    Classify where driver A's advantage comes from relative to driver B.
    Returns: 'braking' | 'minimum_speed' | 'traction' | 'mixed' | 'none'
    """
    if not profile_a or not profile_b:
        return 'none'

    entry_delta = (profile_a.get('entry_speed_kph') or 0) - (profile_b.get('entry_speed_kph') or 0)
    apex_delta = (profile_a.get('apex_speed_kph') or 0) - (profile_b.get('apex_speed_kph') or 0)
    exit_delta = (profile_a.get('exit_speed_kph') or 0) - (profile_b.get('exit_speed_kph') or 0)

    bp_a = profile_a.get('braking_point_m')
    bp_b = profile_b.get('braking_point_m')
    later_braking = bp_a is not None and bp_b is not None and bp_a > bp_b + 5

    scores: dict[str, float] = {}
    if entry_delta >= 3 or later_braking:
        scores['braking'] = abs(entry_delta) + (10 if later_braking else 0)
    if apex_delta >= 2:
        scores['minimum_speed'] = abs(apex_delta) * 2
    if exit_delta >= 3 and exit_delta > apex_delta + 1:
        tp_a = profile_a.get('traction_point_m')
        tp_b = profile_b.get('traction_point_m')
        earlier_traction = tp_a is not None and tp_b is not None and tp_a < tp_b - 5
        scores['traction'] = abs(exit_delta) + (5 if earlier_traction else 0)

    if not scores:
        return 'none'
    if len(scores) >= 2:
        top_two = sorted(scores.values(), reverse=True)[:2]
        if top_two[0] < top_two[1] * 2:
            return 'mixed'
    return max(scores, key=lambda k: scores[k])


def _filter_clean_race_laps(driver_laps) -> list[dict]:
    """
    Filter race laps: remove pit laps, safety car laps, and statistical outliers.
    Returns list of dicts with lap_number, lap_time_s, compound, tyre_age.
    """
    result = []
    for _, lap in driver_laps.iterrows():
        lt = lap.get('LapTime')
        if lt is None or pd.isna(lt):
            continue
        lt_s = lt.total_seconds()
        if lt_s <= 0:
            continue

        pit_in = lap.get('PitInTime')
        pit_out = lap.get('PitOutTime')
        if pit_in is not None and pd.notna(pit_in):
            continue
        if pit_out is not None and pd.notna(pit_out):
            continue

        track_status = str(lap.get('TrackStatus') or '')
        if any(c in track_status for c in ('4', '5', '6')):
            continue

        compound = str(lap.get('Compound') or 'UNKNOWN')
        tyre_age = lap.get('TyreLife')
        tyre_age = int(tyre_age) if tyre_age is not None and pd.notna(tyre_age) else None

        result.append({
            'lap_number': int(lap['LapNumber']),
            'lap_time_s': round(lt_s, 3),
            'compound': compound,
            'tyre_age': tyre_age,
        })

    if not result:
        return result

    sorted_times = sorted(r['lap_time_s'] for r in result)
    mid = len(sorted_times) // 2
    median_time = sorted_times[mid]
    result = [r for r in result if r['lap_time_s'] <= median_time + 5.0]
    return result


def _linear_regression(x_vals: list[float], y_vals: list[float]) -> tuple[float, float, float]:
    """
    Pure Python simple linear regression: y = slope * x + intercept.
    Returns (slope, intercept, r_squared).
    """
    n = len(x_vals)
    if n < 2:
        return (0.0, y_vals[0] if y_vals else 0.0, 0.0)

    sum_x = sum(x_vals)
    sum_y = sum(y_vals)
    sum_xy = sum(x * y for x, y in zip(x_vals, y_vals))
    sum_xx = sum(x * x for x in x_vals)

    denom = n * sum_xx - sum_x ** 2
    if abs(denom) < 1e-10:
        return (0.0, sum_y / n, 0.0)

    slope = (n * sum_xy - sum_x * sum_y) / denom
    intercept = (sum_y - slope * sum_x) / n

    y_mean = sum_y / n
    ss_tot = sum((y - y_mean) ** 2 for y in y_vals)
    ss_res = sum((y - (slope * x + intercept)) ** 2 for x, y in zip(x_vals, y_vals))
    r_squared = 1.0 - ss_res / ss_tot if ss_tot > 1e-10 else 0.0

    return (round(slope, 4), round(intercept, 3), round(r_squared, 3))


def _fit_stint_degradation(clean_laps: list[dict], fuel_correction_s_per_lap: float = 0.03) -> list[dict]:
    """
    Group clean laps by compound block, fit linear regression per stint.
    Returns list of stint dicts with deg_rate_s_per_lap, fuel_corrected_pace, r_squared.
    """
    if not clean_laps:
        return []

    stints: list[dict] = []
    current_compound: str | None = None
    current_laps: list[dict] = []

    for lap in sorted(clean_laps, key=lambda x: x['lap_number']):
        comp = lap['compound']
        if comp != current_compound:
            if current_laps:
                stints.append({'compound': current_compound, 'laps': current_laps})
            current_compound = comp
            current_laps = [lap]
        else:
            current_laps.append(lap)
    if current_laps:
        stints.append({'compound': current_compound, 'laps': current_laps})

    results = []
    for stint in stints:
        laps = stint['laps']
        if len(laps) < 3:
            continue

        lap_nums = [l['lap_number'] for l in laps]
        raw_times = [l['lap_time_s'] for l in laps]
        min_lap = min(lap_nums)

        fuel_corrected = [
            t - fuel_correction_s_per_lap * (n - min_lap)
            for t, n in zip(raw_times, lap_nums)
        ]

        tyre_ages = [
            l.get('tyre_age') or (n - min_lap + 1)
            for l, n in zip(laps, lap_nums)
        ]

        slope, intercept, r_sq = _linear_regression(tyre_ages, fuel_corrected)
        pace_at_age_1 = round(slope * 1 + intercept, 3)

        mean_t = sum(fuel_corrected) / len(fuel_corrected)
        variance = sum((t - mean_t) ** 2 for t in fuel_corrected) / len(fuel_corrected)
        std_dev = round(variance ** 0.5, 3)

        results.append({
            'compound': stint['compound'],
            'lap_count': len(laps),
            'lap_numbers': lap_nums,
            'avg_raw_pace_s': round(sum(raw_times) / len(raw_times), 3),
            'deg_rate_s_per_lap': slope,
            'fuel_corrected_pace_at_age_1_s': pace_at_age_1,
            'r_squared': r_sq,
            'consistency_std_dev_s': std_dev,
        })

    return results


def _align_stints_by_compound(stints_a: list[dict], stints_b: list[dict]) -> list[dict]:
    """Match stints by compound and return aligned pairs with comparative metrics."""
    aligned = []
    used_b: set[int] = set()

    for stint_a in stints_a:
        comp_a = (stint_a.get('compound') or '').upper()
        match_b_idx = None
        for i, sb in enumerate(stints_b):
            if i in used_b:
                continue
            if (sb.get('compound') or '').upper() == comp_a:
                if match_b_idx is None or sb.get('lap_count', 0) > stints_b[match_b_idx].get('lap_count', 0):
                    match_b_idx = i

        if match_b_idx is None:
            continue
        used_b.add(match_b_idx)
        sb = stints_b[match_b_idx]

        deg_a = stint_a.get('deg_rate_s_per_lap') or 0.0
        deg_b = sb.get('deg_rate_s_per_lap') or 0.0
        pace_a = stint_a.get('fuel_corrected_pace_at_age_1_s')
        pace_b = sb.get('fuel_corrected_pace_at_age_1_s')

        aligned.append({
            'compound': comp_a,
            'stint_a': stint_a,
            'stint_b': sb,
            'deg_rate_delta': round(deg_a - deg_b, 4),
            'pace_delta_s': round(pace_a - pace_b, 3) if pace_a is not None and pace_b is not None else None,
        })

    return aligned


def _find_representative_lap(clean_laps: list[dict]) -> int | None:
    """Return the lap number closest to median fuel-corrected pace."""
    if not clean_laps:
        return None
    sorted_by_num = sorted(clean_laps, key=lambda x: x['lap_number'])
    min_lap = sorted_by_num[0]['lap_number']
    corrected = [
        (l['lap_number'], l['lap_time_s'] - 0.03 * (l['lap_number'] - min_lap))
        for l in sorted_by_num
    ]
    sorted_times = sorted(corrected, key=lambda x: x[1])
    mid = len(sorted_times) // 2
    return sorted_times[mid][0]


def extract_corner_profiles(
    round_number: int,
    session_type: str,
    driver_code: str,
    lap_number: int | None = None,
) -> dict:
    """
    Per-corner and per-straight telemetry breakdown for a driver's lap.
    Includes entry/apex/exit speed, braking point, gear at apex, traction point,
    straight acceleration, DRS activation, clipping, and lap zone summary.
    """
    _validate_session_availability(round_number, session_type, telemetry=True)
    session = _load_session(round_number, session_type, laps=True, telemetry=True, weather=False, messages=False)

    driver_laps = _pick_driver(session.laps, driver_code.upper())
    if driver_laps.empty:
        raise ValueError(f"No laps found for driver {driver_code} in round {round_number} {session_type}.")

    if lap_number is not None:
        lap_rows = driver_laps[driver_laps['LapNumber'] == lap_number]
        if lap_rows.empty:
            raise ValueError(f"Lap {lap_number} not found for {driver_code}.")
        lap = lap_rows.iloc[0]
    else:
        lap = _pick_fastest_lap(driver_laps)

    tel = lap.get_telemetry()
    if tel is None or tel.empty:
        raise ValueError(f"Telemetry unavailable for {driver_code} lap {int(lap['LapNumber'])}.")

    samples = []
    for _, row in tel.iterrows():
        dist = row.get('Distance')
        speed = row.get('Speed')
        if dist is None or pd.isna(dist) or speed is None or pd.isna(speed):
            continue
        gear_raw = row.get('nGear')
        drs_raw = row.get('DRS')
        samples.append({
            'distance_m': round(float(dist), 1),
            'speed_kph': round(float(speed), 1),
            'throttle_pct': round(float(row['Throttle']), 1) if pd.notna(row.get('Throttle')) else 0.0,
            'brake': bool(row.get('Brake', False)),
            'gear': int(gear_raw) if gear_raw is not None and pd.notna(gear_raw) else None,
            'rpm': int(row['RPM']) if pd.notna(row.get('RPM')) else None,
            'drs_open': int(drs_raw) >= 10 if drs_raw is not None and pd.notna(drs_raw) else False,
        })

    if not samples:
        raise ValueError(f"No valid telemetry samples for {driver_code}.")

    try:
        corners = get_circuit_corners(round_number)
    except Exception:
        corners = []

    zone_labels = _assign_samples_to_zones(samples, corners)
    lap_summary = _compute_lap_zone_summary(samples)

    corner_profiles: dict[str, dict] = {}
    straight_profiles: list[dict] = []
    current_zone: str | None = None
    current_group: list[dict] = []

    for sample, zone in zip(samples, zone_labels):
        if zone != current_zone:
            if current_zone and current_group:
                if current_zone.startswith('corner_'):
                    corner_profiles[current_zone] = _profile_corner_zone(current_group)
                else:
                    p = _profile_straight_zone(current_group)
                    if p:
                        straight_profiles.append(p)
            current_zone = zone
            current_group = [sample]
        else:
            current_group.append(sample)

    if current_zone and current_group:
        if current_zone.startswith('corner_'):
            corner_profiles[current_zone] = _profile_corner_zone(current_group)
        else:
            p = _profile_straight_zone(current_group)
            if p:
                straight_profiles.append(p)

    lap_time_s = round(lap['LapTime'].total_seconds(), 3) if pd.notna(lap.get('LapTime')) else None

    return {
        'event': session.event['EventName'],
        'session': session_type.upper(),
        'driver': driver_code.upper(),
        'lap_number': int(lap['LapNumber']),
        'lap_time': _fmt_td(lap['LapTime']),
        'lap_time_s': lap_time_s,
        'corner_profiles': corner_profiles,
        'straight_profiles': straight_profiles,
        'lap_summary': lap_summary,
    }


def compare_corner_profiles(
    round_number: int,
    session_type: str,
    driver_a: str,
    driver_b: str,
    lap_number_a: int | None = None,
    lap_number_b: int | None = None,
) -> dict:
    """
    Compare corner profiles between two drivers.
    Returns per-corner cause classification, setup direction inference,
    and gain location summary showing where the faster driver has an advantage.
    """
    profile_a = extract_corner_profiles(round_number, session_type, driver_a, lap_number_a)
    profile_b = extract_corner_profiles(round_number, session_type, driver_b, lap_number_b)

    lt_a = profile_a.get('lap_time_s')
    lt_b = profile_b.get('lap_time_s')
    overall_gap = round(lt_a - lt_b, 3) if lt_a is not None and lt_b is not None else None

    faster = driver_a.upper() if (overall_gap is not None and overall_gap <= 0) else driver_b.upper()
    fps = profile_a['corner_profiles'] if faster == driver_a.upper() else profile_b['corner_profiles']
    sps = profile_b['corner_profiles'] if faster == driver_a.upper() else profile_a['corner_profiles']

    corner_deltas: dict[str, dict] = {}
    for key in fps:
        if key not in sps:
            continue
        fp = fps[key]
        sp = sps[key]
        cause = _classify_corner_delta(fp, sp)
        corner_deltas[key] = {
            'cause': cause,
            'entry_delta_kph': round((fp.get('entry_speed_kph') or 0) - (sp.get('entry_speed_kph') or 0), 1),
            'apex_delta_kph': round((fp.get('apex_speed_kph') or 0) - (sp.get('apex_speed_kph') or 0), 1),
            'exit_delta_kph': round((fp.get('exit_speed_kph') or 0) - (sp.get('exit_speed_kph') or 0), 1),
            'faster_braking_point_m': fp.get('braking_point_m'),
            'slower_braking_point_m': sp.get('braking_point_m'),
            'faster_apex_gear': fp.get('apex_gear'),
            'slower_apex_gear': sp.get('apex_gear'),
        }

    cause_counts: dict[str, int] = {}
    for d in corner_deltas.values():
        c = d.get('cause', 'none')
        cause_counts[c] = cause_counts.get(c, 0) + 1

    straights_a = profile_a.get('straight_profiles', [])
    straights_b = profile_b.get('straight_profiles', [])
    avg_str_a = (sum(s.get('max_speed_kph') or 0 for s in straights_a) / len(straights_a)) if straights_a else 0.0
    avg_str_b = (sum(s.get('max_speed_kph') or 0 for s in straights_b) / len(straights_b)) if straights_b else 0.0

    corner_wins = sum(1 for d in corner_deltas.values() if (d.get('apex_delta_kph') or 0) > 1)
    total_corners = len(corner_deltas)
    corner_win_ratio = corner_wins / total_corners if total_corners > 0 else 0.5

    straight_delta = avg_str_a - avg_str_b
    if faster == driver_b.upper():
        straight_delta = -straight_delta

    if corner_win_ratio >= 0.6 and straight_delta < 5:
        setup_direction = 'corner_heavy'
    elif straight_delta >= 5 and corner_win_ratio < 0.5:
        setup_direction = 'straight_heavy'
    else:
        setup_direction = 'balanced'

    top_corners = sorted(
        corner_deltas.items(),
        key=lambda item: abs(item[1].get('apex_delta_kph') or 0) + abs(item[1].get('exit_delta_kph') or 0),
        reverse=True,
    )[:3]

    gain_location_summary = [
        {
            'corner': k,
            'cause': v['cause'],
            'apex_delta_kph': v['apex_delta_kph'],
            'exit_delta_kph': v['exit_delta_kph'],
        }
        for k, v in top_corners
    ]

    return {
        'event': profile_a.get('event'),
        'session': session_type.upper(),
        'driver_a': driver_a.upper(),
        'driver_b': driver_b.upper(),
        'lap_time_a': profile_a.get('lap_time'),
        'lap_time_b': profile_b.get('lap_time'),
        'lap_time_a_s': lt_a,
        'lap_time_b_s': lt_b,
        'overall_gap_s': overall_gap,
        'faster_driver': faster,
        'corner_deltas': corner_deltas,
        'cause_breakdown': cause_counts,
        'setup_direction_inference': setup_direction,
        'gain_location_summary': gain_location_summary,
        'lap_summary_a': profile_a.get('lap_summary', {}),
        'lap_summary_b': profile_b.get('lap_summary', {}),
        'avg_straight_speed_a_kph': round(avg_str_a, 1) if avg_str_a else None,
        'avg_straight_speed_b_kph': round(avg_str_b, 1) if avg_str_b else None,
    }


def analyze_stint_degradation(round_number: int, driver_code: str, session_type: str = "R") -> dict:
    """
    Compute per-stint tyre degradation model for a driver.
    Returns linear regression deg_rate_s_per_lap, fuel-corrected base pace,
    r_squared, and consistency_std_dev_s for each stint.
    """
    _validate_session_availability(round_number, session_type, telemetry=False)
    session = _load_session(round_number, session_type, laps=True, telemetry=False, weather=False, messages=False)

    driver_laps = _pick_driver(session.laps, driver_code.upper())
    if driver_laps.empty:
        raise ValueError(f"No laps found for {driver_code} in round {round_number} {session_type}.")

    clean_laps = _filter_clean_race_laps(driver_laps)
    if not clean_laps:
        raise ValueError(f"No clean laps available for {driver_code} after filtering.")

    stints = _fit_stint_degradation(clean_laps)

    total_laps = sum(s['lap_count'] for s in stints)
    weighted_pace = None
    if total_laps > 0 and stints:
        weighted_pace = round(
            sum(s['fuel_corrected_pace_at_age_1_s'] * s['lap_count'] for s in stints) / total_laps,
            3,
        )

    worst_stint = max(stints, key=lambda s: s.get('deg_rate_s_per_lap') or 0) if stints else None
    best_stint = min(stints, key=lambda s: s.get('deg_rate_s_per_lap') or 0) if stints else None

    return {
        'event': session.event['EventName'],
        'session': session_type.upper(),
        'driver': driver_code.upper(),
        'total_clean_laps': len(clean_laps),
        'stints': stints,
        'weighted_avg_fuel_corrected_pace_s': weighted_pace,
        'highest_degradation_stint': worst_stint,
        'lowest_degradation_stint': best_stint,
    }


def analyze_race_pace_battle(
    round_number: int,
    driver_a: str,
    driver_b: str,
    session_type: str = "R",
) -> dict:
    """
    Compare race pace and tyre degradation between two drivers.
    Race equivalent of analyze_qualifying_battle: computes structured evidence
    about degradation rates, fuel-corrected pace deltas, and decisive factor.
    """
    _validate_session_availability(round_number, session_type, telemetry=False)
    session = _load_session(round_number, session_type, laps=True, telemetry=False, weather=False, messages=False)

    def _driver_data(code: str):
        laps = _pick_driver(session.laps, code.upper())
        if laps.empty:
            raise ValueError(f"No laps found for {code} in round {round_number} {session_type}.")
        clean = _filter_clean_race_laps(laps)
        if not clean:
            raise ValueError(f"No clean laps available for {code} after filtering.")
        stints = _fit_stint_degradation(clean)
        if not stints:
            raise ValueError(f"No degradable stints available for {code} after filtering.")
        rep_lap = _find_representative_lap(clean)
        return laps, clean, stints, rep_lap

    laps_a, clean_a, stints_a, rep_lap_a = _driver_data(driver_a)
    laps_b, clean_b, stints_b, rep_lap_b = _driver_data(driver_b)

    aligned = _align_stints_by_compound(stints_a, stints_b)

    def _weighted_pace(stints: list[dict]) -> float | None:
        total = sum(s['lap_count'] for s in stints)
        if total == 0:
            return None
        return sum(s['fuel_corrected_pace_at_age_1_s'] * s['lap_count'] for s in stints) / total

    pace_a = _weighted_pace(stints_a)
    pace_b = _weighted_pace(stints_b)
    overall_delta = round(pace_a - pace_b, 3) if pace_a is not None and pace_b is not None else None

    avg_deg_a = (sum(s['deg_rate_s_per_lap'] for s in stints_a) / len(stints_a)) if stints_a else None
    avg_deg_b = (sum(s['deg_rate_s_per_lap'] for s in stints_b) / len(stints_b)) if stints_b else None
    deg_delta = round(avg_deg_a - avg_deg_b, 4) if avg_deg_a is not None and avg_deg_b is not None else None

    decisive_factor = 'mixed'
    if overall_delta is not None and deg_delta is not None:
        if abs(deg_delta) >= 0.08 and abs(deg_delta) > abs(overall_delta) * 0.5:
            decisive_factor = 'tyre_degradation'
        elif abs(overall_delta) >= 0.2 and abs(deg_delta) < 0.05:
            decisive_factor = 'raw_pace_advantage'
        elif abs(overall_delta) < 0.15 and abs(deg_delta) < 0.05:
            decisive_factor = 'strategy_execution'

    def _first_pit_lap(driver_laps) -> int | None:
        for _, lap in driver_laps.iterrows():
            pit_in = lap.get('PitInTime')
            if pit_in is not None and pd.notna(pit_in):
                return int(lap['LapNumber'])
        return None

    pit_lap_a = _first_pit_lap(laps_a)
    pit_lap_b = _first_pit_lap(laps_b)
    undercut_opportunity = None
    if pit_lap_a is not None and pit_lap_b is not None:
        gap = pit_lap_b - pit_lap_a
        if abs(gap) >= 2:
            earlier = driver_a.upper() if gap > 0 else driver_b.upper()
            undercut_opportunity = {
                'earlier_pitter': earlier,
                'pit_lap_delta': gap,
                'note': f"{earlier} pitted {abs(gap)} laps earlier - possible undercut attempt.",
            }

    return {
        'event': session.event['EventName'],
        'session': session_type.upper(),
        'driver_a': driver_a.upper(),
        'driver_b': driver_b.upper(),
        'total_clean_laps_a': len(clean_a),
        'total_clean_laps_b': len(clean_b),
        'stints_a': stints_a,
        'stints_b': stints_b,
        'aligned_stints': aligned,
        'fuel_corrected_pace_a_s': round(pace_a, 3) if pace_a is not None else None,
        'fuel_corrected_pace_b_s': round(pace_b, 3) if pace_b is not None else None,
        'overall_pace_delta_s': overall_delta,
        'avg_deg_rate_a_s_per_lap': round(avg_deg_a, 4) if avg_deg_a is not None else None,
        'avg_deg_rate_b_s_per_lap': round(avg_deg_b, 4) if avg_deg_b is not None else None,
        'deg_rate_delta': deg_delta,
        'decisive_factor': decisive_factor,
        'first_pit_lap_a': pit_lap_a,
        'first_pit_lap_b': pit_lap_b,
        'undercut_opportunity': undercut_opportunity,
        'representative_lap_a': rep_lap_a,
        'representative_lap_b': rep_lap_b,
    }


def analyze_team_performance(round_number: int, team_name: str, session_type: str) -> dict:
    """
    Compare both teammates' corner profiles and (for race sessions) degradation.
    Returns setup direction inference and gain location summary for the team.
    """
    resolved_team = _resolve_team(team_name)
    if not resolved_team:
        raise ValueError(f"Team not found: {team_name!r}")

    all_drivers = get_drivers()
    team_drivers = [d for d in all_drivers if (d.get('team') or '').lower() == resolved_team.lower()]
    if len(team_drivers) < 2:
        raise ValueError(f"Could not find 2 drivers for team {resolved_team!r}.")

    code_a = team_drivers[0].get('code') or team_drivers[0].get('driver_id', '').upper()
    code_b = team_drivers[1].get('code') or team_drivers[1].get('driver_id', '').upper()

    corner_comparison = None
    corner_error = None
    try:
        corner_comparison = compare_corner_profiles(round_number, session_type, code_a, code_b)
    except Exception as exc:
        corner_error = str(exc)

    degradation_a = None
    degradation_b = None
    deg_error = None
    if session_type.upper() in ('R', 'S'):
        try:
            degradation_a = analyze_stint_degradation(round_number, code_a, session_type)
        except Exception as exc:
            deg_error = f"{code_a}: {exc}"
        try:
            degradation_b = analyze_stint_degradation(round_number, code_b, session_type)
        except Exception as exc:
            deg_error = (deg_error or '') + f" | {code_b}: {exc}"

    result: dict = {
        'event': None,
        'session': session_type.upper(),
        'team': resolved_team,
        'driver_a': code_a,
        'driver_b': code_b,
    }

    if corner_comparison:
        result['event'] = corner_comparison.get('event')
        result['corner_comparison'] = corner_comparison
        result['setup_direction_inference'] = corner_comparison.get('setup_direction_inference')
        result['gain_location_summary'] = corner_comparison.get('gain_location_summary')
    if corner_error:
        result['corner_error'] = corner_error

    if degradation_a:
        result['event'] = result.get('event') or degradation_a.get('event')
        result['degradation_a'] = degradation_a
    if degradation_b:
        result['event'] = result.get('event') or degradation_b.get('event')
        result['degradation_b'] = degradation_b
    if deg_error:
        result['degradation_error'] = deg_error

    return result
