"""Evaluation metrics — Day8 implement Dice/IoU."""
from __future__ import annotations

import numpy as np


def dice_score(pred: np.ndarray, target: np.ndarray, smooth: float = 1e-6) -> float:
    pred = (pred > 0).astype(np.uint8)
    target = (target > 0).astype(np.uint8)
    inter = (pred & target).sum()
    return float((2 * inter + smooth) / (pred.sum() + target.sum() + smooth))


def iou_score(pred: np.ndarray, target: np.ndarray, smooth: float = 1e-6) -> float:
    pred = (pred > 0).astype(np.uint8)
    target = (target > 0).astype(np.uint8)
    inter = (pred & target).sum()
    union = (pred | target).sum()
    return float((inter + smooth) / (union + smooth))
