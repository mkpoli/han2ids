import hashlib
import json
import subprocess
import sys

import numpy as np
import pytest
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTCollection, TTFont
from PIL import Image, ImageDraw, ImageFont

from benchmark.render import RenderError
from benchmark.verify_legacy import verify


def make_font(path, char, name):
    builder = FontBuilder(1000, isTTF=True)
    builder.setupGlyphOrder([".notdef", "shape"])
    builder.setupCharacterMap({ord(char): "shape"})
    pen = TTGlyphPen(None)
    pen.moveTo((100, -450)); pen.lineTo((350, -450)); pen.lineTo((350, 900)); pen.lineTo((100, 900)); pen.closePath()
    empty = TTGlyphPen(None).glyph()
    builder.setupGlyf({".notdef": empty, "shape": pen.glyph()})
    builder.setupHorizontalMetrics({".notdef": (600, 0), "shape": (600, 0)})
    builder.setupHorizontalHeader(ascent=1000, descent=-500)
    builder.setupNameTable({"familyName": name, "styleName": "Regular", "fullName": name + " Regular",
                            "psName": name + "-Regular", "uniqueFontIdentifier": name})
    builder.setupOS2(sTypoAscender=1000, sTypoDescender=-500, usWinAscent=1000, usWinDescent=500)
    builder.setupPost()
    builder.setupMaxp()
    builder.save(path)


def independent_render(path, index, char):
    font = ImageFont.truetype(str(path), size=224, index=index)
    image = Image.new("L", (320, 320), 255)
    ImageDraw.Draw(image).text((160, 176), char, font=font, fill=0, anchor="ms")
    return np.array(image.crop((60, 0, 260, 200)).resize((224, 224), Image.Resampling.LANCZOS))


@pytest.fixture
def data(tmp_path):
    first, second, ttc = tmp_path / "first.ttf", tmp_path / "second.ttf", tmp_path / "fonts.ttc"
    make_font(first, "A", "First")
    make_font(second, "B", "Second")
    collection = TTCollection()
    collection.fonts = [TTFont(first), TTFont(second)]
    collection.save(ttc)
    for font in collection.fonts:
        font.close()
    rows = [{"char": "A", "font": "jigmo", "ids": "一"}, {"char": "B", "font": "jigmo", "ids": "二"}]
    manifest = tmp_path / "source.jsonl"
    manifest.write_text("".join(json.dumps(row) + "\n" for row in rows))
    array = tmp_path / "source.npy"
    original = np.stack([independent_render(ttc, 0, "A"), independent_render(ttc, 1, "B")])
    original[1, 0, 0] = 0  # the independently rendered white pixel is 255
    np.save(array, original)
    return manifest, array, ttc


def test_exact_pixel_comparison_and_font_faces(tmp_path, data):
    manifest, array, ttc = data
    out = tmp_path / "report"
    verify(manifest, array, out, [("jigmo", 0, ttc), ("jigmo", 1, ttc)])
    records = [json.loads(x) for x in (out / "rows.jsonl").read_text().splitlines()]
    summary = json.loads((out / "summary.json").read_text())
    assert [r["source_row"] for r in records] == [0, 1]
    assert [r["face_index"] for r in records] == [0, 1]
    assert [r["exact_match"] for r in records] == [True, False]
    assert records[1]["differing_pixels"] == 1 and records[1]["max_abs_difference"] == 255
    assert records[0]["original_pixels_sha256"] == records[0]["rerendered_pixels_sha256"]
    assert records[1]["original_pixels_sha256"] != records[1]["rerendered_pixels_sha256"]
    assert summary["exact_rows"] == 1 and summary["different_rows"] == 1
    assert summary["differing_pixels"] == 1 and summary["max_abs_difference"] == 255
    assert summary["source_manifest"]["sha256"] == hashlib.sha256(manifest.read_bytes()).hexdigest()
    assert summary["source_array"]["sha256"] == hashlib.sha256(array.read_bytes()).hexdigest()
    assert summary["font_candidates"][1]["sha256"] == hashlib.sha256(ttc.read_bytes()).hexdigest()
    assert summary["rows_sha256"] == hashlib.sha256((out / "rows.jsonl").read_bytes()).hexdigest()
    with pytest.raises(FileExistsError):
        verify(manifest, array, out, [("jigmo", 0, ttc), ("jigmo", 1, ttc)])


def test_rejects_invalid_shape_dtype_and_missing_coverage(tmp_path, data):
    manifest, array, ttc = data
    out = tmp_path / "report"
    original = np.load(array)
    for invalid in (original[:1], original.astype(np.int16), np.zeros((2, 2, 2), dtype=np.uint8)):
        np.save(array, invalid)
        with pytest.raises(ValueError, match="uint8"):
            verify(manifest, array, out, [("jigmo", 0, ttc)])
        assert not out.exists()
    np.save(array, original)
    with pytest.raises(RenderError, match="source row 1"):
        verify(manifest, array, out, [("jigmo", 0, ttc)])
    assert not out.exists()
    with pytest.raises(Exception):
        verify(manifest, array, out, [("jigmo", 4, ttc)])
    assert not out.exists()
    assert not list(tmp_path.glob(".verify-legacy-*"))


def test_cli_with_small_dataset(tmp_path, data):
    manifest, array, ttc = data
    out = tmp_path / "report"
    subprocess.run([sys.executable, "-m", "benchmark.verify_legacy", "--manifest", str(manifest),
                    "--array", str(array), "--out", str(out), "--font", f"jigmo=0={ttc}",
                    "--font", f"jigmo=1={ttc}"], check=True)
    assert json.loads((out / "summary.json").read_text())["exact_rows"] == 1
