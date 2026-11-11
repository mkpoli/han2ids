import hashlib
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from benchmark.legacy import export_dataset, import_predictions, publish


def write_rows(path, rows):
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def read_rows(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


@pytest.fixture
def source(tmp_path):
    rows = [{"char": "丐", "font": "noto", "ids": "⿱一㇉", "split": "test"},
            {"char": "丐", "font": "ipamj", "ids": "⿱一㇉", "split": "test"},
            {"char": "木", "font": "jigmo", "ids": "木", "split": "test"}]
    pixels = np.arange(3 * 4 * 5, dtype=np.uint8).reshape(3, 4, 5)
    manifest, array = tmp_path / "source.jsonl", tmp_path / "source.npy"
    write_rows(manifest, rows)
    np.save(array, pixels)
    return manifest, array, rows, pixels


def test_export_exact_pixels_and_separate_references(tmp_path, source):
    manifest, array, rows, pixels = source
    first, second = tmp_path / "dataset1", tmp_path / "dataset2"
    export_dataset(manifest, array, first)
    export_dataset(manifest, array, second)
    for name in ("inputs.jsonl", "references.jsonl", "dataset.json"):
        assert (first / name).read_bytes() == (second / name).read_bytes()
    inputs, refs = read_rows(first / "inputs.jsonl"), read_rows(first / "references.jsonl")
    meta = json.loads((first / "dataset.json").read_text())
    assert meta["source_manifest"]["sha256"] == hashlib.sha256(manifest.read_bytes()).hexdigest()
    assert meta["source_array"]["sha256"] == hashlib.sha256(array.read_bytes()).hexdigest()
    assert "unknown" in meta["font_provenance"]
    assert len({row["sample_id"] for row in inputs}) == len(rows)
    for i, (inp, ref) in enumerate(zip(inputs, refs)):
        assert set(inp) == {"sample_id", "image", "image_sha256"}
        assert inp["sample_id"] == ref["sample_id"]
        assert inp["image"] == f"images/{inp['sample_id']}.png"
        assert ref["source"] == rows[i] and ref["source_row"] == i
        assert ref["review_status"] == "unreviewed"
        assert "font_sha256" not in ref and "face_index" not in ref
        path = first / inp["image"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == inp["image_sha256"]
        assert (second / inp["image"]).read_bytes() == path.read_bytes()
        with Image.open(path) as image:
            assert image.mode == "L"
            assert np.array_equal(np.asarray(image), pixels[i])
        assert ref["original_pixels_sha256"] == hashlib.sha256(pixels[i].tobytes()).hexdigest()
    with pytest.raises(FileExistsError):
        export_dataset(manifest, array, first)


def test_export_checks_count_dtype_and_duplicate_keys(tmp_path, source):
    manifest, array, rows, pixels = source
    out = tmp_path / "out"
    for data in (pixels[:-1], pixels.astype(np.float32), pixels.reshape(3, 20)):
        np.save(array, data)
        with pytest.raises(ValueError, match="uint8"):
            export_dataset(manifest, array, out)
        assert not out.exists()
    np.save(array, pixels)
    write_rows(manifest, rows + [rows[0]])
    with pytest.raises(ValueError, match="duplicate"):
        export_dataset(manifest, array, out)
    assert not out.exists()


def test_export_atomic_failure_and_no_replace(tmp_path, source, monkeypatch):
    manifest, array, _, _ = source
    out = tmp_path / "out"
    def fail(*args, **kwargs):
        raise RuntimeError("save failed")
    monkeypatch.setattr(Image.Image, "save", fail)
    with pytest.raises(RuntimeError, match="save failed"):
        export_dataset(manifest, array, out)
    assert not out.exists()
    assert not list(tmp_path.glob(".legacy-dataset-*"))
    staged, target = tmp_path / "stage", tmp_path / "existing"
    staged.mkdir(); target.mkdir()
    (target / "keep").write_text("original")
    with pytest.raises(FileExistsError):
        publish(staged, target)
    assert (target / "keep").read_text() == "original" and staged.is_dir()


def historical(rows):
    return [{"char": row["char"], "font": row["font"], "ids": row["ids"],
             "pred": f"p{i}", "candidates": [{"text": f"p{i}", "score": 0.8},
                                                  {"text": f"q{i}", "score": 0.2}],
             "seconds": 1.0, "device": "cuda:0"} for i, row in enumerate(rows)]


def test_import_joins_unordered_and_preserves_candidates(tmp_path, source):
    manifest, array, rows, _ = source
    dataset = tmp_path / "dataset"
    export_dataset(manifest, array, dataset)
    history = historical(rows)
    original = tmp_path / "predictions.jsonl"
    write_rows(original, list(reversed(history)))
    out = tmp_path / "run"
    import_predictions(dataset / "references.jsonl", original, out)
    refs, results = read_rows(dataset / "references.jsonl"), read_rows(out / "predictions.jsonl")
    for i, record in enumerate(results):
        assert record["sample_id"] == refs[i]["sample_id"]
        assert record["status"] == "ok" and record["error"] is None and record["execution"] is None
        assert record["candidates"] == [{**c, "rank": j} for j, c in enumerate(history[i]["candidates"], 1)]
        assert record["historical_output"]["pred"] == history[i]["pred"]
        assert not {"ids", "char", "font"} & record["historical_output"].keys()
    meta = json.loads((out / "run.json").read_text())
    assert meta["producer"] == "unknown" and meta["fresh_inference"] is False
    assert meta["run_kind"] == "reused_historical_outputs"
    assert meta["historical_predictions_sha256"] == hashlib.sha256(original.read_bytes()).hexdigest()
    assert meta["manifest_sha256"] == hashlib.sha256((dataset / "inputs.jsonl").read_bytes()).hexdigest()


def test_import_rejects_input_reference_id_mismatch(tmp_path, source):
    manifest, array, rows, _ = source
    dataset = tmp_path / "dataset"
    export_dataset(manifest, array, dataset)
    predictions = tmp_path / "predictions.jsonl"
    write_rows(predictions, historical(rows))
    inputs = read_rows(dataset / "inputs.jsonl")
    inputs[0]["sample_id"] = "wrong-id"
    write_rows(dataset / "inputs.jsonl", inputs)
    with pytest.raises(ValueError, match="sample_id sets differ"):
        import_predictions(dataset / "references.jsonl", predictions, tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_import_single_predictions_and_reject_bad_joins(tmp_path, source):
    manifest, array, rows, _ = source
    dataset = tmp_path / "dataset"
    export_dataset(manifest, array, dataset)
    refpath = dataset / "references.jsonl"
    predictions = tmp_path / "legacy.jsonl"
    history = [{"char": row["char"], "font": row["font"], "ids": row["ids"],
                "pred_tta": f"chosen{i}", "pred_em": f"other{i}"} for i, row in enumerate(rows)]
    write_rows(predictions, history)
    out = tmp_path / "out"
    import_predictions(refpath, predictions, out, "pred_tta")
    records = read_rows(out / "predictions.jsonl")
    assert [r["candidates"][0]["text"] for r in records] == ["chosen0", "chosen1", "chosen2"]
    assert records[0]["historical_output"]["pred_em"] == "other0"
    bad = tmp_path / "bad.jsonl"
    for broken, expected in [(history[:-1], "match reference keys"),
                             (history + [history[0]], "duplicate"),
                             ([{**history[0], "ids": "wrong"}] + history[1:], "ids mismatch"),
                             ([{**history[0], "font": "other"}] + history[1:], "match reference keys")]:
        write_rows(bad, broken)
        with pytest.raises(ValueError, match=expected):
            import_predictions(refpath, bad, tmp_path / "badout", "pred_tta")
        assert not (tmp_path / "badout").exists()
    with pytest.raises(ValueError, match="missing string"):
        import_predictions(refpath, predictions, tmp_path / "badout", "does_not_exist")


def test_cli_subcommands(tmp_path, source):
    manifest, array, rows, _ = source
    dataset, run = tmp_path / "dataset", tmp_path / "run"
    subprocess.run([sys.executable, "-m", "benchmark.legacy", "dataset", "--manifest", str(manifest),
                    "--array", str(array), "--out", str(dataset)], check=True)
    prediction_file = tmp_path / "predictions.jsonl"
    write_rows(prediction_file, historical(rows))
    subprocess.run([sys.executable, "-m", "benchmark.legacy", "import", "--references", str(dataset / "references.jsonl"),
                    "--predictions", str(prediction_file), "--out", str(run)], check=True)
    assert len(read_rows(run / "predictions.jsonl")) == 3
