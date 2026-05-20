"""2026 active-aero (X/Z) detection.

X-mode = high-drag default (corners, low-speed).
Z-mode = low-drag, auto-activates on FIA-permitted straights.

FastF1 in 2026 may expose an aero-state channel (possibly repurposed DRS).
If so, callers should pass `aero_state_channel` and Path A returns directly.
Path B is a heuristic fallback: inside a per-circuit aero zone, speed > 250 km/h,
past the first 100 m of the zone (transition lag).

The heuristic will misfire on slow laps (false positives outside qualifying pace)
and mid-zone lifts (false negatives). Callers should mark widget output as
`inferred=True` when Path B fires.

Zone distances below are editorial best-guess based on 2024-2025 DRS-zone heritage
(2026 aero-zone locations not yet published). All entries are tagged with
`source: "pending citation"` and a `last_reviewed` date.
"""

# Per-circuit aero zone definitions. Keys match CIRCUIT_PROFILES keys in
# server/circuit_profiles.py. 2026 calendar has 24 circuits; coverage below is
# the full set, all 24 populated.
CIRCUIT_AERO_ZONES: dict[str, dict] = {
    "bahrain": {
        "circuit_country": "Bahrain",
        "zones": [
            {"label": "main_straight", "start_distance_m": 0,    "end_distance_m": 1090},
            {"label": "back_straight", "start_distance_m": 2400, "end_distance_m": 3100},
        ],
        "last_reviewed": "2026-05-20",
        "source": "pending citation",
    },
    "saudi_arabia": {
        "circuit_country": "Saudi Arabia",
        "zones": [
            {"label": "main_straight",   "start_distance_m": 0,    "end_distance_m": 1100},
            {"label": "back_straight_1", "start_distance_m": 2700, "end_distance_m": 3300},
        ],
        "last_reviewed": "2026-05-20",
        "source": "pending citation",
    },
    "australia": {
        "circuit_country": "Australia",
        "zones": [
            {"label": "main_straight", "start_distance_m": 0,    "end_distance_m": 900},
            {"label": "lakeside",      "start_distance_m": 2400, "end_distance_m": 3100},
        ],
        "last_reviewed": "2026-05-20",
        "source": "pending citation",
    },
    "japan": {
        "circuit_country": "Japan",
        "zones": [
            {"label": "main_straight", "start_distance_m": 0, "end_distance_m": 1100},
        ],
        "last_reviewed": "2026-05-20",
        "source": "pending citation",
    },
    "china": {
        "circuit_country": "China",
        "zones": [
            {"label": "main_straight", "start_distance_m": 0,    "end_distance_m": 1100},
            {"label": "back_straight", "start_distance_m": 3200, "end_distance_m": 4400},
        ],
        "last_reviewed": "2026-05-20",
        "source": "pending citation",
    },
    "miami": {
        "circuit_country": "United States",
        "zones": [
            {"label": "main_straight", "start_distance_m": 0,    "end_distance_m": 900},
            {"label": "back_straight", "start_distance_m": 2300, "end_distance_m": 3400},
        ],
        "last_reviewed": "2026-05-20",
        "source": "pending citation",
    },
    "emilia_romagna": {
        "circuit_country": "Italy",
        "zones": [
            {"label": "main_straight", "start_distance_m": 0, "end_distance_m": 800},
        ],
        "last_reviewed": "2026-05-20",
        "source": "pending citation",
    },
    "monaco": {
        "circuit_country": "Monaco",
        # Monaco historically had no DRS zone of useful length; aero zone is the
        # tunnel exit / start-finish region only and Z-mode rarely activates.
        "zones": [
            {"label": "tunnel_exit_to_chicane", "start_distance_m": 1600, "end_distance_m": 2200},
        ],
        "last_reviewed": "2026-05-20",
        "source": "pending citation",
    },
    "canada": {
        "circuit_country": "Canada",
        "zones": [
            {"label": "main_straight",  "start_distance_m": 0,    "end_distance_m": 1100},
            {"label": "back_straight",  "start_distance_m": 2400, "end_distance_m": 3500},
        ],
        "last_reviewed": "2026-05-20",
        "source": "pending citation",
    },
    "spain": {
        "circuit_country": "Spain",
        "zones": [
            {"label": "main_straight", "start_distance_m": 0,    "end_distance_m": 1000},
            {"label": "back_straight", "start_distance_m": 2300, "end_distance_m": 3100},
        ],
        "last_reviewed": "2026-05-20",
        "source": "pending citation",
    },
    "austria": {
        "circuit_country": "Austria",
        "zones": [
            {"label": "main_straight", "start_distance_m": 0,    "end_distance_m": 900},
            {"label": "t1_to_t3",      "start_distance_m": 1100, "end_distance_m": 1700},
            {"label": "t4_exit",       "start_distance_m": 2500, "end_distance_m": 3200},
        ],
        "last_reviewed": "2026-05-20",
        "source": "pending citation",
    },
    "britain": {
        "circuit_country": "Great Britain",
        "zones": [
            {"label": "wellington_straight", "start_distance_m": 600,  "end_distance_m": 1400},
            {"label": "hangar_straight",     "start_distance_m": 3200, "end_distance_m": 4100},
        ],
        "last_reviewed": "2026-05-20",
        "source": "pending citation",
    },
    "belgium": {
        "circuit_country": "Belgium",
        "zones": [
            {"label": "kemmel",        "start_distance_m": 1900, "end_distance_m": 3100},
            {"label": "back_straight", "start_distance_m": 4800, "end_distance_m": 5600},
        ],
        "last_reviewed": "2026-05-20",
        "source": "pending citation",
    },
    "hungary": {
        "circuit_country": "Hungary",
        "zones": [
            {"label": "main_straight", "start_distance_m": 0, "end_distance_m": 900},
        ],
        "last_reviewed": "2026-05-20",
        "source": "pending citation",
    },
    "netherlands": {
        "circuit_country": "Netherlands",
        "zones": [
            {"label": "main_straight", "start_distance_m": 0, "end_distance_m": 700},
        ],
        "last_reviewed": "2026-05-20",
        "source": "pending citation",
    },
    "italy": {
        "circuit_country": "Italy",
        "zones": [
            {"label": "start_finish",    "start_distance_m": 0,    "end_distance_m": 1100},
            {"label": "back_straight",   "start_distance_m": 3100, "end_distance_m": 3900},
            {"label": "parabolica_exit", "start_distance_m": 4900, "end_distance_m": 5400},
        ],
        "last_reviewed": "2026-05-20",
        "source": "pending citation",
    },
    "azerbaijan": {
        "circuit_country": "Azerbaijan",
        "zones": [
            # The Turn-16-to-Turn-1 start/finish straight (~2.2 km) is the
            # longest single straight in F1.
            {"label": "main_straight_t16_to_t1", "start_distance_m": 4000, "end_distance_m": 6200},
            {"label": "seafront",                "start_distance_m": 1800, "end_distance_m": 2500},
        ],
        "last_reviewed": "2026-05-20",
        "source": "pending citation",
    },
    "singapore": {
        "circuit_country": "Singapore",
        "zones": [
            {"label": "raffles_blvd_to_t1", "start_distance_m": 4400, "end_distance_m": 5063},
            {"label": "esplanade",          "start_distance_m": 1500, "end_distance_m": 2100},
        ],
        "last_reviewed": "2026-05-20",
        "source": "pending citation",
    },
    "united_states": {
        "circuit_country": "United States",
        "zones": [
            {"label": "back_straight", "start_distance_m": 950,  "end_distance_m": 2000},
            {"label": "main_straight", "start_distance_m": 4900, "end_distance_m": 5500},
        ],
        "last_reviewed": "2026-05-20",
        "source": "pending citation",
    },
    "mexico": {
        "circuit_country": "Mexico",
        "zones": [
            {"label": "recta_principal", "start_distance_m": 0,    "end_distance_m": 1200},
            {"label": "back_section",    "start_distance_m": 2500, "end_distance_m": 3100},
        ],
        "last_reviewed": "2026-05-20",
        "source": "pending citation",
    },
    "brazil": {
        "circuit_country": "Brazil",
        "zones": [
            {"label": "reta_oposta",  "start_distance_m": 1400, "end_distance_m": 2100},
            {"label": "main_straight","start_distance_m": 3500, "end_distance_m": 4309},
        ],
        "last_reviewed": "2026-05-20",
        "source": "pending citation",
    },
    "las_vegas": {
        "circuit_country": "United States",
        "zones": [
            {"label": "strip_straight",        "start_distance_m": 2500, "end_distance_m": 4400},
            {"label": "return_strip_straight", "start_distance_m": 5000, "end_distance_m": 6201},
        ],
        "last_reviewed": "2026-05-20",
        "source": "pending citation",
    },
    "qatar": {
        "circuit_country": "Qatar",
        "zones": [
            {"label": "main_straight", "start_distance_m": 0, "end_distance_m": 1100},
        ],
        "last_reviewed": "2026-05-20",
        "source": "pending citation",
    },
    "abu_dhabi": {
        "circuit_country": "Abu Dhabi",
        "zones": [
            {"label": "post_t5_straight",  "start_distance_m": 800,  "end_distance_m": 1700},
            {"label": "post_t9_straight",  "start_distance_m": 2300, "end_distance_m": 3300},
        ],
        "last_reviewed": "2026-05-20",
        "source": "pending citation",
    },
}


