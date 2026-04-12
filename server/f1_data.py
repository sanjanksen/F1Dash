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
