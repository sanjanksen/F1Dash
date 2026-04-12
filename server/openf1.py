import requests

from f1_data import CURRENT_YEAR, _resolve_driver, get_circuits, get_session_results

OPENF1_BASE = "https://api.openf1.org/v1"


def _session_name_for_openf1(session_type: str) -> str:
    mapping = {
        "FP1": "Practice 1",
        "FP2": "Practice 2",
        "FP3": "Practice 3",
        "Q": "Qualifying",
        "R": "Race",
        "S": "Sprint",
        "SQ": "Sprint Qualifying",
        "SS": "Sprint Shootout",
    }
    normalized = str(session_type).strip().upper()
    if normalized not in mapping:
        raise ValueError(f"Unsupported OpenF1 session type: {session_type!r}")
    return mapping[normalized]


def _openf1_get(endpoint: str, **params):
    response = requests.get(f"{OPENF1_BASE}/{endpoint}", params=params, timeout=20)
    response.raise_for_status()
    return response.json()


def _resolve_openf1_session(round_number: int, session_type: str) -> dict:
    circuit = next((row for row in get_circuits() if row.get("round") == round_number), None)
    if not circuit:
        raise ValueError(f"Round {round_number} not found in {CURRENT_YEAR} schedule.")

    session_name = _session_name_for_openf1(session_type)
    sessions = _openf1_get(
        "sessions",
        year=CURRENT_YEAR,
        country_name=circuit["country"],
        session_name=session_name,
    )
    if not sessions:
        raise ValueError(
            f"OpenF1 session not found for round {round_number} ({circuit['event_name']}) {session_name}."
        )

    sessions = sorted(sessions, key=lambda row: row.get("date_start", ""))
    return sessions[-1]


def _driver_number_for_session(round_number: int, session_type: str, driver_ref: str) -> int:
    matched = _resolve_driver(driver_ref)
    if matched is None:
        raise ValueError(f"Driver not found: {driver_ref!r}")

    session_results = get_session_results(round_number, session_type)
    row = next(
        (
            result for result in session_results.get("results", [])
            if (result.get("abbreviation") or "").upper() == (matched.get("code") or "").upper()
        ),
        None,
    )
    if row is None or not row.get("driver_number"):
        raise ValueError(f"Driver number unavailable for {matched['full_name']} in round {round_number} {session_type}.")
    return int(row["driver_number"])


def get_team_radio(round_number: int, session_type: str, driver_ref: str | None = None, limit: int = 10) -> dict:
    session = _resolve_openf1_session(round_number, session_type)
    params = {"session_key": session["session_key"]}
    driver_number = None
    driver_name = None
    if driver_ref:
        driver_number = _driver_number_for_session(round_number, session_type, driver_ref)
        matched = _resolve_driver(driver_ref)
        driver_name = matched["full_name"] if matched else driver_ref
        params["driver_number"] = driver_number

    radios = _openf1_get("team_radio", **params)
    radios = sorted(radios, key=lambda row: row.get("date", ""), reverse=True)[:limit]
    return {
        "event": session.get("session_name"),
        "country": session.get("country_name"),
        "circuit": session.get("circuit_short_name"),
        "session_key": session.get("session_key"),
        "driver_number": driver_number,
        "driver": driver_name,
        "messages": [
            {
                "date": row.get("date"),
                "driver_number": row.get("driver_number"),
                "recording_url": row.get("recording_url"),
            }
            for row in radios
        ],
    }


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
    rows = sorted(rows, key=lambda row: row.get("date", ""), reverse=True)[:limit]
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


def get_live_position_timeline(round_number: int, session_type: str, driver_ref: str | None = None, limit: int = 50) -> dict:
    session = _resolve_openf1_session(round_number, session_type)
    params = {"session_key": session["session_key"]}
    driver_number = None
    driver_name = None
    if driver_ref:
        driver_number = _driver_number_for_session(round_number, session_type, driver_ref)
        matched = _resolve_driver(driver_ref)
        driver_name = matched["full_name"] if matched else driver_ref
        params["driver_number"] = driver_number

    rows = _openf1_get("position", **params)
    rows = sorted(rows, key=lambda row: row.get("date", ""), reverse=True)[:limit]
    return {
        "event": session.get("session_name"),
        "country": session.get("country_name"),
        "circuit": session.get("circuit_short_name"),
        "session_key": session.get("session_key"),
        "driver_number": driver_number,
        "driver": driver_name,
        "positions": [
            {
                "date": row.get("date"),
                "driver_number": row.get("driver_number"),
                "position": row.get("position"),
            }
            for row in rows
        ],
    }
