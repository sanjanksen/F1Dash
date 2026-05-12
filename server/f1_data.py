# server/f1_data.py
import os
import time
import logging
import threading
import numbers
import math
import fastf1
import requests
import pandas as pd
import numpy as np
from pandas.api.types import is_numeric_dtype
from scipy.signal import savgol_filter
from energy_2026 import get_energy_2026_knowledge
from driver_styles import get_comparison_framing
from circuit_profiles import get_circuit_profile

# Enable FastF1 disk cache
_CACHE_DIR = os.path.join(os.path.dirname(__file__), 'cache')
os.makedirs(_CACHE_DIR, exist_ok=True)
fastf1.Cache.enable_cache(_CACHE_DIR)

JOLPICA_BASE = "https://api.jolpi.ca/ergast/f1"
CURRENT_YEAR = __import__('datetime').date.today().year
logger = logging.getLogger(__name__)

_SESSION_CACHE: dict[tuple[int, int, str], dict] = {}
_SESSION_CACHE_LOCK = threading.Lock()
SESSION_CACHE_TTL = 300  # seconds; session data does not change mid-day


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
        # Evict if stale — safe to do under the global lock
        if entry is not None and time.monotonic() - entry["created_at"] > SESSION_CACHE_TTL:
            logger.debug(
                "Evicting stale FastF1 session cache entry round=%s session=%s",
                round_number,
                normalized_session,
            )
            del _SESSION_CACHE[cache_key]
            entry = None

        if entry is None:
            entry = {
                "session": fastf1.get_session(CURRENT_YEAR, round_number, normalized_session),
                "laps": False,
                "telemetry": False,
                "weather": False,
                "messages": False,
                "lock": threading.Lock(),
                "created_at": time.monotonic(),
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


def _in_late_clip_window(distance, windows: list[dict]) -> bool:
    if distance is None:
        return False
    for window in windows:
        start = window.get("start_distance_m")
        end = window.get("end_distance_m")
        if start is None or end is None:
            continue
        midpoint = start + ((end - start) / 2)
        if midpoint <= distance <= end:
            return True
    return False


def _strongest_comparative_full_throttle_fade(
    samples: list[dict],
    clip_a: list[dict],
    clip_b: list[dict],
    driver_a: str,
    driver_b: str,
) -> dict | None:
    fade_candidates = []
    code_a = driver_a.upper()
    code_b = driver_b.upper()
    for sample in samples:
        delta_speed = sample.get("delta_speed") or 0
        faded_driver = code_a if delta_speed < 0 else code_b
        faded_windows = clip_a if faded_driver == code_a else clip_b
        if (
            (sample.get("throttle_a") or 0) >= 95
            and (sample.get("throttle_b") or 0) >= 95
            and not sample.get("brake_a")
            and not sample.get("brake_b")
            and abs(delta_speed) >= 8
            and _in_late_clip_window(sample.get("distance_m"), faded_windows)
        ):
            fade_candidates.append({
                "distance_m": sample.get("distance_m"),
                "delta_speed_kph": delta_speed,
                "speed_a": sample.get("speed_a"),
                "speed_b": sample.get("speed_b"),
                "faded_driver": faded_driver,
            })
    return max(fade_candidates, key=lambda row: abs(row["delta_speed_kph"]), default=None)


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
        "session": "R",
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
        "session": "Q",
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
        session = _load_session(round_number, "SQ", laps=False, telemetry=False, weather=False, messages=False)
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
                    "position_start": positions[0] if positions else None,
                    "position_end": positions[-1] if positions else None,
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
        strategy = get_driver_strategy(round_number, race_session, code)
        strategy_summary = strategy["drivers"][0] if strategy.get("drivers") else None
    except Exception:
        strategy_summary = None

    safety_car_summary = None
    try:
        sc = get_safety_car_periods(round_number, race_session)
        driver_number = None
        try:
            session_results = get_session_results(round_number, race_session)
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
            session_results = get_session_results(round_number, race_session)
            meta = next((r for r in session_results.get("results", []) if r.get("abbreviation", "").upper() == code.upper()), None)
            grid_position = meta.get("grid_position") if meta else None
        except Exception:
            grid_position = None

    energy_management = None
    preferred_session = quali_session if driver_quali else race_session
    try:
        energy_management = analyze_energy_management(round_number, preferred_session, code)
    except Exception:
        energy_management = None

    openf1_qualifying_radio = None
    if driver_quali:
        try:
            from openf1 import get_team_radio
            openf1_qualifying_radio = get_team_radio(round_number, quali_session, code, limit=6)
        except Exception:
            openf1_qualifying_radio = None

    openf1_race_intervals = None
    openf1_race_positions = None
    openf1_race_radio = None
    if driver_race:
        try:
            from openf1 import get_intervals
            openf1_race_intervals = get_intervals(round_number, code, limit=20, session_type=race_session)
        except Exception:
            openf1_race_intervals = None
        try:
            from openf1 import get_live_position_timeline
            openf1_race_positions = get_live_position_timeline(round_number, race_session, code, limit=30)
        except Exception:
            openf1_race_positions = None
        try:
            from openf1 import get_team_radio
            openf1_race_radio = get_team_radio(round_number, race_session, code, limit=8)
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
            "q1": driver_quali.get("sq1" if is_sprint else "q1") if driver_quali else None,
            "q2": driver_quali.get("sq2" if is_sprint else "q2") if driver_quali else None,
            "q3": driver_quali.get("sq3" if is_sprint else "q3") if driver_quali else None,
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

    summary_points = []
    race = overview.get("race", {})
    quali = overview.get("qualifying", {})

    if quali.get("position") is not None and race.get("finish_position") is not None:
        delta = quali["position"] - race["finish_position"]
        session_label = "sprint qualifying" if session_type == "S" else "qualifying"
        if delta > 0:
            summary_points.append(f"Gained {delta} place(s) from {session_label} to the finish.")
        elif delta < 0:
            summary_points.append(f"Lost {abs(delta)} place(s) from {session_label} to the finish.")
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

    # Field-wide strategy grid for undercut/overcut reasoning
    field_strategy = []
    try:
        all_strat = get_driver_strategy(round_number, race_session)
        for drv in all_strat.get("drivers", []):
            field_strategy.append({
                "driver": drv.get("abbreviation", "").upper(),
                "finish_position": drv.get("finish_position"),
                "grid_position": drv.get("grid_position"),
                "pit_stop_count": drv.get("pit_stop_count"),
                "stints": [
                    {
                        "compound": s.get("compound"),
                        "start_lap": s.get("start_lap"),
                        "end_lap": s.get("end_lap"),
                        "laps": s.get("laps"),
                        "tyre_life_start": s.get("tyre_life_start"),
                    }
                    for s in drv.get("stints", [])
                ],
            })
        field_strategy.sort(key=lambda d: d.get("finish_position") or 999)
    except Exception:
        field_strategy = []

    # Full SC/VSC periods including strategic_crossings for SC strategy reasoning
    safety_car_full = None
    try:
        safety_car_full = get_safety_car_periods(round_number, race_session)
    except Exception:
        safety_car_full = None

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
        "safety_car_full": safety_car_full,
        "field_strategy": field_strategy,
        "teammate": overview["teammate"],
        "nearby_rivals": overview["nearby_rivals"],
        "race_control_highlights": control_highlights,
        "radio_highlights": radio_highlights,
        "interval_summary": interval_summary,
        "position_timeline_summary": position_timeline_summary,
        "story_points": summary_points,
        "rivalry_story": rivalry_story,
    }


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
    quali_results = qualifying.get("results", [])
    race_results = race.get("results", [])

    driver_summaries = []
    for driver in team_drivers:
        code = driver.get("code", "").upper()
        quali_row = next((r for r in quali_results if r.get("code", "").upper() == code), None)
        race_row = next((r for r in race_results if r.get("code", "").upper() == code), None)

        strategy = None
        try:
            strat = get_driver_strategy(round_number, race_session, code)
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
    results = race.get("results", [])
    quali_results = qualifying.get("results", [])
    openf1_intervals = {}
    safety_car = None
    try:
        safety_car = get_safety_car_periods(round_number, race_session)
    except Exception:
        safety_car = None
    try:
        from openf1 import get_intervals
        for row in results[:5]:
            code = row.get("code")
            if not code:
                continue
            interval_payload = get_intervals(round_number, code, limit=20, session_type=race_session)
            summary = _summarize_openf1_intervals(interval_payload.get("intervals") or [])
            if summary:
                openf1_intervals[code.upper()] = summary
    except Exception:
        openf1_intervals = {}

    by_code_quali = {row.get("code", "").upper(): row for row in quali_results}
    finishers = [row for row in results if row.get("position") is not None]
    finishers.sort(key=lambda row: row["position"])

    podium = finishers[:3]
    dnfs = [
        row for row in results
        if row.get("status")
        and row.get("status") != "Finished"
        # "+N Lap(s)" = classified finisher who was lapped, not a retirement
        and not row.get("status", "").startswith("+")
    ]

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

    # Field-wide strategy grid for undercut/overcut/SC reasoning (not applicable for sprints)
    field_strategy = []
    if not is_sprint:
        try:
            all_strat = get_driver_strategy(round_number, race_session)
            for drv in all_strat.get("drivers", []):
                field_strategy.append({
                    "driver": drv.get("abbreviation", "").upper(),
                    "finish_position": drv.get("finish_position"),
                    "grid_position": drv.get("grid_position"),
                    "pit_stop_count": drv.get("pit_stop_count"),
                    "stints": [
                        {
                            "compound": s.get("compound"),
                            "start_lap": s.get("start_lap"),
                            "end_lap": s.get("end_lap"),
                            "laps": s.get("laps"),
                            "tyre_life_start": s.get("tyre_life_start"),
                        }
                        for s in drv.get("stints", [])
                    ],
                })
            field_strategy.sort(key=lambda d: d.get("finish_position") or 999)
        except Exception:
            field_strategy = []

    return {
        "session": session_type,
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
        "field_strategy": field_strategy,
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
    targets = list(range(0, int(total_dist) + 1, INTERVAL_M))
    if targets[-1] < total_dist:
        targets.append(int(total_dist))
    samples = _sample_telemetry_at_distances(tel, targets)

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
        x_a = _normalize_float(row_a.get('X'))
        y_a = _normalize_float(row_a.get('Y'))
        x_b = _normalize_float(row_b.get('X'))
        y_b = _normalize_float(row_b.get('Y'))

        samples.append({
            "distance_m": int(dist),
            "x": x_a if x_a is not None else x_b,
            "y": y_a if y_a is not None else y_b,
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

    sector_boundary_distances = [None, None]
    try:
        s1_dur = lap_a.get('Sector1Time')
        s2_dur = lap_a.get('Sector2Time')
        if s1_dur is not None and pd.notna(s1_dur) and s2_dur is not None and pd.notna(s2_dur):
            s1_idx = (tel_a['Time'] - s1_dur).abs().idxmin()
            s2_idx = (tel_a['Time'] - (s1_dur + s2_dur)).abs().idxmin()
            sector_boundary_distances[0] = int(tel_a.loc[s1_idx, 'Distance'])
            sector_boundary_distances[1] = int(tel_a.loc[s2_idx, 'Distance'])
    except Exception:
        pass

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
        "sector_boundary_distances": sector_boundary_distances,
    }


def _extract_major_straights(
    samples: list[dict],
    speed_threshold_kph: float = 275,
    min_length_m: float = 200,
) -> list[dict]:
    """
    Find sections of track where speed >= threshold for >= min_length_m.
    Returns list of {start_m, end_m, length_m}, sorted by start_m.
    """
    straights: list[dict] = []
    in_straight = False
    start_m: float | None = None

    for s in samples:
        speed = s.get("speed_kph") or 0
        dist = s.get("distance_m") or 0
        if speed >= speed_threshold_kph and not in_straight:
            in_straight = True
            start_m = dist
        elif speed < speed_threshold_kph and in_straight:
            length = dist - (start_m or 0)
            if length >= min_length_m:
                straights.append({"start_m": round(start_m), "end_m": round(dist), "length_m": round(length)})
            in_straight = False

    if in_straight and start_m is not None and samples:
        end_m = samples[-1].get("distance_m") or 0
        length = end_m - start_m
        if length >= min_length_m:
            straights.append({"start_m": round(start_m), "end_m": round(end_m), "length_m": round(length)})

    return straights


def _compute_energy_metrics(
    samples: list[dict],
    lico_events: list[dict],
    clip_windows: list[dict],
) -> dict:
    """
    Quantify ERS energy management from inferred lift-and-coast and clipping signals.

    Clipping metrics: how often and how severely the MGU-K runs out.
    Harvest metrics: how aggressively the driver lifts before corners to recover energy.
    """
    clip_count = len(clip_windows)
    total_clip_distance_m = sum(
        ((c.get("end_distance_m") or 0) - (c.get("start_distance_m") or 0))
        for c in clip_windows
    )
    total_late_drop_kph = sum(
        abs(c.get("late_straight_drop_kph") or 0)
        for c in clip_windows
        if (c.get("late_straight_drop_kph") or 0) < 0
    )

    est_time_lost = 0.0
    for c in clip_windows:
        drop_kph = c.get("late_straight_drop_kph") or 0
        if drop_kph >= 0:
            continue
        half_window_m = ((c.get("end_distance_m") or 0) - (c.get("start_distance_m") or 0)) / 2
        avg_speed_kph = c.get("mid_speed_kph") or 300
        avg_speed_ms = max(avg_speed_kph / 3.6, 1.0)
        drop_ms = abs(drop_kph) / 3.6
        est_time_lost += (drop_ms * half_window_m) / (avg_speed_ms ** 2)

    lico_count = len(lico_events)
    harvest_zones: list[dict] = []
    if lico_events:
        zone_start = lico_events[0].get("distance_m") or 0
        zone_end = zone_start
        for ev in lico_events[1:]:
            d = ev.get("distance_m") or 0
            if d - zone_end < 50:
                zone_end = d
            else:
                harvest_zones.append({
                    "start_m": round(zone_start),
                    "end_m": round(zone_end),
                    "length_m": round(zone_end - zone_start),
                })
                zone_start = d
                zone_end = d
        harvest_zones.append({
            "start_m": round(zone_start),
            "end_m": round(zone_end),
            "length_m": round(zone_end - zone_start),
        })
    total_harvest_distance_m = sum(z["length_m"] for z in harvest_zones)

    return {
        "clip_count": clip_count,
        "total_clip_distance_m": round(total_clip_distance_m, 1),
        "total_late_speed_drop_kph": round(total_late_drop_kph, 2),
        "estimated_time_lost_to_clipping_s": round(est_time_lost, 3),
        "lico_count": lico_count,
        "total_harvest_distance_m": round(total_harvest_distance_m, 1),
        "harvest_zones": harvest_zones,
    }


def _analyze_straights_energy(
    samples_a: list[dict],
    samples_b: list[dict] | None,
    clip_a: list[dict],
    clip_b: list[dict] | None,
    driver_a: str,
    driver_b: str | None,
) -> list[dict]:
    """
    Per-major-straight comparison: peak speed, end speed, clipping for each driver.
    Straights detected from samples_a. Returns up to 6 straights.
    """
    straights = _extract_major_straights(samples_a)
    results: list[dict] = []

    for straight in straights[:6]:
        start_m, end_m = straight["start_m"], straight["end_m"]
        pts_a = [s for s in samples_a if start_m <= (s.get("distance_m") or -1) <= end_m]
        if not pts_a:
            continue

        speeds_a = [p["speed_kph"] for p in pts_a if p.get("speed_kph")]
        peak_a = max(speeds_a) if speeds_a else None
        end_kph_a = pts_a[-1].get("speed_kph")
        drs_a = any(p.get("drs_open") for p in pts_a)
        clipped_a = any(
            (c.get("start_distance_m") or 0) >= start_m and (c.get("start_distance_m") or 0) <= end_m
            for c in clip_a
        )

        row: dict = {
            "start_m": start_m,
            "length_m": straight["length_m"],
            "drs": drs_a,
            "driver_a": {
                "code": driver_a.upper(),
                "peak_kph": round(peak_a, 1) if peak_a else None,
                "end_kph": round(end_kph_a, 1) if end_kph_a else None,
                "clipped": clipped_a,
            },
        }

        if samples_b:
            pts_b = [s for s in samples_b if start_m <= (s.get("distance_m") or -1) <= end_m]
            if pts_b:
                speeds_b = [p["speed_kph"] for p in pts_b if p.get("speed_kph")]
                peak_b = max(speeds_b) if speeds_b else None
                end_kph_b = pts_b[-1].get("speed_kph")
                clipped_b = any(
                    (c.get("start_distance_m") or 0) >= start_m and (c.get("start_distance_m") or 0) <= end_m
                    for c in (clip_b or [])
                )
                row["driver_b"] = {
                    "code": driver_b.upper() if driver_b else None,
                    "peak_kph": round(peak_b, 1) if peak_b else None,
                    "end_kph": round(end_kph_b, 1) if end_kph_b else None,
                    "clipped": clipped_b,
                }

        results.append(row)

    return results


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

        metrics_a = _compute_energy_metrics(driver_a_samples, lico_a, clip_a)
        metrics_b = _compute_energy_metrics(driver_b_samples, lico_b, clip_b)
        straight_breakdown = _analyze_straights_energy(
            driver_a_samples, driver_b_samples, clip_a, clip_b, driver_a, driver_b
        )
        trace_a = [
            {"distance_m": s["distance_m"], "speed_kph": s["speed_a"],
             "throttle_pct": s.get("throttle_a"), "drs_open": s.get("drs_a")}
            for s in samples[::5]
        ]
        trace_b = [
            {"distance_m": s["distance_m"], "speed_kph": s["speed_b"],
             "throttle_pct": s.get("throttle_b"), "drs_open": s.get("drs_b")}
            for s in samples[::5]
        ]

        strongest_fade = _strongest_comparative_full_throttle_fade(
            samples,
            clip_a,
            clip_b,
            driver_a,
            driver_b,
        )
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
            "speed_trace_a": trace_a,
            "speed_trace_b": trace_b,
            "energy_metrics_a": metrics_a,
            "energy_metrics_b": metrics_b,
            "straight_breakdown": straight_breakdown,
        }

    telemetry = get_lap_telemetry(round_number, session_type, driver_a, lap_number_a)
    samples = telemetry["telemetry"]
    lico = _infer_lift_and_coast_samples(samples)
    clip = _infer_clipping_windows(samples)
    metrics_a = _compute_energy_metrics(samples, lico, clip)
    straight_breakdown = _analyze_straights_energy(samples, None, clip, None, driver_a, None)
    trace_a = [
        {
            "distance_m": s["distance_m"],
            "speed_kph": s["speed_kph"],
            "throttle_pct": s.get("throttle_pct"),
            "drs_open": s.get("drs_open"),
        }
        for s in samples[::5]
    ]
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
        "speed_trace_a": trace_a,
        "speed_trace_b": None,
        "energy_metrics_a": metrics_a,
        "energy_metrics_b": None,
        "straight_breakdown": straight_breakdown,
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


def _corner_label(corner: dict | None) -> str | None:
    if not corner:
        return None
    label = f"Turn {corner['number']}"
    if corner.get("label"):
        label += corner["label"]
    return label


def _is_finite_distance(distance_m: int | float | None) -> bool:
    try:
        return distance_m is not None and math.isfinite(distance_m)
    except TypeError:
        return False


def _lap_region(distance_m: int | float | None) -> tuple[str, str]:
    if not _is_finite_distance(distance_m):
        return "Key part of the lap", "in a key part of the lap"
    if distance_m is None or distance_m < 1000:
        return "Early in the lap", "early in the lap"
    if distance_m < 3500:
        return "Middle of the lap", "in the middle of the lap"
    return "Late in the lap", "late in the lap"


def _base_location_context(distance_m: int | float | None) -> dict:
    label, plain = _lap_region(distance_m)
    return {
        "label": label,
        "plain": plain,
        "technical": plain,
        "phase": "lap_region",
        "distance_m": distance_m,
        "corner": None,
        "previous_corner": None,
        "next_corner": None,
    }


def _telemetry_location_context(round_number: int, distance_m: int | float | None, cause_type: str | None) -> dict:
    base = _base_location_context(distance_m)
    if not _is_finite_distance(distance_m):
        return base

    try:
        corners = get_circuit_corners(round_number)
    except Exception:
        return base

    valid_corners = sorted(
        [corner for corner in corners if corner.get("distance_m") is not None],
        key=lambda corner: corner["distance_m"],
    )
    if not valid_corners:
        return base

    previous_corner = None
    next_corner = None
    for corner in valid_corners:
        if corner["distance_m"] <= distance_m:
            previous_corner = corner
        if next_corner is None and corner["distance_m"] >= distance_m:
            next_corner = corner
    if previous_corner is None:
        previous_corner = valid_corners[-1]
    if next_corner is None:
        next_corner = valid_corners[0]

    nearest_corner = min(valid_corners, key=lambda corner: abs(corner["distance_m"] - distance_m))
    previous_label = _corner_label(previous_corner)
    next_label = _corner_label(next_corner)
    nearest_label = _corner_label(nearest_corner)
    cause = cause_type or ""

    context = {
        **base,
        "previous_corner": previous_corner,
        "next_corner": next_corner,
    }

    if cause == "braking":
        plain = f"in the braking zone into {next_label}"
        context.update({
            "label": f"Braking zone into {next_label}",
            "plain": plain,
            "technical": plain,
            "phase": "braking_zone",
            "corner": next_label,
        })
    elif cause == "minimum_speed":
        plain = f"through {nearest_label}"
        context.update({
            "label": f"Mid-corner at {nearest_label}",
            "plain": plain,
            "technical": plain,
            "phase": "mid_corner",
            "corner": nearest_label,
        })
    elif cause == "traction":
        plain = f"on the run out of {previous_label}"
        context.update({
            "label": f"Exit of {previous_label}",
            "plain": plain,
            "technical": plain,
            "phase": "corner_exit",
            "corner": previous_label,
        })
    elif cause in ("straight_line_speed", "straight_line_speed_energy_limited"):
        plain = f"on the straight between {previous_label} and {next_label}"
        context.update({
            "label": f"Straight between {previous_label} and {next_label}",
            "plain": plain,
            "technical": plain,
            "phase": "straight",
            "corner": None,
        })

    return context


def _get_comparable_qualifying_laps(round_number: int, driver_codes: list[str], session_type: str = "Q"):
    session = _load_session(round_number, session_type, laps=True, telemetry=False, weather=False, messages=True)
    try:
        split = session.laps.split_qualifying_sessions()
        segments = [("Q3", split[2]), ("Q2", split[1]), ("Q1", split[0])]
    except Exception:
        if session_type.upper() == "Q":
            raise  # real data error for regular qualifying
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


def _summarize_telemetry_battle(samples: list[dict], faster_driver: str, driver_a: str, driver_b: str) -> dict | None:
    if not samples:
        return None

    faster_is_a = faster_driver == driver_a

    def sample_favors_faster(sample) -> bool:
        delta_speed = sample.get("delta_speed") or 0
        return (delta_speed > 0) if faster_is_a else (delta_speed < 0)

    def _fast(sample, key):
        suffix = "a" if faster_is_a else "b"
        return sample.get(f"{key}_{suffix}")

    def _slow(sample, key):
        suffix = "b" if faster_is_a else "a"
        return sample.get(f"{key}_{suffix}")

    def _full_throttle(sample) -> bool:
        return (
            (_fast(sample, "throttle") or 0) >= 95
            and (_slow(sample, "throttle") or 0) >= 95
            and not (_fast(sample, "brake") or False)
            and not (_slow(sample, "brake") or False)
        )

    speed_candidates = [
        s for s in samples
        if sample_favors_faster(s)
        and abs(s.get("delta_speed") or 0) >= 5
        and _full_throttle(s)
    ]
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
        and not _full_throttle(s)
        and (
            ((s.get("throttle_a") or 0) < 40 and not s.get("brake_a"))
            or ((s.get("throttle_b") or 0) < 40 and not s.get("brake_b"))
        )
    ]
    traction_candidates = [
        s for s in samples
        if sample_favors_faster(s)
        and not _full_throttle(s)
        and (_fast(s, "throttle") or 0) >= 70
        and ((_fast(s, "throttle") or 0) - (_slow(s, "throttle") or 0)) >= 15
        and not (_fast(s, "brake") or False)
    ]

    strongest_speed = max(speed_candidates, key=lambda s: abs(s.get("delta_speed") or 0), default=None)
    strongest_braking = max(braking_candidates, key=lambda s: abs(s.get("delta_speed") or 0), default=None)
    strongest_min_speed = max(min_speed_candidates, key=lambda s: abs(s.get("delta_speed") or 0), default=None)
    strongest_traction = max(traction_candidates, key=lambda s: abs(s.get("delta_speed") or 0), default=None)

    # Rank all found cause types by their peak speed delta magnitude
    ranked = []
    for cause_type, sample in (
        ("straight_line_speed", strongest_speed),
        ("braking", strongest_braking),
        ("minimum_speed", strongest_min_speed),
        ("traction", strongest_traction),
    ):
        if sample is None:
            continue
        ranked.append({
            "cause_type": cause_type,
            "magnitude": abs(sample.get("delta_speed") or 0),
            "distance_m": sample.get("distance_m"),
            "delta_speed_kph": sample.get("delta_speed"),
            "throttle_a": sample.get("throttle_a"),
            "throttle_b": sample.get("throttle_b"),
            "brake_a": sample.get("brake_a"),
            "brake_b": sample.get("brake_b"),
            "gear_a": sample.get("gear_a"),
            "gear_b": sample.get("gear_b"),
        })

    ranked.sort(key=lambda x: x["magnitude"], reverse=True)
    top_causes = ranked[:3]

    if not top_causes:
        return None

    return {"top_causes": top_causes}


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


