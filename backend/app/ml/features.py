"""Multi-scale dense feature extraction for interactive pixel classification.

This is a clean re-implementation of the ``GIS`` feature stack from the original
desktop project. Each pixel is described by a bank of multi-scale filter
responses (intensity, Gaussian, Sobel gradient, Difference-of-Gaussian, local
neighbourhood statistics, Hessian eigenvalues and structure-tensor eigenvalues).
A LightGBM model then learns to map that descriptor to a class label from a few
user scribbles (see :mod:`app.ml.interactive`).

The implementation only depends on numpy / scipy / scikit-image so it runs on CPU
in any environment, including inside the API worker.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

import numpy as np
from scipy import ndimage as ndi
from skimage.feature import hessian_matrix, hessian_matrix_eigvals, structure_tensor, structure_tensor_eigenvalues

# Default scales (sigma in pixels). Kept identical in spirit to the original
# ``kernel_sizes = [1, 2, 4]`` but expressed as Gaussian sigmas.
DEFAULT_SCALES: tuple[int, ...] = (1, 2, 4)


@dataclass
class FeatureConfig:
    """Which feature groups to compute and at what scales."""

    scales: tuple[int, ...] = DEFAULT_SCALES
    intensity: bool = True
    gaussian: bool = True
    sobel: bool = True
    dog: bool = True
    neighbors: bool = True
    hessian: bool = True
    structure_tensor: bool = True
    names: List[str] = field(default_factory=list)


def _as_gray_channels(image: np.ndarray) -> np.ndarray:
    """Return an ``(C, H, W)`` float32 array.

    Grayscale images become a single channel; RGB(A) images keep their first
    three channels so colour information is preserved per channel, matching the
    original behaviour (``arr[:, :, :3]``).
    """
    arr = np.asarray(image)
    if arr.ndim == 2:
        arr = arr[None, ...]
    elif arr.ndim == 3:
        arr = np.moveaxis(arr[:, :, :3], -1, 0)
    else:
        raise ValueError(f"Unsupported image shape {arr.shape!r}")
    return arr.astype(np.float32, copy=False)


def _gaussian(channel: np.ndarray, sigma: float) -> np.ndarray:
    return ndi.gaussian_filter(channel, sigma=sigma)


def _sobel(channel: np.ndarray, sigma: float) -> np.ndarray:
    smooth = ndi.gaussian_filter(channel, sigma=sigma)
    gx = ndi.sobel(smooth, axis=1)
    gy = ndi.sobel(smooth, axis=0)
    return np.hypot(gx, gy)


def _dog(channel: np.ndarray, sigma: float) -> np.ndarray:
    return ndi.gaussian_filter(channel, sigma=sigma) - ndi.gaussian_filter(channel, sigma=sigma * 1.6)


def _neighbors(channel: np.ndarray, sigma: float) -> List[np.ndarray]:
    """Local mean / standard-deviation in a window scaled by ``sigma``."""
    size = int(2 * sigma + 1)
    mean = ndi.uniform_filter(channel, size=size)
    sq = ndi.uniform_filter(channel * channel, size=size)
    std = np.sqrt(np.clip(sq - mean * mean, 0, None))
    return [mean, std]


def _hessian_eigs(channel: np.ndarray, sigma: float) -> List[np.ndarray]:
    h = hessian_matrix(channel, sigma=sigma, order="rc", use_gaussian_derivatives=False)
    eigs = hessian_matrix_eigvals(h)
    return [eigs[0], eigs[1]]


def _structure_eigs(channel: np.ndarray, sigma: float) -> List[np.ndarray]:
    a = structure_tensor(channel, sigma=sigma, order="rc")
    eigs = structure_tensor_eigenvalues(a)
    return [eigs[0], eigs[1]]


def extract_features(image: np.ndarray, config: FeatureConfig | None = None) -> tuple[np.ndarray, List[str]]:
    """Compute the dense feature stack.

    Parameters
    ----------
    image:
        ``(H, W)`` or ``(H, W, 3|4)`` array, any dtype.
    config:
        Feature selection / scales. Defaults to the full stack at scales (1,2,4).

    Returns
    -------
    features:
        ``(F, H, W)`` float32 array where ``F`` is the number of feature maps.
    names:
        Human-readable name for every feature map (length ``F``).
    """
    config = config or FeatureConfig()
    channels = _as_gray_channels(image)
    n_ch = channels.shape[0]

    feature_maps: List[np.ndarray] = []
    names: List[str] = []

    def push(maps: List[np.ndarray] | np.ndarray, label: str) -> None:
        maps = [maps] if isinstance(maps, np.ndarray) else maps
        for j, m in enumerate(maps):
            feature_maps.append(m.astype(np.float32, copy=False))
            suffix = f"_{j}" if len(maps) > 1 else ""
            names.append(label + suffix)

    for c in range(n_ch):
        ch = channels[c]
        ch_tag = f"c{c}"
        if config.intensity:
            push(ch, f"{ch_tag}/intensity")
        for s in config.scales:
            if config.gaussian:
                push(_gaussian(ch, s), f"{ch_tag}/gaussian@{s}")
            if config.sobel:
                push(_sobel(ch, s), f"{ch_tag}/sobel@{s}")
            if config.dog:
                push(_dog(ch, s), f"{ch_tag}/dog@{s}")
            if config.neighbors:
                push(_neighbors(ch, s), f"{ch_tag}/neighbor@{s}")
            if config.hessian:
                push(_hessian_eigs(ch, s), f"{ch_tag}/hessian@{s}")
            if config.structure_tensor:
                push(_structure_eigs(ch, s), f"{ch_tag}/structure@{s}")

    config.names = names
    return np.stack(feature_maps, axis=0), names


def features_to_table(features: np.ndarray) -> np.ndarray:
    """Reshape ``(F, H, W)`` features to an ``(H*W, F)`` sample matrix."""
    f, h, w = features.shape
    return features.reshape(f, h * w).T


def sample_at_points(features: np.ndarray, points: np.ndarray) -> np.ndarray:
    """Sample features at ``points`` given as an ``(N, 2)`` array of ``(x, y)``."""
    xs = points[:, 0].astype(int)
    ys = points[:, 1].astype(int)
    return features[:, ys, xs].T
