"""Prepare and import an image-grounded human reference review.

    python -m benchmark.review export --dataset DATASET --out PACKET --characters 100 --seed 42
    python -m benchmark.review import --dataset DATASET --packet PACKET --out SCOREDATA

Edit annotations.jsonl after examining every image. Set status to reviewed, provide
preferred_ids, any distinct reviewed_references alternatives, an opaque
reviewer_id (reviewer- followed by 8-64 lowercase hex digits), reviewed_date
(YYYY-MM-DD), and provenance (image-inspection). The imported directory contains
exact input manifest bytes, new references and metadata for scoring existing runs;
it is not an image dataset. Existing source labels and reviewed alternatives are
shown, with reviewed alternatives prefilled; review is source-label-assisted
and blind to model identity. No human review is performed by this tool.
"""
from __future__ import annotations

import argparse
from datetime import date
import hashlib
import io
import json
from pathlib import Path
import random
import re
import tempfile

from PIL import Image

from .ids_evaluator import parse_ids
from .legacy import canonical, prepare_output, publish
from .subset import relative_png


FORMAT = "ids-human-review-packet-v1"
REVIEWER = re.compile(r"reviewer-[0-9a-f]{8,64}\Z")
DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}\Z")


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json(data):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    def constant(value):
        raise ValueError(f"invalid JSON constant: {value}")

    return json.loads(data, object_pairs_hook=pairs, parse_constant=constant)


def _rows(data: bytes, label: str):
    rows, lines, seen = [], [], set()
    for line in data.splitlines(keepends=True):
        row = _json(line)
        if not isinstance(row, dict):
            raise ValueError(f"{label}: expected object")
        key = row.get("sample_id")
        if not isinstance(key, str) or not key or key in seen:
            raise ValueError(f"{label}: invalid or duplicate sample_id")
        seen.add(key)
        rows.append(row)
        lines.append(line)
    if not rows:
        raise ValueError(f"{label}: no rows")
    return rows, lines


def _source(dataset: Path, expected_hashes=None):
    dataset = Path(dataset).resolve(strict=True)
    if not dataset.is_dir():
        raise ValueError("dataset must be a directory")
    for name in ("inputs.jsonl", "references.jsonl"):
        path = dataset / name
        if not path.is_file() or not path.resolve().is_relative_to(dataset):
            raise ValueError("source manifest must be inside dataset")
    inputs_bytes = (dataset / "inputs.jsonl").read_bytes()
    references_bytes = (dataset / "references.jsonl").read_bytes()
    if expected_hashes is not None and (digest(inputs_bytes), digest(references_bytes)) != expected_hashes:
        raise ValueError("source input or reference hash mismatch")
    inputs, _ = _rows(inputs_bytes, "inputs")
    refs, lines = _rows(references_bytes, "references")
    by_id = {row["sample_id"]: row for row in inputs}
    if by_id.keys() != {row["sample_id"] for row in refs}:
        raise ValueError("input and reference sample_id sets differ")
    for row in inputs:
        relative_png(row)
    for row in refs:
        if not isinstance(row.get("char"), str) or len(row["char"]) != 1:
            raise ValueError("reference char must be one Unicode code point")
        if not isinstance(row.get("ids"), str) or not row["ids"]:
            raise ValueError("reference must have a preferred IDS")
    return dataset, inputs_bytes, references_bytes, by_id, refs, lines


def _select(refs, count, seed):
    population = sorted({row["char"] for row in refs})
    if type(count) is not int or count < 1 or count > len(population):
        raise ValueError("invalid character count")
    if type(seed) is not int:
        raise ValueError("seed must be an integer")
    selected = set(random.Random(seed).sample(population, count))
    return [row for row in refs if row["char"] in selected], len(population)


def _opaque(sample_id, inputs_hash):
    return digest(canonical([FORMAT, inputs_hash, sample_id]))


def _image(dataset, row):
    relative = relative_png(row)
    source = (dataset / relative).resolve(strict=True)
    if not source.is_relative_to(dataset) or not source.is_file():
        raise ValueError("image must resolve inside dataset")
    data = source.read_bytes()
    if digest(data) != row["image_sha256"].lower():
        raise ValueError("image SHA-256 mismatch")
    with Image.open(io.BytesIO(data)) as image:
        if image.format != "PNG":
            raise ValueError("image must be PNG")
        image.verify()
    with Image.open(io.BytesIO(data)) as image:
        image.load()
    return data


