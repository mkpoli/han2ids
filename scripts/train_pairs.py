#!/usr/bin/env python3
"""Train and measure the pair comparison: do two glyph images draw one registered form?

draw      Every character of the variation database is drawn in every candidate font; each distinct
          drawing is kept with the sequences it names and their collections.
train     A head over the reader's frozen patch tokens learns from pairs of those drawings.
measure   The head and the cosine of mean patch tokens are compared on characters held out of training.

A pair is one form when two font families draw one sequence, and two forms when the two drawings name
different sequences of one collection: a collection registers a design once. Pairs of sequences from
different collections can be one design under two names and are left out of training.

The held-out characters are the sample of scripts/variant_eval.py; the next characters of the same
order choose the checkpoint.

Example:
    python scripts/train_pairs.py draw --output build/pairs
    python scripts/train_pairs.py train --output build/pairs --run head
    python scripts/train_pairs.py measure --output build/pairs --run head
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
SIZE = 224
HELD, CHOSEN = 1500, 500


def family(file: str) -> str:
    return re.sub(r"\d+$", "", Path(file).stem)


_forms = None


def drawn(base: int) -> list[tuple[str, bytes]]:
    """Each distinct drawing of a character: its row and its pixels."""
    char = chr(base)
    out = []
    for shape in _forms.shapes(char):
        collections = defaultdict(set)
        for item in shape.candidates:
            if item.kind != "plain":
                collections[item.name].update(collection for collection, _ in item.registrations)
        row = {"char": char, "family": family(shape.file), "names": shape.names,
               "sequences": {name: sorted(found) for name, found in collections.items()}, "regions": shape.regions}
        out.append((json.dumps(row, ensure_ascii=False), np.asarray(shape.image, dtype=np.uint8).tobytes()))
    _forms._shapes.pop(char, None)
    return out


def draw(args) -> None:
    import multiprocessing

    from han2ids.variants import Forms

    global _forms
    _forms = Forms()
    order = sorted({base for base, _ in _forms.registered})
    random.Random(args.seed).shuffle(order)
    order = order[:args.limit]
    args.output.mkdir(parents=True, exist_ok=True)
    count = 0
    started = time.time()
    # The workers are forked after the tables are read and open their own font faces.
    with open(args.output / "shapes.u8", "wb") as pixels, open(args.output / "shapes.jsonl", "w", encoding="utf-8") as rows, \
            multiprocessing.get_context("fork").Pool(args.workers) as pool:
        for at, found in enumerate(pool.imap(drawn, order, chunksize=8)):
            for row, image in found:
                rows.write(row + "\n")
                pixels.write(image)
                count += 1
            if at % 1000 == 0:
                print(f"draw: {at} of {len(order)} characters, {count} shapes, {time.time() - started:.0f} s", flush=True)
    print(f"draw: {count} shapes of {len(order)} characters", flush=True)


class Shapes:
    """The drawings with their names, grouped by character in the order they were drawn."""

    def __init__(self, folder: Path, loaded: bool = False):
        self.rows = [json.loads(line) for line in (folder / "shapes.jsonl").read_text(encoding="utf-8").splitlines()]
        shape = (len(self.rows), SIZE, SIZE)
        # Training reads drawings at random, which a file on disk answers slowly; it holds them in memory.
        self.pixels = (np.fromfile(folder / "shapes.u8", dtype=np.uint8).reshape(shape) if loaded
                       else np.memmap(folder / "shapes.u8", dtype=np.uint8, mode="r", shape=shape))
        self.chars: dict[str, list[int]] = {}
        for index, row in enumerate(self.rows):
            self.chars.setdefault(row["char"], []).append(index)
        for row in self.rows:
            row["collections"] = {collection for found in row["sequences"].values() for collection in found}
            row["named"] = set(row["sequences"])

    def one(self, a: int, b: int) -> bool:
        return bool(self.rows[a]["named"] & self.rows[b]["named"])

    def two(self, a: int, b: int) -> bool:
        """Different sequences that one collection registers."""
        first, second = self.rows[a], self.rows[b]
        return not first["named"] & second["named"] and bool(first["collections"] & second["collections"])

    def pairs(self, chars: list[str]) -> dict[str, dict[str, list[tuple[int, int]]]]:
        """Per kind of pair, each character's pairs: one form across families, two forms across and within."""
        out: dict[str, dict[str, list[tuple[int, int]]]] = {"same": {}, "apart": {}, "within": {}, "self": {}}
        for char in chars:
            found = defaultdict(list)
            members = self.chars[char]
            for at, a in enumerate(members):
                if self.rows[a]["named"]:
                    found["self"].append((a, a))
                for b in members[at + 1:]:
                    across = self.rows[a]["family"] != self.rows[b]["family"]
                    if across and self.one(a, b):
                        found["same"].append((a, b))
                    elif self.two(a, b):
                        found["apart" if across else "within"].append((a, b))
            for kind, items in found.items():
                out[kind][char] = items
        return out

    def split(self) -> tuple[list[str], list[str], list[str]]:
        """Held-out characters, the characters that choose the checkpoint, and the training characters."""
        shared = []
        for char, members in self.chars.items():
            families = defaultdict(set)
            for index in members:
                for name in self.rows[index]["named"]:
                    if self.rows[index]["sequences"][name]:
                        families[name].add(self.rows[index]["family"])
            if any(len(found) > 1 for found in families.values()):
                shared.append(char)
        held, chosen = shared[:HELD], shared[HELD:HELD + CHOSEN]
        apart = set(held) | set(chosen)
        return held, chosen, [char for char in self.chars if char not in apart]


