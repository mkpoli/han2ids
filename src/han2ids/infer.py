"""Load the checkpoint and read an IDS from an image."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import torch
from PIL import Image, ImageOps

from .grammar import generate, generate_beam, valid_ids
from .model import GlyphIDS
from .tokenizer import Vocabulary

SIZE = 224


def _gray(image: Image.Image) -> Image.Image:
    if image.mode in ("LA", "RGBA", "PA"):
        ground = Image.new("RGBA", image.size, (255, 255, 255, 255))
        ground.alpha_composite(image.convert("RGBA"))
        image = ground.convert("L")
    else:
        image = image.convert("L")
    array = np.asarray(image)
    if array.mean() < 127:
        image = ImageOps.invert(image)
    return image


def _fit(glyph: Image.Image, margin: float) -> Image.Image:
    inner = max(1, int(round(SIZE * (1 - 2 * margin))))
    scale = min(inner / glyph.width, inner / glyph.height)
    glyph = glyph.resize((max(1, round(glyph.width * scale)), max(1, round(glyph.height * scale))),
                         Image.Resampling.LANCZOS)
    canvas = Image.new("L", (SIZE, SIZE), 255)
    canvas.paste(glyph, ((SIZE - glyph.width) // 2, (SIZE - glyph.height) // 2))
    return canvas


def variants(image: Image.Image) -> list[tuple[str, Image.Image]]:
    """The em-box reading and three tight-crop readings."""
    base = _gray(image)
    padded = ImageOps.pad(base, (SIZE, SIZE), color=255)
    out = [("em", padded)]
    ink = base.point(lambda value: 0 if value < 220 else 255)
    box = ink.getbbox()
    if box:
        glyph = base.crop(box)
        for margin in (0.03, 0.08, 0.15):
            out.append((f"fit {margin:.2f}", _fit(glyph, margin)))
    return out


def tensor(image: Image.Image) -> torch.Tensor:
    x = torch.from_numpy(np.asarray(image, dtype=np.float32) / 255)
    return x.unsqueeze(0).repeat(3, 1, 1).sub_(0.5).div_(0.5)


@dataclass
class Reading:
    ids: str
    confidence: float
    variant: str
    valid: bool


class Han2IDS:
    def __init__(self, checkpoint: str | Path = "models/han2ids-v0.3.pt", device: str | None = None):
        path = Path(checkpoint)
        if not path.exists():
            raise FileNotFoundError(f"Checkpoint not found: {path}")
        payload = torch.load(path, map_location="cpu", weights_only=False)
        self.itos = payload["itos"]
        self.vocab = Vocabulary(self.itos)
        self.model = GlyphIDS(len(self.itos), payload["args"]["encoder"],
                              max_len=payload["args"].get("max_len", 48))
        self.model.load_state_dict(payload["model"])
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.model.to(self.device).eval()

    @torch.no_grad()
    def read(self, image: Image.Image, tta: bool = True) -> Reading:
        choices = variants(image) if tta else variants(image)[:1]
        readings = []
        for name, picture in choices:
            tokens, confidence = generate(self.model, tensor(picture).unsqueeze(0).to(self.device), self.itos)
            text = self.vocab.decode(tokens[0].tolist())
            readings.append(Reading(text, float(confidence[0]), name, valid_ids(text)))
        best = 0
        if not readings[0].valid:
            valid = [i for i, item in enumerate(readings) if item.valid]
            best = max(valid, key=lambda i: readings[i].confidence) if valid else 0
        else:
            for i in range(1, len(readings)):
                if readings[i].valid and readings[i].confidence > readings[0].confidence + 0.08:
                    best = i
        return readings[best]
    @torch.no_grad()
    def read_topk(self, image: Image.Image, k: int = 3, tta: bool = True) -> list[Reading]:
        choices = variants(image) if tta else variants(image)[:1]
        best = []
        for name, picture in choices:
            readings = generate_beam(self.model, tensor(picture).unsqueeze(0).to(self.device), self.itos, k=k)
            option = [Reading(text, float(score), name, valid_ids(text)) for text, score in readings]
            if not best:
                best = option
            elif name == 'em':
                continue
            elif option and option[0].confidence > best[0].confidence + 0.08 and option[0].valid:
                best = option
        return best

    def read_path(self, path: str | Path, tta: bool = True) -> Reading:
        with Image.open(path) as image:
            return self.read(image, tta=tta)
