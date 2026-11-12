import gzip
import hashlib
import io
import json
from pathlib import Path
import struct
import subprocess
import sys
import tarfile
import zlib

from PIL import Image
import pytest

from benchmark.export import export


def sha(data):
    return hashlib.sha256(data).hexdigest()


def make_sources(tmp_path, monkeypatch):
    home = tmp_path / "private-home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    dataset = tmp_path / "dataset"
    dataset.mkdir()
    (dataset / "inputs.jsonl").write_bytes(b'{"sample_id":"1","image":"images/1.png"}\r\n')
    (dataset / "references.jsonl").write_bytes('{"sample_id":"1","ids":"⿰木木"}\n'.encode())
    (dataset / "fonts.json").write_text(json.dumps({"font": f"{home}/font.ttf", f"{home}/key": [f"prefix {home}/data"]}))
    (dataset / "image.png").write_bytes(b"image must not be copied")
    (dataset / "font.ttf").write_bytes(b"font must not be copied")
    (dataset / "chise.jsonl").write_text('{"private":true}\n')
    run = tmp_path / "run1"
    run.mkdir()
    (run / "predictions.jsonl").write_bytes(b'{"sample_id":"1", "candidates":[{"text":"X", "raw":"\\u0058"}]}\r\n')
    (run / "run.json").write_text(json.dumps({"manifest_sha256": sha((dataset / "inputs.jsonl").read_bytes()),
                                               "files_sha256": {f"{home}/model": "abc"}}))
    score = tmp_path / "score.json"
    score.write_text(json.dumps({"path": f"{home}/score", "runs": {"run1": {"accuracy": 1}},
                                 "provenance": {"inputs_sha256": sha((dataset / "inputs.jsonl").read_bytes()),
                                                "references_sha256": sha((dataset / "references.jsonl").read_bytes()),
                                                "prediction_sha256": {"run1": sha((run / "predictions.jsonl").read_bytes())}}}))
    return home, dataset, run, score


def test_determinism_hashes_privacy_and_allowlist(tmp_path, monkeypatch):
    home, dataset, run, score = make_sources(tmp_path, monkeypatch)
    out1, out2 = tmp_path / "bundle1", tmp_path / "bundle2"
    first = export(dataset, [run], [score], out1, compress_threshold=0)
    second = export(dataset, [run], [score], out2, compress_threshold=0)
    assert first == second
    assert (out1 / "bundle.json").read_bytes() == (out2 / "bundle.json").read_bytes()
    originals = {"dataset/inputs.jsonl": dataset / "inputs.jsonl",
                 "dataset/references.jsonl": dataset / "references.jsonl",
                 "runs/run1/predictions.jsonl": run / "predictions.jsonl"}
    for item in first["files"]:
        stored = (out1 / item["path"]).read_bytes()
        assert stored == (out2 / item["path"]).read_bytes()
        assert stored[4:8] == b"\0\0\0\0"
        data = gzip.decompress(stored)
        assert item["stored_sha256"] == sha(stored)
        assert item["content_sha256"] == sha(data)
        assert str(home).encode() not in data
        if item["reconstructed_path"] in originals:
            original = originals[item["reconstructed_path"]].read_bytes()
            assert data == original
            assert item["source_sha256"] == sha(original)
    fonts = json.loads(gzip.decompress((out1 / "dataset/fonts.json.gz").read_bytes()))
    assert fonts == {"font": "$HOME/font.ttf", "$HOME/key": ["prefix $HOME/data"]}
    assert json.loads(gzip.decompress((out1 / "runs/run1/run.json.gz").read_bytes()))["files_sha256"] == {"$HOME/model": "abc"}
    assert not any(p.suffix in (".png", ".ttf") or "chise" in p.name for p in out1.rglob("*"))
    assert b"Decompress" in (out1 / "bundle.json").read_bytes()


