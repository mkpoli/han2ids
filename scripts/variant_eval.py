#!/usr/bin/env python3
"""Measure the variant matcher: one font's drawing of a form against the other fonts' candidates.

Three questions, each on a seeded sample:

cross     A sequence that two font families both draw is taken from one family and matched against
          the candidates of the other, of every other family, and of every family with the query
          drawn again at 96 px. The same queries are matched against only the forms the query's own
          font draws differently, and against the candidates of another character: a random one, and
          the one of the sample that scores highest.
regional  A character is taken from each regional face of another Noto file (another weight, or the
          sans design) and matched against the default candidates.

The script writes one row per query with every candidate's score, then summarises the rows with the
given thresholds. Characters at even positions of the sample set the thresholds; the tables report the
odd positions. `--rows` summarises an earlier run again without drawing or embedding anything.

Example:
    python scripts/variant_eval.py --output build/variants --device cpu --threads 4
    python scripts/variant_eval.py --rows docs/variant-match/rows-v0.5.jsonl.gz --floor 0.93 --margin 0.03
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import random
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
NOTO = Path("/usr/share/fonts/opentype/noto")
QUERY_FONTS = {"Noto Serif CJK Bold": NOTO / "NotoSerifCJK-Bold.ttc", "Noto Sans CJK Regular": NOTO / "NotoSansCJK-Regular.ttc"}


def family(file: str) -> str:
    return re.sub(r"\d+$", "", Path(file).stem)


def distances(mask):
    """Each cell's distance to the nearest ink cell."""
    import numpy as np
    rows, columns = np.arange(mask.shape[0]), np.arange(mask.shape[1])
    down = np.where(mask[None], np.abs(rows[:, None, None] - rows[None, :, None]), 1e6).min(axis=1)
    return np.sqrt((down[:, None, :] ** 2 + (columns[None, :, None] - columns[None, None, :]) ** 2).min(axis=2))


