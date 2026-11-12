#!/usr/bin/env python3
"""Run an IDS adapter on an input-only image manifest.

Input: DATASET/inputs.jsonl, one {sample_id, image, image_sha256} object per
line. Image paths are relative to DATASET. No reference file is read.
Output: a new directory containing predictions.jsonl and run.json. Predictions
have sample_id, status, candidates, error, and execution. Candidate order is
the adapter's order; rank 1 is the only top-1 prediction, including beam runs.
This runner records no timings and is not a performance benchmark.

The default greedy mode calls the shipped CLI reader. ``greedy-batched`` is a
separate configuration requiring ``--no-tta``: it batches the same shipped
em-box preprocessing and constrained greedy decoder. Its returned confidences
can differ from single-image decoding because the shipped decoder accumulates
extra EOS probabilities for finished batch rows; do not compare those scores.
``--cuda-memory-fraction`` limits PyTorch CUDA allocator memory in this process only, not total GPU memory
or allocations by other libraries or processes. Use trusted checkpoints only.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import io
import json
import platform
import re
import sys
from pathlib import Path

SHA256 = re.compile(r"[0-9a-fA-F]{64}\Z")
ROOT = Path(__file__).resolve().parents[1]


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_manifest(dataset: Path) -> list[dict]:
    rows = []
    seen = set()
    with (dataset / "inputs.jsonl").open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSON at line {line_number}: {exc.msg}") from exc
            if not isinstance(row, dict) or set(row) != {"sample_id", "image", "image_sha256"}:
                raise ValueError(f"line {line_number}: expected only sample_id, image, image_sha256")
            if not isinstance(row["sample_id"], str) or not row["sample_id"]:
                raise ValueError(f"line {line_number}: invalid sample_id")
            if row["sample_id"] in seen:
                raise ValueError(f"line {line_number}: duplicate sample_id {row['sample_id']!r}")
            seen.add(row["sample_id"])
            if not isinstance(row["image"], str) or not row["image"]:
                raise ValueError(f"line {line_number}: invalid image path")
            if not isinstance(row["image_sha256"], str) or not SHA256.fullmatch(row["image_sha256"]):
                raise ValueError(f"line {line_number}: invalid image_sha256")
            rows.append(row)
    return rows


def open_image(dataset: Path, row: dict):
    """Hash and decode the same bytes, after resolving symlinks within dataset."""
    from PIL import Image

    root = dataset.resolve()
    relative = Path(row["image"])
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("image path must stay within dataset")
    if relative.suffix.lower() not in {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp", ".gif"}:
        raise ValueError("image path must have a supported raster extension")
    path = (root / relative).resolve(strict=True)
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError("image path must be a file within dataset")
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != row["image_sha256"].lower():
        raise ValueError("image SHA-256 mismatch")
    with Image.open(io.BytesIO(data)) as image:
        image.load()
        return image.copy()


def error_text(exc: Exception) -> str:
    return f"{type(exc).__name__}: {exc}"


def versions() -> dict:
    result = {"python": platform.python_version(), "platform": platform.platform()}
    for dist in ("torch", "numpy", "Pillow", "timm", "onnxruntime"):
        try:
            result[dist] = importlib.metadata.version(dist)
        except importlib.metadata.PackageNotFoundError:
            result[dist] = None
    return result


def hash_files(paths: list[Path]) -> dict:
    return {str(path.resolve()): file_hash(path) for path in paths}


class HanAdapter:
    def __init__(self, args):
        if args.decode == "greedy-batched" and not args.no_tta:
            raise ValueError("greedy-batched requires no_tta")
        sys.path.insert(0, str(ROOT / "src"))
        import torch
        from han2ids.infer import Han2IDS, tensor, variants
        from han2ids.grammar import generate, valid_ids
        torch.set_num_threads(args.threads)
        self.torch, self.tensor, self.variants = torch, tensor, variants
        self.generate, self.valid_ids = generate, valid_ids
        # The shipped reader loads the checkpoint's own itos and args.
        # Checkpoints must be trusted: the shipped loader uses weights_only=False.
        self.reader = Han2IDS(args.checkpoint, device=None if args.device == "auto" else args.device)
        self.decode = args.decode
        self.tta = not args.no_tta

    def predict(self, images):
        if self.decode == "greedy-batched":
            # Exactly the shipped em-box variant and tensor conversion, then
            # one call to the same grammar-constrained greedy decoder.
            batch = self.torch.stack([self.tensor(self.variants(image)[0][1]) for image in images])
            tokens, confidence = self.generate(self.reader.model, batch.to(self.reader.device), self.reader.itos)
            return [[{"text": text, "score": float(confidence[i]), "variant": "em",
                      "valid": bool(self.valid_ids(text))}]
                    for i, text in enumerate(self.reader.vocab.decode(row.tolist()) for row in tokens)]
        results = []
        for image in images:
            readings = ([self.reader.read(image, tta=self.tta)] if self.decode == "greedy"
                        else self.reader.read_topk(image, k=5, tta=self.tta))
            results.append([{"text": x.ids, "score": float(x.confidence),
                             "variant": x.variant, "valid": bool(x.valid)} for x in readings])
        return results

    def execution(self):
        return {"device": str(self.reader.device), "warnings": []}


class GlyphAdapter:
    def __init__(self, args):
        # runtime inserts GlyphStudio's vendor directory before loading IDSModelRunner.
        sys.path.insert(0, str(args.app.resolve()))
        from glyphstudio.inference import IDSModelRunner
        self.reader = IDSModelRunner(args.app / "models" / "ids", threads=args.threads,
                                     preference=args.device, gpu_index=args.gpu_index)

    def predict(self, images):
        return self.reader.predict(images)

    def execution(self):
        return {"device": str(self.reader.device), "warnings": list(self.reader.warnings)}


def adapter_files(args) -> list[Path]:
    if args.system == "han2ids":
        source = ROOT / "src" / "han2ids"
        return [args.checkpoint] + [source / name for name in
                                    ("infer.py", "model.py", "grammar.py", "tokenizer.py")]
    model = args.app / "models" / "ids"
    config = json.loads((model / "inference_config.json").read_text(encoding="utf-8"))
    names = config["checkpoints"] + ["inference_config.json", config["output_policy"],
                                    "normalization.json", "vocab.json"]
    # Checkpoint names in a trusted config still must stay in the model directory.
    paths = []
    for name in names:
        path = (model / name).resolve()
        if not path.is_relative_to(model.resolve()) or not path.is_file():
            raise ValueError(f"invalid model file in config: {name}")
        paths.append(path)
    paths += [args.app / "glyphstudio" / name for name in ("inference.py", "runtime.py", "devices.py")]
    paths += sorted((args.app / "glyphstudio" / "vendor").glob("*.py"))
    return paths


def run(args, adapter_factory=None):
    dataset = args.dataset.resolve()
    rows = load_manifest(dataset)
    if args.limit is not None:
        rows = rows[:args.limit]
    output = args.output.resolve()
    if output == dataset or output.is_relative_to(dataset):
        raise ValueError("output must be outside the dataset directory")
    if args.cuda_memory_fraction is not None:
        if not isinstance(args.cuda_memory_fraction, (int, float)) or not 0 < args.cuda_memory_fraction <= 1:
            raise ValueError("CUDA memory fraction must be in (0, 1]")
        if args.device not in ("auto", "cuda"):
            raise ValueError("CUDA memory fraction requires --device auto or cuda")
    files = hash_files(adapter_files(args))
    metadata = {
        "format": "ids-inference-run-v1", "system": args.system,
        "manifest_sha256": file_hash(dataset / "inputs.jsonl"),
        "runner_sha256": file_hash(Path(__file__)), "files_sha256": files,
        "software": versions(),
        "settings": {"device_requested": args.device, "gpu_index": args.gpu_index,
                     "cuda_memory_fraction": args.cuda_memory_fraction,
                     "cuda_memory_cap_scope": "PyTorch CUDA allocator only" if args.cuda_memory_fraction is not None else None,
                     "batch_size": args.batch_size, "threads": args.threads,
                     "limit": args.limit, "decode": args.decode if args.system == "han2ids" else "shipped-ensemble-beam",
                     "tta": not args.no_tta if args.system == "han2ids" else None,
                     "score_note": ("Shipped batched decoder can accumulate extra EOS scores for finished rows; "
                                    "scores are not comparable to single-image CLI confidence"
                                    if args.system == "han2ids" and args.decode == "greedy-batched" else None),
                     "concurrency": "single-process, serial batches",
                     "timing": "not measured; this is not a speed benchmark"},
        "samples": len(rows), "initialization_error": None, "batch_failures": [],
    }
    if args.system == "glyphstudio":
        metadata["model_config"] = json.loads((args.app / "models" / "ids" / "inference_config.json").read_text(encoding="utf-8"))
    output.mkdir(parents=True, exist_ok=False)
    adapter = None
    try:
        if args.cuda_memory_fraction is not None:
            import torch
            if not torch.cuda.is_available() or args.gpu_index >= torch.cuda.device_count():
                raise RuntimeError("CUDA memory limit requested but CUDA device is unavailable")
            torch.cuda.set_per_process_memory_fraction(args.cuda_memory_fraction, args.gpu_index)
        adapter = (adapter_factory or (HanAdapter if args.system == "han2ids" else GlyphAdapter))(args)
        metadata["initial_execution"] = adapter.execution()
    except Exception as exc:
        metadata["initialization_error"] = error_text(exc)
        metadata["initial_execution"] = None

    def failure(row, exc, execution=None):
        return {"sample_id": row["sample_id"], "status": "error", "candidates": [],
                "error": error_text(exc), "execution": execution}

    def infer_one_batch(batch):
        indexes, images, records = [], [], [None] * len(batch)
        for i, row in enumerate(batch):
            try:
                image = open_image(dataset, row)
                if adapter is None:
                    image.close()
                    raise RuntimeError("adapter initialization failed: " + metadata["initialization_error"])
                indexes.append(i)
                images.append(image)
            except Exception as exc:
                records[i] = failure(row, exc, adapter.execution() if adapter else None)
        def predict_group(group_indexes, group_images):
            try:
                results = adapter.predict(group_images)
                if len(results) != len(group_images):
                    raise RuntimeError("adapter returned wrong batch length")
            except Exception as exc:
                execution = adapter.execution()
                metadata["batch_failures"].append({"sample_ids": [batch[i]["sample_id"] for i in group_indexes],
                                                   "error": error_text(exc), "execution": execution})
                if len(group_images) > 1:
                    # A single bad image must not cause other images to disappear.
                    for i, image in zip(group_indexes, group_images):
                        predict_group([i], [image])
                else:
                    records[group_indexes[0]] = failure(batch[group_indexes[0]], exc, execution)
                return
            execution = adapter.execution()
            for i, candidates in zip(group_indexes, results):
                try:
                    if not isinstance(candidates, list) or not candidates:
                        raise ValueError("adapter returned no candidates")
                    ranked = []
                    for rank, item in enumerate(candidates, 1):
                        if not isinstance(item, dict) or not isinstance(item.get("text"), str):
                            raise ValueError("invalid adapter candidate")
                        ranked.append({**item, "rank": rank})
                    json.dumps(ranked, allow_nan=False)
                    records[i] = {"sample_id": batch[i]["sample_id"], "status": "ok",
                                  "candidates": ranked, "error": None, "execution": execution}
                except (ValueError, TypeError) as exc:
                    records[i] = failure(batch[i], exc, execution)

        if images:
            try:
                predict_group(indexes, images)
            finally:
                for image in images:
                    image.close()
        return records

    with (output / "predictions.jsonl").open("x", encoding="utf-8") as handle:
        for start in range(0, len(rows), args.batch_size):
            for record in infer_one_batch(rows[start:start + args.batch_size]):
                handle.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n")
    metadata["final_execution"] = adapter.execution() if adapter else None
    (output / "run.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return metadata


def positive(value):
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return parsed


def cuda_fraction(value):
    try:
        number = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a number in (0, 1]") from exc
    if not 0 < number <= 1:
        raise argparse.ArgumentTypeError("must be in (0, 1]")
    return number


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dataset", type=Path, required=True)
    p.add_argument("--system", choices=("han2ids", "glyphstudio"), required=True)
    p.add_argument("--checkpoint", type=Path, help="trusted han2ids checkpoint")
    p.add_argument("--app", type=Path, help="extracted GlyphStudio source root")
    p.add_argument("--output", type=Path, required=True, help="new output directory")
    p.add_argument("--device", choices=("auto", "cpu", "cuda", "mps"), default="auto")
    p.add_argument("--gpu-index", type=int, default=0)
    p.add_argument("--cuda-memory-fraction", type=cuda_fraction,
                   help="cap PyTorch's CUDA allocator on the selected GPU (0 < fraction <= 1); default uncapped")
    p.add_argument("--threads", type=positive, default=4)
    p.add_argument("--batch-size", type=positive, default=1)
    p.add_argument("--limit", type=positive)
    p.add_argument("--decode", choices=("greedy", "greedy-batched", "beam5"), default="greedy")
    p.add_argument("--no-tta", action="store_true", help="han2ids em-box only")
    return p


def main(argv=None):
    p = parser()
    args = p.parse_args(argv)
    if args.gpu_index < 0:
        p.error("--gpu-index must be nonnegative")
    if args.system == "han2ids":
        if args.checkpoint is None or args.app is not None:
            p.error("han2ids requires --checkpoint and disallows --app")
        if args.gpu_index != 0:
            p.error("han2ids accepts only --gpu-index 0")
        if args.decode == "greedy-batched" and not args.no_tta:
            p.error("--decode greedy-batched requires --no-tta")
    elif args.app is None or args.checkpoint is not None:
        p.error("glyphstudio requires --app and disallows --checkpoint")
    elif args.decode != "greedy" or args.no_tta:
        p.error("--decode and --no-tta apply only to han2ids")
    try:
        run(args)
    except (OSError, ValueError, KeyError) as exc:
        p.exit(2, f"error: {error_text(exc)}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
