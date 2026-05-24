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

SCHEMA_VERSION = 2

CACHE_DIR = os.path.join(os.path.dirname(__file__), "cache", "corner_regions")

KAPPA_ENTER_PERCENTILE = 70.0
KAPPA_EXIT_PERCENTILE = 50.0

RESAMPLE_SPACING_M = 2.0

SAVGOL_WINDOW = 21
SAVGOL_POLY = 3

MIN_RAW_SAMPLES = 100

MIN_REGION_WIDTH_M = 20.0

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


def get_corner_regions(year: int, round_number: int) -> list[CornerRegion]:
    raise NotImplementedError


def resolve_corner_for_distance(
    year: int, round_number: int, distance_m: float
) -> dict:
    raise NotImplementedError
