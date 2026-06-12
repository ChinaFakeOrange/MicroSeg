"""Tests for the pure-numpy algorithm modules.

These cover the scientific core that does **not** require torch / a GPU:
multi-scale feature extraction, the LightGBM interactive segmenter, particle
morphometry, percolation analysis and 3D volume meshing. They are designed to
run in CI on a plain CPU image.
"""
from __future__ import annotations

import numpy as np
import pytest

from app.ml.features import FeatureConfig, extract_features, features_to_table
from app.ml.interactive import InteractiveSegmenter, Stroke, colorize
from app.ml.morphometry import MorphometryConfig, analyze, porosity
from app.ml.percolation import invasion_percolation, spanning_clusters
from app.ml.volume import build_volume, isosurface_mesh, volume_histogram


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture
def two_blobs() -> np.ndarray:
    """A grey image with two bright blobs on a dark background.

    Low-amplitude noise keeps the task realistic but cleanly separable so the
    learnability assertions below are deterministic.
    """
    rng = np.random.default_rng(0)
    img = (30 + rng.random((96, 96)) * 15).astype(np.uint8)  # dark, faint texture
    yy, xx = np.ogrid[:96, :96]
    img[(yy - 28) ** 2 + (xx - 28) ** 2 < 120] = 210
    img[(yy - 68) ** 2 + (xx - 68) ** 2 < 260] = 205
    return img


def _dense_fg_bg_strokes():
    """Foreground strokes through both blobs, background strokes on a grid."""
    fg = Stroke(label=1, points=[(28 + d, 28) for d in range(-3, 4)]
                + [(68 + d, 68) for d in range(-3, 4)])
    bg_pts = [
        (c, r)
        for r in range(4, 96, 10)
        for c in range(4, 96, 10)
        if (r - 28) ** 2 + (c - 28) ** 2 > 200 and (r - 68) ** 2 + (c - 68) ** 2 > 360
    ]
    bg = Stroke(label=0, points=bg_pts)
    return fg, bg


@pytest.fixture
def two_disks_labels() -> np.ndarray:
    img = np.zeros((100, 100), np.int32)
    yy, xx = np.ogrid[:100, :100]
    img[(yy - 30) ** 2 + (xx - 30) ** 2 < 100] = 1
    img[(yy - 70) ** 2 + (xx - 70) ** 2 < 225] = 1
    return img


# --------------------------------------------------------------------------- #
# Features
# --------------------------------------------------------------------------- #
def test_extract_features_shape_and_names(two_blobs):
    feats, names = extract_features(two_blobs, FeatureConfig(scales=(1, 2, 4)))
    assert feats.ndim == 3
    assert feats.shape[1:] == two_blobs.shape
    assert feats.shape[0] == len(names)
    assert feats.shape[0] > 10  # a rich multi-scale stack
    assert np.isfinite(feats).all()


def test_features_to_table_roundtrip(two_blobs):
    feats, names = extract_features(two_blobs, FeatureConfig(scales=(1, 2)))
    table = features_to_table(feats)
    assert table.shape == (two_blobs.size, feats.shape[0])
    assert table.shape[1] == len(names)


# --------------------------------------------------------------------------- #
# Interactive segmentation
# --------------------------------------------------------------------------- #
def test_interactive_segmenter_learns_blobs(two_blobs):
    fg, bg = _dense_fg_bg_strokes()
    seg = InteractiveSegmenter(FeatureConfig(scales=(1, 2)))
    seg.fit(two_blobs, [fg, bg])
    pred = seg.predict(two_blobs)
    assert pred.shape == two_blobs.shape

    # The blob centres should be foreground, a far corner background.
    assert pred[28, 28] == 1
    assert pred[68, 68] == 1
    assert pred[2, 2] == 0

    # And the learned mask should overlap the ground-truth blobs well.
    yy, xx = np.ogrid[:96, :96]
    gt = ((yy - 28) ** 2 + (xx - 28) ** 2 < 120) | ((yy - 68) ** 2 + (xx - 68) ** 2 < 260)
    inter = ((pred == 1) & gt).sum()
    union = ((pred == 1) | gt).sum()
    assert inter / union > 0.6


def test_interactive_segmenter_serialization_roundtrip(two_blobs):
    fg, bg = _dense_fg_bg_strokes()
    seg = InteractiveSegmenter(FeatureConfig(scales=(1, 2)))
    seg.fit(two_blobs, [fg, bg])
    blob = seg.dumps()
    assert isinstance(blob, (bytes, bytearray))

    restored = InteractiveSegmenter.loads(blob)
    np.testing.assert_array_equal(restored.predict(two_blobs), seg.predict(two_blobs))


