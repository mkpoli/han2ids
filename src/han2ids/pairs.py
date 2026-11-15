"""Score whether two glyph images draw one registered form.

The head reads the reader's patch tokens of both images at once. It is trained on pairs of forms that
variation collections register: one sequence in two fonts, and two sequences of one collection. See
docs/pair-comparison.md for the pairs and the measurements.
"""
from __future__ import annotations

from pathlib import Path

import torch
from torch import nn


def patch_tokens(encoder, pixels: torch.Tensor, taps: tuple[int, ...]) -> torch.Tensor:
    """The normalised patch tokens after each tapped block, side by side."""
    return torch.cat(encoder.get_intermediate_layers(pixels, n=list(taps), norm=True), dim=-1)


class PairHead(nn.Module):
    """A transformer over the tokens of two images; its class token gives the logit of one form."""

    def __init__(self, width: int, taps: tuple[int, ...] = (5, 8, 11), patches: int = 196, dim: int = 256,
                 layers: int = 2, heads: int = 4, dropout: float = 0.1):
        super().__init__()
        self.taps = tuple(taps)
        self.settings = {"width": width, "taps": list(taps), "patches": patches, "dim": dim, "layers": layers,
                         "heads": heads, "dropout": dropout}
        self.project = nn.Sequential(nn.Linear(width * len(taps), dim), nn.LayerNorm(dim))
        self.place = nn.Parameter(torch.zeros(1, patches, dim))
        self.side = nn.Parameter(torch.zeros(2, 1, 1, dim))
        self.start = nn.Parameter(torch.zeros(1, 1, dim))
        block = nn.TransformerEncoderLayer(dim, heads, dim_feedforward=4 * dim, dropout=dropout, activation="gelu",
                                           batch_first=True, norm_first=True)
        self.blocks = nn.TransformerEncoder(block, layers, norm=nn.LayerNorm(dim), enable_nested_tensor=False)
        self.out = nn.Linear(dim, 1)
        for value in (self.place, self.side, self.start):
            nn.init.normal_(value, std=0.02)

    def forward(self, first: torch.Tensor, second: torch.Tensor) -> torch.Tensor:
        """The logit for each pair of token grids, in the order given."""
        first = self.project(first) + self.place + self.side[0]
        second = self.project(second) + self.place + self.side[1]
        joined = torch.cat([self.start.expand(first.size(0), -1, -1), first, second], dim=1)
        return self.out(self.blocks(joined)[:, 0]).squeeze(-1)

    def logit(self, first: torch.Tensor, second: torch.Tensor) -> torch.Tensor:
        """The logit of one form, the same whichever image comes first."""
        return (self(first, second) + self(second, first)) / 2

    def score(self, first: torch.Tensor, second: torch.Tensor) -> torch.Tensor:
        """The probability of one form."""
        return torch.sigmoid(self.logit(first, second))


def load(path: str | Path, device: str = "cpu") -> PairHead:
    payload = torch.load(path, map_location="cpu", weights_only=True)
    settings = dict(payload["settings"])
    head = PairHead(settings.pop("width"), tuple(settings.pop("taps")), **settings)
    head.load_state_dict(payload["head"])
    return head.to(device).eval()