def _destination(output, *sources):
    output = Path(output).absolute()
    resolved = output.resolve()
    for source in sources:
        source = Path(source).resolve(strict=True)
        if resolved == source or resolved.is_relative_to(source) or source.is_relative_to(resolved):
            raise ValueError("output and source paths overlap")
    return prepare_output(output)


def export_review(dataset: Path, output: Path, characters: int, seed: int):
    dataset, inputs, references, by_id, refs, _ = _source(dataset)
    selected, population = _select(refs, characters, seed)
    output = _destination(output, dataset)
    inputs_hash, refs_hash = digest(inputs), digest(references)
    with tempfile.TemporaryDirectory(prefix=".review-export-", dir=output.parent) as temp:
        base = Path(temp)
        (base / "images").mkdir()
        entries, annotations = [], []
        for ref in sorted(selected, key=lambda row: _opaque(row["sample_id"], inputs_hash)):
            key = _opaque(ref["sample_id"], inputs_hash)
            image = _image(dataset, by_id[ref["sample_id"]])
            image_path = f"images/{key}.png"
            (base / image_path).write_bytes(image)
            entries.append({"sample_id": key, "image": image_path, "image_sha256": digest(image)})
            alternatives = ref.get("reviewed_references", [])
            if (not isinstance(alternatives, list)
                    or (alternatives and ref.get("review_status") != "reviewed")
                    or any(not isinstance(text, str) or not text for text in alternatives)):
                raise ValueError("invalid existing reviewed references")
            annotations.append({"sample_id": key, "preferred_ids": ref["ids"],
                                "reviewed_references": alternatives, "status": "pending",
                                "reviewer_id": "", "reviewed_date": "", "provenance": ""})
        metadata = {"format": FORMAT, "source_inputs_sha256": inputs_hash,
                    "source_references_sha256": refs_hash, "seed": seed,
                    "population_characters": population, "selected_characters": characters,
                    "images": entries}
        (base / "packet.json").write_bytes(canonical(metadata) + b"\n")
        (base / "annotations.jsonl").write_bytes(b"".join(canonical(row) + b"\n" for row in annotations))
        publish(base, output)
    return metadata


