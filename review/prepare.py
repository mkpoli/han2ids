#!/usr/bin/env python3
"""Build the review desk's decks: glyphs to describe, each with the model's suggestions.

`read` runs a checkpoint over a folder of glyph images and writes its three best readings per image.
`decks` joins those readings and a benchmark run into build/review/decks.json, which the desk serves.
Image paths in that file are absolute and stay on this machine.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
OUT = ROOT / "build" / "review"


def strip_frame(image, band=0.08, cover=0.55):
    """Whiten the rules of a table cell: long dark rows and columns hugging the image edge."""
    import numpy as np
    from PIL import Image
    pixels = np.asarray(image).copy()
    dark = pixels < 128
    height, width = dark.shape
    for axis, length, reach in ((1, height, width), (0, width, height)):
        share = dark.sum(axis=axis) / reach
        depth = max(2, round(band * length))
        for edge in (range(depth), range(length - 1, length - 1 - depth, -1)):
            for at in edge:
                if share[at] >= cover:
                    if axis == 1:
                        pixels[at, :] = 255
                    else:
                        pixels[:, at] = 255
    return Image.fromarray(pixels)


def fit(image, margin=12, size=224):
    """The ink centred on white with the clean track's margin."""
    import numpy as np
    from PIL import Image, ImageOps
    if image.mode in ("LA", "RGBA", "PA", "P"):
        ground = Image.new("RGBA", image.size, (255, 255, 255, 255))
        ground.alpha_composite(image.convert("RGBA"))
        image = ground
    image = image.convert("L")
    if np.asarray(image).mean() < 127:
        image = ImageOps.invert(image)
    image = strip_frame(image)
    ys, xs = np.where(np.asarray(image) < 128)
    if not len(xs):
        return None
    part = image.crop((xs.min(), ys.min(), xs.max() + 1, ys.max() + 1))
    scale = (size - 2 * margin) / max(part.size)
    part = part.resize((max(1, round(part.width * scale)), max(1, round(part.height * scale))), Image.Resampling.LANCZOS)
    out = Image.new("L", (size, size), 255)
    out.paste(part, ((size - part.width) // 2, (size - part.height) // 2))
    return out


def read(args) -> int:
    import torch
    from PIL import Image
    from han2ids.forms import unify
    from han2ids.grammar import generate_beam, valid_ids
    from han2ids.infer import Han2IDS, tensor
    reader = Han2IDS(args.checkpoint)
    files = sorted(args.glyphs.glob("*/*.png"))
    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / "readings.jsonl", "w", encoding="utf-8") as out:
        for at, path in enumerate(files):
            image = fit(Image.open(path))
            if image is None:
                continue
            with torch.no_grad():
                beams = generate_beam(reader.model, tensor(image).unsqueeze(0).to(reader.device), reader.itos, k=3)
            out.write(json.dumps({"glyph": str(path.relative_to(args.glyphs.parent)), "readings": [
                {"ids": unify(text), "score": round(score, 4)} for text, score in beams if valid_ids(text)]}, ensure_ascii=False) + "\n")
            if at % 500 == 0:
                print(at, len(files), flush=True)
    return 0


def decks(args) -> int:
    from han2ids.tree import normalise
    sources = {}
    for path in args.charsets.glob("*_records.json"):
        body = json.loads(path.read_text(encoding="utf-8"))
        for row in body if isinstance(body, list) else body.get("records", []):
            if row.get("glyph"):
                sources[row["glyph"]] = row
    proposals = []
    rows = [json.loads(line) for line in (OUT / "readings.jsonl").read_text(encoding="utf-8").splitlines()]
    rows.sort(key=lambda row: row["readings"][0]["score"] if row["readings"] else 0)
    for row in rows:
        _, name, file = row["glyph"].split("/")
        record = sources.get(row["glyph"], {})
        proposals.append({"id": f"irg-{name}-{Path(file).stem}", "set": name, "source": record.get("source", ""),
                          "doc": record.get("document", ""), "image": str(args.charsets / row["glyph"]),
                          "cands": [[reading["ids"], round(reading["score"], 3)] for reading in row["readings"]]})

    references = {}
    for line in (args.dataset / "references.jsonl").read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        references[row["sample_id"]] = row
    images = {}
    for line in (args.dataset / "inputs.jsonl").read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        images[row["sample_id"]] = row["image"]
    disagreements = []
    for line in (args.run / "predictions.jsonl").read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        reference = references[row["sample_id"]]
        text = row["candidates"][0]["text"] if row["candidates"] else ""
        if text and normalise(text) != normalise(reference["ids"]):
            disagreements.append({"id": f"clean-{row['sample_id'][:16]}", "char": reference["char"], "font": reference["font"],
                                  "label": reference["ids"], "model": text, "score": round(row["candidates"][0]["score"], 3),
                                  "image": str(args.dataset / images[row["sample_id"]])})
    random.Random(args.seed).shuffle(disagreements)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "decks.json").write_text(json.dumps({"irg": proposals, "clean": disagreements}, ensure_ascii=False), encoding="utf-8")
    print(f"{OUT / 'decks.json'}\t{len(proposals)} proposal glyphs, {len(disagreements)} disagreements")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    one = commands.add_parser("read", help="read a folder of glyph images with a checkpoint")
    one.add_argument("--glyphs", type=Path, required=True, help="a folder of <set>/<name>.png")
    one.add_argument("--checkpoint", type=Path, default=ROOT / "models" / "han2ids-v0.5.pt")
    one.set_defaults(handler=read)
    two = commands.add_parser("decks", help="write build/review/decks.json")
    two.add_argument("--charsets", type=Path, required=True, help="the folder holding glyphs/ and *_records.json")
    two.add_argument("--dataset", type=Path, required=True, help="a benchmark dataset folder")
    two.add_argument("--run", type=Path, required=True, help="a benchmark run on that dataset")
    two.add_argument("--seed", type=int, default=20261113)
    two.set_defaults(handler=decks)
    args = parser.parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
