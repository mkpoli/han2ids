import hashlib
import json
import subprocess
import sys

import pytest
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen

from benchmark.style_manifest import create_manifest


def make_font(path, chars, name):
    font = FontBuilder(1000, isTTF=True)
    font.setupGlyphOrder([".notdef", "shape"])
    font.setupCharacterMap({ord(char): "shape" for char in chars})
    pen = TTGlyphPen(None)
    pen.moveTo((0, 0)); pen.lineTo((400, 0)); pen.lineTo((400, 700)); pen.lineTo((0, 700)); pen.closePath()
    font.setupGlyf({".notdef": TTGlyphPen(None).glyph(), "shape": pen.glyph()})
    font.setupHorizontalMetrics({".notdef": (600, 0), "shape": (600, 0)})
    font.setupHorizontalHeader(ascent=800, descent=-200)
    font.setupNameTable({"familyName": name, "styleName": "Regular", "fullName": name + " Regular",
                         "psName": name + "-Regular", "uniqueFontIdentifier": name})
    font.setupOS2(sTypoAscender=800, sTypoDescender=-200, usWinAscent=800, usWinDescent=200)
    font.setupPost(); font.setupMaxp(); font.save(path)


def write_rows(path, rows):
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def read_rows(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


@pytest.fixture
def data(tmp_path):
    first, second = tmp_path / "one.ttf", tmp_path / "two.ttf"
    make_font(first, "ABCD", "One")
    make_font(second, "ABC", "Two")
    rows = []
    # Reverse codepoint order to test deterministic ordering.
    for char in "DCBA":
        for font in ("noto", "ipamj", "jigmo"):
            if char == "C" and font == "jigmo":
                continue
            rows.append({"char": char, "font": font, "ids": "ids-" + char, "split": "test"})
    source = tmp_path / "input.jsonl"
    write_rows(source, rows)
    return source, rows, first, second


def test_paired_intersection_and_provenance(tmp_path, data):
    source, rows, first, second = data
    targets = [("style-b", 0, second), ("style-a", 0, first)]
    required = ["noto", "ipamj", "jigmo"]
    a, b = tmp_path / "a", tmp_path / "b"
    create_manifest(source, a, required, targets)
    create_manifest(source, b, required, targets)
    for name in ("manifest.jsonl", "metadata.json"):
        assert (a / name).read_bytes() == (b / name).read_bytes()
    output = read_rows(a / "manifest.jsonl")
    assert [(row["char"], row["font"]) for row in output] == [("A", "style-b"), ("A", "style-a"),
                                                               ("B", "style-b"), ("B", "style-a")]
    assert [row["ids"] for row in output] == ["ids-A", "ids-A", "ids-B", "ids-B"]
    for row in output:
        label = row["label_source"]
        assert label["review_status"] == "unreviewed"
        assert label["manifest_sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
        assert [rows[i]["char"] for i in label["source_rows"]] == [row["char"]] * 3
    meta = json.loads((a / "metadata.json").read_text())
    assert meta["selection"]["source_font_intersection_characters"] == 3
    assert meta["selection"]["selected_characters"] == 2
    assert meta["selection"]["output_rows"] == 4
    assert meta["target_fonts"][0]["sha256"] == hashlib.sha256(second.read_bytes()).hexdigest()
    assert meta["manifest_sha256"] == hashlib.sha256((a / "manifest.jsonl").read_bytes()).hexdigest()
    assert meta["reference_status"] == "unreviewed" and meta["model_exposure"] == "unknown"
    assert sorted(p.name for p in a.iterdir()) == ["manifest.jsonl", "metadata.json"]
    with pytest.raises(FileExistsError):
        create_manifest(source, a, required, targets)


def test_reject_conflicts_duplicates_and_empty_intersection(tmp_path, data):
    source, rows, first, second = data
    output = tmp_path / "out"
    required = ["noto", "ipamj", "jigmo"]
    targets = [("a", 0, first), ("b", 0, second)]
    conflicting = [dict(row) for row in rows]
    conflicting[1]["ids"] = "bad"
    write_rows(source, conflicting)
    with pytest.raises(ValueError, match="conflicting IDS"):
        create_manifest(source, output, required, targets)
    write_rows(source, rows + [rows[0]])
    with pytest.raises(ValueError, match="duplicate"):
        create_manifest(source, output, required, targets)
    write_rows(source, rows)
    with pytest.raises(ValueError, match="no characters"):
        create_manifest(source, output, ["missing"], targets)
    with pytest.raises(ValueError, match="unique target"):
        create_manifest(source, output, required, [("same", 0, first), ("same", 0, second)])
    with pytest.raises(ValueError, match="unique --require"):
        create_manifest(source, output, ["noto", "noto"], targets)
    assert not output.exists()
    assert not list(tmp_path.glob(".style-manifest-*"))


def test_style_manifest_cli(tmp_path, data):
    source, _, first, second = data
    out = tmp_path / "style"
    subprocess.run([sys.executable, "-m", "benchmark.style_manifest", "--manifest", str(source), "--out", str(out),
                    "--require-original-font", "noto", "--require-original-font", "ipamj",
                    "--require-original-font", "jigmo", "--font-family", f"a=0={first}",
                    "--font-family", f"b=0={second}"], check=True)
    assert len(read_rows(out / "manifest.jsonl")) == 4
