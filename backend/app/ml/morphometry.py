"""Quantitative particle / pore morphometry.

A hardened re-implementation of the original ``particle_stats``. Given a
segmentation label map (or a binary mask), it labels connected objects, applies
an optional watershed split for touching particles, and reports per-object shape
descriptors using SimpleITK's ``LabelShapeStatisticsImageFilter``.

Descriptors (per object):
  area        - physical size (px^2, or um^2 if ``spacing`` given)
  ed          - equivalent (circular) diameter
  esp         - equivalent spherical perimeter
  perimeter   - measured boundary length
  rugosity    - esp / perimeter  (1.0 = perfectly smooth/round)
  cpc         - measured perimeter (closed-perimeter count)
  centroid_x/y, bbox, elongation, roundness, feret_diameter
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List

import numpy as np

try:
    import SimpleITK as sitk
except Exception:  # pragma: no cover
    sitk = None


@dataclass
class MorphometryConfig:
    spacing: float = 1.0           # physical size of one pixel (e.g. um/px)
    watershed: bool = True         # split touching particles
    watershed_level: float = 0.1
    min_area: float = 0.0          # discard objects smaller than this (post-spacing)
    target_label: int | None = None  # restrict to one class id; None = non-zero


COLUMNS: List[str] = [
    "object", "area", "ed", "esp", "perimeter", "rugosity", "cpc",
    "centroid_x", "centroid_y", "elongation", "roundness", "feret_diameter",
]


@dataclass
class MorphometryResult:
    rows: List[Dict[str, float]] = field(default_factory=list)
    summary: Dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return {"columns": COLUMNS, "rows": self.rows, "summary": self.summary}


def _binary_from_labels(label_map: np.ndarray, target_label: int | None) -> np.ndarray:
    if target_label is None:
        return (label_map > 0).astype(np.uint8)
    return (label_map == target_label).astype(np.uint8)


def analyze(label_map: np.ndarray, config: MorphometryConfig | None = None) -> MorphometryResult:
    """Compute per-object morphometry for a 2D **or 3D** segmentation.

    For 3D volumes ``area`` is the object volume and ``perimeter`` is the surface
    area; an extra ``centroid_z`` column is added.
    """
    if sitk is None:
        raise RuntimeError("SimpleITK is required for morphometry")
    config = config or MorphometryConfig()

    binary = _binary_from_labels(np.asarray(label_map), config.target_label)
    ndim = binary.ndim
    image = sitk.GetImageFromArray(binary)
    image.SetSpacing(tuple([config.spacing] * ndim))

    if config.watershed:
        gradient = sitk.GradientMagnitude(sitk.Cast(image, sitk.sitkFloat32))
        labelled = sitk.MorphologicalWatershed(
            gradient, level=config.watershed_level,
            markWatershedLine=False, fullyConnected=False,
        )
        # Watershed labels the background too; mask it out.
        labelled = sitk.Mask(labelled, image)
    else:
        labelled = sitk.ConnectedComponent(image)

    stats = sitk.LabelShapeStatisticsImageFilter()
    stats.SetComputeFeretDiameter(True)
    stats.Execute(labelled)

    rows: List[Dict[str, float]] = []
    for idx, lbl in enumerate(stats.GetLabels()):
        area = stats.GetPhysicalSize(lbl)        # area (2D) or volume (3D)
        if area < config.min_area:
            continue
        perimeter = stats.GetPerimeter(lbl) * config.spacing
        esp = stats.GetEquivalentSphericalPerimeter(lbl)
        c = stats.GetCentroid(lbl)
        row = {
            "object": idx,
            "area": area,
            "ed": stats.GetEquivalentSphericalRadius(lbl) * 2.0,
            "esp": esp,
            "perimeter": perimeter,
            "rugosity": (esp / perimeter) if perimeter else 0.0,
            "cpc": stats.GetPerimeter(lbl),
            "centroid_x": c[0],
            "centroid_y": c[1] if len(c) > 1 else 0.0,
            "elongation": stats.GetElongation(lbl),
            "roundness": stats.GetRoundness(lbl),
            "feret_diameter": stats.GetFeretDiameter(lbl),
        }
        if ndim >= 3:
            row["centroid_z"] = c[2]
        rows.append(row)

    result = MorphometryResult(rows=rows, summary=_summarize(rows))
    result.summary["ndim"] = ndim
    return result


def _summarize(rows: List[Dict[str, float]]) -> Dict[str, float]:
    if not rows:
        return {"count": 0}
    arr = {k: np.array([r[k] for r in rows], dtype=float) for k in rows[0] if k != "object"}
    summary: Dict[str, float] = {"count": len(rows)}
    for key, values in arr.items():
        summary[f"{key}_mean"] = float(values.mean())
        summary[f"{key}_std"] = float(values.std())
    summary["total_area"] = float(arr["area"].sum())
    return summary


def porosity(label_map: np.ndarray, pore_label: int | None = None) -> float:
    """Area fraction occupied by the pore phase (porosity)."""
    binary = _binary_from_labels(np.asarray(label_map), pore_label)
    return float(binary.sum()) / float(binary.size)
