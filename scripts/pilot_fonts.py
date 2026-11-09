"""Pilot: train on Noto + Jigmo and test on held-out IPAmj.

The label table is BabelStone. Every selected character must be covered by Noto, the Jigmo family and
IPAmj. IPAmj is never in the training set; it is the held-out face.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import random
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
from torch.utils.data import DataLoader, Dataset

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from han2ids.grammar import generate, valid_ids
from han2ids.model import GlyphIDS
from han2ids.tokenizer import BOS, EOS, PAD, UNK, Vocabulary

SIZE = 224
OPERATORS = set("⿰⿱⿲⿳⿴⿵⿶⿷⿸⿹⿺⿻⿼⿽⿾⿿〾㇯")
REGIONS = re.compile(r"\([A-Z]+\)$")
CACHE = ROOT / "build" / "font-pilot"
CACHE.mkdir(parents=True, exist_ok=True)


def labels() -> dict[str, str]:
    out = {}
    with gzip.open(ROOT / "data" / "babelstone-ids.tsv.gz", "rt", encoding="utf-8") as handle:
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
    return "test" if n < 70 else "val" if n < 100 else "train"


def render(font, char: str) -> np.ndarray:
    canvas = Image.new("L", (SIZE, SIZE), 255)
    ImageDraw.Draw(canvas).text((SIZE / 2, SIZE / 2), char, font=font, fill=0, anchor="mm")
    return np.asarray(canvas, dtype=np.uint8)


class PairData(Dataset):
    def __init__(self, arrays, labels, stoi):
        self.arrays, self.labels, self.stoi = arrays, labels, stoi
        self.items = [(array, i) for array in arrays for i in range(len(labels))]
    def __len__(self): return len(self.items)
    def __getitem__(self, index):
        array, i = self.items[index]
        x = torch.from_numpy(np.asarray(array[i]).copy()).float().div_(255).unsqueeze(0).repeat(3, 1, 1).sub_(0.5).div_(0.5)
        ids = [BOS] + [self.stoi.get(ch, UNK) for ch in self.labels[i]] + [EOS]
        return x, torch.tensor(ids[:48], dtype=torch.long)


def collate(batch):
    width = max(len(ids) for _, ids in batch)
    x = torch.stack([item[0] for item in batch])
    y = torch.full((len(batch), width), PAD, dtype=torch.long)
    for i, (_, ids) in enumerate(batch):
        y[i, :len(ids)] = ids
    return x, y


@torch.no_grad()
def evaluate(model, array, labels, vocab, batch=32):
    model.eval()
    exact = valid = 0
    for start in range(0, len(labels), batch):
        x = torch.from_numpy(np.asarray(array[start:start + batch]).copy()).float().div_(255).unsqueeze(1).repeat(1, 3, 1, 1).sub_(0.5).div_(0.5).cuda()
        tokens, _ = generate(model, x, vocab.itos)
        for pred, gold in zip(tokens, labels[start:start + batch]):
            text = vocab.decode(pred.tolist())
            exact += text == gold
            valid += valid_ids(text)
    return exact / len(labels), valid / len(labels)


def main():
    table = labels()
    cmaps = {}
    fonts = {}
    paths = {
        "noto": ("/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc", 0),
        "ipamj": (str(ROOT / "cache/fonts/ipamj/ipamjm.ttf"), None),
    }
    jigmo_paths = [ROOT / "cache/fonts/jigmo/Jigmo.ttf", ROOT / "cache/fonts/jigmo/Jigmo2.ttf", ROOT / "cache/fonts/jigmo/Jigmo3.ttf"]
    for name, (path, index) in paths.items():
        fonts[name] = ImageFont.truetype(path, SIZE, index=index) if index is not None else ImageFont.truetype(path, SIZE)
        cmaps[name] = set((TTFont(path, fontNumber=index) if index is not None else TTFont(path)).getBestCmap())
    jigmo_fonts = [ImageFont.truetype(str(path), SIZE) for path in jigmo_paths]
    jigmo_maps = [set(TTFont(str(path)).getBestCmap()) for path in jigmo_paths]
    cmaps["jigmo"] = set().union(*jigmo_maps)

    chars = [char for char in table if han(char) and all(ord(char) in cmaps[name] for name in ("noto", "ipamj", "jigmo"))]
    random.Random(0).shuffle(chars)
    cut1, cut2 = int(len(chars) * 0.82), int(len(chars) * 0.91)
    train, val, test = chars[:cut1], chars[cut1:cut2], chars[cut2:]
    print("chars", len(train), len(val), len(test), flush=True)

    def face_for_jigmo(char):
        for font, cmap in zip(jigmo_fonts, jigmo_maps):
            if ord(char) in cmap:
                return font
        return jigmo_fonts[0]

    def array(name, chars, tag):
        path = CACHE / f"{tag}-{name}.npy"
        if path.exists():
            return np.load(path, mmap_mode="r")
        out = np.lib.format.open_memmap(path, mode="w+", dtype=np.uint8, shape=(len(chars), SIZE, SIZE))
        began = time.time()
        font = fonts.get(name)
        for i, char in enumerate(chars):
            out[i] = render(face_for_jigmo(char) if name == "jigmo" else font, char)
        out.flush()
        print(tag, name, f"{len(chars) / (time.time() - began):.0f}/s", flush=True)
        return out

    labels_train = [table[char] for char in train]
    labels_val = [table[char] for char in val]
    labels_test = [table[char] for char in test]
    vocab = Vocabulary.from_chars({ch for text in labels_train + labels_val + labels_test for ch in text})
    train_arrays = [array("noto", train, "train"), array("jigmo", train, "train")]
    val_array = array("ipamj", val, "val")
    test_arrays = {name: array(name, test, "test") for name in ("noto", "jigmo", "ipamj")}

    model = GlyphIDS(len(vocab), "vit_small_patch16_224.augreg_in21k_ft_in1k", pretrained=True).cuda()
    loader = DataLoader(PairData(train_arrays, labels_train, vocab.stoi), batch_size=32, shuffle=True, collate_fn=collate, drop_last=True, num_workers=0)
    encoder = [p for name, p in model.named_parameters() if name.startswith("encoder.")]
    decoder = [p for name, p in model.named_parameters() if not name.startswith("encoder.")]
    optimizer = AdamW([{"params": encoder, "lr": 1e-4}, {"params": decoder, "lr": 5e-4}], weight_decay=0.05)
    best = 0.0
    for epoch in range(4):
        began = time.time()
        model.train()
        running = 0.0
        for step, (x, y) in enumerate(loader):
            x, y = x.cuda(), y.cuda()
            with torch.autocast("cuda", dtype=torch.bfloat16):
                logits = model(x, y[:, :-1])
                loss = F.cross_entropy(logits.reshape(-1, logits.size(-1)), y[:, 1:].reshape(-1), ignore_index=PAD, label_smoothing=0.05)
            optimizer.zero_grad(set_to_none=True); loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0); optimizer.step()
            running += loss.item()
            if step % 200 == 0:
                print(f"epoch {epoch} step {step}/{len(loader)} loss {running/(step+1):.4f}", flush=True)
        exact, valid = evaluate(model, val_array, labels_val, vocab)
        print(f"epoch {epoch} val-ipamj {exact:.4f} valid {valid:.4f} {time.time()-began:.0f}s", flush=True)
        if exact > best:
            best = exact
            torch.save({"model": model.state_dict(), "itos": vocab.itos,
                        "args": {"encoder": "vit_small_patch16_224.augreg_in21k_ft_in1k", "max_len": 48}},
                       ROOT / "models/han2ids-font-pilot.pt")
            print("saved", best, flush=True)

    checkpoint = torch.load(ROOT / "models/han2ids-font-pilot.pt", map_location="cpu", weights_only=False)
    model.load_state_dict(checkpoint["model"])
    results = {"train": len(train), "val": len(val), "test": len(test), "best_val": best, "test": {}}
    for name in ("noto", "jigmo", "ipamj"):
        exact, valid = evaluate(model, test_arrays[name], labels_test, vocab)
        results["test"][name] = {"exact": exact, "valid": valid}
        print("test", name, exact, valid, flush=True)
    baseline_path = ROOT.parent / "ids-input/build/train/run3/best.pt"
    results["baseline"] = {}
    if baseline_path.exists():
        baseline = torch.load(baseline_path, map_location="cpu", weights_only=False)
        old = GlyphIDS(len(baseline["itos"]), baseline["args"]["encoder"]).cuda()
        old.load_state_dict(baseline["model"])
        old_vocab = Vocabulary(baseline["itos"])
        for name in ("noto", "jigmo", "ipamj"):
            exact, valid = evaluate(old, test_arrays[name], labels_test, old_vocab)
            results["baseline"][name] = {"exact": exact, "valid": valid}
            print("baseline", name, exact, valid, flush=True)
    (CACHE / "results.json").write_text(json.dumps(results, indent=1))


if __name__ == "__main__":
    main()