def collect(args) -> list[dict]:
    import numpy as np
    import torch
    from PIL import Image
    from han2ids.infer import Han2IDS
    from PIL import ImageFont
    from han2ids.variants import Forms, VariantMatcher, faces, frame, framed

    torch.set_num_threads(args.threads)
    matcher = VariantMatcher(Han2IDS(args.checkpoint, device=args.device))
    forms = matcher.forms
    store = args.output / "vectors.npz"
    known = dict(np.load(store)) if store.is_file() else {}

    def vectors(images):
        keys = [hashlib.sha256(image.tobytes()).hexdigest() for image in images]
        missing = {key: image for key, image in zip(keys, images) if key not in known}
        for key, vector in zip(missing, matcher.embed(list(missing.values()))):
            known[key] = vector
        return np.stack([known[key] for key in keys]) if keys else np.zeros((0, 384), dtype=np.float32)

    def entry(score, shape):
        return [round(float(score), 4), shape.names, family(shape.file), shape.regions]

    pens = {}

    def small(shape):
        """The shape drawn again at 96 px and framed as an image given to the matcher is."""
        key = (shape.file, shape.index)
        if key not in pens:
            pens[key] = ImageFont.truetype(shape.file, 96, index=shape.index, layout_engine=ImageFont.Layout.RAQM)
        return framed(frame(pens[key], shape.candidates[0].text))

    rows: list[dict] = []
    order = sorted({base for base, _ in forms.registered})
    random.Random(args.seed).shuffle(order)
    sample = []
    for base in order:
        if len(sample) >= args.bases:
            break
        shapes = forms.shapes(chr(base))
        drawn = defaultdict(set)
        for shape in shapes:
            for item in shape.candidates:
                if item.kind == "ivs":
                    drawn[item.name].add(family(shape.file))
        if any(len(families) > 1 for families in drawn.values()):
            sample.append((chr(base), shapes, drawn))
    every = [shape for _, shapes, _ in sample for shape in shapes]
    owner = np.array([at for at, (_, shapes, _) in enumerate(sample) for _ in shapes])
    matrix = vectors([shape.image for shape in every])
    np.savez(store, **known)
    print(f"cross: {len(sample)} characters, {len(every)} shapes", flush=True)
    # The two bitmap measures the encoder is compared with: overlap at 64 px, mean nearest-ink distance at 96 px.
    coarse = [np.asarray(shape.image.resize((64, 64), Image.Resampling.BOX)) < 128 for shape in every]
    fine = [np.asarray(shape.image.resize((96, 96), Image.Resampling.BOX)) < 128 for shape in every]
    reach = [distances(mask) for mask in fine]

    def overlap(a, b):
        return (coarse[a] & coarse[b]).sum() / max(1, (coarse[a] | coarse[b]).sum())

    def chamfer(a, b):
        return -(reach[b][fine[a]].mean() + reach[a][fine[b]].mean()) / 2

    asked = [shape for _, shapes, drawn in sample for shape in shapes
             if any(len(drawn.get(name, ())) > 1 for name in shape.names)]
    again = dict(zip(map(id, asked), vectors([small(shape) for shape in asked])))
    np.savez(store, **known)
    print(f"cross: {len(asked)} queries", flush=True)
    picker = random.Random(args.seed + 1)
    start = 0
    for at, (char, shapes, drawn) in enumerate(sample):
        mine = matrix[start:start + len(shapes)]
        for index, shape in enumerate(shapes):
            source = family(shape.file)
            shared = [name for name in shape.names if len(drawn.get(name, ())) > 1]
            if not shared:
                continue
            scores = mine @ mine[index]
            apart = [(float(scores[k]), other) for k, other in enumerate(shapes)
                     if family(other.file) == source and not set(other.names) & set(shape.names)]
            siblings = [score for score, _ in apart]
            own = sorted({name for _, other in apart for name in other.names})
            rest = matrix @ mine[index]
            rest[owner == at] = -1
            per_char = np.full(len(sample), -1.0)
            np.maximum.at(per_char, owner, rest)
            other_char = picker.choice([k for k in range(len(sample)) if k != at])
            targets = sorted({name for item in shared for name in drawn[item]} - {source})
            for target in [*targets, "every other family", "every family"]:
                if target == "every family":
                    others = list(zip(mine @ again[id(shape)], shapes))
                else:
                    others = [(scores[k], other) for k, other in enumerate(shapes)
                              if family(other.file) != source and target in (family(other.file), "every other family")]
                held = {name for _, other in others for name in other.names}
                bitmap = {}
                if target in targets:
                    places = [k for k, other in enumerate(shapes) if family(other.file) == target]
                    for label, measure in (("overlap", overlap), ("chamfer", chamfer)):
                        best = max(places, key=lambda k: measure(start + index, start + k))
                        bitmap[label] = bool(set(shapes[best].names) & set(shape.names))
                collections = sorted({collection for item in shape.candidates if item.name in shared and item.name in held
                                      for collection, _ in item.registrations})
                rows.append({
                    "kind": "cross", "half": at % 2, "char": char, "from": source, "to": target, "names": shape.names,
                    "collections": collections, "bitmap": bitmap,
                    "scored": sorted((entry(score, other) for score, other in others), reverse=True),
                    "sibling": round(max(siblings), 4) if siblings else None, "own": own,
                    "random": round(float(per_char[other_char]), 4), "nearest": round(float(per_char.max()), 4),
                    "nearest_char": sample[int(per_char.argmax())][0],
                })
        start += len(shapes)

    regional = [face for face in forms.faces if face.region]
    covered = sorted(set.intersection(*(set(face.cmap) for face in regional)))
    covered = [point for point in covered if unicodedata.name(chr(point), "").startswith("CJK UNIFIED IDEOGRAPH")]
    random.Random(args.seed + 2).shuffle(covered)
    designs = Counter()
    split = []
    for point in covered[:args.outlines]:
        groups = defaultdict(list)
        for face in regional:
            image = frame(face.pen, chr(point))
            groups[np.packbits(np.asarray(image) < 128).tobytes()].append(face.region)
        designs[len(groups)] += 1
        if len(groups) > 1:
            split.append(chr(point))
    rows.append({"kind": "outlines", "characters": min(args.outlines, len(covered)), "covered": len(covered),
                 "designs": dict(sorted(designs.items()))})
    for name, path in QUERY_FONTS.items():
        if not path.is_file():
            print(f"regional: {path} is absent, skipped", flush=True)
            continue
        query_faces = [face for face in faces(path) if face.region and "Mono" not in face.font]
        for at, char in enumerate(split[:args.regional]):
            groups: dict[bytes, list] = {}
            for face in query_faces:
                if ord(char) not in face.cmap:
                    continue
                image = frame(face.pen, char)
                groups.setdefault(np.packbits(np.asarray(image) < 128).tobytes(), [image, []])[1].append(face.region)
            shapes = forms.shapes(char)
            base = vectors([shape.image for shape in shapes])
            for image, regions in groups.values():
                scores = base @ vectors([image])[0]
                rows.append({"kind": "regional", "half": at % 2, "char": char, "from": name, "regions": regions,
                             "scored": sorted((entry(score, shape) for score, shape in zip(scores, shapes)), reverse=True)})
        np.savez(store, **known)
        print(f"regional: {name}, {min(args.regional, len(split))} characters", flush=True)
    return rows


