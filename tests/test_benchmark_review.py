import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import zlib

from PIL import Image
import pytest

from benchmark.review import export_review, import_review
from benchmark.score import read_jsonl, score_runs


def sha(data):
    return hashlib.sha256(data).hexdigest()


def write_rows(path, rows):
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def dataset_at(tmp_path):
    dataset = tmp_path / "dataset"
    (dataset / "images").mkdir(parents=True)
    inputs, refs = [], []
    for index, char in enumerate("明明林林休休"):
        sample_id = f"source-{index}"
        stream = io.BytesIO()
        Image.new("L", (4, 4), index * 30).save(stream, format="PNG")
        image = stream.getvalue()
        (dataset / "images" / f"{index}.png").write_bytes(image)
        inputs.append({"sample_id": sample_id, "image": f"images/{index}.png", "image_sha256": sha(image)})
        refs.append({"sample_id": sample_id, "char": char, "font": f"font{index % 2}",
                     "ids": "⿰木木", "review_status": "unreviewed", "source": {"order": index}})
    write_rows(dataset / "inputs.jsonl", inputs)
    write_rows(dataset / "references.jsonl", refs)
    return dataset, inputs, refs


def mark_reviewed(packet):
    rows = read_jsonl(packet / "annotations.jsonl")
    for row in rows:
        row.update(status="reviewed", preferred_ids="⿰木日", reviewed_references=["⿰木月"],
                   reviewer_id="reviewer-deadbeef", reviewed_date="2026-11-12", provenance="image-inspection")
    write_rows(packet / "annotations.jsonl", rows)
    return rows


def test_selection_packet_images_and_rescoring(tmp_path):
    dataset, inputs, refs = dataset_at(tmp_path)
    one, two = tmp_path / "packet1", tmp_path / "packet2"
    metadata = export_review(dataset, one, 2, 19)
    assert export_review(dataset, two, 2, 19) == metadata
    assert (one / "packet.json").read_bytes() == (two / "packet.json").read_bytes()
    assert (one / "annotations.jsonl").read_bytes() == (two / "annotations.jsonl").read_bytes()
    annotation = read_jsonl(one / "annotations.jsonl")
    assert len(annotation) == 4
    assert all(row["status"] == "pending" and row["reviewed_references"] == [] for row in annotation)
    assert set(row["sample_id"] for row in annotation).isdisjoint(row["sample_id"] for row in inputs)
    assert metadata["source_inputs_sha256"] == sha((dataset / "inputs.jsonl").read_bytes())
    assert metadata["source_references_sha256"] == sha((dataset / "references.jsonl").read_bytes())
    originals = {sha((dataset / row["image"]).read_bytes()): (dataset / row["image"]).read_bytes() for row in inputs}
    for entry in metadata["images"]:
        data = (one / entry["image"]).read_bytes()
        assert entry["image_sha256"] == sha(data)
        assert data == originals[sha(data)]
    assert "prediction" not in (one / "packet.json").read_text().lower()
    mark_reviewed(one)
    out = tmp_path / "scoring"
    import_review(dataset, one, out)
    assert (out / "inputs.jsonl").read_bytes() == (dataset / "inputs.jsonl").read_bytes()
    new_refs = read_jsonl(out / "references.jsonl")
    assert [r["sample_id"] for r in new_refs] == [r["sample_id"] for r in refs]
    selected_chars = {r["char"] for r in new_refs if r["review_status"] == "reviewed"}
    assert len(selected_chars) == 2
    for original, row in zip(refs, new_refs):
        if row["char"] in selected_chars:
            assert row["review_status"] == "reviewed"
            assert row["ids"] == "⿰木日"
            assert row["reviewed_references"] == ["⿰木月"]
            assert row["reviewer_id"] == "reviewer-deadbeef"
        else:
            assert row == original
    predictions = [{"sample_id": r["sample_id"], "status": "ok", "candidates": [{"text": "⿰木日", "rank": 1}]} for r in inputs]
    scored = score_runs(read_jsonl(out / "inputs.jsonl"), new_refs, {"run": predictions}, iterations=2)
    assert len(scored["runs"]["run"]["samples"]) == len(inputs)
    with pytest.raises(FileExistsError):
        import_review(dataset, one, out)


