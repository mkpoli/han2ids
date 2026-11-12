"""Compare original NPY pixels against a re-render of the v0.3 legacy crop.

Run as python -m benchmark.verify_legacy --manifest TEST.jsonl --array TEST.npy
--out NEW_DIR --font 'noto=0=/path/font.ttc' --font 'ipamj=0=/path/font.ttf'
--font 'jigmo=0=/path/Jigmo.ttf' --font 'jigmo=0=/path/Jigmo2.ttf' ...

Mappings are explicit FAMILY=FACE_INDEX=PATH in cmap coverage priority order.
This measures a re-render with the supplied files and current rendering stack;
it does not independently establish the fonts or environment used historically.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import tempfile
from pathlib import Path

import fontTools
import numpy as np
from PIL import Image, ImageDraw, ImageFont, __version__ as pillow_version, features

from .generate import parse_font
from .legacy import canonical, hash_file, jsonl, prepare_output, publish
from .render import Face, RenderError, select_face


def legacy_pixels(face: Face, char: str, font: ImageFont.FreeTypeFont) -> np.ndarray:
    """Reproduce the legacy 320 canvas, crop, and 224px Lanczos resize."""
    if len(char) != 1 or ord(char) not in face.cmap:
        raise RenderError("character is not covered by the selected face")
    canvas = Image.new("L", (320, 320), 255)
    ImageDraw.Draw(canvas).text((160, 176), char, font=font, fill=0, anchor="ms")
    return np.asarray(canvas.crop((60, 0, 260, 200)).resize((224, 224), Image.Resampling.LANCZOS))


def verify(manifest: Path, array: Path, output: Path,
           mappings: list[tuple[str, int, Path]]) -> None:
    if not mappings:
        raise ValueError("at least one explicit font mapping is required")
    manifest, array = manifest.resolve(strict=True), array.resolve(strict=True)
    output = prepare_output(output)
    rows = jsonl(manifest)
    for n, row in enumerate(rows):
        if (not isinstance(row.get("char"), str) or len(row["char"]) != 1
                or not isinstance(row.get("font"), str) or not row["font"]):
            raise ValueError(f"source row {n}: expected one-codepoint char and nonempty font")
    originals = np.load(array, mmap_mode="r", allow_pickle=False)
    if originals.dtype != np.uint8 or originals.shape != (len(rows), 224, 224):
        raise ValueError("source array must be uint8 N×224×224 and match the full manifest count")
    source_manifest_hash, source_array_hash = hash_file(manifest), hash_file(array)
    candidates: dict[str, list[Face]] = {}
    faces = []
    legacy_fonts = {}
    for family, index, path in mappings:
        face = Face.load(family, path, index)
        candidates.setdefault(family, []).append(face)
        faces.append(face.metadata())
        legacy_fonts[(face.path, face.index)] = ImageFont.truetype(str(face.path), size=224, index=face.index)
    exact_rows, changed_pixels, largest_difference = 0, 0, 0
    with tempfile.TemporaryDirectory(prefix=".verify-legacy-", dir=output.parent) as temp:
        base = Path(temp)
        with (base / "rows.jsonl").open("w", encoding="utf-8", newline="\n") as out:
            for index, row in enumerate(rows):
                try:
                    face = select_face(row["char"], candidates.get(row["font"], []))
                    font = legacy_fonts[(face.path, face.index)]
                    produced = legacy_pixels(face, row["char"], font)
                except (ValueError, RenderError) as exc:
                    raise RenderError(f"source row {index} ({row['font']}): {exc}") from exc
                original = originals[index]
                difference = np.abs(produced.astype(np.int16) - original.astype(np.int16))
                changed = int(np.count_nonzero(difference))
                maximum = int(difference.max())
                exact = changed == 0
                exact_rows += int(exact)
                changed_pixels += changed
                largest_difference = max(largest_difference, maximum)
                record = {"source_row": index, "char": row["char"], "font": row["font"],
                          "font_sha256": face.sha256, "face_index": face.index,
                          "exact_match": exact, "differing_pixels": changed,
                          "max_abs_difference": maximum,
                          "original_pixels_sha256": hashlib.sha256(original.tobytes(order="C")).hexdigest(),
                          "rerendered_pixels_sha256": hashlib.sha256(produced.tobytes(order="C")).hexdigest()}
                out.write(canonical(record).decode("utf-8") + "\n")
        summary = {"format": "legacy-pixel-verification-v1", "source_manifest": {"path": str(manifest),
                   "sha256": source_manifest_hash, "rows": len(rows)},
                   "source_array": {"path": str(array), "sha256": source_array_hash,
                                    "shape": list(originals.shape), "dtype": str(originals.dtype)},
                   "font_candidates": faces,
                   "render": {"font_size": 224, "canvas": [320, 320], "origin": [160, 176],
                              "anchor": "ms", "crop": [60, 0, 260, 200], "output_size": [224, 224],
                              "resampling": "LANCZOS", "layout_engine": "Pillow default"},
                   "software": {"python": platform.python_version(), "pillow": pillow_version,
                                "freetype": features.version_module("freetype2"),
                                "raqm": features.version_feature("raqm") if features.check_feature("raqm") else None,
                                "fonttools": fontTools.__version__, "numpy": np.__version__},
                   "exact_rows": exact_rows, "different_rows": len(rows) - exact_rows,
                   "differing_pixels": changed_pixels, "max_abs_difference": largest_difference,
                   "rows_sha256": hash_file(base / "rows.jsonl"),
                   "provenance": "Supplied font files and current software are not independently verified as historical inputs."}
        (base / "summary.json").write_bytes(canonical(summary) + b"\n")
        publish(base, output)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--array", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--font", type=parse_font, action="append", required=True,
                        help="FAMILY=FACE_INDEX=PATH; repeat in cmap priority order")
    args = parser.parse_args()
    verify(args.manifest, args.array, args.out, args.font)


if __name__ == "__main__":
    main()
