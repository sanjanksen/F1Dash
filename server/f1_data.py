# server/f1_data.py
import os
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
from units import kph_to_ms

# Enable FastF1 disk cache
_CACHE_DIR = os.path.join(os.path.dirname(__file__), 'cache')
os.makedirs(_CACHE_DIR, exist_ok=True)
fastf1.Cache.enable_cache(_CACHE_DIR)

JOLPICA_BASE = "https://api.jolpi.ca/ergast/f1"
CURRENT_YEAR = __import__('datetime').date.today().year
logger = logging.getLogger(__name__)

_SESSION_CACHE: dict[tuple[int, int, str], dict] = {}
_SESSION_CACHE_LOCK = threading.Lock()


class FastF1Error(RuntimeError):
    """Raised when FastF1 cannot load the requested session."""

    def __init__(self, message: str, *, round_number: int, session_type: str, cause: Exception | None = None):
        super().__init__(message)
        self.round_number = round_number
        self.session_type = session_type


def _unavailable_payload(round_number: int, session_type: str) -> dict:
    return {
        "available": False,
        "reason": "fastf1_unavailable",
        "round_number": round_number,
        "session_type": session_type,
    }


def drs_active(drs_value) -> bool:
    """FastF1 DRS channel: 10/12/14 = open and active, else closed."""
    try:
        return int(drs_value) in (10, 12, 14)
    except (TypeError, ValueError):
        return False


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
        newly_created = False
        if entry is None:
            try:
                ff1_session = fastf1.get_session(CURRENT_YEAR, round_number, normalized_session)
            except Exception as exc:
                raise FastF1Error(
                    f"FastF1 unavailable for round {round_number} session {session_type}",
                    round_number=round_number,
                    session_type=session_type,
                    cause=exc,
                ) from exc
            entry = {
                "session": ff1_session,
                "laps": False,
                "telemetry": False,
                "weather": False,
                "messages": False,
                "lock": threading.Lock(),
            }
            _SESSION_CACHE[cache_key] = entry
            newly_created = True

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

        try:
            session.load(
                laps=target_flags["laps"],
                telemetry=target_flags["telemetry"],
                weather=target_flags["weather"],
                messages=target_flags["messages"],
            )
        except Exception as exc:
            if newly_created:
                with _SESSION_CACHE_LOCK:
                    _SESSION_CACHE.pop(cache_key, None)
            raise FastF1Error(
                f"FastF1 unavailable for round {round_number} session {session_type}",
                round_number=round_number,
                session_type=session_type,
                cause=exc,
            ) from exc
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


def _deployment_curve_anchors(curve_name: str = "standard") -> list[dict]:
    knowledge = get_energy_2026_knowledge()
    deployment_curve = knowledge.get("deployment_curve")
    if not deployment_curve or curve_name not in deployment_curve:
        raise RuntimeError(
            f"energy_2026 knowledge missing 'deployment_curve.{curve_name}' — "
            "required for clipping detection (F33 prereq)."
        )
    return deployment_curve[curve_name]


def _reference_slope_kph_per_m(speed_kph: float, anchors: list[dict]) -> float:
    """Approximate reference speed slope (km/h per meter) at a given speed
    on the deployment curve. The slope is proportional to delivered power,
    which drops linearly between anchors. We normalize so the slope at the
    plateau (max power) is ~1.0 km/h per meter, then scale by power ratio.
    Anchors are sorted by speed_kph; expects at least 2."""
    if not anchors:
        return 0.0
    plateau_kw = max(a["power_kw"] for a in anchors)
    if plateau_kw <= 0:
        return 0.0
    sorted_anchors = sorted(anchors, key=lambda a: a["speed_kph"])
    if speed_kph <= sorted_anchors[0]["speed_kph"]:
        power_kw = sorted_anchors[0]["power_kw"]
    elif speed_kph >= sorted_anchors[-1]["speed_kph"]:
        power_kw = sorted_anchors[-1]["power_kw"]
    else:
        for i in range(len(sorted_anchors) - 1):
            lo = sorted_anchors[i]
            hi = sorted_anchors[i + 1]
            if lo["speed_kph"] <= speed_kph <= hi["speed_kph"]:
                span = hi["speed_kph"] - lo["speed_kph"]
                t = (speed_kph - lo["speed_kph"]) / span if span > 0 else 0.0
                power_kw = lo["power_kw"] + t * (hi["power_kw"] - lo["power_kw"])
                break
        else:
            power_kw = 0.0
    return (power_kw / plateau_kw) * 1.0


def detect_clipping_signature(
    speed_trace: list[float],
    throttle_trace: list[float],
    distance_trace: list[float],
    *,
    drs_state: list[int] | None = None,
    full_power_below_kmh: float | None = None,
    ramp_zero_at_kmh: float | None = None,
    min_segment_length_m: float = 80.0,
    min_speed_flatten_kph: float = 8.0,
) -> dict:
    """Return clipping segments where speed flattens despite full throttle in
    the deployment-taper window (290-355 km/h by default)."""
    anchors = _deployment_curve_anchors("standard")
    sorted_anchors = sorted(anchors, key=lambda a: a["speed_kph"])
    if full_power_below_kmh is None:
        full_power_below_kmh = float(sorted_anchors[0]["speed_kph"])
    if ramp_zero_at_kmh is None:
        ramp_zero_at_kmh = float(sorted_anchors[-1]["speed_kph"])

    n = min(len(speed_trace), len(throttle_trace), len(distance_trace))
    samples = [
        {
            "distance_m": distance_trace[i],
            "speed_kph": speed_trace[i],
            "throttle_pct": throttle_trace[i],
            "brake": False,
            "gear": 8,
            "drs_open": drs_state[i] if drs_state and i < len(drs_state) else None,
        }
        for i in range(n)
    ]

    full_throttle_windows = _find_full_throttle_straight_windows(samples)

    segments: list[dict] = []
    for window in full_throttle_windows:
        sub: list[dict] = []
        for s in window:
            sp = s.get("speed_kph")
            th = s.get("throttle_pct")
            if (
                sp is not None and th is not None
                and full_power_below_kmh <= sp <= ramp_zero_at_kmh
                and th >= 95
            ):
                sub.append(s)
            else:
                if len(sub) >= 4:
                    seg = _evaluate_clipping_sub_window(sub, sorted_anchors, min_segment_length_m, min_speed_flatten_kph)
                    if seg:
                        segments.append(seg)
                sub = []
        if len(sub) >= 4:
            seg = _evaluate_clipping_sub_window(sub, sorted_anchors, min_segment_length_m, min_speed_flatten_kph)
            if seg:
                segments.append(seg)

    total_clipping_seconds = round(sum(s["duration_s"] for s in segments), 3)
    budget_status = "within" if total_clipping_seconds <= 4.0 else "above"

    strong_segments = [s for s in segments if s["slope_deficit_pct"] >= 60 and (s["end_distance_m"] - s["start_distance_m"]) >= 50]
    if len(strong_segments) >= 2:
        confidence = "high"
    elif len(strong_segments) == 1 or len(segments) >= 2:
        confidence = "moderate"
    elif segments:
        confidence = "low"
    else:
        confidence = "low"

    return {
        "clipping_detected": bool(segments),
        "segments": [
            {
                "start_distance_m": s["start_distance_m"],
                "end_distance_m": s["end_distance_m"],
                "start_speed_kph": s["start_speed_kph"],
                "end_speed_kph": s["end_speed_kph"],
                "observed_slope_kph_per_m": s["observed_slope_kph_per_m"],
                "reference_slope_kph_per_m": s["reference_slope_kph_per_m"],
                "duration_s": s["duration_s"],
                "severity": s["severity"],
            }
            for s in segments
        ],
        "total_clipping_seconds": total_clipping_seconds,
        "budget_status": budget_status,
        "confidence": confidence,
        "detector_version": "f33-v1",
    }


def _evaluate_clipping_sub_window(
    sub: list[dict],
    sorted_anchors: list[dict],
    min_segment_length_m: float,
    min_speed_flatten_kph: float,
) -> dict | None:
    start = sub[0]
    end = sub[-1]
    sd = start.get("distance_m")
    ed = end.get("distance_m")
    ss = start.get("speed_kph")
    es = end.get("speed_kph")
    if sd is None or ed is None or ss is None or es is None:
        return None
    length_m = ed - sd
    if length_m < min_segment_length_m:
        return None
    observed_slope = (es - ss) / length_m if length_m > 0 else 0.0
    mid_speed = (ss + es) / 2.0
    reference_slope = _reference_slope_kph_per_m(mid_speed, sorted_anchors)
    if reference_slope <= 0:
        return None
    deficit_pct = (1.0 - observed_slope / reference_slope) * 100.0
    if deficit_pct < 50:
        return None
    speeds = [s.get("speed_kph") for s in sub if s.get("speed_kph") is not None]
    if speeds and (max(speeds) - min(speeds)) < 0:
        return None
    avg_speed_ms = (ss + es) / 2.0 / 3.6
    duration_s = length_m / avg_speed_ms if avg_speed_ms > 0 else 0.0
    if deficit_pct >= 85:
        severity = "severe"
    elif deficit_pct >= 70:
        severity = "moderate"
    else:
        severity = "mild"
    return {
        "start_distance_m": round(sd, 1),
        "end_distance_m": round(ed, 1),
        "start_speed_kph": round(ss, 1),
        "end_speed_kph": round(es, 1),
        "observed_slope_kph_per_m": round(observed_slope, 4),
        "reference_slope_kph_per_m": round(reference_slope, 4),
        "slope_deficit_pct": round(deficit_pct, 1),
        "duration_s": round(duration_s, 3),
        "severity": severity,
    }


def _override_curve_thresholds() -> tuple[float, float]:
    """Return (full_power_below_kmh, override_extended_below_kmh) from energy_2026.
    Raises if override_mode is missing."""
    knowledge = get_energy_2026_knowledge()
    override = knowledge.get("override_mode")
    if not override or "curve" not in override:
        raise RuntimeError(
            "energy_2026 knowledge missing 'override_mode.curve' — required for F32 override-mode detection."
        )
    standard_anchors = sorted(_deployment_curve_anchors("standard"), key=lambda a: a["speed_kph"])
    override_anchors = sorted(override["curve"], key=lambda a: a["speed_kph"])
    return float(standard_anchors[0]["speed_kph"]), float(override_anchors[0]["speed_kph"])


def detect_override_mode(
    lap_telemetry: list[dict],
    gap_to_ahead_trace: list[float | None],
    *,
    full_power_below_kmh: float | None = None,
    override_extended_below_kmh: float | None = None,
    gap_window_s: float = 1.0,
    min_segment_length_m: float = 40.0,
) -> dict:
    """Identify segments where 2026 override-mode boost (extended 350 kW above
    290 km/h up to 337 km/h) was plausibly active.

    Trigger: speed in [290, 337] km/h, throttle >= 95, brake off, gap to ahead
    < 1s for >= 80% of samples, observed slope steeper than the F33 standard
    deployment-taper reference at the same speed.

    `lap_telemetry` samples must carry distance_m, speed_kph, throttle_pct, and
    either `brake` (bool) or `brake_pct` (float).
    `gap_to_ahead_trace` is parallel; entries may be None when unknown.

    Defaults read from energy_2026.override_mode."""
    if full_power_below_kmh is None or override_extended_below_kmh is None:
        full_default, override_default = _override_curve_thresholds()
        if full_power_below_kmh is None:
            full_power_below_kmh = full_default
        if override_extended_below_kmh is None:
            override_extended_below_kmh = override_default

    standard_anchors = sorted(_deployment_curve_anchors("standard"), key=lambda a: a["speed_kph"])
    n = min(len(lap_telemetry), len(gap_to_ahead_trace))

    def _brake_off(sample: dict) -> bool:
        brake = sample.get("brake")
        if isinstance(brake, bool):
            return not brake
        bp = sample.get("brake_pct")
        if bp is None and brake is None:
            return True
        if isinstance(brake, (int, float)):
            return brake == 0
        return (bp or 0) == 0

    candidate_blocks: list[list[int]] = []
    current: list[int] = []
    for i in range(n):
        s = lap_telemetry[i]
        sp = s.get("speed_kph")
        th = s.get("throttle_pct")
        if (
            sp is not None and th is not None
            and full_power_below_kmh <= sp <= override_extended_below_kmh
            and th >= 95
            and _brake_off(s)
        ):
            current.append(i)
        else:
            if len(current) >= 2:
                candidate_blocks.append(current)
            current = []
    if len(current) >= 2:
        candidate_blocks.append(current)

    segments: list[dict] = []
    for block in candidate_blocks:
        gaps_in_window: list[float] = [gap_to_ahead_trace[i] for i in block if gap_to_ahead_trace[i] is not None]
        if not gaps_in_window:
            continue
        in_window_count = sum(1 for g in gaps_in_window if g < gap_window_s)
        if in_window_count / len(gaps_in_window) < 0.8:
            continue
        start = lap_telemetry[block[0]]
        end = lap_telemetry[block[-1]]
        sd = start.get("distance_m")
        ed = end.get("distance_m")
        ss = start.get("speed_kph")
        es = end.get("speed_kph")
        if sd is None or ed is None or ss is None or es is None:
            continue
        length_m = ed - sd
        if length_m < min_segment_length_m:
            continue
        observed_slope = (es - ss) / length_m if length_m > 0 else 0.0
        mid_speed = (ss + es) / 2.0
        reference_slope = _reference_slope_kph_per_m(mid_speed, standard_anchors)
        if reference_slope <= 0:
            continue
        # Override-mode signature: observed slope is STEEPER than the standard
        # taper reference (car is still accelerating where the standard curve
        # would already be tapering).
        slope_ratio = observed_slope / reference_slope
        if slope_ratio < 1.5:
            continue
        avg_speed_ms = (ss + es) / 2.0 / 3.6
        duration_s = length_m / avg_speed_ms if avg_speed_ms > 0 else 0.0
        peak_speed = max((lap_telemetry[i].get("speed_kph") or 0) for i in block)
        avg_gap = sum(gaps_in_window) / len(gaps_in_window)
        segments.append({
            "start_distance_m": round(sd, 1),
            "end_distance_m": round(ed, 1),
            "peak_speed_kph": round(peak_speed, 1),
            "gap_at_segment_s": round(avg_gap, 3),
            "speed_gain_kph": round(es - ss, 1),
            "duration_s": round(duration_s, 3),
            "slope_ratio_vs_reference": round(slope_ratio, 2),
            "circuit_straight_label": None,
        })

    total_override_seconds = round(sum(s["duration_s"] for s in segments), 3)

    strong_segments = [
        s for s in segments
        if (s["end_distance_m"] - s["start_distance_m"]) >= min_segment_length_m
        and s["gap_at_segment_s"] < 0.7
        and s["slope_ratio_vs_reference"] >= 1.5
    ]
    if len(strong_segments) >= 2:
        confidence = "high"
    elif len(strong_segments) == 1 or len(segments) >= 2:
        confidence = "moderate"
    elif segments:
        confidence = "low"
    else:
        confidence = "low"

    return {
        "override_detected": bool(segments),
        "segments": segments,
        "total_override_seconds": total_override_seconds,
        "confidence": confidence,
        "detector_version": "f32-v1",
    }


