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


def test_cumulative_arc_length_for_straight_line():
    x = np.array([0.0, 3.0, 6.0, 9.0])
    y = np.array([0.0, 4.0, 8.0, 12.0])
    s = cs._cumulative_arc_length(x, y)
    assert s == pytest.approx([0.0, 5.0, 10.0, 15.0])


def test_resample_uses_exact_arange_spacing():
    x = np.array([0.0, 7.0, 23.0, 50.0])
    y = np.zeros_like(x)
    xs, ys, s_new, dx, total = cs._resample_uniform(x, y, spacing_m=5.0)
    assert s_new[0] == pytest.approx(0.0)
    assert s_new[-1] <= 50.0
    deltas = np.diff(s_new)
    assert np.all(np.abs(deltas - 5.0) < 1e-9)
    assert dx == pytest.approx(5.0)
    assert total == pytest.approx(50.0)


def test_resample_returns_true_total_when_not_divisible():
    # 11m straight along x-axis with enough samples for cubic interpolation.
    x = np.linspace(0.0, 11.0, 5)
    y = np.zeros_like(x)
    xs, ys, s_new, dx, total = cs._resample_uniform(x, y, spacing_m=4.0)
    # s_new sampled at 0, 4, 8 (last <= 11).
    assert s_new.tolist() == [0.0, 4.0, 8.0]
    assert dx == pytest.approx(4.0)
    # True total length = 11m, not 12m (which would be s_new[-1] + spacing).
    assert total == pytest.approx(11.0)