def augment(ink, generator):
    """The drawing as another printing of it: weight, placement, resolution and blur vary."""
    import torch
    import torch.nn.functional as F

    count, device = ink.size(0), ink.device

    def uniform(low, high, shape=(count, 1, 1, 1)):
        return torch.rand(shape, device=device, generator=generator) * (high - low) + low

    heavier = F.max_pool2d(ink, 3, 1, 1)
    lighter = -F.max_pool2d(-ink, 3, 1, 1)
    weight = uniform(-0.5, 0.8)
    ink = torch.where(weight > 0, ink + (heavier - ink) * weight, ink + (lighter - ink) * -weight)
    scale = uniform(0.93, 1.05, (count, 2))
    turn = uniform(-0.03, 0.03, (count,))
    shift = uniform(-0.035, 0.035, (count, 2))
    theta = torch.zeros(count, 2, 3, device=device)
    theta[:, 0, 0], theta[:, 0, 1] = torch.cos(turn) / scale[:, 0], -torch.sin(turn) / scale[:, 1]
    theta[:, 1, 0], theta[:, 1, 1] = torch.sin(turn) / scale[:, 0], torch.cos(turn) / scale[:, 1]
    theta[:, :, 2] = shift
    ink = F.grid_sample(ink, F.affine_grid(theta, ink.shape, align_corners=False), mode="bilinear",
                        padding_mode="zeros", align_corners=False)
    coarse = int(torch.randint(72, SIZE + 1, (1,), generator=generator, device=device))
    if coarse < 200:
        ink = F.interpolate(F.interpolate(ink, size=coarse, mode="bilinear", antialias=True), size=SIZE, mode="bilinear")
    sigma = uniform(0.0, 0.9)
    reach = torch.arange(-2, 3, device=device).view(1, 5).float()
    kernel = torch.exp(-reach ** 2 / (2 * sigma.view(count, 1).clamp(min=0.05) ** 2))
    kernel = kernel / kernel.sum(1, keepdim=True)
    ink = F.conv2d(ink.transpose(0, 1), kernel.view(count, 1, 1, 5), padding=(0, 2), groups=count)
    ink = F.conv2d(ink, kernel.view(count, 1, 5, 1), padding=(2, 0), groups=count).transpose(0, 1)
    return ink.clamp(0, 1)


def pixels_of(ink):
    """Ink in 0 to 1 as the reader's input: white ground, three channels, centred."""
    return ((1 - ink) - 0.5).div(0.5).expand(-1, 3, -1, -1)