def verdict(scored, floor, margin, ratio):
    from han2ids.variants import decide
    kind, reason, near = decide([(score, SimpleNamespace(names=names, regions=regions))
                                 for score, names, _, regions in scored], floor, margin, ratio)
    names = list(dict.fromkeys(name for shape in near for name in shape.names))
    return kind, reason, names or ["plain"], sorted({region for shape in near for region in shape.regions})


def cross(rows, floor, margin, ratio):
    """Outcome counts of the cross-font queries, by collection and by direction of the fonts."""
    by = defaultdict(Counter)
    for row in rows:
        kind, _, names, _ = verdict(row["scored"], floor, margin, ratio)
        hit = bool(set(names) & set(row["names"]))
        outcome = {"matched": "single" if hit else "wrong", "ambiguous": "within" if hit else "outside", "none": "none"}[kind]
        for key in ["all", *row["collections"], f"{row['from']} to {row['to']}"]:
            by[key][outcome] += 1
            by[key]["n"] += 1
            if outcome == "within":
                by[key]["listed"] += len(names)
        top = row["scored"][0] if row["scored"] else None
        by["all"]["top1"] += bool(top and set(top[1]) & set(row["names"]))
    return by


def held_out(rows, floor, margin, ratio):
    """Verdicts against only the forms the query's own font draws differently, by the nearest such form's score."""
    by = defaultdict(Counter)
    for row in rows:
        scored = [item for item in row["scored"] if not set(item[1]) & set(row["names"]) and set(item[1]) & set(row["own"])]
        if not scored:
            continue
        kind = verdict(scored, floor, margin, ratio)[0]
        sibling = row["sibling"]
        band = "under 0.90" if sibling < 0.90 else "0.90 to 0.95" if sibling < 0.95 else "0.95 and over"
        for key in ["all", band]:
            by[key][kind] += 1
            by[key]["n"] += 1
    return by


def regional(rows, floor, margin, ratio):
    by = defaultdict(Counter)
    for row in rows:
        kind, _, _, regions = verdict(row["scored"], floor, margin, ratio)
        truth = set(row["regions"])
        if kind == "none":
            outcome = "none"
        elif not regions:
            outcome = "no region"
        elif set(regions) == truth:
            outcome = "exact"
        elif truth <= set(regions):
            outcome = "wider"
        elif truth & set(regions):
            outcome = "partial"
        else:
            outcome = "wrong"
        by[row["from"]][outcome] += 1
        by[row["from"]]["n"] += 1
        best = next((set(item[3]) for item in row["scored"] if item[3]), set())
        by[row["from"]]["top"] += bool(best & truth)
    return by


def share(count, total):
    return f"{count} ({100 * count / total:.1f}%)" if total else "0"


OUTCOMES = ("single", "within", "wrong", "outside", "none")


