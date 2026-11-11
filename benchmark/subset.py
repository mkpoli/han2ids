"""Sample character clusters from an existing benchmark dataset.

    python -m benchmark.subset --dataset DATASET --out NEW_DIR --characters 100 --seed 42

All rows for each selected character are retained. The subset is a sample,
not a full-dataset result. Source predictions are never read.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import platform
import random
import re
import tempfile
from pathlib import Path

from PIL import Image

from .legacy import canonical, hash_file, prepare_output, publish

SHA256 = re.compile(r"[0-9a-fA-F]{64}\Z")
RESERVED = {"inputs.jsonl", "references.jsonl", "subset.json"}


def read_manifest(path: Path) -> list[tuple[dict, str]]:
    records = []
    seen = set()
    with path.open(encoding="utf-8") as stream:
        for number, line in enumerate(stream, 1):
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{number}: invalid JSON") from exc
            if not isinstance(value, dict):
                raise ValueError(f"{path}:{number}: expected object")
            sample_id = value.get("sample_id")
            if not isinstance(sample_id, str) or not sample_id or sample_id in seen:
                raise ValueError(f"{path}:{number}: invalid or duplicate sample_id")
            seen.add(sample_id)
            records.append((value, line.rstrip("\r\n")))
    if not records:
        raise ValueError(f"{path}: no rows")
    return records


def relative_png(row: dict) -> Path:
    if set(row) != {"sample_id", "image", "image_sha256"}:
        raise ValueError("input row must contain only sample_id, image and image_sha256")
    name, digest = row["image"], row["image_sha256"]
    if not isinstance(name, str) or not name or not isinstance(digest, str) or not SHA256.fullmatch(digest):
        raise ValueError("invalid input image path or SHA-256")
    relative = Path(name)
    if (relative.is_absolute() or ".." in relative.parts or not relative.parts
            or relative.parts[0] in RESERVED or relative.suffix.lower() != ".png"):
        raise ValueError("image path must be a relative PNG path inside the dataset")
    return relative


def create_subset(dataset: Path, output: Path, characters: int, seed: int) -> None:
    dataset = dataset.resolve(strict=True)
    if output.resolve().is_relative_to(dataset):
        raise ValueError("output must be outside the source dataset")
    output = prepare_output(output)
    inputs = read_manifest(dataset / "inputs.jsonl")
    references = read_manifest(dataset / "references.jsonl")
    input_by_id = {row["sample_id"]: row for row, _ in inputs}
    reference_by_id = {row["sample_id"]: row for row, _ in references}
    if input_by_id.keys() != reference_by_id.keys():
        raise ValueError("input and reference sample_id sets differ")
    for row, _ in inputs:
        relative_png(row)
    for row, _ in references:
        if not isinstance(row.get("char"), str) or len(row["char"]) != 1:
            raise ValueError("reference char must be one Unicode code point")
    population = sorted({row["char"] for row, _ in references})
    if type(characters) is not int or characters <= 0 or characters > len(population):
        raise ValueError("characters must be positive and not exceed the character population")
    if type(seed) is not int:
        raise ValueError("seed must be an integer")
    selected = set(random.Random(seed).sample(population, characters))
    selected_ids = {row["sample_id"] for row, _ in references if row["char"] in selected}
    input_hash = hash_file(dataset / "inputs.jsonl")
    reference_hash = hash_file(dataset / "references.jsonl")
    with tempfile.TemporaryDirectory(prefix=".benchmark-subset-", dir=output.parent) as temp:
        base = Path(temp)
        with (base / "inputs.jsonl").open("w", encoding="utf-8", newline="\n") as out:
            for row, original_line in inputs:
                if row["sample_id"] not in selected_ids:
                    continue
                relative = relative_png(row)
                source = (dataset / relative).resolve(strict=True)
                if not source.is_relative_to(dataset) or not source.is_file():
                    raise ValueError("image path must resolve to a file inside the dataset")
                data = source.read_bytes()
                if hashlib.sha256(data).hexdigest() != row["image_sha256"].lower():
                    raise ValueError(f"image SHA-256 mismatch for {row['sample_id']}")
                if not data.startswith(b"\x89PNG\r\n\x1a\n"):
                    raise ValueError(f"invalid PNG signature for {row['sample_id']}")
                try:
                    with Image.open(io.BytesIO(data)) as image:
                        if image.format != "PNG":
                            raise ValueError("input image is not PNG")
                        image.verify()
                    # verify() checks chunks and CRCs but does not decompress IDAT.
                    with Image.open(io.BytesIO(data)) as image:
                        image.load()
                except (OSError, SyntaxError, ValueError) as exc:
                    raise ValueError(f"invalid PNG for {row['sample_id']}: {exc}") from exc
                destination = base / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                if destination.exists():
                    if not destination.is_file() or destination.read_bytes() != data:
                        raise ValueError("selected images have conflicting output paths")
                else:
                    destination.write_bytes(data)
                out.write(original_line + "\n")
        with (base / "references.jsonl").open("w", encoding="utf-8", newline="\n") as out:
            for row, original_line in references:
                if row["sample_id"] in selected_ids:
                    out.write(original_line + "\n")
        metadata = {"format": "character-cluster-subset-v1", "source_dataset": str(dataset),
                    "source_inputs_sha256": input_hash, "source_references_sha256": reference_hash,
                    "seed": seed, "population_characters": len(population),
                    "sampled_characters": characters, "sampled_rows": len(selected_ids),
                    "selected_sample_ids": [row["sample_id"] for row, _ in inputs if row["sample_id"] in selected_ids],
                    "sampling": "random.Random(seed).sample over sorted unique characters; retain all rows per character",
                    "scope": "sampled subset, not the full dataset",
                    "image_validation": "selected images only; exact PNG bytes and SHA-256",
                    "inputs_sha256": hash_file(base / "inputs.jsonl"),
                    "references_sha256": hash_file(base / "references.jsonl"),
                    "software": {"python": platform.python_version()}}
        (base / "subset.json").write_bytes(canonical(metadata) + b"\n")
        publish(base, output)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--characters", type=int, required=True)
    parser.add_argument("--seed", type=int, required=True)
    args = parser.parse_args()
    create_subset(args.dataset, args.out, args.characters, args.seed)


if __name__ == "__main__":
    main()
