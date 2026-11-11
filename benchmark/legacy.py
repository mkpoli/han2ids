"""Export original uint8 images or import historical predictions.

    python -m benchmark.legacy dataset --manifest TEST.jsonl --array TEST.npy --out DATASET
    python -m benchmark.legacy import --references DATASET/references.jsonl \
        --predictions OUTPUTS.jsonl --out RUN --prediction-field pred_tta

The export preserves original pixels and makes no claim about the original font
files. Historical prediction import joins on (char, font), not source order.
"""
from __future__ import annotations

import argparse
import ctypes
import errno
import hashlib
import json
import os
import platform
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image, __version__ as pillow_version


def hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def jsonl(path: Path) -> list[dict]:
    result = []
    with path.open(encoding="utf-8") as handle:
        for n, line in enumerate(handle, 1):
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{n}: invalid JSON") from exc
            if not isinstance(row, dict):
                raise ValueError(f"{path}:{n}: expected an object")
            result.append(row)
    if not result:
        raise ValueError(f"{path}: no rows")
    return result


def keyed(rows: list[dict], label: str) -> dict[tuple[str, str], dict]:
    index = {}
    for row in rows:
        if (not isinstance(row.get("char"), str) or len(row["char"]) != 1
                or not isinstance(row.get("font"), str) or not row["font"]
                or not isinstance(row.get("ids"), str) or not row["ids"]):
            raise ValueError(f"{label}: expected one-codepoint char and nonempty font and ids")
        key = (row["char"], row["font"])
        if key in index:
            raise ValueError(f"{label}: duplicate (char,font) {key!r}")
        index[key] = row
    return index


def publish(source: Path, destination: Path) -> None:
    """Atomically publish a staged directory without replacing any target on Linux."""
    libc = ctypes.CDLL(None, use_errno=True)
    try:
        rename = libc.renameat2
    except AttributeError as exc:
        raise RuntimeError("atomic no-replace publication requires Linux renameat2") from exc
    rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    rename.restype = ctypes.c_int
    if rename(-100, os.fsencode(source), -100, os.fsencode(destination), 1):
        error = ctypes.get_errno()
        if error == errno.EEXIST:
            raise FileExistsError(error, os.strerror(error), str(destination))
        raise OSError(error, os.strerror(error), str(destination))


