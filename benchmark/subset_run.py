"""Derive a prediction run for a strict subset without running inference.

    python -m benchmark.subset_run --full-dataset FULL --subset-dataset SUBSET \
      --source-run FULL_RUN --out NEW_RUN

The source run is checked against the entire full input manifest. Only input
manifests and run artifacts are read; references and images are not needed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import re
import tempfile
from pathlib import Path

from .legacy import canonical, hash_file, prepare_output, publish

SHA256 = re.compile(r"[0-9a-fA-F]{64}\Z")


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_records(path: Path) -> tuple[bytes, list[tuple[dict, bytes]]]:
    data = path.read_bytes()
    records = []
    ids = set()
    for number, line in enumerate(data.splitlines(), 1):
        try:
            row = json.loads(line)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ValueError(f"{path}:{number}: invalid JSON") from exc
        if not isinstance(row, dict):
            raise ValueError(f"{path}:{number}: expected object")
        sample_id = row.get("sample_id")
        if not isinstance(sample_id, str) or not sample_id or sample_id in ids:
            raise ValueError(f"{path}:{number}: invalid or duplicate sample_id")
        ids.add(sample_id)
        records.append((row, line))
    if not records:
        raise ValueError(f"{path}: no rows")
    return data, records


def validate_inputs(records: list[tuple[dict, bytes]], label: str) -> dict[str, dict]:
    result = {}
    for row, _ in records:
        if set(row) != {"sample_id", "image", "image_sha256"}:
            raise ValueError(f"{label}: expected only sample_id, image and image_sha256")
        if (not isinstance(row["image"], str) or not row["image"]
                or not isinstance(row["image_sha256"], str) or not SHA256.fullmatch(row["image_sha256"])):
            raise ValueError(f"{label}: invalid image or SHA-256")
        result[row["sample_id"]] = row
    return result


def validate_prediction(row: dict) -> None:
    status, candidates = row.get("status"), row.get("candidates")
    if status not in ("ok", "error") or not isinstance(candidates, list):
        raise ValueError("prediction has invalid status or candidates")
    if status == "ok" and not candidates:
        raise ValueError("successful prediction has no candidates")
    if status == "error" and candidates:
        raise ValueError("failed prediction must have no candidates")
    for index, candidate in enumerate(candidates, 1):
        if (not isinstance(candidate, dict) or not isinstance(candidate.get("text"), str)
                or type(candidate.get("rank")) is not int or candidate["rank"] != index):
            raise ValueError("prediction has invalid candidate text or rank")
    try:
        json.dumps(row, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError("prediction contains non-finite or invalid values") from exc


def derive(full_dataset: Path, subset_dataset: Path, source_run: Path, output: Path) -> None:
    full_dataset = full_dataset.resolve(strict=True)
    subset_dataset = subset_dataset.resolve(strict=True)
    source_run = source_run.resolve(strict=True)
    destination = output.resolve()
    if any(destination.is_relative_to(root) for root in (full_dataset, subset_dataset, source_run)):
        raise ValueError("output must be outside both datasets and the source run")
    output = prepare_output(output)
    full_bytes, full_rows = read_records(full_dataset / "inputs.jsonl")
    subset_bytes, subset_rows = read_records(subset_dataset / "inputs.jsonl")
    full = validate_inputs(full_rows, "full inputs")
    subset = validate_inputs(subset_rows, "subset inputs")
    if not subset.keys() < full.keys():
        raise ValueError("subset IDs must be a nonempty strict subset of the full input IDs")
    for sample_id, row in subset.items():
        if row != full[sample_id]:
            raise ValueError(f"subset input differs from full input for {sample_id}")
    run_data = (source_run / "run.json").read_bytes()
    try:
        run_metadata = json.loads(run_data)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError("invalid source run.json") from exc
    if not isinstance(run_metadata, dict) or run_metadata.get("format") != "ids-inference-run-v1":
        raise ValueError("invalid source run format")
    full_hash = digest(full_bytes)
    if run_metadata.get("manifest_sha256") != full_hash:
        raise ValueError("source run manifest_sha256 does not match full inputs")
    if type(run_metadata.get("samples")) is not int or run_metadata["samples"] != len(full):
        raise ValueError("source run sample count does not match full inputs")
    prediction_data, predictions = read_records(source_run / "predictions.jsonl")
    prediction_hash = digest(prediction_data)
    recorded_prediction_hash = run_metadata.get("output_predictions_sha256")
    if recorded_prediction_hash is not None and recorded_prediction_hash != prediction_hash:
        raise ValueError("source run output_predictions_sha256 does not match predictions")
    if {row["sample_id"] for row, _ in predictions} != full.keys():
        raise ValueError("source predictions do not match full input IDs")
    index = {}
    for line_number, (row, line) in enumerate(predictions, 1):
        validate_prediction(row)
        index[row["sample_id"]] = (line_number, line)
    run_hash, subset_hash = digest(run_data), digest(subset_bytes)
    with tempfile.TemporaryDirectory(prefix=".subset-run-", dir=output.parent) as temp:
        base = Path(temp)
        with (base / "predictions.jsonl").open("wb") as out, (base / "provenance.jsonl").open("wb") as provenance:
            for row, _ in subset_rows:
                sample_id = row["sample_id"]
                line_number, original_line = index[sample_id]
                out.write(original_line + b"\n")
                provenance.write(canonical({"sample_id": sample_id, "source_prediction_line": line_number,
                                            "source_predictions_sha256": prediction_hash,
                                            "source_run_sha256": run_hash}) + b"\n")
        metadata = {"format": "ids-inference-run-v1", "run_kind": "derived_subset", "derived": True,
                    "fresh_inference": False, "samples": len(subset), "manifest_sha256": subset_hash,
                    "source_manifest_sha256": full_hash, "source_run_sha256": run_hash,
                    "source_predictions_sha256": prediction_hash,
                    "output_predictions_sha256": hash_file(base / "predictions.jsonl"),
                    "provenance_sha256": hash_file(base / "provenance.jsonl"),
                    "source_run": str(source_run), "source_system": run_metadata.get("system"),
                    "source_run_prediction_binding": ("verified by source output_predictions_sha256" if recorded_prediction_hash is not None
                                                       else "unverified; source run has no predictions hash"),
                    "software": {"python": platform.python_version()}}
        (base / "run.json").write_bytes(canonical(metadata) + b"\n")
        publish(base, output)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--full-dataset", type=Path, required=True)
    parser.add_argument("--subset-dataset", type=Path, required=True)
    parser.add_argument("--source-run", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    derive(args.full_dataset, args.subset_dataset, args.source_run, args.out)


if __name__ == "__main__":
    main()
