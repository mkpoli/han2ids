import hashlib
import importlib
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTCollection, TTFont
from PIL import Image, ImageDraw, ImageOps

from benchmark.generate import generate, parse_font
from benchmark.render import Face, RenderError, audit_legacy_crop, checked_crop, render, select_face


def make_font(path, codepoint=ord("A"), family="Bench"):
    fb = FontBuilder(1000, isTTF=True)
    fb.setupGlyphOrder([".notdef", "shape", "blank"])
    fb.setupCharacterMap({codepoint: "shape", ord(" "): "blank"})
    glyphs = {}
    for name in (".notdef", "shape", "blank"):
        pen = TTGlyphPen(None)
        if name == "shape":
            # Narrow ink with a long descender; not square or inside a typical em box.
            pen.moveTo((100, -500))
            pen.lineTo((400, -500))
            pen.lineTo((400, 900))
            pen.lineTo((100, 900))
            pen.closePath()
        glyphs[name] = pen.glyph()
    fb.setupGlyf(glyphs)
    fb.setupHorizontalMetrics({name: (600, 0) for name in glyphs})
    fb.setupHorizontalHeader(ascent=1000, descent=-500)
    fb.setupNameTable({"familyName": family, "styleName": "Regular", "fullName": family + " Regular",
                       "psName": family + "-Regular", "uniqueFontIdentifier": family})
    fb.setupOS2(sTypoAscender=1000, sTypoDescender=-500, usWinAscent=1000, usWinDescent=500)
    fb.setupPost()
    fb.setupMaxp()
    fb.save(path)


@pytest.fixture
def fonts(tmp_path):
    first, second = tmp_path / "first.ttf", tmp_path / "second.ttf"
    make_font(first, ord("A"), "First")
    make_font(second, ord("B"), "Second")
    collection = TTCollection()
    collection.fonts = [TTFont(first), TTFont(second)]
    collection_path = tmp_path / "faces.ttc"
    collection.save(collection_path)
    for font in collection.fonts:
        font.close()
    return first, second, collection_path


def test_render_preserves_ink_aspect_and_padding(fonts):
    face = Face.load("x", fonts[0], 0)
    picture = render(face, "A", 224, 12)
    bounds = ImageOps.invert(picture).getbbox()
    assert picture.mode == "L" and picture.size == (224, 224)
    assert bounds is not None
    x0, y0, x1, y1 = bounds
    assert min(x0, y0, 224 - x1, 224 - y1) >= 9  # Lanczos antialias tails
    assert (y1 - y0) > 3 * (x1 - x0)
    assert abs((x0 + x1) - 224) <= 2
    assert abs((y0 + y1) - 224) <= 2


@pytest.mark.parametrize("padding", [1, 2, 12])
@pytest.mark.parametrize("point", [(0, 112), (223, 112), (112, 0), (112, 223)])
def test_render_rejects_ink_on_every_output_boundary(fonts, monkeypatch, padding, point):
    renderer = importlib.import_module("benchmark.render")
    face = Face.load("x", fonts[0], 0)
    crop = Image.new("L", (224, 224), 255)
    crop.putpixel((112, 112), 0)
    crop.putpixel(point, 254)
    monkeypatch.setattr(renderer, "checked_crop", lambda canvas, box: crop)
    with pytest.raises(RenderError, match="output boundary"):
        renderer.render(face, "A", padding=padding)


def test_actual_small_padding_and_default(fonts):
    face = Face.load("x", fonts[0], 0)
    for padding in (1, 2, 12):
        try:
            picture = render(face, "A", padding=padding)
        except RenderError as exc:
            assert "output boundary" in str(exc) and padding != 12
        else:
            left, top, right, bottom = ImageOps.invert(picture).getbbox()
            assert 0 < left and 0 < top and right < 224 and bottom < 224


def test_clipping_uses_actual_oversized_ink():
    image = Image.new("L", (100, 100), 255)
    draw = ImageDraw.Draw(image)
    draw.rectangle((20, 25, 70, 80), fill=0)
    draw.point((10, 40), fill=254)  # even faint ink outside crop is clipping
    with pytest.raises(RenderError, match="outside intended crop"):
        checked_crop(image, (15, 15, 90, 90))
    assert checked_crop(image, (5, 15, 90, 90)).size == (85, 75)
    draw.point((0, 20), fill=0)
    with pytest.raises(RenderError, match="boundary"):
        checked_crop(image, (0, 0, 100, 100))
    with pytest.raises(RenderError, match="no visible ink"):
        checked_crop(Image.new("L", (30, 30), 255), (0, 0, 30, 30))


def test_legacy_crop_audits_actual_ink_outside_old_canvas(fonts):
    face = Face.load("test", fonts[0], 0)
    audit = audit_legacy_crop(face, "A")
    assert audit["outside_crop_pixels"] > 0
    assert audit["outside_crop_by_side"]["bottom"] > 0
    assert audit["total_ink_pixels"] == audit["inside_crop_pixels"] + audit["outside_crop_pixels"]
    assert sum(audit["outside_crop_by_side"].values()) == audit["outside_crop_pixels"]
    assert audit["oversized_canvas_boundary_ink"] is False


def test_cmap_explicit_faces_no_fallback(fonts):
    a = Face.load("jigmo", fonts[2], 0)
    b = Face.load("jigmo", fonts[2], 1)
    assert select_face("B", [a, b]) is b
    assert b.names["family"] == "Second"
    assert select_face("A", [a, b]) is a
    with pytest.raises(RenderError, match="covers"):
        select_face("C", [a, b])
    with pytest.raises(RenderError, match="covered"):
        render(a, "B")
    with pytest.raises(RenderError, match="one Unicode"):
        select_face("AB", [a, b])
    with pytest.raises(RenderError, match="no visible ink"):
        render(a, " ")


