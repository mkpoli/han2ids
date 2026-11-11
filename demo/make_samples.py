"""Render the demo's glyph sheets from IPAmj Mincho.

The font is the one `scripts/fetch_fonts.py` caches; pass `--font` for another Mincho or Song face.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "demo" / "static" / "samples"
CELL = 180
MARGIN = 30
GUTTER = 28
POINT = 152

SHEETS = {
    "sheet-grid.png": ["明曼", "川二"],
    "sheet-row.png": ["疑明謝鬱"],
    "glyph-chuan.png": ["川"],
}


def sheet(rows: list[str], font: ImageFont.FreeTypeFont) -> Image.Image:
    columns = max(len(row) for row in rows)
    width = 2 * MARGIN + columns * CELL + (columns - 1) * GUTTER
    height = 2 * MARGIN + len(rows) * CELL + (len(rows) - 1) * GUTTER
    canvas = Image.new("L", (width, height), 255)
    draw = ImageDraw.Draw(canvas)
    for row, text in enumerate(rows):
        for column, char in enumerate(text):
            left = MARGIN + column * (CELL + GUTTER)
            top = MARGIN + row * (CELL + GUTTER)
            box = draw.textbbox((0, 0), char, font=font)
            x = left + (CELL - (box[2] - box[0])) // 2 - box[0]
            y = top + (CELL - (box[3] - box[1])) // 2 - box[1]
            draw.text((x, y), char, font=font, fill=0)
    return canvas


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="make-samples", description=__doc__)
    parser.add_argument("--font", type=Path, default=ROOT / "cache" / "fonts" / "ipamj" / "ipamjm.ttf")
    parser.add_argument("--out", type=Path, default=TARGET)
    args = parser.parse_args(argv)

    if not args.font.exists():
        parser.error(f"Font not found: {args.font}")
    font = ImageFont.truetype(str(args.font), POINT)
    args.out.mkdir(parents=True, exist_ok=True)

    for name, rows in SHEETS.items():
        picture = sheet(rows, font)
        picture.save(args.out / name, optimize=True)
        print(f"{args.out / name}\t{picture.width} × {picture.height}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
