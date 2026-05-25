"""Curvature-based corner segmentation.

Builds a list of CornerRegion records per circuit by computing curvature
κ(s) along the track centerline derived from a clean reference lap's
position telemetry. Each region exposes explicit (entry_m, apex_m, exit_m)
bounds — replacing the nearest-apex-within-radius heuristic with proper
geometric segmentation. Track is treated as circular (wrap-around handled).

Public API:
    get_corner_regions(year, round_number) -> list[CornerRegion]
    resolve_corner_for_distance(year, round_number, distance_m) -> dict
"""

from __future__ import annotations

import json
import logging
import math
import os
from dataclasses import asdict, dataclass
from typing import Optional

import numpy as np
from scipy.interpolate import interp1d
from scipy.signal import savgol_filter

LOGGER = logging.getLogger(__name__)

SCHEMA_VERSION = 3

CACHE_DIR = os.path.join(os.path.dirname(__file__), "cache", "corner_regions")

KAPPA_ENTER_PERCENTILE = 70.0
KAPPA_EXIT_PERCENTILE = 50.0

RESAMPLE_SPACING_M = 2.0

SAVGOL_WINDOW = 21
SAVGOL_POLY = 3

MIN_RAW_SAMPLES = 100

MIN_REGION_WIDTH_M = 20.0

RESCUE_WINDOW_M = 100.0
RESCUE_KAPPA_FLOOR = 0.001
RESCUE_MIN_WIDTH_M = 10.0
RESCUE_FALLBACK_HALF_WIDTH_M = 20.0

DEBOUNCE_GAP_M = 10.0

MIN_REGIONS = 4
MAX_REGIONS = 40
MIN_LAP_LENGTH_M = 2000.0
MAX_LAP_LENGTH_M = 8500.0


@dataclass
class CornerRegion:
    corner_number: Optional[int]
    label_suffix: str
    entry_m: float
    apex_m: float
    exit_m: float
    sign: int


class SegmentationInputError(ValueError):
    """Raised when input data is too sparse or corrupt to segment safely."""


