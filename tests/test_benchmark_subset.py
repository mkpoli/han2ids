import hashlib
import io
import json
import random
import subprocess
import sys
import zlib

import pytest
from PIL import Image

from benchmark.subset import create_subset


def write_rows(path, rows):
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def read_rows(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


@pytest.fixture
def dataset(tmp_path):
    root = tmp_path / "source"
    (root / "images").mkdir(parents=True)
    inputs, refs = [], []
    for i, char in enumerate("ABCD"):
        for j, font in enumerate(("one", "two", "three")):
            key = hashlib.sha256(f"sample{i}-{j}".encode()).hexdigest()
            target = f"images/{key}.png"
            buf = io.BytesIO()
            Image.new("L", (4, 4), i * 50 + j).save(buf, format="PNG")
            data = buf.getvalue()
            (root / target).write_bytes(data)
            inputs.append({"sample_id": key, "image": target, "image_sha256": hashlib.sha256(data).hexdigest()})
            refs.append({"sample_id": key, "char": char, "font": font, "ids": "gold-" + char,
                         "review_status": "unreviewed"})
    write_rows(root / "inputs.jsonl", list(reversed(inputs)))
    write_rows(root / "references.jsonl", refs)
    (root / "predictions.jsonl").mkdir()  # This utility must never read predictions.
    return root


def test_seeded_sample_retains_clusters_and_input_is_blind(tmp_path, dataset):
    a, b = tmp_path / "a", tmp_path / "b"
    create_subset(dataset, a, 2, 17)
    create_subset(dataset, b, 2, 17)
    for name in ("inputs.jsonl", "references.jsonl", "subset.json"):
        assert (a / name).read_bytes() == (b / name).read_bytes()
    inputs, refs = read_rows(a / "inputs.jsonl"), read_rows(a / "references.jsonl")
    meta = json.loads((a / "subset.json").read_text())
    expected = set(random.Random(17).sample(sorted("ABCD"), 2))
    assert {r["char"] for r in refs} == expected
    assert len(refs) == len(inputs) == 6
    for char in expected:
        assert {r["font"] for r in refs if r["char"] == char} == {"one", "two", "three"}
    assert {r["sample_id"] for r in refs} == {r["sample_id"] for r in inputs}
    source_in = {r["sample_id"]: r for r in read_rows(dataset / "inputs.jsonl")}
    source_ref = {r["sample_id"]: r for r in read_rows(dataset / "references.jsonl")}
    for row in inputs:
        assert set(row) == {"sample_id", "image", "image_sha256"}
        assert row == source_in[row["sample_id"]]
        source_path, copied_path = dataset / row["image"], a / row["image"]
        assert copied_path.read_bytes() == source_path.read_bytes()
        assert hashlib.sha256(source_path.read_bytes()).hexdigest() == row["image_sha256"]
        with Image.open(source_path) as source, Image.open(copied_path) as copied:
            source.load(); copied.load()
            assert hashlib.sha256(source.tobytes()).digest() == hashlib.sha256(copied.tobytes()).digest()
    assert all(row == source_ref[row["sample_id"]] for row in refs)
    assert meta["seed"] == 17 and meta["population_characters"] == 4
    assert meta["sampled_characters"] == 2 and meta["sampled_rows"] == 6
    assert meta["selected_sample_ids"] == [r["sample_id"] for r in inputs]
    assert meta["source_inputs_sha256"] == hashlib.sha256((dataset / "inputs.jsonl").read_bytes()).hexdigest()
    assert meta["inputs_sha256"] == hashlib.sha256((a / "inputs.jsonl").read_bytes()).hexdigest()
    assert "sampled subset" in meta["scope"]
    assert "char" not in meta and not (a / "predictions.jsonl").exists()
    with pytest.raises(FileExistsError):
        create_subset(dataset, a, 2, 17)


def test_reject_missing_or_mismatched_images(tmp_path, dataset):
    inputs = read_rows(dataset / "inputs.jsonl")
    path = dataset / inputs[0]["image"]
    data = path.read_bytes()
    path.unlink()
    with pytest.raises(FileNotFoundError):
        create_subset(dataset, tmp_path / "missing", 4, 1)
    path.write_bytes(data + b"corruption")
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        create_subset(dataset, tmp_path / "bad", 4, 1)
    assert not (tmp_path / "bad").exists() and not (tmp_path / "missing").exists()
    assert not list(tmp_path.glob(".benchmark-subset-*"))


def test_rejects_valid_crc_with_corrupt_idat(tmp_path, dataset):
    inputs_path = dataset / "inputs.jsonl"
    inputs = read_rows(inputs_path)
    path = dataset / inputs[0]["image"]
    data = bytearray(path.read_bytes())
    offset = 8
    while data[offset + 4:offset + 8] != b"IDAT":
        offset += 12 + int.from_bytes(data[offset:offset + 4], "big")
    length = int.from_bytes(data[offset:offset + 4], "big")
    data[offset + 8] = 0  # break zlib header while preserving the PNG chunk structure
    crc = zlib.crc32(data[offset + 4:offset + 8 + length])
    data[offset + 8 + length:offset + 12 + length] = crc.to_bytes(4, "big")
    # The original failure: CRC verification alone accepts this PNG.
    with Image.open(io.BytesIO(data)) as image:
        image.verify()
    with Image.open(io.BytesIO(data)) as image, pytest.raises(OSError):
        image.load()
    path.write_bytes(data)
    inputs[0]["image_sha256"] = hashlib.sha256(data).hexdigest()
    write_rows(inputs_path, inputs)
    with pytest.raises(ValueError, match="invalid PNG"):
        create_subset(dataset, tmp_path / "out", 4, 0)
    assert not (tmp_path / "out").exists()
    assert not list(tmp_path.glob(".benchmark-subset-*"))


def test_rejects_invalid_png_signature(tmp_path, dataset):
    inputs_path = dataset / "inputs.jsonl"
    inputs = read_rows(inputs_path)
    path = dataset / inputs[0]["image"]
    buf = io.BytesIO()
    Image.new("L", (4, 4)).save(buf, format="GIF")
    data = buf.getvalue()
    path.write_bytes(data)
    inputs[0]["image_sha256"] = hashlib.sha256(data).hexdigest()
    write_rows(inputs_path, inputs)
    with pytest.raises(ValueError, match="invalid PNG signature"):
        create_subset(dataset, tmp_path / "out", 4, 0)
    assert not (tmp_path / "out").exists()


def test_reject_bad_paths_and_outside_symlink(tmp_path, dataset):
    inputs_path = dataset / "inputs.jsonl"
    original = read_rows(inputs_path)
    for unsafe in ("../outside.png", "/tmp/outside.png", "inputs.jsonl/evil.png"):
        modified = [dict(row) for row in original]
        modified[0]["image"] = unsafe
        write_rows(inputs_path, modified)
        with pytest.raises(ValueError, match="inside the dataset"):
            create_subset(dataset, tmp_path / "out", 4, 0)
    outside = tmp_path / "outside.png"
    outside.write_bytes((dataset / original[0]["image"]).read_bytes())
    target = dataset / original[0]["image"]
    target.unlink(); target.symlink_to(outside)
    write_rows(inputs_path, original)
    with pytest.raises(ValueError, match="inside the dataset"):
        create_subset(dataset, tmp_path / "out", 4, 0)
    assert not (tmp_path / "out").exists()


def test_reject_duplicate_ids_missing_refs_and_invalid_sample_count(tmp_path, dataset):
    inputs_path, refs_path = dataset / "inputs.jsonl", dataset / "references.jsonl"
    inputs, refs = read_rows(inputs_path), read_rows(refs_path)
    write_rows(inputs_path, inputs + [inputs[0]])
    with pytest.raises(ValueError, match="duplicate"):
        create_subset(dataset, tmp_path / "out", 1, 0)
    write_rows(inputs_path, inputs)
    write_rows(refs_path, refs[:-1])
    with pytest.raises(ValueError, match="sample_id sets differ"):
        create_subset(dataset, tmp_path / "out", 1, 0)
    write_rows(refs_path, refs + [refs[0]])
    with pytest.raises(ValueError, match="duplicate"):
        create_subset(dataset, tmp_path / "out", 1, 0)
    write_rows(refs_path, refs)
    for count in (0, 5):
        with pytest.raises(ValueError, match="characters must be"):
            create_subset(dataset, tmp_path / "out", count, 0)
    with pytest.raises(ValueError, match="outside"):
        create_subset(dataset, dataset / "bad" / "out", 1, 0)
    assert not (dataset / "bad").exists()


def test_subset_cli(tmp_path, dataset):
    out = tmp_path / "out"
    subprocess.run([sys.executable, "-m", "benchmark.subset", "--dataset", str(dataset), "--out", str(out),
                    "--characters", "1", "--seed", "8"], check=True)
    assert len(read_rows(out / "inputs.jsonl")) == 3
