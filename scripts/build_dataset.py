"""Render a Mincho training set from BabelStone labels.

Each row is one character in one font: (char, IDS, image, font, split). Fonts are checked for the
character first; a missing character simply has no row for that font.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
from pathlib import Path

from fontTools.ttLib import TTFont
from PIL import Image, ImageDraw, ImageFont

SIZE = 224
REGIONS = re.compile(r"\([A-Z]+\)$")
OPERATORS = set("⿰⿱⿲⿳⿴⿵⿶⿷⿸⿹⿺⿻⿼⿽⿾⿿〾㇯")


def labels(path: Path) -> dict[str, str]:
    """First usable IDS for each character."""
    out = {}
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip() or line.startswith("#"):
                continue
            char, rest = line.rstrip("\n").split("\t", 1)
            for candidate in rest.split(" "):
                text = REGIONS.sub("", candidate)
                if text and text[0] in OPERATORS and "{" not in text and "？" not in text and "?" not in text:
                    out[char] = text
                    break
    return out


def split(char: str) -> str:
    n = int(hashlib.sha256(char.encode()).hexdigest()[:8], 16) % 100
    return "val" if n < 5 else "test" if n < 10 else "train"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--labels", type=Path, default=Path("data/babelstone-ids.tsv.gz"))
    parser.add_argument("--out", type=Path, default=Path("build/dataset"))
    parser.add_argument("--noto", type=Path, default=Path("/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc"))
    parser.add_argument("--ipamj", type=Path, default=Path("cache/fonts/ipamj/ipamjm.ttf"))
    parser.add_argument("--jigmo", type=Path, default=Path("cache/fonts/jigmo/Jigmo.ttf"))
    parser.add_argument("--jigmo2", type=Path, default=Path("cache/fonts/jigmo/Jigmo2.ttf"))
    parser.add_argument("--jigmo3", type=Path, default=Path("cache/fonts/jigmo/Jigmo3.ttf"))
    parser.add_argument("--fonts", default="noto,ipamj,jigmo,jigmo2,jigmo3")
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()

    paths = {"noto": (args.noto, 0), "ipamj": (args.ipamj, None), "jigmo": (args.jigmo, None), "jigmo2": (args.jigmo2, None), "jigmo3": (args.jigmo3, None)}
    table = labels(args.labels)
    if args.limit:
        table = dict(list(table.items())[:args.limit])
    cmaps = {}
    for name in args.fonts.split(","):
        path, index = paths[name]
        cmaps[name] = set((TTFont(path, fontNumber=index) if index is not None else TTFont(path)).getBestCmap())

    rows = []
    for name in args.fonts.split(","):
        path, index = paths[name]
        font = ImageFont.truetype(str(path), SIZE, index=index) if index is not None else ImageFont.truetype(str(path), SIZE)
        folder = args.out / "images" / name
        folder.mkdir(parents=True, exist_ok=True)
        for char, ids in table.items():
            if ord(char) not in cmaps[name]:
                continue
            canvas = Image.new("L", (SIZE, SIZE), 255)
            ImageDraw.Draw(canvas).text((SIZE / 2, SIZE / 2), char, font=font, fill=0, anchor="mm")
            image = folder / f"U+{ord(char):04X}.png"
            canvas.save(image)
            rows.append({"char": char, "ids": ids, "image": str(image.relative_to(args.out)), "font": name, "split": split(char)})
    args.out.mkdir(parents=True, exist_ok=True)
    for name in ("train", "val", "test"):
        part = [row for row in rows if row["split"] == name]
        (args.out / f"{name}.jsonl").write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in part))
        print(name, len(part))
    print("rows", len(rows))


if __name__ == "__main__":
    main()
