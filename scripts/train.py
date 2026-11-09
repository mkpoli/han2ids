"""Train han2ids from image/label JSONL files."""
from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image
from torch.optim import AdamW
from torch.optim.lr_scheduler import LambdaLR
from torch.utils.data import DataLoader, Dataset

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from han2ids.grammar import generate, valid_ids
from han2ids.model import GlyphIDS
from han2ids.tokenizer import BOS, EOS, PAD, UNK, Vocabulary


class Rows(Dataset):
    def __init__(self, rows, root, vocab, max_len=48):
        self.rows, self.root, self.vocab, self.max_len = rows, root, vocab, max_len

    def __len__(self):
        return len(self.rows)

    def __getitem__(self, index):
        row = self.rows[index]
        image = Image.open(self.root / row["image"]).convert("L").resize((224, 224), Image.Resampling.BILINEAR)
        x = torch.from_numpy(np.asarray(image, dtype=np.float32) / 255).unsqueeze(0).repeat(3, 1, 1).sub_(0.5).div_(0.5)
        ids = [BOS] + [self.vocab.stoi.get(char, UNK) for char in row["ids"]] + [EOS]
        return x, torch.tensor(ids[:self.max_len], dtype=torch.long)


def collate(batch):
    width = max(len(ids) for _, ids in batch)
    x = torch.stack([item[0] for item in batch])
    y = torch.full((len(batch), width), PAD, dtype=torch.long)
    for i, (_, ids) in enumerate(batch):
        y[i, :len(ids)] = ids
    return x, y


def load(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line]


@torch.no_grad()
def evaluate(model, rows, root, vocab, max_batches=None):
    model.eval()
    loader = DataLoader(Rows(rows, root, vocab), batch_size=32, collate_fn=collate)
    exact = valid = total = 0
    for index, (x, y) in enumerate(loader):
        if max_batches is not None and index >= max_batches:
            break
        tokens, _ = generate(model, x.cuda(), vocab.itos)
        for pred, gold in zip(tokens, y):
            text = vocab.decode(pred.tolist())
            exact += text == vocab.decode(gold[1:].tolist())
            valid += valid_ids(text)
            total += 1
    return exact / max(1, total), valid / max(1, total), total


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, default=Path("build/dataset"))
    parser.add_argument("--out", type=Path, default=Path("models/han2ids-font-v0.1.pt"))
    parser.add_argument("--encoder", default="vit_small_patch16_224.augreg_in21k_ft_in1k")
    parser.add_argument("--epochs", type=int, default=8)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--lr-encoder", type=float, default=1e-4)
    parser.add_argument("--lr-decoder", type=float, default=5e-4)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()

    train = load(args.data / "train.jsonl")
    val = load(args.data / "val.jsonl")
    if args.limit:
        train, val = train[:args.limit], val[:150]
    vocab = Vocabulary.from_chars({char for row in train + val for char in row["ids"]})
    model = GlyphIDS(len(vocab), args.encoder, pretrained=True).cuda()
    loader = DataLoader(Rows(train, args.data, vocab), batch_size=args.batch_size, shuffle=True,
                        collate_fn=collate, drop_last=True, num_workers=0)
    encoder = [p for name, p in model.named_parameters() if name.startswith("encoder.")]
    decoder = [p for name, p in model.named_parameters() if not name.startswith("encoder.")]
    optimizer = AdamW([{"params": encoder, "lr": args.lr_encoder}, {"params": decoder, "lr": args.lr_decoder}], weight_decay=0.05)
    steps = len(loader) * args.epochs
    scheduler = LambdaLR(optimizer, lambda step: min(1, step / max(1, steps // 20)) * 0.5 * (1 + math.cos(math.pi * step / max(1, steps))))
    best = 0
    for epoch in range(args.epochs):
        began = time.time()
        model.train()
        running = 0.0
        for step, (x, y) in enumerate(loader):
            x, y = x.cuda(), y.cuda()
            with torch.autocast("cuda", dtype=torch.bfloat16):
                logits = model(x, y[:, :-1])
                loss = F.cross_entropy(logits.reshape(-1, logits.size(-1)), y[:, 1:].reshape(-1), ignore_index=PAD, label_smoothing=0.05)
            optimizer.zero_grad(set_to_none=True); loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0); optimizer.step(); scheduler.step()
            running += loss.item()
            if step % 100 == 0:
                print(f"{epoch} {step}/{len(loader)} loss {running / (step + 1):.4f}", flush=True)
        exact, valid, seen = evaluate(model, val, args.data, vocab, max_batches=50)
        print(f"epoch {epoch} val {exact:.4f} valid {valid:.4f} n={seen} {time.time() - began:.0f}s", flush=True)
        if exact > best:
            best = exact
            args.out.parent.mkdir(parents=True, exist_ok=True)
            torch.save({"model": model.state_dict(), "itos": vocab.itos,
                        "args": {"encoder": args.encoder, "max_len": 48}}, args.out)
            print(f"saved {args.out} at {best:.4f}", flush=True)


if __name__ == "__main__":
    main()