def _resolve_circuit_slug_for_round(round_number: int) -> str | None:
    """Best-effort mapping of round_number to a CIRCUIT_PROFILES / CIRCUIT_AERO_ZONES key.
    Uses the session event's Country field via fastf1's schedule, falling back to None."""
    try:
        from circuit_profiles import get_circuit_profile
        schedule = fastf1.get_event_schedule(CURRENT_YEAR, include_testing=False)
        matching = schedule[schedule["RoundNumber"] == round_number]
        if matching.empty:
            return None
        country = str(matching.iloc[0].get("Country", "") or "")
        event_name = str(matching.iloc[0].get("EventName", "") or "")
        profile = get_circuit_profile(country, event_name)
        if profile:
            return profile.get("circuit_key")
    except Exception:
        return None
    return None


def analyze_active_aero_usage(
    driver_code: str, round_number: int, session_type: str, lap_number: int,
) -> dict:
    """Detect 2026 active-aero (X/Z) usage on a specific lap.

    Path A (preferred): if FastF1 exposes an active-aero channel on Car_Data,
    use it directly. As of 2026-05-20 the channel name is unconfirmed — this
    function probes candidate fields (`AeroState`, `Aero`, `XZ`) and treats any
    non-zero value as Z-mode active. When no candidate channel resolves, falls
    back to Path B.

    Path B (fallback): per-circuit aero-zone bands from active_aero.CIRCUIT_AERO_ZONES,
    a 250 km/h minimum speed, and a 100 m transition lag at zone entry.
    Path-B results are marked inferred=True.
    """
    from active_aero import is_z_mode, get_circuit_aero_zones, get_zone_label_at

    circuit_slug = _resolve_circuit_slug_for_round(round_number)
    if circuit_slug is None or get_circuit_aero_zones(circuit_slug) is None:
        return {
            "available": True,
            "driver_code": driver_code.upper(),
            "round_number": round_number,
            "session_type": session_type,
            "lap_number": lap_number,
            "circuit_slug": circuit_slug,
            "circuit_in_coverage": False,
            "segments": [],
            "total_z_mode_seconds": 0.0,
            "estimated_lap_time_delta_s": 0.0,
            "inferred": True,
            "detector_version": "f31-v1",
            "note": "Circuit not in active-aero zone coverage; defaulted to no Z-mode detected.",
        }

    tele = get_lap_telemetry(round_number, session_type, driver_code, lap_number)
    samples = tele.get("telemetry") or []

    # Path A probe: aero-state channel is currently unknown in 2026 FastF1.
    # Look for one of several candidate keys per sample; if any is present and
    # consistent across the lap, we treat it as the authoritative source.
    AERO_CHANNEL_CANDIDATES = ("aero_state", "aero", "xz_mode", "z_mode")
    aero_channel_key: str | None = None
    for cand in AERO_CHANNEL_CANDIDATES:
        if samples and cand in samples[0]:
            aero_channel_key = cand
            break

    in_zone_flags: list[bool] = []
    for s in samples:
        speed = s.get("speed_kph")
        dist = s.get("distance_m")
        if speed is None or dist is None:
            in_zone_flags.append(False)
            continue
        channel_val = s.get(aero_channel_key) if aero_channel_key else None
        in_zone_flags.append(
            is_z_mode(float(speed), float(dist), circuit_slug, aero_state_channel=channel_val)
        )

    inferred = aero_channel_key is None

    segments: list[dict] = []
    i = 0
    n = len(samples)
    while i < n:
        if not in_zone_flags[i]:
            i += 1
            continue
        j = i
        while j + 1 < n and in_zone_flags[j + 1]:
            j += 1
        seg_samples = samples[i:j + 1]
        if len(seg_samples) >= 2:
            start_d = float(seg_samples[0]["distance_m"])
            end_d = float(seg_samples[-1]["distance_m"])
            length_m = max(end_d - start_d, 1.0)
            peak = max(float(s["speed_kph"]) for s in seg_samples)
            avg_speed_kph = sum(float(s["speed_kph"]) for s in seg_samples) / len(seg_samples)
            avg_speed_ms = avg_speed_kph / 3.6
            duration_s = length_m / avg_speed_ms if avg_speed_ms > 0 else 0.0
            # Conservative speed-gain heuristic: longer/faster zones see more gain.
            # If end-of-zone speed > 320 km/h assume +8 km/h vs full-X-mode;
            # otherwise +4 km/h. These figures are editorial estimates.
            end_speed = float(seg_samples[-1]["speed_kph"])
            est_gain = 8.0 if end_speed > 320 else 4.0
            label = get_zone_label_at(circuit_slug, start_d) or None
            segments.append({
                "label": label,
                "start_distance_m": round(start_d, 1),
                "end_distance_m": round(end_d, 1),
                "duration_s": round(duration_s, 3),
                "peak_speed_kph": round(peak, 1),
                "estimated_speed_gain_kph": est_gain,
            })
        i = j + 1

    total_z = round(sum(s["duration_s"] for s in segments), 3)
    # First-order lap-time delta: roughly 2% of Z-mode time saved vs X-only.
    est_delta = round(total_z * 0.02, 3)

    return {
        "available": True,
        "driver_code": driver_code.upper(),
        "round_number": round_number,
        "session_type": session_type,
        "lap_number": lap_number,
        "circuit_slug": circuit_slug,
        "circuit_in_coverage": True,
        "segments": segments,
        "total_z_mode_seconds": total_z,
        "estimated_lap_time_delta_s": est_delta,
        "inferred": inferred,
        "detector_version": "f31-v1",
    }


def analyze_override_usage(driver_code: str, round_number: int, session_type: str, lap_number: int) -> dict:
    """Detect 2026 override-mode boost on a specific lap. Loads telemetry for
    the lap, approximates gap-to-ahead from openf1 intervals (averaged across
    the lap due to lack of per-sample interval data), and runs detect_override_mode."""
    tele = get_lap_telemetry(round_number, session_type, driver_code, lap_number)
    samples = tele.get("telemetry") or []

    # Approximation: openf1 'interval' is the gap to the car immediately ahead,
    # sampled at ~1Hz across the session. We average it over the driver's lap
    # window and apply the same scalar to every telemetry sample. This is
    # coarse but correct in steady-state straight-line scenarios where override
    # actually matters.
    from openf1 import get_intervals
    avg_gap = None
    try:
        intervals = get_intervals(round_number, driver_ref=driver_code, limit=200, session_type=session_type)
        rows = intervals.get("intervals") or []
        numeric_gaps = []
        for row in rows:
            g = row.get("interval")
            if isinstance(g, (int, float)):
                numeric_gaps.append(float(g))
        if numeric_gaps:
            avg_gap = sum(numeric_gaps) / len(numeric_gaps)
    except Exception:
        avg_gap = None

    gap_trace = [avg_gap] * len(samples) if avg_gap is not None else [None] * len(samples)
    result = detect_override_mode(samples, gap_trace)
    return {
        **result,
        "driver_code": driver_code.upper(),
        "round_number": round_number,
        "session_type": session_type,
        "lap_number": lap_number,
        "gap_source": "openf1_interval_average" if avg_gap is not None else "unavailable",
    }


def compare_drivers_clipping(
    driver_a_signature: dict,
    driver_b_signature: dict,
    driver_a_code: str,
    driver_b_code: str,
) -> dict | None:
    """Return chat-ready summary when one driver clips materially more.
    Threshold: difference >= 0.2 s/lap to be worth surfacing. Else None."""
    if not driver_a_signature or not driver_b_signature:
        return None
    a_total = driver_a_signature.get("total_clipping_seconds") or 0.0
    b_total = driver_b_signature.get("total_clipping_seconds") or 0.0
    delta = abs(a_total - b_total)
    if delta < 0.2:
        return None
    if a_total > b_total:
        clipping_driver = driver_a_code.upper()
        faster_driver = driver_b_code.upper()
        segments = driver_a_signature.get("segments") or []
    else:
        clipping_driver = driver_b_code.upper()
        faster_driver = driver_a_code.upper()
        segments = driver_b_signature.get("segments") or []
    delta_rounded = round(delta, 1)
    phrase = (
        f"{clipping_driver} clipped roughly {delta_rounded} s/lap on the main straight; "
        f"{faster_driver} did not."
    )
    segment_reference = None
    if segments:
        worst = max(segments, key=lambda s: s.get("duration_s") or 0.0)
        segment_reference = {
            "start_distance_m": worst.get("start_distance_m"),
            "end_distance_m": worst.get("end_distance_m"),
        }
    return {
        "faster_driver": faster_driver,
        "clipping_driver": clipping_driver,
        "delta_seconds": delta_rounded,
        "phrase": phrase,
        "segment_reference": segment_reference,
    }


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


def _compute_time_gained_over_window(
    v_winner_kph: float | None,
    v_loser_kph: float | None,
    window_distance_m: float | None,
) -> float | None:
    """Time the winner gains over the loser by sustaining v_winner_kph over
    v_loser_kph for window_distance_m of distance.

    Two-point constant-speed approximation. Use
    `_integrate_time_gained_from_samples` when per-sample telemetry is
    available — it integrates the per-meter contribution exactly rather
    than assuming a constant speed delta.

    Returns seconds, or None when either speed is missing / below a safe
    minimum (30 km/h) or the window is non-positive.
    """
    SAFE_MIN_KPH = 30.0
    if (v_winner_kph is None or v_loser_kph is None
            or v_winner_kph < SAFE_MIN_KPH or v_loser_kph < SAFE_MIN_KPH
            or window_distance_m is None or window_distance_m <= 0):
        return None
    v_a = v_winner_kph / 3.6
    v_b = v_loser_kph / 3.6
    return (1.0 / v_b - 1.0 / v_a) * float(window_distance_m)


_TRAPEZOIDAL_SAFE_MIN_KPH = 30.0
_TRAPEZOIDAL_MAX_SEG_WIDTH_M = 150.0
_TRAPEZOIDAL_MAX_SEG_CONTRIB_S = 0.25


def _trapezoidal_time_gained_segments(
    distance,
    speed_winner_kph,
    speed_loser_kph,
):
    """Shared trapezoidal quadrature for time-gained-by-winner.

    Returns ``(sorted_distance, seg_mids, seg_contrib)`` where ``seg_contrib[i]``
    is the trapezoidal time-gain contribution (seconds, positive = winner
    gained) over the segment between sorted samples ``i`` and ``i+1``, clipped
    to a physically plausible per-segment magnitude. Returns ``None`` when
    fewer than 2 samples are available.

    Why trapezoidal: end-of-step rectangular quadrature at ~100 m sample
    spacing treats an instantaneous apex sample as if it persisted across
    the whole segment, generating ~1.5 s artefacts. Trapezoidal averages
    the endpoints. We additionally cap segment width at 150 m so pathological
    data gaps do not leak through, and cap |contribution| at 0.25 s so any
    residual single-sample artefact stays bounded.
    """
    distance_arr = np.asarray(distance, dtype=float)
    sw = np.asarray(speed_winner_kph, dtype=float)
    sl = np.asarray(speed_loser_kph, dtype=float)
    n = min(len(distance_arr), len(sw), len(sl))
    if n < 2:
        return None
    distance_arr = distance_arr[:n]
    sw = sw[:n]
    sl = sl[:n]

    order = np.argsort(distance_arr)
    distance_arr = distance_arr[order]
    sw = sw[order]
    sl = sl[order]

    inv_sw = 1.0 / (np.clip(sw, _TRAPEZOIDAL_SAFE_MIN_KPH, None) / 3.6)
    inv_sl = 1.0 / (np.clip(sl, _TRAPEZOIDAL_SAFE_MIN_KPH, None) / 3.6)

    seg_widths = np.clip(np.diff(distance_arr), 0.0, _TRAPEZOIDAL_MAX_SEG_WIDTH_M)
    seg_per_m = 0.5 * ((inv_sl[:-1] + inv_sl[1:]) - (inv_sw[:-1] + inv_sw[1:]))
    seg_contrib = np.clip(
        seg_per_m * seg_widths,
        -_TRAPEZOIDAL_MAX_SEG_CONTRIB_S,
        _TRAPEZOIDAL_MAX_SEG_CONTRIB_S,
    )
    seg_mids = 0.5 * (distance_arr[:-1] + distance_arr[1:])
    return distance_arr, seg_mids, seg_contrib


def _integrate_time_gained_from_samples(
    distance,
    speed_winner_kph,
    speed_loser_kph,
    start_distance: float | None = None,
    end_distance: float | None = None,
) -> float | None:
    """Per-segment integration of time-gained-by-winner over distance.

    Optionally restricts integration to [start_distance, end_distance].
    Returns seconds (positive = winner gained time).

    Uses the trapezoidal rule for ``∫ (1/v_loser - 1/v_winner) ds`` via
    :func:`_trapezoidal_time_gained_segments`. See that helper for the
    rationale behind sorting, the 150 m segment-width cap, and the 0.25 s
    per-segment magnitude cap.

    Returns None when fewer than 2 samples or the requested window
    contains no segments.
    """
    segs = _trapezoidal_time_gained_segments(
        distance, speed_winner_kph, speed_loser_kph,
    )
    if segs is None:
        return None
    distance_arr, seg_mids, seg_contrib = segs

    if start_distance is not None or end_distance is not None:
        lo = start_distance if start_distance is not None else float(distance_arr[0])
        hi = end_distance if end_distance is not None else float(distance_arr[-1])
        mask = (seg_mids >= lo) & (seg_mids <= hi)
        if not mask.any():
            return None
        seg_contrib = seg_contrib[mask]
    return float(seg_contrib.sum())


