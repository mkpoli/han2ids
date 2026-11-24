"""Load the checkpoint and read an IDS from an image."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import torch
from PIL import Image, ImageOps

from .forms import unify
from .grammar import generate, generate_beam_batch, valid_ids
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
    # getbbox bounds the nonzero pixels, so the ink is the nonzero class.
    ink = base.point(lambda value: 255 if value < 220 else 0)
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

    @property
    def unified(self) -> str:
        return unify(self.ids)


class Han2IDS:
    def __init__(self, checkpoint: str | Path = "models/han2ids-v0.5.pt", device: str | None = None):
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
    def read(self, image: Image.Image, tta: bool = True, beam_size: int = 5) -> Reading:
        readings = self.read_topk(image, k=beam_size, tta=tta)
        if not readings:
            choices = variants(image)
            label = "em+fit 0.08" if tta and any(name == "fit 0.08" for name, _ in choices[1:]) else "em"
            return Reading("", 0.0, label, False)
        return readings[0]

    @torch.no_grad()
    def read_greedy(self, image: Image.Image, tta: bool = True) -> Reading:
        choices = variants(image) if tta else variants(image)[:1]
        batch = torch.stack([tensor(picture) for _, picture in choices]).to(self.device)
        tokens, confidence = generate(self.model, batch, self.itos)
        readings = [
            Reading(text, float(confidence[i]), name, valid_ids(text))
            for i, ((name, _), row) in enumerate(zip(choices, tokens))
            for text in (self.vocab.decode(row.tolist()),)
        ]
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
        choices = variants(image)
        if tta:
            selected = [choices[0]] + [item for item in choices[1:] if item[0] == "fit 0.08"]
            if len(selected) == 1 and len(choices) > 1:
                selected.append(choices[1])
        else:
            selected = choices[:1]
        label = "+".join(name for name, _ in selected)
        views = [tensor(picture).unsqueeze(0).to(self.device) for _, picture in selected]
        readings = generate_beam_batch(self.model, views, self.itos, k=k, merge=True)[0]
        return [Reading(text, float(score), label, valid_ids(text)) for text, score in readings]

    @torch.no_grad()
    def read_batch(self, images: list[Image.Image], k: int = 5, tta: bool = True) -> list[list[Reading]]:
        if not images:
            return []
        if not tta:
            batch = torch.stack([tensor(variants(image)[0][1]) for image in images]).to(self.device)
            grouped = generate_beam_batch(self.model, batch, self.itos, k=k, merge=True)
            return [[Reading(text, float(score), "em", valid_ids(text)) for text, score in items]
                    for items in grouped]
        em_tensors, fit_tensors, labels = [], [], []
        for image in images:
            choices = variants(image)
            em_tensors.append(tensor(choices[0][1]))
            fit = next((picture for name, picture in choices[1:] if name == "fit 0.08"), None)
            if fit is None:
                fit_tensors.append(tensor(choices[0][1]))
                labels.append("em")
            else:
                fit_tensors.append(tensor(fit))
                labels.append("em+fit 0.08")
        views = [torch.stack(em_tensors).to(self.device), torch.stack(fit_tensors).to(self.device)]
        grouped = generate_beam_batch(self.model, views, self.itos, k=k, merge=True)
        return [[Reading(text, float(score), label, valid_ids(text)) for text, score in items]
                for label, items in zip(labels, grouped)]

    def read_path(self, path: str | Path, tta: bool = True) -> Reading:
        with Image.open(path) as image:
            return self.read(image, tta=tta)