def test_existing_reviewed_alternatives_are_prefilled(tmp_path):
    dataset, _, refs = dataset_at(tmp_path)
    for row in refs:
        row.update(review_status="reviewed", reviewed_references=["⿰木月"])
    write_rows(dataset / "references.jsonl", refs)
    packet = tmp_path / "packet"
    export_review(dataset, packet, 1, 4)
    annotations = read_jsonl(packet / "annotations.jsonl")
    for row in annotations:
        assert row["status"] == "pending"
        assert row["reviewed_references"] == ["⿰木月"]
        row.update(status="reviewed", reviewer_id="reviewer-deadbeef",
                   reviewed_date="2026-11-12", provenance="image-inspection")
    write_rows(packet / "annotations.jsonl", annotations)
    output = tmp_path / "out"
    import_review(dataset, packet, output)
    rows = read_jsonl(output / "references.jsonl")
    assert all(row["reviewed_references"] == ["⿰木月"] for row in rows)


def test_single_preferred_reference_removes_old_alternatives(tmp_path):
    dataset, inputs, refs = dataset_at(tmp_path)
    for row in refs:
        row.update(review_status="reviewed", reviewed_references=["⿰木月"])
    write_rows(dataset / "references.jsonl", refs)
    packet = tmp_path / "packet"
    export_review(dataset, packet, 1, 4)
    rows = mark_reviewed(packet)
    for row in rows:
        row["reviewed_references"] = []
    write_rows(packet / "annotations.jsonl", rows)
    output = tmp_path / "out"
    import_review(dataset, packet, output)
    updated = read_jsonl(output / "references.jsonl")
    single = [row for row in updated if row.get("reviewer_id") == "reviewer-deadbeef"]
    assert len(single) == 2
    assert all(row["ids"] == "⿰木日" and "reviewed_references" not in row for row in single)
    assert [row for row in updated if row not in single] == [row for row in refs if row["sample_id"] not in {r["sample_id"] for r in single}]
    predictions = [{"sample_id": row["sample_id"], "status": "ok", "candidates": [{"text": "⿰木日", "rank": 1}]} for row in inputs]
    scored = score_runs(read_jsonl(output / "inputs.jsonl"), updated, {"run": predictions}, iterations=2)
    assert len(scored["runs"]["run"]["samples"]) == len(inputs)


def test_image_crc_valid_but_undecodable_is_rejected(tmp_path):
    dataset, inputs, _ = dataset_at(tmp_path)
    path = dataset / inputs[0]["image"]
    data = bytearray(path.read_bytes())
    offset = 8
    while offset < len(data):
        size = int.from_bytes(data[offset:offset + 4], "big")
        kind = data[offset + 4:offset + 8]
        if kind == b"IDAT":
            start = offset + 8
            data[start:start + size] = bytes(size)
            crc = zlib.crc32(kind + data[start:start + size])
            data[start + size:start + size + 4] = crc.to_bytes(4, "big")
            break
        offset += size + 12
    else:
        pytest.fail("test image has no IDAT")
    with Image.open(io.BytesIO(data)) as image:
        image.verify()  # PNG chunk integrity succeeds despite invalid compressed pixels.
    path.write_bytes(data)
    inputs[0]["image_sha256"] = sha(data)
    write_rows(dataset / "inputs.jsonl", inputs)
    with pytest.raises((OSError, ValueError)):
        export_review(dataset, tmp_path / "packet", 3, 0)
    assert not (tmp_path / "packet").exists()


