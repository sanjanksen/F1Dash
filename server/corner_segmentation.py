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


def get_corner_regions(year: int, round_number: int) -> list[CornerRegion]:
    raise NotImplementedError


def resolve_corner_for_distance(
    year: int, round_number: int, distance_m: float
) -> dict:
    raise NotImplementedError
