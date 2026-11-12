#!/usr/bin/env python3
"""Read every registered ideographic variation sequence with a han2ids checkpoint.

IVD_Sequences.txt lists each registered pair of a base character and a variation selector with its
collection and identifier. Each face given here draws the pairs its cmap carries, ink-fitted with a
12 px margin, and the checkpoint reads them with batched greedy decoding. The output has one line per
drawn pair and face: the base, the selector, the registrations, the reading and its unified form, the
score, and whether the reading equals the reading of the base character alone in that face.

Example:
    python scripts/ivd_sweep.py --sequences cache/ivd/IVD_Sequences-2026-08-03.txt \
        --face jigmo=0=cache/fonts/jigmo/Jigmo.ttf --face ipamj=0=cache/fonts/ipamj/ipamjm.ttf \
        --output build/ivd/sweep.jsonl
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
SIZE, MARGIN = 224, 12
LINE = re.compile(r"^([0-9A-F]+) (E01[0-9A-F]{2}); ([^;]+); (.+)$")


def registrations(path: Path) -> dict[tuple[int, int], list[list[str]]]:
    pairs: dict[tuple[int, int], list[list[str]]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = LINE.match(line)
        if match:
            pairs.setdefault((int(match.group(1), 16), int(match.group(2), 16)), []).append(
                [match.group(3).strip(), match.group(4).strip()])
    return pairs


def frame(font, text: str):
    """The text's ink centred on white with the clean track's margin, or None when nothing is drawn."""
    from PIL import Image, ImageDraw, ImageOps
    canvas = Image.new("L", (448, 448), 255)
    ImageDraw.Draw(canvas).text((224, 300), text, font=font, fill=0, anchor="ms")
    box = ImageOps.invert(canvas).getbbox()
    if not box:
        return None
    part = canvas.crop(box)
    scale = (SIZE - 2 * MARGIN) / max(part.size)
    part = part.resize((max(1, round(part.width * scale)), max(1, round(part.height * scale))), Image.Resampling.LANCZOS)
    out = Image.new("L", (SIZE, SIZE), 255)
    out.paste(part, ((SIZE - part.width) // 2, (SIZE - part.height) // 2))
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sequences", type=Path, required=True, help="IVD_Sequences.txt")
    parser.add_argument("--face", action="append", required=True, help="NAME=INDEX=PATH; repeat a name for more files")
    parser.add_argument("--checkpoint", type=Path, default=ROOT / "models" / "han2ids-v0.5.pt")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--batch-size", type=int, default=64)
    args = parser.parse_args(argv)

    import torch
    from fontTools.ttLib import TTFont
    from PIL import ImageFont
    from han2ids.forms import unify
    from han2ids.grammar import generate
    from han2ids.infer import Han2IDS, tensor

    registered = registrations(args.sequences)
    reader = Han2IDS(args.checkpoint)

    def read(images):
        out = []
        for start in range(0, len(images), args.batch_size):
            batch = torch.stack([tensor(image) for image in images[start:start + args.batch_size]]).to(reader.device)
            with torch.no_grad():
                tokens, scores = generate(reader.model, batch, reader.itos)
            out += [(reader.vocab.decode(row.tolist()), float(score)) for row, score in zip(tokens, scores)]
        return out

    args.output.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    with open(args.output, "w", encoding="utf-8") as out:
        for item in args.face:
            name, index, path = item.split("=", 2)
            table = TTFont(path, fontNumber=int(index))
            font = ImageFont.truetype(path, SIZE, index=int(index), layout_engine=ImageFont.Layout.RAQM)
            pairs = sorted({(base, selector) for sub in table["cmap"].tables if sub.format == 14
                            for selector, entries in sub.uvsDict.items() for base, _ in entries} & set(registered))
            bases = sorted({base for base, _ in pairs})
            plain = {}
            drawn = [(base, frame(font, chr(base))) for base in bases]
            drawn = [(base, image) for base, image in drawn if image is not None]
            for (base, _), (text, _) in zip(drawn, read([image for _, image in drawn])):
                plain[base] = text
            rows = [(pair, frame(font, chr(pair[0]) + chr(pair[1]))) for pair in pairs]
            rows = [(pair, image) for pair, image in rows if image is not None]
            for ((base, selector), _), (text, score) in zip(rows, read([image for _, image in rows])):
                out.write(json.dumps({
                    "base": chr(base), "code": f"U+{base:04X}", "selector": f"U+{selector:X}", "face": name,
                    "registrations": registered[(base, selector)], "ids": text, "unified": unify(text),
                    "score": round(score, 4), "as_base": text == plain.get(base),
                }, ensure_ascii=False) + "\n")
            total += len(rows)
            print(name, Path(path).name, len(rows), flush=True)
    print(f"{args.output}\t{total} readings")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
