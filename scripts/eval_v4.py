"""Evaluate a v0.4 checkpoint on the clean 8,730-row test set."""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from han2ids.grammar import generate, valid_ids
from han2ids.model import GlyphIDS
from han2ids.status import classify
from han2ids.tokenizer import Vocabulary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ckpt", type=Path, default=ROOT / "models/han2ids-v0.4a.pt")
    parser.add_argument("--cache", type=Path, default=ROOT / "build/font-v03")
    parser.add_argument("--out", type=Path, default=ROOT / "docs/v0.4a-results.json")
    args = parser.parse_args()
    rows = [json.loads(line) for line in (args.cache / "test.jsonl").read_text().splitlines()]
    array = np.load(args.cache / "test.npy", mmap_mode="r")
    payload = torch.load(args.ckpt, map_location="cpu", weights_only=False)
    vocab = Vocabulary(payload["itos"])
    model = GlyphIDS(len(vocab), payload["args"]["encoder"]).cuda()
    model.load_state_dict(payload["model"]); model.eval()

    counts = Counter(); by_font = defaultdict(Counter); records = []
    for start in range(0, len(rows), 32):
        x = torch.from_numpy(np.asarray(array[start:start + 32]).copy()).float().div_(255).unsqueeze(1).repeat(1, 3, 1, 1).sub_(0.5).div_(0.5).cuda()
        tokens, confidence = generate(model, x, vocab.itos)
        for i, (pred, row) in enumerate(zip(tokens, rows[start:start + 32])):
            text = vocab.decode(pred.tolist())
            kind = classify(row["char"], row["font"], text, row["ids"])
            counts[kind] += 1; by_font[row["font"]][kind] += 1
            records.append({**row, "pred": text, "kind": kind, "valid": valid_ids(text), "confidence": round(float(confidence[i]), 4)})
    total = len(rows)
    out = {"rows": total, "counts": dict(counts),
           "exact": counts["exact"] / total, "same_tree": (counts["exact"] + counts["same"]) / total,
           "valid": sum(record["valid"] for record in records) / total, "by_font": {font: {k: v / sum(c.values()) for k, v in c.items()} for font, c in by_font.items()}}
    print(json.dumps(out, indent=1))
    args.out.write_text(json.dumps(out, indent=1) + "\n")
    with open(ROOT / "build/improvements/v04a.jsonl", "w") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