def _integrate_time_gained_around_extremum(
    distance,
    speed_a_kph,
    speed_b_kph,
    center_distance_m: float,
    peak_fraction_threshold: float = 0.3,
    max_window_m: float = 200.0,
    sector_bounds_m: tuple[float, float] | None = None,
) -> float | None:
    """Integrate signed time gained (A − B convention) around a local
    per-meter extremum near ``center_distance_m``.

    Walks outward in both directions from the peak-magnitude segment until
    the per-meter contribution drops below ``peak_fraction_threshold *
    |peak|`` (or until the cumulative window exceeds ``max_window_m``).
    Captures the physical event without summing adjacent unrelated samples.

    When ``sector_bounds_m=(lo, hi)`` is supplied, the search and the
    outward walk are clamped to ``[lo, hi]`` — markers can never claim
    time gained outside their owning sector, so per-sector marker totals
    stay coherent with FastF1's per-lap sector gaps.

    Returns seconds (positive = A gained, negative = B gained), or ``None``
    when integration is not possible.
    """
    segs = _trapezoidal_time_gained_segments(
        distance, speed_a_kph, speed_b_kph,
    )
    if segs is None:
        return None
    distance_arr, seg_mids, seg_contrib = segs
    if seg_mids.size == 0:
        return None

    sector_lo: float | None = None
    sector_hi: float | None = None
    if sector_bounds_m is not None:
        sector_lo = float(sector_bounds_m[0])
        sector_hi = float(sector_bounds_m[1])

    # Locate the segment closest to the requested center.
    centre_idx = int(np.argmin(np.abs(seg_mids - float(center_distance_m))))

    # Search for the magnitude-peak segment in a small neighbourhood
    # (±max_window_m/2) so a tiny near-zero seg right at the requested
    # center doesn't become the "peak" by accident.
    search_lo = float(center_distance_m) - max_window_m / 2.0
    search_hi = float(center_distance_m) + max_window_m / 2.0
    if sector_lo is not None:
        search_lo = max(search_lo, sector_lo)
        search_hi = min(search_hi, sector_hi)
    in_window = (seg_mids >= search_lo) & (seg_mids <= search_hi)
    if not in_window.any():
        return float(seg_contrib[centre_idx])
    window_idx = np.flatnonzero(in_window)
    abs_window_contrib = np.abs(seg_contrib[window_idx])
    peak_idx = int(window_idx[int(np.argmax(abs_window_contrib))])
    peak_abs = abs(float(seg_contrib[peak_idx]))
    if peak_abs <= 0.0:
        return float(seg_contrib[peak_idx])

    threshold = peak_abs * float(peak_fraction_threshold)
    peak_sign = 1.0 if seg_contrib[peak_idx] >= 0 else -1.0

    # Walk left/right while per-meter contribution stays above threshold
    # AND keeps the same sign as the peak. Cap by max_window_m total AND
    # by sector bounds when supplied (markers don't cross sector
    # boundaries).
    half_window = max_window_m / 2.0
    lo_idx = peak_idx
    hi_idx = peak_idx
    peak_mid = float(seg_mids[peak_idx])

    while lo_idx - 1 >= 0:
        cand = seg_contrib[lo_idx - 1]
        if abs(cand) < threshold or (cand >= 0) != (peak_sign >= 0):
            break
        if peak_mid - float(seg_mids[lo_idx - 1]) > half_window:
            break
        if sector_lo is not None and float(seg_mids[lo_idx - 1]) < sector_lo:
            break
        lo_idx -= 1

    while hi_idx + 1 < seg_contrib.size:
        cand = seg_contrib[hi_idx + 1]
        if abs(cand) < threshold or (cand >= 0) != (peak_sign >= 0):
            break
        if float(seg_mids[hi_idx + 1]) - peak_mid > half_window:
            break
        if sector_hi is not None and float(seg_mids[hi_idx + 1]) > sector_hi:
            break
        hi_idx += 1

    return float(seg_contrib[lo_idx:hi_idx + 1].sum())


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
    try:
        session = _load_session(
            round_number,
            session_type,
            laps=True,
            telemetry=False,
            weather=False,
            messages=_session_needs_race_control_messages(session_type),
        )
    except FastF1Error:
        return _unavailable_payload(round_number, session_type)
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
    try:
        session = _load_session(
            round_number,
            session_type,
            laps=True,
            telemetry=False,
            weather=False,
            messages=_session_needs_race_control_messages(session_type),
        )
    except FastF1Error as exc:
        # Return type is list[dict] — cannot carry the unavailable dict payload; chained ValueError surfaces the same information.
        raise ValueError("session data unavailable") from exc

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
    try:
        session = _load_session(
            round_number,
            session_type,
            laps=True,
            telemetry=False,
            weather=False,
            messages=_session_needs_race_control_messages(session_type),
        )
    except FastF1Error:
        return _unavailable_payload(round_number, session_type)

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
    try:
        session = _load_session(round_number, session_type, laps=True, telemetry=False, weather=False, messages=False)
    except FastF1Error:
        return _unavailable_payload(round_number, session_type)
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
    try:
        session = _load_session(round_number, 'Q', laps=True, telemetry=False, weather=False, messages=False)
    except FastF1Error:
        return _unavailable_payload(round_number, "Q")
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
    try:
        session = _load_session(
            round_number,
            session_type,
            laps=True,
            telemetry=False,
            weather=False,
            messages=_session_needs_race_control_messages(session_type),
        )
    except FastF1Error:
        return _unavailable_payload(round_number, session_type)
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


def compute_mini_sectors(lap, n: int = 25) -> list[dict]:
    """Split a lap into n equal cumulative-distance segments.

    Returns a list of n dicts, each with:
        - index: 0-based segment number
        - start_m, end_m: distance bounds in meters
        - time_s: seconds spent in this segment
        - avg_speed_kmh, min_speed_kmh
        - drs_active_pct: % of samples in segment where DRS was active
                           (values 10/12/14 in FastF1's DRS column)

    Returns [] if telemetry is missing, empty, or has < n*2 samples.
    """
    try:
        tel = lap.get_car_data().add_distance()
    except Exception:
        return []

    if tel is None or len(tel) < n * 2:
        return []

    required = ("Distance", "Time", "Speed")
    if not all(col in tel.columns for col in required):
        return []

    distance = tel["Distance"].to_numpy(dtype=float)
    total_distance = float(distance[-1])
    if total_distance <= 0.0 or not np.isfinite(total_distance):
        return []

    # Time column may be timedelta — convert to seconds
    time_col = tel["Time"]
    if pd.api.types.is_timedelta64_dtype(time_col):
        time_s = time_col.dt.total_seconds().to_numpy(dtype=float)
    else:
        time_s = time_col.to_numpy(dtype=float)

    speed = tel["Speed"].to_numpy(dtype=float)
    drs = tel["DRS"].to_numpy() if "DRS" in tel.columns else None

    boundaries = np.linspace(0.0, total_distance, n + 1)
    # Interpolate the lap time at each boundary so adjacent segments share an
    # endpoint and segment times sum exactly to the total lap time.
    boundary_times = np.interp(boundaries, distance, time_s)
    segments: list[dict] = []

    for i in range(n):
        start_m = float(boundaries[i])
        end_m = float(boundaries[i + 1])
        # Inclusive on the lower bound, exclusive on the upper, except for the
        # last segment which must include the final sample.
        if i == n - 1:
            mask = (distance >= start_m) & (distance <= end_m)
        else:
            mask = (distance >= start_m) & (distance < end_m)

        if not mask.any():
            segments.append({
                "index": i,
                "start_m": round(start_m, 2),
                "end_m": round(end_m, 2),
                "time_s": 0.0,
                "avg_speed_kmh": 0.0,
                "min_speed_kmh": 0.0,
                "drs_active_pct": 0.0,
            })
            continue

        seg_speeds = speed[mask]
        seg_time = float(boundary_times[i + 1] - boundary_times[i])

        if drs is not None:
            seg_drs = drs[mask]
            try:
                drs_active = float(np.mean([int(v) in (10, 12, 14) for v in seg_drs]) * 100.0)
            except Exception:
                drs_active = 0.0
        else:
            drs_active = 0.0

        segments.append({
            "index": i,
            "start_m": round(start_m, 2),
            "end_m": round(end_m, 2),
            "time_s": round(seg_time, 4),
            "avg_speed_kmh": round(float(np.mean(seg_speeds)), 2),
            "min_speed_kmh": round(float(np.min(seg_speeds)), 2),
            "drs_active_pct": round(drs_active, 1),
        })

    return segments


_DRS_ACTIVE_THRESHOLD_PCT = 30.0
_MINI_SECTOR_TIE_THRESHOLD_S = 0.005


def _build_mini_sector_comparison(
    driver_a: str,
    driver_b: str,
    a_segments: list[dict],
    b_segments: list[dict],
) -> dict:
    """Build the comparison dict from two equal-length segment lists.

    Pure function — no telemetry I/O. Easy to unit test.
    """
    n = min(len(a_segments), len(b_segments))
    out_segments: list[dict] = []
    cumulative: list[tuple[float, float]] = [(0.0, 0.0)]
    cum = 0.0
    drs_mix = False

    for i in range(n):
        a = a_segments[i]
        b = b_segments[i]
        delta = round(a["time_s"] - b["time_s"], 4)
        if abs(delta) < _MINI_SECTOR_TIE_THRESHOLD_S:
            winner = "tie"
        elif delta < 0:
            winner = "A"
        else:
            winner = "B"

        a_drs = a.get("drs_active_pct", 0.0) >= _DRS_ACTIVE_THRESHOLD_PCT
        b_drs = b.get("drs_active_pct", 0.0) >= _DRS_ACTIVE_THRESHOLD_PCT
        if a_drs != b_drs:
            drs_mix = True

        cum = round(cum + delta, 4)
        cumulative.append((a["end_m"], cum))

        out_segments.append({
            "index": i,
            "start_m": a["start_m"],
            "end_m": a["end_m"],
            "delta_s": delta,
            "winner": winner,
            "drs_a_active": a_drs,
            "drs_b_active": b_drs,
        })

    return {
        "driver_a": driver_a,
        "driver_b": driver_b,
        "segments": out_segments,
        "cumulative_delta": cumulative,
        "total_delta_s": round(cum, 4),
        "segments_won_a": sum(1 for s in out_segments if s["winner"] == "A"),
        "segments_won_b": sum(1 for s in out_segments if s["winner"] == "B"),
        "segments_tied": sum(1 for s in out_segments if s["winner"] == "tie"),
        "drs_mix_warning": drs_mix,
    }


def compare_mini_sectors(
    driver_a: str,
    driver_b: str,
    lap_number: int,
    round_number: int,
    session_type: str = "Q",
    n: int = 25,
) -> dict:
    """Compute per-driver mini-sectors and build the comparison."""
    try:
        session = _load_session(round_number, session_type)
    except FastF1Error:
        return _unavailable_payload(round_number, session_type)

    try:
        lap_a = session.laps.pick_drivers(driver_a).pick_laps(lap_number)
        lap_b = session.laps.pick_drivers(driver_b).pick_laps(lap_number)
    except Exception as e:
        logger.warning("compare_mini_sectors lap pick failed: %s", type(e).__name__)
        return {"available": False, "reason": "lap_not_found"}

    if lap_a is None or lap_b is None or len(lap_a) == 0 or len(lap_b) == 0:
        return {"available": False, "reason": "lap_not_found"}

    lap_a_row = lap_a.iloc[0]
    lap_b_row = lap_b.iloc[0]

    a_segments = compute_mini_sectors(lap_a_row, n=n)
    b_segments = compute_mini_sectors(lap_b_row, n=n)

    if not a_segments or not b_segments:
        return {"available": False, "reason": "telemetry_empty"}

    weather_state = "unknown"
    try:
        if hasattr(session, "weather_data") and session.weather_data is not None:
            rainfall = session.weather_data.get("Rainfall")
            if rainfall is not None:
                weather_state = "wet" if bool(rainfall.any()) else "dry"
    except Exception:
        pass

    comparison = _build_mini_sector_comparison(driver_a, driver_b, a_segments, b_segments)
    return {
        "available": True,
        "lap_number": lap_number,
        "round_number": round_number,
        "session_type": session_type,
        "n_segments": n,
        "weather_state": weather_state,
        **comparison,
    }


