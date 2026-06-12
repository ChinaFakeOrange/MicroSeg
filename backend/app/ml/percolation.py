"""Percolation simulation for porous microstructures.

Given a segmented microscope image (a binary *pore* mask, possibly a 3D stack),
this module answers two questions a materials scientist actually cares about:

1. **Does the pore phase percolate?** i.e. is there a connected path of pores
   spanning the sample from one face to the opposite face. Computed with
   connected-component labelling (:func:`spanning_clusters`).

2. **In what order does an invading fluid fill the pores?** Modelled as
   *invasion percolation*: a non-wetting fluid enters from an inlet face and at
   each step invades the accessible pore voxel with the largest throat (lowest
   capillary entry pressure), estimated from the Euclidean distance transform.
   The result is a *time-of-invasion* map that the frontend animates frame by
   frame (:func:`invasion_percolation`).

A classic site-percolation lattice generator is included for teaching/demos
(:func:`site_percolation_lattice`).

Everything is pure numpy / scipy / scikit-image and works for 2D and 3D arrays.
"""
from __future__ import annotations

import heapq
from dataclasses import dataclass
from typing import Dict, List, Tuple

import numpy as np
from scipy import ndimage as ndi


# --------------------------------------------------------------------------- #
# Connectivity / spanning analysis
# --------------------------------------------------------------------------- #
@dataclass
class PercolationReport:
    percolates: bool
    axis: int
    porosity: float
    n_clusters: int
    largest_cluster_fraction: float
    spanning_cluster_fraction: float


def spanning_clusters(mask: np.ndarray, axis: int = 0) -> PercolationReport:
    """Detect whether the pore phase spans the volume along ``axis``.

    Parameters
    ----------
    mask: bool/int array. Non-zero = pore phase.
    axis: the spanning direction (0 by default).
    """
    mask = np.asarray(mask) > 0
    structure = ndi.generate_binary_structure(mask.ndim, 1)
    labels, n = ndi.label(mask, structure=structure)

    inlet = np.unique(labels.take(0, axis=axis))
    outlet = np.unique(labels.take(-1, axis=axis))
    spanning = sorted(set(inlet.tolist()) & set(outlet.tolist()) - {0})

    sizes = np.bincount(labels.ravel())
    total = mask.size
    largest = (sizes[1:].max() / total) if n else 0.0
    spanning_frac = float(sum(sizes[s] for s in spanning)) / total if spanning else 0.0

    return PercolationReport(
        percolates=bool(spanning),
        axis=axis,
        porosity=float(mask.sum()) / total,
        n_clusters=int(n),
        largest_cluster_fraction=float(largest),
        spanning_cluster_fraction=spanning_frac,
    )


# --------------------------------------------------------------------------- #
# Invasion percolation
# --------------------------------------------------------------------------- #
@dataclass
class InvasionResult:
    time_map: np.ndarray          # int array, -1 = never invaded, else invasion step
    n_steps: int
    breakthrough_step: int        # step at which outlet is first reached (-1 if none)
    saturation_curve: List[float]  # invaded pore fraction after each recorded frame
    report: PercolationReport


def _neighbor_offsets(ndim: int) -> List[Tuple[int, ...]]:
    offsets = []
    for d in range(ndim):
        for delta in (-1, 1):
            off = [0] * ndim
            off[d] = delta
            offsets.append(tuple(off))
    return offsets


def invasion_percolation(
    mask: np.ndarray,
    inlet_axis: int = 0,
    inlet_side: str = "low",
    n_frames: int = 120,
) -> InvasionResult:
    """Simulate non-wetting invasion percolation through a pore mask.

    Wider pore throats (large distance-transform value) invade first. Returns a
    ``time_map`` where every invaded pore voxel holds its invasion step; the
    frontend animates by revealing voxels with ``time_map <= t``.

    Parameters
    ----------
    mask: pore phase (non-zero = pore).
    inlet_axis / inlet_side: which face the fluid enters from.
    n_frames: number of evenly spaced points sampled for the saturation curve.
    """
    mask = np.asarray(mask) > 0
    ndim = mask.ndim
    dist = ndi.distance_transform_edt(mask)  # throat width proxy
    time_map = np.full(mask.shape, -1, dtype=np.int32)
    offsets = _neighbor_offsets(ndim)

    # Seed the frontier with inlet-face pores. Heap key = -radius so the widest
    # throat (lowest entry pressure) is popped first; tie-break with a counter.
    heap: List[Tuple[float, int, Tuple[int, ...]]] = []
    counter = 0
    if inlet_side == "low":
        inlet_index, outlet_index = 0, mask.shape[inlet_axis] - 1
    else:
        inlet_index, outlet_index = mask.shape[inlet_axis] - 1, 0
    inlet_slab = mask.take(inlet_index, axis=inlet_axis)
    for coord in zip(*np.nonzero(inlet_slab)):
        full = list(coord)
        full.insert(inlet_axis, inlet_index)
        full = tuple(full)
        heapq.heappush(heap, (-float(dist[full]), counter, full))
        counter += 1

    step = 0
    breakthrough = -1
    in_heap = set(v[2] for v in heap)
    while heap:
        _, _, voxel = heapq.heappop(heap)
        if time_map[voxel] != -1:
            continue
        time_map[voxel] = step
        if voxel[inlet_axis] == outlet_index and breakthrough == -1:
            breakthrough = step
        step += 1
        for off in offsets:
            nb = tuple(v + o for v, o in zip(voxel, off))
            if all(0 <= nb[d] < mask.shape[d] for d in range(ndim)) and mask[nb] and time_map[nb] == -1:
                if nb not in in_heap:
                    heapq.heappush(heap, (-float(dist[nb]), counter, nb))
                    in_heap.add(nb)
                    counter += 1

    total_pore = int(mask.sum())
    saturation: List[float] = []
    if total_pore and step:
        frames = np.linspace(0, step - 1, num=min(n_frames, step), dtype=int)
        invaded = time_map >= 0
        saturation = [
            float(np.count_nonzero(invaded & (time_map <= int(t)))) / total_pore
            for t in frames
        ]

    return InvasionResult(
        time_map=time_map,
        n_steps=step,
        breakthrough_step=breakthrough,
        saturation_curve=saturation,
        report=spanning_clusters(mask, axis=inlet_axis),
    )


# --------------------------------------------------------------------------- #
# Synthetic site percolation (teaching / demo)
# --------------------------------------------------------------------------- #
def site_percolation_lattice(size: int = 128, p: float = 0.59, seed: int | None = None) -> Dict:
    """Generate a 2D site-percolation lattice at occupation probability ``p``.

    ``p_c ~ 0.5927`` for the 2D square lattice; values above it almost surely
    percolate. Returns the occupancy mask plus a spanning report — handy as a
    live demo before applying invasion percolation to a real sample.
    """
    rng = np.random.default_rng(seed)
    occupied = rng.random((size, size)) < p
    report = spanning_clusters(occupied, axis=0)
    return {"mask": occupied, "p": p, "report": report}
