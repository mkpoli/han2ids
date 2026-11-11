"""v0.4j: Jigmo specialist continued from v0.4a.

This run keeps only the Jigmo rows, so the model can specialise on the largest clean error bucket. v0.1 is deliberately not used: 4,274 of the 4,752
test characters were in its training split.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F
from torch.optim import AdamW
from torch.optim.lr_scheduler import LambdaLR
from torch.utils.data import DataLoader, Dataset

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from han2ids.grammar import generate, valid_ids
from han2ids.model import GlyphIDS
from han2ids.status import gold
from han2ids.tokenizer import BOS, EOS, PAD, UNK, Vocabulary


def select_rows(rows, array):
    if len(rows) != len(array):
        raise ValueError(f"Manifest rows ({len(rows)}) and image array ({len(array)}) differ in length")
    return [(i, row) for i, row in enumerate(rows) if row["font"] == "jigmo"]


def load_rows(cache, split):
    rows = [json.loads(line) for line in (cache / f"{split}.jsonl").read_text().splitlines()]
    array = np.load(cache / f"{split}.npy", mmap_mode="r")
    return select_rows(rows, array), array


class Rows(Dataset):
    def __init__(self, rows, array, vocab):
        self.array, self.vocab = array, vocab
        self.items = []
        for i, row in rows:
            ids = gold(row['char'], row['font'], row['ids'])
            if all(ch in vocab.stoi for ch in ids if ch not in '⿰⿱⿲⿳⿴⿵⿶⿷⿸⿹⿺⿻⿼⿽⿾⿿〾㇯'):
                self.items.append((i, ids))

    def __len__(self): return len(self.items)

    def __getitem__(self, index):
        i, ids = self.items[index]
        x = torch.from_numpy(np.asarray(self.array[i]).copy()).float().div_(255).unsqueeze(0).repeat(3, 1, 1).sub_(0.5).div_(0.5)
        tokens = [BOS] + [self.vocab.stoi[ch] for ch in ids] + [EOS]
        return x, torch.tensor(tokens[:48], dtype=torch.long)


def collate(batch):
    width = max(len(ids) for _, ids in batch)
    x = torch.stack([item[0] for item in batch])
    y = torch.full((len(batch), width), PAD, dtype=torch.long)
    for i, (_, ids) in enumerate(batch):
        y[i, :len(ids)] = ids
    return x, y


@torch.no_grad()
def evaluate(model, rows, array, vocab, batch=32, device="cuda"):
    model.eval(); exact = valid = total = 0
    for start in range(0, len(rows), batch):
        selected = rows[start:start + batch]
        indices = [i for i, _ in selected]
        x = torch.from_numpy(np.asarray(array[indices]).copy()).float().div_(255).unsqueeze(1).repeat(1, 3, 1, 1).sub_(0.5).div_(0.5).to(device)
        tokens, _ = generate(model, x, vocab.itos)
        for pred, (_, row) in zip(tokens, selected):
            text = vocab.decode(pred.tolist()); g = gold(row['char'], row['font'], row['ids'])
            exact += text == g; valid += valid_ids(text); total += 1
    return exact / max(1, total), valid / max(1, total), total


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache", type=Path, default=ROOT / "build/font-v03")
    parser.add_argument("--init", type=Path, default=ROOT / "models/han2ids-v0.4a.pt")
    parser.add_argument("--out", type=Path, default=ROOT / "models/han2ids-v0.4j.pt")
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument("--batch-size", type=int, default=32)
    args = parser.parse_args()

    train, train_array = load_rows(args.cache, "train")
    val, val_array = load_rows(args.cache, "val")

    payload = torch.load(args.init, map_location="cpu", weights_only=False)
    vocab = Vocabulary(payload["itos"])
    model = GlyphIDS(len(vocab), payload["args"]["encoder"]).cuda()
    model.load_state_dict(payload["model"])
    print("train rows", len(train), "val", len(val), flush=True)

    loader = DataLoader(Rows(train, train_array, vocab), batch_size=args.batch_size, shuffle=True,
                        collate_fn=collate, drop_last=True, num_workers=0)
    encoder = [p for name, p in model.named_parameters() if name.startswith("encoder.")]
    decoder = [p for name, p in model.named_parameters() if not name.startswith("encoder.")]
    optimizer = AdamW([{"params": encoder, "lr": 2e-5}, {"params": decoder, "lr": 1e-4}], weight_decay=0.05)
    steps = len(loader) * args.epochs
    scheduler = LambdaLR(optimizer, lambda step: min(1, step / max(1, steps // 20)) * 0.5 * (1 + math.cos(math.pi * step / max(1, steps))))
    best = 0.0
    for epoch in range(args.epochs):
        began = time.time(); model.train(); running = 0.0
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
        exact, valid, seen = evaluate(model, val, val_array, vocab)
        print(f"epoch {epoch} val {exact:.4f} valid {valid:.4f} n={seen} {time.time()-began:.0f}s", flush=True)
        if exact > best:
            best = exact
            torch.save({"model": model.state_dict(), "itos": vocab.itos,
                        "args": payload["args"]}, args.out)
            print("saved", args.out, best, flush=True)


if __name__ == "__main__":
    main()