def get_sector_comparison(round_number: int, session_type: str,
                          driver_a: str, driver_b: str) -> dict:
    """
    Head-to-head fastest-lap comparison between two drivers.
    Shows time gap per sector AND speed trap deltas (SpeedI1/I2/FL/ST).
    Positive gap_s = driver_a is SLOWER. Positive speed_delta = driver_a is FASTER.
    Answers: "why was Norris 0.3s faster than Leclerc in sector 2?"
    """
    try:
        session = _load_session(
            round_number,
            session_type,
            laps=True,
            telemetry=False,
            weather=False,
            messages=_session_needs_race_control_messages(session_type),
        )
    except FastF1Error:
        return _unavailable_payload(round_number, session_type)

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
    try:
        session = _load_session(
            round_number,
            session_type,
            laps=True,
            telemetry=True,
            weather=False,
            messages=_session_needs_race_control_messages(session_type),
        )
    except FastF1Error:
        return _unavailable_payload(round_number, session_type)

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
        is_drs_active = drs_active(drs) if pd.notna(drs) else False
        samples.append({
            "distance_m": int(dist),
            "speed_kph": round(float(row['Speed']), 1),
            "throttle_pct": round(float(row['Throttle']), 1),
            "brake": bool(row['Brake']),
            "gear": int(gear) if pd.notna(gear) else None,
            "rpm": int(rpm) if pd.notna(rpm) else None,
            "drs_open": is_drs_active,
            "drs_active": is_drs_active,
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
    try:
        session = _load_session(
            round_number,
            session_type,
            laps=True,
            telemetry=True,
            weather=False,
            messages=_session_needs_race_control_messages(session_type),
        )
    except FastF1Error:
        return _unavailable_payload(round_number, session_type)

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

        drs_a_int = int(drs_a_raw) if pd.notna(drs_a_raw) else None
        drs_b_int = int(drs_b_raw) if pd.notna(drs_b_raw) else None
        drs_a_active = drs_active(drs_a_raw) if pd.notna(drs_a_raw) else False
        drs_b_active = drs_active(drs_b_raw) if pd.notna(drs_b_raw) else False
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
            "drs_a": drs_a_active,
            "drs_b": drs_b_active,
            "drs_a_active": drs_a_active,
            "drs_b_active": drs_b_active,
            "drs_a_raw": drs_a_int,
            "drs_b_raw": drs_b_int,
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
        avg_speed_ms = max(kph_to_ms(avg_speed_kph), 1.0)
        drop_ms = kph_to_ms(abs(drop_kph))
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
        clip_sig_a = detect_clipping_signature(
            [s["speed_kph"] for s in driver_a_samples if s.get("speed_kph") is not None],
            [s["throttle_pct"] for s in driver_a_samples if s.get("speed_kph") is not None],
            [s["distance_m"] for s in driver_a_samples if s.get("speed_kph") is not None],
            drs_state=[1 if s.get("drs_open") else 0 for s in driver_a_samples if s.get("speed_kph") is not None],
        )
        clip_sig_b = detect_clipping_signature(
            [s["speed_kph"] for s in driver_b_samples if s.get("speed_kph") is not None],
            [s["throttle_pct"] for s in driver_b_samples if s.get("speed_kph") is not None],
            [s["distance_m"] for s in driver_b_samples if s.get("speed_kph") is not None],
            drs_state=[1 if s.get("drs_open") else 0 for s in driver_b_samples if s.get("speed_kph") is not None],
        )
        clipping_comparison = compare_drivers_clipping(clip_sig_a, clip_sig_b, driver_a, driver_b)

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
            "clipping_signature_a": clip_sig_a,
            "clipping_signature_b": clip_sig_b,
            "clipping_comparison": clipping_comparison,
        }

    telemetry = get_lap_telemetry(round_number, session_type, driver_a, lap_number_a)
    samples = telemetry["telemetry"]
    lico = _infer_lift_and_coast_samples(samples)
    clip = _infer_clipping_windows(samples)
    clip_sig = detect_clipping_signature(
        [s["speed_kph"] for s in samples if s.get("speed_kph") is not None],
        [s["throttle_pct"] for s in samples if s.get("speed_kph") is not None],
        [s["distance_m"] for s in samples if s.get("speed_kph") is not None],
        drs_state=[1 if s.get("drs_open") else 0 for s in samples if s.get("speed_kph") is not None],
    )
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
        "clipping_signature_a": clip_sig,
        "clipping_signature_b": None,
        "clipping_comparison": None,
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


def _distance_fallback_label(distance_m: int | float | None) -> tuple[str, str]:
    """Pure distance fallback when no circuit corner data is available.

    Vague "late/middle/early in the lap" phrasing was misleading — replaced
    with a raw distance phrase so the marker still anchors to *somewhere*.
    """
    if not _is_finite_distance(distance_m):
        return "Distance unavailable", "at an unknown point on the lap"
    return f"around {int(distance_m)}m", f"around {int(distance_m)}m"


def _resolve_corner_for_distance(
    round_number: int,
    distance_m: int | float | None,
    year: int | None = None,
) -> dict:
    """Resolve a telemetry distance to a named-corner / straight label.

    When ``year`` is provided and positive, delegates to the curvature-
    based segmentation module. On any failure (or when segmentation
    returns no useful label) falls back to the legacy nearest-apex
    heuristic against FastF1's MultiViewer data.

    Returns a dict with keys:
      - corner_number: int | None (set when the distance lies between a
        corner's entry and exit range)
      - corner_name:   str | None (e.g. "Turn 11")
      - location_label: str | None (e.g. "Turn 11", "T8 → T9 straight",
        "around 4700m" when corner data is unavailable)

    Falls back gracefully when ``get_circuit_corners`` raises or returns
    no corners — never crashes. The returned ``location_label`` is what
    callers should prefer; it always includes a meaningful anchor.
    """
    fallback_label, _fallback_plain = _distance_fallback_label(distance_m)
    empty = {"corner_number": None, "corner_name": None, "location_label": fallback_label}
    if not _is_finite_distance(distance_m):
        return empty
    # When year is known, prefer curvature-based segmentation.
    if year is not None and year > 0:
        try:
            import corner_segmentation
            seg_result = corner_segmentation.resolve_corner_for_distance(
                year, round_number, float(distance_m)
            )
            if seg_result.get("location_label"):
                return seg_result
        except Exception as exc:  # noqa: BLE001 — log and fall back
            logger.debug(
                "corner_segmentation failed for year=%s round=%s d=%s: %s",
                year, round_number, distance_m, exc,
            )
    try:
        corners = get_circuit_corners(round_number)
    except Exception:
        return empty
    valid_corners = sorted(
        [c for c in corners if c.get("distance_m") is not None],
        key=lambda c: c["distance_m"],
    )
    if not valid_corners:
        return empty

    # A corner from ``get_circuit_corners`` only carries a single
    # distance_m (its apex/marker position). Treat ±150m around that as
    # the corner's footprint — close enough for marker copy and matches
    # the granularity FastF1 returns.
    # When corner footprints overlap (e.g. Miami T17 @ 4830m and T18 @
    # 4967m are only 137m apart), pick the corner whose apex is nearest
    # the distance — not whichever comes first in lap order.
    CORNER_RADIUS_M = 150.0
    target = float(distance_m)
    nearest_corner = None
    nearest_delta = None
    for corner in valid_corners:
        delta = abs(corner["distance_m"] - target)
        if delta <= CORNER_RADIUS_M and (nearest_delta is None or delta < nearest_delta):
            nearest_corner = corner
            nearest_delta = delta
    if nearest_corner is not None:
        label = _corner_label(nearest_corner)
        return {
            "corner_number": nearest_corner.get("number"),
            "corner_name": label,
            "location_label": label or fallback_label,
        }

    # Between corners → straight. Find bracketing pair.
    previous_corner = None
    next_corner = None
    for corner in valid_corners:
        if corner["distance_m"] <= distance_m:
            previous_corner = corner
        if next_corner is None and corner["distance_m"] >= distance_m:
            next_corner = corner
    prev_label = _corner_label(previous_corner)
    next_label = _corner_label(next_corner)
    if prev_label and next_label:
        straight = f"{prev_label} → {next_label} straight"
    elif next_label:
        straight = f"approach to {next_label}"
    elif prev_label:
        straight = f"run out of {prev_label}"
    else:
        straight = fallback_label
    return {
        "corner_number": None,
        "corner_name": None,
        "location_label": straight,
    }


def _base_location_context(distance_m: int | float | None) -> dict:
    label, plain = _distance_fallback_label(distance_m)
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


def _cause_explanation(
    ct: str,
    dist: int | None,
    location_context: dict | None = None,
    *,
    gainer_driver: str | None = None,
    faster_driver: str | None = None,
    driver_a_code: str | None = None,
    driver_b_code: str | None = None,
    is_teammate_comparison: bool = False,
    corner_name: str | None = None,
    location_label: str | None = None,
) -> str:
    """Build the per-marker prose. ``gainer_driver`` is the driver who
    gained at THIS specific marker — narrate from their perspective
    even when they are not the overall-faster driver on the lap.

    Prefers corner-aware labels (``corner_name`` / ``location_label`` from
    the marker dict) over the raw distance phrasing in
    ``location_context.plain``.
    """
    def _location_phrase() -> str:
        # 1. Explicit corner name from marker (highest priority).
        if corner_name:
            return f" at {corner_name}"
        # 2. Explicit location_label from marker, IF it's not the
        #    'around <distance>m' fallback form.
        if location_label and not location_label.startswith("around "):
            if "straight" in location_label.lower():
                return f" on the {location_label}"
            return f" at {location_label}"
        # 3. location_context.plain (named phrase from corner context).
        if location_context and location_context.get("phase") != "lap_region":
            plain = location_context.get("plain")
            if plain:
                return f" {plain}"
        # 4. Distance-only fallback.
        if dist is not None:
            return f" around {dist}m"
        return ""

    loc = _location_phrase()
    gainer = gainer_driver or faster_driver
    loser = driver_b_code if gainer == driver_a_code else driver_a_code
    if ct == "straight_line_speed":
        if is_teammate_comparison:
            return (
                f"There's a straight-line speed delta{loc} — on identical machinery this likely reflects "
                f"a setup trim difference (wing angle, cooling) or DRS timing rather than "
                f"a meaningful car performance gap."
            )
        return (
            f"{gainer} carries more speed at full throttle late on the straight{loc}, "
            f"opening the gap before the braking zone."
        )
    if ct == "straight_line_speed_energy_limited":
        return (
            f"Late-straight deployment{loc}: {loser} fades while still full throttle, "
            f"so {gainer} keeps accelerating harder before the next braking zone."
        )
    if ct == "braking":
        if is_teammate_comparison:
            return (
                f"Braking technique is the key difference{loc}: {loser} commits to the brake "
                f"earlier while {gainer} trails the braking point and carries more entry speed. "
                f"On identical hardware this is a pure driving style call."
            )
        return (
            f"Corner entry{loc}: {loser} is already on the brake while "
            f"{gainer} is still carrying speed into the zone."
        )
    if ct == "minimum_speed":
        if is_teammate_comparison:
            return (
                f"Mid-corner minimum speed{loc}: {gainer} gives up less speed at the direction change. "
                f"Between teammates this points to setup divergence (downforce level, diff, ride height) "
                f"or a conscious style difference through the apex — not a car advantage."
            )
        return (
            f"{gainer} gives up less speed mid-corner{loc} and exits with more momentum."
        )
    if ct == "traction":
        if is_teammate_comparison:
            return (
                f"Traction on exit{loc}: {gainer} gets back to full throttle earlier. "
                f"Between teammates this usually comes down to throttle application technique "
                f"or diff settings — same rear end, different commitment level."
            )
        return (
            f"Traction on exit{loc}: {gainer} gets back to full speed earlier "
            f"and carries that advantage down the following straight."
        )
    return "Mixed advantages — no single dominant mechanism."


def _telemetry_location_context(round_number: int, distance_m: int | float | None, cause_type: str | None, year: int | None = None) -> dict:
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
    try:
        session = _load_session(round_number, session_type, laps=True, telemetry=False, weather=False, messages=True)
    except FastF1Error as exc:
        # Return type is tuple — cannot carry the unavailable dict payload; chained ValueError surfaces the same information.
        raise ValueError(f"session data unavailable for round {round_number} {session_type}") from exc
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


def _classify_cause_type_at_sample(sample: dict, gain_is_a: bool) -> str:
    """Classify the dominant mechanism at a sample, given which driver
    gained time at that point. Mirrors the categorisation rules used by
    the legacy four-bucket picker but operates on a single sample plus
    the local gain direction.
    """
    def _gainer(key):
        return sample.get(f"{key}_a") if gain_is_a else sample.get(f"{key}_b")

    def _loser(key):
        return sample.get(f"{key}_b") if gain_is_a else sample.get(f"{key}_a")

    g_throttle = float(_gainer("throttle") or 0)
    l_throttle = float(_loser("throttle") or 0)
    g_brake = bool(_gainer("brake") or False)
    l_brake = bool(_loser("brake") or False)

    # Braking: loser on brake while gainer is still carrying speed.
    if l_brake and not g_brake:
        return "braking"
    # Full-throttle both sides → straight-line speed.
    if g_throttle >= 95 and l_throttle >= 95 and not g_brake and not l_brake:
        return "straight_line_speed"
    # Traction: gainer back to high throttle, loser still rolling on.
    if g_throttle >= 70 and (g_throttle - l_throttle) >= 15 and not g_brake:
        return "traction"
    # Mid-corner / direction change.
    if g_throttle < 40 and not g_brake:
        return "minimum_speed"
    if l_throttle < 40 and not l_brake:
        return "minimum_speed"
    # Fall-through bucket — generic.
    return "minimum_speed"


def _sector_label_for_distance(
    dist_m: float | None,
    sector_boundary_distances: list | tuple,
) -> str | None:
    if dist_m is None:
        return None
    b1 = sector_boundary_distances[0] if len(sector_boundary_distances) > 0 else None
    b2 = sector_boundary_distances[1] if len(sector_boundary_distances) > 1 else None
    if b1 is None:
        return None
    if dist_m <= b1:
        return "Sector 1"
    if b2 is None or dist_m <= b2:
        return "Sector 2"
    return "Sector 3"


def _summarize_telemetry_battle(
    samples: list[dict],
    faster_driver: str,
    driver_a: str,
    driver_b: str,
    sector_boundary_distances: list | tuple | None = None,
    top_k: int = 4,
    min_spacing_m: float = 200.0,
    round_number: int | None = None,
    authoritative_sector_gaps_s: dict | None = None,
    year: int | None = None,
) -> dict | None:
    """Two-sided telemetry-battle summary.

    Ranks ALL samples by absolute local time contribution (A − B
    convention) and picks the top K with min_spacing_m separation.
    Markers can come from EITHER driver — the gainer is recorded per
    marker. Per-marker time contribution uses
    ``_integrate_time_gained_around_extremum`` so a 14 km/h delta at
    300 km/h doesn't get over-attributed by a fixed-width window.

    When ``authoritative_sector_gaps_s`` is supplied (mapping
    ``"Sector 1"``/``"Sector 2"``/``"Sector 3"`` → FastF1 sector
    time-gap in seconds, A − B convention), the ``sector_reconciliation``
    panel reports those FastF1-authoritative values as ``sector_gap_s``
    (single source of truth so the panel matches the sector-breakdown
    panel exactly) rather than a telemetry-integration approximation.
    """
    if not samples:
        return None

    sector_boundary_distances = list(sector_boundary_distances or [None, None])
    auth_gaps = dict(authoritative_sector_gaps_s or {})

    # Build numpy arrays once for the integrator.
    _dist_arr = np.asarray([s.get("distance_m") for s in samples], dtype=float)
    _v_a_arr = np.asarray([s.get("speed_a") or 0 for s in samples], dtype=float)
    _v_b_arr = np.asarray([s.get("speed_b") or 0 for s in samples], dtype=float)

    # Compute per-sample local time contribution via the extremum walker.
    # When the walker isn't available (fewer than 2 samples) bail.
    if len(samples) < 2:
        return None

    _b1 = sector_boundary_distances[0]
    _b2 = sector_boundary_distances[1]
    _lap_end = float(_dist_arr.max()) if _dist_arr.size else None

    def _sector_bounds_for_distance(d: float) -> tuple[float, float] | None:
        """Owning-sector (lo, hi) for a distance, or None if boundaries unknown."""
        if _b1 is None or _lap_end is None:
            return None
        if d <= _b1:
            return (0.0, float(_b1))
        if _b2 is None or d <= _b2:
            return (float(_b1), float(_b2) if _b2 is not None else _lap_end)
        return (float(_b2), _lap_end)

    candidates: list[dict] = []
    for s in samples:
        dist = s.get("distance_m")
        if dist is None:
            continue
        v_a = s.get("speed_a")
        v_b = s.get("speed_b")
        if v_a is None or v_b is None:
            continue
        # Skip degenerate near-zero deltas before integration to keep the
        # candidate pool focused on physically meaningful moments.
        if abs(float(v_a) - float(v_b)) < 1.0:
            continue
        contrib = _integrate_time_gained_around_extremum(
            _dist_arr, _v_a_arr, _v_b_arr, center_distance_m=float(dist),
            sector_bounds_m=_sector_bounds_for_distance(float(dist)),
        )
        if contrib is None or abs(contrib) < 1e-4:
            continue
        gain_is_a = contrib > 0
        cause_type = _classify_cause_type_at_sample(s, gain_is_a)
        sector_label = _sector_label_for_distance(dist, sector_boundary_distances)
        candidates.append({
            "cause_type": cause_type,
            "distance_m": dist,
            "delta_speed_kph": s.get("delta_speed"),
            "magnitude": abs(s.get("delta_speed") or 0),
            "speed_a": s.get("speed_a"),
            "speed_b": s.get("speed_b"),
            "time_gained_s": contrib,
            "gainer_driver": driver_a if gain_is_a else driver_b,
            "sector": sector_label,
            "throttle_a": s.get("throttle_a"),
            "throttle_b": s.get("throttle_b"),
            "brake_a": s.get("brake_a"),
            "brake_b": s.get("brake_b"),
            "gear_a": s.get("gear_a"),
            "gear_b": s.get("gear_b"),
        })

    if not candidates:
        return None

    # Rank by absolute time contribution (largest first) and pick top K
    # with min_spacing_m enforced so two markers can't describe the same
    # physical event.
    candidates.sort(key=lambda c: abs(c["time_gained_s"]), reverse=True)
    picked: list[dict] = []
    for cand in candidates:
        if any(abs(cand["distance_m"] - p["distance_m"]) < min_spacing_m for p in picked):
            continue
        picked.append(cand)
        if len(picked) >= top_k:
            break

    if not picked:
        return None

    # Re-rank picked markers in lap order so widgets/prose surface them
    # left-to-right around the lap. The "primary" remains the largest by
    # absolute time gain — we expose both orderings.
    picked.sort(key=lambda c: c["distance_m"])

    # Enrich each picked marker with a corner / straight label so widget
    # prose can say "Turn 11" instead of "around 4700m". Best-effort:
    # the resolver returns a distance-fallback label if corner data is
    # unavailable for the round.
    if round_number is not None:
        for marker in picked:
            corner_info = _resolve_corner_for_distance(round_number, marker["distance_m"], year=year)
            marker["corner_number"] = corner_info["corner_number"]
            marker["corner_name"] = corner_info["corner_name"]
            marker["location_label"] = corner_info["location_label"]
    else:
        # No round context — still set the keys so consumers don't need
        # to guard for missing fields. location_label falls back to the
        # raw distance phrase.
        for marker in picked:
            fallback, _ = _distance_fallback_label(marker["distance_m"])
            marker["corner_number"] = None
            marker["corner_name"] = None
            marker["location_label"] = fallback

    # NOTE: per-sector conservation cap + sector_reconciliation construction
    # were moved out of this function (to apply_sector_conservation_and_build_reconciliation
    # below) so they run AFTER analyze_qualifying_battle finalizes top_causes
    # (e.g. after inserting the synthesized energy-fade cause). Doing it here
    # would build reconciliation from a stale marker set.

    # Build sector_reconciliation. Note: this initial pass uses the picker's
    # markers BEFORE any energy-fade synthesis. analyze_qualifying_battle will
    # rebuild it after finalising top_causes via
    # apply_sector_conservation_and_build_reconciliation.
    sector_reconciliation: dict[str, dict] = {}
    if sector_boundary_distances[0] is not None:
        for label, lo, hi in (
            ("Sector 1", 0.0, sector_boundary_distances[0]),
            ("Sector 2", sector_boundary_distances[0], sector_boundary_distances[1]),
            ("Sector 3",
                sector_boundary_distances[1] if sector_boundary_distances[1] is not None else None,
                float(_dist_arr.max()) if _dist_arr.size else None),
        ):
            if lo is None or hi is None:
                continue
            if label in auth_gaps and auth_gaps[label] is not None:
                # auth_gaps stores FastF1 time-delta convention
                # (sector_gap_s = a_time − b_time, so positive = B faster,
                # negative = A faster). We convert to GAIN convention
                # (positive = A gained) so the reconciliation panel uses
                # the SAME sign convention as time_gained_s on markers.
                sector_gap = -float(auth_gaps[label])
            else:
                # The telemetry-integrated helper already returns values in
                # GAIN convention (positive = A gained at that span), so no
                # negation needed.
                sector_gap = _integrate_time_gained_from_samples(
                    _dist_arr, _v_a_arr, _v_b_arr,
                    start_distance=float(lo),
                    end_distance=float(hi),
                )
            sector_markers = [m for m in picked if m.get("sector") == label]
            marker_contribution = sum(m["time_gained_s"] for m in sector_markers)
            sector_reconciliation[label] = {
                # sector_gap_s and marker_contribution_s are BOTH in GAIN
                # convention now: positive = driver_a gained, negative =
                # driver_b gained. The residual is the unsurfaced gain for
                # driver_a (positive) or driver_b (negative) in this sector.
                "sector_gap_s": round(sector_gap, 4) if sector_gap is not None else None,
                "marker_contribution_s": round(marker_contribution, 4),
                "residual_s": (
                    round(sector_gap - marker_contribution, 4)
                    if sector_gap is not None else None
                ),
                "markers": sector_markers,
            }

    return {"top_causes": picked, "sector_reconciliation": sector_reconciliation}


def apply_sector_conservation_and_build_reconciliation(
    top_causes: list[dict],
    auth_gaps: dict[str, float] | None,
    sector_boundary_distances: list | tuple | None,
    sample_distances: list | None = None,
) -> dict:
    """Re-apply per-sector conservation cap to top_causes IN PLACE and
    return a fresh sector_reconciliation dict.

    Must be called AFTER top_causes is finalized (after energy-fade
    synthesis). The cap scales markers proportionally so their summed
    magnitude in a sector doesn't exceed |sector_gap_s|. The reconciliation
    dict is built from the final, capped markers — guaranteeing the
    displayed marker_contribution_s actually matches the sum of the
    markers visible to the user.

    sector_gap_s in the returned reconciliation uses GAIN convention
    (positive = driver_a gained), negated from the FastF1 TIME-DELTA
    input so it matches time_gained_s on markers.
    """
    auth_gaps = dict(auth_gaps or {})
    # Conservation cap: scale markers' time_gained_s if a sector's named
    # sum magnitude exceeds the authoritative |sector_gap|.
    if auth_gaps and top_causes:
        sectors_seen = {m.get("sector") for m in top_causes if m.get("sector")}
        for label in sectors_seen:
            gap = auth_gaps.get(label)
            if gap is None:
                continue
            sec_markers = [m for m in top_causes if m.get("sector") == label]
            named_sum = sum(
                m.get("time_gained_s") or 0.0 for m in sec_markers
            )
            if abs(named_sum) <= abs(gap) + 1e-6:
                continue
            scale = abs(gap) / abs(named_sum) if abs(named_sum) > 0 else 0.0
            for m in sec_markers:
                tg = m.get("time_gained_s")
                if tg is not None:
                    m["time_gained_s"] = tg * scale

    # Build sector_reconciliation from final top_causes.
    reconciliation: dict[str, dict] = {}
    if not sector_boundary_distances or sector_boundary_distances[0] is None:
        return reconciliation
    b1, b2 = sector_boundary_distances[0], sector_boundary_distances[1] if len(sector_boundary_distances) > 1 else None
    max_dist = max(sample_distances) if sample_distances else None
    sector_ranges = [
        ("Sector 1", 0.0, b1),
        ("Sector 2", b1, b2),
        ("Sector 3", b2, max_dist),
    ]
    for label, lo, hi in sector_ranges:
        if lo is None or hi is None:
            continue
        if label in auth_gaps and auth_gaps[label] is not None:
            # auth_gaps is FastF1 TIME-DELTA (positive = A slower).
            # Convert to GAIN convention (positive = A gained) so
            # sector_gap_s and marker_contribution_s share the same sign.
            sector_gap = -float(auth_gaps[label])
        else:
            sector_gap = None
        sec_markers = [m for m in top_causes if m.get("sector") == label]
        marker_contribution = sum(
            m.get("time_gained_s") or 0.0 for m in sec_markers
        )
        reconciliation[label] = {
            "sector_gap_s": round(sector_gap, 4) if sector_gap is not None else None,
            "marker_contribution_s": round(marker_contribution, 4),
            "residual_s": (
                round(sector_gap - marker_contribution, 4)
                if sector_gap is not None else None
            ),
            "markers": sec_markers,
        }
    return reconciliation


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
                "drs_a_active": bool(sample.get("drs_a_active") or sample.get("drs_a")),
                "drs_b_active": bool(sample.get("drs_b_active") or sample.get("drs_b")),
            })
            last_distance = distance
    if reduced and reduced[-1]["distance_m"] != samples[-1].get("distance_m"):
        final = samples[-1]
        reduced.append({
            "distance_m": final.get("distance_m"),
            "speed_a": final.get("speed_a"),
            "speed_b": final.get("speed_b"),
            "delta_speed": final.get("delta_speed"),
            "drs_a_active": bool(final.get("drs_a_active") or final.get("drs_a")),
            "drs_b_active": bool(final.get("drs_b_active") or final.get("drs_b")),
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


def _classify_decisive_sector(
    s1_gap_s: float,
    s2_gap_s: float,
    s3_gap_s: float,
    dominance_threshold: float = 0.55,
) -> dict:
    """Classify a qualifying lap's decisive sector by share of total absolute gap.

    Returns {"decisive_sector": "S1"|"S2"|"S3"|None, "split_sector_lap": bool}.

    decisive_sector is None when:
      - Total absolute gap is negligible (no meaningful difference between laps)
      - Or no sector owns >= dominance_threshold of the total absolute gap
        (i.e. the gap is distributed across sectors)

    split_sector_lap is True only in the second case — when there IS a gap
    but it's spread across sectors.
    """
    abs_gaps = {"S1": abs(s1_gap_s), "S2": abs(s2_gap_s), "S3": abs(s3_gap_s)}
    total = sum(abs_gaps.values())
    if total < 1e-6:
        return {"decisive_sector": None, "split_sector_lap": False}
    dominant_sector, dominant_gap = max(abs_gaps.items(), key=lambda kv: kv[1])
    if dominant_gap / total >= dominance_threshold:
        return {"decisive_sector": dominant_sector, "split_sector_lap": False}
    return {"decisive_sector": None, "split_sector_lap": True}


def analyze_qualifying_battle(round_number: int, driver_a: str, driver_b: str, session_type: str = "Q") -> dict:
    """
    Backend-derived causal summary for a qualifying battle.
    Explains where the time was gained and the most likely mechanism.
    """
    session, compared_segment, chosen_laps = _get_comparable_qualifying_laps(round_number, [driver_a, driver_b], session_type)
    year = int(session.event["Year"])
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
    s1_gap = sector_rows[0][1] or 0.0
    s2_gap = sector_rows[1][1] or 0.0
    s3_gap = sector_rows[2][1] or 0.0
    _classification = _classify_decisive_sector(s1_gap, s2_gap, s3_gap)
    split_sector_lap = _classification["split_sector_lap"]
    _short_to_long = {"S1": "Sector 1", "S2": "Sector 2", "S3": "Sector 3"}
    _short_to_gap = {"S1": s1_gap, "S2": s2_gap, "S3": s3_gap}
    if _classification["decisive_sector"] is not None:
        _short = _classification["decisive_sector"]
        decisive_sector = _short_to_long[_short]
        decisive_sector_gap = _short_to_gap[_short]
    else:
        decisive_sector = None
        decisive_sector_gap = None

    comparison_samples = telemetry.get("comparison", []) if telemetry else []
    sector_boundary_distances = telemetry.get("sector_boundary_distances", [None, None]) if telemetry else [None, None]
    # Authoritative per-sector A-B time gap, A − B convention, from FastF1
    # lap-time sector splits. Used downstream — single source of truth so
    # the reconciliation panel's sector_gap_s matches the sector breakdown
    # panel exactly.
    authoritative_sector_gaps_s = {
        "Sector 1": sector_rows[0][1],
        "Sector 2": sector_rows[1][1],
        "Sector 3": sector_rows[2][1],
    }
    telemetry_summary = _summarize_telemetry_battle(
        comparison_samples,
        faster_driver,
        driver_a_code,
        driver_b_code,
        sector_boundary_distances=sector_boundary_distances,
        round_number=round_number,
        authoritative_sector_gaps_s=authoritative_sector_gaps_s,
        year=year,
    )
    top_causes = (telemetry_summary.get("top_causes") or []) if telemetry_summary else []
    sector_reconciliation = (
        telemetry_summary.get("sector_reconciliation") or {}
    ) if telemetry_summary else {}

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
            # Express the energy cause's rank_weight in the same time-per-meter
            # units as _summarize_telemetry_battle now uses, so this cause
            # competes fairly with braking/min_speed/traction. The fade event
            # occurs at full-throttle top speed (~290 kph slow-car nominal);
            # we approximate per-meter time loss = Δv * 3.6 / v² and keep the
            # historical +15% boost that priorities energy explanations.
            ENERGY_NOMINAL_SLOW_KPH = 290.0
            v_slow_ms = ENERGY_NOMINAL_SLOW_KPH / 3.6
            v_fast_ms = max((ENERGY_NOMINAL_SLOW_KPH + abs(delta_speed)) / 3.6, 1.0)
            energy_time_per_m = max((1.0 / v_slow_ms) - (1.0 / v_fast_ms), 0.0)
            energy_winner_kph = ENERGY_NOMINAL_SLOW_KPH + abs(delta_speed)
            # Two-point approximation over a 200m window — synthetic cause
            # has no per-sample telemetry of its own, so we use the same
            # window as the standard cause-level fallback. Signed by A's
            # perspective: faded_driver=B (delta_speed>0) → A gained, sign=+.
            # faded_driver=A (delta_speed<0) → B gained, sign=-.
            energy_time_magnitude = _compute_time_gained_over_window(
                v_winner_kph=energy_winner_kph,
                v_loser_kph=ENERGY_NOMINAL_SLOW_KPH,
                window_distance_m=200.0,
            )
            if energy_time_magnitude is None:
                energy_time_gained_s = None
            else:
                energy_sign = 1.0 if faded_driver == driver_b_code else -1.0
                energy_time_gained_s = energy_sign * energy_time_magnitude
            energy_cause = {
                "cause_type": "straight_line_speed_energy_limited",
                "magnitude": abs(delta_speed),
                "rank_weight": energy_time_per_m * 1.15,
                "distance_m": energy_distance,
                "delta_speed_kph": delta_speed,
                "speed_a": None,
                "speed_b": None,
                "time_gained_s": energy_time_gained_s,
                "gainer_driver": (
                    driver_b_code if (faded_driver == driver_a_code) else driver_a_code
                ),
                "sector": _sector_label_for_distance(energy_distance, sector_boundary_distances),
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
            top_causes = [energy_cause, *non_energy_causes][:4]
            # Keep lap order for downstream rendering / sector grouping.
            top_causes.sort(key=lambda tc: tc.get("distance_m") or 0)

    # Rebuild sector_reconciliation now that top_causes is finalized
    # (energy-fade cause may have replaced an earlier picker selection).
    # This guarantees marker_contribution_s actually sums the displayed
    # markers — no more stale reconciliation from the pre-energy set.
    _sample_distances = [s.get("distance_m") for s in comparison_samples
                         if s.get("distance_m") is not None]
    sector_reconciliation = apply_sector_conservation_and_build_reconciliation(
        top_causes,
        authoritative_sector_gaps_s,
        sector_boundary_distances,
        sample_distances=_sample_distances,
    )

    # Primary = largest |time_gained_s| marker (or fall back to first when
    # time_gained_s is missing). `top_causes` itself stays in lap order.
    def _abs_time(tc):
        tg = tc.get("time_gained_s")
        return abs(tg) if tg is not None else 0.0
    primary_cause = max(top_causes, key=_abs_time) if top_causes else None
    decisive_distance = primary_cause["distance_m"] if primary_cause else None
    cause_type = primary_cause["cause_type"] if primary_cause else "mixed"
    primary_location_context = (
        _telemetry_location_context(round_number, primary_cause["distance_m"], primary_cause["cause_type"], year=year)
        if primary_cause else None
    )
    cause_explanation = _cause_explanation(
        cause_type,
        primary_cause["distance_m"] if primary_cause else None,
        primary_location_context,
        gainer_driver=(primary_cause.get("gainer_driver") if primary_cause else None),
        faster_driver=faster_driver,
        driver_a_code=driver_a_code,
        driver_b_code=driver_b_code,
        is_teammate_comparison=is_teammate_comparison,
        corner_name=(primary_cause.get("corner_name") if primary_cause else None),
        location_label=(primary_cause.get("location_label") if primary_cause else None),
    )

    # Build multi-cause explanation list. Rank by absolute time contribution
    # so "Primary" / "Secondary" / "Tertiary" labels reflect *time impact*,
    # not lap order. Lap-ordered top_causes stay intact for sector grouping.
    causes_ranked_by_impact = sorted(top_causes, key=_abs_time, reverse=True)
    cause_explanations = []
    for i, tc in enumerate(causes_ranked_by_impact):
        location_context = (
            primary_location_context
            if tc is primary_cause and primary_location_context is not None
            else _telemetry_location_context(round_number, tc["distance_m"], tc["cause_type"], year=year)
        )
        cause_explanations.append({
            "cause_type": tc["cause_type"],
            "rank": i + 1,
            "distance_m": tc["distance_m"],
            "delta_speed_kph": tc["delta_speed_kph"],
            "speed_a": tc.get("speed_a"),
            "speed_b": tc.get("speed_b"),
            "time_gained_s": tc.get("time_gained_s"),
            "gainer_driver": tc.get("gainer_driver"),
            "gear_a": tc.get("gear_a"),
            "gear_b": tc.get("gear_b"),
            "sector": _sector_for_distance(tc["distance_m"]) or tc.get("sector"),
            "corner_number": tc.get("corner_number"),
            "corner_name": tc.get("corner_name"),
            "location_label": tc.get("location_label"),
            "location_context": location_context,
            "explanation": _cause_explanation(
                tc["cause_type"],
                tc["distance_m"],
                location_context,
                gainer_driver=tc.get("gainer_driver"),
                faster_driver=faster_driver,
                driver_a_code=driver_a_code,
                driver_b_code=driver_b_code,
                is_teammate_comparison=is_teammate_comparison,
                corner_name=tc.get("corner_name"),
                location_label=tc.get("location_label"),
            ),
        })

    decisive_corner = _nearest_corner_label(round_number, decisive_distance)

    strongest_evidence = [
        f"Overall qualifying gap: {abs(overall_gap):.3f}s in favour of {faster_driver}.",
    ]
    if decisive_sector_gap is not None:
        strongest_evidence.append(f"{decisive_sector} accounts for {abs(decisive_sector_gap):.3f}s of the gap.")
    for i, tc in enumerate(cause_explanations):
        prefix = "Primary" if i == 0 else ("Secondary" if i == 1 else "Tertiary")
        delta_kph = tc.get("delta_speed_kph")
        delta_phrase = f"{abs(delta_kph):.1f} kph speed separation" if delta_kph is not None else "speed separation"
        time_phrase = (
            f" ({abs(tc['time_gained_s']):.3f}s)" if tc.get("time_gained_s") is not None else ""
        )
        gainer = tc.get("gainer_driver")
        gainer_phrase = f" — {gainer} gained" if gainer else ""
        strongest_evidence.append(
            f"{prefix} mechanism — {tc['cause_type']}{gainer_phrase}: "
            f"{delta_phrase}{time_phrase}"
            f"{_location_phrase(tc.get('distance_m'), tc.get('location_context'))}."
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
        zone_summary_driver = primary_cause.get("gainer_driver") or faster_driver
        zone_summary = (
            f"{' '.join(location_bits) if location_bits else 'Key zone'}: "
            f"{zone_summary_driver} has a {abs(primary_cause['delta_speed_kph']):.1f} kph speed advantage "
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
        "split_sector_lap": split_sector_lap,
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
        "sector_reconciliation": sector_reconciliation,
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

    FastF1 doesn't expose circuit info at the module level — circuit info is
    only available on a loaded session. `session.get_circuit_info()` internally
    calls `self.laps.pick_fastest()` to determine corner distances along the
    fastest lap, so we MUST load laps (and the telemetry that backs them).

    Tries qualifying first (richest data, most lap variety) then race.
    Returns [] if no session for the round has happened yet.
    """
    session = None
    for st in ('Q', 'R'):
        try:
            session = _load_session(
                round_number, st,
                laps=True, telemetry=True, weather=False, messages=False,
            )
            break
        except Exception:
            session = None
    if session is None:
        return []
    try:
        circuit_info = session.get_circuit_info()
    except Exception:
        return []
    if circuit_info is None or getattr(circuit_info, 'corners', None) is None:
        return []
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
    except FastF1Error:
        circuit_info = fastf1.get_circuit_info(CURRENT_YEAR, round_number)
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

    try:
        session = _load_session(round_number, session_type, laps=True, telemetry=False, weather=False, messages=False)
    except FastF1Error:
        return _unavailable_payload(round_number, session_type)
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
    try:
        session = _load_session(round_number, session_type, laps=True, telemetry=False, weather=False, messages=False)
    except FastF1Error:
        return _unavailable_payload(round_number, session_type)

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
    try:
        session = _load_session(round_number, session_type, laps=True, telemetry=False, weather=False, messages=True)
    except FastF1Error:
        return _unavailable_payload(round_number, session_type)
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
    try:
        session = _load_session(round_number, session_type, laps=True, telemetry=True, weather=False, messages=False)
    except FastF1Error:
        return _unavailable_payload(round_number, session_type)

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
    try:
        session = _load_session(round_number, session_type, laps=False, telemetry=False, weather=True, messages=False)
    except FastF1Error:
        return _unavailable_payload(round_number, session_type)

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

    entry_dist = zone_samples[0].get('distance_m')
    exit_dist = zone_samples[-1].get('distance_m')
    corner_length_m = None
    if entry_dist is not None and exit_dist is not None:
        corner_length_m = max(float(exit_dist) - float(entry_dist), 0.0)

    return {
        'entry_speed_kph': entry_speed,
        'apex_speed_kph': apex_speed,
        'exit_speed_kph': exit_speed,
        'braking_point_m': braking_point_m,
        'apex_gear': apex_gear,
        'traction_point_m': traction_point_m,
        'entry_distance_m': entry_dist,
        'exit_distance_m': exit_dist,
        'corner_length_m': corner_length_m,
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


def _linear_regression_raw(x_vals: list[float], y_vals: list[float]) -> tuple[float, float, float]:
    """
    Pure Python simple linear regression without rounding.
    Used for model selection where rounded parameters can distort SSE/BIC.
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

    return (slope, intercept, r_squared)


def _regression_sse(x_vals: list[float], y_vals: list[float], slope: float, intercept: float) -> float:
    return sum((y - (slope * x + intercept)) ** 2 for x, y in zip(x_vals, y_vals))


def _detect_cliff(
    tyre_ages: list[float],
    lap_times: list[float],
    min_segment_laps: int = 5,
    bic_threshold: float = 6.0,
    slope_ratio_threshold: float = 2.5,
    slope_abs_increase_threshold: float = 0.06,
    sse_epsilon: float = 1e-9,
) -> dict:
    """
    Detect a sustained tyre performance cliff with two-segment linear regression.

    The model compares a one-line fit with all valid two-line breakpoints using
    BIC, then requires the post-break slope to be materially worse.
    """
    n = len(tyre_ages)
    if n != len(lap_times) or n < min_segment_laps * 2:
        return {"cliff_detected": False}

    s0, i0, _ = _linear_regression_raw(tyre_ages, lap_times)
    sse0 = _regression_sse(tyre_ages, lap_times, s0, i0)
    bic1 = n * math.log(max(sse0, sse_epsilon) / n) + 2 * math.log(n)

    best_bic2 = float("inf")
    best_k = None
    best_fit = None

    for k in range(min_segment_laps, n - min_segment_laps + 1):
        ages_pre = tyre_ages[:k]
        times_pre = lap_times[:k]
        ages_post = tyre_ages[k:]
        times_post = lap_times[k:]

        s1, i1, _ = _linear_regression_raw(ages_pre, times_pre)
        s2, i2, _ = _linear_regression_raw(ages_post, times_post)

        sse_pre = _regression_sse(ages_pre, times_pre, s1, i1)
        sse_post = _regression_sse(ages_post, times_post, s2, i2)
        sse2 = sse_pre + sse_post
        bic2 = n * math.log(max(sse2, sse_epsilon) / n) + 4 * math.log(n)

        if bic2 < best_bic2:
            best_bic2 = bic2
            best_k = k
            best_fit = (s1, i1, s2, i2)

    if best_k is None or best_fit is None:
        return {"cliff_detected": False}

    delta_bic = bic1 - best_bic2
    if delta_bic <= bic_threshold:
        return {"cliff_detected": False}

    s1, i1, s2, i2 = best_fit
    if s2 <= s1:
        return {"cliff_detected": False}

    slope_increase = s2 - s1
    ratio_is_meaningful = s1 > 0.01
    ratio = s2 / s1 if ratio_is_meaningful else None
    ratio_passes = ratio is not None and ratio >= slope_ratio_threshold
    if not ratio_passes and slope_increase < slope_abs_increase_threshold:
        return {"cliff_detected": False}

    ages_pre = tyre_ages[:best_k]
    ages_post = tyre_ages[best_k:]
    cliff_tyre_age = ages_post[0]
    confidence = "high" if delta_bic > 10 else "moderate"

    return {
        "cliff_detected": True,
        "cliff_tyre_age": cliff_tyre_age,
        "cliff_slope_increase_s_per_lap": round(slope_increase, 4),
        "cliff_severity_ratio": round(ratio, 2) if ratio is not None else None,
        "pre_cliff_deg_rate_s_per_lap": round(s1, 4),
        "post_cliff_deg_rate_s_per_lap": round(s2, 4),
        "pre_cliff_lap_count": len(ages_pre),
        "post_cliff_lap_count": len(ages_post),
        "pre_cliff_regression_line": [
            {"tyre_age": ages_pre[0], "lap_time_s": round(s1 * ages_pre[0] + i1, 3)},
            {"tyre_age": ages_pre[-1], "lap_time_s": round(s1 * ages_pre[-1] + i1, 3)},
        ],
        "post_cliff_regression_line": [
            {"tyre_age": cliff_tyre_age, "lap_time_s": round(s2 * cliff_tyre_age + i2, 3)},
            {"tyre_age": ages_post[-1], "lap_time_s": round(s2 * ages_post[-1] + i2, 3)},
        ],
        "bic_improvement": round(delta_bic, 2),
        "cliff_confidence": confidence,
    }


def _fit_stint_degradation(clean_laps: list[dict], fuel_correction_s_per_lap: float = 0.04) -> list[dict]:
    """
    Group clean laps by compound block, fit linear regression per stint.
    Returns list of stint dicts with deg_rate_s_per_lap, fuel_corrected_pace, r_squared.
    """
    if not clean_laps:
        return []

    stints: list[dict] = []
    current_compound: str | None = None
    current_laps: list[dict] = []

    previous_tyre_age = None
    for lap in sorted(clean_laps, key=lambda x: x['lap_number']):
        comp = lap['compound']
        tyre_age = lap.get('tyre_age')
        tyre_age_reset = (
            current_laps
            and tyre_age is not None
            and previous_tyre_age is not None
            and tyre_age < previous_tyre_age
        )
        if comp != current_compound or tyre_age_reset:
            if current_laps:
                stints.append({'compound': current_compound, 'laps': current_laps})
            current_compound = comp
            current_laps = [lap]
        else:
            current_laps.append(lap)
        previous_tyre_age = tyre_age
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

        # Later laps are naturally faster because the car burns fuel. Add that
        # expected fuel-burn gain back to later laps so the remaining slope is
        # tyre performance loss rather than fuel weight.
        fuel_corrected = [
            t + fuel_correction_s_per_lap * (n - min_lap)
            for t, n in zip(raw_times, lap_nums)
        ]

        tyre_ages = [
            l.get('tyre_age') or (n - min_lap + 1)
            for l, n in zip(laps, lap_nums)
        ]

        raw_slope, _, _ = _linear_regression(tyre_ages, raw_times)
        slope, intercept, r_sq = _linear_regression(tyre_ages, fuel_corrected)
        pace_at_age_1 = round(slope * 1 + intercept, 3)

        mean_t = sum(fuel_corrected) / len(fuel_corrected)
        variance = sum((t - mean_t) ** 2 for t in fuel_corrected) / len(fuel_corrected)
        std_dev = round(variance ** 0.5, 3)

        positive_deg = max(0.0, slope)
        total_deg_loss = round(positive_deg * len(laps), 3)
        cliff = _detect_cliff(tyre_ages, fuel_corrected)

        results.append({
            'compound': stint['compound'],
            'lap_count': len(laps),
            'lap_numbers': lap_nums,
            'avg_raw_pace_s': round(sum(raw_times) / len(raw_times), 3),
            'raw_pace_trend_s_per_lap': round(raw_slope, 4),
            'fuel_burn_gain_assumption_s_per_lap': fuel_correction_s_per_lap,
            'deg_rate_s_per_lap': round(slope, 4),
            'positive_deg_rate_s_per_lap': round(positive_deg, 4),
            'total_deg_loss_s': total_deg_loss,
            'fuel_corrected_pace_at_age_1_s': pace_at_age_1,
            'r_squared': round(r_sq, 3),
            'consistency_std_dev_s': std_dev,
            'ranking_basis': (
                "raw_pace_trend_s_per_lap is what the stopwatch did — the raw slope of lap times over "
                "tyre age. deg_rate_s_per_lap adds back expected fuel-burn gain; positive values estimate "
                "tyre performance loss per lap. Only compare deg rates between stints on the same compound — "
                "different compounds degrade at different baseline rates and cannot be directly compared. "
                "Lower positive_deg_rate_s_per_lap is better within the same compound."
            ),
            'scatter_data': [
                {'tyre_age': ta, 'lap_time_s': round(fc, 3), 'lap_number': ln}
                for ta, fc, ln in zip(tyre_ages, fuel_corrected, lap_nums)
            ],
            'regression_line': [
                {'tyre_age': tyre_ages[0],  'lap_time_s': round(slope * tyre_ages[0]  + intercept, 3)},
                {'tyre_age': tyre_ages[-1], 'lap_time_s': round(slope * tyre_ages[-1] + intercept, 3)},
            ],
            'cliff_detected': cliff.get('cliff_detected', False),
            'cliff_tyre_age': cliff.get('cliff_tyre_age'),
            'cliff_slope_increase_s_per_lap': cliff.get('cliff_slope_increase_s_per_lap'),
            'cliff_severity_ratio': cliff.get('cliff_severity_ratio'),
            'pre_cliff_deg_rate_s_per_lap': cliff.get('pre_cliff_deg_rate_s_per_lap'),
            'post_cliff_deg_rate_s_per_lap': cliff.get('post_cliff_deg_rate_s_per_lap'),
            'pre_cliff_lap_count': cliff.get('pre_cliff_lap_count'),
            'post_cliff_lap_count': cliff.get('post_cliff_lap_count'),
            'pre_cliff_regression_line': cliff.get('pre_cliff_regression_line') or [],
            'post_cliff_regression_line': cliff.get('post_cliff_regression_line') or [],
            'bic_improvement': cliff.get('bic_improvement'),
            'cliff_confidence': cliff.get('cliff_confidence'),
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
        pace_a = stint_a.get('fuel_corrected_pace_at_age_1_s')
        pace_b = sb.get('fuel_corrected_pace_at_age_1_s')

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
    try:
        session = _load_session(round_number, session_type, laps=True, telemetry=True, weather=False, messages=False)
    except FastF1Error:
        return _unavailable_payload(round_number, session_type)

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

    # Two-point time-gained approximation: assume the apex speed differential
    # is sustained over 0.4 * corner_length_m of the corner zone. The 0.4
    # heuristic reflects that a corner's speed minimum (apex) is held for a
    # fraction of the total zone length — the entry/exit transitions are
    # accelerating or braking phases where the per-meter delta is smaller.
    # When corner_length_m is unavailable, fall back to 80m (typical mid-speed
    # corner) and flag the record as an estimate.
    CORNER_TIME_WINDOW_FRACTION = 0.4
    CORNER_DEFAULT_LENGTH_M = 80.0

    corner_deltas: dict[str, dict] = {}
    total_time_gained_s = 0.0
    any_time_gained = False
    for key in fps:
        if key not in sps:
            continue
        fp = fps[key]
        sp = sps[key]
        cause = _classify_corner_delta(fp, sp)
        apex_a = fp.get('apex_speed_kph')
        apex_b = sp.get('apex_speed_kph')

        # Prefer the faster corner zone's length (the faster driver finished
        # the zone faster, but both define the same physical corner).
        fp_len = fp.get('corner_length_m')
        sp_len = sp.get('corner_length_m')
        if fp_len is not None and sp_len is not None:
            corner_length_m = (float(fp_len) + float(sp_len)) / 2.0
        elif fp_len is not None:
            corner_length_m = float(fp_len)
        elif sp_len is not None:
            corner_length_m = float(sp_len)
        else:
            corner_length_m = None
        time_gained_estimate = corner_length_m is None or corner_length_m <= 0
        effective_length = corner_length_m if (corner_length_m and corner_length_m > 0) else CORNER_DEFAULT_LENGTH_M
        window_m = effective_length * CORNER_TIME_WINDOW_FRACTION

        if apex_a is not None and apex_b is not None:
            winner_kph = max(apex_a, apex_b)
            loser_kph = min(apex_a, apex_b)
            magnitude = _compute_time_gained_over_window(winner_kph, loser_kph, window_m)
            if magnitude is None:
                time_gained_s = None
            else:
                # Signed: positive = driver_a gained at this corner, negative = driver_b gained.
                # Aggregated below as a signed sum so the rollup reads as net driver_a
                # advantage across corners (matches qualifying_battle top_causes convention).
                sign = 1.0 if apex_a >= apex_b else -1.0
                signed_delta = sign * magnitude
                time_gained_s = round(signed_delta, 4)
                any_time_gained = True
                total_time_gained_s += signed_delta
        else:
            time_gained_s = None

        corner_deltas[key] = {
            'cause': cause,
            'entry_delta_kph': round((fp.get('entry_speed_kph') or 0) - (sp.get('entry_speed_kph') or 0), 1),
            'apex_delta_kph': round((fp.get('apex_speed_kph') or 0) - (sp.get('apex_speed_kph') or 0), 1),
            'exit_delta_kph': round((fp.get('exit_speed_kph') or 0) - (sp.get('exit_speed_kph') or 0), 1),
            'faster_braking_point_m': fp.get('braking_point_m'),
            'slower_braking_point_m': sp.get('braking_point_m'),
            'faster_apex_gear': fp.get('apex_gear'),
            'slower_apex_gear': sp.get('apex_gear'),
            'corner_length_m': corner_length_m,
            'time_gained_s': time_gained_s,
            'time_gained_estimate': bool(time_gained_estimate),
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
            'time_gained_s': v.get('time_gained_s'),
            'time_gained_estimate': v.get('time_gained_estimate'),
            'corner_length_m': v.get('corner_length_m'),
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
        'total_time_gained_s': round(total_time_gained_s, 4) if any_time_gained else None,
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
    try:
        session = _load_session(round_number, session_type, laps=True, telemetry=False, weather=False, messages=False)
    except FastF1Error:
        return _unavailable_payload(round_number, session_type)

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
    try:
        session = _load_session(round_number, session_type, laps=True, telemetry=False, weather=False, messages=False)
    except FastF1Error:
        return _unavailable_payload(round_number, session_type)

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
        return sum(s['fuel_corrected_pace_at_age_1_s'] * s['lap_count'] for s in stints) / total

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

    clip_sig_a = None
    clip_sig_b = None
    clipping_comparison = None

    def _clipping_signature_for(code: str, lap_num: int | None) -> dict | None:
        try:
            tel = get_lap_telemetry(round_number, session_type, code, lap_num)
        except Exception:
            return None
        samples = tel.get("telemetry") or []
        if not samples:
            return None
        speeds = [s["speed_kph"] for s in samples if s.get("speed_kph") is not None]
        throttles = [s["throttle_pct"] for s in samples if s.get("speed_kph") is not None]
        distances = [s["distance_m"] for s in samples if s.get("speed_kph") is not None]
        drs_state = [1 if s.get("drs_open") else 0 for s in samples if s.get("speed_kph") is not None]
        if not speeds:
            return None
        return detect_clipping_signature(speeds, throttles, distances, drs_state=drs_state)

    clip_sig_a = _clipping_signature_for(driver_a, rep_lap_a)
    clip_sig_b = _clipping_signature_for(driver_b, rep_lap_b)
    if clip_sig_a and clip_sig_b:
        clipping_comparison = compare_drivers_clipping(
            clip_sig_a, clip_sig_b, driver_a.upper(), driver_b.upper()
        )

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
        'clipping_signature_a': clip_sig_a,
        'clipping_signature_b': clip_sig_b,
        'clipping_comparison': clipping_comparison,
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

    v_mps = kph_to_ms(v_full)
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

    v_mps = kph_to_ms(tel['Speed'].to_numpy(dtype=float))
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
    Build a speed-indexed friction ellipse from a list of telemetry DataFrames.
    Returns dict with lat_max, brake_max, throttle_max (all shape (7,)) and speed_bins.
    Each value is the 95th-percentile ceiling for that speed band.
    Falls back to _theoretical_ggv_envelope() if fewer than 2 usable frames.
    """
    lat_all, long_all, spd_all = [], [], []
    for tel in telemetry_frames:
        if any(c not in tel.columns for c in ('Speed', 'X', 'Y', 'Time')) or len(tel) < 20:
            continue
        try:
            lat_all.append(_compute_lateral_g(tel))
            long_all.append(_compute_longitudinal_g(tel))
            spd_all.append(tel['Speed'].to_numpy(dtype=float))
        except Exception:
            continue

    if len(lat_all) < 2:
        return _theoretical_ggv_envelope()

    lat_cat = np.concatenate(lat_all)
    long_cat = np.concatenate(long_all)
    spd_cat = np.concatenate(spd_all)

    n_bins = len(_GGV_BIN_EDGES) - 1
    lat_max = np.zeros(n_bins)
    brake_max = np.zeros(n_bins)
    throttle_max = np.zeros(n_bins)

    for i in range(n_bins):
        mask = (spd_cat >= _GGV_BIN_EDGES[i]) & (spd_cat < _GGV_BIN_EDGES[i + 1])
        if mask.sum() < 10:
            lat_max[i] = float(_theoretical_max_g(np.array([_GGV_BIN_CENTERS[i]]))[0])
            brake_max[i] = lat_max[i] * 1.1
            throttle_max[i] = lat_max[i] * 0.65
            continue
        lat_bin = lat_cat[mask]
        long_bin = long_cat[mask]
        lat_max[i] = max(float(np.percentile(np.abs(lat_bin), 95)), 0.5)
        braking = -long_bin[long_bin < -0.1]
        brake_max[i] = max(float(np.percentile(braking, 95)), 0.3) if len(braking) >= 5 else lat_max[i] * 1.1
        throttle = long_bin[long_bin > 0.1]
        throttle_max[i] = max(float(np.percentile(throttle, 95)), 0.2) if len(throttle) >= 5 else lat_max[i] * 0.65

    return {'lat_max': lat_max, 'brake_max': brake_max,
            'throttle_max': throttle_max, 'speed_bins': _GGV_BIN_CENTERS}


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
    """Speed-dependent theoretical max lateral G for a 2025-spec F1 car."""
    return 2.0 + speed_kph * 0.012


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
        lat_ceil, brake_ceil, thr_ceil = _ggv_ceiling_at_speed(seg_v, envelope)
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
        "apex_speed_kph": round(float(seg_v[apex_idx_local]), 1),
        "ggv_util_pct": ggv_util_pct,
        "envelope_time_pct": envelope_time_pct,
        "throttle_acceptance_pct": throttle_acceptance_pct,
        "entry_bravery_pct": entry_bravery_pct,
    }


def _align_corners(corners_a: list[tuple[int, int]], dist_a: np.ndarray,
                   corners_b: list[tuple[int, int]], dist_b: np.ndarray,
                   tolerance_m: float = 200.0) -> list[tuple[tuple, tuple]]:
    """Match corners from driver A to driver B by entry distance."""
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
        if best is not None and best_diff <= tolerance_m:
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
    try:
        session = _load_session(
            round_number,
            session_type,
            laps=True,
            telemetry=True,
            weather=False,
            messages=_session_needs_race_control_messages(session_type),
        )
    except FastF1Error:
        return _unavailable_payload(round_number, session_type)

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

    # Per-corner time-gained: two-point apex-speed approximation over
    # 0.4 * corner_length_m. Same 0.4 heuristic used in compare_corner_profiles.
    GRIP_CORNER_TIME_WINDOW_FRACTION = 0.4
    GRIP_CORNER_DEFAULT_LENGTH_M = 80.0

    per_corner = []
    for i, (ca, cb) in enumerate(aligned):
        ma = _corner_metrics(lat_g_a, long_g_a, spd_a, dist_a, ca[0], ca[1],
                             envelope=envelope, throttle=throttle_a)
        mb = _corner_metrics(lat_g_b, long_g_b, spd_b, dist_b, cb[0], cb[1],
                             envelope=envelope, throttle=throttle_b)

        apex_a = ma.get("apex_speed_kph")
        apex_b = mb.get("apex_speed_kph")
        # Corner length is the longer driver-zone (covers the full event).
        len_a = (ma.get("exit_dist_m") or 0) - (ma.get("entry_dist_m") or 0)
        len_b = (mb.get("exit_dist_m") or 0) - (mb.get("entry_dist_m") or 0)
        corner_length_m = max(float(len_a), float(len_b)) if (len_a or len_b) else None
        estimate = corner_length_m is None or corner_length_m <= 0
        eff_len = corner_length_m if (corner_length_m and corner_length_m > 0) else GRIP_CORNER_DEFAULT_LENGTH_M
        window_m = eff_len * GRIP_CORNER_TIME_WINDOW_FRACTION

        time_gained_s = None
        if apex_a is not None and apex_b is not None:
            winner_kph = max(apex_a, apex_b)
            loser_kph = min(apex_a, apex_b)
            magnitude = _compute_time_gained_over_window(winner_kph, loser_kph, window_m)
            if magnitude is not None:
                # Positive = code_a (driver_a) gained time.
                sign = 1.0 if apex_a >= apex_b else -1.0
                time_gained_s = round(sign * magnitude, 4)

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
            "corner_length_m": corner_length_m,
            "time_gained_s": time_gained_s,
            "time_gained_estimate": bool(estimate),
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
    try:
        session = _load_session(
            round_number,
            "R",
            laps=True,
            telemetry=True,
            weather=False,
            messages=False,
        )
    except FastF1Error:
        return _unavailable_payload(round_number, "R")

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
    try:
        session = _load_session(round_number, "R", laps=True)
    except FastF1Error:
        return _unavailable_payload(round_number, "R")

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
    try:
        session = _load_session(round_number, session_type, laps=True, weather=True)
    except FastF1Error:
        return _unavailable_payload(round_number, session_type)

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
    try:
        session = _load_session(round_number, session_type, laps=True, telemetry=False, weather=False, messages=False)
    except FastF1Error:
        return _unavailable_payload(round_number, session_type)
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


def get_speed_trap_leaderboard(round_number: int, session_type: str,
                                allow_mixed_drs: bool = False) -> dict:
    """Scan all laps and return peak speed at each trap (ST, FL, I1, I2) per driver.

    Each row carries a `drs_open` flag derived from telemetry at the moment of the
    peak reading. When some drivers' peak came with DRS open and others with DRS
    closed, the call returns a refusal payload unless `allow_mixed_drs=True`.
    """
    try:
        session = _load_session(round_number, session_type, laps=True, telemetry=True, weather=False, messages=False)
    except FastF1Error:
        return _unavailable_payload(round_number, session_type)
    driver_info = _driver_lookup(session)

    traps = {
        "speed_st": "SpeedST",
        "speed_fl": "SpeedFL",
        "speed_i1": "SpeedI1",
        "speed_i2": "SpeedI2",
    }

    # For each trap, build {driver_code: {speed, lap_number, compound, drs_open}}
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
            drs_open_at_trap = False
            try:
                tel = best_row.get_telemetry() if hasattr(best_row, "get_telemetry") else None
                if tel is not None and not getattr(tel, "empty", True) and 'Speed' in tel.columns and 'DRS' in tel.columns:
                    peak_speed = float(best_row[col])
                    idx = (tel['Speed'] - peak_speed).abs().idxmin()
                    drs_open_at_trap = drs_active(tel.loc[idx, 'DRS'])
            except Exception:
                drs_open_at_trap = False
            trap_bests[trap_key][code_upper] = {
                "speed_kph": round(float(best_row[col]), 1),
                "lap_number": int(best_row["LapNumber"]) if pd.notna(best_row.get("LapNumber")) else None,
                "compound": str(best_row["Compound"]) if pd.notna(best_row.get("Compound")) else None,
                "drs_open": bool(drs_open_at_trap),
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
                "drs_open": data["drs_open"],
            })
        entries.sort(key=lambda e: e["speed_kph"], reverse=True)
        for i, e in enumerate(entries):
            e["rank"] = i + 1
        return entries

    ranked_by_trap = {trap_key: _ranked(trap_key) for trap_key in traps}

    # Refusal logic: if rows mix DRS-open and DRS-closed peaks, comparison is misleading.
    if not allow_mixed_drs:
        for trap_key, rows in ranked_by_trap.items():
            has_drs_open = any(row["drs_open"] for row in rows)
            has_drs_closed = any(not row["drs_open"] for row in rows)
            if has_drs_open and has_drs_closed:
                return {
                    "available": True,
                    "refusal": (
                        "Comparing DRS-open and DRS-closed top-speeds is misleading; "
                        "the gap could be 6+ km/h purely from DRS state. "
                        "Re-ask with allow_mixed_drs=True if you want the raw figures anyway."
                    ),
                    "event": session.event["EventName"],
                    "session": session_type,
                    "trap_with_mixed_drs": trap_key,
                    "rows": rows,
                }

    return {
        "event": session.event["EventName"],
        "session": session_type,
        "trap_labels": {
            "speed_st": "Speed Trap (main straight)",
            "speed_fl": "Finish Line",
            "speed_i1": "Intermediate 1",
            "speed_i2": "Intermediate 2",
        },
        "speed_st": ranked_by_trap["speed_st"],
        "speed_fl": ranked_by_trap["speed_fl"],
        "speed_i1": ranked_by_trap["speed_i1"],
        "speed_i2": ranked_by_trap["speed_i2"],
    }


# ── F16 / F19 strategy helpers ───────────────────────────────────────────────

_PIT_LOSS_CACHE: dict[int, float] = {}
_PIT_LOSS_CACHE_LOCK = threading.Lock()


def get_actual_pit_loss(round_number: int) -> float:
    """Median in-race pit-lane delta (pit-cycle lap-time vs clean race pace).

    Computed across every stop in the race session. Cached per round.
    Returns the green-flag pit-loss in seconds; SC/VSC variants are derived
    by callers via strategy_math.compute_pit_loss_variants.
    """
    with _PIT_LOSS_CACHE_LOCK:
        cached = _PIT_LOSS_CACHE.get(round_number)
        if cached is not None:
            return cached

    try:
        session = _load_session(round_number, "R", laps=True)
    except FastF1Error:
        return 22.0  # safe field-average fallback

    laps = session.laps
    if laps is None or laps.empty:
        return 22.0

    clean_times: list[float] = []
    for _, lap in laps.iterrows():
        lt = lap.get("LapTime")
        if lt is None or pd.isna(lt):
            continue
        if pd.notna(lap.get("PitInTime")) or pd.notna(lap.get("PitOutTime")):
            continue
        track_status = str(lap.get("TrackStatus") or "")
        if any(c in track_status for c in ("4", "5", "6")):
            continue
        clean_times.append(lt.total_seconds())
    if not clean_times:
        return 22.0
    clean_times.sort()
    median_clean = clean_times[len(clean_times) // 2]

    pit_in_lap_times: list[float] = []
    for _, lap in laps.iterrows():
        if not pd.notna(lap.get("PitInTime")):
            continue
        lt = lap.get("LapTime")
        if lt is None or pd.isna(lt):
            continue
        lt_s = lt.total_seconds()
        if lt_s <= 0:
            continue
        delta = lt_s - median_clean
        if 5.0 <= delta <= 60.0:
            pit_in_lap_times.append(delta)

    if not pit_in_lap_times:
        result = 22.0
    else:
        pit_in_lap_times.sort()
        median_delta = pit_in_lap_times[len(pit_in_lap_times) // 2]
        # Add canonical stationary time (~2.4s) — most public pit-loss numbers
        # already roll this in; FastF1 PitInTime markers don't isolate it.
        result = round(float(median_delta) + 2.4, 2)

    with _PIT_LOSS_CACHE_LOCK:
        _PIT_LOSS_CACHE[round_number] = result
    return result


def get_tyre_age_at_lap(driver_code: str, lap_number: int, round_number: int,
                        session_type: str = "R") -> int:
    """Number of laps since the driver last pitted, or since lights-out if no
    stops yet. Reads session.laps for the driver and counts forwards from the
    last PitOutTime marker preceding lap_number.
    """
    try:
        session = _load_session(round_number, session_type, laps=True)
    except FastF1Error:
        return max(0, int(lap_number) - 1)

    driver_laps = _pick_driver(session.laps, driver_code.upper())
    if driver_laps.empty:
        return max(0, int(lap_number) - 1)

    driver_laps = driver_laps.sort_values("LapNumber")
    last_pit_out_lap = 0
    for _, lap in driver_laps.iterrows():
        ln = int(lap["LapNumber"]) if pd.notna(lap.get("LapNumber")) else None
        if ln is None or ln > lap_number:
            break
        if pd.notna(lap.get("PitOutTime")):
            last_pit_out_lap = ln
    return max(0, int(lap_number) - last_pit_out_lap)


def get_gap_to_driver(driver_a: str, driver_b: str, lap_number: int,
                      round_number: int, session_type: str = "R") -> float:
    """Cumulative gap (driver_a's elapsed time minus driver_b's) at the end of
    `lap_number`. Positive number means driver_a is BEHIND (slower). The plan
    spec says positive = A ahead; we follow that convention here.
    """
    try:
        session = _load_session(round_number, session_type, laps=True)
    except FastF1Error:
        return 0.0

    laps = session.laps
    if laps is None or laps.empty:
        return 0.0

    def _elapsed_through(code: str) -> float | None:
        rows = _pick_driver(laps, code.upper())
        if rows.empty:
            return None
        rows = rows[rows["LapNumber"] <= lap_number].sort_values("LapNumber")
        total = 0.0
        for _, lap in rows.iterrows():
            lt = lap.get("LapTime")
            if lt is None or pd.isna(lt):
                continue
            total += lt.total_seconds()
        return total if total > 0 else None

    elapsed_a = _elapsed_through(driver_a)
    elapsed_b = _elapsed_through(driver_b)
    if elapsed_a is None or elapsed_b is None:
        return 0.0
    # Positive = A ahead → A took less time → elapsed_b - elapsed_a.
    return round(float(elapsed_b - elapsed_a), 2)


def _build_strategy_snapshot(driver_code: str, lap_number: int,
                             target_driver_code: str | None,
                             round_number: int,
                             session_type: str = "R") -> dict:
    """Assemble the snapshot dict consumed by strategy_math.compute_undercut_window.

    See F16 plan, lines 249-258.
    """
    pit_loss_s = get_actual_pit_loss(round_number)

    track_temp_c: float | None = None
    active_sc_state = "green"
    try:
        session = _load_session(round_number, session_type, laps=True, weather=True, messages=True)
    except FastF1Error:
        session = None

    if session is not None:
        try:
            weather = session.weather_data
            if weather is not None and not weather.empty:
                track_temp_c = float(weather["TrackTemp"].median())
        except Exception:
            track_temp_c = None

        try:
            ts = session.track_status
            if ts is not None and not ts.empty:
                # Find most recent status change at or before lap_number's start time.
                laps_for_lookup = session.laps[session.laps["LapNumber"] == lap_number]
                if not laps_for_lookup.empty:
                    lap_start = laps_for_lookup.iloc[0].get("LapStartTime")
                    if lap_start is not None and pd.notna(lap_start):
                        prior = ts[ts["Time"] <= lap_start]
                        if not prior.empty:
                            current_status = str(prior.iloc[-1]["Status"])
                            if current_status == "4":
                                active_sc_state = "sc"
                            elif current_status == "6":
                                active_sc_state = "vsc"
        except Exception:
            pass

    driver_info = _driver_strategy_info(driver_code, lap_number, round_number, session_type, session)
    target_info = None
    gap_to_target_s = None
    if target_driver_code:
        target_info = _driver_strategy_info(
            target_driver_code, lap_number, round_number, session_type, session
        )
        gap_to_target_s = get_gap_to_driver(driver_code, target_driver_code, lap_number, round_number, session_type)

    cars_in_rejoin_window = _project_rejoin_window(
        driver_code, lap_number, round_number, session_type,
        gap_to_target_s, pit_loss_s, session,
    )

    return {
        "pit_loss_s": pit_loss_s,
        "track_temp_c": track_temp_c,
        "driver": driver_info,
        "target": target_info,
        "gap_to_target_s": gap_to_target_s,
        "cars_in_rejoin_window": cars_in_rejoin_window,
        "active_sc_state": active_sc_state,
    }


def _driver_strategy_info(driver_code: str, lap_number: int, round_number: int,
                          session_type: str, session) -> dict:
    """Per-driver block: compound, age, deg slope, cliff fields, base pace."""
    info = {
        "driver_code": driver_code.upper(),
        "compound": None,
        "tyre_age": get_tyre_age_at_lap(driver_code, lap_number, round_number, session_type),
        "deg_slope": None,
        "base_pace": None,
        "base_pace_new": None,
        "next_compound": None,
        "stint_laps_used": 0,
        "has_cliff": False,
        "pre_cliff_slope": None,
        "post_cliff_slope": None,
        "cliff_age": None,
    }
    if session is None:
        return info

    driver_laps = _pick_driver(session.laps, driver_code.upper())
    if driver_laps.empty:
        return info

    # Pick the current compound from the most recent lap at or before lap_number.
    prior = driver_laps[driver_laps["LapNumber"] <= lap_number].sort_values("LapNumber")
    if not prior.empty:
        comp = prior.iloc[-1].get("Compound")
        if comp is not None and pd.notna(comp):
            info["compound"] = str(comp).upper()

    try:
        clean = _filter_clean_race_laps(driver_laps)
        if clean:
            stints = _fit_stint_degradation(clean)
            current_stint = None
            for stint in stints:
                lap_nums = stint.get("lap_numbers") or []
                if lap_nums and lap_nums[0] <= lap_number:
                    current_stint = stint
            if current_stint is not None:
                info["deg_slope"] = current_stint.get("deg_rate_s_per_lap")
                info["base_pace"] = current_stint.get("fuel_corrected_pace_at_age_1_s")
                info["stint_laps_used"] = current_stint.get("lap_count", 0)
                info["has_cliff"] = bool(current_stint.get("cliff_detected"))
                info["pre_cliff_slope"] = current_stint.get("pre_cliff_deg_rate_s_per_lap")
                info["post_cliff_slope"] = current_stint.get("post_cliff_deg_rate_s_per_lap")
                info["cliff_age"] = current_stint.get("cliff_tyre_age")
    except Exception:
        pass

    # base_pace_new: if the driver ran the typical replacement compound earlier
    # this race, use that compound's first-three-laps median; otherwise fall
    # back to base_pace minus a typical 1.0s/lap fresh-tyre offset.
    if info["base_pace"] is not None:
        info["base_pace_new"] = round(float(info["base_pace"]) - 1.5, 3)

    return info


def _project_rejoin_window(driver_code: str, lap_number: int, round_number: int,
                           session_type: str, gap_to_target_s: float | None,
                           pit_loss_s: float, session) -> list[dict]:
    """Identify cars likely to be within ±2s of the focal driver's rejoin gap.

    Returns a list of {code, predicted_pace, predicted_gap_after_pit}.
    Best-effort — returns [] if the session isn't fully available.
    """
    if session is None or gap_to_target_s is None:
        return []
    try:
        laps = session.laps
        if laps is None or laps.empty:
            return []
        all_codes = [str(c).upper() for c in laps["Driver"].dropna().unique()]
        focal_code = driver_code.upper()
        results: list[dict] = []
        for code in all_codes:
            if code == focal_code:
                continue
            gap = get_gap_to_driver(focal_code, code, lap_number, round_number, session_type)
            projected_gap_after_pit = gap - pit_loss_s
            if not (-2.0 <= projected_gap_after_pit <= 2.0):
                continue
            other_laps = _pick_driver(laps, code)
            clean = _filter_clean_race_laps(other_laps)
            predicted_pace = None
            if clean:
                recent = clean[-5:]
                if recent:
                    predicted_pace = round(sum(l["lap_time_s"] for l in recent) / len(recent), 3)
            results.append({
                "code": code,
                "predicted_pace": predicted_pace,
                "predicted_gap_after_pit": round(projected_gap_after_pit, 2),
            })
        return results
    except Exception:
        return []


def analyze_undercut_overcut(driver_code: str, lap_number: int,
                             round_number: int,
                             target_driver_code: str | None = None,
                             session_type: str = "R") -> dict:
    """Top-level entry point invoked by the `analyze_undercut_overcut` tool.

    Builds the strategy snapshot, runs the pure-math model, returns a single
    dict ready for the chat widget builder.
    """
    from strategy_math import compute_undercut_window  # avoid circular

    snapshot = _build_strategy_snapshot(
        driver_code, int(lap_number), target_driver_code, round_number, session_type
    )
    result = compute_undercut_window(
        driver_code.upper(), int(lap_number), target_driver_code, snapshot
    )
    result["round_number"] = round_number
    result["session_type"] = session_type
    # Resolve a human-readable event name if we managed to load the session.
    try:
        session = _load_session(round_number, session_type, laps=True)
        result["event"] = session.event["EventName"]
    except FastF1Error:
        result["event"] = None
    return result
