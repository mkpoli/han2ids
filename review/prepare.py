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
import re
import subprocess
import sys
import zipfile
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


def encoded(unihan: Path) -> dict[str, str]:
    """Each IRG source reference in Unihan, without its punctuation, to the character it became."""
    found = {}
    with zipfile.ZipFile(unihan) as archive:
        for line in archive.read("Unihan_IRGSources.txt").decode("utf-8").splitlines():
            parts = line.split("\t")
            if len(parts) == 3 and parts[1].startswith("kIRG_") and parts[1].endswith("Source"):
                for value in parts[2].split():
                    found[re.sub(r"[-_]", "", value.split(":")[0])] = chr(int(parts[0][2:], 16))
    return found


def became(source: str, unified: str, later: dict[str, str]) -> str | None:
    """The character a proposal glyph is now: its own source encoded later, else the character it was unified with.

    Unihan goes first; the withdrawal lists give Extension E positions from drafts, a few code points off the final ones.
    """
    def key(reference: str) -> str:
        return re.sub(r"[-_]", "", reference)
    if key(source) in later:
        return later[key(source)]
    if unified.startswith("U+"):
        return chr(int(unified[2:], 16))
    return later.get(key(unified)) if unified else None


def region(source: str) -> str:
    """The BabelStone region tag of a proposal's source reference."""
    for prefix, tag in (("UTC", "U"), ("Z_SAT", "U"), ("MAC", "M")):
        if source.startswith(prefix):
            return tag
    return source[:1]


def n891_positions(pdf: Path) -> dict[str, str]:
    """Each source reference in IRG N891 to the position code zi.tools files it under, 0891.0.PPCRR.

    The document lists five columns of glyphs a page, each cell a code line, a radical line and a source line.
    """
    text = subprocess.run(["pdftotext", "-layout", str(pdf), "-"], capture_output=True, text=True, check=True).stdout
    found = {}
    for page, body in enumerate(text.split("\f"), 1):
        lines = body.splitlines()
        row = 0
        for at, line in enumerate(lines):
            # A source line follows a line of radicals, which follows a line of position codes.
            if at >= 2 and re.match(r"^\s*\d{4}\.\d{3}", lines[at - 2]) and not re.match(r"^\s*\d{4}\.\d{3}", line) and line.strip():
                row += 1
                for column, token in enumerate(line.split(), 1):
                    found[token.upper()] = f"0891.0.{page:02d}{column}{row:02d}"
    return found


def clean_ids(text: str) -> bool:
    """A sequence in plain IDS: an operator first and none of zi.tools' own notation."""
    return bool(text) and "\u2ff0" <= text[0] <= "\u2fff" and not re.search(r"[#()\[\]{}?？&\-]", text)


def decks(args) -> int:
    from han2ids.labels import read as read_ids
    from han2ids.tree import normalise
    sources = {}
    for path in args.charsets.glob("*_records.json"):
        body = json.loads(path.read_text(encoding="utf-8"))
        for row in body if isinstance(body, list) else body.get("records", []):
            if row.get("glyph"):
                sources[row["glyph"]] = row
    later = encoded(args.unihan)
    known = read_ids(args.ids)
    positions = n891_positions(args.n891) if args.n891 else {}
    pages = json.loads(args.zi.read_text(encoding="utf-8")) if args.zi.exists() else {}
    proposals = []
    rows = [json.loads(line) for line in (OUT / "readings.jsonl").read_text(encoding="utf-8").splitlines()]
    rows.sort(key=lambda row: row["readings"][0]["score"] if row["readings"] else 0)
    for row in rows:
        _, name, file = row["glyph"].split("/")
        record = sources.get(row["glyph"], {})
        source = record.get("source", "")
        char = became(source, record.get("unifiedWith", ""), later)
        # The zi.tools page of an N891 glyph; a page named by one character is an encoded character.
        page = pages.get(positions.get(re.sub(r"^G_", "", source).upper(), ""), "")
        if len(page) == 1 and not char:
            char = page
        item = {"id": f"irg-{name}-{Path(file).stem}", "set": name, "source": source,
                "doc": record.get("document", ""), "image": str(args.charsets / row["glyph"]),
                "cands": [[reading["ids"], round(reading["score"], 3)] for reading in row["readings"]]}
        if char:
            item["char"] = char
            sequences = known.get(char, [])
            tagged = next((sequence for sequence in sequences if region(source) in sequence.regions), sequences[0] if sequences else None)
            if tagged:
                item["known"] = tagged.text
        elif page:
            item["zi"] = page
            if clean_ids(page):
                item["known"] = page
        proposals.append(item)

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
    two.add_argument("--unihan", type=Path, required=True, help="Unihan.zip, for proposals encoded later")
    two.add_argument("--n891", type=Path, help="IRG N891, the China Extension C1 submission (PDF)")
    two.add_argument("--zi", type=Path, default=ROOT / "cache" / "zi-tools" / "n891.json", help="scripts/fetch_zi_n891.py's output")
    two.add_argument("--ids", type=Path, default=ROOT / "data" / "IDS.TXT", help="BabelStone IDS")
    two.add_argument("--seed", type=int, default=20261113)
    two.set_defaults(handler=decks)
    args = parser.parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