def import_review(dataset: Path, packet: Path, output: Path):
    packet = Path(packet).resolve(strict=True)
    if not packet.is_dir():
        raise ValueError("packet must be a directory")
    for name in ("packet.json", "annotations.jsonl"):
        path = packet / name
        if not path.is_file() or not path.resolve().is_relative_to(packet):
            raise ValueError("packet files must be inside packet")
    metadata_bytes = (packet / "packet.json").read_bytes()
    metadata = _json(metadata_bytes)
    if not isinstance(metadata, dict) or metadata.get("format") != FORMAT:
        raise ValueError("invalid packet format")
    expected_hashes = (metadata.get("source_inputs_sha256"), metadata.get("source_references_sha256"))
    dataset, inputs, references, by_id, refs, lines = _source(dataset, expected_hashes)
    inputs_hash, refs_hash = digest(inputs), digest(references)
    selected, population = _select(refs, metadata.get("selected_characters"), metadata.get("seed"))
    if metadata.get("population_characters") != population:
        raise ValueError("population mismatch")
    mapping = {_opaque(row["sample_id"], inputs_hash): row for row in selected}
    if len(mapping) != len(selected):
        raise ValueError("opaque ID collision")
    entries = metadata.get("images")
    if not isinstance(entries, list) or len(entries) != len(mapping):
        raise ValueError("packet images do not match selected IDs")
    seen = set()
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {"sample_id", "image", "image_sha256"}:
            raise ValueError("invalid packet image entry")
        key = entry["sample_id"]
        if not isinstance(key, str) or key not in mapping or key in seen:
            raise ValueError("duplicate or unknown packet image ID")
        seen.add(key)
        if entry["image"] != f"images/{key}.png":
            raise ValueError("invalid packet image path")
        path = packet / entry["image"]
        if not path.is_file() or not path.resolve().is_relative_to(packet):
            raise ValueError("packet image must resolve inside packet")
        data = path.read_bytes()
        original = _image(dataset, by_id[mapping[key]["sample_id"]])
        if data != original or entry["image_sha256"] != digest(data):
            raise ValueError("packet image SHA-256 mismatch")
    annotations_bytes = (packet / "annotations.jsonl").read_bytes()
    annotations, _ = _rows(annotations_bytes, "annotations")
    annotated = {row["sample_id"]: row for row in annotations}
    if annotated.keys() != mapping.keys():
        raise ValueError("annotations missing or contain extra selected IDs")
    required = {"sample_id", "preferred_ids", "reviewed_references", "status", "reviewer_id", "reviewed_date", "provenance"}
    updates = {}
    for key, row in annotated.items():
        if set(row) != required or row["status"] != "reviewed":
            raise ValueError("each selected annotation must be explicitly reviewed")
        reviewer, day = row["reviewer_id"], row["reviewed_date"]
        if not isinstance(reviewer, str) or not REVIEWER.fullmatch(reviewer):
            raise ValueError("reviewer_id must be an opaque reviewer identifier")
        if not isinstance(day, str) or not DATE.fullmatch(day):
            raise ValueError("reviewed_date must be YYYY-MM-DD")
        try:
            date.fromisoformat(day)
        except ValueError as exc:
            raise ValueError("invalid reviewed_date") from exc
        if row["provenance"] != "image-inspection":
            raise ValueError("provenance must be image-inspection")
        preferred, alternatives = row["preferred_ids"], row["reviewed_references"]
        if not isinstance(preferred, str) or not isinstance(alternatives, list):
            raise ValueError("preferred IDS and reviewed alternatives list required")
        texts = [preferred, *alternatives]
        if any(not isinstance(text, str) or parse_ids(text).status != "valid" for text in texts):
            raise ValueError("all reviewed IDS strings must parse as valid")
        if len(set(texts)) != len(texts):
            raise ValueError("reviewed IDS strings must be unique")
        original = mapping[key]
        updated = {**original, "ids": preferred, "review_status": "reviewed",
                   "reviewer_id": reviewer, "reviewed_date": day, "review_provenance": row["provenance"]}
        updated.pop("reviewed_references", None)
        if alternatives:
            updated["reviewed_references"] = alternatives
        updates[original["sample_id"]] = updated
    output = _destination(output, dataset, packet)
    with tempfile.TemporaryDirectory(prefix=".review-import-", dir=output.parent) as temp:
        base = Path(temp)
        (base / "inputs.jsonl").write_bytes(inputs)
        with (base / "references.jsonl").open("wb") as out:
            for ref, original in zip(refs, lines):
                if ref["sample_id"] in updates:
                    out.write(canonical(updates[ref["sample_id"]]) + b"\n")
                else:
                    out.write(original)
                    if not original.endswith((b"\n", b"\r")):
                        out.write(b"\n")
        result = {"format": "ids-human-review-import-v1", "source_inputs_sha256": inputs_hash,
                  "source_references_sha256": refs_hash, "packet_sha256": digest(metadata_bytes),
                  "annotations_sha256": digest(annotations_bytes), "seed": metadata["seed"],
                  "selected_characters": metadata["selected_characters"], "reviewed_samples": len(updates),
                  "references_sha256": digest((base / "references.jsonl").read_bytes())}
        (base / "review.json").write_bytes(canonical(result) + b"\n")
        publish(base, output)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    exp = sub.add_parser("export")
    exp.add_argument("--dataset", type=Path, required=True)
    exp.add_argument("--out", type=Path, required=True)
    exp.add_argument("--characters", type=int, required=True)
    exp.add_argument("--seed", type=int, required=True)
    imp = sub.add_parser("import")
    imp.add_argument("--dataset", type=Path, required=True)
    imp.add_argument("--packet", type=Path, required=True)
    imp.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "export":
            export_review(args.dataset, args.out, args.characters, args.seed)
        else:
            import_review(args.dataset, args.packet, args.out)
    except (OSError, ValueError, UnicodeError) as exc:
        parser.exit(2, f"error: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
