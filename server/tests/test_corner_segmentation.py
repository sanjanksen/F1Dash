import json
import math

import numpy as np
import pytest

import corner_segmentation as cs


def test_clean_xy_drops_non_finite():
    x = np.array([0.0, 1.0, np.nan, 3.0, np.inf, 5.0])
    y = np.array([0.0, 1.0, 2.0, 3.0, 4.0, 5.0])
    # Need at least MIN_RAW_SAMPLES to pass — extend with finite values.
    x = np.concatenate([x, np.linspace(6.0, 200.0, 200)])
    y = np.concatenate([y, np.linspace(6.0, 200.0, 200)])
    cx, cy = cs._clean_xy(x, y)
    # NaN at index 2 and inf at index 4 must be dropped from the prefix.
    assert not np.any(np.isnan(cx))
    assert not np.any(np.isinf(cx))


def test_clean_xy_drops_zero_arc_length_duplicates():
    x = np.array([0.0, 1.0, 1.0, 2.0])
    y = np.array([0.0, 0.0, 0.0, 0.0])
    # Pad above MIN_RAW_SAMPLES.
    x = np.concatenate([x, np.linspace(3.0, 200.0, 200)])
    y = np.concatenate([y, np.linspace(0.0, 0.0, 200)])
    cx, cy = cs._clean_xy(x, y)
    # Duplicate (1.0, 0.0) at index 2 must be dropped.
    assert len(cx) == len(x) - 1


def test_clean_xy_raises_when_below_minimum_samples():
    x = np.array([0.0, 1.0, 2.0])
    y = np.array([0.0, 1.0, 2.0])
    with pytest.raises(cs.SegmentationInputError):
        cs._clean_xy(x, y)