def _downsample_track_map(samples: list[dict], *, step: int = 100) -> list[dict]:
    if not samples:
        return []
    reduced = []
    last_distance = None
    for sample in samples:
        distance = sample.get("distance_m")
        x = sample.get("x")
        y = sample.get("y")
        if distance is None or x is None or y is None:
            continue
        if last_distance is None or distance - last_distance >= step:
            reduced.append({
                "distance_m": distance,
                "x": x,
                "y": y,
            })
            last_distance = distance

    final = samples[-1]
    final_distance = final.get("distance_m")
    if (
        reduced
        and final_distance != reduced[-1]["distance_m"]
        and final.get("x") is not None
        and final.get("y") is not None
    ):
        reduced.append({
            "distance_m": final_distance,
            "x": final.get("x"),
            "y": final.get("y"),
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

    # intervals arrive sorted ascending (earliest first) from get_intervals
    parsed = [_parse_gap(row.get("gap_to_leader")) for row in intervals]
    valid = [value for value in parsed if value is not None]
    if not valid:
        latest = intervals[-1]  # most recent entry
        return {
            "latest_gap_to_leader": latest.get("gap_to_leader"),
            "latest_interval": latest.get("interval"),
            "sample_count": len(intervals),
        }

    earliest_gap = valid[0]   # first non-None = chronologically earliest
    latest_gap = valid[-1]    # last non-None = chronologically most recent
    min_gap = min(valid)
    max_gap = max(valid)
    trend = "stable"
    if latest_gap > earliest_gap + 0.75:
        trend = "dropping_back"
    elif latest_gap < earliest_gap - 0.75:
        trend = "closing"

    return {
        "latest_gap_to_leader": intervals[-1].get("gap_to_leader"),  # most recent raw value
        "latest_interval": intervals[-1].get("interval"),
        "sample_count": len(intervals),
        "earliest_gap_to_leader_s": round(earliest_gap, 3),
        "latest_gap_to_leader_s": round(latest_gap, 3),
        "min_gap_to_leader_s": round(min_gap, 3),
        "max_gap_to_leader_s": round(max_gap, 3),
        "trend": trend,
    }


def analyze_qualifying_battle(round_number: int, driver_a: str, driver_b: str, session_type: str = "Q") -> dict:
    """
    Backend-derived causal summary for a qualifying battle.
    Explains where the time was gained and the most likely mechanism.
    """
    session, compared_segment, chosen_laps = _get_comparable_qualifying_laps(round_number, [driver_a, driver_b], session_type)
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
        "session": session_type.upper(),
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
            session_type,
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
            session_type,
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

    # Detect teammate comparison — same car so the analysis framing changes
    _da_info = _resolve_driver(driver_a)
    _db_info = _resolve_driver(driver_b)
    is_teammate_comparison = (
        _da_info is not None
        and _db_info is not None
        and bool(_da_info.get("team"))
        and _da_info.get("team") == _db_info.get("team")
    )

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
    sector_boundary_distances = telemetry.get("sector_boundary_distances", [None, None]) if telemetry else [None, None]
    telemetry_summary = _summarize_telemetry_battle(comparison_samples, faster_driver, driver_a_code, driver_b_code)
    top_causes = (telemetry_summary.get("top_causes") or []) if telemetry_summary else []

    def _sector_for_distance(dist_m):
        if dist_m is None or sector_boundary_distances[0] is None:
            return None
        if dist_m <= sector_boundary_distances[0]:
            return "sector1"
        if sector_boundary_distances[1] is None or dist_m <= sector_boundary_distances[1]:
            return "sector2"
        return "sector3"

    # For teammates: straight-line speed reflects same PU/aero — deprioritise it so
    # the analysis focuses on braking technique, minimum speed, and traction where
    # driving style and setup divergence actually show up.
    earlier_braker = driver_b_code if faster_driver == driver_a_code else driver_a_code

    def _specific_location_plain(location_context: dict | None) -> str | None:
        if not location_context or location_context.get("phase") == "lap_region":
            return None
        return location_context.get("plain")

    def _specific_location_label(location_context: dict | None) -> str | None:
        if not location_context or location_context.get("phase") == "lap_region":
            return None
        return location_context.get("label")

    def _location_phrase(dist: int | None, location_context: dict | None = None) -> str:
        readable_location = _specific_location_plain(location_context)
        return f" {readable_location}" if readable_location else (f" around {dist}m" if dist is not None else "")

    def _cause_explanation(ct: str, dist: int | None, location_context: dict | None = None) -> str:
        loc = _location_phrase(dist, location_context)
        if ct == "straight_line_speed":
            if is_teammate_comparison:
                return (
                    f"There's a straight-line speed delta{loc} — on identical machinery this likely reflects "
                    f"a setup trim difference (wing angle, cooling) or DRS timing rather than "
                    f"a meaningful car performance gap."
                )
            return (
                f"{faster_driver} carries more speed at full throttle late on the straight{loc}, "
                f"opening the gap before the braking zone."
            )
        if ct == "straight_line_speed_energy_limited":
            return (
                f"Late-straight deployment{loc}: {slower_driver} fades while still full throttle, "
                f"so {faster_driver} keeps accelerating harder before the next braking zone."
            )
        if ct == "braking":
            if is_teammate_comparison:
                return (
                    f"Braking technique is the key difference{loc}: {earlier_braker} commits to the brake "
                    f"earlier while {faster_driver} trails the braking point and carries more entry speed. "
                    f"On identical hardware this is a pure driving style call."
                )
            return (
                f"Corner entry{loc}: {earlier_braker} is already on the brake while "
                f"{faster_driver} is still carrying speed into the zone."
            )
        if ct == "minimum_speed":
            if is_teammate_comparison:
                return (
                    f"Mid-corner minimum speed{loc}: {faster_driver} gives up less speed at the direction change. "
                    f"Between teammates this points to setup divergence (downforce level, diff, ride height) "
                    f"or a conscious style difference through the apex — not a car advantage."
                )
            return (
                f"{faster_driver} gives up less speed mid-corner{loc} and exits with more momentum."
            )
        if ct == "traction":
            if is_teammate_comparison:
                return (
                    f"Traction on exit{loc}: {faster_driver} gets back to full throttle earlier. "
                    f"Between teammates this usually comes down to throttle application technique "
                    f"or diff settings — same rear end, different commitment level."
                )
            return (
                f"Traction on exit{loc}: {faster_driver} gets back to full speed earlier "
                f"and carries that advantage down the following straight."
            )
        return "Mixed advantages — no single dominant mechanism."

    energy_relevant = False
    energy_reason = None
    energy_context_explanation = None
    strongest_fade = ((energy.get("comparative_signal") or {}) if energy else {}).get("strongest_full_throttle_speed_fade")
    if strongest_fade:
        delta_speed = strongest_fade.get("delta_speed_kph") or 0
        faded_driver = driver_a_code if delta_speed < 0 else driver_b_code
        if faded_driver == slower_driver:
            energy_relevant = True
            energy_distance = strongest_fade.get("distance_m")
            energy_reason = (
                f"{slower_driver} shows the strongest late-straight full-throttle speed fade around "
                f"{energy_distance}m, which is consistent with clipping or running out of deployment earlier."
            )
            energy_context_explanation = (
                "Under the 2026 rules the electrical contribution is much larger, so if one car reaches the taper in deployment earlier, "
                "it can remain flat-out but stop accelerating as hard late on the straight."
            )
            energy_cause = {
                "cause_type": "straight_line_speed_energy_limited",
                "magnitude": abs(delta_speed),
                "rank_weight": abs(delta_speed) * 1.15,
                "distance_m": energy_distance,
                "delta_speed_kph": delta_speed,
                "throttle_a": None,
                "throttle_b": None,
                "brake_a": False,
                "brake_b": False,
                "gear_a": None,
                "gear_b": None,
            }
            non_energy_causes = [
                tc for tc in top_causes
                if tc.get("cause_type") != "straight_line_speed"
                or abs((tc.get("distance_m") or 0) - (energy_distance or 0)) > 300
            ]
            reranked_causes = [energy_cause, *non_energy_causes]
            reranked_causes.sort(key=lambda tc: tc.get("rank_weight", tc.get("magnitude", 0)), reverse=True)
            top_causes = reranked_causes[:3]

    primary_cause = top_causes[0] if top_causes else None
    decisive_distance = primary_cause["distance_m"] if primary_cause else None
    cause_type = primary_cause["cause_type"] if primary_cause else "mixed"
    primary_location_context = (
        _telemetry_location_context(round_number, primary_cause["distance_m"], primary_cause["cause_type"])
        if primary_cause else None
    )
    cause_explanation = _cause_explanation(
        cause_type,
        primary_cause["distance_m"] if primary_cause else None,
        primary_location_context,
    )

    # Build multi-cause explanation list (up to 3 mechanisms with their telemetry evidence)
    cause_explanations = []
    for i, tc in enumerate(top_causes):
        location_context = (
            primary_location_context
            if i == 0 and primary_location_context is not None
            else _telemetry_location_context(round_number, tc["distance_m"], tc["cause_type"])
        )
        cause_explanations.append({
            "cause_type": tc["cause_type"],
            "rank": i + 1,
            "distance_m": tc["distance_m"],
            "delta_speed_kph": tc["delta_speed_kph"],
            "gear_a": tc.get("gear_a"),
            "gear_b": tc.get("gear_b"),
            "sector": _sector_for_distance(tc["distance_m"]),
            "location_context": location_context,
            "explanation": _cause_explanation(tc["cause_type"], tc["distance_m"], location_context),
        })

    decisive_corner = _nearest_corner_label(round_number, decisive_distance)

    strongest_evidence = [
        f"Overall qualifying gap: {abs(overall_gap):.3f}s in favour of {faster_driver}.",
    ]
    if decisive_sector_gap is not None:
        strongest_evidence.append(f"{decisive_sector} accounts for {abs(decisive_sector_gap):.3f}s of the gap.")
    for i, tc in enumerate(top_causes):
        prefix = "Primary" if i == 0 else ("Secondary" if i == 1 else "Tertiary")
        strongest_evidence.append(
            f"{prefix} mechanism — {tc['cause_type']}: "
            f"{abs(tc['delta_speed_kph']):.1f} kph speed separation"
            f"{_location_phrase(tc.get('distance_m'), cause_explanations[i]['location_context'] if i < len(cause_explanations) else None)}."
        )
    if energy_reason:
        strongest_evidence.append(energy_reason)
    if energy_context_explanation:
        strongest_evidence.append(energy_context_explanation)

    zone_summary = None
    if primary_cause:
        location_bits = []
        primary_sector = _sector_for_distance(primary_cause.get("distance_m"))
        if primary_sector:
            location_bits.append(primary_sector.replace("sector", "Sector "))
        elif decisive_sector:
            location_bits.append(decisive_sector)
        primary_location_label = _specific_location_label(primary_location_context)
        primary_location_plain = _specific_location_plain(primary_location_context)
        if primary_location_label:
            location_bits.append(primary_location_label)
        elif decisive_corner:
            location_bits.append(f"near {decisive_corner}")
        elif decisive_distance is not None:
            location_bits.append(f"around {decisive_distance}m")
        advantage_location = (
            f" {primary_location_plain}"
            if primary_location_plain
            else (f" at roughly {primary_cause['distance_m']}m" if primary_cause.get("distance_m") is not None else "")
        )
        zone_summary = (
            f"{' '.join(location_bits) if location_bits else 'Key zone'}: "
            f"{faster_driver} has a {abs(primary_cause['delta_speed_kph']):.1f} kph speed advantage "
            f"{advantage_location}."
        )
        strongest_evidence.append(zone_summary)

    # Driver style comparison — predicts where each driver's approach should gain/lose
    style_comparison = None
    try:
        style_comparison = get_comparison_framing(driver_a_code, driver_b_code)
    except Exception:
        pass

    speed_trace = _downsample_speed_trace(comparison_samples, step=200) if comparison_samples else []
    track_map = _downsample_track_map(comparison_samples, step=100) if comparison_samples else []
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
        "session": session_type.upper(),
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
        "is_teammate_comparison": is_teammate_comparison,
        "teammate_context": (
            f"Both drivers race for the same team ({_da_info.get('team')}), so differences "
            f"reflect driving style, setup divergence (wing angles, ride height, diff settings), "
            f"and technique — not car performance gaps."
        ) if is_teammate_comparison and _da_info else None,
        "cause_type": cause_type,
        "cause_explanation": cause_explanation,
        "cause_explanations": cause_explanations,
        "telemetry_summary": telemetry_summary,
        "energy_relevant": energy_relevant,
        "energy_reason": energy_reason,
        "energy_context_explanation": energy_context_explanation,
        "telemetry_available": telemetry is not None,
        "energy_available": energy is not None,
        "caveats": caveats,
        "strongest_evidence": strongest_evidence,
        "speed_trace": speed_trace,
        "track_map": track_map,
        "focus_window_trace": focus_window,
        "sector_boundary_distances": sector_boundary_distances,
        "sector_comparison": sector,
        "energy_analysis": energy,
        "style_comparison": style_comparison,
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


def get_circuit_track_map(round_number: int) -> dict:
    """
    GPS-derived circuit shape for visualization.
    Returns downsampled {x, y, distance_m} points from the fastest qualifying lap
    and sector boundary distances from marshal_sectors.
    Falls back to previous seasons if the current-year race hasn't happened yet.
    """
    schedule = fastf1.get_event_schedule(CURRENT_YEAR, include_testing=False)
    matching = schedule[schedule["RoundNumber"] == round_number]
    if matching.empty:
        raise ValueError(f"Round {round_number} not found in {CURRENT_YEAR} schedule")
    location = str(matching.iloc[0].get("Location", ""))

    def _try_load(year, gp_ref, session_type):
        try:
            s = fastf1.get_session(year, gp_ref, session_type)
            s.load(laps=True, telemetry=True, weather=False, messages=False)
            if s.laps is None or s.laps.empty:
                return None
            return s
        except Exception:
            return None

    session = None
    for session_type in ('Q', 'R'):
        session = _try_load(CURRENT_YEAR, round_number, session_type)
        if session is not None:
            break
        for year in (CURRENT_YEAR - 1, CURRENT_YEAR - 2, CURRENT_YEAR - 3):
            session = _try_load(year, location, session_type)
            if session is not None:
                break
        if session is not None:
            break

    if session is None:
        raise ValueError(f"No session data available for round {round_number}")

    laps = session.laps
    valid_laps = laps.dropna(subset=['LapTime'])
    if valid_laps.empty:
        raise ValueError(f"No valid laps for round {round_number}")

    fastest = _pick_fastest_lap(valid_laps)
    tel = fastest.get_telemetry().add_distance()

    if 'X' not in tel.columns or 'Y' not in tel.columns:
        raise ValueError(f"No GPS telemetry available for round {round_number}")

    dist_arr = tel['Distance'].to_numpy(dtype=float)
    x_arr = tel['X'].to_numpy(dtype=float)
    y_arr = tel['Y'].to_numpy(dtype=float)
    total_dist = float(dist_arr[-1])

    targets = np.arange(0, total_dist, 50.0)
    indices = np.clip(np.searchsorted(dist_arr, targets), 0, len(dist_arr) - 1)

    points = []
    for i, idx in enumerate(indices):
        x = float(x_arr[idx])
        y = float(y_arr[idx])
        if not (np.isnan(x) or np.isnan(y)):
            points.append({"x": round(x, 1), "y": round(y, 1), "distance_m": int(targets[i])})

    try:
        circuit_info = session.get_circuit_info()
        all_markers = _extract_track_markers(getattr(circuit_info, 'marshal_sectors', None))
        sector_boundaries = [
            {"number": m["number"], "distance_m": m["distance_m"]}
            for m in all_markers
            if m.get("number") is not None and m.get("distance_m") is not None
        ]
    except Exception:
        sector_boundaries = []

    return {
        "points": points,
        "sector_boundaries": sector_boundaries,
        "total_distance_m": int(total_dist),
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


def _fetch_year_classifications(year: int, session_type: str) -> list[dict]:
    session = str(session_type or "Q").strip().upper()
    endpoint = "qualifying" if session == "Q" else "results"
    resp = requests.get(
        f"{JOLPICA_BASE}/{year}/{endpoint}.json?limit=1000",
        timeout=20,
    )
    resp.raise_for_status()
    races = resp.json()["MRData"]["RaceTable"]["Races"]

    classifications = []
    for race in races:
        rows = race.get("QualifyingResults" if endpoint == "qualifying" else "Results", [])
        if not rows:
            continue
        country = ((race.get("Circuit") or {}).get("Location") or {}).get("country", "")
        profile = get_circuit_profile(country, race.get("raceName", ""))
        if profile is None:
            continue
        entries = []
        for row in rows:
            position = _normalize_position(row.get("position"))
            if position is None:
                continue
            entries.append({
                "position": position,
                "team": (row.get("Constructor") or {}).get("name", ""),
                "driver": f"{(row.get('Driver') or {}).get('givenName', '')} {(row.get('Driver') or {}).get('familyName', '')}".strip(),
                "code": (row.get("Driver") or {}).get("code", ""),
            })
        if entries:
            classifications.append({
                "year": year,
                "round": _normalize_position(race.get("round")),
                "race_name": race.get("raceName", ""),
                "country": country,
                "circuit_key": profile.get("circuit_key"),
                "circuit_name": profile.get("circuit_name"),
                "character": profile.get("character"),
                "style_verdict": (profile.get("style_verdict") or {}).get("qualifier"),
                "downforce_level": profile.get("downforce_level"),
                "entries": entries,
            })
    return classifications


def _historical_team_matches(team_name: str, candidate: str) -> bool:
    needle = (team_name or "").lower().strip()
    haystack = (candidate or "").lower().strip()
    if not needle or not haystack:
        return False
    return needle in haystack or haystack in needle


def _confidence_from_samples(sample_count: int, year_count: int) -> str:
    if sample_count >= 8 and year_count >= 3:
        return "high"
    if sample_count >= 4 and year_count >= 2:
        return "medium"
    return "low"


def analyze_team_circuit_fit(
    team_name: str,
    years: list[int] | None = None,
    session_type: str = "Q",
) -> dict:
    """
    Derive a team's historical circuit-fit tendencies from real classifications.

    This does not claim the car is mechanically "a late-braking car". It compares
    the team's average result at each circuit archetype against that team's own
    season baseline, then reports where it over/under-performed.
    """
    if years is None:
        years = [y for y in range(CURRENT_YEAR - 3, CURRENT_YEAR) if y >= 1950]
    years = sorted({int(y) for y in years if int(y) < CURRENT_YEAR})
    if not years:
        raise ValueError("Provide at least one completed historical season.")

    session = str(session_type or "Q").strip().upper()
    if session not in {"Q", "R"}:
        raise ValueError("session_type must be Q or R.")

    team_races = []
    season_rows: dict[int, list[dict]] = {}
    matched_names: set[str] = set()
    fetch_errors = []

    for year in years:
        try:
            races = _fetch_year_classifications(year, session)
        except Exception as exc:
            fetch_errors.append({"year": year, "error": str(exc)})
            continue

        year_rows = []
        for race in races:
            team_entries = [
                entry for entry in race["entries"]
                if _historical_team_matches(team_name, entry.get("team", ""))
            ]
            if not team_entries:
                continue
            matched_names.update(entry.get("team", "") for entry in team_entries if entry.get("team"))
            avg_position = sum(entry["position"] for entry in team_entries) / len(team_entries)
            row = {
                "year": year,
                "race_name": race["race_name"],
                "country": race["country"],
                "circuit_key": race["circuit_key"],
                "circuit_name": race["circuit_name"],
                "character": race["character"],
                "style_verdict": race["style_verdict"],
                "downforce_level": race["downforce_level"],
                "avg_position": round(avg_position, 3),
                "cars_counted": len(team_entries),
                "drivers": [
                    {
                        "driver": entry.get("driver"),
                        "code": entry.get("code"),
                        "position": entry.get("position"),
                    }
                    for entry in team_entries
                ],
            }
            team_races.append(row)
            year_rows.append(row)
        if year_rows:
            season_rows[year] = year_rows

    if not team_races:
        raise ValueError(f"No historical {session} results found for team {team_name!r} in {years}.")

    season_baselines = {
        year: sum(row["avg_position"] for row in rows) / len(rows)
        for year, rows in season_rows.items()
        if rows
    }

    for row in team_races:
        baseline = season_baselines.get(row["year"])
        row["season_baseline_position"] = round(baseline, 3) if baseline is not None else None
        row["fit_delta_position"] = round(baseline - row["avg_position"], 3) if baseline is not None else None

    def _group_fit(key: str) -> list[dict]:
        grouped: dict[str, list[dict]] = {}
        for row in team_races:
            value = row.get(key)
            delta = row.get("fit_delta_position")
            if value is None or delta is None:
                continue
            grouped.setdefault(value, []).append(row)

        summaries = []
        for value, rows in grouped.items():
            years_seen = sorted({row["year"] for row in rows})
            avg_delta = sum(row["fit_delta_position"] for row in rows) / len(rows)
            summaries.append({
                key: value,
                "avg_fit_delta_position": round(avg_delta, 3),
                "interpretation": "overperforms" if avg_delta > 0.25 else ("underperforms" if avg_delta < -0.25 else "neutral"),
                "sample_count": len(rows),
                "years": years_seen,
                "confidence": _confidence_from_samples(len(rows), len(years_seen)),
                "examples": sorted(
                    [
                        {
                            "year": row["year"],
                            "race_name": row["race_name"],
                            "avg_position": row["avg_position"],
                            "season_baseline_position": row["season_baseline_position"],
                            "fit_delta_position": row["fit_delta_position"],
                        }
                        for row in rows
                    ],
                    key=lambda item: item["fit_delta_position"],
                    reverse=True,
                )[:3],
            })
        return sorted(summaries, key=lambda item: item["avg_fit_delta_position"], reverse=True)

    by_character = _group_fit("character")
    by_style_verdict = _group_fit("style_verdict")
    by_downforce_level = _group_fit("downforce_level")

    all_groups = [
        {"dimension": "character", **item} for item in by_character
    ] + [
        {"dimension": "style_verdict", **item} for item in by_style_verdict
    ] + [
        {"dimension": "downforce_level", **item} for item in by_downforce_level
    ]
    reliable_groups = [g for g in all_groups if g.get("sample_count", 0) >= 2]
    strongest_fit = max(reliable_groups, key=lambda g: g["avg_fit_delta_position"], default=None)
    weakest_fit = min(reliable_groups, key=lambda g: g["avg_fit_delta_position"], default=None)

    caveats = [
        "This is derived from classifications, not private setup or aerodynamic data.",
        "It blends car, drivers, operations, reliability, and race execution; it is a team-circuit tendency, not a pure car trait.",
    ]
    if max(years) <= CURRENT_YEAR - 1:
        caveats.append("Historical seasons are only a proxy for the current regulation package.")
    if fetch_errors:
        caveats.append("Some seasons could not be fetched and were excluded.")

    return {
        "team_query": team_name,
        "matched_team_names": sorted(matched_names),
        "session": session,
        "years": years,
        "season_baselines": {
            year: round(value, 3)
            for year, value in season_baselines.items()
        },
        "sample_count": len(team_races),
        "by_character": by_character,
        "by_style_verdict": by_style_verdict,
        "by_downforce_level": by_downforce_level,
        "strongest_fit": strongest_fit,
        "weakest_fit": weakest_fit,
        "race_samples": sorted(team_races, key=lambda row: (row["year"], row["race_name"])),
        "fetch_errors": fetch_errors,
        "method": "For each season, average the team's two-car classification at every profiled circuit, compare it with that team's season average, then aggregate the over/under-performance by circuit archetype.",
        "caveats": caveats,
    }


def _median(values: list[float]) -> float | None:
    clean = sorted(v for v in values if v is not None)
    if not clean:
        return None
    mid = len(clean) // 2
    if len(clean) % 2:
        return clean[mid]
    return (clean[mid - 1] + clean[mid]) / 2


def _profile_trait_summary(profile: dict) -> dict:
    corners = list((profile.get("corner_profiles") or {}).values())
    straights = profile.get("straight_profiles") or []
    lap_summary = profile.get("lap_summary") or {}

    def avg(key: str, rows: list[dict]) -> float | None:
        values = [row.get(key) for row in rows if row.get(key) is not None]
        return round(sum(values) / len(values), 3) if values else None

    return {
        "avg_entry_speed_kph": avg("entry_speed_kph", corners),
        "avg_apex_speed_kph": avg("apex_speed_kph", corners),
        "avg_exit_speed_kph": avg("exit_speed_kph", corners),
        "avg_braking_point_m": avg("braking_point_m", corners),
        "avg_straight_max_speed_kph": avg("max_speed_kph", straights),
        "full_throttle_pct": lap_summary.get("full_throttle_pct"),
        "braking_pct": lap_summary.get("braking_pct"),
        "coasting_pct": lap_summary.get("coasting_pct"),
    }


def analyze_team_telemetry_traits(
    round_number: int,
    team_name: str,
    session_type: str = "Q",
    field_limit: int = 10,
) -> dict:
    """
    Compare one team's fastest-lap telemetry traits against the field median.

    This characterizes visible behavior in a specific session: straight-line
    speed, minimum speed, exit speed, braking point, and throttle/brake usage.
    It still blends car, setup, and driver inputs.
    """
    resolved_team = _resolve_team(team_name)
    if resolved_team is None:
        raise ValueError(f"Team not found: {team_name!r}. Try the current constructor name.")

    drivers = get_drivers()
    team_codes = [
        (driver.get("code") or driver.get("driver_id", "").upper())
        for driver in drivers
        if (driver.get("team") or "").lower() == resolved_team.lower()
    ]
    if not team_codes:
        raise ValueError(f"No current-season drivers found for team {resolved_team!r}.")

    session = _load_session(round_number, session_type, laps=True, telemetry=False, weather=False, messages=False)
    fastest_rows = []
    for code in getattr(session, "drivers", []) or []:
        try:
            laps = _pick_driver(session.laps, str(code))
            if laps.empty:
                continue
            lap = _pick_fastest_lap(laps)
            lap_time = _safe_timedelta_seconds(lap.get("LapTime"))
            abbr = str(lap.get("Driver") or code).upper()
            if lap_time is not None:
                fastest_rows.append((abbr, lap_time))
        except Exception:
            continue

    if fastest_rows:
        field_codes = [code for code, _ in sorted(fastest_rows, key=lambda item: item[1])[:max(field_limit, len(team_codes))]]
    else:
        field_codes = [driver.get("code") for driver in drivers if driver.get("code")][:field_limit]

    for code in team_codes:
        if code not in field_codes:
            field_codes.append(code)

    driver_summaries = []
    errors = []
    for code in field_codes:
        try:
            profile = extract_corner_profiles(round_number, session_type, code)
            summary = _profile_trait_summary(profile)
            summary["driver"] = code
            summary["team"] = next((d.get("team") for d in drivers if (d.get("code") or "").upper() == code.upper()), None)
            summary["is_target_team"] = code.upper() in {c.upper() for c in team_codes}
            driver_summaries.append(summary)
        except Exception as exc:
            errors.append({"driver": code, "error": str(exc)})

    target_rows = [row for row in driver_summaries if row.get("is_target_team")]
    if not target_rows:
        raise ValueError(f"No telemetry profiles available for {resolved_team} in round {round_number} {session_type}.")

    metrics = [
        "avg_entry_speed_kph",
        "avg_apex_speed_kph",
        "avg_exit_speed_kph",
        "avg_braking_point_m",
        "avg_straight_max_speed_kph",
        "full_throttle_pct",
        "braking_pct",
        "coasting_pct",
    ]
    field_medians = {metric: _median([row.get(metric) for row in driver_summaries]) for metric in metrics}
    team_averages = {}
    deltas = {}
    for metric in metrics:
        values = [row.get(metric) for row in target_rows if row.get(metric) is not None]
        team_value = round(sum(values) / len(values), 3) if values else None
        baseline = field_medians.get(metric)
        team_averages[metric] = team_value
        deltas[metric] = round(team_value - baseline, 3) if team_value is not None and baseline is not None else None

    trait_flags = []
    if (deltas.get("avg_straight_max_speed_kph") or 0) >= 2.0:
        trait_flags.append("straight_line_speed")
    if (deltas.get("avg_apex_speed_kph") or 0) >= 1.5:
        trait_flags.append("high_minimum_speed")
    if (deltas.get("avg_exit_speed_kph") or 0) >= 1.5:
        trait_flags.append("corner_exit_traction")
    if (deltas.get("avg_braking_point_m") or 0) >= 5.0:
        trait_flags.append("late_braking")
    if (deltas.get("braking_pct") or 0) <= -2.0 and (deltas.get("coasting_pct") or 0) >= 1.5:
        trait_flags.append("coast_or_brake_avoidance")
    if not trait_flags:
        trait_flags.append("balanced_or_inconclusive")

    return {
        "team": resolved_team,
        "round_number": round_number,
        "session": str(session_type).upper(),
        "event": getattr(session, "event", {}).get("EventName") if hasattr(session, "event") else None,
        "team_codes": team_codes,
        "field_codes": field_codes,
        "field_sample_count": len(driver_summaries),
        "team_averages": team_averages,
        "field_medians": field_medians,
        "deltas_vs_field_median": deltas,
        "trait_flags": trait_flags,
        "driver_summaries": driver_summaries,
        "errors": errors,
        "method": "Extract fastest-lap corner and straight profiles for the target team and a fastest-lap field sample, then compare team averages with the field median.",
        "caveats": [
            "This is session telemetry, so it blends car, setup, and driver execution.",
            "It is stronger than historical trend evidence for this specific round, but weaker than private team setup and sensor data.",
        ],
    }


def get_safety_car_periods(round_number: int, session_type: str) -> dict:
    """
    Find all Safety Car and Virtual Safety Car periods in a session.
    For each period: deployment lap/time, duration, and three pit-stop impact categories:
    - pitted_just_before: pitted in the final ~90s — SC immediately erased their gap
    - pitted_before_extended: pitted within ~5 laps before SC — paid full pit cost but SC
      neutralised the gap they were building on fresh tyres (the driver IS affected even
      though they didn't pit under it — rivals who pitted during the SC got a free stop)
    - pitted_during: free stop under SC
    Also includes strategic_crossings: explicit list of who was disadvantaged vs who benefited,
    with a plain-language note explaining the mechanism. Use this to answer questions about
    drivers being affected by an SC even when they didn't pit under it.
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

        # Pit stop impact — three categories:
        # pitted_just_before:     final ~90s before SC — pitted in the closing approach, SC immediately erased gap
        # pitted_before_extended: pitted within ~5 laps before SC — paid full pit cost, SC neutralised the gap
        #                         they were building on fresh tyres (the "Piastri case")
        # pitted_during:          pitted under SC — free stop, minimal track-position cost
        IMMEDIATE_LOOK_BACK_S = 90
        EXTENDED_LOOK_BACK_S = 450  # ~5 laps at ~90s/lap

        pitted_just_before = []
        pitted_before_extended = []
        pitted_during = []

        for driver_code in laps['Driver'].unique():
            for _, lap in _pick_driver(laps, str(driver_code)).iterrows():
                pit_in = lap.get('PitInTime')
                if pit_in is None or pd.isna(pit_in):
                    continue
                pit_s = pit_in.total_seconds()
                pit_lap = int(lap['LapNumber']) if pd.notna(lap.get('LapNumber')) else None
                entry = {
                    'driver': str(lap['Driver']),
                    'team': str(lap['Team']),
                    'lap': pit_lap,
                    'seconds_before_sc': round(start_s - pit_s, 1),
                }

                if (start_s - IMMEDIATE_LOOK_BACK_S) <= pit_s < start_s:
                    pitted_just_before.append(entry)
                elif (start_s - EXTENDED_LOOK_BACK_S) <= pit_s < (start_s - IMMEDIATE_LOOK_BACK_S):
                    pitted_before_extended.append(entry)
                elif end_s and start_s <= pit_s <= end_s:
                    pitted_during.append({
                        'driver': str(lap['Driver']),
                        'team': str(lap['Team']),
                        'lap': pit_lap,
                    })

        # Strategic crossings: drivers who paid full pit cost before SC but had rivals
        # get a free stop during SC — SC erased the gap advantage the early-stopper was building.
        # This is how a driver can be heavily affected by an SC even without pitting under it.
        strategic_crossings = []
        all_before = sorted(
            pitted_just_before + pitted_before_extended,
            key=lambda x: x['seconds_before_sc'],
        )
        for before in all_before:
            for during in pitted_during:
                if before['driver'] == during['driver']:
                    continue
                strategic_crossings.append({
                    'driver_disadvantaged': before['driver'],
                    'driver_advantaged': during['driver'],
                    'disadvantaged_pitted_lap': before['lap'],
                    'advantaged_pitted_lap': during['lap'],
                    'seconds_before_sc': before['seconds_before_sc'],
                    'note': (
                        f"{during['driver']} pitted under the SC (free stop) while "
                        f"{before['driver']} had already pitted {before['seconds_before_sc']:.0f}s before the SC "
                        f"(lap {before['lap']}). "
                        f"The SC neutralised the field gap {before['driver']} was building on fresh tyres, "
                        f"allowing {during['driver']} to emerge with similar tyre age at almost no track-position cost. "
                        f"{before['driver']} was directly affected by this SC even though they did not pit under it."
                    ),
                })

        period['pitted_just_before'] = sorted(pitted_just_before, key=lambda x: x['seconds_before_sc'])
        period['pitted_before_extended'] = sorted(pitted_before_extended, key=lambda x: x['seconds_before_sc'])
        period['pitted_during'] = pitted_during
        period['strategic_crossings'] = strategic_crossings

    def _sc_period_narrative(period: dict) -> str:
        sc_type = period.get('type', 'SafetyCar')
        lap = period.get('deployed_on_lap')
        lap_str = f" lap {lap}" if lap else ""
        just_before = [e['driver'] for e in period.get('pitted_just_before', [])]
        extended = [e['driver'] for e in period.get('pitted_before_extended', [])]
        during = [e['driver'] for e in period.get('pitted_during', [])]
        parts = []
        if just_before:
            parts.append(f"{', '.join(just_before)} pitted in the final ~90s before it (immediately disadvantaged — SC erased fresh-tyre gap)")
        if extended:
            parts.append(f"{', '.join(extended)} pitted 1–5 laps before it (paid full pit cost; rivals' free stop erased their fresh-tyre advantage)")
        if during:
            parts.append(f"{', '.join(during)} pitted under it (near-free stop)")
        body = "; ".join(parts) if parts else "no drivers significantly impacted around this period"
        return f"{sc_type}{lap_str}: {body}."

    for period in periods:
        period['period_narrative'] = _sc_period_narrative(period)

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

    return {
        'event': session.event['EventName'],
        'session': session_type.upper(),
        'sc_count': len([p for p in periods if p['type'] == 'SafetyCar']),
        'vsc_count': len([p for p in periods if p['type'] == 'VSC']),
        'periods': periods,
        'all_victims': all_victims,
        'all_beneficiaries': all_beneficiaries,
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
    Filter race laps: remove pit laps, yellow-flag/SC/VSC laps, and statistical outliers.
    Outlier filter uses IQR (Q3 + 1.5*IQR) instead of a flat median+5s threshold.
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
        # 2=yellow/VSC, 4=SC deployed, 5=red flag, 6=VSC deployed (FastF1 variants)
        if any(c in track_status for c in ('2', '4', '5', '6')):
            continue

        compound = str(lap.get('Compound') or 'UNKNOWN')
        tyre_age = lap.get('TyreLife')
        tyre_age = int(tyre_age) if tyre_age is not None and pd.notna(tyre_age) else None

        result.append({
            'lap_number': int(lap['LapNumber']),
            'lap_time_s': round(lt_s, 3),
            'compound':   compound,
            'tyre_age':   tyre_age,
        })

    if len(result) < 4:
        return result

    times = sorted(r['lap_time_s'] for r in result)
    n = len(times)
    q1 = times[n // 4]
    q3 = times[(3 * n) // 4]
    iqr = q3 - q1
    upper = q3 + 1.5 * iqr
    lower = max(0, q1 - 1.5 * iqr)

    return [r for r in result if lower <= r['lap_time_s'] <= upper]


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


def _fuel_correction_s_per_lap(circuit_length_km: float) -> float:
    """
    Circuit-specific fuel correction in seconds per lap.
    Longer circuits burn more fuel/lap but have fewer braking zones/km.
    Formula: 0.16 / (1 + 0.22 * circuit_km), clamped to [0.025, 0.090].
    Monaco 3.3 km → 0.070 s/lap; Monza 5.8 km → 0.042 s/lap.
    """
    raw = 0.16 / (1.0 + 0.22 * circuit_length_km)
    return round(max(0.025, min(0.090, raw)), 4)


def _fit_stint_degradation(
    clean_laps: list[dict],
    fuel_correction_s_per_lap: float | None = None,
    circuit_length_km: float | None = None,
) -> list[dict]:
    """
    Group clean laps by compound block, fit linear + quadratic regression per stint.
    Cold-tyre laps (tyre_age <= 2) are excluded from regression.
    Uses circuit-specific fuel correction when circuit_length_km is provided.
    Returns list of stint dicts including deg_rate_s_per_lap, pace_at_age_10_s, quad_coeff, cliff_lap_est.
    """
    if not clean_laps:
        return []

    if fuel_correction_s_per_lap is None:
        fuel_correction_s_per_lap = (
            _fuel_correction_s_per_lap(circuit_length_km)
            if circuit_length_km is not None
            else 0.04
        )

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
        all_laps = stint['laps']
        if len(all_laps) < 3:
            continue

        lap_nums  = [l['lap_number'] for l in all_laps]
        raw_times = [l['lap_time_s']  for l in all_laps]
        min_lap   = min(lap_nums)

        tyre_ages = [
            l.get('tyre_age') or (n - min_lap + 1)
            for l, n in zip(all_laps, lap_nums)
        ]

        fuel_corrected_all = [
            t + fuel_correction_s_per_lap * (n - min_lap)
            for t, n in zip(raw_times, lap_nums)
        ]

        # Exclude cold-tyre laps (tyre_age <= 2) from regression
        warm_laps = [
            (age, fc)
            for age, fc in zip(tyre_ages, fuel_corrected_all)
            if age > 2
        ]
        if len(warm_laps) < 2:
            warm_laps = list(zip(tyre_ages, fuel_corrected_all))

        reg_ages = [w[0] for w in warm_laps]
        reg_fc   = [w[1] for w in warm_laps]

        raw_slope, _, _     = _linear_regression(tyre_ages, raw_times)
        slope, intercept, r_sq = _linear_regression(reg_ages, reg_fc)

        pace_at_age_1  = round(slope * 1  + intercept, 3)
        pace_at_age_10 = round(slope * 10 + intercept, 3)

        mean_t   = sum(fuel_corrected_all) / len(fuel_corrected_all)
        variance = sum((t - mean_t) ** 2 for t in fuel_corrected_all) / len(fuel_corrected_all)
        std_dev  = round(variance ** 0.5, 3)

        positive_deg   = max(0.0, slope)
        total_deg_loss = round(positive_deg * len(all_laps), 3)

        # Quadratic (polynomial) fit on warm laps
        _poly_ages = np.array(reg_ages, dtype=float)
        _poly_fc   = np.array(reg_fc,   dtype=float)
        if len(_poly_ages) >= 4:
            quad_coeff_raw, lin_coeff_raw, intercept_raw = np.polyfit(_poly_ages, _poly_fc, 2)
        else:
            quad_coeff_raw, lin_coeff_raw, intercept_raw = 0.0, slope, intercept

        # Cliff: scan rolling windows; cliff is where local slope first exceeds
        # 2x the median rolling slope (robust to parabola vertex location).
        cliff_lap_est = None
        if len(reg_ages) >= 6 and quad_coeff_raw > 0.001:
            window = max(3, len(reg_ages) // 4)
            win_slopes = []
            for i in range(len(reg_ages) - window + 1):
                seg_a = reg_ages[i:i + window]
                seg_f = reg_fc[i:i + window]
                s, _, _ = _linear_regression(seg_a, seg_f)
                win_slopes.append((reg_ages[i], s))
            if win_slopes:
                sorted_slopes = sorted(s for _, s in win_slopes)
                median_slope = sorted_slopes[len(sorted_slopes) // 2]
                threshold_slope = 2.0 * max(median_slope, 0.02)
                for age, s in win_slopes:
                    if s > threshold_slope:
                        cliff_lap_est = int(round(age))
                        break

        scatter_data = [
            {'tyre_age': age, 'lap_time_s': fc, 'lap_number': ln}
            for age, fc, ln in zip(tyre_ages, fuel_corrected_all, lap_nums)
        ]
        reg_line = [
            {'tyre_age': age, 'predicted_s': round(slope * age + intercept, 3)}
            for age in sorted(set(reg_ages))
        ]

        cold_excluded = len(all_laps) - len(warm_laps)

        results.append({
            'compound':                            stint['compound'],
            'lap_count':                           len(all_laps),
            'lap_numbers':                         lap_nums,
            'avg_raw_pace_s':                      round(sum(raw_times) / len(raw_times), 3),
            'raw_pace_trend_s_per_lap':            round(raw_slope, 4),
            'fuel_burn_gain_assumption_s_per_lap': fuel_correction_s_per_lap,
            'deg_rate_s_per_lap':                  round(slope, 4),
            'positive_deg_rate_s_per_lap':         round(positive_deg, 4),
            'total_deg_loss_s':                    total_deg_loss,
            'fuel_corrected_pace_at_age_1_s':      pace_at_age_1,
            'pace_at_age_10_s':                    pace_at_age_10,
            'r_squared':                           round(r_sq, 3),
            'consistency_std_dev_s':               std_dev,
            'cold_laps_excluded_from_reg':         cold_excluded,
            'quad_coeff':                          round(float(quad_coeff_raw), 6),
            'cliff_lap_est':                       cliff_lap_est,
            'scatter_data':                        scatter_data,
            'regression_line':                     reg_line,
            'ranking_basis': (
                "deg_rate_s_per_lap is the fuel-corrected slope on warm laps (tyre_age > 2). "
                "pace_at_age_10_s is mid-stint reference pace — use for cross-driver comparison. "
                "quad_coeff > 0 signals accelerating degradation; cliff_lap_est estimates when."
            ),
        })

    return results


def _summarize_tyre_management(stints: list[dict]) -> dict | None:
    if not stints:
        return None
    total = sum(s.get('lap_count', 0) for s in stints)
    if total <= 0:
        return None

    # Group by compound — deg rates are only meaningful within the same compound.
    by_compound: dict[str, list[dict]] = {}
    for s in stints:
        comp = (s.get('compound') or 'UNKNOWN').upper()
        by_compound.setdefault(comp, []).append(s)

    per_compound: dict[str, dict] = {}
    for comp, comp_stints in by_compound.items():
        comp_laps = sum(s.get('lap_count', 0) for s in comp_stints)
        if comp_laps <= 0:
            continue

        def _wt(key: str) -> float | None:
            rows = [(s.get(key), s.get('lap_count', 0)) for s in comp_stints
                    if isinstance(s.get(key), (int, float)) and s.get('lap_count', 0) > 0]
            w = sum(weight for _, weight in rows)
            return sum(v * weight for v, weight in rows) / w if w > 0 else None

        total_deg_loss = sum(
            s.get('total_deg_loss_s', 0) for s in comp_stints
            if isinstance(s.get('total_deg_loss_s'), (int, float))
        )
        per_compound[comp] = {
            'lap_count': comp_laps,
            'deg_rate_s_per_lap': round(_wt('deg_rate_s_per_lap'), 4) if _wt('deg_rate_s_per_lap') is not None else None,
            'positive_deg_rate_s_per_lap': round(_wt('positive_deg_rate_s_per_lap'), 4) if _wt('positive_deg_rate_s_per_lap') is not None else None,
            'total_deg_loss_s': round(total_deg_loss, 2),
            'r_squared': round(_wt('r_squared'), 3) if _wt('r_squared') is not None else None,
        }

    # Consistency (lap-to-lap spread) is not compound-specific — aggregate across all stints
    cons_rows = [(s.get('consistency_std_dev_s'), s.get('lap_count', 0)) for s in stints
                 if isinstance(s.get('consistency_std_dev_s'), (int, float)) and s.get('lap_count', 0) > 0]
    cons_laps = sum(w for _, w in cons_rows)
    consistency = sum(v * w for v, w in cons_rows) / cons_laps if cons_laps > 0 else None

    total_deg_loss_all = round(sum(
        v['total_deg_loss_s'] for v in per_compound.values()
        if isinstance(v.get('total_deg_loss_s'), (int, float))
    ), 2)

    # Cross-compound weighted averages for top-level summary
    def _wt_all(key: str) -> float | None:
        rows = [(s.get(key), s.get('lap_count', 0)) for s in stints
                if isinstance(s.get(key), (int, float)) and s.get('lap_count', 0) > 0]
        w = sum(weight for _, weight in rows)
        return sum(v * weight for v, weight in rows) / w if w > 0 else None

    w_deg = _wt_all('positive_deg_rate_s_per_lap')
    w_r2 = _wt_all('r_squared')

    return {
        'total_modelled_laps': total,
        'per_compound': per_compound,
        'total_deg_loss_all_stints_s': total_deg_loss_all,
        'weighted_deg_rate_s_per_lap': round(w_deg, 4) if w_deg is not None else None,
        'weighted_consistency_std_dev_s': round(consistency, 3) if consistency is not None else None,
        'weighted_r_squared': round(w_r2, 3) if w_r2 is not None else None,
        'score_explanation': (
            "R² is the trust level for the deg rate fit — higher means the linear trend explains more of "
            "the lap-time variance. weighted_deg_rate_s_per_lap is lap-count-weighted across all compounds. "
            "Deg rates are compound-specific — only compare stints on the same compound."
        ),
        'note': (
            "Deg rates are compound-specific — only compare stints on the same compound. "
            "Lower positive_deg_rate_s_per_lap means less tyre performance loss per lap within that compound. "
            "total_deg_loss_all_stints_s is the total time lost to tyre wear across ALL stints combined. "
            "consistency_std_dev_s is lap-to-lap spread around the deg trend."
        ),
    }


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

        # Use positive_deg_rate (clamped at 0) so delta reflects real tyre wear, not noise artifacts
        deg_a = stint_a.get('positive_deg_rate_s_per_lap') or 0.0
        deg_b = sb.get('positive_deg_rate_s_per_lap') or 0.0
        pace_a = stint_a.get('pace_at_age_10_s', stint_a.get('fuel_corrected_pace_at_age_1_s'))
        pace_b = sb.get('pace_at_age_10_s', sb.get('fuel_corrected_pace_at_age_1_s'))

        aligned.append({
            'compound': comp_a,
            'stint_a': stint_a,
            'stint_b': sb,
            'deg_rate_delta': round(deg_a - deg_b, 4),  # positive = driver_a degrades faster
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
    tyre_management = _summarize_tyre_management(stints)
    weighted_pace = None
    if total_laps > 0 and stints:
        weighted_pace = round(
            sum(s.get('pace_at_age_10_s', s['fuel_corrected_pace_at_age_1_s']) * s['lap_count'] for s in stints) / total_laps,
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
        'tyre_management': tyre_management,
        'weighted_avg_fuel_corrected_pace_s': weighted_pace,
        'highest_degradation_stint': worst_stint,
        'lowest_degradation_stint': best_stint,
        'how_to_read': (
            "raw_pace_trend_s_per_lap is what the stopwatch did through the stint. deg_rate_s_per_lap adds back "
            "the expected fuel-burn gain, so positive values estimate tyre performance loss per lap; lower is "
            "better. consistency_std_dev_s is not time lost per lap; it is lap-to-lap spread around the trend. "
            "r_squared says how trustworthy the trend is."
        ),
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
    tyre_management_a = _summarize_tyre_management(stints_a)
    tyre_management_b = _summarize_tyre_management(stints_b)

    def _weighted_pace(stints: list[dict]) -> float | None:
        total = sum(s['lap_count'] for s in stints)
        if total == 0:
            return None
        return sum(s.get('pace_at_age_10_s', s['fuel_corrected_pace_at_age_1_s']) * s['lap_count']
                   for s in stints) / total

    pace_a = _weighted_pace(stints_a)
    pace_b = _weighted_pace(stints_b)
    overall_delta = round(pace_a - pace_b, 3) if pace_a is not None and pace_b is not None else None

    # Compute deg averages only from compound-matched aligned stints.
    # Cross-compound averaging is meaningless — soft and hard degrade at different baseline rates.
    if aligned:
        laps_a_matched = sum(a['stint_a'].get('lap_count', 1) for a in aligned)
        laps_b_matched = sum(a['stint_b'].get('lap_count', 1) for a in aligned)
        avg_deg_a = sum(a['stint_a'].get('positive_deg_rate_s_per_lap', 0) * a['stint_a'].get('lap_count', 1) for a in aligned) / laps_a_matched if laps_a_matched else None
        avg_deg_b = sum(a['stint_b'].get('positive_deg_rate_s_per_lap', 0) * a['stint_b'].get('lap_count', 1) for a in aligned) / laps_b_matched if laps_b_matched else None
    else:
        avg_deg_a = avg_deg_b = None
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
        'tyre_management_a': tyre_management_a,
        'tyre_management_b': tyre_management_b,
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
        'how_to_read_degradation': (
            "deg_rate_s_per_lap adds back the expected fuel-burn gain so the remaining slope estimates tyre "
            "performance loss per lap. Only compare deg rates between stints on the same compound — different "
            "compounds have different baseline rates and cannot be averaged together. "
            "avg_deg_rate_a/b_s_per_lap are lap-weighted averages across matched compounds only. "
            "Lower positive_deg_rate_s_per_lap means less tyre wear within that compound."
        ),
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


# ---------------------------------------------------------------------------
# Cornering load / grip utilisation analysis
# ---------------------------------------------------------------------------

def _compute_lateral_g(tel: pd.DataFrame) -> np.ndarray:
    """
    Derive lateral G from X/Y position: κ = |x'y'' - y'x''| / (x'²+y'²)^1.5 parameterised by distance.
    lat_G = v² * κ / 9.81.

    FastF1 X/Y coordinates are in units of 0.1m (decimeters). They must be converted to
    meters before computing curvature (otherwise κ is 10x too small and lat_G 10x too low).
    FastF1 linearly interpolates GPS (≈4 Hz) to the merged telemetry rate. Use Source=='pos'
    to select only actual GPS samples; the pos_step filter passes interpolated rows too.
    """
    s_full = tel['Distance'].to_numpy(dtype=float)
    x_full = tel['X'].to_numpy(dtype=float)
    y_full = tel['Y'].to_numpy(dtype=float)
    v_full = tel['Speed'].to_numpy(dtype=float)

    # Select only real GPS samples (Source == 'pos'); fall back to all samples if missing.
    if 'Source' in tel.columns:
        gps_idx = np.where(tel['Source'].to_numpy() == 'pos')[0]
    else:
        gps_idx = np.arange(len(x_full))
    if len(gps_idx) < 20:
        gps_idx = np.arange(len(x_full))

    # Convert coordinates from decimeters (FastF1 GPS units) to meters.
    x_u = x_full[gps_idx] * 0.1
    y_u = y_full[gps_idx] * 0.1
    s_u = s_full[gps_idx]

    # Smooth the sparse position data
    n = len(x_u)
    wl = min(15, n if n % 2 == 1 else n - 1)
    wl = max(wl, 5)
    if wl % 2 == 0:
        wl -= 1
    polyord = min(3, wl - 1)
    if n >= wl:
        x_sm = savgol_filter(x_u, window_length=wl, polyorder=polyord)
        y_sm = savgol_filter(y_u, window_length=wl, polyorder=polyord)
    else:
        x_sm, y_sm = x_u, y_u

    # Curvature parameterised by track distance → units of [1/m]
    dx = np.gradient(x_sm, s_u)
    dy = np.gradient(y_sm, s_u)
    ddx = np.gradient(dx, s_u)
    ddy = np.gradient(dy, s_u)

    denom = (dx**2 + dy**2) ** 1.5
    denom = np.where(denom < 1e-12, 1e-12, denom)
    kappa = np.abs(dx * ddy - dy * ddx) / denom
    kappa = np.clip(kappa, 0.0, 0.15)  # 0.15 rad/m ≈ 6.7m radius — tightest F1 hairpin

    # Interpolate kappa back to the full telemetry grid
    kappa_full = np.interp(s_full, s_u, kappa)

    v_mps = v_full / 3.6
    lat_g_raw = (v_mps**2) * kappa_full / 9.81
    lat_g_raw = np.clip(lat_g_raw, 0.0, 6.0)

    # Light final smoothing
    wl_f = min(15, len(lat_g_raw) if len(lat_g_raw) % 2 == 1 else len(lat_g_raw) - 1)
    if wl_f >= 5:
        lat_g = savgol_filter(lat_g_raw, window_length=wl_f, polyorder=2)
    else:
        lat_g = lat_g_raw

    return np.clip(lat_g, 0.0, 6.0)


def _compute_longitudinal_g(tel: pd.DataFrame) -> np.ndarray:
    """
    Derive longitudinal G from Speed channel: long_G = (dv/dt) / 9.81.
    Positive = accelerating, negative = braking.
    Falls back to zeros if Time column is missing.
    """
    n = len(tel)
    if 'Time' not in tel.columns or 'Speed' not in tel.columns or n < 3:
        return np.zeros(n)

    v_mps = tel['Speed'].to_numpy(dtype=float) / 3.6
    t_s = tel['Time'].dt.total_seconds().to_numpy(dtype=float)

    if not np.all(np.diff(t_s) >= 0):
        t_s = np.sort(t_s)

    long_g_raw = np.gradient(v_mps, t_s) / 9.81
    long_g_raw = np.clip(long_g_raw, -6.0, 4.0)

    wl = min(15, n if n % 2 == 1 else n - 1)
    wl = max(wl, 5)
    if wl % 2 == 0:
        wl -= 1
    if n >= wl:
        long_g = savgol_filter(long_g_raw, window_length=wl, polyorder=2)
    else:
        long_g = long_g_raw

    return np.clip(long_g, -6.0, 4.0)


_GGV_BIN_EDGES = np.array([0.0, 50.0, 100.0, 150.0, 200.0, 250.0, 300.0, 360.0])
_GGV_BIN_CENTERS = (_GGV_BIN_EDGES[:-1] + _GGV_BIN_EDGES[1:]) / 2.0


def _build_ggv_envelope(telemetry_frames: list) -> dict:
    """
    Build a speed-indexed friction ellipse.
    Accepts:
      - list of DataFrames → returns {'ALL': envelope_dict}
      - list of (DataFrame, compound_str) tuples → returns {compound: envelope_dict, 'ALL': envelope_dict}
    Falls back to _theoretical_ggv_envelope() for 'ALL' if fewer than 2 usable frames.
    """
    if telemetry_frames and isinstance(telemetry_frames[0], tuple):
        tagged = telemetry_frames
    else:
        tagged = [(df, 'ALL') for df in telemetry_frames]

    compound_data: dict[str, tuple[list, list, list]] = {}
    for tel, compound in tagged:
        if any(c not in tel.columns for c in ('Speed', 'X', 'Y', 'Time')) or len(tel) < 20:
            continue
        try:
            lat  = _compute_lateral_g(tel)
            long = _compute_longitudinal_g(tel)
            spd  = tel['Speed'].to_numpy(dtype=float)
        except Exception:
            continue
        if compound not in compound_data:
            compound_data[compound] = ([], [], [])
        compound_data[compound][0].append(lat)
        compound_data[compound][1].append(long)
        compound_data[compound][2].append(spd)

    def _build_single(lat_list, long_list, spd_list) -> dict:
        if len(lat_list) < 2:
            return _theoretical_ggv_envelope()
        lat_cat  = np.concatenate(lat_list)
        long_cat = np.concatenate(long_list)
        spd_cat  = np.concatenate(spd_list)
        n_bins = len(_GGV_BIN_EDGES) - 1
        lat_max      = np.zeros(n_bins)
        brake_max    = np.zeros(n_bins)
        throttle_max = np.zeros(n_bins)
        for i in range(n_bins):
            mask = (spd_cat >= _GGV_BIN_EDGES[i]) & (spd_cat < _GGV_BIN_EDGES[i + 1])
            if mask.sum() < 10:
                lat_max[i]      = float(_theoretical_max_g(np.array([_GGV_BIN_CENTERS[i]]))[0])
                brake_max[i]    = lat_max[i] * 1.1
                throttle_max[i] = lat_max[i] * 0.65
                continue
            lb = lat_cat[mask]
            lg = long_cat[mask]
            lat_max[i] = max(float(np.percentile(np.abs(lb), 95)), 0.5)
            braking  = -lg[lg < -0.1]
            throttle =  lg[lg >  0.1]
            brake_max[i]    = max(float(np.percentile(braking,  95)), 0.3) if len(braking)  >= 5 else lat_max[i] * 1.1
            throttle_max[i] = max(float(np.percentile(throttle, 95)), 0.2) if len(throttle) >= 5 else lat_max[i] * 0.65
        return {'lat_max': lat_max, 'brake_max': brake_max,
                'throttle_max': throttle_max, 'speed_bins': _GGV_BIN_CENTERS}

    result = {}
    all_lat, all_long, all_spd = [], [], []
    for compound, (lat_l, long_l, spd_l) in compound_data.items():
        result[compound] = _build_single(lat_l, long_l, spd_l)
        all_lat.extend(lat_l)
        all_long.extend(long_l)
        all_spd.extend(spd_l)

    if 'ALL' not in result:
        result['ALL'] = _build_single(all_lat, all_long, all_spd)

    return result if result else {'ALL': _theoretical_ggv_envelope()}


def _theoretical_ggv_envelope() -> dict:
    """Fallback GGV envelope from the theoretical max lateral formula."""
    lat = _theoretical_max_g(_GGV_BIN_CENTERS)
    return {'lat_max': lat, 'brake_max': lat * 1.1,
            'throttle_max': lat * 0.65, 'speed_bins': _GGV_BIN_CENTERS}


def _ggv_ceiling_at_speed(speed_kph: np.ndarray, envelope: dict) -> tuple:
    """Interpolate (lat_max, brake_max, throttle_max) arrays for given speed array."""
    bins = envelope['speed_bins']
    return (
        np.interp(speed_kph, bins, envelope['lat_max']),
        np.interp(speed_kph, bins, envelope['brake_max']),
        np.interp(speed_kph, bins, envelope['throttle_max']),
    )


def _bravery_score(envelope_time: float | None,
                   throttle_acc: float | None,
                   entry_bravery: float | None) -> float:
    """
    Composite bravery metric (0–100 range).
    Weights: throttle acceptance 40 %, envelope time 35 %, entry bravery 25 %.
    """
    raw = (
        0.35 * (envelope_time or 0.0) +
        0.40 * (throttle_acc or 0.0) +
        0.25 * (entry_bravery or 0.0)
    )
    return round(max(0.0, min(100.0, raw)), 1)


def _theoretical_max_g(speed_kph: np.ndarray) -> np.ndarray:
    """
    Speed-dependent theoretical max lateral G for a 2025-spec F1 car.
    Mechanical grip floor ~1.3G at standstill; aerodynamic downforce adds ~0.014G per kph.
    At 300 kph: ~5.5G.
    """
    return np.maximum(1.3, 1.3 + speed_kph * 0.014)


def _detect_corners(lat_g: np.ndarray, dist: np.ndarray,
                    threshold: float | None = None, min_samples: int = 5) -> list[tuple[int, int]]:
    """
    Return list of (start_idx, end_idx) index pairs for each cornering event.
    Threshold is adaptive: 25% of observed peak G, clamped to [0.4, 0.8].
    This handles both slow-corner circuits (high peak G, 0.8 works) and
    fast-sweeper circuits (lower computed G, needs lower threshold).
    """
    if threshold is None:
        peak = float(lat_g.max())
        threshold = float(np.clip(0.25 * peak, 0.4, 0.8))

    in_corner = lat_g >= threshold
    corners = []
    start = None
    for i, flag in enumerate(in_corner):
        if flag and start is None:
            start = i
        elif not flag and start is not None:
            if i - start >= min_samples:
                corners.append((start, i - 1))
            start = None
    if start is not None and len(lat_g) - start >= min_samples:
        corners.append((start, len(lat_g) - 1))
    return corners


def _corner_metrics(lat_g: np.ndarray, long_g: np.ndarray, speed_kph: np.ndarray,
                    dist: np.ndarray, start: int, end: int,
                    envelope: dict | None = None,
                    throttle: np.ndarray | None = None) -> dict:
    seg_g = lat_g[start:end + 1]
    seg_lg = long_g[start:end + 1]
    seg_v = speed_kph[start:end + 1]
    seg_dist = dist[start:end + 1]

    apex_idx_local = int(np.argmin(seg_v))  # apex = min speed
    peak_idx_local = int(np.argmax(seg_g))

    # Trail brake: % of entry phase (start→apex) where lat>0.4G AND long<-0.3G simultaneously
    entry_end = max(apex_idx_local, 1)
    entry_lat = seg_g[:entry_end]
    entry_long = seg_lg[:entry_end]
    trail_mask = (entry_lat > 0.4) & (entry_long < -0.3)
    trail_brake_pct = round(float(np.mean(trail_mask) * 100), 1) if len(trail_mask) > 0 else 0.0

    # --- GGV-based metrics (only when envelope is provided) ---
    if envelope is not None:
        # Handle both old flat format (has 'lat_max') and new compound-keyed format
        _env = envelope if 'lat_max' in envelope else (envelope.get('ALL') or _theoretical_ggv_envelope())
        lat_ceil, brake_ceil, thr_ceil = _ggv_ceiling_at_speed(seg_v, _env)
        safe_lat = np.where(lat_ceil < 0.1, 0.1, lat_ceil)
        long_ceil = np.where(
            seg_lg < 0.0,
            np.where(brake_ceil < 0.1, 0.1, brake_ceil),
            np.where(thr_ceil < 0.1, 0.1, thr_ceil),
        )
        ggv_util = np.clip(
            np.sqrt((seg_g / safe_lat) ** 2 + (seg_lg / long_ceil) ** 2),
            0.0, 1.5,
        )
        ggv_util_pct = round(float(np.mean(ggv_util) * 100), 1)
        envelope_time_pct = round(float(np.mean(ggv_util >= 0.85) * 100), 1)

        # Throttle acceptance: exit phase (apex→end), full throttle + lateral load > 60% ceiling
        exit_s = max(apex_idx_local, 1)  # at least 1 so entry always has ≥1 sample
        exit_lat = seg_g[exit_s:]
        exit_lat_ceil = safe_lat[exit_s:]
        lat_loaded = (exit_lat / exit_lat_ceil) > 0.60
        if throttle is not None:
            seg_thr = throttle[start:end + 1]
            full_throttle = seg_thr[exit_s:] > 90.0
        else:
            full_throttle = seg_lg[exit_s:] > 0.3  # proxy: net positive acceleration
        ta_mask = full_throttle & lat_loaded
        throttle_acceptance_pct = round(float(np.mean(ta_mask) * 100), 1) if len(ta_mask) >= 2 else 0.0

        # Entry bravery: entry phase (start→apex), ggv_util >= 0.80 AND still braking
        entry_end_idx = min(max(apex_idx_local, 1), len(seg_g) - 1)
        entry_ggv = ggv_util[:entry_end_idx]
        entry_long = seg_lg[:entry_end_idx]
        brave_mask = (entry_ggv >= 0.80) & (entry_long < -0.3)
        entry_bravery_pct = round(float(np.mean(brave_mask) * 100), 1) if len(brave_mask) >= 2 else 0.0
    else:
        ggv_util_pct = None
        envelope_time_pct = None
        throttle_acceptance_pct = None
        entry_bravery_pct = None

    # count sign changes in d(lat_g) as a proxy for steering corrections
    dlg = np.gradient(seg_g)
    sign_changes = int(np.sum(np.diff(np.sign(dlg)) != 0))

    return {
        "entry_g": round(float(seg_g[0]), 3),
        "apex_g": round(float(seg_g[apex_idx_local]), 3),
        "peak_g": round(float(seg_g[peak_idx_local]), 3),
        "exit_g": round(float(seg_g[-1]), 3),
        "mean_g": round(float(np.mean(seg_g)), 3),
        "load_variance": round(float(np.std(seg_g)), 3),
        "correction_count": sign_changes,
        "trail_brake_pct": trail_brake_pct,
        "entry_dist_m": round(float(seg_dist[0]), 0),
        "exit_dist_m": round(float(seg_dist[-1]), 0),
        "ggv_util_pct": ggv_util_pct,
        "envelope_time_pct": envelope_time_pct,
        "throttle_acceptance_pct": throttle_acceptance_pct,
        "entry_bravery_pct": entry_bravery_pct,
    }


def _align_corners(
    corners_a: list[tuple[int, int]], dist_a: np.ndarray,
    corners_b: list[tuple[int, int]], dist_b: np.ndarray,
    tolerance_m: float = 200.0,
    speed_a: np.ndarray | None = None,
    speed_b: np.ndarray | None = None,
    apex_speed_tolerance_kph: float = 30.0,
) -> list[tuple[tuple, tuple]]:
    """Match corners from driver A to driver B by entry distance.
    Optionally validates that matched corners have similar apex speeds to avoid false pairings."""
    pairs = []
    used_b = set()
    for ca in corners_a:
        entry_a = dist_a[ca[0]]
        best = None
        best_diff = tolerance_m + 1
        for j, cb in enumerate(corners_b):
            if j in used_b:
                continue
            diff = abs(dist_b[cb[0]] - entry_a)
            if diff < best_diff:
                best_diff = diff
                best = j
        if best is None or best_diff > tolerance_m:
            continue
        if speed_a is not None and speed_b is not None:
            cb_matched = corners_b[best]
            apex_a = float(speed_a[ca[0] + np.argmin(speed_a[ca[0]:ca[1] + 1])])
            apex_b = float(speed_b[cb_matched[0] + np.argmin(speed_b[cb_matched[0]:cb_matched[1] + 1])])
            if abs(apex_a - apex_b) > apex_speed_tolerance_kph:
                continue
        pairs.append((ca, corners_b[best]))
        used_b.add(best)
    return pairs


def analyze_cornering_loads(round_number: int, session_type: str,
                             driver_a: str, driver_b: str,
                             lap_number_a: int | None = None,
                             lap_number_b: int | None = None) -> dict:
    """
    Compare two drivers' lateral G profiles and grip utilisation across all corners.

    Uses X/Y position telemetry to derive curvature-based lateral G (v²/R),
    then computes grip utilisation against a speed-dependent theoretical maximum.
    Identifies cornering events and computes per-corner statistics for both drivers.

    Returns summary stats, per-corner breakdown, and a human-readable narrative.

    Caveat: derived from GPS position (not steering angle or IMU), so ±5-10%
    absolute uncertainty. Comparative rankings are reliable; absolute values less so.
    """
    session = _load_session(
        round_number,
        session_type,
        laps=True,
        telemetry=True,
        weather=False,
        messages=_session_needs_race_control_messages(session_type),
    )

    code_a = driver_a.upper()
    code_b = driver_b.upper()

    def _get_lap(code: str, lap_num: int | None):
        laps = _pick_driver(session.laps, code)
        if laps.empty:
            raise ValueError(f"No data for driver {code!r}")
        if lap_num is not None:
            matching = laps[laps['LapNumber'] == lap_num]
            if matching.empty:
                raise ValueError(f"Lap {lap_num} not found for {code!r}")
            return matching.iloc[0]
        return _pick_fastest_lap(laps)

    lap_a = _get_lap(code_a, lap_number_a)
    lap_b = _get_lap(code_b, lap_number_b)

    tel_a = lap_a.get_telemetry().add_distance()
    tel_b = lap_b.get_telemetry().add_distance()

    # Require X/Y position columns
    for col in ('X', 'Y', 'Speed'):
        if col not in tel_a.columns or col not in tel_b.columns:
            raise ValueError(f"Telemetry missing column '{col}' — position data unavailable for this session.")

    dist_a = tel_a['Distance'].to_numpy(dtype=float)
    dist_b = tel_b['Distance'].to_numpy(dtype=float)
    spd_a = tel_a['Speed'].to_numpy(dtype=float)
    spd_b = tel_b['Speed'].to_numpy(dtype=float)

    lat_g_a = _compute_lateral_g(tel_a)
    lat_g_b = _compute_lateral_g(tel_b)
    long_g_a = _compute_longitudinal_g(tel_a)
    long_g_b = _compute_longitudinal_g(tel_b)

    # Build shared GGV envelope from fastest laps of both drivers in this session.
    def _collect_session_tels(code: str, n_laps: int = 6) -> list:
        laps_for_code = _pick_driver(session.laps, code)
        if laps_for_code.empty:
            return []
        valid = laps_for_code[laps_for_code['LapTime'].notna()].nsmallest(n_laps, 'LapTime')
        tels = []
        for _, lap_row in valid.iterrows():
            try:
                t = lap_row.get_telemetry().add_distance()
                if len(t) >= 20:
                    tels.append(t)
            except Exception:
                continue
        return tels

    envelope = _build_ggv_envelope(_collect_session_tels(code_a) + _collect_session_tels(code_b))

    throttle_a = tel_a['Throttle'].to_numpy(dtype=float) if 'Throttle' in tel_a.columns else None
    throttle_b = tel_b['Throttle'].to_numpy(dtype=float) if 'Throttle' in tel_b.columns else None

    corners_a = _detect_corners(lat_g_a, dist_a)
    corners_b = _detect_corners(lat_g_b, dist_b)

    aligned = _align_corners(corners_a, dist_a, corners_b, dist_b)

    per_corner = []
    for i, (ca, cb) in enumerate(aligned):
        ma = _corner_metrics(lat_g_a, long_g_a, spd_a, dist_a, ca[0], ca[1],
                             envelope=envelope, throttle=throttle_a)
        mb = _corner_metrics(lat_g_b, long_g_b, spd_b, dist_b, cb[0], cb[1],
                             envelope=envelope, throttle=throttle_b)
        per_corner.append({
            "corner_index": i + 1,
            "entry_dist_m": int(ma["entry_dist_m"]),
            code_a: ma,
            code_b: mb,
            "peak_g_delta": round(ma["peak_g"] - mb["peak_g"], 3),
            "load_variance_delta": round(ma["load_variance"] - mb["load_variance"], 3),
            "corrections_delta": ma["correction_count"] - mb["correction_count"],
            "trail_brake_delta_pct": round(ma["trail_brake_pct"] - mb["trail_brake_pct"], 1),
            "ggv_util_delta_pct": round((ma.get("ggv_util_pct") or 0.0) - (mb.get("ggv_util_pct") or 0.0), 1),
            "envelope_time_delta_pct": round((ma.get("envelope_time_pct") or 0.0) - (mb.get("envelope_time_pct") or 0.0), 1),
            "throttle_acceptance_delta_pct": round((ma.get("throttle_acceptance_pct") or 0.0) - (mb.get("throttle_acceptance_pct") or 0.0), 1),
            "entry_bravery_delta_pct": round((ma.get("entry_bravery_pct") or 0.0) - (mb.get("entry_bravery_pct") or 0.0), 1),
        })

    # Summary stats
    def _summary(lat_g: np.ndarray, code: str, corners: list[tuple[int, int]]) -> dict:
        peak_g = round(float(lat_g.max()), 2)
        avg_corr = round(sum(c[code]["correction_count"] for c in per_corner) / len(per_corner), 1) if per_corner else None
        avg_var = round(sum(c[code]["load_variance"] for c in per_corner) / len(per_corner), 3) if per_corner else None
        if per_corner:
            avg_trail = round(sum(c[code]["trail_brake_pct"] for c in per_corner) / len(per_corner), 1)
            avg_ggv = round(float(np.mean([c[code].get("ggv_util_pct") or 0.0 for c in per_corner])), 1)
            avg_env_time = round(float(np.mean([c[code].get("envelope_time_pct") or 0.0 for c in per_corner])), 1)
            avg_ta = round(float(np.mean([c[code].get("throttle_acceptance_pct") or 0.0 for c in per_corner])), 1)
            avg_eb = round(float(np.mean([c[code].get("entry_bravery_pct") or 0.0 for c in per_corner])), 1)
        else:
            avg_trail = avg_ggv = avg_env_time = avg_ta = avg_eb = None
        return {
            "peak_lateral_g": peak_g,
            "corners_detected": len(corners),
            "avg_corrections_per_corner": avg_corr,
            "avg_load_variance": avg_var,
            "avg_trail_brake_pct": avg_trail,
            "avg_ggv_util_pct": avg_ggv,
            "avg_envelope_time_pct": avg_env_time,
            "avg_throttle_acceptance_pct": avg_ta,
            "avg_entry_bravery_pct": avg_eb,
        }

    sum_a = _summary(lat_g_a, code_a, corners_a)
    sum_b = _summary(lat_g_b, code_b, corners_b)

    # Human-readable narrative
    higher_var_driver = code_a if (sum_a.get("avg_load_variance") or 0) > (sum_b.get("avg_load_variance") or 0) else code_b
    lower_var_driver = code_b if higher_var_driver == code_a else code_a

    if per_corner:
        ggv_a_corners = sum(1 for c in per_corner if (c[code_a].get("ggv_util_pct") or 0.0) > (c[code_b].get("ggv_util_pct") or 0.0))
        ggv_b_corners = len(per_corner) - ggv_a_corners
    else:
        ggv_a_corners = ggv_b_corners = 0

    narrative_parts = []

    # --- Smoothness: clean arc vs fighting / correcting ---
    if sum_a.get("avg_load_variance") and sum_b.get("avg_load_variance"):
        var_hi = max(sum_a['avg_load_variance'], sum_b['avg_load_variance'])
        var_lo = min(sum_a['avg_load_variance'], sum_b['avg_load_variance'])
        if var_hi - var_lo >= 0.01:
            corr_hi = sum_a.get("avg_corrections_per_corner", 0) if higher_var_driver == code_a else sum_b.get("avg_corrections_per_corner", 0)
            corr_lo = sum_b.get("avg_corrections_per_corner", 0) if higher_var_driver == code_a else sum_a.get("avg_corrections_per_corner", 0)
            if corr_hi > corr_lo + 1:
                balance_desc = (
                    f"{higher_var_driver} was chasing the balance mid-corner — "
                    f"the car a bit twitchy through the apex, making corrections rather than committing to one clean arc. "
                    f"{lower_var_driver} was rotating the car smoothly and holding it — the load profile barely flickered."
                )
            else:
                balance_desc = (
                    f"{higher_var_driver}'s inputs were less settled through the apex — "
                    f"more oscillation in the load profile compared to {lower_var_driver}'s cleaner arc. "
                    f"The car was working harder than it needed to be."
                )
            narrative_parts.append(balance_desc)

    # --- Corner spread (GGV-based) ---
    if per_corner and len(per_corner) >= 4:
        higher_ggv_corners_driver = code_a if ggv_a_corners >= ggv_b_corners else code_b
        lower_ggv_corners_driver = code_b if higher_ggv_corners_driver == code_a else code_a
        hi_cnt = max(ggv_a_corners, ggv_b_corners)
        lo_cnt = min(ggv_a_corners, ggv_b_corners)
        narrative_parts.append(
            f"{higher_ggv_corners_driver} used more of the car's grip envelope in {hi_cnt} "
            f"of the {len(per_corner)} matched corners; "
            f"{lower_ggv_corners_driver} in {lo_cnt}."
        )

    # --- Trail braking signature ---
    tb_a = sum_a.get("avg_trail_brake_pct") or 0.0
    tb_b = sum_b.get("avg_trail_brake_pct") or 0.0
    if tb_a or tb_b:
        if abs(tb_a - tb_b) >= 5.0:
            higher_tb = code_a if tb_a >= tb_b else code_b
            lower_tb = code_b if higher_tb == code_a else code_a
            narrative_parts.append(
                f"{higher_tb} was carrying the brake deep into the corner — "
                f"still on the pedal at turn-in for {max(tb_a, tb_b):.1f}% of the entry phase, "
                f"using it to rotate the car. {lower_tb} finished braking earlier ({min(tb_a, tb_b):.1f}%), "
                f"turning in on a cleaner line."
            )
        elif max(tb_a, tb_b) < 5.0:
            narrative_parts.append(
                f"Neither driver was trail braking meaningfully — both finishing braking before turn-in."
            )

    # --- GGV utilisation (empirical envelope) ---
    ggv_a = sum_a.get("avg_ggv_util_pct") or 0.0
    ggv_b = sum_b.get("avg_ggv_util_pct") or 0.0
    if ggv_a and ggv_b and abs(ggv_a - ggv_b) >= 2.0:
        higher_ggv = code_a if ggv_a >= ggv_b else code_b
        lower_ggv = code_b if higher_ggv == code_a else code_a
        narrative_parts.append(
            f"Against the car's empirical grip ceiling — what this car on these tyres has been "
            f"shown to do in this session — {higher_ggv} used {max(ggv_a, ggv_b):.1f}% of that "
            f"envelope vs {lower_ggv}'s {min(ggv_a, ggv_b):.1f}%. "
            f"{higher_ggv} was asking more of what the car can actually produce."
        )

    # --- Throttle acceptance (exit bravery) ---
    ta_a = sum_a.get("avg_throttle_acceptance_pct") or 0.0
    ta_b = sum_b.get("avg_throttle_acceptance_pct") or 0.0
    if abs(ta_a - ta_b) >= 5.0:
        braver_exit = code_a if ta_a >= ta_b else code_b
        cautious_exit = code_b if braver_exit == code_a else code_a
        narrative_parts.append(
            f"{braver_exit} was committing to full power earlier at corner exits — still carrying "
            f"heavy lateral load in {max(ta_a, ta_b):.1f}% of exits vs {min(ta_a, ta_b):.1f}% "
            f"for {cautious_exit}. That's asking the rear tyre to drive the car forward and corner "
            f"simultaneously — the brave part of the exit."
        )
    elif max(ta_a, ta_b) < 5.0:
        narrative_parts.append(
            f"Neither driver was particularly aggressive at exit — both waiting for the car to "
            f"settle before committing to power."
        )

    # --- Outlier detection: load_variance spikes and standout committed corners ---
    if len(per_corner) >= 4:
        for code in (code_a, code_b):
            variances = [c[code]["load_variance"] for c in per_corner if c[code].get("load_variance") is not None]
            if len(variances) >= 4:
                var_mean = float(np.mean(variances))
                var_std = float(np.std(variances))
                if var_std > 0:
                    for c in per_corner:
                        v = c[code].get("load_variance")
                        if v is not None and v > var_mean + 2 * var_std:
                            corner_num = c["corner_index"]
                            dist_m = c["entry_dist_m"]
                            narrative_parts.append(
                                f"Standout moment: {code}'s roughest corner was corner {corner_num} "
                                f"(~{dist_m}m) — load wobble of {v:.3f} vs their {var_mean:.3f} typical. "
                                f"That spike suggests a snap, oversteer moment, or a correction they had to manage."
                            )
                            break  # report only the single worst outlier per driver

            ggv_vals = [c[code].get("ggv_util_pct") or 0.0 for c in per_corner]
            if len(ggv_vals) >= 4:
                ggv_mean = float(np.mean(ggv_vals))
                ggv_std = float(np.std(ggv_vals))
                if ggv_std > 0:
                    best_c = max(per_corner, key=lambda c: c[code].get("ggv_util_pct") or 0.0)
                    best_val = best_c[code].get("ggv_util_pct") or 0.0
                    if best_val > ggv_mean + 2 * ggv_std and best_val >= 90.0:
                        corner_num = best_c["corner_index"]
                        dist_m = best_c["entry_dist_m"]
                        narrative_parts.append(
                            f"Corner {corner_num} (~{dist_m}m) was {code}'s standout committed corner — "
                            f"{best_val:.1f}% of the car's grip ceiling vs their {ggv_mean:.1f}% average. "
                            f"That's right at the ragged edge of what this car can produce."
                        )

    return {
        "event": session.event['EventName'],
        "session": session_type.upper(),
        "driver_a": code_a,
        "driver_b": code_b,
        "lap_a": {"lap_number": int(lap_a['LapNumber']), "lap_time": _fmt_td(lap_a['LapTime'])},
        "lap_b": {"lap_number": int(lap_b['LapNumber']), "lap_time": _fmt_td(lap_b['LapTime'])},
        "summary": {
            code_a: sum_a,
            code_b: sum_b,
        },
        "per_corner": per_corner,
        "narrative": " ".join(narrative_parts),
        "caveat": (
            "Lateral G derived from X/Y GPS position via curvature (v²/R) with Savitzky-Golay smoothing. "
            "Absolute values carry ±5-10% uncertainty. Comparative rankings between drivers on the same "
            "session are reliable. No steering angle or IMU data available in FastF1."
        ),
    }


def _aggregate_lap_cornering_stats(tel: pd.DataFrame, envelope: dict | None = None) -> dict | None:
    """
    Compute aggregate cornering stats for a single lap's telemetry.
    All metrics are computed only within detected cornering segments (lat_G > 0.8G).
    Returns None if data is insufficient or missing required columns.
    """
    if any(c not in tel.columns for c in ('X', 'Y', 'Speed')):
        return None
    if len(tel) < 50:
        return None
    try:
        dist = tel['Distance'].to_numpy(dtype=float) if 'Distance' in tel.columns else np.arange(len(tel), dtype=float)
        spd = tel['Speed'].to_numpy(dtype=float)
        lat_g = _compute_lateral_g(tel)
        long_g = _compute_longitudinal_g(tel)
        throttle = tel['Throttle'].to_numpy(dtype=float) if 'Throttle' in tel.columns else None
        corners = _detect_corners(lat_g, dist)
        if not corners:
            return None

        corner_trail_brake_samples = []
        corner_corrections = []
        corner_variances = []
        corner_ggv_util = []
        corner_env_time = []
        corner_throttle_acc = []
        corner_entry_bravery = []

        for c_start, c_end in corners:
            metrics = _corner_metrics(lat_g, long_g, spd, dist, c_start, c_end,
                                      envelope=envelope, throttle=throttle)
            seg_g = lat_g[c_start:c_end + 1]
            corner_trail_brake_samples.append(metrics['trail_brake_pct'])
            corner_corrections.append(metrics['correction_count'])
            corner_variances.append(float(np.std(seg_g)))
            corner_ggv_util.append(metrics.get('ggv_util_pct') or 0.0)
            corner_env_time.append(metrics.get('envelope_time_pct') or 0.0)
            corner_throttle_acc.append(metrics.get('throttle_acceptance_pct') or 0.0)
            corner_entry_bravery.append(metrics.get('entry_bravery_pct') or 0.0)

        if not corner_corrections:
            return None

        return {
            "corners_detected": len(corners),
            "avg_corrections_per_corner": round(float(np.mean(corner_corrections)), 1),
            "avg_load_variance": round(float(np.mean(corner_variances)), 3),
            "avg_trail_brake_pct": round(float(np.mean(corner_trail_brake_samples)), 1),
            "avg_ggv_util_pct": round(float(np.mean(corner_ggv_util)), 1) if corner_ggv_util else None,
            "avg_envelope_time_pct": round(float(np.mean(corner_env_time)), 1) if corner_env_time else None,
            "avg_throttle_acceptance_pct": round(float(np.mean(corner_throttle_acc)), 1) if corner_throttle_acc else None,
            "avg_entry_bravery_pct": round(float(np.mean(corner_entry_bravery)), 1) if corner_entry_bravery else None,
        }
    except Exception:
        return None


def analyze_race_cornering_profile(
    round_number: int,
    driver_a: str,
    driver_b: str,
) -> dict:
    """
    Analyze lateral G and grip utilisation across an entire race for two drivers.

    Processes every clean race lap (excluding pit laps and laps with deleted times)
    and aggregates cornering stats by stint and overall. All metrics are computed
    within detected cornering events only (lateral G > 0.8G threshold).

    Returns per-stint breakdown and an overall narrative comparing:
    - Average corner grip utilisation %
    - % of cornering time above 90% theoretical grip
    - Average steering corrections per corner (proxy for driving smoothness)
    - Average lateral load variance (proxy for tyre thermal stress)

    Caveat: derived from GPS position, ±5-10% absolute uncertainty.
    Comparative rankings between drivers are reliable.
    """
    session = _load_session(
        round_number,
        "R",
        laps=True,
        telemetry=True,
        weather=False,
        messages=False,
    )

    code_a = driver_a.upper()
    code_b = driver_b.upper()

    def _get_clean_laps(code: str):
        laps = _pick_driver(session.laps, code)
        if laps.empty:
            raise ValueError(f"No data for driver {code!r}")
        mask = (
            laps['LapTime'].notna() &
            laps['PitInTime'].isna() &
            laps['PitOutTime'].isna()
        )
        if 'Deleted' in laps.columns:
            mask &= ~laps['Deleted'].fillna(False)
        return laps[mask].sort_values('LapNumber')

    clean_a = _get_clean_laps(code_a)
    clean_b = _get_clean_laps(code_b)

    # Pass 1: collect telemetry frames for both drivers to build the shared GGV envelope.
    def _collect_lap_tels(clean_laps):
        result = []
        for _, lap in clean_laps.iterrows():
            try:
                tel = lap.get_telemetry().add_distance()
                if len(tel) >= 50:
                    result.append((lap, tel))
            except Exception:
                continue
        return result

    lap_tels_a = _collect_lap_tels(clean_a)
    lap_tels_b = _collect_lap_tels(clean_b)
    envelope = _build_ggv_envelope([t for _, t in lap_tels_a + lap_tels_b])

    # Pass 2: compute per-lap stats with the shared envelope.
    def _process_lap_tels(lap_tels) -> list[dict]:
        results = []
        for lap, tel in lap_tels:
            try:
                stats = _aggregate_lap_cornering_stats(tel, envelope=envelope)
                if stats is None:
                    continue
                stats['lap_number'] = int(lap['LapNumber'])
                stats['stint'] = int(lap['Stint']) if pd.notna(lap.get('Stint')) else None
                stats['compound'] = str(lap['Compound']) if pd.notna(lap.get('Compound')) else None
                results.append(stats)
            except Exception:
                continue
        return results

    laps_a = _process_lap_tels(lap_tels_a)
    laps_b = _process_lap_tels(lap_tels_b)

    def _aggregate(laps_data: list[dict]) -> dict:
        if not laps_data:
            return {"laps_analyzed": 0}
        return {
            "laps_analyzed": len(laps_data),
            "avg_corrections_per_corner": round(float(np.mean([l["avg_corrections_per_corner"] for l in laps_data])), 1),
            "avg_load_variance": round(float(np.mean([l["avg_load_variance"] for l in laps_data])), 3),
            "avg_trail_brake_pct": round(float(np.mean([l.get("avg_trail_brake_pct", 0.0) for l in laps_data])), 1),
            "avg_ggv_util_pct": round(float(np.mean([l.get("avg_ggv_util_pct") or 0.0 for l in laps_data])), 1),
            "avg_envelope_time_pct": round(float(np.mean([l.get("avg_envelope_time_pct") or 0.0 for l in laps_data])), 1),
            "avg_throttle_acceptance_pct": round(float(np.mean([l.get("avg_throttle_acceptance_pct") or 0.0 for l in laps_data])), 1),
            "avg_entry_bravery_pct": round(float(np.mean([l.get("avg_entry_bravery_pct") or 0.0 for l in laps_data])), 1),
        }

    def _aggregate_by_stint(laps_data: list[dict]) -> list[dict]:
        from collections import defaultdict
        stints: dict = defaultdict(list)
        for lap in laps_data:
            key = (lap.get('stint') or 0, lap.get('compound') or '')
            stints[key].append(lap)
        out = []
        for (stint_num, compound), laps in sorted(stints.items()):
            agg = _aggregate(laps)
            agg['stint'] = stint_num if stint_num else None
            agg['compound'] = compound or None
            out.append(agg)
        return out

    overall_a = _aggregate(laps_a)
    overall_b = _aggregate(laps_b)
    stints_a = _aggregate_by_stint(laps_a)
    stints_b = _aggregate_by_stint(laps_b)

    # Build narrative
    var_a = overall_a.get("avg_load_variance", 0.0)
    var_b = overall_b.get("avg_load_variance", 0.0)
    corr_a = overall_a.get("avg_corrections_per_corner", 0.0)
    corr_b = overall_b.get("avg_corrections_per_corner", 0.0)

    higher_var = code_a if var_a >= var_b else code_b
    lower_var = code_b if higher_var == code_a else code_a

    narrative_parts = []
    laps_a_count = overall_a.get('laps_analyzed', 0)
    laps_b_count = overall_b.get('laps_analyzed', 0)

    # --- Smoothness and balance: clean arc vs chasing / fighting ---
    if abs(var_a - var_b) >= 0.01:
        var_hi = max(var_a, var_b)
        var_lo = min(var_a, var_b)
        # Combine with correction count for richer language
        corr_hi_val = corr_a if higher_var == code_a else corr_b
        corr_lo_val = corr_b if higher_var == code_a else corr_a
        corr_diff = abs(corr_a - corr_b)
        if corr_diff >= 0.5:
            narrative_parts.append(
                f"{higher_var} was fighting the car more through the apex — making around {corr_hi_val:.1f} corrections per corner "
                f"vs {corr_lo_val:.1f} for {lower_var}, chasing oversteer or understeer rather than riding one clean committed arc. "
                f"{lower_var} was rotating the car smoothly, the load barely moving once committed. "
                f"Those corrections are working the tyre harder than the lap requires — that's what turns a healthy stint into a degradation cliff."
            )
        else:
            narrative_parts.append(
                f"{higher_var}'s inputs were twitchier mid-corner — the lateral load fluctuating more than {lower_var}'s cleaner arc. "
                f"Even without significantly more corrections, that oscillation in the load works the tyre harder and builds heat unevenly."
            )

    # --- Stint-level confidence shifts ---
    if stints_a and stints_b:
        a_by_stint = {s['stint']: s for s in stints_a}
        b_by_stint = {s['stint']: s for s in stints_b}
        shared_stints = sorted(set(a_by_stint) & set(b_by_stint))
        for sn in shared_stints:
            sa = a_by_stint[sn]
            sb = b_by_stint[sn]
            sa_ggv = sa.get('avg_ggv_util_pct') or 0.0
            sb_ggv = sb.get('avg_ggv_util_pct') or 0.0
            if sa_ggv and sb_ggv:
                stint_diff = abs(sa_ggv - sb_ggv)
                if stint_diff >= 2.0:
                    stint_leader = code_a if sa_ggv >= sb_ggv else code_b
                    stint_trailer = code_b if stint_leader == code_a else code_a
                    compound = sa.get('compound') or sb.get('compound') or 'unknown'
                    narrative_parts.append(
                        f"Stint {sn} on the {compound}: {stint_leader} was asking more of the car's grip envelope — "
                        f"{stint_diff:.1f}pp more of the empirical ceiling through the corners. "
                        f"{stint_trailer} kept more in reserve, whether by choice or because the tyre wasn't fully in their window."
                    )

    # --- Trail braking style across the race ---
    tb_a = overall_a.get("avg_trail_brake_pct", 0.0)
    tb_b = overall_b.get("avg_trail_brake_pct", 0.0)
    if abs(tb_a - tb_b) >= 5.0:
        higher_tb = code_a if tb_a >= tb_b else code_b
        lower_tb = code_b if higher_tb == code_a else code_a
        narrative_parts.append(
            f"{higher_tb} was the trail braker of the two — still on the brakes at turn-in "
            f"for {max(tb_a, tb_b):.1f}% of corner entry across the race vs {min(tb_a, tb_b):.1f}% for {lower_tb}. "
            f"Over a full race distance that front-tyre load difference adds up."
        )

    # --- GGV utilisation race-long ---
    ggv_race_a = overall_a.get("avg_ggv_util_pct", 0.0)
    ggv_race_b = overall_b.get("avg_ggv_util_pct", 0.0)
    if overall_a.get("laps_analyzed", 0) > 0 and overall_b.get("laps_analyzed", 0) > 0 and abs(ggv_race_a - ggv_race_b) >= 2.0:
        higher_ggv_r = code_a if ggv_race_a >= ggv_race_b else code_b
        lower_ggv_r = code_b if higher_ggv_r == code_a else code_a
        narrative_parts.append(
            f"Against the empirical grip ceiling, {higher_ggv_r} used {max(ggv_race_a, ggv_race_b):.1f}% "
            f"of the envelope vs {lower_ggv_r}'s {min(ggv_race_a, ggv_race_b):.1f}% over the race. "
            f"That's the fraction of the car's demonstrated combined capability being asked of the tyres, lap after lap."
        )

    # --- Throttle acceptance race-long ---
    ta_race_a = overall_a.get("avg_throttle_acceptance_pct", 0.0)
    ta_race_b = overall_b.get("avg_throttle_acceptance_pct", 0.0)
    if abs(ta_race_a - ta_race_b) >= 5.0:
        braver_exit_r = code_a if ta_race_a >= ta_race_b else code_b
        cautious_exit_r = code_b if braver_exit_r == code_a else code_a
        narrative_parts.append(
            f"{braver_exit_r} was getting on the power earlier at every exit — still loaded laterally in "
            f"{max(ta_race_a, ta_race_b):.1f}% of exits vs {min(ta_race_a, ta_race_b):.1f}% for {cautious_exit_r}. "
            f"Over a race distance, that exit aggression compounds — more drive out of every corner, every lap."
        )

    return {
        "event": session.event['EventName'],
        "session": "R",
        "driver_a": code_a,
        "driver_b": code_b,
        "overall_summary": {
            code_a: overall_a,
            code_b: overall_b,
        },
        "stint_breakdown": {
            code_a: stints_a,
            code_b: stints_b,
        },
        "narrative": " ".join(narrative_parts),
        "caveat": (
            "Lateral G derived from X/Y GPS position via curvature (v²/R) with Savitzky-Golay smoothing. "
            "Metrics are computed within cornering segments only (lateral G > 0.8G). "
            "Pit laps and laps with deleted times excluded. "
            "Absolute values carry ±5-10% uncertainty; comparative rankings are reliable."
        ),
    }


def _openf1_pit_fetch(round_number: int) -> dict:
    """
    Returns {(driver_number_int, lap_number_int): pit_duration_s} from OpenF1.
    Falls back to empty dict on any error so the caller always gets valid data.
    Local import avoids circular dependency (openf1.py imports from f1_data.py).
    """
    try:
        from openf1 import get_pit_stops
        rows = get_pit_stops(round_number)
        return {
            (int(r["driver_number"]), int(r["lap_number"])): r["pit_duration_s"]
            for r in rows
            if r.get("driver_number") is not None and r.get("lap_number") is not None
        }
    except Exception:
        return {}


def get_pit_stop_analysis(round_number: int) -> dict:
    """
    Pit stop strategy for all classified finishers in a race.
    Returns per-driver stints (compound, start_lap, end_lap, laps) and pit stops
    (lap, duration_s from OpenF1, compound_in, compound_out).
    Drivers are sorted by finish position.
    """
    _validate_session_availability(round_number, "R", telemetry=False)
    session = _load_session(round_number, "R", laps=True)

    session_results = get_session_results(round_number, "R")
    results_list = session_results.get("results", [])
    num_to_code = {
        int(r["driver_number"]): r["abbreviation"].upper()
        for r in results_list
        if r.get("driver_number") and r.get("abbreviation")
    }
    finish_order = {
        r["abbreviation"].upper(): _normalize_position(r.get("position")) or 99
        for r in results_list
        if r.get("abbreviation")
    }

    pit_durations = _openf1_pit_fetch(round_number)

    drivers_data = []
    all_codes = session.laps["Driver"].dropna().unique() if not session.laps.empty else []

    for code in all_codes:
        code = str(code).upper()
        driver_laps = session.laps[session.laps["Driver"] == code]
        if driver_laps.empty:
            continue

        driver_laps = driver_laps.sort_values("LapNumber")
        stints: list[dict] = []
        pit_stops: list[dict] = []
        current_compound: str | None = None
        stint_start: int | None = None
        driver_num_int = next((n for n, c in num_to_code.items() if c == code), None)

        for _, lap in driver_laps.iterrows():
            lap_num = int(lap["LapNumber"])
            compound = str(lap.get("Compound") or "UNKNOWN").upper()

            if current_compound is None:
                current_compound = compound
                stint_start = lap_num
            elif compound != current_compound:
                stints.append({
                    "compound": current_compound,
                    "start_lap": stint_start,
                    "end_lap": lap_num - 1,
                    "laps": lap_num - 1 - stint_start + 1,
                })
                duration = (
                    pit_durations.get((driver_num_int, lap_num - 1))
                    if driver_num_int is not None else None
                )
                pit_stops.append({
                    "lap": lap_num - 1,
                    "duration_s": duration,
                    "compound_in": current_compound,
                    "compound_out": compound,
                })
                current_compound = compound
                stint_start = lap_num

        if current_compound and stint_start is not None:
            max_lap = int(driver_laps["LapNumber"].max())
            stints.append({
                "compound": current_compound,
                "start_lap": stint_start,
                "end_lap": max_lap,
                "laps": max_lap - stint_start + 1,
            })

        if stints:
            drivers_data.append({
                "driver": code,
                "stints": stints,
                "pit_stops": pit_stops,
                "_finish": finish_order.get(code, 99),
            })

    drivers_data.sort(key=lambda d: d.pop("_finish"))
    total_laps = int(session.laps["LapNumber"].max()) if not session.laps.empty else None

    return {
        "event": session.event["EventName"],
        "session": "R",
        "total_laps": total_laps,
        "drivers": drivers_data,
    }


def analyze_weather_pace_correlation(round_number: int, session_type: str = "Q") -> dict:
    """
    Correlates track temperature with lap time evolution through the session.
    For qualifying: Q1/Q2/Q3 segments — temperature and best lap per segment.
    For race: 10-lap blocks — temperature and top-5 average pace per block.
    Primary use: explain anomalies (Q3 slower than Q2, pace drop mid-race).
    """
    _validate_session_availability(round_number, session_type, telemetry=False)
    session = _load_session(round_number, session_type, laps=True, weather=True)

    if session.weather_data is None or session.weather_data.empty:
        raise ValueError(f"No weather data available for round {round_number} {session_type}.")

    weather = session.weather_data.copy()
    laps = session.laps.copy()
    st = session_type.upper()

    def _nearest_weather(time_td):
        if weather.empty or time_td is None or pd.isna(time_td):
            return None, None
        diffs = (weather["Time"] - time_td).abs()
        row = weather.loc[diffs.idxmin()]
        return _normalize_float(row.get("TrackTemp")), _normalize_float(row.get("AirTemp"))

    segments = []

    if st == "Q":
        for q_seg in ["Q1", "Q2", "Q3"]:
            if "Session" in laps.columns:
                seg_laps = laps[laps["Session"] == q_seg]
            else:
                total = len(laps)
                thirds = [laps.iloc[:total//3], laps.iloc[total//3:2*total//3], laps.iloc[2*total//3:]]
                seg_laps = thirds[["Q1","Q2","Q3"].index(q_seg)]

            valid = seg_laps[
                seg_laps["LapTime"].notna()
                & ~seg_laps.get("Deleted", pd.Series(False, index=seg_laps.index))
            ]
            if valid.empty:
                continue

            lap_times_s = sorted([lt.total_seconds() for lt in valid["LapTime"] if pd.notna(lt)])
            best = round(lap_times_s[0], 3) if lap_times_s else None
            top5_avg = round(sum(lap_times_s[:5]) / min(5, len(lap_times_s)), 3) if lap_times_s else None
            mid_time = valid["Time"].median() if "Time" in valid.columns else None
            track_temp, air_temp = _nearest_weather(mid_time)

            segments.append({
                "segment": q_seg,
                "avg_track_temp_c": track_temp,
                "avg_air_temp_c": air_temp,
                "best_lap_s": best,
                "top5_avg_pace_s": top5_avg,
                "lap_count": len(valid),
            })
    else:
        max_lap = int(laps["LapNumber"].max()) if not laps.empty else 0
        for start in range(1, max_lap + 1, 10):
            end = min(start + 9, max_lap)
            block = laps[(laps["LapNumber"] >= start) & (laps["LapNumber"] <= end)]
            valid = block[block["LapTime"].notna()]
            if valid.empty:
                continue
            lap_times_s = sorted([
                lt.total_seconds() for lt in valid["LapTime"]
                if pd.notna(lt) and lt.total_seconds() < 200
            ])
            if not lap_times_s:
                continue
            mid_time = valid["Time"].median() if "Time" in valid.columns else None
            track_temp, air_temp = _nearest_weather(mid_time)
            segments.append({
                "segment": f"Laps {start}–{end}",
                "avg_track_temp_c": track_temp,
                "avg_air_temp_c": air_temp,
                "best_lap_s": round(lap_times_s[0], 3),
                "top5_avg_pace_s": round(sum(lap_times_s[:5]) / min(5, len(lap_times_s)), 3),
                "lap_count": len(valid),
            })

    first = next((s for s in segments if s["best_lap_s"]), None)
    last  = next((s for s in reversed(segments) if s["best_lap_s"]), None)
    track_evolution_s = (
        round(last["best_lap_s"] - first["best_lap_s"], 3)
        if first and last and first is not last else None
    )
    first_temp = first["avg_track_temp_c"] if first else None
    last_temp  = last["avg_track_temp_c"]  if last  else None
    temp_change_c = (
        round(last_temp - first_temp, 1)
        if first_temp is not None and last_temp is not None else None
    )
    rainfall = bool((weather.get("Rainfall") == True).any()) if not weather.empty else False

    return {
        "event": session.event["EventName"],
        "session": st,
        "segments": segments,
        "track_evolution_s": track_evolution_s,
        "temp_change_c": temp_change_c,
        "rainfall_recorded": rainfall,
        "how_to_read": (
            "track_evolution_s: negative = track got faster across the session. "
            "Use temp_change_c alongside track_evolution_s to separate rubber-laid grip from temperature effect. "
            "top5_avg_pace_s is more robust than best_lap_s when a single hotlap distorts the sample."
        ),
    }


def get_fp_summary(round_number: int, fp_number: int) -> dict:
    """Return a structured summary of a free practice session with stint classification."""
    session_type = f"FP{fp_number}"
    session = _load_session(round_number, session_type, laps=True, telemetry=False, weather=False, messages=False)
    driver_info = _driver_lookup(session)

    _SOFT_COMPOUNDS = {"SOFT", "SUPERSOFT", "ULTRASOFT", "HYPERSOFT"}

    def _classify_stint(laps_in_stint: list, stint_no: int) -> str:
        lc = len(laps_in_stint)
        first = laps_in_stint[0]
        compound = str(first.get("Compound", "")) if pd.notna(first.get("Compound")) else ""
        fresh = bool(first.get("FreshTyre")) if pd.notna(first.get("FreshTyre")) else False
        is_pit_out = pd.notna(first.get("PitOutTime"))
        if lc == 1 and is_pit_out and stint_no == 1:
            return "installation"
        if lc >= 8:
            return "long_run"
        if lc <= 2 and fresh and compound.upper() in _SOFT_COMPOUNDS:
            return "quali_sim"
        return "short_run"

    driver_results = []
    for code in session.drivers:
        driver_laps = _pick_driver(session.laps, str(code))
        if getattr(driver_laps, "empty", True):
            continue

        groups: dict[int, list] = {}
        for _, lap in driver_laps.iterrows():
            stint_key = int(lap["Stint"]) if pd.notna(lap.get("Stint")) else 1
            groups.setdefault(stint_key, []).append(lap)

        stints = []
        for stint_no in sorted(groups):
            laps_in = groups[stint_no]
            first = laps_in[0]
            last = laps_in[-1]
            compound = str(first.get("Compound")) if pd.notna(first.get("Compound")) else None
            fresh = bool(first.get("FreshTyre")) if pd.notna(first.get("FreshTyre")) else None
            valid_times = [
                l["LapTime"].total_seconds()
                for l in laps_in
                if l.get("LapTime") is not None and not pd.isna(l["LapTime"])
            ]
            stints.append({
                "stint": stint_no,
                "compound": compound,
                "fresh_tyre": fresh,
                "laps": len(laps_in),
                "classification": _classify_stint(laps_in, stint_no),
                "start_lap": int(first["LapNumber"]) if pd.notna(first.get("LapNumber")) else None,
                "end_lap": int(last["LapNumber"]) if pd.notna(last.get("LapNumber")) else None,
                "best_lap_s": round(min(valid_times), 3) if valid_times else None,
                "avg_lap_s": round(sum(valid_times) / len(valid_times), 3) if valid_times else None,
            })

        all_valid = sorted(
            [l for _, l in driver_laps.iterrows() if l.get("LapTime") is not None and not pd.isna(l["LapTime"])],
            key=lambda l: l["LapTime"],
        )
        best = all_valid[0] if all_valid else None
        info = driver_info.get(str(code).upper(), {})

        driver_results.append({
            "driver": info.get("FullName") or str(code).upper(),
            "code": str(code).upper(),
            "team": info.get("TeamName"),
            "stints": stints,
            "best_lap_time": _fmt_td(best["LapTime"]) if best is not None else None,
            "best_lap_time_s": round(best["LapTime"].total_seconds(), 3) if best is not None else None,
            "best_lap_compound": str(best["Compound"]) if best is not None and pd.notna(best.get("Compound")) else None,
            "speed_st": round(float(best["SpeedST"]), 1) if best is not None and pd.notna(best.get("SpeedST")) else None,
            "long_run_count": sum(1 for s in stints if s["classification"] == "long_run"),
            "quali_sim_count": sum(1 for s in stints if s["classification"] == "quali_sim"),
            "compounds_used": list({s["compound"] for s in stints if s.get("compound")}),
        })

    driver_results.sort(key=lambda d: d.get("best_lap_time_s") or float("inf"))

    return {
        "event": session.event["EventName"],
        "session": session_type,
        "drivers": driver_results,
        "session_notes": [
            "Fuel load is not measured — FastF1 does not provide fuel load for FP sessions.",
            "Long-run stints (8+ laps, same compound) approximate race pace but are run on heavier fuel than the race.",
            "Quali-sim stints (1-2 laps on fresh soft, fast time) approximate single-lap pace.",
            "Installation laps (first pit-out lap of session) are included in stints but excluded from pace context.",
            "FP lap times are not directly comparable to qualifying times due to fuel load and tyre program differences.",
        ],
    }


def get_speed_trap_leaderboard(round_number: int, session_type: str) -> dict:
    """Scan all laps and return peak speed at each trap (ST, FL, I1, I2) per driver."""
    session = _load_session(round_number, session_type, laps=True, telemetry=False, weather=False, messages=False)
    driver_info = _driver_lookup(session)

    traps = {
        "speed_st": "SpeedST",
        "speed_fl": "SpeedFL",
        "speed_i1": "SpeedI1",
        "speed_i2": "SpeedI2",
    }

    # For each trap, build {driver_code: {speed, lap_number, compound}}
    trap_bests: dict[str, dict[str, dict]] = {t: {} for t in traps}

    for code in session.drivers:
        driver_laps = _pick_driver(session.laps, str(code))
        if getattr(driver_laps, "empty", True):
            continue
        code_upper = str(code).upper()
        for trap_key, col in traps.items():
            if col not in driver_laps.columns:
                continue
            valid = driver_laps[driver_laps[col].notna() & (driver_laps[col] > 0)]
            if valid.empty:
                continue
            best_row = valid.loc[valid[col].idxmax()]
            trap_bests[trap_key][code_upper] = {
                "speed_kph": round(float(best_row[col]), 1),
                "lap_number": int(best_row["LapNumber"]) if pd.notna(best_row.get("LapNumber")) else None,
                "compound": str(best_row["Compound"]) if pd.notna(best_row.get("Compound")) else None,
            }

    def _ranked(trap_key: str) -> list[dict]:
        entries = []
        for code_upper, data in trap_bests[trap_key].items():
            info = driver_info.get(code_upper, {})
            entries.append({
                "driver": code_upper,
                "team": info.get("TeamName"),
                "speed_kph": data["speed_kph"],
                "lap_number": data["lap_number"],
                "compound": data["compound"],
            })
        entries.sort(key=lambda e: e["speed_kph"], reverse=True)
        for i, e in enumerate(entries):
            e["rank"] = i + 1
        return entries

    return {
        "event": session.event["EventName"],
        "session": session_type,
        "trap_labels": {
            "speed_st": "Speed Trap (main straight)",
            "speed_fl": "Finish Line",
            "speed_i1": "Intermediate 1",
            "speed_i2": "Intermediate 2",
        },
        "speed_st": _ranked("speed_st"),
        "speed_fl": _ranked("speed_fl"),
        "speed_i1": _ranked("speed_i1"),
        "speed_i2": _ranked("speed_i2"),
    }


def _sample_telemetry_at_distances(tel, targets: list[int]) -> list[dict]:
    """
    Sample all telemetry channels at each target distance using linear interpolation.
    Replaces the old nearest-neighbour idxmin lookup.
    """
    dist_arr = tel['Distance'].to_numpy(dtype=float)
    spd_arr  = tel['Speed'].to_numpy(dtype=float)
    thr_arr  = tel['Throttle'].to_numpy(dtype=float)
    brk_arr  = tel['Brake'].to_numpy(dtype=float)
    gear_arr = tel['nGear'].to_numpy(dtype=float) if 'nGear' in tel.columns else None
    drs_arr  = tel['DRS'].to_numpy(dtype=float)   if 'DRS'  in tel.columns else None
    rpm_arr  = tel['RPM'].to_numpy(dtype=float)   if 'RPM'  in tel.columns else None

    result = []
    for d in targets:
        speed    = float(np.interp(d, dist_arr, spd_arr))
        throttle = float(np.interp(d, dist_arr, thr_arr))
        brake    = float(np.interp(d, dist_arr, brk_arr)) >= 0.5
        gear_f   = float(np.interp(d, dist_arr, gear_arr)) if gear_arr is not None else None
        drs_f    = float(np.interp(d, dist_arr, drs_arr))  if drs_arr  is not None else None
        rpm_f    = float(np.interp(d, dist_arr, rpm_arr))  if rpm_arr  is not None else None
        result.append({
            'distance_m':   int(d),
            'speed_kph':    round(speed, 1),
            'throttle_pct': round(throttle, 1),
            'brake':        brake,
            'gear':         int(round(gear_f)) if gear_f is not None else None,
            'drs_open':     int(round(drs_f)) >= 10 if drs_f is not None else False,
            'rpm':          round(rpm_f, 0) if rpm_f is not None else None,
        })
    return result


def _compute_delta_trace(
    samples_a: list[dict], samples_b: list[dict], interval_m: float = 100.0
) -> list[dict]:
    """
    Compute cumulative time delta at each 100m mark.
    delta_s = cum_time_A - cum_time_B.
    Negative = driver A is ahead (faster to that point).
    """
    cum_time_a = 0.0
    cum_time_b = 0.0
    result = []
    for sa, sb in zip(samples_a, samples_b):
        spd_a = max(sa['speed_kph'], 1.0)
        spd_b = max(sb['speed_kph'], 1.0)
        cum_time_a += interval_m / (spd_a / 3.6)
        cum_time_b += interval_m / (spd_b / 3.6)
        result.append({
            'distance_m':  sa['distance_m'],
            'delta_s':     round(cum_time_a - cum_time_b, 4),
            'speed_a_kph': sa['speed_kph'],
            'speed_b_kph': sb['speed_kph'],
        })
    return result


def get_lap_delta_trace(
    round_number: int, session_type: str, driver_a: str, driver_b: str,
    lap_type: str = "fastest"
) -> dict:
    """
    Cumulative time delta at every 100m between driver_a and driver_b.
    lap_type: 'fastest' uses each driver's fastest lap.
    """
    sess = _load_session(
        round_number,
        session_type,
        laps=True,
        telemetry=True,
        weather=False,
        messages=_session_needs_race_control_messages(session_type),
    )
    laps = sess.laps

    driver_a = driver_a.upper()
    driver_b = driver_b.upper()

    def _pick_lap(drv):
        dl = _pick_driver(laps, drv)
        if lap_type == "qualifying":
            dl = dl[dl['IsPersonalBest'] == True]
        return _pick_fastest_lap(dl)

    lap_a = _pick_lap(driver_a)
    lap_b = _pick_lap(driver_b)

    tel_a = lap_a.get_telemetry().add_distance()
    tel_b = lap_b.get_telemetry().add_distance()

    total_dist = min(float(tel_a['Distance'].max()), float(tel_b['Distance'].max()))
    INTERVAL_M = 100
    targets = list(range(0, int(total_dist), INTERVAL_M))

    samples_a_list = _sample_telemetry_at_distances(tel_a, targets)
    samples_b_list = _sample_telemetry_at_distances(tel_b, targets)

    delta_trace = _compute_delta_trace(samples_a_list, samples_b_list, interval_m=INTERVAL_M)

    lt_a_raw = lap_a.get('LapTime')
    lt_b_raw = lap_b.get('LapTime')
    lt_a = float(lt_a_raw.total_seconds()) if hasattr(lt_a_raw, 'total_seconds') else None
    lt_b = float(lt_b_raw.total_seconds()) if hasattr(lt_b_raw, 'total_seconds') else None

    final_delta = delta_trace[-1]['delta_s'] if delta_trace else 0.0

    return {
        'driver_a':         driver_a,
        'driver_b':         driver_b,
        'lap_type':         lap_type,
        'lap_time_a_s':     round(lt_a, 3) if lt_a else None,
        'lap_time_b_s':     round(lt_b, 3) if lt_b else None,
        'total_delta_s':    round(final_delta, 3),
        'fastest_driver':   driver_a if final_delta < 0 else driver_b,
        'circuit_length_m': int(total_dist),
        'delta_trace':      delta_trace,
    }


# ---------------------------------------------------------------------------
# FEAT-15: Driver Form Trend
# ---------------------------------------------------------------------------

def _compute_positions_gained(races: list[dict]) -> list[int]:
    """
    Return positions gained per race (grid - finish). DNF (position <= 0 or None) excluded.
    Positive = improved, negative = fell back.
    """
    result = []
    for r in races:
        pos = r.get('position')
        grid = r.get('grid')
        if not pos or not grid:
            continue
        try:
            pos_int = int(pos)
            grid_int = int(grid)
        except (TypeError, ValueError):
            continue
        if pos_int <= 0:
            continue
        result.append(grid_int - pos_int)
    return result


def _classify_form_trend(deltas: list) -> str:
    """
    Fit a linear slope over positions-gained values.
    slope > 0.25/race = improving, < -0.25/race = declining, else stable.
    """
    n = len(deltas)
    if n < 2:
        return 'stable'
    xs = list(range(n))
    mean_x = sum(xs) / n
    mean_y = sum(deltas) / n
    num = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, deltas))
    den = sum((x - mean_x) ** 2 for x in xs)
    slope = num / den if den else 0.0
    if slope > 0.25:
        return 'improving'
    if slope < -0.25:
        return 'declining'
    return 'stable'


def get_driver_form_trend(driver_name: str, last_n: int = 8) -> dict:
    """
    Rolling positions gained/lost vs grid for driver's last N races.
    Uses Jolpica current-season results.
    """
    matched = _resolve_driver(driver_name)
    if not matched:
        return {'error': f'Driver not found: {driver_name}'}
    driver_id = matched['driver_id']
    driver_code = matched['code']

    url = f"{JOLPICA_BASE}/{CURRENT_YEAR}/drivers/{driver_id}/results.json?limit={last_n}"
    resp = requests.get(url, timeout=15)
    resp.raise_for_status()
    races_raw = resp.json()['MRData']['RaceTable']['Races']

    race_entries = []
    for race in races_raw[-last_n:]:
        result = race.get('Results', [{}])[0]
        race_entries.append({
            'round':     int(race.get('round', 0)),
            'race_name': race.get('raceName', ''),
            'grid':      result.get('grid'),
            'position':  result.get('position'),
            'status':    result.get('status', ''),
        })

    deltas = _compute_positions_gained(race_entries)
    trend = _classify_form_trend(deltas)

    rolling_avg = []
    for i in range(len(deltas)):
        window = deltas[max(0, i - 2):i + 1]
        rolling_avg.append(round(sum(window) / len(window), 2))

    per_race = []
    for r in race_entries:
        try:
            pos_int = int(r['position']) if r['position'] else 0
        except (TypeError, ValueError):
            pos_int = 0
        try:
            grid_int = int(r['grid']) if r['grid'] else 0
        except (TypeError, ValueError):
            grid_int = 0
        gained = (grid_int - pos_int) if pos_int > 0 and grid_int > 0 else None
        per_race.append({
            'round':            r['round'],
            'race_name':        r['race_name'].replace(' Grand Prix', ''),
            'grid':             grid_int or None,
            'finish':           pos_int or None,
            'positions_gained': gained,
            'status':           r['status'],
        })

    return {
        'driver':               driver_code,
        'races_analysed':       len(deltas),
        'trend':                trend,
        'avg_positions_gained': round(sum(deltas) / len(deltas), 2) if deltas else 0.0,
        'per_race':             per_race,
        'rolling_avg':          rolling_avg,
    }


# ---------------------------------------------------------------------------
# FEAT-08: Safety Car Probability
# ---------------------------------------------------------------------------

_SC_PROBABILITY_BY_CIRCUIT: dict[str, float] = {
    'Baku':              0.78,
    'Singapore':         0.72,
    'Monaco':            0.65,
    'Jeddah':            0.65,
    'Melbourne':         0.58,
    'Spa':               0.55,
    'Las Vegas':         0.55,
    'Brazil':            0.55,
    'Japan':             0.50,
    'Hungaroring':       0.45,
    'Silverstone':       0.43,
    'Austin':            0.43,
    'Miami':             0.42,
    'Zandvoort':         0.42,
    'Mexico City':       0.40,
    'Imola':             0.38,
    'Abu Dhabi':         0.36,
    'Barcelona':         0.35,
    'China':             0.35,
    'Bahrain':           0.33,
    'Monza':             0.30,
    'Canada':            0.29,
    'Lusail':            0.28,
}

_SC_SERIES_AVERAGE = 0.42


def _sc_probability_for_circuit(circuit_name: str) -> float:
    """Lookup SC probability by circuit name. Partial match. Returns series average if unknown."""
    name_lower = circuit_name.lower()
    for key, prob in _SC_PROBABILITY_BY_CIRCUIT.items():
        if key.lower() in name_lower or name_lower in key.lower():
            return prob
    return _SC_SERIES_AVERAGE


def get_sc_probability(round_number: int) -> dict:
    """
    Return historical SC/VSC probability for the circuit hosting round_number.
    """
    url = f"{JOLPICA_BASE}/current/{round_number}.json"
    resp = requests.get(url, timeout=15)
    resp.raise_for_status()
    data = resp.json()['MRData']['RaceTable']['Races']
    if not data:
        return {'error': f'Round {round_number} not found in current season'}

    race = data[0]
    circuit_name = race['Circuit']['circuitName']
    race_name    = race['raceName']

    prob = _sc_probability_for_circuit(circuit_name)

    historical = sorted(_SC_PROBABILITY_BY_CIRCUIT.items(), key=lambda x: x[1], reverse=True)
    rank = next(
        (i + 1 for i, (k, _) in enumerate(historical)
         if k.lower() in circuit_name.lower() or circuit_name.lower() in k.lower()),
        None
    )

    return {
        'circuit_name':           circuit_name,
        'race_name':              race_name,
        'round':                  round_number,
        'sc_probability':         prob,
        'sc_probability_pct':     round(prob * 100, 1),
        'classification':         (
            'very high (street circuit)' if prob >= 0.65 else
            'high' if prob >= 0.50 else
            'moderate' if prob >= 0.38 else
            'low'
        ),
        'circuits_ranked':        len(_SC_PROBABILITY_BY_CIRCUIT),
        'rank_by_sc_probability': rank,
        'series_average_pct':     round(_SC_SERIES_AVERAGE * 100, 1),
        'interpretation': (
            f"{circuit_name} has a {round(prob * 100)}% historical SC/VSC rate "
            f"({'above' if prob > _SC_SERIES_AVERAGE else 'below'} the "
            f"{round(_SC_SERIES_AVERAGE * 100)}% series average). "
            f"{'High SC probability — undercut and cover both viable; evaluate 1-stop vs 2-stop carefully.' if prob >= 0.50 else 'Lower SC likelihood; standard degradation strategy applies.'}"
        ),
    }


# ---------------------------------------------------------------------------
# FEAT-20: Head-to-Head Driver History
# ---------------------------------------------------------------------------

def _compute_head_to_head_stats(
    comparisons: list[dict], driver_a: str, driver_b: str
) -> dict:
    """
    Compare finishing positions in shared races.
    comparisons: list of {'driver_a_pos': int, 'driver_b_pos': int}
    Races with either driver DNF (pos <= 0) are excluded.
    avg_position_delta = avg(driver_b_pos - driver_a_pos); positive = A consistently ahead.
    """
    valid = [
        c for c in comparisons
        if c.get('driver_a_pos', 0) > 0 and c.get('driver_b_pos', 0) > 0
    ]
    n = len(valid)
    if n == 0:
        return {
            'driver_a': driver_a, 'driver_b': driver_b,
            'races_together': 0, 'driver_a_wins': 0, 'driver_b_wins': 0,
            'driver_a_win_rate': None, 'avg_position_delta': None,
        }

    a_wins = sum(1 for c in valid if c['driver_a_pos'] < c['driver_b_pos'])
    b_wins = sum(1 for c in valid if c['driver_b_pos'] < c['driver_a_pos'])
    deltas = [c['driver_b_pos'] - c['driver_a_pos'] for c in valid]

    return {
        'driver_a':           driver_a,
        'driver_b':           driver_b,
        'races_together':     n,
        'driver_a_wins':      a_wins,
        'driver_b_wins':      b_wins,
        'ties':               n - a_wins - b_wins,
        'driver_a_win_rate':  round(a_wins / n, 3),
        'driver_b_win_rate':  round(b_wins / n, 3),
        'avg_position_delta': round(sum(deltas) / n, 2),
    }


def get_head_to_head_history(
    driver_a: str, driver_b: str, seasons: list[int] | None = None
) -> dict:
    """
    Multi-season head-to-head race results between driver_a and driver_b.
    seasons defaults to the last 3 complete seasons.
    """
    current_year = CURRENT_YEAR
    if seasons is None:
        seasons = [current_year - 3, current_year - 2, current_year - 1]

    matched_a = _resolve_driver(driver_a)
    matched_b = _resolve_driver(driver_b)
    if not matched_a:
        return {'error': f'Driver not found: {driver_a}'}
    if not matched_b:
        return {'error': f'Driver not found: {driver_b}'}

    drv_a_id   = matched_a['driver_id']
    drv_b_id   = matched_b['driver_id']
    drv_a_code = matched_a['code']
    drv_b_code = matched_b['code']

    def _fetch_results(driver_id: str, year: int) -> dict:
        url = f"{JOLPICA_BASE}/{year}/drivers/{driver_id}/results.json?limit=30"
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        races_data = resp.json()['MRData']['RaceTable']['Races']
        by_key = {}
        for race in races_data:
            key = (int(race['season']), int(race['round']))
            result = race.get('Results', [{}])[0]
            try:
                pos = int(result.get('position', 0))
            except (TypeError, ValueError):
                pos = 0
            by_key[key] = {
                'race_name': race['raceName'],
                'circuit':   race['Circuit']['circuitName'],
                'position':  pos,
                'grid':      int(result.get('grid', 0) or 0),
                'status':    result.get('status', ''),
            }
        return by_key

    all_comparisons = []
    per_race_rows = []

    for season in seasons:
        results_a = _fetch_results(drv_a_id, season)
        results_b = _fetch_results(drv_b_id, season)
        shared_keys = sorted(set(results_a) & set(results_b))
        for key in shared_keys:
            ra = results_a[key]
            rb = results_b[key]
            all_comparisons.append({
                'driver_a_pos': ra['position'],
                'driver_b_pos': rb['position'],
            })
            winner = None
            if ra['position'] > 0 and rb['position'] > 0:
                winner = drv_a_code if ra['position'] < rb['position'] else drv_b_code
            per_race_rows.append({
                'season':    key[0],
                'round':     key[1],
                'race_name': ra['race_name'].replace(' Grand Prix', ''),
                'circuit':   ra['circuit'],
                'a_position': ra['position'] or None,
                'b_position': rb['position'] or None,
                'a_grid':    ra['grid'] or None,
                'b_grid':    rb['grid'] or None,
                'winner':    winner,
            })

    stats = _compute_head_to_head_stats(all_comparisons, drv_a_code, drv_b_code)

    avg_delta = stats.get('avg_position_delta', 0) or 0
    dominant = (
        drv_a_code if avg_delta > 0.5 else
        drv_b_code if avg_delta < -0.5 else
        'evenly matched'
    )

    return {
        **stats,
        'seasons_analysed': seasons,
        'per_race':         per_race_rows,
        'dominant_driver':  dominant,
    }


# ---------------------------------------------------------------------------
# FEAT-17: Per-Session Driver Style Fingerprint
# ---------------------------------------------------------------------------

_STYLE_METRICS = [
    'trail_brake_pct',
    'throttle_acceptance_pct',
    'entry_bravery_pct',
    'avg_ggv_util_pct',
    'apex_speed_kph',
]


def _aggregate_style_fingerprint(corners: list[dict]) -> dict:
    """
    Aggregate per-corner style metrics into session-level means.
    Skips None values per metric. Returns None for any metric with no valid corners.
    """
    if not corners:
        return {m: None for m in _STYLE_METRICS} | {'corner_count': 0}

    result: dict = {'corner_count': len(corners)}
    for metric in _STYLE_METRICS:
        vals = [c[metric] for c in corners if c.get(metric) is not None]
        result[metric] = round(sum(vals) / len(vals), 2) if vals else None
    return result


def get_session_style_fingerprint(
    round_number: int, session_type: str, driver_name: str
) -> dict:
    """
    Aggregate cornering metrics across all corners in the session into a style fingerprint.
    Calls analyze_cornering_loads internally.
    """
    cornering = analyze_cornering_loads(round_number, session_type, driver_name)
    corners = cornering.get('corners', [])

    fingerprint = _aggregate_style_fingerprint(corners)

    return {
        'driver':                  driver_name.upper(),
        'round':                   round_number,
        'session':                 session_type,
        'corner_count':            fingerprint['corner_count'],
        'trail_brake_pct':         fingerprint.get('trail_brake_pct'),
        'throttle_acceptance_pct': fingerprint.get('throttle_acceptance_pct'),
        'entry_bravery_pct':       fingerprint.get('entry_bravery_pct'),
        'avg_ggv_util_pct':        fingerprint.get('avg_ggv_util_pct'),
        'avg_apex_speed_kph':      fingerprint.get('apex_speed_kph'),
        'interpretation_hints': {
            'trail_brake_pct':         'High (>50%) = carries braking into corners (late-braker style)',
            'throttle_acceptance_pct': 'High (>60%) = early throttle application (V-line style)',
            'entry_bravery_pct':       'High (>55%) = high entry speed relative to circuit norms',
            'avg_ggv_util_pct':        'High (>80%) = near the traction/grip limit throughout',
        },
    }


def get_driver_skill_rating(driver_name: str) -> dict:
    """
    Return Bayesian skill estimate for a driver from the pre-computed cache.
    driver_name: 3-letter code (NOR) or surname (normalised internally).
    Includes rank among all rated drivers, credible interval, and Elo cross-check.
    """
    from driver_rating import load_cached_ratings, _CACHE_PATH

    cache = load_cached_ratings(_CACHE_PATH)
    if cache is None:
        return {
            'error': 'Driver rating cache not built yet. Run POST /api/admin/rebuild-driver-ratings to generate ratings.',
            'driver': driver_name.upper(),
        }

    driver_code = driver_name.upper().strip()[:3]
    skills = cache.get('driver_skills', {})

    if driver_code not in skills:
        return {
            'error': f"Driver '{driver_code}' not found in ratings. Available: {sorted(skills.keys())}",
            'driver': driver_code,
        }

    skill = skills[driver_code]

    sorted_drivers = sorted(skills.items(), key=lambda x: x[1]['mean'], reverse=True)
    rank = next(i + 1 for i, (k, _) in enumerate(sorted_drivers) if k == driver_code)

    skill_in_seconds = round(skill['mean'] * 0.3, 2)

    elo = cache.get('elo_driver_ratings', {}).get(driver_code)
    seasons = cache.get('seasons', [])

    return {
        'driver':            driver_code,
        'skill_mean':        skill['mean'],
        'skill_std':         skill['std'],
        'hdi_5':             skill['hdi_5'],
        'hdi_95':            skill['hdi_95'],
        'rank':              rank,
        'n_drivers_rated':   len(skills),
        'skill_in_seconds':  skill_in_seconds,
        'elo_rating':        elo,
        'seasons_used':      seasons,
        'n_comparisons':     cache.get('n_comparisons'),
        'built_at_iso':      time.strftime('%Y-%m-%d', time.gmtime(cache.get('built_at', 0))),
        'interpretation': (
            f"{driver_code} is ranked #{rank} of {len(skills)} rated drivers. "
            f"Posterior mean skill: {skill['mean']:+.2f} SD units "
            f"({'+' if skill_in_seconds >= 0 else ''}{skill_in_seconds}s/lap vs median driver in median car). "
            f"90% credible interval: [{skill['hdi_5']:+.2f}, {skill['hdi_95']:+.2f}] SD. "
            f"Model trained on {cache.get('n_comparisons', '?')} comparisons from {seasons}."
        ),
    }
