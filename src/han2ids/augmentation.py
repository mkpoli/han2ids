"""Random, ink-preserving augmentations for glyph images."""
from __future__ import annotations

import random

from PIL import Image, ImageFilter, ImageOps


SIZE = 224


def _grayscale(image: Image.Image) -> Image.Image:
    """Composite transparency over white before converting to grayscale."""
    if image.mode in ("RGBA", "LA", "PA") or "transparency" in image.info:
        rgba = image.convert("RGBA")
        background = Image.new("RGBA", image.size, "white")
        background.alpha_composite(rgba)
        return background.convert("L")
    return image.convert("L")


def augment(image: Image.Image, rng: random.Random) -> Image.Image:
    """Fit a randomly cropped glyph on a 224px canvas and mildly degrade it.

    Images are assumed to have dark ink on a white background. The crop always
    includes every non-white pixel; extra original whitespace, output margin,
    and placement within 8% of the canvas center are sampled with the RNG.
    """
    gray = _grayscale(image)
    box = ImageOps.invert(gray).getbbox()
    if box is None:
        return Image.new("L", (SIZE, SIZE), 255)

    left, top, right, bottom = box
    # Retain a random amount of the original whitespace around the ink.
    crop = (
        rng.randint(0, left),
        rng.randint(0, top),
        rng.randint(right, gray.width),
        rng.randint(bottom, gray.height),
    )
    glyph = gray.crop(crop)
    margin = rng.uniform(0.0, 0.2)
    # Two extra pixels accommodate blur while preserving a three-pixel border.
    padding = 5
    inner = min(SIZE - 2 * padding, max(1, round(SIZE * (1 - 2 * margin))))
    scale = min(inner / glyph.width, inner / glyph.height)
    width = max(1, min(inner, round(glyph.width * scale)))
    height = max(1, min(inner, round(glyph.height * scale)))
    glyph = glyph.resize((width, height), Image.Resampling.LANCZOS)

    max_shift = round(SIZE * 0.08)

    def offset(length: int) -> int:
        center = (SIZE - length) // 2
        return rng.randint(max(padding, center - max_shift),
                           min(SIZE - padding - length, center + max_shift))

    x = offset(width)
    y = offset(height)
    result = Image.new("L", (SIZE, SIZE), 255)
    result.paste(glyph, (x, y))

    if rng.random() < 0.5:
        result = result.filter(ImageFilter.GaussianBlur(rng.uniform(0.15, 0.5)))
    if rng.random() < 0.5:
        strength = rng.uniform(0.85, 1.0)
        result = result.point(lambda value: round(255 - (255 - value) * strength))
    return result
