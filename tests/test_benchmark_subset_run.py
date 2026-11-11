import hashlib
import json
import subprocess
import sys

import pytest

from benchmark.subset_run import derive


def write_rows(path, rows):
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def read_rows(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def data(tmp_path):
    full, subset, run = (tmp_path / name for name in ("full", "subset", "source-run"))
    for path in (full, subset, run):
        path.mkdir()
    inputs = [{"sample_id": f"sample-{i}", "image": f"images/{i}.png", "image_sha256": f"{i:064x}"}
              for i in range(4)]
    predictions = [
        {"sample_id": "sample-2", "status": "error", "candidates": [], "error": "failed", "execution": None},
        {"sample_id": "sample-0", "status": "ok", "candidates": [{"rank": 1, "text": "甲", "score": 0.9},
                           {"rank": 2, "text": "乙", "score": 0.2, "raw_ids": ["乙"]}], "error": None},
        {"sample_id": "sample-3", "status": "ok", "candidates": [{"rank": 1, "text": "一"}], "error": None},
        {"sample_id": "sample-1", "status": "ok", "candidates": [{"rank": 1, "text": "二"}], "error": None},
    ]
    write_rows(full / "inputs.jsonl", inputs)
    write_rows(subset / "inputs.jsonl", [inputs[0], inputs[2]])
    write_rows(run / "predictions.jsonl", predictions)
    (run / "run.json").write_text(json.dumps({"format": "ids-inference-run-v1", "system": "test",
                           "manifest_sha256": sha(full / "inputs.jsonl"), "samples": len(inputs)}))
    # The implementation must not inspect references or images.
    (full / "references.jsonl").mkdir()
    (subset / "references.jsonl").mkdir()
    return full, subset, run, inputs, predictions


def test_derive_preserves_original_ranked_rows_and_provenance(tmp_path, data):
    full, subset, source, _, predictions = data
    out, out2 = tmp_path / "out", tmp_path / "out2"
    derive(full, subset, source, out)
    derive(full, subset, source, out2)
    for filename in ("predictions.jsonl", "provenance.jsonl", "run.json"):
        assert (out / filename).read_bytes() == (out2 / filename).read_bytes()
    records = read_rows(out / "predictions.jsonl")
    assert records == [predictions[1], predictions[0]]
    source_lines = (source / "predictions.jsonl").read_text().splitlines()
    assert (out / "predictions.jsonl").read_text().splitlines() == [source_lines[1], source_lines[0]]
    metadata = json.loads((out / "run.json").read_text())
    assert metadata["derived"] and not metadata["fresh_inference"]
    assert metadata["manifest_sha256"] == sha(subset / "inputs.jsonl")
    assert metadata["source_manifest_sha256"] == sha(full / "inputs.jsonl")
    assert metadata["source_run_sha256"] == sha(source / "run.json")
    assert metadata["source_predictions_sha256"] == sha(source / "predictions.jsonl")
    assert metadata["output_predictions_sha256"] == sha(out / "predictions.jsonl")
    assert "unverified" in metadata["source_run_prediction_binding"]
    provenance = read_rows(out / "provenance.jsonl")
    assert [row["sample_id"] for row in provenance] == ["sample-0", "sample-2"]
    assert [row["source_prediction_line"] for row in provenance] == [2, 1]
    assert all(row["source_predictions_sha256"] == metadata["source_predictions_sha256"] for row in provenance)
    with pytest.raises(FileExistsError):
        derive(full, subset, source, out)


def test_subset_must_be_strict_and_identical(tmp_path, data):
    full, subset, source, inputs, _ = data
    for invalid in ([inputs[0], {**inputs[2], "image": "different.png"}],
                    [inputs[0], {**inputs[2], "image_sha256": "f" * 64}]):
        write_rows(subset / "inputs.jsonl", invalid)
        with pytest.raises(ValueError, match="differs"):
            derive(full, subset, source, tmp_path / "out")
    write_rows(subset / "inputs.jsonl", inputs)
    with pytest.raises(ValueError, match="strict subset"):
        derive(full, subset, source, tmp_path / "out")
    write_rows(subset / "inputs.jsonl", [inputs[0], {**inputs[1], "sample_id": "extra"}])
    with pytest.raises(ValueError, match="strict subset"):
        derive(full, subset, source, tmp_path / "out")
    write_rows(subset / "inputs.jsonl", [inputs[0], inputs[0]])
    with pytest.raises(ValueError, match="duplicate"):
        derive(full, subset, source, tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_source_run_binding_and_count_checks(tmp_path, data):
    full, subset, source, _, predictions = data
    meta_path = source / "run.json"
    metadata = json.loads(meta_path.read_text())
    for key, value, expected in (("manifest_sha256", "0" * 64, "manifest_sha256"),
                                 ("samples", 3, "sample count"),
                                 ("format", "other", "source run format"),
                                 ("output_predictions_sha256", "f" * 64, "output_predictions_sha256")):
        meta_path.write_text(json.dumps({**metadata, key: value}))
        with pytest.raises(ValueError, match=expected):
            derive(full, subset, source, tmp_path / "out")
    meta_path.write_text(json.dumps({**metadata, "output_predictions_sha256": sha(source / "predictions.jsonl")}))
    derive(full, subset, source, tmp_path / "good")
    assert "verified" in json.loads((tmp_path / "good" / "run.json").read_text())["source_run_prediction_binding"]
    assert not (tmp_path / "out").exists()


def test_reject_incomplete_duplicate_or_invalid_predictions(tmp_path, data):
    full, subset, source, _, predictions = data
    path = source / "predictions.jsonl"
    tests = [(predictions[:-1], "do not match"), (predictions + [predictions[0]], "duplicate"),
             ([{**predictions[0], "status": "ok"}] + predictions[1:], "no candidates"),
             ([predictions[0], {**predictions[1], "candidates": [{"text": "甲", "rank": 2}]}] + predictions[2:], "rank"),
             ([predictions[0], {**predictions[1], "candidates": [{"text": "甲", "rank": 1, "score": float('nan')}]}] + predictions[2:], "non-finite")]
    for rows, message in tests:
        write_rows(path, rows)
        with pytest.raises(ValueError, match=message):
            derive(full, subset, source, tmp_path / "out")
        assert not (tmp_path / "out").exists()
    assert not list(tmp_path.glob(".subset-run-*"))


def test_subset_run_cli(tmp_path, data):
    full, subset, source, _, _ = data
    out = tmp_path / "out"
    subprocess.run([sys.executable, "-m", "benchmark.subset_run", "--full-dataset", str(full),
                    "--subset-dataset", str(subset), "--source-run", str(source), "--out", str(out)], check=True)
    assert len(read_rows(out / "predictions.jsonl")) == 2