class Batches:
    """Batches of pairs: a character is taken at random, then one of its pairs of the kind."""

    MIX = (("same", 0.30, 1.0), ("self", 0.15, 1.0), ("apart", 0.20, 0.0), ("within", 0.25, 0.0), ("other", 0.10, 0.0))

    def __init__(self, shapes: Shapes, chars: list[str], seed: int):
        self.shapes, self.random = shapes, random.Random(seed)
        self.pairs = shapes.pairs(chars)
        self.keys = {kind: sorted(found) for kind, found in self.pairs.items()}
        self.named = [index for char in chars for index in shapes.chars[char] if shapes.rows[index]["named"]]

    def take(self, size: int) -> tuple[list[int], list[int], list[float]]:
        first, second, labels = [], [], []
        kinds = self.random.choices([kind for kind, _, _ in self.MIX], [share for _, share, _ in self.MIX], k=size)
        label = {kind: value for kind, _, value in self.MIX}
        for kind in kinds:
            if kind == "other":
                a, b = self.random.sample(self.named, 2)
                if self.shapes.rows[a]["char"] == self.shapes.rows[b]["char"]:
                    continue
            else:
                a, b = self.random.choice(self.pairs[kind][self.random.choice(self.keys[kind])])
            if self.random.random() < 0.5:
                a, b = b, a
            first.append(a), second.append(b), labels.append(label[kind])
        return first, second, labels


def reader(args):
    import torch
    from han2ids.infer import Han2IDS

    encoder = Han2IDS(args.checkpoint, device=args.device).model.encoder
    for value in encoder.parameters():
        value.requires_grad_(False)
    return encoder.eval(), torch.device(args.device)


def load_ink(shapes: Shapes, indices: list[int], device):
    import torch

    order = np.argsort(indices)
    block = np.empty((len(indices), SIZE, SIZE), dtype=np.uint8)
    block[order] = shapes.pixels[np.asarray(indices)[order]]
    return (1 - torch.from_numpy(block).to(device).float().div_(255)).unsqueeze(1)


def scores(shapes: Shapes, encoder, head, taps, pairs: list[tuple[int, int]], device, batch: int = 192):
    """For each pair, the head's probability and the cosine of the mean final patch tokens."""
    import torch
    from han2ids.pairs import patch_tokens

    learned, cosine = [], []
    with torch.no_grad(), torch.autocast(device.type, dtype=torch.bfloat16, enabled=device.type == "cuda"):
        for start in range(0, len(pairs), batch):
            part = pairs[start:start + batch]
            unique = sorted({index for pair in part for index in pair})
            place = {index: at for at, index in enumerate(unique)}
            tokens = patch_tokens(encoder, pixels_of(load_ink(shapes, unique, device)), taps)
            width = tokens.size(-1) // len(taps)
            means = torch.nn.functional.normalize(tokens[..., -width:].float().mean(1), dim=1)
            a = torch.tensor([place[pair[0]] for pair in part], device=device)
            b = torch.tensor([place[pair[1]] for pair in part], device=device)
            cosine.append((means[a] * means[b]).sum(1).cpu())
            if head is not None:
                learned.append(head.score(tokens[a], tokens[b]).float().cpu())
    return (torch.cat(learned).numpy() if learned else None), torch.cat(cosine).numpy()


def area(positive: np.ndarray, negative: np.ndarray) -> float:
    """The chance that a pair of one form scores above a pair of two."""
    ranks = np.concatenate([positive, negative]).argsort().argsort() + 1
    return float((ranks[:len(positive)].sum() - len(positive) * (len(positive) + 1) / 2) / (len(positive) * len(negative)))


def flat(pairs: dict[str, list[tuple[int, int]]], chars: list[str]) -> list[tuple[int, int]]:
    return [pair for char in chars for pair in pairs.get(char, [])]


