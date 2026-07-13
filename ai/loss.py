"""Segmentation losses for platform U-Net."""
from __future__ import annotations

import torch
import torch.nn.functional as F


def dice_loss(logits: torch.Tensor, target: torch.Tensor, *, num_classes: int | None = None, eps: float = 1e-6) -> torch.Tensor:
    """Multi-class soft Dice on logits (N,C,H,W) vs target class indices (N,H,W)."""
    if logits.ndim != 4:
        raise ValueError("logits must be NCHW")
    if num_classes is None:
        num_classes = int(logits.shape[1])
    probs = torch.softmax(logits, dim=1)
    if target.ndim == 4 and target.shape[1] == 1:
        target = target[:, 0]
    target = target.long()
    one_hot = F.one_hot(target.clamp(min=0, max=num_classes - 1), num_classes=num_classes)
    one_hot = one_hot.permute(0, 3, 1, 2).float()
    dims = (0, 2, 3)
    intersection = torch.sum(probs * one_hot, dims)
    cardinality = torch.sum(probs + one_hot, dims)
    dice = (2.0 * intersection + eps) / (cardinality + eps)
    # Skip background channel in mean when possible.
    if num_classes > 1:
        return 1.0 - dice[1:].mean()
    return 1.0 - dice.mean()


def bce_loss(logits: torch.Tensor, target: torch.Tensor) -> torch.Tensor:
    """Binary case: logits (N,1,H,W) or (N,2,H,W); target (N,H,W) with {0,1}."""
    if logits.shape[1] == 1:
        tgt = target.float()
        if tgt.ndim == 3:
            tgt = tgt.unsqueeze(1)
        return F.binary_cross_entropy_with_logits(logits, tgt)
    # Use CE for 2-class
    return F.cross_entropy(logits, target.long())


def combined_loss(
    logits: torch.Tensor,
    target: torch.Tensor,
    *,
    dice_weight: float = 0.5,
    ce_weight: float = 0.5,
) -> torch.Tensor:
    ce = F.cross_entropy(logits, target.long())
    dsc = dice_loss(logits, target)
    return ce_weight * ce + dice_weight * dsc
