"""2D U-Net stub — implement encoder-decoder on Day4."""


class UNet2D:
    def __init__(self, in_channels: int = 1, out_channels: int = 1):
        self.in_channels = in_channels
        self.out_channels = out_channels

    def forward(self, x):
        raise NotImplementedError("Day4: UNet2D.forward")