def test_generation_reproducible_and_labels_separate(tmp_path, fonts):
    rows = [{"char": "A", "ids": "⿱一二", "font": "jigmo", "split": "test", "extra": 42},
            {"char": "B", "ids": "⿰三四", "font": "jigmo", "split": "test"},
            {"char": "A", "ids": "⿱一二", "font": "jigmo", "split": "test", "extra": 42}]
    manifest = tmp_path / "test.jsonl"
    manifest.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    original = tmp_path / "test.npy"
    np.save(original, np.arange(3 * 6 * 6, dtype=np.uint8).reshape(3, 6, 6))
    mappings = [("jigmo", 0, fonts[2]), ("jigmo", 1, fonts[2])]
    one, two = tmp_path / "one", tmp_path / "two"
    for out in (one, two):
        generate(manifest, out, mappings, original_array=original, audit_legacy=True)
    for filename in ("inputs.jsonl", "references.jsonl", "fonts.json", "legacy-audit.jsonl"):
        assert (one / filename).read_bytes() == (two / filename).read_bytes()
    inputs = [json.loads(line) for line in (one / "inputs.jsonl").read_text().splitlines()]
    references = [json.loads(line) for line in (one / "references.jsonl").read_text().splitlines()]
    metadata = json.loads((one / "fonts.json").read_text())
    assert len({row["sample_id"] for row in inputs}) == 3
    assert [ref["source_row"] for ref in references] == [0, 1, 2]
    assert [ref["face_index"] for ref in references] == [0, 1, 0]
    assert [ref["source"] for ref in references] == rows
    assert all(ref["review_status"] == "unreviewed" for ref in references)
    assert references[1]["original_pixels_sha256"] == hashlib.sha256(np.load(original)[1].tobytes()).hexdigest()
    assert metadata["source_manifest"]["sha256"] == hashlib.sha256(manifest.read_bytes()).hexdigest()
    benchmark = Path(__file__).resolve().parents[1] / "benchmark"
    assert metadata["generator_sha256"] == hashlib.sha256((benchmark / "generate.py").read_bytes()).hexdigest()
    assert metadata["renderer_sha256"] == hashlib.sha256((benchmark / "render.py").read_bytes()).hexdigest()
    assert metadata["layout_engine"] == "Pillow BASIC"
    assert metadata["legacy_audit_layout_engine"] == "Pillow default"
    assert len(metadata["fonts"]) == 2
    for inp, ref in zip(inputs, references):
        assert set(inp) == {"sample_id", "image", "image_sha256"}
        assert inp["sample_id"] == ref["sample_id"]
        assert inp["image"] == f"images/{inp['sample_id']}.png"
        assert inp["image_sha256"] == hashlib.sha256((one / inp["image"]).read_bytes()).hexdigest()
        assert (one / inp["image"]).read_bytes() == (two / inp["image"]).read_bytes()


def test_failure_is_atomic_and_invalid_inputs_rejected(tmp_path, fonts):
    manifest = tmp_path / "source.jsonl"
    manifest.write_text(json.dumps({"char": "B", "ids": "一", "font": "noto"}) + "\n")
    output = tmp_path / "out"
    with pytest.raises(RenderError, match="source row 0"):
        generate(manifest, output, [("noto", 0, fonts[0])])
    assert not output.exists()
    with pytest.raises(ValueError, match="positive"):
        generate(manifest, output, [("noto", 0, fonts[0])], limit=0)
    np.save(tmp_path / "bad.npy", np.zeros((2, 10, 10), dtype=np.uint8))
    with pytest.raises(ValueError, match="match the full manifest"):
        generate(manifest, output, [("noto", 0, fonts[0])], original_array=tmp_path / "bad.npy")
    with pytest.raises(Exception, match="FAMILY=FACE_INDEX=PATH"):
        parse_font("bad")


def test_generation_publication_does_not_replace_racing_directory(tmp_path, fonts, monkeypatch):
    module = importlib.import_module("benchmark.generate")
    real_publish = module.publish
    manifest = tmp_path / "in.jsonl"
    manifest.write_text(json.dumps({"char": "A", "ids": "一", "font": "noto"}) + "\n")
    output = tmp_path / "out"
    inode = []

    def competing_writer(source, destination):
        destination.mkdir()
        inode.append(destination.stat().st_ino)
        real_publish(source, destination)

    monkeypatch.setattr(module, "publish", competing_writer)
    with pytest.raises(FileExistsError):
        module.generate(manifest, output, [("noto", 0, fonts[0])])
    assert output.is_dir() and output.stat().st_ino == inode[0]
    assert list(output.iterdir()) == []
    assert not list(tmp_path.glob(".benchmark-*"))


def test_cli_end_to_end(tmp_path, fonts):
    manifest = tmp_path / "in.jsonl"
    manifest.write_text(json.dumps({"char": "A", "ids": "一", "font": "noto"}) + "\n")
    output = tmp_path / "out"
    subprocess.run([sys.executable, "-m", "benchmark.generate", "--manifest", str(manifest),
                    "--out", str(output), "--font", f"noto=0={fonts[0]}", "--limit", "1"], check=True)
    assert len((output / "inputs.jsonl").read_text().splitlines()) == 1