_TRANSITION_LAG_M = 100.0
_MIN_Z_MODE_SPEED_KPH = 250.0


def is_z_mode(
    speed_kph: float,
    distance_on_lap_m: float,
    circuit_slug: str,
    *,
    aero_state_channel: int | None = None,
) -> bool:
    """Return True if active aero is in Z-mode (low-drag) at this sample.

    Path A (preferred): if `aero_state_channel` is provided, return it directly
    (any non-zero int is treated as Z-mode active).
    Path B (fallback): inside a CIRCUIT_AERO_ZONES band for circuit_slug,
    speed > 250 km/h, and past the first 100 m of the zone (transition lag).
    """
    if aero_state_channel is not None:
        try:
            return int(aero_state_channel) != 0
        except (TypeError, ValueError):
            return False

    profile = CIRCUIT_AERO_ZONES.get(circuit_slug)
    if not profile or speed_kph < _MIN_Z_MODE_SPEED_KPH:
        return False
    for zone in profile.get("zones", []):
        zone_start = zone["start_distance_m"]
        zone_end = zone["end_distance_m"]
        if zone_start + _TRANSITION_LAG_M <= distance_on_lap_m <= zone_end:
            return True
    return False


def get_circuit_aero_zones(circuit_slug: str) -> list[dict] | None:
    """Return aero zone list for a circuit, or None if not in coverage."""
    profile = CIRCUIT_AERO_ZONES.get(circuit_slug)
    return profile.get("zones") if profile else None


def get_zone_label_at(circuit_slug: str, distance_on_lap_m: float) -> str | None:
    """Return the zone label whose distance band contains this sample, or None."""
    profile = CIRCUIT_AERO_ZONES.get(circuit_slug)
    if not profile:
        return None
    for zone in profile.get("zones", []):
        if zone["start_distance_m"] <= distance_on_lap_m <= zone["end_distance_m"]:
            return zone.get("label")
    return None
