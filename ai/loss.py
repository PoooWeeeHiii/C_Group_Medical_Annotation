"""Loss: Dice + BCE (Day1 interface, Day4 implementation)."""


def dice_loss(pred, target, smooth: float = 1e-6):
    raise NotImplementedError("Day4: torch Dice loss")


def bce_loss(pred, target):
    raise NotImplementedError("Day4: torch BCE loss")


def combined_loss(pred, target, dice_weight: float = 0.5, bce_weight: float = 0.5):
    raise NotImplementedError("Day4: weighted Dice + BCE")