def summarise(rows, floor, margin, ratio, out=print):
    crossing = [row for row in rows if row["kind"] == "cross"]
    pairs = [row for row in crossing if not row["to"].startswith("every")]
    fit_half, test = [row for row in pairs if row["half"] == 0], [row for row in pairs if row["half"] == 1]
    out(f"Even half, {len(fit_half)} queries of {len({row['char'] for row in fit_half})} characters, ratio {ratio}\n")
    out("| Floor | Margin | One form, right | Several, right one listed | One form, wrong | Several, right one missing | None "
        "| Random other character | Highest-scoring other character | Other forms only |")
    out("| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
    for trial_floor in (0.90, 0.92, 0.93, 0.94, 0.95):
        for trial_margin in (0.0, 0.01, 0.02, 0.03, 0.05):
            counts = cross(fit_half, trial_floor, trial_margin, ratio)["all"]
            held = held_out(fit_half, trial_floor, trial_margin, ratio)["all"]
            n = counts["n"]
            out(f"| {trial_floor:.2f} | {trial_margin:.2f} | " + " | ".join(f"{100 * counts[key] / n:.1f}%" for key in OUTCOMES)
                + f" | {100 * sum(row['random'] >= trial_floor for row in fit_half) / n:.1f}%"
                + f" | {100 * sum(row['nearest'] >= trial_floor for row in fit_half) / n:.1f}%"
                + f" | {100 * (held['n'] - held['none']) / max(1, held['n']):.1f}% |")

    def line(key, row):
        n = row["n"]
        listed = f", {row['listed'] / row['within']:.1f} listed" if row["within"] else ""
        return (f"| {key} | {n} | {share(row['single'], n)} | {share(row['within'], n)}{listed} | {share(row['wrong'], n)} "
                f"| {share(row['outside'], n)} | {share(row['none'], n)} |")

    head = ("| | Queries | One form, right | Several forms, right one listed | One form, wrong | Several forms, right one missing | None |\n"
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: |")
    out(f"\nOdd half, {len(test)} queries of {len({row['char'] for row in test})} characters; "
        f"floor {floor}, margin {margin}, ratio {ratio}\n")
    out(head)
    counts = cross(test, floor, margin, ratio)
    for key in sorted(counts, key=lambda name: (name != "all", " to " in name, name)):
        out(line(key, counts[key]))
    n = counts["all"]["n"]
    out(f"\nBest-scoring candidate carries the query's name: encoder {share(counts['all']['top1'], n)}, "
        + ", ".join(f"{label} {share(sum(row['bitmap'][label] for row in test), n)}" for label in ("overlap", "chamfer")) + "\n")
    out(head)
    for target, trial, label in (("every other family", ratio, "every other family at once"),
                                 ("every family", ratio, "every family, the query drawn at 96 px"),
                                 ("every family", 1e9, "the same without the ratio")):
        pooled = [row for row in crossing if row["to"] == target and row["half"] == 1]
        out(line(label, cross(pooled, floor, margin, trial)["all"]))
    n = len(test)
    out("\n| Query against | Queries | Matched or ambiguous |")
    out("| --- | ---: | ---: |")
    out(f"| a random other character | {n} | {share(sum(row['random'] >= floor for row in test), n)} |")
    out(f"| the highest-scoring other character of the sample | {n} | {share(sum(row['nearest'] >= floor for row in test), n)} |")
    held = held_out(test, floor, margin, ratio)
    for key in ("all", "under 0.90", "0.90 to 0.95", "0.95 and over"):
        row = held[key]
        if row["n"]:
            label = "the other forms of its character" if key == "all" else f"the other forms, the nearest scoring {key} in the query's font"
            out(f"| {label} | {row['n']} | {share(row['n'] - row['none'], row['n'])} |")
    for row in rows:
        if row["kind"] == "outlines":
            out(f"\nRegional outlines, {row['characters']} of {row['covered']} characters all five faces map: "
                + ", ".join(f"{count} with {designs} design{'s' if int(designs) > 1 else ''}"
                            for designs, count in row["designs"].items()))
    queries = [row for row in rows if row["kind"] == "regional" and row["half"] == 1]
    if queries:
        out("\n| Query face | Queries | Exact regions | Right regions and more | Some right | Wrong | No regional face | None | Best regional candidate right |")
        out("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
        for name, row in regional(queries, floor, margin, ratio).items():
            n = row["n"]
            out(f"| {name} | {n} | " + " | ".join(share(row[key], n) for key in
                                                 ("exact", "wider", "partial", "wrong", "no region", "none", "top")) + " |")


def main(argv=None) -> int:
    from han2ids.variants import FLOOR, MARGIN_OF_BEST, RATIO
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", type=Path, default=ROOT / "build/variants")
    parser.add_argument("--rows", type=Path, help="summarise this earlier run instead of collecting")
    parser.add_argument("--checkpoint", type=Path, default=ROOT / "models/han2ids-v0.5.pt")
    parser.add_argument("--device", default=None)
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--seed", type=int, default=20261115)
    parser.add_argument("--bases", type=int, default=1500, help="characters with a sequence two families draw")
    parser.add_argument("--outlines", type=int, default=3000, help="characters whose regional outlines are compared")
    parser.add_argument("--regional", type=int, default=500, help="characters with more than one regional design")
    parser.add_argument("--floor", type=float, default=FLOOR)
    parser.add_argument("--margin", type=float, default=MARGIN_OF_BEST)
    parser.add_argument("--ratio", type=float, default=RATIO)
    args = parser.parse_args(argv)

    if args.rows:
        with (gzip.open if args.rows.suffix == ".gz" else open)(args.rows, "rt", encoding="utf-8") as handle:
            rows = [json.loads(line) for line in handle]
    else:
        args.output.mkdir(parents=True, exist_ok=True)
        rows = collect(args)
        with open(args.output / "rows.jsonl", "w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    summarise(rows, args.floor, args.margin, args.ratio)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
