"""Build an unreviewed paired-style manifest, without rendering images.

    python -m benchmark.style_manifest --manifest TEST.jsonl --out NEW_DIR \
      --require-original-font noto --require-original-font ipamj --require-original-font jigmo \
      --font-family 'style-a=0=/path/a.ttf' --font-family 'style-b=0=/path/b.ttf'

Each target family must have one explicit face. No training exposure or glyph
identity is inferred from font coverage.
"""
from __future__ import annotations

import argparse
import platform
import tempfile
from pathlib import Path

import fontTools
from PIL import __version__ as pillow_version

from .generate import parse_font
from .legacy import canonical, hash_file, jsonl, prepare_output, publish
from .render import Face


def create_manifest(source: Path, output: Path, required_fonts: list[str],
                    target_fonts: list[tuple[str, int, Path]]) -> None:
    if not required_fonts or any(not family for family in required_fonts) or len(set(required_fonts)) != len(required_fonts):
        raise ValueError("at least one unique --require-original-font is required")
    target_names = [family for family, _, _ in target_fonts]
    if not target_names or any(not family for family in target_names) or len(set(target_names)) != len(target_names):
        raise ValueError("at least one unique target --font-family is required")
    source = source.resolve(strict=True)
    output = prepare_output(output)
    rows = jsonl(source)
    source_sha256 = hash_file(source)
    characters: dict[str, dict] = {}
    seen = set()
    for index, row in enumerate(rows):
        char, family, ids = row.get("char"), row.get("font"), row.get("ids")
        if (not isinstance(char, str) or len(char) != 1 or not isinstance(family, str)
                or not family or not isinstance(ids, str) or not ids):
            raise ValueError(f"source row {index}: invalid char, font or ids")
        if (char, family) in seen:
            raise ValueError(f"source row {index}: duplicate (char,font) {(char, family)!r}")
        seen.add((char, family))
        if char not in characters:
            characters[char] = {"ids": ids, "fonts": set(), "source_rows": []}
        info = characters[char]
        if info["ids"] != ids:
            raise ValueError(f"source row {index}: conflicting IDS for U+{ord(char):04X}")
        info["fonts"].add(family)
        info["source_rows"].append(index)
    faces = [Face.load(family, path, face_index) for family, face_index, path in target_fonts]
    required = set(required_fonts)
    original_intersection = [char for char, info in characters.items() if required <= info["fonts"]]
    selected = sorted(char for char in original_intersection if all(ord(char) in face.cmap for face in faces))
    if not selected:
        raise ValueError("no characters remain after source-font and target-cmap intersection")
    with tempfile.TemporaryDirectory(prefix=".style-manifest-", dir=output.parent) as temp:
        base = Path(temp)
        with (base / "manifest.jsonl").open("w", encoding="utf-8", newline="\n") as handle:
            for char in selected:
                info = characters[char]
                for face in faces:
                    row = {"char": char, "font": face.family, "ids": info["ids"],
                           "label_source": {"manifest_sha256": source_sha256,
                                            "source_rows": info["source_rows"], "review_status": "unreviewed"}}
                    handle.write(canonical(row).decode("utf-8") + "\n")
        metadata = {"format": "paired-style-manifest-v1", "source_manifest": {"path": str(source),
                    "sha256": source_sha256, "rows": len(rows), "characters": len(characters)},
                    "required_original_fonts": required_fonts,
                    "target_fonts": [face.metadata() for face in faces],
                    "selection": {"source_font_intersection_characters": len(original_intersection),
                                  "selected_characters": len(selected), "target_families": len(faces),
                                  "output_rows": len(selected) * len(faces),
                                  "order": "Unicode codepoint, then target font argument order"},
                    "manifest_sha256": hash_file(base / "manifest.jsonl"),
                    "reference_status": "unreviewed", "model_exposure": "unknown",
                    "coverage_note": "Cmap coverage is not glyph identity or label validation.",
                    "software": {"python": platform.python_version(), "fonttools": fontTools.__version__,
                                 "pillow": pillow_version}}
        (base / "metadata.json").write_bytes(canonical(metadata) + b"\n")
        publish(base, output)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--require-original-font", action="append", required=True,
                        help="source font family required for each character; repeat as needed")
    parser.add_argument("--font-family", type=parse_font, action="append", required=True,
                        help="target FAMILY=FACE_INDEX=PATH; repeat once per target family")
    args = parser.parse_args()
    create_manifest(args.manifest, args.out, args.require_original_font, args.font_family)


if __name__ == "__main__":
    main()
