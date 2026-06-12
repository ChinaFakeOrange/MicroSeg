"""3D volume reconstruction and meshing.

Microscope acquisitions are often z-stacks (serial sections / confocal slices).
This module stacks 2D images or label maps into a volume and produces artifacts
the browser viewer can render:

* :func:`build_volume`     - assemble & optionally downsample a z-stack
* :func:`isosurface_mesh`  - marching-cubes surface for a chosen label/threshold,
                             returned as flat vertex/normal/index arrays ready
                             for a Three.js ``BufferGeometry``
* :func:`slice_planes`     - orthogonal slice images for the 3-plane viewer
* :func:`volume_histogram` - intensity distribution for transfer-function setup

All heavy work stays on the server; the client only receives compact meshes.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Sequence

import numpy as np
from skimage import measure
from scipy import ndimage as ndi


@dataclass
class Volume:
    data: np.ndarray              # (Z, Y, X)
    spacing: tuple[float, float, float] = (1.0, 1.0, 1.0)
    is_labels: bool = False

    @property
    def shape(self) -> tuple[int, int, int]:
        return self.data.shape


def build_volume(
    slices: Sequence[np.ndarray],
    spacing: tuple[float, float, float] = (1.0, 1.0, 1.0),
    is_labels: bool = False,
    downsample: int = 1,
) -> Volume:
    """Stack 2D slices (already aligned, same shape) into a :class:`Volume`."""
    if not slices:
        raise ValueError("No slices supplied")
    arr = np.stack([np.asarray(s) for s in slices], axis=0)
    if arr.ndim == 4:  # RGB slices -> luminance
        arr = arr[..., :3].mean(axis=-1)
    if downsample > 1:
        order = 0 if is_labels else 1
        arr = ndi.zoom(arr, (1, 1 / downsample, 1 / downsample), order=order)
        spacing = (spacing[0], spacing[1] * downsample, spacing[2] * downsample)
    if is_labels:
        arr = arr.astype(np.int32)
    else:
        arr = arr.astype(np.float32)
    return Volume(data=arr, spacing=spacing, is_labels=is_labels)


def isosurface_mesh(
    volume: Volume,
    label: int | None = None,
    threshold: float | None = None,
    step_size: int = 1,
    smooth: bool = True,
) -> Dict:
    """Extract a marching-cubes isosurface.

    For label volumes pass ``label`` (the surface of that class). For intensity
    volumes pass ``threshold`` (defaults to the midpoint). Returns flat arrays:
    ``vertices`` (N*3), ``normals`` (N*3), ``indices`` (M*3), plus ``bounds``.
    """
    data = volume.data
    if volume.is_labels and label is not None:
        field = (data == label).astype(np.float32)
        level = 0.5
    else:
        field = data.astype(np.float32)
        level = threshold if threshold is not None else float((field.max() + field.min()) / 2)

    if smooth:
        field = ndi.gaussian_filter(field, sigma=1.0)

    verts, faces, normals, _ = measure.marching_cubes(
        field, level=level, spacing=volume.spacing, step_size=step_size,
    )
    # Center the mesh so the client can orbit around the origin.
    center = verts.mean(axis=0)
    verts = verts - center

    return {
        "vertices": verts.astype(np.float32).ravel().tolist(),
        "normals": normals.astype(np.float32).ravel().tolist(),
        "indices": faces.astype(np.uint32).ravel().tolist(),
        "vertex_count": int(len(verts)),
        "triangle_count": int(len(faces)),
        "bounds": {
            "min": (verts.min(axis=0)).tolist(),
            "max": (verts.max(axis=0)).tolist(),
        },
    }


def slice_planes(volume: Volume, index: tuple[int, int, int] | None = None) -> Dict[str, np.ndarray]:
    """Return axial/coronal/sagittal slices through ``index`` (defaults: center)."""
    z, y, x = volume.shape
    if index is None:
        index = (z // 2, y // 2, x // 2)
    iz, iy, ix = index
    return {
        "axial": volume.data[iz, :, :],
        "coronal": volume.data[:, iy, :],
        "sagittal": volume.data[:, :, ix],
    }


def volume_histogram(volume: Volume, bins: int = 64) -> Dict[str, List[float]]:
    counts, edges = np.histogram(volume.data.ravel(), bins=bins)
    return {"counts": counts.tolist(), "edges": edges.tolist()}


def label_volume_stats(volume: Volume) -> Dict[int, Dict[str, float]]:
    """Per-label voxel volume (3D analogue of 2D morphometry)."""
    if not volume.is_labels:
        raise ValueError("label_volume_stats requires a label volume")
    voxel_vol = float(np.prod(volume.spacing))
    out: Dict[int, Dict[str, float]] = {}
    for lbl in np.unique(volume.data):
        if lbl == 0:
            continue
        count = int((volume.data == lbl).sum())
        out[int(lbl)] = {"voxels": count, "volume": count * voxel_vol}
    return out
