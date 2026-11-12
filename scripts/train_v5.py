"""v0.5: continue v0.4 with printed-form labels, ink-fitted renders and composed glyphs.

Three things change from v0.4. A share of the training rows is drawn again from its face with the ink
centred and scaled to a random margin, the framing of the clean benchmark track and of a cropped
glyph; the rest keeps the cached em-box image. Labels follow the form each face prints (`data/font-label-overrides.tsv`),
so a variation sequence such as 鄕 U+E0102 is one output token. And a share of every batch is composed
from parts: two glyphs of one face placed side by side or stacked, labelled `⿰AB` or `⿱AB`. Composed
glyphs show every vocabulary component in a labelled position, including the components that no
training character contains. A composition whose unified reading is a validation or test label is
never drawn.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sys
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image, ImageDraw, ImageFont, ImageOps
from torch.optim import AdamW
from torch.optim.lr_scheduler import LambdaLR
from torch.utils.data import DataLoader, Dataset

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from han2ids.grammar import ARITY, generate, valid_ids
from han2ids.model import GlyphIDS
from han2ids.status import FONT_GOLD, UNIFIED, gold, unify
from han2ids.tokenizer import BOS, EOS, PAD, UNK, Vocabulary, split

SIZE = 224
FACES = {
    "noto": [("/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc", 0)],
    "ipamj": [("cache/fonts/ipamj/ipamjm.ttf", 0)],
    "jigmo": [("cache/fonts/jigmo/Jigmo.ttf", 0), ("cache/fonts/jigmo/Jigmo2.ttf", 0),
              ("cache/fonts/jigmo/Jigmo3.ttf", 0)],
}
# Faces whose default glyph for a bare character is not the form the token names.
FORM_FACES = {"鄕\U000E0102": ("ipamj", "jigmo"), "鄕\U000E0101": ("ipamj", "jigmo")}


def to_tensor(array: np.ndarray) -> torch.Tensor:
    return torch.from_numpy(array.copy()).float().div_(255).unsqueeze(0).repeat(3, 1, 1).sub_(0.5).div_(0.5)


class Composer:
    """Draws `⿰AB` and `⿱AB` from two glyphs of one face."""

    def __init__(self, root: Path, leaves: list[str], rare: set[str], forms: list[str], held_out: set[str],
                 form_share: float):
        self.root, self.leaves, self.rare, self.forms = root, leaves, rare, forms
        self.held_out, self.form_share = held_out, form_share
        self.fonts = None

    def load(self):
        from fontTools.ttLib import TTFont
        self.fonts, self.covered = {}, {}
        for name, files in FACES.items():
            entries = []
            for file, index in files:
                path = file if file.startswith("/") else str(self.root / file)
                entries.append((ImageFont.truetype(path, SIZE, index=index),
                                set(TTFont(path, fontNumber=index).getBestCmap())))
            self.fonts[name] = entries
            self.covered[name] = [leaf for leaf in self.leaves if any(ord(leaf[0]) in cmap for _, cmap in entries)]
        self.scarce = {name: [leaf for leaf in covered if leaf in self.rare] for name, covered in self.covered.items()}

    def leaf(self, face: str, rng: random.Random) -> str:
        """Half of the draws come from the components that few training labels contain."""
        pool = self.scarce[face] if self.scarce[face] and rng.random() < 0.5 else self.covered[face]
        return rng.choice(pool)

    def ink(self, face: str, text: str):
        for font, cmap in self.fonts[face]:
            if ord(text[0]) in cmap:
                canvas = Image.new("L", (448, 448), 255)
                ImageDraw.Draw(canvas).text((224, 300), text, font=font, fill=0, anchor="ms")
                box = ImageOps.invert(canvas).getbbox()
                return canvas.crop(box) if box else None
        return None

    def fitted(self, face: str, text: str, padding: int, shift: tuple[int, int] = (0, 0)):
        """The glyph with its ink centred in the frame and scaled to leave the given margin."""
        if self.fonts is None:
            self.load()
        part = self.ink(face, text)
        if part is None:
            return None
        scale = (SIZE - 2 * padding) / max(part.size)
        part = part.resize((max(1, round(part.width * scale)), max(1, round(part.height * scale))),
                           Image.Resampling.LANCZOS)
        canvas = Image.new("L", (SIZE, SIZE), 255)
        canvas.paste(part, ((SIZE - part.width) // 2 + shift[0], (SIZE - part.height) // 2 + shift[1]))
        return np.asarray(canvas, dtype=np.uint8)

    def sample(self, rng: random.Random):
        if self.fonts is None:
            self.load()
        for _ in range(20):
            face = rng.choice(list(FACES))
            pair = [self.leaf(face, rng), self.leaf(face, rng)]
            if self.forms and rng.random() < self.form_share:
                form = rng.choice(self.forms)
                if face not in FORM_FACES.get(form, FACES):
                    face = rng.choice(FORM_FACES[form])
                    pair = [self.leaf(face, rng), self.leaf(face, rng)]
                pair[rng.randrange(2)] = form
            operator = rng.choice("⿰⿱")
            label = operator + pair[0] + pair[1]
            if unify(label) in self.held_out:
                continue
            parts = [self.ink(face, leaf) for leaf in pair]
            if None in parts:
                continue
            lo, hi = rng.randint(8, 20), rng.randint(204, 216)
            cut = round(lo + (hi - lo) * rng.uniform(0.36, 0.64))
            gap = rng.randint(0, 3)
            canvas = Image.new("L", (SIZE, SIZE), 255)
            if operator == "⿰":
                boxes = [(lo, lo, cut - gap, hi), (cut + gap, lo, hi, hi)]
            else:
                boxes = [(lo, lo, hi, cut - gap), (lo, cut + gap, hi, hi)]
            for part, (x0, y0, x1, y1) in zip(parts, boxes):
                canvas.paste(part.resize((x1 - x0, y1 - y0), Image.Resampling.LANCZOS), (x0, y0))
            return np.asarray(canvas, dtype=np.uint8), label
        return None


class Rows(Dataset):
    def __init__(self, items, path, vocab, composer, share, fitted, seed):
        self.items, self.path, self.vocab = items, path, vocab
        self.fitted = fitted
        self.array = None
        self.composer, self.share, self.seed = composer, share, seed
        self.epoch = 0

    def __len__(self):
        return len(self.items)

    def __getitem__(self, index):
        rng = random.Random(self.seed * 1_000_003 + self.epoch * 10_000_019 + index)
        drawn = self.composer.sample(rng) if self.share and rng.random() < self.share else None
        if drawn:
            image, ids = drawn
        else:
            row, ids, char, face = self.items[index]
            image = None
            if rng.random() < self.fitted:
                padding = rng.randint(6, 30)
                shift = (rng.randint(-4, 4), rng.randint(-4, 4))
                image = self.composer.fitted(face, char, padding, shift)
            if image is None:
                if self.array is None:
                    self.array = np.load(self.path, mmap_mode="r")
                image = np.asarray(self.array[row])
        tokens = [BOS] + [self.vocab.stoi[token] for token in split(ids)] + [EOS]
        return to_tensor(image), torch.tensor(tokens[:48], dtype=torch.long)


def collate(batch):
    width = max(len(ids) for _, ids in batch)
    x = torch.stack([item[0] for item in batch])
    y = torch.full((len(batch), width), PAD, dtype=torch.long)
    for i, (_, ids) in enumerate(batch):
        y[i, :len(ids)] = ids
    return x, y


@torch.no_grad()
def predict(model, array, vocab, batch=64):
    model.eval()
    out = []
    for start in range(0, len(array), batch):
        x = torch.from_numpy(np.asarray(array[start:start + batch]).copy()).float().div_(255)
        x = x.unsqueeze(1).repeat(1, 3, 1, 1).sub_(0.5).div_(0.5).cuda()
        with torch.autocast("cuda", dtype=torch.bfloat16):
            tokens, _ = generate(model, x, vocab.itos)
        out.extend(vocab.decode(row.tolist()) for row in tokens)
    return out


def fitted_view(composer, rows, fallback):
    """Every row drawn with the clean track's 12-pixel margin; the cached image where a face fails."""
    out = np.empty((len(rows), SIZE, SIZE), dtype=np.uint8)
    for index, row in enumerate(rows):
        image = composer.fitted(row["font"], row["char"], 12)
        out[index] = image if image is not None else fallback[index]
    return out


