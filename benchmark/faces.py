#!/usr/bin/env python3
"""Score han2ids checkpoints on held-out characters drawn in faces outside training.

Each face is given as NAME=INDEX=PATH. The test manifest's characters that the face covers are drawn
with the clean track's renderer (ink-fitted, 12 px margin), up to --limit per face in a seeded order,
and read with batched greedy decoding. Agreement is exact equality of unified readings, per image.
The references are the manifest's first usable sequence; a face that prints a regional form differs
from its reference by design. No image is written; the summary records each face's file hash.

Example: python -m benchmark.faces --manifest build/font-v03/test.jsonl \
    --checkpoint v0.5=models/han2ids-v0.5.pt --face 'Yu Mincho=0=/path/yumin.ttf' --output faces.json
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--checkpoint", action="append", required=True, help="NAME=PATH; trusted checkpoints only")
    parser.add_argument("--face", action="append", required=True, help="NAME=INDEX=PATH")
    parser.add_argument("--limit", type=int, default=1500)
    parser.add_argument("--seed", type=int, default=20261113)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    import torch
    from benchmark.render import Face, RenderError, render
    from han2ids.forms import unify
    from han2ids.grammar import generate
    from han2ids.infer import Han2IDS, tensor
    from han2ids.status import GOLD

    labels = {}
    for line in args.manifest.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        labels[row["char"]] = unify(GOLD.get(row["char"], row["ids"]))
    order = sorted(labels)
    random.Random(args.seed).shuffle(order)
    readers = {}
    for item in args.checkpoint:
        name, path = item.split("=", 1)
        readers[name] = Han2IDS(path)

    faces = []
    for item in args.face:
        name, index, path = item.split("=", 2)
        face = Face.load(name, Path(path), int(index))
        covered = [char for char in order if ord(char) in face.cmap]
        chars, images = [], []
        for char in covered:
            try:
                images.append(tensor(render(face, char).convert("L")))
            except RenderError:
                continue
            chars.append(char)
            if len(chars) >= args.limit:
                break
        record = {"name": name, "face_index": int(index), "sha256": face.sha256, "names": face.names,
                  "covered": len(covered), "characters": len(chars), "agreement": {}, "rows": []}
        readings = {}
        for reader_name, reader in readers.items():
            out = []
            for start in range(0, len(images), 32):
                batch = torch.stack(images[start:start + 32]).to(reader.device)
                with torch.no_grad():
                    tokens, _ = generate(reader.model, batch, reader.itos)
                out += [unify(reader.vocab.decode(row.tolist())) for row in tokens]
            readings[reader_name] = out
            hits = sum(text == labels[char] for text, char in zip(out, chars))
            record["agreement"][reader_name] = round(100 * hits / max(1, len(chars)), 2)
        for at, char in enumerate(chars):
            record["rows"].append({"char": char, "reference": labels[char],
                                   **{name: out[at] for name, out in readings.items()}})
        faces.append(record)
        print(name, record["characters"], record["covered"], record["agreement"], flush=True)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({
        "format": "han2ids-faces-v1", "seed": args.seed, "limit": args.limit, "padding": 12, "size": 224,
        "decode": "greedy-batched", "reading": "unified", "faces": faces,
    }, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
