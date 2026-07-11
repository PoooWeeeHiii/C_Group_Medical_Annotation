"""Loss: Dice + BCE — Day4."""
from __future__ import annotations

import torch
import torch.nn.functional as F

from ai.config import LOSS_BCE_WEIGHT, LOSS_DICE_WEIGHT


def dice_loss(pred: torch.Tensor, target: torch.Tensor, smooth: float = 1e-6) -> torch.Tensor:
    prob = torch.sigmoid(pred)
    prob = prob.reshape(prob.size(0), -1)
    target = target.reshape(target.size(0), -1)
    inter = (prob * target).sum(dim=1)
    denom = prob.sum(dim=1) + target.sum(dim=1)
    dice = (2 * inter + smooth) / (denom + smooth)
    return 1.0 - dice.mean()


def bce_loss(pred: torch.Tensor, target: torch.Tensor) -> torch.Tensor:
    positive = target.sum()
    negative = target.numel() - positive
    pos_weight = torch.clamp(negative / (positive + 1e-6), min=1.0, max=50.0)
    return F.binary_cross_entropy_with_logits(pred, target, pos_weight=pos_weight)


def combined_loss(
    pred: torch.Tensor,
    target: torch.Tensor,
    dice_weight: float = LOSS_DICE_WEIGHT,
    bce_weight: float = LOSS_BCE_WEIGHT,
) -> torch.Tensor:
    return dice_weight * dice_loss(pred, target) + bce_weight * bce_loss(pred, target)