def test_colorize_produces_rgb():
    labels = np.array([[0, 1], [2, 3]], np.int32)
    rgb = colorize(labels)
    assert rgb.shape == (2, 2, 3)
    assert rgb.dtype == np.uint8


# --------------------------------------------------------------------------- #
# Morphometry
# --------------------------------------------------------------------------- #
def test_morphometry_counts_two_objects(two_disks_labels):
    res = analyze(two_disks_labels, MorphometryConfig(watershed=False))
    assert res.summary["count"] == 2
    assert len(res.rows) == 2
    # Larger disk (r=15 -> area ~707) bigger than smaller (r=10 -> area ~314).
    areas = sorted(r["area"] for r in res.rows)
    assert areas[0] < areas[1]
    assert res.summary["total_area"] == pytest.approx(sum(areas))


def test_morphometry_row_schema(two_disks_labels):
    res = analyze(two_disks_labels, MorphometryConfig(watershed=False))
    expected = {
        "object", "area", "ed", "esp", "perimeter", "rugosity", "cpc",
        "centroid_x", "centroid_y", "elongation", "roundness", "feret_diameter",
    }
    assert expected.issubset(res.rows[0].keys())
    # A near-circular disk has rugosity ~1 and roundness ~1.
    assert res.rows[0]["rugosity"] == pytest.approx(1.0, abs=0.1)


def test_porosity_fraction():
    vol = np.ones((10, 10), np.int32)
    vol[:5, :] = 0  # half pores
    assert porosity(vol, pore_label=0) == pytest.approx(0.5)


# --------------------------------------------------------------------------- #
# Percolation
# --------------------------------------------------------------------------- #
def test_spanning_below_threshold_does_not_percolate():
    rng = np.random.default_rng(0)
    rep = spanning_clusters(rng.random((80, 80)) < 0.45)
    assert rep.percolates is False
    assert rep.largest_cluster_fraction < 0.2


def test_spanning_above_threshold_percolates():
    rng = np.random.default_rng(0)
    rep = spanning_clusters(rng.random((80, 80)) < 0.70)
    assert rep.percolates is True
    assert rep.largest_cluster_fraction > 0.4


def test_invasion_percolation_saturates_and_is_monotonic():
    medium = np.ones((40, 40), bool)
    res = invasion_percolation(medium, inlet_axis=0, inlet_side="low")
    sat = res.saturation_curve
    assert sat[-1] == pytest.approx(1.0, abs=1e-6)
    assert all(b >= a - 1e-9 for a, b in zip(sat, sat[1:]))  # monotonic
    assert res.breakthrough_step is not None
    # time_map: -1 = never invaded, otherwise an ordering >= 0.
    assert res.time_map.min() >= -1
    assert res.time_map.max() >= 0


def test_invasion_percolation_blocked_medium_never_breaks_through():
    medium = np.ones((30, 30), bool)
    medium[15, :] = False  # an impermeable wall across the middle
    res = invasion_percolation(medium, inlet_axis=0, inlet_side="low")
    # Fluid cannot cross the wall, so final saturation stays well below 1.
    assert res.saturation_curve[-1] < 0.95


# --------------------------------------------------------------------------- #
# 3D volume
# --------------------------------------------------------------------------- #
def test_build_volume_and_mesh():
    slices = [
        (np.random.default_rng(i).random((48, 48)) * 255).astype(np.uint8)
        for i in range(16)
    ]
    vol = build_volume(slices)
    assert vol.data.shape[0] == 16

    mesh = isosurface_mesh(vol, threshold=128)
    assert mesh["vertex_count"] > 0
    assert mesh["triangle_count"] > 0
    # Flat buffers for Three.js BufferGeometry: 3 floats per vertex.
    assert len(mesh["vertices"]) == mesh["vertex_count"] * 3
    assert len(mesh["normals"]) == mesh["vertex_count"] * 3
    assert len(mesh["indices"]) == mesh["triangle_count"] * 3
    assert set(mesh["bounds"]) == {"min", "max"}


def test_volume_histogram_sums_to_voxel_count():
    slices = [np.full((20, 20), v, np.uint8) for v in (10, 50, 200)]
    vol = build_volume(slices)
    hist = volume_histogram(vol, bins=16)
    assert sum(hist["counts"]) == vol.data.size
