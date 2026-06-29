"""Training-time augmentation — Day2: apply only on train split."""
from __future__ import annotations

import random

import numpy as np
from PIL import Image


def random_flip(image: np.ndarray, mask: np.ndarray, p: float = 0.5) -> tuple[np.ndarray, np.ndarray]:
    if random.random() < p:
        image = np.flip(image, axis=1).copy()
        mask = np.flip(mask, axis=1).copy()
    return image, mask


def random_rotate(image: np.ndarray, mask: np.ndarray, max_angle: float = 10.0, p: float = 0.5) -> tuple[np.ndarray, np.ndarray]:
    if random.random() >= p:
        return image, mask
    angle = random.uniform(-max_angle, max_angle)
    img = Image.fromarray((np.clip(image, 0, 1) * 255).astype(np.uint8)).rotate(angle, resample=Image.Resampling.BILINEAR)
    msk = Image.fromarray((mask > 0).astype(np.uint8) * 255).rotate(angle, resample=Image.Resampling.NEAREST)
    return np.asarray(img, dtype=np.float32) / 255.0, (np.asarray(msk) > 127).astype(np.uint8)


def random_brightness(image: np.ndarray, delta: float = 0.1, p: float = 0.5) -> np.ndarray:
    if random.random() >= p:
        return image
    shift = random.uniform(-delta, delta)
    return np.clip(image.astype(np.float32) + shift, 0.0, 1.0).astype(np.float32)


def augment_pair(image: np.ndarray, mask: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    image, mask = random_flip(image, mask)
    image, mask = random_rotate(image, mask)
    image = random_brightness(image)
    return image, mask