def train(args) -> None:
    import torch
    from han2ids.pairs import PairHead, patch_tokens

    torch.manual_seed(args.seed)
    shapes = Shapes(args.output, loaded=True)
    _, chosen, rest = shapes.split()
    encoder, device = reader(args)
    taps = tuple(args.taps)
    head = PairHead(encoder.num_features, taps, dim=args.dim, layers=args.layers).to(device)
    batches = Batches(shapes, rest, args.seed)
    check = shapes.pairs(chosen)
    check_same, check_apart = flat(check["same"], chosen), flat(check["apart"], chosen)
    print(f"train: {len(rest)} characters, " + ", ".join(f"{kind} {sum(map(len, found.values()))} pairs of {len(found)}"
          for kind, found in batches.pairs.items()), flush=True)
    print(f"train: checkpoint chosen on {len(check_same)} pairs of one form and {len(check_apart)} of two", flush=True)
    optimizer = torch.optim.AdamW(head.parameters(), lr=args.rate, weight_decay=0.05)
    warm = 500
    schedule = torch.optim.lr_scheduler.LambdaLR(optimizer, lambda step: min(1.0, (step + 1) / warm) * 0.5 * (
        1 + np.cos(np.pi * min(1.0, step / args.steps))))
    generator = torch.Generator(device=device).manual_seed(args.seed)
    folder = args.output / args.run
    folder.mkdir(parents=True, exist_ok=True)
    best, log, seen, started = 0.0, [], [], time.time()
    for step in range(1, args.steps + 1):
        first, second, labels = batches.take(args.batch)
        with torch.no_grad():
            ink = augment(load_ink(shapes, first + second, device), generator)
            with torch.autocast(device.type, dtype=torch.bfloat16, enabled=device.type == "cuda"):
                tokens = patch_tokens(encoder, pixels_of(ink), taps)
        head.train()
        with torch.autocast(device.type, dtype=torch.bfloat16, enabled=device.type == "cuda"):
            logits = head(tokens[:len(first)], tokens[len(first):])
        loss = torch.nn.functional.binary_cross_entropy_with_logits(logits.float(), torch.tensor(labels, device=device))
        optimizer.zero_grad(set_to_none=True)
        loss.backward()
        torch.nn.utils.clip_grad_norm_(head.parameters(), 1.0)
        optimizer.step()
        schedule.step()
        seen.append(loss.item())
        if step % args.every == 0 or step == args.steps:
            head.eval()
            same, _ = scores(shapes, encoder, head, taps, check_same, device)
            apart, _ = scores(shapes, encoder, head, taps, check_apart, device)
            found = area(same, apart)
            entry = {"step": step, "loss": round(float(np.mean(seen)), 4), "area": round(found, 4),
                     "seconds": round(time.time() - started),
                     "memory": torch.cuda.max_memory_allocated() >> 20 if device.type == "cuda" else None}
            log.append(entry)
            seen = []
            print(json.dumps(entry), flush=True)
            if found > best:
                best = found
                torch.save({"head": head.state_dict(), "settings": head.settings, "step": step, "area": found,
                            "reader": Path(args.checkpoint).name}, folder / "pairs.pt")
    (folder / "log.json").write_text(json.dumps({"args": {key: str(value) for key, value in vars(args).items()
                                                          if key != "command"}, "log": log}, indent=1) + "\n")


BANDS = ("under 0.90", "0.90 to 0.95", "0.95 and over")