def prepare_output(output: Path) -> Path:
    output = output.absolute()
    if output.exists() or output.is_symlink():
        raise FileExistsError(f"output already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    return output


def export_dataset(manifest: Path, array: Path, output: Path) -> None:
    manifest, array = manifest.resolve(strict=True), array.resolve(strict=True)
    output = prepare_output(output)
    rows = jsonl(manifest)
    keyed(rows, "source manifest")
    images = np.load(array, mmap_mode="r", allow_pickle=False)
    if (images.ndim != 3 or images.dtype != np.uint8 or len(images) != len(rows)
            or images.shape[1] == 0 or images.shape[2] == 0):
        raise ValueError("source array must be uint8 N×H×W with the same count as the full manifest")
    manifest_hash, array_hash = hash_file(manifest), hash_file(array)
    with tempfile.TemporaryDirectory(prefix=".legacy-dataset-", dir=output.parent) as temp:
        base = Path(temp)
        (base / "images").mkdir()
        with (base / "inputs.jsonl").open("w", encoding="utf-8", newline="\n") as inputs, \
             (base / "references.jsonl").open("w", encoding="utf-8", newline="\n") as refs:
            for index, row in enumerate(rows):
                sample_id = hashlib.sha256(canonical({"format": "original-array-v1", "manifest_sha256": manifest_hash,
                                                      "array_sha256": array_hash, "source_row": index})).hexdigest()
                relative = f"images/{sample_id}.png"
                pixels = np.asarray(images[index])
                Image.fromarray(pixels).save(base / relative, format="PNG", optimize=False, compress_level=9)
                inp = {"sample_id": sample_id, "image": relative, "image_sha256": hash_file(base / relative)}
                ref = {"sample_id": sample_id, "char": row["char"], "ids": row["ids"], "font": row["font"],
                       "source_row": index, "source": row, "review_status": "unreviewed",
                       "original_pixels_sha256": hashlib.sha256(pixels.tobytes(order="C")).hexdigest()}
                inputs.write(canonical(inp).decode("utf-8") + "\n")
                refs.write(canonical(ref).decode("utf-8") + "\n")
        metadata = {"format": "original-array-dataset-v1", "source_manifest": {"path": str(manifest),
                    "sha256": manifest_hash, "rows": len(rows)}, "source_array": {"path": str(array),
                    "sha256": array_hash, "dtype": str(images.dtype), "shape": list(images.shape)},
                    "inputs_sha256": hash_file(base / "inputs.jsonl"),
                    "references_sha256": hash_file(base / "references.jsonl"),
                    "font_provenance": "unknown; source manifest names font families but does not identify font files",
                    "reference_status": "unreviewed", "software": {"python": platform.python_version(),
                    "numpy": np.__version__, "pillow": pillow_version}}
        (base / "dataset.json").write_bytes(canonical(metadata) + b"\n")
        publish(base, output)


def import_predictions(references: Path, predictions: Path, output: Path,
                       prediction_field: str | None = None) -> None:
    references, predictions = references.resolve(strict=True), predictions.resolve(strict=True)
    output = prepare_output(output)
    ref_rows, pred_rows = jsonl(references), jsonl(predictions)
    input_path = references.parent / "inputs.jsonl"
    input_rows = jsonl(input_path)
    input_ids = set()
    for row in input_rows:
        if set(row) != {"sample_id", "image", "image_sha256"}:
            raise ValueError("inputs: expected only sample_id, image, image_sha256")
        sample_id = row["sample_id"]
        if not isinstance(sample_id, str) or not sample_id or sample_id in input_ids:
            raise ValueError("inputs contain invalid or duplicate sample_id")
        input_ids.add(sample_id)
    refs, preds = keyed(ref_rows, "references"), keyed(pred_rows, "historical predictions")
    if refs.keys() != preds.keys():
        missing, extra = sorted(refs.keys() - preds.keys()), sorted(preds.keys() - refs.keys())
        raise ValueError(f"historical predictions do not match reference keys: missing={missing[:10]!r} extra={extra[:10]!r}")
    ids = set()
    result = []
    for ref in ref_rows:
        key = (ref["char"], ref["font"])
        source = preds[key]
        if source["ids"] != ref["ids"]:
            raise ValueError(f"historical prediction ids mismatch for {key!r}")
        sample_id = ref.get("sample_id")
        if not isinstance(sample_id, str) or not sample_id or sample_id in ids:
            raise ValueError("references contain invalid or duplicate sample_id")
        ids.add(sample_id)
        if prediction_field:
            prediction = source.get(prediction_field)
            if not isinstance(prediction, str):
                raise ValueError(f"{key!r}: missing string prediction field {prediction_field!r}")
            candidates = [{"text": prediction, "rank": 1}]
        else:
            raw = source.get("candidates")
            if not isinstance(raw, list) or not raw:
                raise ValueError(f"{key!r}: missing nonempty candidates; specify --prediction-field")
            candidates = []
            for rank, item in enumerate(raw, 1):
                if not isinstance(item, dict) or not isinstance(item.get("text"), str):
                    raise ValueError(f"{key!r}: invalid candidate {rank}")
                if "rank" in item and (type(item["rank"]) is not int or item["rank"] != rank):
                    raise ValueError(f"{key!r}: inconsistent candidate rank {rank}")
                candidates.append({**item, "rank": rank})
            if "pred" in source and source["pred"] != candidates[0]["text"]:
                raise ValueError(f"{key!r}: pred differs from first candidate")
        # Preserve historical non-label fields; never add references to prediction input.
        historical = {k: v for k, v in source.items() if k not in {"char", "font", "ids"}}
        record = {"sample_id": sample_id, "status": "ok", "candidates": candidates,
                  "error": None, "execution": None, "historical_output": historical}
        canonical(record)  # reject non-finite numeric values
        result.append(record)
    if ids != input_ids:
        raise ValueError("input and reference sample_id sets differ")
    with tempfile.TemporaryDirectory(prefix=".legacy-import-", dir=output.parent) as temp:
        base = Path(temp)
        with (base / "predictions.jsonl").open("w", encoding="utf-8", newline="\n") as handle:
            for record in result:
                handle.write(canonical(record).decode("utf-8") + "\n")
        metadata = {"format": "ids-inference-run-v1", "run_kind": "reused_historical_outputs",
                    "producer": "unknown", "fresh_inference": False, "samples": len(result),
                    "manifest_sha256": hash_file(input_path), "reference_manifest_sha256": hash_file(references),
                    "historical_predictions_sha256": hash_file(predictions),
                    "output_predictions_sha256": hash_file(base / "predictions.jsonl"),
                    "prediction_field": prediction_field, "matching": "exact (char,font) and ids; order independent",
                    "warning": "historical producer, model, settings and image provenance are unverified"}
        (base / "run.json").write_bytes(canonical(metadata) + b"\n")
        publish(base, output)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    dataset = sub.add_parser("dataset", help="export original NPY rows losslessly")
    dataset.add_argument("--manifest", type=Path, required=True)
    dataset.add_argument("--array", type=Path, required=True)
    dataset.add_argument("--out", type=Path, required=True)
    imported = sub.add_parser("import", help="import existing full historical predictions")
    imported.add_argument("--references", type=Path, required=True)
    imported.add_argument("--predictions", type=Path, required=True)
    imported.add_argument("--out", type=Path, required=True)
    imported.add_argument("--prediction-field", help="select one prediction field instead of candidate list")
    args = parser.parse_args()
    if args.command == "dataset":
        export_dataset(args.manifest, args.array, args.out)
    else:
        import_predictions(args.references, args.predictions, args.out, args.prediction_field)


if __name__ == "__main__":
    main()