@pytest.mark.parametrize("relative", ["inputs.jsonl", "references.jsonl", "predictions.jsonl"])
@pytest.mark.parametrize("escaped", [False, True])
def test_immutable_home_paths_fail(tmp_path, monkeypatch, relative, escaped):
    home, dataset, run, score = make_sources(tmp_path, monkeypatch)
    target = (run if relative == "predictions.jsonl" else dataset) / relative
    home_text = str(home)
    if escaped:
        home_text = home_text.replace("/", "\\u002f")
    target.write_text('{"value":"' + home_text + '/secret"}\n')
    if relative == "inputs.jsonl":
        meta = json.loads((run / "run.json").read_text())
        meta["manifest_sha256"] = sha(target.read_bytes())
        (run / "run.json").write_text(json.dumps(meta))
    with pytest.raises(ValueError, match="HOME path"):
        export(dataset, [run], [], tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_duplicate_redacted_keys_rejected(tmp_path, monkeypatch):
    home, dataset, run, score = make_sources(tmp_path, monkeypatch)
    report = json.loads(score.read_text())
    report["keys"] = {f"{home}/x": 1, "$HOME/x": 2}
    score.write_text(json.dumps(report))
    with pytest.raises(ValueError, match="collide"):
        export(dataset, [run], [score], tmp_path / "out")


def test_duplicate_names_overlap_missing_and_existing(tmp_path, monkeypatch):
    _, dataset, run, score = make_sources(tmp_path, monkeypatch)
    other = tmp_path / "other" / run.name
    other.parent.mkdir()
    other.mkdir()
    with pytest.raises(ValueError, match="duplicate run"):
        export(dataset, [run, other], [], tmp_path / "out")
    other_score = other / score.name
    other_score.write_text('{}')
    with pytest.raises(ValueError, match="duplicate score"):
        export(dataset, [run], [score, other_score], tmp_path / "out")
    for dest in (dataset / "out", tmp_path / "new" / ".." / "dataset" / "out", tmp_path / "parent"):
        if dest.name == "parent":
            nested = dest / "dataset"
            nested.parent.mkdir()
            dataset.rename(nested)
            dataset = nested
        with pytest.raises(ValueError, match="overlap"):
            export(dataset, [run], [], dest)
    existing = tmp_path / "existing"
    existing.mkdir()
    (existing / "untouched").write_text("keep")
    with pytest.raises(FileExistsError):
        export(dataset, [run], [], existing)
    assert (existing / "untouched").read_text() == "keep"
    (run / "predictions.jsonl").unlink()
    with pytest.raises(ValueError, match="missing"):
        export(dataset, [run], [], tmp_path / "out")


def test_large_files_compress_by_default_and_immutable_keys_checked(tmp_path, monkeypatch):
    home, dataset, run, score = make_sources(tmp_path, monkeypatch)
    prediction = run / "predictions.jsonl"
    prediction.write_bytes(b'{"text":"' + b'x' * (1024 * 1024) + b'"}\n')
    result = export(dataset, [run], [], tmp_path / "out")
    entry = next(item for item in result["files"] if item["reconstructed_path"].endswith("predictions.jsonl"))
    assert entry["compression"] == "gzip"
    assert gzip.decompress((tmp_path / "out" / entry["path"]).read_bytes()) == prediction.read_bytes()
    prediction.write_text(json.dumps({str(home) + "/secret": 1}) + "\n")
    with pytest.raises(ValueError, match="HOME path"):
        export(dataset, [run], [], tmp_path / "out2")
    link = tmp_path / "link"
    link.symlink_to(tmp_path / "missing-output")
    with pytest.raises(FileExistsError):
        export(dataset, [run], [], link)


def test_subset_metadata_without_parent_metadata_and_no_images(tmp_path, monkeypatch):
    home, dataset, run, score = make_sources(tmp_path, monkeypatch)
    (dataset / "fonts.json").unlink()
    images = dataset / "images"
    images.mkdir()
    (images / "1.png").write_bytes(b"unique image bytes must stay private")
    subset = {"format": "character-cluster-subset-v1", "source_dataset": str(home / "source"),
              "inputs_sha256": sha((dataset / "inputs.jsonl").read_bytes()),
              "references_sha256": sha((dataset / "references.jsonl").read_bytes()),
              "selected_sample_ids": ["1"]}
    (dataset / "subset.json").write_text(json.dumps(subset))
    before_ref = (dataset / "references.jsonl").read_bytes()
    out = tmp_path / "out"
    result = export(dataset, [run], [score], out)
    bundled = json.loads((out / "dataset/subset.json").read_text())
    assert bundled == {**subset, "source_dataset": "$HOME/source"}
    assert (out / "dataset/references.jsonl").read_bytes() == before_ref
    assert (dataset / "references.jsonl").read_bytes() == before_ref
    assert not (out / "dataset/images").exists()
    assert all(b"unique image bytes must stay private" not in file.read_bytes()
               for file in out.rglob("*") if file.is_file())
    assert any(x["reconstructed_path"] == "dataset/subset.json" for x in result["files"])
    assert all(str(home).encode() not in file.read_bytes() for file in out.rglob("*") if file.is_file())


def test_all_dataset_metadata_included(tmp_path, monkeypatch):
    _, dataset, run, _ = make_sources(tmp_path, monkeypatch)
    for name in ("dataset.json", "subset.json", "review.json"):
        (dataset / name).write_text('{}')
    result = export(dataset, [run], [], tmp_path / "out")
    paths = {item["reconstructed_path"] for item in result["files"]}
    assert {"dataset/dataset.json", "dataset/fonts.json", "dataset/subset.json", "dataset/review.json"} <= paths


def test_review_metadata_only_and_prior_reference_hash(tmp_path, monkeypatch):
    home, dataset, run, score = make_sources(tmp_path, monkeypatch)
    (dataset / "fonts.json").unlink()
    (dataset / "review.json").write_text(json.dumps({"source": f"{home}/dataset"}))
    meta = json.loads((run / "run.json").read_text())
    meta["reference_manifest_sha256"] = "1" * 64
    (run / "run.json").write_text(json.dumps(meta))
    out = tmp_path / "out"
    result = export(dataset, [run], [score], out)
    assert json.loads((out / "dataset/review.json").read_text()) == {"source": "$HOME/dataset"}
    assert result["runs_with_other_reference_manifest"] == ["run1"]
    assert json.loads((out / "runs/run1/run.json").read_text())["reference_manifest_sha256"] == "1" * 64
    assert (out / "dataset/references.jsonl").read_bytes() == (dataset / "references.jsonl").read_bytes()
    # Review datasets can contain manifests without the referenced image files.
    with pytest.raises((ValueError, OSError)):
        export(dataset, [run], [], tmp_path / "images-out", include_images=True)
    assert not (tmp_path / "images-out").exists()


def test_run_manifest_hash_required(tmp_path, monkeypatch):
    _, dataset, run, score = make_sources(tmp_path, monkeypatch)
    (run / "run.json").write_text('{}')
    with pytest.raises(ValueError, match="manifest_sha256 missing"):
        export(dataset, [run], [score], tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_recorded_run_prediction_hash_must_match(tmp_path, monkeypatch):
    _, dataset, run, _ = make_sources(tmp_path, monkeypatch)
    run_meta = run / "run.json"
    meta = json.loads(run_meta.read_text())
    meta["output_predictions_sha256"] = sha((run / "predictions.jsonl").read_bytes())
    run_meta.write_text(json.dumps(meta))
    export(dataset, [run], [], tmp_path / "valid")
    (run / "predictions.jsonl").write_text('{"sample_id":"corrupted"}\n')
    with pytest.raises(ValueError, match="output_predictions_sha256 mismatch"):
        export(dataset, [run], [], tmp_path / "invalid")
    assert not (tmp_path / "invalid").exists()


def test_bad_hash_and_missing_metadata(tmp_path, monkeypatch):
    _, dataset, run, score = make_sources(tmp_path, monkeypatch)
    (dataset / "inputs.jsonl").write_text('{}\n')
    with pytest.raises(ValueError, match="manifest_sha256 mismatch"):
        export(dataset, [run], [score], tmp_path / "out")
    (dataset / "fonts.json").unlink()
    with pytest.raises(ValueError, match="metadata missing"):
        export(dataset, [run], [score], tmp_path / "out")


def make_png():
    stream = io.BytesIO()
    Image.new("RGB", (1, 1), "white").save(stream, format="PNG")
    return stream.getvalue()


PNG = make_png()


def image_sources(dataset, run, rows):
    (dataset / "inputs.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows))
    meta = json.loads((run / "run.json").read_text())
    meta["manifest_sha256"] = sha((dataset / "inputs.jsonl").read_bytes())
    (run / "run.json").write_text(json.dumps(meta))


def test_image_archive_is_deterministic_and_matches_manifest(tmp_path, monkeypatch):
    home, dataset, run, score = make_sources(tmp_path, monkeypatch)
    (dataset / "images").mkdir()
    (dataset / "images/z.png").write_bytes(PNG)
    (dataset / "images/a.png").write_bytes(PNG + b"second")
    rows = [{"sample_id": "z", "image": "images/z.png", "image_sha256": sha(PNG)},
            {"sample_id": "a", "image": "images/a.png", "image_sha256": sha(PNG + b"second")}]
    image_sources(dataset, run, rows)
    out1, out2 = tmp_path / "out1", tmp_path / "out2"
    first = export(dataset, [run], [], out1, include_images=True, compress_threshold=0)
    second = export(dataset, [run], [], out2, include_images=True, compress_threshold=0)
    assert first == second
    entry = first["image_archive"]
    archive = (out1 / entry["path"]).read_bytes()
    assert archive == (out2 / entry["path"]).read_bytes()
    assert archive[4:8] == b"\0" * 4
    assert sha(archive) == entry["stored_sha256"]
    assert entry["input_manifest_sha256"] == sha((dataset / "inputs.jsonl").read_bytes())
    assert entry["images"] == [{"path": "images/a.png", "sha256": sha(PNG + b"second")},
                               {"path": "images/z.png", "sha256": sha(PNG)}]
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tar:
        members = tar.getmembers()
        assert [m.name for m in members] == ["images/a.png", "images/z.png"]
        for member in members:
            assert member.isfile() and member.uid == member.gid == member.mtime == 0
            assert member.uname == member.gname == "" and member.mode == 0o644
            assert str(home) not in member.name
            assert tar.extractfile(member).read() == (dataset / member.name).read_bytes()
    assert (dataset / "images/z.png").read_bytes() == PNG


def test_invalid_idat_rejected_after_verify(tmp_path, monkeypatch):
    _, dataset, run, _ = make_sources(tmp_path, monkeypatch)

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    broken = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
              + chunk(b"IDAT", b"not zlib") + chunk(b"IEND", b""))
    with Image.open(io.BytesIO(broken)) as image:
        image.verify()
    with pytest.raises(OSError):
        with Image.open(io.BytesIO(broken)) as image:
            image.load()
    (dataset / "images").mkdir()
    (dataset / "images/bad.png").write_bytes(broken)
    image_sources(dataset, run, [{"sample_id": "1", "image": "images/bad.png", "image_sha256": sha(broken)}])
    with pytest.raises(ValueError, match="invalid raster image"):
        export(dataset, [run], [], tmp_path / "out", include_images=True)
    assert not (tmp_path / "out").exists()


def test_cli_image_option(tmp_path, monkeypatch):
    _, dataset, run, _ = make_sources(tmp_path, monkeypatch)
    (dataset / "images").mkdir()
    (dataset / "images/a.png").write_bytes(PNG)
    image_sources(dataset, run, [{"sample_id": "1", "image": "images/a.png", "image_sha256": sha(PNG)}])
    output = tmp_path / "out"
    result = subprocess.run([sys.executable, "-m", "benchmark.export", "--dataset", str(dataset),
                             "--run", str(run), "--output", str(output), "--include-images"],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    with tarfile.open(output / "dataset/images.tar.gz", "r:gz") as tar:
        assert tar.getnames() == ["images/a.png"]
        assert tar.extractfile("images/a.png").read() == PNG


@pytest.mark.parametrize("bad", ["duplicate", "escape", "absolute", "hash", "missing", "font", "symlink", "signature"])
def test_image_archive_rejects_invalid_manifest_or_image(tmp_path, monkeypatch, bad):
    _, dataset, run, score = make_sources(tmp_path, monkeypatch)
    (dataset / "images").mkdir()
    (dataset / "images/a.png").write_bytes(PNG)
    name, digest = "images/a.png", sha(PNG)
    if bad == "escape":
        name = "../a.png"
    elif bad == "absolute":
        name = "/outside.png"
    elif bad == "hash":
        digest = "0" * 64
    elif bad == "missing":
        name = "images/missing.png"
    elif bad == "font":
        name = "font.ttf"
    elif bad == "symlink":
        (dataset / "images/outside.png").symlink_to(score)
        name = "images/outside.png"
    elif bad == "signature":
        (dataset / "images/a.png").write_bytes(b"not a raster file")
        digest = sha(b"not a raster file")
    row = {"sample_id": "1", "image": name, "image_sha256": digest}
    image_sources(dataset, run, [row, row] if bad == "duplicate" else [row])
    with pytest.raises((ValueError, OSError)):
        export(dataset, [run], [], tmp_path / "out", include_images=True)
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize("problem", ["missing_provenance", "input", "references", "prediction", "unknown_run", "unmatched_runs"])
def test_score_provenance_rejects_unrelated_data(tmp_path, monkeypatch, problem):
    _, dataset, run, score = make_sources(tmp_path, monkeypatch)
    report = json.loads(score.read_text())
    if problem == "missing_provenance":
        del report["provenance"]
    elif problem in ("input", "references"):
        key = "inputs_sha256" if problem == "input" else "references_sha256"
        report["provenance"][key] = "0" * 64
    elif problem == "prediction":
        report["provenance"]["prediction_sha256"]["run1"] = "0" * 64
    elif problem == "unknown_run":
        report["runs"] = {"unknown": {}}
        report["provenance"]["prediction_sha256"] = {"unknown": "0" * 64}
    else:
        report["runs"]["untracked"] = {}
    score.write_text(json.dumps(report))
    with pytest.raises(ValueError, match="score"):
        export(dataset, [run], [score], tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_cli_multiple_runs_jsonl_scores_and_uncompressed(tmp_path, monkeypatch):
    home, dataset, run, score = make_sources(tmp_path, monkeypatch)
    run2 = tmp_path / "run2"
    run2.mkdir()
    for name in ("run.json", "predictions.jsonl"):
        (run2 / name).write_bytes((run / name).read_bytes())
    score2 = tmp_path / "details.jsonl"
    report = json.loads(score.read_text())
    report["path"] = f"{home}/file"
    score2.write_text(json.dumps(report) + '\n')
    output = tmp_path / "out"
    result = subprocess.run([sys.executable, "-m", "benchmark.export", "--dataset", str(dataset),
                             "--run", str(run), "--run", str(run2), "--score", str(score),
                             "--score", str(score2), "--output", str(output)],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert (output / "dataset/inputs.jsonl").read_bytes() == (dataset / "inputs.jsonl").read_bytes()
    assert (output / "runs/run2/predictions.jsonl").read_bytes() == (run2 / "predictions.jsonl").read_bytes()
    assert json.loads((output / "scores/details.jsonl").read_text())["path"] == "$HOME/file"
