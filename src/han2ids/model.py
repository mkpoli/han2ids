"""The encoder-decoder used by han2ids."""
from __future__ import annotations

import math

import timm
import torch
from torch import nn


class GlyphIDS(nn.Module):
    """ViT encoder and a character-level transformer decoder."""

    def __init__(self, vocab_size: int, encoder_name: str, d_model: int = 384, layers: int = 4,
                 heads: int = 6, max_len: int = 48, dropout: float = 0.1,
                 pretrained: bool = False):
        super().__init__()
        self.encoder = timm.create_model(encoder_name, pretrained=pretrained, num_classes=0)
        enc_dim = self.encoder.num_features
        self.memory_proj = nn.Linear(enc_dim, d_model) if enc_dim != d_model else nn.Identity()
        self.tok = nn.Embedding(vocab_size, d_model, padding_idx=0)
        self.pos = nn.Embedding(max_len, d_model)
        layer = nn.TransformerDecoderLayer(
            d_model, heads, dim_feedforward=4 * d_model, dropout=dropout,
            activation="gelu", batch_first=True, norm_first=True,
        )
        self.decoder = nn.TransformerDecoder(layer, layers, norm=nn.LayerNorm(d_model))
        self.head = nn.Linear(d_model, vocab_size)
        self.head.weight = self.tok.weight
        self.d_model, self.max_len = d_model, max_len

    def forward(self, images: torch.Tensor, tokens: torch.Tensor) -> torch.Tensor:
        memory = self.encoder.forward_features(images)
        if memory.dim() == 4:
            memory = memory.flatten(2).transpose(1, 2)
        memory = self.memory_proj(memory)
        length = tokens.size(1)
        target = self.tok(tokens) * math.sqrt(self.d_model)
        target = target + self.pos(torch.arange(length, device=tokens.device))[None]
        causal = torch.triu(torch.full((length, length), float("-inf"), device=tokens.device), 1)
        out = self.decoder(target, memory, tgt_mask=causal, tgt_key_padding_mask=tokens.eq(0))
        return self.head(out)