def score(rows, predictions, unseen):
    """Exact agreement with the printed-form label, the unified label, and the unseen-component rows."""
    exact = unified = valid = rare = rare_total = 0
    fonts = {}
    for row, text in zip(rows, predictions):
        label = gold(row["char"], row["font"], row["ids"])
        hit = text == label
        exact += hit
        unified += unify(text) == unify(label)
        valid += valid_ids(text)
        tally = fonts.setdefault(row["font"], [0, 0])
        tally[0] += hit
        tally[1] += 1
        if unseen & set(split(label)):
            rare += hit
            rare_total += 1
    total = max(1, len(rows))
    return {"exact": exact / total, "unified": unified / total, "valid": valid / total,
            "unseen_component": rare / max(1, rare_total), "unseen_component_rows": rare_total,
            "by_font": {font: hit / count for font, (hit, count) in sorted(fonts.items())}}


def extend(model, payload, tokens):
    """Add output tokens, each starting from the embedding of its base or unified character."""
    itos = list(payload["itos"])
    stoi = {token: index for index, token in enumerate(itos)}
    added = [token for token in tokens if token not in stoi]
    if not added:
        return model, itos
    base = [stoi.get(token[0], stoi.get(UNIFIED.get(token, ""), UNK)) for token in added]
    grown = GlyphIDS(len(itos) + len(added), payload["args"]["encoder"])
    state = model.state_dict()
    weight = torch.cat([state["tok.weight"], state["tok.weight"][base]])
    state["tok.weight"] = state["head.weight"] = weight
    state["head.bias"] = torch.cat([state["head.bias"], state["head.bias"][base]])
    grown.load_state_dict(state)
    return grown, itos + added


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache", type=Path, default=ROOT / "build/font-v03")
    parser.add_argument("--fonts-root", type=Path, default=ROOT)
    parser.add_argument("--init", type=Path, default=ROOT / "models/han2ids-v0.4.pt")
    parser.add_argument("--out", type=Path, default=ROOT / "models/han2ids-v0.5.pt")
    parser.add_argument("--log", type=Path, default=ROOT / "build/v0.5/metrics.jsonl")
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--encoder-lr", type=float, default=1e-5)
    parser.add_argument("--decoder-lr", type=float, default=5e-5)
    parser.add_argument("--composed", type=float, default=0.2, help="share of each batch that is composed")
    parser.add_argument("--fitted", type=float, default=0.5, help="share of rows drawn ink-fitted")
    parser.add_argument("--form-share", type=float, default=0.25, help="share of compositions holding a printed form")
    parser.add_argument("--form-repeat", type=int, default=20, help="copies of each row whose label holds a printed form")
    parser.add_argument("--limit", type=int, help="train on this many rows per epoch")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--seed", type=int, default=17)
    args = parser.parse_args()
    torch.manual_seed(args.seed)

    def read(name):
        return [json.loads(line) for line in (args.cache / f"{name}.jsonl").read_text().splitlines()]

    train, val, test = read("train"), read("val"), read("test")
    val_array = np.load(args.cache / "val.npy", mmap_mode="r")

    payload = torch.load(args.init, map_location="cpu", weights_only=False)
    model = GlyphIDS(len(payload["itos"]), payload["args"]["encoder"])
    model.load_state_dict(payload["model"])
    forms = sorted(form for form in UNIFIED if len(split(form)) == 1 and len(form) > 1)
    labelled = sorted({token for text in FONT_GOLD.values() for token in split(text)})
    model, itos = extend(model, payload, forms + labelled)
    model.cuda()
    vocab = Vocabulary(itos)

    items, seen = [], {}
    for index, row in enumerate(train):
        ids = gold(row["char"], row["font"], row["ids"])
        tokens = split(ids)
        if all(token in vocab.stoi for token in tokens):
            copies = args.form_repeat if any(token in UNIFIED or token in UNIFIED.values() for token in tokens) else 1
            items.extend([(index, ids, row["char"], row["font"])] * copies)
            for token in tokens:
                seen[token] = seen.get(token, 0) + 1
    held_out = {unify(gold(row["char"], row["font"], row["ids"])) for row in val + test}
    unseen = {token for row in val for token in split(gold(row["char"], row["font"], row["ids"]))} - set(seen)
    leaves = [token for token in itos[4:] if token not in ARITY and len(token) == 1]
    rare = {token for token in leaves if seen.get(token, 0) < 6}
    composer = Composer(args.fonts_root, leaves, rare, forms + ["鄉", "郷"], held_out, args.form_share)
    if args.limit:
        random.Random(args.seed).shuffle(items)
        items = items[:args.limit]
    data = Rows(items, args.cache / "train.npy", vocab, composer, args.composed, args.fitted, args.seed)
    loader = DataLoader(data, batch_size=args.batch_size, shuffle=True, collate_fn=collate, drop_last=True,
                        num_workers=args.workers, persistent_workers=False)
    print("train items", len(items), "val", len(val), "unseen val components", len(unseen), "vocab", len(vocab), flush=True)

    encoder = [p for name, p in model.named_parameters() if name.startswith("encoder.")]
    decoder = [p for name, p in model.named_parameters() if not name.startswith("encoder.")]
    optimizer = AdamW([{"params": encoder, "lr": args.encoder_lr}, {"params": decoder, "lr": args.decoder_lr}],
                      weight_decay=0.05)
    steps = len(loader) * args.epochs
    scheduler = LambdaLR(optimizer, lambda step: min(1, step / max(1, steps // 20)) * 0.5 * (1 + math.cos(math.pi * step / max(1, steps))))

    args.log.parent.mkdir(parents=True, exist_ok=True)
    args.out.parent.mkdir(parents=True, exist_ok=True)

    view = args.log.parent.parent / "val-fitted.npy"
    if not view.exists():
        np.save(view, fitted_view(composer, val, val_array))
    val_fitted = np.load(view, mmap_mode="r")

    def report(epoch, loss=None, seconds=None):
        result = {"epoch": epoch, "loss": loss, "seconds": seconds,
                  "cached": score(val, predict(model, val_array, vocab), unseen),
                  "fitted": score(val, predict(model, val_fitted, vocab), unseen)}
        print(json.dumps(result, ensure_ascii=False), flush=True)
        with open(args.log, "a") as handle:
            handle.write(json.dumps(result, ensure_ascii=False) + "\n")
        return (result["cached"]["exact"] + result["fitted"]["exact"]) / 2

    best = report(0)
    for epoch in range(1, args.epochs + 1):
        began, running = time.time(), 0.0
        data.epoch = epoch  # workers start per epoch, so each sees the new value
        model.train()
        for step, (x, y) in enumerate(loader):
            x, y = x.cuda(non_blocking=True), y.cuda(non_blocking=True)
            with torch.autocast("cuda", dtype=torch.bfloat16):
                logits = model(x, y[:, :-1])
                loss = F.cross_entropy(logits.reshape(-1, logits.size(-1)).float(), y[:, 1:].reshape(-1),
                                       ignore_index=PAD, label_smoothing=0.05)
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            scheduler.step()
            running += loss.item()
            if step % 500 == 0:
                print(f"epoch {epoch} step {step}/{len(loader)} loss {running / (step + 1):.4f} {time.time() - began:.0f}s", flush=True)
        exact = report(epoch, running / max(1, len(loader)), round(time.time() - began))
        state = {"model": model.state_dict(), "itos": vocab.itos, "args": payload["args"]}
        torch.save(state, args.out.with_name(f"{args.out.stem}-epoch{epoch}.pt"))
        if exact > best:
            best = exact
            torch.save(state, args.out)
            print("saved", args.out, best, flush=True)


if __name__ == "__main__":
    main()
