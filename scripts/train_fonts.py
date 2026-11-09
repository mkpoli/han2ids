"""Train han2ids on the full BabelStone Han table, one image per available Mincho face.

Noto covers about 30k records, IPAmj about 52k, and the Jigmo family all 97,680. A character may
therefore have one to three images. The split is by character, so no character crosses train/val/test.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import re
import sys
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F
from fontTools.ttLib import TTFont
from PIL import Image, ImageDraw, ImageFont
from torch.optim import AdamW
from torch.optim.lr_scheduler import LambdaLR
from torch.utils.data import DataLoader, Dataset

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from han2ids.grammar import generate, valid_ids
from han2ids.model import GlyphIDS
from han2ids.tokenizer import BOS, EOS, PAD, UNK, Vocabulary

SIZE = 224
OPERATORS = set("⿰⿱⿲⿳⿴⿵⿶⿷⿸⿹⿺⿻⿼⿽⿾⿿〾㇯")
REGIONS = re.compile(r"\([A-Z]+\)$")


def labels() -> dict[str, str]:
    out = {}
    with gzip.open(ROOT / "data/babelstone-ids.tsv.gz", "rt", encoding="utf-8") as handle:
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


def han(char: str) -> bool:
    cp = ord(char)
    return 0x3400 <= cp <= 0x9FFF or 0x20000 <= cp <= 0x3347F


def split(char: str) -> str:
    n = int(hashlib.sha256(char.encode()).hexdigest()[:8], 16) % 1000
    return "test" if n < 50 else "val" if n < 100 else "train"


def render(font, char: str) -> np.ndarray:
    canvas = Image.new("L", (SIZE, SIZE), 255)
    ImageDraw.Draw(canvas).text((SIZE / 2, SIZE / 2), char, font=font, fill=0, anchor="mm")
    return np.asarray(canvas, dtype=np.uint8)


class Rows(Dataset):
    def __init__(self, rows, array, stoi):
        self.rows, self.array, self.stoi = rows, array, stoi
    def __len__(self): return len(self.rows)
    def __getitem__(self, index):
        row = self.rows[index]
        x = torch.from_numpy(np.asarray(self.array[index]).copy()).float().div_(255).unsqueeze(0).repeat(3, 1, 1).sub_(0.5).div_(0.5)
        ids = [BOS] + [self.stoi.get(ch, UNK) for ch in row["ids"]] + [EOS]
        return x, torch.tensor(ids[:48], dtype=torch.long)


def collate(batch):
    width = max(len(ids) for _, ids in batch)
    x = torch.stack([item[0] for item in batch])
    y = torch.full((len(batch), width), PAD, dtype=torch.long)
    for i, (_, ids) in enumerate(batch):
        y[i, :len(ids)] = ids
    return x, y


@torch.no_grad()
def evaluate(model, rows, array, vocab, batch=32, limit=None):
    model.eval()
    exact = valid = total = 0
    by_font = {}
    for start in range(0, len(rows), batch):
        if limit is not None and start >= limit:
            break
        x = torch.from_numpy(np.asarray(array[start:start + batch]).copy()).float().div_(255).unsqueeze(1).repeat(1, 3, 1, 1).sub_(0.5).div_(0.5).cuda()
        tokens, _ = generate(model, x, vocab.itos)
        for pred, gold_row in zip(tokens, rows[start:start + batch]):
            text = vocab.decode(pred.tolist())
            ok = text == gold_row["ids"]
            exact += ok; valid += valid_ids(text); total += 1
            font = gold_row["font"]
            by_font.setdefault(font, [0, 0])
            by_font[font][0] += ok; by_font[font][1] += 1
    return exact / max(1, total), valid / max(1, total), total, {k: v[0] / v[1] for k, v in by_font.items()}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=ROOT / "models/han2ids-font-v0.1.pt")
    parser.add_argument("--cache", type=Path, default=ROOT / "build/font-full")
    parser.add_argument("--epochs", type=int, default=4)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    args.cache.mkdir(parents=True, exist_ok=True)

    table = {char: ids for char, ids in labels().items() if han(char)}
    faces = {"noto": (ROOT / "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc", 0),
             "ipamj": (ROOT / "cache/fonts/ipamj/ipamjm.ttf", None)}
    faces["noto"] = (Path("/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc"), 0)
    jigmo_paths = [ROOT / "cache/fonts/jigmo/Jigmo.ttf", ROOT / "cache/fonts/jigmo/Jigmo2.ttf", ROOT / "cache/fonts/jigmo/Jigmo3.ttf"]
    jigmo_fonts = [ImageFont.truetype(str(path), SIZE) for path in jigmo_paths]
    jigmo_maps = [set(TTFont(str(path)).getBestCmap()) for path in jigmo_paths]
    fonts = {name: (ImageFont.truetype(str(path), SIZE, index=index) if index is not None else ImageFont.truetype(str(path), SIZE))
             for name, (path, index) in faces.items()}
    cmaps = {name: set((TTFont(path, fontNumber=index) if index is not None else TTFont(path)).getBestCmap())
             for name, (path, index) in faces.items()}

    def jigmo_face(char):
        for font, cmap in zip(jigmo_fonts, jigmo_maps):
            if ord(char) in cmap:
                return font
        return jigmo_fonts[0]

    records = []
    for char, ids in table.items():
        if args.limit and len(records) >= args.limit:
            break
        part = split(char)
        for name in ("noto", "ipamj"):
            if ord(char) in cmaps[name]:
                records.append({"char": char, "ids": ids, "font": name, "split": part})
        if any(ord(char) in cmap for cmap in jigmo_maps):
            records.append({"char": char, "ids": ids, "font": "jigmo", "split": part})
    print("rows", len(records), flush=True)

    arrays = {}
    for part in ("train", "val", "test"):
        rows = [row for row in records if row["split"] == part]
        path = args.cache / f"{part}.npy"
        if path.exists():
            array = np.load(path, mmap_mode="r")
            if len(array) != len(rows):
                raise SystemExit(f"{path} has {len(array)} images, expected {len(rows)}")
        else:
            array = np.lib.format.open_memmap(path, mode="w+", dtype=np.uint8, shape=(len(rows), SIZE, SIZE))
            began = time.time()
            for i, row in enumerate(rows):
                font = jigmo_face(row["char"]) if row["font"] == "jigmo" else fonts[row["font"]]
                array[i] = render(font, row["char"])
                if i and i % 20000 == 0:
                    print(part, i, f"{i / (time.time() - began):.0f}/s", flush=True)
            array.flush()
            print(part, len(rows), f"{len(rows) / (time.time() - began):.0f}/s", flush=True)
        arrays[part] = array
        (args.cache / f"{part}.jsonl").write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows))
        print(part, len(rows), flush=True)

    vocab = Vocabulary.from_chars({ch for row in records for ch in row["ids"]})
    model = GlyphIDS(len(vocab), "vit_small_patch16_224.augreg_in21k_ft_in1k", pretrained=True).cuda()
    loader = DataLoader(Rows([r for r in records if r["split"] == "train"], arrays["train"], vocab.stoi),
                        batch_size=args.batch_size, shuffle=True, collate_fn=collate, drop_last=True, num_workers=0)
    encoder = [p for name, p in model.named_parameters() if name.startswith("encoder.")]
    decoder = [p for name, p in model.named_parameters() if not name.startswith("encoder.")]
    optimizer = AdamW([{"params": encoder, "lr": 1e-4}, {"params": decoder, "lr": 5e-4}], weight_decay=0.05)
    steps = len(loader) * args.epochs
    scheduler = LambdaLR(optimizer, lambda step: min(1, step / max(1, steps // 20)) * 0.5 * (1 + math.cos(math.pi * step / max(1, steps))))
    val_rows = [r for r in records if r["split"] == "val"]
    best = 0.0
    for epoch in range(args.epochs):
        began = time.time()
        model.train(); running = 0.0
        for step, (x, y) in enumerate(loader):
            x, y = x.cuda(), y.cuda()
            with torch.autocast("cuda", dtype=torch.bfloat16):
                logits = model(x, y[:, :-1])
                loss = F.cross_entropy(logits.reshape(-1, logits.size(-1)), y[:, 1:].reshape(-1), ignore_index=PAD, label_smoothing=0.05)
            optimizer.zero_grad(set_to_none=True); loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0); optimizer.step(); scheduler.step()
            running += loss.item()
            if step % 200 == 0:
                print(f"epoch {epoch} step {step}/{len(loader)} loss {running/(step+1):.4f}", flush=True)
        exact, valid, seen, by_font = evaluate(model, val_rows, arrays["val"], vocab)
        print(f"epoch {epoch} val {exact:.4f} valid {valid:.4f} n={seen} {time.time()-began:.0f}s {by_font}", flush=True)
        if exact > best:
            best = exact
            args.out.parent.mkdir(parents=True, exist_ok=True)
            torch.save({"model": model.state_dict(), "itos": vocab.itos,
                        "args": {"encoder": "vit_small_patch16_224.augreg_in21k_ft_in1k", "max_len": 48}}, args.out)
            print("saved", args.out, best, flush=True)

    checkpoint = torch.load(args.out, map_location="cpu", weights_only=False)
    model.load_state_dict(checkpoint["model"])
    test_rows = [r for r in records if r["split"] == "test"]
    exact, valid, seen, by_font = evaluate(model, test_rows, arrays["test"], vocab)
    print("test", exact, valid, seen, by_font, flush=True)
    (args.cache / "results.json").write_text(json.dumps({"best_val": best, "test": exact, "valid": valid, "seen": seen, "by_font": by_font}, indent=1))


if __name__ == "__main__":
    main()
