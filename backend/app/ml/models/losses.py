"""Segmentation losses.

Ported from the original project, but rewritten to be **fully differentiable**.
The original ``DiceLoss`` computed a hard (argmax-style) dice with numpy, which
breaks autograd; here we use the standard soft-dice over softmax probabilities.
``GDL`` (generalised dice) and ``FocalTverskyLoss`` are preserved, and a combined
:class:`ComboLoss` mirrors the old ``criteria`` (CE + region term).
"""
from __future__ import annotations

import torch
import torch.nn as nn
import torch.nn.functional as F


def _to_one_hot(target: torch.Tensor, num_classes: int) -> torch.Tensor:
    """``(B, H, W)`` int labels -> ``(B, C, H, W)`` one-hot float."""
    if target.dim() == 4 and target.shape[1] == num_classes:
        return target.float()
    return F.one_hot(target.long(), num_classes).permute(0, 3, 1, 2).float()


class SoftDiceLoss(nn.Module):
    """Soft multi-class dice loss (mean over foreground classes)."""

    def __init__(self, ignore_background: bool = True, eps: float = 1e-6):
        super().__init__()
        self.ignore_background = ignore_background
        self.eps = eps

    def forward(self, logits: torch.Tensor, target: torch.Tensor) -> torch.Tensor:
        num_classes = logits.shape[1]
        probs = F.softmax(logits, dim=1)
        onehot = _to_one_hot(target, num_classes)
        start = 1 if self.ignore_background and num_classes > 1 else 0
        dims = (0, 2, 3)
        inter = (probs[:, start:] * onehot[:, start:]).sum(dims)
        union = probs[:, start:].sum(dims) + onehot[:, start:].sum(dims)
        dice = (2 * inter + self.eps) / (union + self.eps)
        return 1 - dice.mean()


class GeneralizedDiceLoss(nn.Module):
    """Generalised dice loss with inverse-square frequency weighting (GDL)."""

    def __init__(self, eps: float = 1e-6):
        super().__init__()
        self.eps = eps

    def forward(self, logits: torch.Tensor, target: torch.Tensor) -> torch.Tensor:
        num_classes = logits.shape[1]
        probs = F.softmax(logits, dim=1)
        onehot = _to_one_hot(target, num_classes)
        weights = 1.0 / (onehot.sum(dim=(0, 2, 3)) ** 2 + self.eps)
        inter = (weights * (probs * onehot).sum(dim=(0, 2, 3))).sum()
        union = (weights * (probs + onehot).sum(dim=(0, 2, 3))).sum()
        return 1 - (2.0 * inter) / (union + self.eps)


class FocalTverskyLoss(nn.Module):
    """Focal-Tversky loss; alpha penalises FP, beta penalises FN."""

    def __init__(self, alpha: float = 0.7, beta: float = 0.3, gamma: float = 1.33, eps: float = 1e-7):
        super().__init__()
        self.alpha, self.beta, self.gamma, self.eps = alpha, beta, gamma, eps

    def forward(self, logits: torch.Tensor, target: torch.Tensor) -> torch.Tensor:
        num_classes = logits.shape[1]
        probs = F.softmax(logits, dim=1)
        onehot = _to_one_hot(target, num_classes)
        start = 1 if num_classes > 1 else 0
        p = probs[:, start:].reshape(-1)
        t = onehot[:, start:].reshape(-1)
        tp = (p * t).sum()
        fp = ((1 - t) * p).sum()
        fn = (t * (1 - p)).sum()
        tversky = (tp + self.eps) / (tp + self.alpha * fp + self.beta * fn + self.eps)
        return (1 - tversky) ** self.gamma


class ComboLoss(nn.Module):
    """Weighted sum of cross-entropy and a region loss (default: soft dice).

    Replaces the old ``criteria`` while remaining differentiable end-to-end.
    """

    def __init__(self, ce_weight: float = 0.5, region: nn.Module | None = None,
                 class_weights: torch.Tensor | None = None):
        super().__init__()
        self.ce = nn.CrossEntropyLoss(weight=class_weights)
        self.region = region or SoftDiceLoss()
        self.ce_weight = ce_weight

    def forward(self, logits: torch.Tensor, target: torch.Tensor) -> torch.Tensor:
        ce_target = target.argmax(1) if target.dim() == 4 else target.long()
        return self.ce_weight * self.ce(logits, ce_target) + (1 - self.ce_weight) * self.region(logits, target)


@torch.no_grad()
def dice_score(logits: torch.Tensor, target: torch.Tensor, eps: float = 1e-6) -> float:
    """Hard dice metric for monitoring (mean over foreground classes)."""
    num_classes = logits.shape[1]
    pred = logits.argmax(1)
    scores = []
    for c in range(1, num_classes):
        p = pred == c
        t = (target.argmax(1) if target.dim() == 4 else target) == c
        inter = (p & t).sum().float()
        union = p.sum().float() + t.sum().float()
        scores.append(((2 * inter + eps) / (union + eps)).item())
    return float(sum(scores) / len(scores)) if scores else 0.0


LOSS_REGISTRY = {
    "dice": SoftDiceLoss,
    "gdl": GeneralizedDiceLoss,
    "focal_tversky": FocalTverskyLoss,
    "combo": ComboLoss,
}
