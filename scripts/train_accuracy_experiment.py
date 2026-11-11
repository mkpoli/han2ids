"""Continue a checkpoint and compare agreement on matched validation renders.

This experiment reports agreement with existing labels, not visual accuracy.
It reads only the train and val cache files and writes a new output directory.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import math
import os
import random
import sys
from collections import defaultdict
from contextlib import nullcontext
from pathlib import Path

# Required by deterministic CUDA matrix operations; set before importing torch.
os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")

import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image, features, __version__ as pillow_version
from torch.optim import AdamW
from torch.optim.lr_scheduler import LambdaLR
from torch.utils.data import DataLoader, Dataset

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from han2ids.grammar import generate
from han2ids.model import GlyphIDS
from han2ids.status import gold
from han2ids.tokenizer import BOS, EOS, PAD, Vocabulary


def safe_path(path: Path) -> str:
    """Identify a resolved path without exposing the home directory."""
    resolved = Path(path).resolve()
    home = Path.home().resolve()
    try:
        relative = resolved.relative_to(home)
    except ValueError:
        return str(resolved)
    return "$HOME" if relative == Path(".") else f"$HOME/{relative.as_posix()}"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def derived_seed(seed: int, *parts: object) -> int:
    encoded = json.dumps([seed, *parts], ensure_ascii=False, separators=(",", ":"))
    return int.from_bytes(hashlib.sha256(encoded.encode()).digest()[:8], "big")


def sample_rows(rows: list[dict], limit: int | None, seed: int, split: str) -> list[tuple[int, dict]]:
    """Select entire characters by a stable seeded rank and retain cache order."""
    if limit is not None and limit <= 0:
        raise ValueError("character limits must be positive")
    chars = {row["char"] for row in rows}
    ordered = sorted(chars, key=lambda char: (derived_seed(seed, split, char), char))
    selected = set(ordered if limit is None else ordered[:limit])
    return [(i, row) for i, row in enumerate(rows) if row["char"] in selected]


def read_split(cache: Path, split: str, limit: int | None, seed: int):
    if split not in ("train", "val"):
        raise ValueError("only train and val are permitted")
    path = cache / f"{split}.jsonl"
    rows = []
    with path.open(encoding="utf-8") as stream:
        for line_no, line in enumerate(stream, 1):
            if not line.strip():
                raise ValueError(f"blank row in {path}:{line_no}")
            row = json.loads(line)
            if not all(isinstance(row.get(k), str) and row[k] for k in ("char", "font", "ids")):
                raise ValueError(f"invalid row in {path}:{line_no}")
            if len(row["char"]) != 1 or row.get("split", split) != split:
                raise ValueError(f"invalid character or split in {path}:{line_no}")
            rows.append(row)
    images = np.load(cache / f"{split}.npy", mmap_mode="r", allow_pickle=False)
    if images.shape != (len(rows), 224, 224) or images.dtype != np.uint8:
        raise ValueError(f"{split} images must be uint8 with shape ({len(rows)}, 224, 224)")
    selected = sample_rows(rows, limit, seed, split)
    if not selected:
        raise ValueError(f"{split} split is empty")
    return selected, images


def validate_rows(train, val, vocab, max_len: int, fonts: dict) -> None:
    overlap = {r["char"] for _, r in train} & {r["char"] for _, r in val}
    if overlap:
        raise ValueError(f"train/val character overlap: {len(overlap)} characters")
    for split, rows in (("train", train), ("val", val)):
        for index, row in rows:
            if row["font"] not in fonts:
                raise ValueError(f"missing font family {row['font']!r} for {split} row {index}")
            label = gold(row["char"], row["font"], row["ids"])
            missing = sorted(set(label) - vocab.stoi.keys())
            if missing:
                raise ValueError(f"unknown label tokens in {split} row {index}: {missing}")
            if len(label) + 2 > max_len:
                raise ValueError(f"label too long in {split} row {index}: {len(label) + 2} > {max_len}")


def parse_fonts(specs: list[str]) -> dict[str, list[tuple[Path, int]]]:
    fonts: dict[str, list[tuple[Path, int]]] = {}
    for spec in specs:
        try:
            family, index, path = spec.split("=", 2)
            index = int(index)
        except ValueError as exc:
            raise ValueError(f"invalid --font {spec!r}; expected family=index=path") from exc
        if not family or index < 0 or not path:
            raise ValueError(f"invalid --font {spec!r}")
        resolved = Path(path).expanduser().resolve(strict=True)
        if not resolved.is_file():
            raise ValueError(f"font is not a file: {resolved}")
        fonts.setdefault(family, []).append((resolved, index))
    return fonts


def create_output(path: Path) -> None:
    # mkdir is atomic and refuses existing directories, including empty ones.
    path.mkdir(parents=False, exist_ok=False)


def image_tensor(image: Image.Image) -> torch.Tensor:
    if image.mode != "L" or image.size != (224, 224):
        raise ValueError("renderer and augmentation must return a 224x224 grayscale image")
    return torch.from_numpy(np.array(image, dtype=np.uint8, copy=True)).float().div_(255).unsqueeze(0).repeat(3, 1, 1).sub_(0.5).div_(0.5)


class Rows(Dataset):
    def __init__(self, rows, images, vocab, renderer, condition, seed, augmented=False):
        self.rows, self.images, self.vocab = rows, images, vocab
        self.renderer, self.condition, self.seed, self.augmented = renderer, condition, seed, augmented
        self.epoch = 0

    def __len__(self):
        return len(self.rows)

    def __getitem__(self, position):
        index, row = self.rows[position]
        if self.condition == "legacy":
            image = Image.fromarray(np.array(self.images[index], copy=True), mode="L")
        else:
            image = self.renderer.render(row["char"], row["font"])
        if self.augmented:
            from han2ids.augmentation import augment
            image = augment(image, random.Random(derived_seed(self.seed, "augmentation", self.epoch, index)))
        label = gold(row["char"], row["font"], row["ids"])
        tokens = [BOS, *[self.vocab.stoi[ch] for ch in label], EOS]
        return image_tensor(image), torch.tensor(tokens, dtype=torch.long)


def collate(batch):
    x = torch.stack([item[0] for item in batch])
    y = torch.full((len(batch), max(len(item[1]) for item in batch)), PAD, dtype=torch.long)
    for i, (_, tokens) in enumerate(batch):
        y[i, :len(tokens)] = tokens
    return x, y


def agreement(records):
    """Micro row agreement and equal-character macro agreement, overall and by font."""
    def summary(items):
        by_char = defaultdict(list)
        for item in items:
            by_char[item["char"]].append(int(item["exact"]))
        return {"rows": len(items), "characters": len(by_char),
                "exact_row_agreement": sum(int(x["exact"]) for x in items) / len(items),
                "exact_character_macro_agreement": sum(sum(v) / len(v) for v in by_char.values()) / len(by_char)}
    by_font = defaultdict(list)
    for record in records:
        by_font[record["font"]].append(record)
    return {"overall": summary(records), "per_font": {font: summary(items) for font, items in sorted(by_font.items())}}


@torch.no_grad()
def evaluate(model, rows, images, vocab, renderer, condition, batch_size, output):
    dataset = Rows(rows, images, vocab, renderer, condition, 0)
    loader = DataLoader(dataset, batch_size=batch_size, shuffle=False, collate_fn=collate, num_workers=0, drop_last=False)
    records = []
    offset = 0
    with output.open("x", encoding="utf-8") as stream:
        for x, _ in loader:
            tokens, _ = generate(model, x.cuda(), vocab.itos, max_len=model.max_len)
            for token_ids in tokens.tolist():
                index, row = rows[offset]
                label = gold(row["char"], row["font"], row["ids"])
                pred = vocab.decode(token_ids)
                record = {"row_index": index, "char": row["char"], "font": row["font"],
                          "gold": label, "prediction": pred, "token_ids": token_ids, "exact": pred == label}
                stream.write(json.dumps(record, ensure_ascii=False) + "\n")
                records.append({"char": row["char"], "font": row["font"], "exact": pred == label})
                offset += 1
    if offset != len(rows):
        raise RuntimeError(f"evaluation returned {offset} predictions for {len(rows)} rows")
    return agreement(records)


def evaluate_conditions(model, rows, images, vocab, renderer, batch_size, out_dir, epoch):
    results = {}
    for condition in ("legacy", "clean"):
        output = out_dir / f"val_epoch_{epoch}_{condition}.jsonl"
        results[condition] = evaluate(model, rows, images, vocab, renderer, condition, batch_size, output)
        results[condition]["predictions_sha256"] = sha256_file(output)
    return results


def positive_int(value):
    try:
        result = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a positive integer") from exc
    if result <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return result


def positive_float(value):
    try:
        result = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a positive finite number") from exc
    if not math.isfinite(result) or result <= 0:
        raise argparse.ArgumentTypeError("must be a positive finite number")
    return result


def gpu_fraction(value):
    result = positive_float(value)
    if result > 1:
        raise argparse.ArgumentTypeError("must be in (0, 1]")
    return result


def guard_cuda_memory(fraction, min_free_gib):
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required for training")
    free_bytes, total_bytes = torch.cuda.mem_get_info()
    if free_bytes < min_free_gib * (1024 ** 3):
        raise RuntimeError(f"Insufficient free CUDA memory: {free_bytes} bytes free; "
                           f"{min_free_gib} GiB required")
    torch.cuda.set_per_process_memory_fraction(fraction)
    return {"requested_allocator_fraction": fraction,
            "min_free_gib": min_free_gib,
            "free_bytes": free_bytes, "total_bytes": total_bytes,
            "allocator_fraction_note": "The allocator fraction excludes CUDA context memory."}


def update_count(microbatches, accumulation_steps, epochs):
    return ((microbatches + accumulation_steps - 1) // accumulation_steps) * epochs


def make_optimizer(model, encoder_lr, decoder_lr):
    encoder = [p for name, p in model.named_parameters() if name.startswith("encoder.")]
    decoder = [p for name, p in model.named_parameters() if not name.startswith("encoder.")]
    return AdamW([{"params": encoder, "lr": encoder_lr}, {"params": decoder, "lr": decoder_lr}], weight_decay=0.05)


def make_scheduler(optimizer, steps):
    return LambdaLR(optimizer, lambda step: min(1, step / max(1, steps // 20)) * 0.5 * (1 + math.cos(math.pi * step / max(1, steps))))


def train_epoch(model, loader, optimizer, scheduler, accumulation_steps, device, label_smoothing=0.05, gradient_clip=1.0):
    """Normalize each accumulated gradient by the group's non-padding targets."""
    model.train()
    optimizer.zero_grad(set_to_none=True)
    loss_sum = 0.0
    rows = tokens = updates = group_tokens = group_batches = 0

    def step():
        nonlocal updates, group_tokens, group_batches
        if not group_tokens:
            raise ValueError("training group contains no non-PAD target tokens")
        for parameter in model.parameters():
            if parameter.grad is not None:
                parameter.grad.div_(group_tokens)
        torch.nn.utils.clip_grad_norm_(model.parameters(), gradient_clip, error_if_nonfinite=True)
        optimizer.step()
        scheduler.step()
        optimizer.zero_grad(set_to_none=True)
        updates += 1
        group_tokens = group_batches = 0

    for x, y in loader:
        batch_tokens = y[:, 1:].ne(PAD).sum().item()
        x, y = x.to(device), y.to(device)
        autocast = torch.autocast("cuda", dtype=torch.bfloat16) if torch.device(device).type == "cuda" else nullcontext()
        with autocast:
            logits = model(x, y[:, :-1])
            loss = F.cross_entropy(logits.reshape(-1, logits.size(-1)), y[:, 1:].reshape(-1),
                                   ignore_index=PAD, label_smoothing=label_smoothing, reduction="sum")
        loss.backward()
        loss_sum += loss.item()
        rows += len(x)
        tokens += batch_tokens
        group_tokens += batch_tokens
        group_batches += 1
        if group_batches == accumulation_steps:
            step()
    if group_batches:
        step()
    if not tokens:
        raise ValueError("training epoch contains no non-PAD target tokens")
    return {"train_rows": rows, "train_tokens": tokens, "train_updates": updates,
            "train_loss_token_weighted": loss_sum / tokens}


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cache", type=Path, required=True)
    p.add_argument("--init", type=Path, required=True)
    p.add_argument("--out-dir", type=Path, required=True)
    p.add_argument("--font", action="append", required=True, metavar="FAMILY=INDEX=PATH")
    p.add_argument("--render", choices=("legacy", "clean"), required=True)
    p.add_argument("--augment", action="store_true")
    p.add_argument("--epochs", type=int, required=True)
    p.add_argument("--batch-size", type=int, required=True, help="training microbatch size")
    p.add_argument("--accumulation-steps", type=positive_int, default=1)
    p.add_argument("--eval-batch-size", type=positive_int, help="evaluation batch size (default: training microbatch size)")
    p.add_argument("--encoder-lr", type=positive_float, default=5e-5)
    p.add_argument("--decoder-lr", type=positive_float, default=2.5e-4)
    p.add_argument("--gpu-fraction", type=gpu_fraction, required=True, help="PyTorch CUDA allocator fraction in (0, 1]")
    p.add_argument("--min-free-gib", type=positive_float, required=True, help="minimum free CUDA memory in GiB")
    p.add_argument("--seed", type=int, required=True)
    p.add_argument("--sample-seed", type=int, required=True, help="cohort sampling seed, independent of training seed")
    p.add_argument("--max-train-characters", type=int)
    p.add_argument("--max-val-characters", type=int)
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    if args.epochs <= 0 or args.batch_size <= 0 or not 0 <= args.seed < 2**32 or not 0 <= args.sample_seed < 2**32:
        raise ValueError("epochs and batch size must be positive; seeds must be in [0, 2**32)")
    if args.eval_batch_size is None:
        args.eval_batch_size = args.batch_size
    if os.environ.get("CUBLAS_WORKSPACE_CONFIG") not in (":4096:8", ":16:8"):
        raise ValueError("CUBLAS_WORKSPACE_CONFIG must be :4096:8 or :16:8 for deterministic CUDA")
    # Fail before doing work if the destination already exists.
    if args.out_dir.exists() or args.out_dir.is_symlink():
        raise FileExistsError(args.out_dir)
    fonts = parse_fonts(args.font)
    train, train_images = read_split(args.cache, "train", args.max_train_characters, args.sample_seed)
    microbatches_per_epoch = (len(train) + args.batch_size - 1) // args.batch_size
    updates_per_epoch = update_count(microbatches_per_epoch, args.accumulation_steps, 1)
    if updates_per_epoch * args.epochs < 2:
        raise ValueError("training requires at least two optimizer updates because the initial learning rate is zero")
    val, val_images = read_split(args.cache, "val", args.max_val_characters, args.sample_seed)
    # Check the complete split, including rows excluded by smoke-test sampling.
    all_train, _ = read_split(args.cache, "train", None, args.seed)
    all_val, _ = read_split(args.cache, "val", None, args.seed)
    if {r["char"] for _, r in all_train} & {r["char"] for _, r in all_val}:
        raise ValueError("train and val cache splits overlap by character")
    del all_train, all_val
    payload = torch.load(args.init, map_location="cpu", weights_only=False)
    vocab = Vocabulary(payload["itos"])
    max_len = payload["args"].get("max_len", 48)
    validate_rows(train, val, vocab, max_len, fonts)
    cuda_memory = guard_cuda_memory(args.gpu_fraction, args.min_free_gib)
    from han2ids.training_render import FontRenderer
    renderer = FontRenderer(fonts)
    create_output(args.out_dir)
    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    torch.cuda.manual_seed_all(args.seed)
    torch.use_deterministic_algorithms(True)
    torch.backends.cudnn.benchmark = False
    torch.backends.cudnn.deterministic = True
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    settings = {"training_protocol_version": 2,
                "cache": safe_path(args.cache), "init": safe_path(args.init),
                "render": args.render, "augment": args.augment, "epochs": args.epochs,
                "batch_size": args.batch_size, "microbatch_size": args.batch_size,
                "accumulation_steps": args.accumulation_steps,
                "effective_nominal_batch_size": args.batch_size * args.accumulation_steps,
                "eval_batch_size": args.eval_batch_size,
                "microbatches_per_epoch": microbatches_per_epoch, "updates_per_epoch": updates_per_epoch,
                "total_updates": updates_per_epoch * args.epochs,
                "seed": args.seed, "sample_seed": args.sample_seed,
                "max_train_characters": args.max_train_characters, "max_val_characters": args.max_val_characters,
                "fonts": {family: [{"path": safe_path(path), "index": index, "sha256": sha256_file(path)}
                                   for path, index in faces] for family, faces in fonts.items()},
                "inputs_sha256": {safe_path(path): sha256_file(path) for path in
                                  [args.init, *[args.cache / f"{part}.{ext}" for part in ("train", "val") for ext in ("jsonl", "npy")],
                                   *[ROOT / "data" / name for name in ("IDS.TXT", "label-overrides.tsv", "font-label-overrides.tsv")]]},
                "code_sha256": {str(path.relative_to(ROOT)): sha256_file(path) for path in
                                [Path(__file__).resolve(), *[ROOT / "src/han2ids" / name for name in
                                 ("model.py", "grammar.py", "tokenizer.py", "status.py", "labels.py",
                                  "training_render.py", "augmentation.py")]]},
                "python_version": sys.version, "torch_version": torch.__version__, "numpy_version": np.__version__,
                "timm_version": importlib.metadata.version("timm"), "torchvision_version": importlib.metadata.version("torchvision"),
                "pillow_version": pillow_version, "freetype_version": features.version("freetype2"),
                "fonttools_version": importlib.metadata.version("fonttools"), "cuda_version": torch.version.cuda,
                "cudnn_version": torch.backends.cudnn.version(), "cuda_device": torch.cuda.get_device_name(),
                "cuda_memory": cuda_memory,
                "cublas_workspace_config": os.environ["CUBLAS_WORKSPACE_CONFIG"],
                "metric_note": "Agreement with existing labels; labels are not independently reviewed visual gold.",
                "optimizer": {"name": "AdamW", "encoder_lr": args.encoder_lr, "other_lr": args.decoder_lr,
                              "weight_decay": 0.05, "label_smoothing": 0.05, "gradient_clip": 1.0,
                              "schedule": "linear warmup 5% and cosine decay",
                              "gradient_reduction": "token-weighted per accumulation group", "drop_last": False}}
    (args.out_dir / "settings.json").write_text(json.dumps(settings, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for split, rows in (("train", train), ("val", val)):
        with (args.out_dir / f"{split}_rows.jsonl").open("x", encoding="utf-8") as stream:
            for index, row in rows:
                stream.write(json.dumps({"row_index": index, "row": row, "gold": gold(row["char"], row["font"], row["ids"])}, ensure_ascii=False) + "\n")
    model = GlyphIDS(len(vocab), payload["args"]["encoder"], max_len=max_len, pretrained=False).cuda()
    model.load_state_dict(payload["model"])
    dataset = Rows(train, train_images, vocab, renderer, args.render, args.seed, args.augment)
    loader_rng = torch.Generator().manual_seed(derived_seed(args.seed, "loader"))
    loader = DataLoader(dataset, batch_size=args.batch_size, shuffle=True, collate_fn=collate,
                        drop_last=False, num_workers=0, generator=loader_rng)
    optimizer = make_optimizer(model, args.encoder_lr, args.decoder_lr)
    steps = update_count(len(loader), args.accumulation_steps, args.epochs)
    scheduler = make_scheduler(optimizer, steps)
    with (args.out_dir / "metrics.jsonl").open("x", encoding="utf-8") as metrics:
        initial = {"epoch": 0, "train_rows": 0, "train_tokens": 0, "train_updates": 0}
        initial.update(evaluate_conditions(model, val, val_images, vocab, renderer, args.eval_batch_size, args.out_dir, 0))
        metrics.write(json.dumps(initial, ensure_ascii=False) + "\n")
        metrics.flush()
        for epoch in range(args.epochs):
            dataset.epoch = epoch
            training = train_epoch(model, loader, optimizer, scheduler, args.accumulation_steps, "cuda")
            checkpoint = args.out_dir / f"epoch_{epoch + 1}.pt"
            with checkpoint.open("xb") as stream:
                torch.save({"model": model.state_dict(), "itos": vocab.itos, "args": payload["args"]}, stream)
            results = {"epoch": epoch + 1, **training,
                       "checkpoint": checkpoint.name, "checkpoint_sha256": sha256_file(checkpoint)}
            results.update(evaluate_conditions(model, val, val_images, vocab, renderer, args.eval_batch_size, args.out_dir, epoch + 1))
            metrics.write(json.dumps(results, ensure_ascii=False) + "\n")
            metrics.flush()
    artifacts = sorted(path for path in args.out_dir.iterdir() if path.is_file())
    (args.out_dir / "artifacts.json").write_text(
        json.dumps({path.name: sha256_file(path) for path in artifacts}, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