def measure(args) -> None:
    import gzip

    import torch
    from han2ids.pairs import load

    shapes = Shapes(args.output)
    held, _, _ = shapes.split()
    encoder, device = reader(args)
    head = load(args.output / args.run / "pairs.pt", args.device)
    half = {char: at % 2 for at, char in enumerate(held)}
    found = shapes.pairs(held)

    def right(query: int, other: int) -> bool:
        return bool(set(shapes.rows[query]["names"]) & set(shapes.rows[other]["names"]))

    # Queries as scripts/variant_eval.py takes them: a drawing whose sequence another family draws too,
    # against that family's drawings of the character.
    queries = []
    for char in held:
        members = shapes.chars[char]
        drawn = defaultdict(set)
        for index in members:
            for name in shapes.rows[index]["named"]:
                if shapes.rows[index]["sequences"][name]:
                    drawn[name].add(shapes.rows[index]["family"])
        for query in members:
            row = shapes.rows[query]
            shared = {name for name in row["named"] if len(drawn[name]) > 1}
            if not shared:
                continue
            siblings = [other for other in members if shapes.rows[other]["family"] == row["family"] and not right(query, other)]
            own = {name for other in siblings for name in shapes.rows[other]["names"]}
            for target in sorted({item for name in shared for item in drawn[name]} - {row["family"]}):
                others = [other for other in members if shapes.rows[other]["family"] == target]
                # The candidates of forms the query's own font draws differently: no right answer among them.
                wrong = [other for other in others if not right(query, other) and set(shapes.rows[other]["names"]) & own]
                queries.append({"char": char, "query": query, "others": others, "wrong": wrong, "siblings": siblings})
    same, apart = flat(found["same"], held), flat(found["apart"], held)
    every = sorted({(item["query"], other) for item in queries for other in item["others"] + item["siblings"]}
                   | set(same) | set(apart))
    learned, cosine = scores(shapes, encoder, head, head.taps, every, device)
    # The third column is the head's score for a pair above the cosine floor, and nothing below it.
    table = {pair: (float(a), float(b), float(a) if b >= args.floor else -1.0) for pair, a, b in zip(every, learned, cosine)}
    odd = [item for item in queries if half[item["char"]] == 1]

    def band(item) -> str:
        nearest = max(table[(item["query"], other)][1] for other in item["siblings"])
        return BANDS[0] if nearest < 0.90 else BANDS[1] if nearest < 0.95 else BANDS[2]

    saved = torch.load(args.output / args.run / "pairs.pt", weights_only=True)
    report = {"reader": Path(args.checkpoint).name, "head": {key: saved[key] for key in ("step", "area", "settings")},
              "characters": sum(half.values()), "scorers": {}}
    for name, column, level in (("head", 0, None), ("cosine", 1, None), ("cosine at the floor", 1, args.floor),
                                ("head above the floor", 2, "head")):
        def value(a: int, b: int, column: int = column) -> float:
            return table[(a, b)][column]

        if level == "head":
            level = report["scorers"]["head"]["level"]
        elif level is None:
            # The level that refuses 1% of the right candidates among the even characters.
            level = float(np.quantile([value(item["query"], other) for item in queries if half[item["char"]] == 0
                                       for other in item["others"] if right(item["query"], other)], 0.01))
        others = {key: [0, 0] for key in ("all", *BANDS)}
        for item in odd:
            if item["wrong"]:
                taken = max(value(item["query"], other) for other in item["wrong"]) >= level
                for key in ("all", band(item)):
                    others[key][0] += 1
                    others[key][1] += taken
        one = np.array([value(*pair) for pair in same if half[shapes.rows[pair[0]]["char"]] == 1])
        two = np.array([value(*pair) for pair in apart if half[shapes.rows[pair[0]]["char"]] == 1])
        report["scorers"][name] = {
            "level": round(level, 4), "queries": len(odd),
            "best_right": sum(right(item["query"], max(item["others"], key=lambda other: value(item["query"], other)))
                              for item in odd),
            "right_refused": sum(max(value(item["query"], other) for other in item["others"] if right(item["query"], other))
                                 < level for item in odd),
            "others": others,
            "one_form": [len(one), int((one < level).sum())], "two_forms": [len(two), int((two >= level).sum())],
            "area": round(area(one, two), 4),
        }
    text = json.dumps(report, indent=1, ensure_ascii=False)
    (args.output / args.run / "measure.json").write_text(text + "\n")
    with gzip.open(args.output / args.run / "pairs.jsonl.gz", "wt", encoding="utf-8") as out:
        for kind, pairs in (("one", same), ("two", apart)):
            for a, b in pairs:
                first, second = shapes.rows[a], shapes.rows[b]
                out.write(json.dumps({
                    "forms": kind, "half": half[first["char"]], "char": first["char"], "shapes": [a, b],
                    "families": [first["family"], second["family"]], "names": [first["names"], second["names"]],
                    "head": round(table[(a, b)][0], 4), "cosine": round(table[(a, b)][1], 4),
                }, ensure_ascii=False) + "\n")
    print(text)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["draw", "train", "measure"])
    parser.add_argument("--output", type=Path, default=ROOT / "build/pairs")
    parser.add_argument("--checkpoint", default=str(ROOT / "models/han2ids-v0.5.pt"))
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--seed", type=int, default=20261115)
    parser.add_argument("--limit", type=int, default=None, help="draw only this many characters")
    parser.add_argument("--workers", type=int, default=4, help="processes that draw")
    parser.add_argument("--run", default="head")
    parser.add_argument("--taps", type=int, nargs="+", default=[5, 8, 11], help="encoder blocks whose tokens the head reads")
    parser.add_argument("--dim", type=int, default=256)
    parser.add_argument("--layers", type=int, default=2)
    parser.add_argument("--steps", type=int, default=8000)
    parser.add_argument("--batch", type=int, default=128)
    parser.add_argument("--rate", type=float, default=3e-4)
    parser.add_argument("--every", type=int, default=500, help="steps between checks of the head")
    parser.add_argument("--floor", type=float, default=0.93, help="the cosine floor of the variant match")
    args = parser.parse_args()
    {"draw": draw, "train": train, "measure": measure}[args.command](args)


if __name__ == "__main__":
    main()
