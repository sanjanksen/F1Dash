# server/f1_data.py
import os
import fastf1
import requests

# Enable FastF1 disk cache
_CACHE_DIR = os.path.join(os.path.dirname(__file__), 'cache')
os.makedirs(_CACHE_DIR, exist_ok=True)
fastf1.Cache.enable_cache(_CACHE_DIR)

JOLPICA_BASE = "https://api.jolpi.ca/ergast/f1"
CURRENT_YEAR = 2025


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

    driver_id = matched["driver_id"]

    resp = requests.get(
        f"{JOLPICA_BASE}/{CURRENT_YEAR}/drivers/{driver_id}/results.json?limit=30",
        timeout=15,
    )
    resp.raise_for_status()
    races = resp.json()["MRData"]["RaceTable"]["Races"]

    wins = 0
    podiums = 0
    fastest_laps = 0
    recent_races = []

    for race in races:
        results = race.get("Results", [])
        if not results:
            continue
        r = results[0]
        pos_str = r.get("position", "0")
        pos = int(pos_str) if pos_str.isdigit() else 0
        points = float(r.get("points", 0))

        if pos == 1:
            wins += 1
        if 1 <= pos <= 3:
            podiums += 1

        fl = r.get("FastestLap", {})
        if fl.get("rank") == "1":
            fastest_laps += 1

        recent_races.append({
            "race": race.get("raceName", ""),
            "position": pos,
            "points": points,
            "fastest_lap": fl.get("rank") == "1",
        })

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
        "recent_races": recent_races[-5:],
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


def get_f1_context(message: str) -> str:
    """Build a concise F1 data context string for the chat endpoint."""
    parts: list[str] = []

    try:
        drivers = get_drivers()
        lines = [f"  {d['standing']}. {d['full_name']} ({d['team']}) — {d['points']} pts, {d['wins']} wins"
                 for d in drivers[:10]]
        parts.append("=== 2025 Driver Championship Standings (Top 10) ===\n" + "\n".join(lines))
    except Exception as exc:
        parts.append(f"[Standings unavailable: {exc}]")

    try:
        circuits = get_circuits()
        upcoming = [c for c in circuits if c["date"] >= "2025-04-11"][:3]
        lines = [f"  Round {c['round']}: {c['event_name']} ({c['country']}) — {c['date']}"
                 for c in upcoming]
        parts.append("=== Upcoming Races ===\n" + "\n".join(lines))
    except Exception as exc:
        parts.append(f"[Schedule unavailable: {exc}]")

    return "\n\n".join(parts)
