"""Regex-tag an article body for driver/team/circuit mentions."""
from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)


_FALLBACK_DRIVER_CODES: list[tuple[str, list[str]]] = [
    ("VER", ["verstappen", "max verstappen"]),
    ("NOR", ["norris", "lando norris"]),
    ("PIA", ["piastri", "oscar piastri"]),
    ("LEC", ["leclerc", "charles leclerc"]),
    ("HAM", ["hamilton", "lewis hamilton"]),
    ("RUS", ["russell", "george russell"]),
    ("ANT", ["antonelli", "kimi antonelli"]),
    ("ALO", ["alonso", "fernando alonso"]),
    ("STR", ["stroll", "lance stroll"]),
    ("SAI", ["sainz", "carlos sainz"]),
    ("ALB", ["albon", "alex albon", "alexander albon"]),
    ("GAS", ["gasly", "pierre gasly"]),
    ("OCO", ["ocon", "esteban ocon"]),
    ("HUL", ["hulkenberg", "hülkenberg", "nico hulkenberg"]),
    ("BOR", ["bortoleto", "gabriel bortoleto"]),
    ("BEA", ["bearman", "oliver bearman", "ollie bearman"]),
    ("TSU", ["tsunoda", "yuki tsunoda"]),
    ("LAW", ["lawson", "liam lawson"]),
    ("HAD", ["hadjar", "isack hadjar"]),
    ("DOO", ["doohan", "jack doohan"]),
]


def _drivers_for_tagging() -> list[tuple[str, list[str]]]:
    try:
        from resolver import _cached_drivers
        drivers = _cached_drivers()
    except Exception:
        drivers = []

    out: list[tuple[str, list[str]]] = []
    for d in drivers or []:
        code = (d.get("code") or "").upper().strip()
        full = (d.get("full_name") or "").strip().lower()
        if not code:
            continue
        surname = full.split()[-1] if full else ""
        aliases = [a for a in [full, surname] if a]
        out.append((code, aliases))
    if out:
        return out
    return _FALLBACK_DRIVER_CODES


def _teams_for_tagging() -> list[str]:
    try:
        from team_car_profiles import TEAM_CAR_PROFILES
        return list(TEAM_CAR_PROFILES.keys())
    except Exception:
        return ["ferrari", "mercedes", "mclaren", "red bull", "aston martin",
                "alpine", "williams", "haas", "racing bulls", "audi"]


def _circuits_for_tagging() -> list[str]:
    try:
        from circuit_profiles import CIRCUIT_PROFILES
        return list(CIRCUIT_PROFILES.keys())
    except Exception:
        return []


def tag_subjects(article_id: int, body: str, title: str = "") -> list[dict]:
    """Return deduplicated [{article_id, kind, ref}] rows for what the text mentions."""
    haystack = f"{title}\n{body}".lower()
    if not haystack.strip():
        return []

    rows: list[dict] = []
    seen: set[tuple[str, str]] = set()

    for code, aliases in _drivers_for_tagging():
        for alias in aliases:
            if not alias:
                continue
            if re.search(rf"\b{re.escape(alias.lower())}\b", haystack):
                key = ("driver", code)
                if key not in seen:
                    seen.add(key)
                    rows.append({"article_id": article_id, "kind": "driver", "ref": code})
                break

    for team in _teams_for_tagging():
        if re.search(rf"\b{re.escape(team.lower())}\b", haystack):
            key = ("team", team.lower())
            if key not in seen:
                seen.add(key)
                rows.append({"article_id": article_id, "kind": "team", "ref": team.lower()})

    for slug in _circuits_for_tagging():
        word = slug.replace("_", " ")
        if re.search(rf"\b{re.escape(word.lower())}\b", haystack):
            key = ("circuit", slug)
            if key not in seen:
                seen.add(key)
                rows.append({"article_id": article_id, "kind": "circuit", "ref": slug})

    return rows
