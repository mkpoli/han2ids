"""Explicit-face glyph rendering for benchmark data preparation."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from fontTools.ttLib import TTFont
from PIL import Image, ImageChops, ImageDraw, ImageFont, ImageOps


class RenderError(ValueError):
    """The specified face or rendering cannot produce a trustworthy image."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


@dataclass
class Face:
    family: str
    path: Path
    index: int
    sha256: str
    cmap: set[int]
    names: dict[str, str | None]
    font: ImageFont.FreeTypeFont

    @classmethod
    def load(cls, family: str, path: Path, index: int, em: int = 256) -> "Face":
        if not family or index < 0:
            raise ValueError("font family must be nonempty and face index nonnegative")
        path = Path(path).resolve(strict=True)
        with TTFont(str(path), fontNumber=index, lazy=True) as tt:
            cmap = {cp for cp, glyph in (tt.getBestCmap() or {}).items() if glyph != ".notdef"}
            names = {
                key: tt["name"].getDebugName(name_id)
                for key, name_id in (("family", 1), ("subfamily", 2), ("full", 4), ("postscript", 6))
            }
        if not cmap:
            raise RenderError(f"no Unicode cmap in {path} face {index}")
        font = ImageFont.truetype(str(path), size=em, index=index, layout_engine=ImageFont.Layout.BASIC)
        return cls(family, path, index, sha256_file(path), cmap, names, font)

    def metadata(self) -> dict:
        return {"family": self.family, "path": str(self.path), "face_index": self.index,
                "sha256": self.sha256, "names": self.names}


def select_face(char: str, candidates: list[Face]) -> Face:
    if len(char) != 1:
        raise RenderError("each source char must be one Unicode code point")
    for face in candidates:
        if ord(char) in face.cmap:
            return face
    raise RenderError(f"no configured face covers U+{ord(char):04X}")


def checked_crop(canvas: Image.Image, box: tuple[int, int, int, int]) -> Image.Image:
    """Crop only if every non-white pixel is inside the crop and canvas boundary."""
    if canvas.mode != "L":
        raise ValueError("canvas must be grayscale")
    ink = ImageOps.invert(canvas)
    bounds = ink.getbbox()
    if bounds is None:
        raise RenderError("glyph produced no visible ink")
    x0, y0, x1, y1 = bounds
    if x0 == 0 or y0 == 0 or x1 == canvas.width or y1 == canvas.height:
        raise RenderError("ink touches oversized canvas boundary; clipping is unresolved")
    l, t, r, b = box
    if l < 0 or t < 0 or r > canvas.width or b > canvas.height or l >= r or t >= b:
        raise RenderError("crop extends beyond oversized canvas")
    crop = canvas.crop(box)
    reconstructed = Image.new("L", canvas.size, 255)
    reconstructed.paste(crop, (l, t))
    if ImageChops.difference(canvas, reconstructed).getbbox() is not None:
        raise RenderError("foreground ink lies outside intended crop")
    return crop


def audit_legacy_crop(face: Face, char: str) -> dict:
    """Measure ink lost by the v0.3 crop, including beyond its 320-pixel canvas."""
    if len(char) != 1 or ord(char) not in face.cmap:
        raise RenderError("character is not covered by the explicitly selected face")
    # Match the original font size, default layout engine, text origin and crop.
    legacy_font = ImageFont.truetype(str(face.path), size=224, index=face.index)
    margin = 1024
    surface = Image.new("L", (320 + 2 * margin, 320 + 2 * margin), 255)
    draw = ImageDraw.Draw(surface)
    origin = (margin + 160, margin + 176)
    metrics = draw.textbbox(origin, char, font=legacy_font, anchor="ms")
    if metrics[0] <= 0 or metrics[1] <= 0 or metrics[2] >= surface.width or metrics[3] >= surface.height:
        raise RenderError("legacy glyph metrics exceed oversized canvas")
    draw.text(origin, char, font=legacy_font, fill=0, anchor="ms")
    bounds = ImageOps.invert(surface).getbbox()
    if bounds is None:
        raise RenderError("legacy glyph produced no visible ink")
    if bounds[0] == 0 or bounds[1] == 0 or bounds[2] == surface.width or bounds[3] == surface.height:
        raise RenderError("legacy ink touches oversized canvas boundary; clipping is unresolved")
    ink = np.asarray(surface) < 255
    left, top, right, bottom = margin + 60, margin, margin + 260, margin + 200
    # Partition the lost pixels: above/below the crop, then left/right within its vertical span.
    counts = {"top": int(np.count_nonzero(ink[:top, :])),
              "bottom": int(np.count_nonzero(ink[bottom:, :])),
              "left": int(np.count_nonzero(ink[top:bottom, :left])),
              "right": int(np.count_nonzero(ink[top:bottom, right:]))}
    inside_old_canvas = int(np.count_nonzero(ink[margin:margin + 320, margin:margin + 320]))
    total = int(np.count_nonzero(ink))
    return {"crop_box": [60, 0, 260, 200], "legacy_canvas": [320, 320],
            "font_size": 224, "ink_bbox": [x - margin for x in bounds],
            "total_ink_pixels": total, "inside_crop_pixels": int(np.count_nonzero(ink[top:bottom, left:right])),
            "outside_crop_pixels": sum(counts.values()), "outside_crop_by_side": counts,
            "outside_legacy_canvas_pixels": total - inside_old_canvas,
            "oversized_canvas_boundary_ink": False}


def render(face: Face, char: str, size: int = 224, padding: int = 12) -> Image.Image:
    """Render actual ink at high resolution, center it, and isotropically resize."""
    if len(char) != 1 or ord(char) not in face.cmap:
        raise RenderError("character is not covered by the explicitly selected face")
    if size <= 0 or padding < 1 or 2 * padding >= size:
        raise ValueError("size must exceed twice the positive padding")
    em = face.font.size
    width = 8 * em
    canvas = Image.new("L", (width, width), 255)
    draw = ImageDraw.Draw(canvas)
    origin = (width // 2, width // 2)
    # Reject unexpectedly large metrics even if the painted pixels happen not to
    # reach the edge of the finite observation surface.
    metrics = draw.textbbox(origin, char, font=face.font, anchor="mm")
    if metrics[0] <= 0 or metrics[1] <= 0 or metrics[2] >= width or metrics[3] >= width:
        raise RenderError("glyph metrics exceed oversized canvas")
    draw.text(origin, char, font=face.font, fill=0, anchor="mm")
    bounds = ImageOps.invert(canvas).getbbox()
    if bounds is None:
        raise RenderError("glyph produced no visible ink")
    l, t, r, b = bounds
    # Choose a square in source pixels with at least the requested output margin.
    side = (max(r - l, b - t) * size + (size - 2 * padding) - 1) // (size - 2 * padding)
    side = max(side, max(r - l, b - t) + 2)
    left = (l + r - side) // 2
    top = (t + b - side) // 2
    crop = checked_crop(canvas, (left, top, left + side, top + side))
    result = crop.resize((size, size), Image.Resampling.LANCZOS)
    # Resampling tails can reach the output boundary despite a padded source crop.
    output_bounds = ImageOps.invert(result).getbbox()
    if output_bounds is None:
        raise RenderError("resampling removed all ink")
    if (output_bounds[0] == 0 or output_bounds[1] == 0
            or output_bounds[2] == size or output_bounds[3] == size):
        raise RenderError("resampled ink touches output boundary; increase padding")
    return result