def _clean_xy(x: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Drop non-finite rows and zero-arc-length duplicates.

    Raises SegmentationInputError if fewer than MIN_RAW_SAMPLES rows
    survive — caller is expected to fall back to a legacy resolver.
    """
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    finite = np.isfinite(x) & np.isfinite(y)
    x = x[finite]
    y = y[finite]
    if len(x) < 2:
        raise SegmentationInputError(f"only {len(x)} finite samples")
    keep = np.ones(len(x), dtype=bool)
    keep[1:] = (x[1:] != x[:-1]) | (y[1:] != y[:-1])
    x = x[keep]
    y = y[keep]
    if len(x) < MIN_RAW_SAMPLES:
        raise SegmentationInputError(
            f"only {len(x)} valid samples after cleaning (need >= {MIN_RAW_SAMPLES})"
        )
    return x, y


def _cumulative_arc_length(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    dx = np.diff(x)
    dy = np.diff(y)
    seg = np.sqrt(dx * dx + dy * dy)
    return np.concatenate(([0.0], np.cumsum(seg)))


def _resample_uniform(
    x: np.ndarray, y: np.ndarray, spacing_m: float = RESAMPLE_SPACING_M
) -> tuple[np.ndarray, np.ndarray, np.ndarray, float, float]:
    """Resample (x, y) at exact spacing_m. Returns (x_new, y_new, s_new, spacing, total)."""
    s = _cumulative_arc_length(x, y)
    total = float(s[-1])
    s_new = np.arange(0.0, total + 1e-9, spacing_m)
    s_new = s_new[s_new <= total]
    if len(s_new) < 2:
        raise SegmentationInputError(
            f"total arc length {total}m too short for spacing {spacing_m}m"
        )
    x_interp = interp1d(s, x, kind="cubic", assume_sorted=True)
    y_interp = interp1d(s, y, kind="cubic", assume_sorted=True)
    return x_interp(s_new), y_interp(s_new), s_new, float(spacing_m), total


def _compute_curvature(
    x: np.ndarray, y: np.ndarray, spacing_m: float
) -> np.ndarray:
    """Signed curvature κ(s) for uniformly resampled (x, y).

    Sign convention: positive κ = left turn (counter-clockwise),
    negative = right turn.
    """
    n = len(x)
    window = min(SAVGOL_WINDOW, n if n % 2 == 1 else n - 1)
    if window < 5 or window <= SAVGOL_POLY:
        return np.zeros_like(x)
    dx = savgol_filter(x, window, SAVGOL_POLY, deriv=1, delta=spacing_m)
    dy = savgol_filter(y, window, SAVGOL_POLY, deriv=1, delta=spacing_m)
    ddx = savgol_filter(x, window, SAVGOL_POLY, deriv=2, delta=spacing_m)
    ddy = savgol_filter(y, window, SAVGOL_POLY, deriv=2, delta=spacing_m)
    denom = (dx * dx + dy * dy) ** 1.5
    denom = np.where(denom < 1e-9, 1e-9, denom)
    return (dx * ddy - dy * ddx) / denom


def _nearest_idx(s: np.ndarray, value: float) -> int:
    return int(np.argmin(np.abs(s - value)))


def _finalize_region(
    s: np.ndarray,
    kappa: np.ndarray,
    start_idx: int,
    end_idx: int,
) -> tuple[float, float, float, int]:
    slice_ = kappa[start_idx : end_idx + 1]
    apex_local = int(np.argmax(np.abs(slice_)))
    apex_global = start_idx + apex_local
    return (
        float(s[start_idx]),
        float(s[apex_global]),
        float(s[end_idx]),
        1 if kappa[apex_global] >= 0 else -1,
    )


def _detect_regions(
    s: np.ndarray,
    kappa: np.ndarray,
    kappa_enter: float,
    kappa_exit: float,
    lap_length_m: float,
) -> list[tuple[float, float, float, int]]:
    """Walk κ(s) with hysteresis; merge wrap-around regions at s=0.

    Order: hysteresis walk -> debounce-merge -> wrap-merge -> width-filter.

    Each region is (entry_m, apex_m, exit_m, sign). For wrap-around
    regions entry_m > exit_m. Sign is +1 for left turn, -1 for right.
    """
    abs_k = np.abs(kappa)
    in_corner = False
    start_idx = 0
    raw: list[tuple[float, float, float, int]] = []
    for i in range(len(s)):
        if not in_corner and abs_k[i] >= kappa_enter:
            in_corner = True
            start_idx = i
        elif in_corner and abs_k[i] < kappa_exit:
            in_corner = False
            raw.append(_finalize_region(s, kappa, start_idx, i - 1))
    if in_corner:
        raw.append(_finalize_region(s, kappa, start_idx, len(s) - 1))

    # Debounce pass: merge same-sign adjacent regions with gap < DEBOUNCE_GAP_M.
    # Done before the wrap-around merge so the wrap merge sees fully-merged halves.
    merged: list[tuple[float, float, float, int]] = []
    for region in raw:
        if merged and merged[-1][3] == region[3] and region[0] - merged[-1][2] < DEBOUNCE_GAP_M:
            prev = merged[-1]
            prev_apex_k = abs(kappa[_nearest_idx(s, prev[1])])
            cur_apex_k = abs(kappa[_nearest_idx(s, region[1])])
            new_apex = prev[1] if prev_apex_k >= cur_apex_k else region[1]
            merged[-1] = (prev[0], new_apex, region[2], prev[3])
        else:
            merged.append(region)
    raw = merged

    # Wrap-around merge: MUST run before the width filter — otherwise two
    # 18m halves of a real wrap-around corner get filtered as noise before
    # they can combine into a single 36m region.
    if len(raw) >= 2:
        first = raw[0]
        last = raw[-1]
        start_at_zero = first[0] <= 2.0
        end_at_lap_end = last[2] >= lap_length_m - 2.0
        same_sign = first[3] == last[3]
        if start_at_zero and end_at_lap_end and same_sign:
            entry = last[0]
            exit_ = first[2]
            apex = first[1] if abs(kappa[_nearest_idx(s, first[1])]) >= abs(kappa[_nearest_idx(s, last[1])]) else last[1]
            raw = [(entry, apex, exit_, first[3])] + raw[1:-1]

    # Width filter: runs after wrap-merge so a real wrap-around corner
    # that produces two narrow halves keeps its full merged width.
    def _region_width(region):
        entry, _apex, exit_, _sign = region
        if entry <= exit_:
            return exit_ - entry
        return (lap_length_m - entry) + exit_

    raw = [r for r in raw if _region_width(r) >= MIN_REGION_WIDTH_M]
    return raw


def _split_merged_regions(
    regions: list[tuple[float, float, float, int]],
    multiviewer_corners: list[dict],
    s: np.ndarray,
    kappa: np.ndarray,
    lap_length_m: float,
) -> list[tuple[float, float, float, int]]:
    """Split regions that contain 2+ MV corner apexes.

    For each such region, find the |kappa| local minimum between each
    consecutive pair of MV corners and split the region there.
    """
    result: list[tuple[float, float, float, int]] = []
    for region in regions:
        entry, _apex, exit_, _sign = region
        # Skip wrap-around regions (entry > exit) — rare edge case
        if entry > exit_:
            result.append(region)
            continue
        inside = [
            c for c in multiviewer_corners
            if _distance_inside_region(region, float(c["distance_m"]), lap_length_m)
        ]
        if len(inside) < 2:
            result.append(region)
            continue
        inside.sort(key=lambda c: float(c["distance_m"]))
        entry_idx = _nearest_idx(s, entry)
        exit_idx = _nearest_idx(s, exit_)
        abs_k = np.abs(kappa)
        split_indices = []
        for j in range(len(inside) - 1):
            d_left = float(inside[j]["distance_m"])
            d_right = float(inside[j + 1]["distance_m"])
            left_idx = max(_nearest_idx(s, d_left), entry_idx)
            right_idx = min(_nearest_idx(s, d_right), exit_idx)
            if left_idx >= right_idx:
                continue
            local_min_idx = left_idx + int(np.argmin(abs_k[left_idx:right_idx + 1]))
            split_indices.append(local_min_idx)
        if not split_indices:
            result.append(region)
            continue
        bounds = [entry_idx] + split_indices + [exit_idx]
        for k in range(len(bounds) - 1):
            si = bounds[k]
            ei = bounds[k + 1]
            sub = _finalize_region(s, kappa, si, ei)
            sub_width = sub[2] - sub[0]
            if sub_width >= MIN_REGION_WIDTH_M:
                result.append(sub)
    return result


def _rescue_missing_corners(
    regions: list[tuple[float, float, float, int]],
    multiviewer_corners: list[dict],
    s: np.ndarray,
    kappa: np.ndarray,
    lap_length_m: float,
) -> list[tuple[float, float, float, int]]:
    """Rescue MV corners missed by the global-threshold detector.

    For each MV corner not already inside an existing region, look at
    local |kappa| in a +/-RESCUE_WINDOW_M window. If a curvature peak
    exists above RESCUE_KAPPA_FLOOR, walk outward to define a region;
    otherwise create a narrow synthetic region.
    """
    abs_k = np.abs(kappa)
    result = list(regions)

    for mv in multiviewer_corners:
        mv_dist = float(mv["distance_m"])
        already_matched = any(
            _distance_inside_region(r, mv_dist, lap_length_m) for r in result
        )
        if already_matched:
            continue

        center_idx = _nearest_idx(s, mv_dist)
        window_samples = int(RESCUE_WINDOW_M / RESAMPLE_SPACING_M)
        lo = max(center_idx - window_samples, 0)
        hi = min(center_idx + window_samples, len(s) - 1)

        local_abs_k = abs_k[lo : hi + 1]
        peak_val = float(np.max(local_abs_k))

        if peak_val < RESCUE_KAPPA_FLOOR:
            fallback_lo = max(_nearest_idx(s, mv_dist - RESCUE_FALLBACK_HALF_WIDTH_M), 0)
            fallback_hi = min(_nearest_idx(s, mv_dist + RESCUE_FALLBACK_HALF_WIDTH_M), len(s) - 1)
            new_region = _finalize_region(s, kappa, fallback_lo, fallback_hi)
        else:
            peak_local_idx = int(np.argmax(local_abs_k))
            peak_idx = lo + peak_local_idx

            start_idx = peak_idx
            while start_idx > 0 and abs_k[start_idx - 1] >= RESCUE_KAPPA_FLOOR:
                start_idx -= 1

            end_idx = peak_idx
            while end_idx < len(s) - 1 and abs_k[end_idx + 1] >= RESCUE_KAPPA_FLOOR:
                end_idx += 1

            new_region = _finalize_region(s, kappa, start_idx, end_idx)

        width = new_region[2] - new_region[0]
        if width < RESCUE_MIN_WIDTH_M:
            continue

        entry, _apex, exit_, _sign = new_region
        overlaps = any(
            _distance_inside_region(r, entry, lap_length_m)
            or _distance_inside_region(r, exit_, lap_length_m)
            for r in result
        )
        if overlaps:
            continue

        result.append(new_region)

    return result


def _distance_inside_region(
    region: tuple[float, float, float, int], distance: float, lap_length_m: float
) -> bool:
    entry, _apex, exit_, _sign = region
    if entry <= exit_:
        return entry <= distance <= exit_
    return distance >= entry or distance <= exit_


def _circular_apex_distance(apex_m: float, mv_dist_m: float, lap_length_m: float) -> float:
    raw = abs(apex_m - mv_dist_m)
    if lap_length_m <= 0:
        return raw
    return min(raw, lap_length_m - raw)


def _tag_regions(
    regions: list[tuple[float, float, float, int]],
    multiviewer_corners: list[dict],
    lap_length_m: float,
) -> list[CornerRegion]:
    """Greedy one-to-one match: each region claims at most one MV corner."""
    unmatched_mv = list(multiviewer_corners)
    assignments: list[Optional[dict]] = [None] * len(regions)

    # Pass 1: regions with one or more MV corners inside.
    for idx, region in enumerate(regions):
        inside = [
            c for c in unmatched_mv
            if _distance_inside_region(region, float(c["distance_m"]), lap_length_m)
        ]
        if inside:
            chosen = min(
                inside,
                key=lambda c: _circular_apex_distance(region[1], float(c["distance_m"]), lap_length_m),
            )
            assignments[idx] = chosen
            unmatched_mv.remove(chosen)

    # Pass 2: regions still without a match — closest unclaimed by circular distance.
    for idx, region in enumerate(regions):
        if assignments[idx] is not None or not unmatched_mv:
            continue
        chosen = min(
            unmatched_mv,
            key=lambda c: _circular_apex_distance(region[1], float(c["distance_m"]), lap_length_m),
        )
        if _circular_apex_distance(region[1], float(chosen["distance_m"]), lap_length_m) <= 250.0:
            assignments[idx] = chosen
            unmatched_mv.remove(chosen)

    tagged: list[CornerRegion] = []
    for region, chosen in zip(regions, assignments):
        entry, apex, exit_, sign = region
        tagged.append(
            CornerRegion(
                corner_number=(chosen.get("number") if chosen else None),
                label_suffix=(chosen.get("letter") or "" if chosen else ""),
                entry_m=entry,
                apex_m=apex,
                exit_m=exit_,
                sign=sign,
            )
        )
    return tagged


class SegmentationOutputError(ValueError):
    """Raised when the segmentation output fails validity checks."""


def _build_and_validate_regions(
    x: np.ndarray,
    y: np.ndarray,
    multiviewer_corners: list[dict],
) -> tuple[list[CornerRegion], float]:
    """Run the full pipeline and validate the result. Returns (regions, lap_length_m)."""
    x_clean, y_clean = _clean_xy(x, y)
    x_u, y_u, s_u, spacing, lap_length = _resample_uniform(x_clean, y_clean, RESAMPLE_SPACING_M)
    kappa = _compute_curvature(x_u, y_u, spacing_m=spacing)
    abs_k = np.abs(kappa)
    kappa_enter = float(np.percentile(abs_k, KAPPA_ENTER_PERCENTILE))
    kappa_exit = float(np.percentile(abs_k, KAPPA_EXIT_PERCENTILE))
    raw_regions = _detect_regions(s_u, kappa, kappa_enter, kappa_exit, lap_length)

    # Post-processing: use official corner positions to fix detection gaps
    if multiviewer_corners:
        raw_regions = _split_merged_regions(raw_regions, multiviewer_corners, s_u, kappa, lap_length)
        raw_regions = _rescue_missing_corners(raw_regions, multiviewer_corners, s_u, kappa, lap_length)

    tagged = _tag_regions(raw_regions, multiviewer_corners, lap_length)

    if not (MIN_LAP_LENGTH_M <= lap_length <= MAX_LAP_LENGTH_M):
        raise SegmentationOutputError(
            f"lap length {lap_length}m outside [{MIN_LAP_LENGTH_M}, {MAX_LAP_LENGTH_M}]"
        )
    if not (MIN_REGIONS <= len(tagged) <= MAX_REGIONS):
        raise SegmentationOutputError(
            f"detected {len(tagged)} regions outside [{MIN_REGIONS}, {MAX_REGIONS}]"
        )
    return tagged, lap_length


def _load_session(year: int, round_number: int):
    """Thin wrapper around fastf1 so tests can patch it."""
    import fastf1
    session = fastf1.get_session(year, round_number, "Q")
    session.load(laps=True, telemetry=True, weather=False, messages=False)
    return session


def _load_multiviewer_corners(session) -> list[dict]:
    rows = []
    for _, row in session.get_circuit_info().corners.iterrows():
        rows.append({
            "number": int(row["Number"]),
            "letter": str(row.get("Letter") or "") or "",
            "distance_m": float(row["Distance"]),
        })
    return rows


def _load_reference_lap_xy(session) -> tuple[np.ndarray, np.ndarray]:
    """Return the fastest lap's X/Y position in meters.

    FastF1 publishes position data in units of decimeters (matching the
    raw F1 timing-feed coordinate system). Divide by 10 so arc-length
    integration matches MultiViewer's corner Distance values, which are
    already in meters.
    """
    lap = session.laps.pick_fastest()
    pos = lap.get_pos_data()
    x = np.asarray(pos["X"], dtype=float) * 0.1
    y = np.asarray(pos["Y"], dtype=float) * 0.1
    return x, y


def _cache_path(year: int, round_number: int) -> str:
    return os.path.join(CACHE_DIR, f"{year}_{round_number}.json")


def _read_cache(
    year: int,
    round_number: int,
    accept_legacy: bool = False,
) -> Optional[tuple[list[CornerRegion], float, list[dict]]]:
    """Read cached regions for a session.

    Returns None on missing/corrupt/invalid cache. When ``accept_legacy``
    is True, an older schema cache (no `multiviewer_corners` field) is
    read in degraded mode with an empty MV list — used as a fallback
    when a v2 rebuild fails.
    """
    path = _cache_path(year, round_number)
    if not os.path.isfile(path):
        return None
    try:
        with open(path) as f:
            raw = json.load(f)
        version = raw.get("schema_version")
        mv: list[dict] = []
        if version != SCHEMA_VERSION:
            if not (accept_legacy and isinstance(version, int) and version >= 1):
                LOGGER.info(
                    "corner_regions cache schema mismatch at %s (%s != %s) — rebuilding",
                    path, version, SCHEMA_VERSION,
                )
                return None
            regions = [CornerRegion(**entry) for entry in raw["regions"]]
            lap_length = float(raw["lap_length_m"])
        else:
            regions = [CornerRegion(**entry) for entry in raw["regions"]]
            lap_length = float(raw["lap_length_m"])
            mv = list(raw["multiviewer_corners"])

        # Re-validate values against the same gates as _write_cache.
        if not (MIN_LAP_LENGTH_M <= lap_length <= MAX_LAP_LENGTH_M):
            LOGGER.warning(
                "corner_regions cache at %s has invalid lap_length=%s — ignoring",
                path, lap_length,
            )
            return None
        tol = max(1e-3, lap_length * 1e-9)
        for r in regions:
            for field in (r.entry_m, r.apex_m, r.exit_m):
                if field < -tol or field > lap_length + tol:
                    LOGGER.warning(
                        "corner_regions cache at %s has out-of-bounds boundary %s — ignoring",
                        path, field,
                    )
                    return None
        if version != SCHEMA_VERSION:
            return regions, lap_length, []
        return regions, lap_length, mv
    except (json.JSONDecodeError, TypeError, KeyError, ValueError) as exc:
        LOGGER.warning("corner_regions cache unreadable at %s: %s", path, exc)
        return None


def _write_cache(
    year: int,
    round_number: int,
    regions: list[CornerRegion],
    lap_length_m: float,
    multiviewer_corners: list[dict],
) -> None:
    tol = max(1e-3, lap_length_m * 1e-9)
    clean_regions: list[CornerRegion] = []
    for r in regions:
        boundaries = []
        for field in (r.entry_m, r.apex_m, r.exit_m):
            if field < -tol or field > lap_length_m + tol:
                raise SegmentationOutputError(
                    f"region boundary {field}m outside [0, {lap_length_m}m] — cache write rejected"
                )
            boundaries.append(min(max(field, 0.0), lap_length_m))
        clean_regions.append(
            CornerRegion(
                corner_number=r.corner_number,
                label_suffix=r.label_suffix,
                entry_m=boundaries[0],
                apex_m=boundaries[1],
                exit_m=boundaries[2],
                sign=r.sign,
            )
        )
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = _cache_path(year, round_number)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "lap_length_m": lap_length_m,
        "multiviewer_corners": multiviewer_corners,
        "regions": [asdict(r) for r in clean_regions],
    }
    with open(path, "w") as f:
        json.dump(payload, f)


_LAP_LENGTH_BY_KEY: dict[tuple[int, int], float] = {}
_MV_BY_KEY: dict[tuple[int, int], list[dict]] = {}


def _require_positive_int(value, name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise SegmentationInputError(f"{name} must be a positive int, got {value!r}")


def get_corner_regions(year: int, round_number: int) -> list[CornerRegion]:
    _require_positive_int(year, "year")
    _require_positive_int(round_number, "round_number")
    key = (year, round_number)
    cached = _read_cache(year, round_number)
    if cached is not None:
        regions, lap_length, mv = cached
        _LAP_LENGTH_BY_KEY[key] = lap_length
        _MV_BY_KEY[key] = mv
        return regions
    # Cache miss or schema mismatch — attempt a fresh build.
    try:
        session = _load_session(year, round_number)
        multiviewer = _load_multiviewer_corners(session)
        x, y = _load_reference_lap_xy(session)
        regions, lap_length = _build_and_validate_regions(x, y, multiviewer)
        _write_cache(year, round_number, regions, lap_length, multiviewer)
        _LAP_LENGTH_BY_KEY[key] = lap_length
        _MV_BY_KEY[key] = multiviewer
        return regions
    except Exception as build_exc:
        LOGGER.warning(
            "corner_regions rebuild failed for year=%s round=%s: %s — trying degraded read",
            year, round_number, build_exc,
        )
        degraded = _read_cache(year, round_number, accept_legacy=True)
        if degraded is not None:
            regions, lap_length, mv = degraded
            _LAP_LENGTH_BY_KEY[key] = lap_length
            _MV_BY_KEY[key] = mv
            return regions
        raise


def _lap_length_for(year: int, round_number: int) -> Optional[float]:
    return _LAP_LENGTH_BY_KEY.get((year, round_number))


def _corner_name(region: CornerRegion) -> Optional[str]:
    if region.corner_number is None:
        return None
    return f"Turn {region.corner_number}{region.label_suffix}"


def _arc_distance_forward(target: float, point_m: float, lap_length_m: float) -> float:
    """Arc length from target moving forward to point_m, with wrap."""
    if lap_length_m <= 0:
        return abs(point_m - target)
    d = point_m - target
    if d < 0:
        d += lap_length_m
    return d


def _arc_distance_backward(target: float, point_m: float, lap_length_m: float) -> float:
    """Arc length from target moving backward to point_m, with wrap."""
    if lap_length_m <= 0:
        return abs(target - point_m)
    d = target - point_m
    if d < 0:
        d += lap_length_m
    return d


def _load_multiviewer_corners_for_resolve(year: int, round_number: int) -> list[dict]:
    """Return MV corners cached in-process. NEVER hits FastF1/network.

    Populated as a side effect of `get_corner_regions` (which is called
    before any resolve). If somehow neither happened, returns an empty
    list — caller treats that as "no fallback available."
    """
    return _MV_BY_KEY.get((year, round_number), [])


def resolve_corner_for_distance(
    year: int, round_number: int, distance_m: float
) -> dict:
    _require_positive_int(year, "year")
    _require_positive_int(round_number, "round_number")
    if distance_m is None or not math.isfinite(float(distance_m)):
        raise SegmentationInputError(
            f"distance_m must be finite, got {distance_m!r}"
        )
    regions = get_corner_regions(year, round_number)
    if not regions:
        return {"corner_number": None, "corner_name": None, "location_label": None}
    lap_length = _lap_length_for(year, round_number) or 0.0
    target = float(distance_m)
    # Normalize into [0, lap_length) so circular arithmetic is safe
    # against floating-point drift or multi-lap distances.
    if lap_length > 0:
        target = target % lap_length

    # Step 1: inside any region?
    for region in regions:
        if _distance_inside_region(
            (region.entry_m, region.apex_m, region.exit_m, region.sign),
            target,
            lap_length,
        ):
            if region.corner_number is not None:
                label = _corner_name(region)
                return {
                    "corner_number": region.corner_number,
                    "corner_name": label,
                    "location_label": label,
                }
            # Untagged region — fall back to nearest MV apex circularly.
            mv = _load_multiviewer_corners_for_resolve(year, round_number)
            if mv:
                chosen = min(
                    mv,
                    key=lambda c: _circular_apex_distance(
                        region.apex_m, float(c["distance_m"]), lap_length
                    ),
                )
                label = f"Turn {chosen['number']}{chosen.get('letter') or ''}"
                return {
                    "corner_number": int(chosen["number"]),
                    "corner_name": label,
                    "location_label": label,
                }
            return {"corner_number": None, "corner_name": None, "location_label": "in corner"}

    # Step 2: straight between regions, with circular bracket lookup.
    prev_region = min(
        regions,
        key=lambda r: _arc_distance_backward(target, r.exit_m, lap_length),
    )
    next_region = min(
        regions,
        key=lambda r: _arc_distance_forward(target, r.entry_m, lap_length),
    )
    prev_name = _corner_name(prev_region)
    next_name = _corner_name(next_region)
    if prev_name and next_name and prev_region is not next_region:
        label = f"{prev_name} → {next_name} straight"
    elif next_name:
        label = f"approach to {next_name}"
    elif prev_name:
        label = f"run out of {prev_name}"
    else:
        label = None
    return {"corner_number": None, "corner_name": None, "location_label": label}