def test_source_and_image_hash_mismatch(tmp_path):
    dataset, inputs, _ = dataset_at(tmp_path)
    packet = tmp_path / "packet"
    meta = export_review(dataset, packet, 1, 4)
    mark_reviewed(packet)
    image = packet / meta["images"][0]["image"]
    original = image.read_bytes()
    image.write_bytes(original + b"x")
    with pytest.raises(ValueError, match="image SHA-256"):
        import_review(dataset, packet, tmp_path / "out")
    image.write_bytes(original)
    reference = dataset / "references.jsonl"
    original_reference = reference.read_bytes()
    reference.write_bytes(original_reference + b" ")
    with pytest.raises(ValueError, match="hash mismatch"):
        import_review(dataset, packet, tmp_path / "out")
    assert not (tmp_path / "out").exists()
    reference.write_bytes(original_reference)
    input_path = dataset / "inputs.jsonl"
    original_inputs = input_path.read_bytes()
    input_path.write_bytes(original_inputs + b" ")
    with pytest.raises(ValueError, match="hash mismatch"):
        import_review(dataset, packet, tmp_path / "out")
    input_path.write_bytes(original_inputs)
    (dataset / inputs[0]["image"]).write_bytes(b"bad")
    with pytest.raises(ValueError, match="SHA-256"):
        export_review(dataset, tmp_path / "all", 3, 0)


@pytest.mark.parametrize("change,match", [
    (lambda rows: rows[0].update(status="pending"), "explicitly reviewed"),
    (lambda rows: rows[0].update(reviewer_id=""), "reviewer_id"),
    (lambda rows: rows[0].update(reviewer_id="Jane Doe"), "reviewer_id"),
    (lambda rows: rows[0].update(reviewed_date="2026-02-30"), "reviewed_date"),
    (lambda rows: rows[0].update(provenance=""), "provenance"),
    (lambda rows: rows[0].update(reviewed_references=None), "alternatives list"),
    (lambda rows: rows[0].update(reviewed_references=[""]), "parse"),
    (lambda rows: rows[0].update(preferred_ids="⿰木"), "parse"),
    (lambda rows: rows[0].update(reviewed_references=["?" ]), "parse"),
    (lambda rows: rows[0].update(reviewed_references=["⿰木日"]), "unique"),
    (lambda rows: rows.append(rows[0]), "duplicate"),
    (lambda rows: rows.pop(), "missing"),
    (lambda rows: rows[0].update(sample_id="unknown"), "extra"),
])
def test_incomplete_or_invalid_review_rejected(tmp_path, change, match):
    dataset, _, _ = dataset_at(tmp_path)
    packet = tmp_path / "packet"
    export_review(dataset, packet, 1, 4)
    rows = mark_reviewed(packet)
    change(rows)
    write_rows(packet / "annotations.jsonl", rows)
    with pytest.raises(ValueError, match=match):
        import_review(dataset, packet, tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_path_traversal_symlink_and_cli(tmp_path):
    dataset, inputs, _ = dataset_at(tmp_path)
    inputs[0]["image"] = "../outside.png"
    write_rows(dataset / "inputs.jsonl", inputs)
    with pytest.raises(ValueError, match="relative PNG"):
        export_review(dataset, tmp_path / "packet", 3, 0)
    inputs[0]["image"] = "images/link.png"
    (dataset / "images/link.png").symlink_to(tmp_path / "outside.png")
    (tmp_path / "outside.png").write_bytes(b"bad")
    write_rows(dataset / "inputs.jsonl", inputs)
    with pytest.raises(ValueError, match="inside dataset"):
        export_review(dataset, tmp_path / "packet", 3, 0)
    inputs[0]["image"] = "images/0.png"
    write_rows(dataset / "inputs.jsonl", inputs)
    result = subprocess.run([sys.executable, "-m", "benchmark.review", "export", "--dataset", str(dataset),
                             "--out", str(tmp_path / "packet"), "--characters", "1", "--seed", "0"],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    mark_reviewed(tmp_path / "packet")
    result = subprocess.run([sys.executable, "-m", "benchmark.review", "import", "--dataset", str(dataset),
                             "--packet", str(tmp_path / "packet"), "--out", str(tmp_path / "out")],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
