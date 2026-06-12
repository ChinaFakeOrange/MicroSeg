"""Interactive pixel classification with LightGBM.

Re-implements the original ``training`` / ``d_set`` / ``Pred`` flow as a single
self-contained, serialisable classifier. The user supplies coloured scribbles
(``strokes``); each stroke contributes pixels of one class. We extract dense
features once per image, gather the labelled pixels, fit a LightGBM model with a
feature-importance based feature-selection pass, then predict a full-frame label
map.
"""
from __future__ import annotations

import io
from dataclasses import dataclass
from typing import Dict, List, Sequence

import numpy as np

from .features import FeatureConfig, extract_features, features_to_table, sample_at_points

try:  # LightGBM is optional at import time so the module can be introspected.
    import lightgbm as lgb
except Exception:  # pragma: no cover - exercised only without lightgbm
    lgb = None


@dataclass
class Stroke:
    """A single user scribble: a class id plus a list of ``(x, y)`` points."""

    label: int
    points: Sequence[Sequence[float]]


class InteractiveSegmenter:
    """Few-scribble pixel classifier.

    Example
    -------
    >>> seg = InteractiveSegmenter()
    >>> seg.fit(image, [Stroke(1, [(10, 10), (11, 10)]), Stroke(2, [(80, 80)])])
    >>> labels = seg.predict(image)  # (H, W) uint8 label map
    """

    def __init__(self, config: FeatureConfig | None = None, params: Dict | None = None):
        if lgb is None:
            raise RuntimeError("lightgbm is required for InteractiveSegmenter")
        self.config = config or FeatureConfig()
        self.params = {
            "verbosity": -1,
            "n_estimators": 200,
            "num_leaves": 31,
            "learning_rate": 0.1,
            "n_jobs": -1,
            **(params or {}),
        }
        self.model: "lgb.LGBMClassifier | None" = None
        self.selected_features: np.ndarray | None = None
        self.classes_: List[int] = []

    # ------------------------------------------------------------------ fit
    def fit(self, image: np.ndarray, strokes: Sequence[Stroke]) -> "InteractiveSegmenter":
        return self.fit_multi([(image, strokes)])

    def fit_multi(self, pairs: Sequence[tuple]) -> "InteractiveSegmenter":
        """Fit on labelled pixels gathered from several (image, strokes) pairs.

        This mirrors the original desktop ``MLSeg`` behaviour: every scribble on
        every image contributes training pixels to a single classifier, which is
        then used to label the whole dataset.
        """
        x_parts, y_parts = [], []
        for image, strokes in pairs:
            xs, ys = self._gather(image, strokes)
            if xs is not None:
                x_parts.append(xs)
                y_parts.append(ys)
        if not x_parts:
            raise ValueError("No labelled pixels supplied")
        x = np.concatenate(x_parts, axis=0)
        y = np.concatenate(y_parts, axis=0)
        self._fit_xy(x, y)
        return self

    def _gather(self, image: np.ndarray, strokes: Sequence[Stroke]):
        """Sample the dense feature stack at every scribble pixel of one image."""
        features, _ = extract_features(image, self.config)
        x_parts, y_parts = [], []
        for stroke in strokes:
            pts = np.asarray(stroke.points, dtype=float)
            if pts.size == 0:
                continue
            pts = self._clip_points(pts, image.shape[:2])
            x_parts.append(sample_at_points(features, pts))
            y_parts.append(np.full(len(pts), stroke.label, dtype=np.int64))
        if not x_parts:
            return None, None
        return np.concatenate(x_parts, axis=0), np.concatenate(y_parts, axis=0)

    def _fit_xy(self, x: np.ndarray, y: np.ndarray) -> None:
        self.classes_ = sorted(np.unique(y).tolist())

        # First pass: fit on all features to estimate importances.
        clf = lgb.LGBMClassifier(**self.params)
        clf.fit(x, y)
        importances = clf.feature_importances_
        self.selected_features = importances > 0
        if not self.selected_features.any():  # keep everything if all-zero
            self.selected_features = np.ones_like(importances, dtype=bool)

        # Second pass: refit on the retained subset for a leaner predictor.
        clf = lgb.LGBMClassifier(**self.params)
        clf.fit(x[:, self.selected_features], y)
        self.model = clf


    # -------------------------------------------------------------- predict
    def predict(self, image: np.ndarray) -> np.ndarray:
        if self.model is None or self.selected_features is None:
            raise RuntimeError("Call fit() before predict()")
        features, _ = extract_features(image, self.config)
        _, h, w = features.shape
        table = features_to_table(features)[:, self.selected_features]
        pred = self.model.predict(table)
        return pred.reshape(h, w).astype(np.uint8)

    def predict_proba(self, image: np.ndarray) -> np.ndarray:
        if self.model is None or self.selected_features is None:
            raise RuntimeError("Call fit() before predict()")
        features, _ = extract_features(image, self.config)
        _, h, w = features.shape
        table = features_to_table(features)[:, self.selected_features]
        proba = self.model.predict_proba(table)
        return proba.reshape(h, w, -1).astype(np.float32)

    # ------------------------------------------------------------ serialise
    def dumps(self) -> bytes:
        import joblib

        buf = io.BytesIO()
        joblib.dump(
            {
                "params": self.params,
                "config": self.config,
                "model": self.model,
                "selected_features": self.selected_features,
                "classes_": self.classes_,
            },
            buf,
        )
        return buf.getvalue()

    @classmethod
    def loads(cls, blob: bytes) -> "InteractiveSegmenter":
        import joblib

        state = joblib.load(io.BytesIO(blob))
        obj = cls(config=state["config"], params=state["params"])
        obj.model = state["model"]
        obj.selected_features = state["selected_features"]
        obj.classes_ = state["classes_"]
        return obj

    # ------------------------------------------------------------- helpers
    @staticmethod
    def _clip_points(points: np.ndarray, shape: tuple[int, int]) -> np.ndarray:
        h, w = shape
        points = points.copy()
        points[:, 0] = np.clip(points[:, 0], 0, w - 1)
        points[:, 1] = np.clip(points[:, 1], 0, h - 1)
        return points


# Default palette reused by the frontend overlay (matches the original mapping).
LABEL_PALETTE: Dict[int, tuple[int, int, int]] = {
    0: (230, 126, 34),
    1: (192, 57, 43),
    2: (0, 255, 23),
    3: (41, 128, 185),
    4: (26, 188, 156),
    5: (241, 196, 15),
    6: (250, 128, 114),
    7: (211, 84, 0),
    8: (0, 8, 255),
    9: (155, 89, 182),
}


def colorize(label_map: np.ndarray, palette: Dict[int, tuple[int, int, int]] | None = None) -> np.ndarray:
    """Map an integer label image to an RGB overlay."""
    palette = palette or LABEL_PALETTE
    max_label = int(label_map.max())
    lut = np.zeros((max_label + 1, 3), dtype=np.uint8)
    for k, v in palette.items():
        if k <= max_label:
            lut[k] = v
    return lut[label_map]
